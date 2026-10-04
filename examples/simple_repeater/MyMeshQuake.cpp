// Earthquake channel alerts for the Mesh America Quake Repeater. The decisions (when to send, what
// the message says) are in helpers/sensors/SeismicAlert and are tested on a PC; this file only
// supplies the repeater's facts to them and sends what they decide. See docs/earthquake-alerts.md.
#include "MyMesh.h"

#if ENV_INCLUDE_D7S

#include <helpers/AlertReporter.h>
#include <helpers/FileRead.h>
#include <helpers/AtomicFileWriter.h>
#include <helpers/ContactFileTransaction.h>
#include <string.h>
#include <stdio.h>

namespace {

const char QUAKE_PREFS_FILE[] = "/quake_prefs";
const uint8_t QUAKE_PREFS_MAGIC = 'Q';
const uint8_t QUAKE_PREFS_VERSION = 1;

const uint16_t QUAKE_COOLDOWN_MIN_DEFAULT = 10;
const uint16_t QUAKE_COOLDOWN_MIN_MAX = 1440;
const uint32_t QUAKE_JITTER_MAX_MS = 2UL * 1000;
const uint32_t QUAKE_TEST_GAP_MS = 30UL * 1000;  // a typo should not be able to flood the channel

const char* skipSpaces(const char* s) {
  while (*s == ' ') ++s;
  return s;
}

}  // namespace

void MyMesh::applyQuakePolicyConfig() {
  quake_policy.configure(uint32_t(quake_cooldown_min) * 60UL * 1000UL, QUAKE_JITTER_MAX_MS);
}

// Settings live in their own small file so the shared preferences image keeps its layout.
void MyMesh::loadQuakePrefs() {
  quake_channel[0] = 0;
  quake_cooldown_min = QUAKE_COOLDOWN_MIN_DEFAULT;
  if (_fs != NULL) {
    File file = mesh::openFileRead(_fs, QUAKE_PREFS_FILE);
    if (file) {
      uint8_t header[2];
      char channel[sizeof(quake_channel)];
      uint16_t cooldown = 0;
      const bool ok = file.size() == sizeof(header) + sizeof(channel) + sizeof(cooldown)
          && file.read(header, sizeof(header)) == sizeof(header)
          && header[0] == QUAKE_PREFS_MAGIC && header[1] == QUAKE_PREFS_VERSION
          && file.read((uint8_t*)channel, sizeof(channel)) == sizeof(channel)
          && file.read((uint8_t*)&cooldown, sizeof(cooldown)) == sizeof(cooldown);
      file.close();
      if (ok) {
        channel[sizeof(channel) - 1] = 0;
        // A damaged name must not become a channel nobody chose.
        char canonical[sizeof(quake_channel)];
        if (seismic::normalizeHashtag(channel, canonical, sizeof(canonical)) == seismic::Hashtag::Ok) {
          strcpy(quake_channel, canonical);
        }
        if (cooldown >= 1 && cooldown <= QUAKE_COOLDOWN_MIN_MAX) quake_cooldown_min = cooldown;
      }
    }
  }
  applyQuakePolicyConfig();
}

bool MyMesh::saveQuakePrefs() {
  if (_fs == NULL) return false;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  mesh::AtomicFileWriter file(_fs, QUAKE_PREFS_FILE);
#else
  mesh::ContactFileTransaction file(_fs, QUAKE_PREFS_FILE);
#endif
  if (!file) return false;
  const uint8_t header[2] = {QUAKE_PREFS_MAGIC, QUAKE_PREFS_VERSION};
  char channel[sizeof(quake_channel)] = {};
  strncpy(channel, quake_channel, sizeof(channel) - 1);
  file.write(header, sizeof(header));
  file.write((const uint8_t*)channel, sizeof(channel));
  file.write((const uint8_t*)&quake_cooldown_min, sizeof(quake_cooldown_min));
  return file.commit();
}

// "#name" -> the channel key every MeshCore client derives: the first 16 bytes of SHA-256("#name").
bool MyMesh::buildQuakeChannel(mesh::GroupChannel& channel, const char*& problem) {
  problem = NULL;
  char name[sizeof(quake_channel)];
  if (seismic::normalizeHashtag(quake_channel, name, sizeof(name)) != seismic::Hashtag::Ok) {
    problem = "earthquake.channel is not set";
    return false;
  }
  memset(channel.secret, 0, sizeof(channel.secret));
  mesh::Utils::sha256(channel.secret, 16, (const uint8_t*)name, (int)strlen(name));
  const char* banned = alertReporterBannedChannelMatch(channel.secret);
  if (banned != NULL) {
    problem = "earthquake.channel is a busy shared channel and is refused";
    return false;
  }
  mesh::Utils::sha256(channel.hash, sizeof(channel.hash), channel.secret, 16);
  return true;
}

// The things every send needs: a usable channel, scope and location. The clock is not required. `why` says what is missing.
bool MyMesh::quakeSendBlocker(const char*& why, mesh::GroupChannel& channel, TransportKey& scope) {
  why = NULL;
  if (!buildQuakeChannel(channel, why)) return true;
  scope = default_scope;  // the repeater's own default region, as for its adverts
  if (!seismic::locationIsSet(_prefs.node_lat, _prefs.node_lon)) {
    why = seismic::blockText(seismic::Block::NoLocation);
    return true;
  }
  return false;
}

bool MyMesh::sendQuakeMessage(const seismic::Send& values, bool test, const char*& why) {
  mesh::GroupChannel channel;
  TransportKey scope;
  if (quakeSendBlocker(why, channel, scope)) return false;

  // Room left for the text after "<repeater name>: " and the timestamp/type bytes.
  const size_t max_data_len = MAX_PACKET_PAYLOAD - CIPHER_BLOCK_SIZE;
  const size_t budget = max_data_len - 5 - (strnlen(_prefs.node_name, sizeof(_prefs.node_name)) + 2);
  char text[200];
  if (seismic::formatMessage(text, sizeof(text), budget, _prefs.node_lat, _prefs.node_lon,
                             values.haveValues, values.siRaw, values.pgaRaw, test) == 0) {
    why = "repeater name is too long for the message";
    return false;
  }
  if (!sendGroupFloodText(channel, text, &scope)) {
    why = "could not queue the packet";
    return false;
  }
  return true;
}

void MyMesh::checkQuakeAlert() {
  SeismicReading reading;
  seismic::Input in;
  if (sensors.getSeismicReading(reading)) {
    in.sensorPresent = true;
    in.sensorFaulted = reading.sensorFaulted;
    in.processing = reading.processing;
    in.recordValid = reading.recordValid;
    in.shakingCount = reading.shakingCount;
    in.siRaw = reading.siRaw;
    in.pgaRaw = reading.pgaRaw;
  }
  seismic::Gates gates;
  gates.channelSet = quake_channel[0] != 0;
  gates.locationSet = seismic::locationIsSet(_prefs.node_lat, _prefs.node_lon);

  const uint32_t jitter = (uint32_t)getRNG()->nextInt(0, (int)quake_policy.jitterMaxMs() + 1);
  seismic::Send send;
  if (!quake_policy.update(millis(), in, gates, jitter, send)) return;

  const char* why = NULL;
  if (!sendQuakeMessage(send, false, why)) {
    // Channel and location were checked above, so this is a scope or queue problem. The
    // event is not retried: an old alert is worse than none.
    ++quake_send_failures;
    MESH_DEBUG_PRINTLN("quake alert not sent: %s", why);
  }
}

bool MyMesh::quakeAlertBusy() const {
  const auto phase = quake_policy.phase();
  return phase == seismic::Policy::Phase::WaitingForRecord || phase == seismic::Policy::Phase::Delaying;
}

// ---- Clock floor: keep the clock from going backwards across a restart --------------------------------

namespace {
const char CLOCK_FLOOR_FILE[] = "/clock_floor";
}

void MyMesh::restoreClockFloor() {
  clockfloor::Record saved;
  if (_fs != NULL) {
    File file = mesh::openFileRead(_fs, CLOCK_FLOOR_FILE);
    if (file) {
      uint8_t bytes[clockfloor::kRecordSize];
      const size_t size = file.size();
      const bool whole = size == sizeof(bytes) && file.read(bytes, sizeof(bytes)) == (int)sizeof(bytes);
      file.close();
      clockfloor::Record decoded;
      if (whole && clockfloor::decode(bytes, sizeof(bytes), decoded)) saved = decoded;  // else: ignore a damaged file
    }
  }
  clock_keeper.begin(saved);
  const uint32_t found = getRTCClock()->getCurrentTime();
  const uint32_t target = clockfloor::restoreTime(found, saved);
  if (target != 0) {
    getRTCClock()->setCurrentTime(target);
    clock_boot_from = found;
    clock_boot_to = target;
  }
}

bool MyMesh::writeClockFloor(const clockfloor::Record& record) {
  if (_fs == NULL) return false;
  uint8_t bytes[clockfloor::kRecordSize];
  clockfloor::encode(record, bytes);
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  mesh::AtomicFileWriter file(_fs, CLOCK_FLOOR_FILE);
#else
  mesh::ContactFileTransaction file(_fs, CLOCK_FLOOR_FILE);
#endif
  if (!file) return false;
  file.write(bytes, sizeof(bytes));
  return file.commit();
}

// `now` skips the once-a-second throttle (used right before a planned restart).
void MyMesh::serviceClockFloor(bool now) {
  static uint32_t lastSecond = 0;
  const uint32_t second = millis() / 1000;
  if (!now && second == lastSecond) return;
  lastSecond = second;
  clockfloor::Record out;
  if (!clock_keeper.update(getRTCClock()->getCurrentTime(), second, out)) return;
  if (writeClockFloor(out)) clock_keeper.saved(out);
  else clock_keeper.failed();
}

bool MyMesh::handleClockFloorCommand(const char* command, char* reply) {
  // A planned restart or update: save the time first, so it comes back right. Not handled here: the
  // command carries on to its normal handler.
  if (strncmp(command, "reboot", 6) == 0 || strncmp(command, "clkreboot", 9) == 0
      || strncmp(command, "start ota", 9) == 0) {
    clock_keeper.requestSave();
    serviceClockFloor(true);
    return false;
  }
  if (strcmp(command, "get clock.floor") == 0) {
    const clockfloor::Record& r = clock_keeper.record();
    char saved[20] = "never";
    if (r.renewedAt != 0) clockfloor::formatUtc(saved, sizeof(saved), r.renewedAt);
    char boot[64] = "not restored";
    if (clock_boot_to != 0) {
      char from[20], to[20];
      clockfloor::formatUtc(from, sizeof(from), clock_boot_from);
      clockfloor::formatUtc(to, sizeof(to), clock_boot_to);
      snprintf(boot, sizeof(boot), "restored %s -> %s", from, to);
    }
    snprintf(reply, 160, "> %s, every %u min; saved %s UTC; %lu writes (%lu failed); boot: %s", r.enabled ? "on" : "off",
             (unsigned)r.intervalMin, saved, (unsigned long)clock_keeper.writes(), (unsigned long)clock_keeper.failures(),
             boot);
  } else if (strcmp(command, "get clock.floor.interval") == 0) {
    snprintf(reply, 160, "> %u", (unsigned)clock_keeper.record().intervalMin);
  } else if (strncmp(command, "set clock.floor ", 16) == 0) {
    const char* value = skipSpaces(command + 16);
    if (strcmp(value, "on") != 0 && strcmp(value, "off") != 0) {
      strcpy(reply, "Err - usage: set clock.floor <on|off>");
      return true;
    }
    clock_keeper.setEnabled(strcmp(value, "on") == 0);
    strcpy(reply, writeClockFloor(clock_keeper.record()) ? "OK" : "Err - could not save");
  } else if (strncmp(command, "set clock.floor.interval ", 25) == 0) {
    const long minutes = atol(skipSpaces(command + 25));
    if (minutes < clockfloor::kMinIntervalMin || minutes > clockfloor::kMaxIntervalMin) {
      snprintf(reply, 160, "Err - minutes between saves, %u to %u (the default %u is 4 a day)",
               (unsigned)clockfloor::kMinIntervalMin, (unsigned)clockfloor::kMaxIntervalMin,
               (unsigned)clockfloor::kDefaultIntervalMin);
      return true;
    }
    clock_keeper.setIntervalMin((unsigned)minutes);
    strcpy(reply, writeClockFloor(clock_keeper.record()) ? "OK" : "Err - could not save");
  } else {
    return false;
  }
  return true;
}

bool MyMesh::handleQuakeCommand(const char* command, char* reply) {
  if (handleClockFloorCommand(command, reply)) return true;
  if (strcmp(command, "ver") == 0) {
    // Name the product, not just a number: "Quake Repeater v1.17.1.6". No build date: the date in this
    // build was a fixed default, not the real one. getFirmwareVer() stays the bare version, because adverts, telemetry, the
    // bridges and companion apps all read it and the image's version stamp is parsed from it.
    snprintf(reply, 160, "%s %s", FIRMWARE_PRODUCT, getFirmwareVer());
  } else if (strcmp(command, "get earthquake.channel") == 0) {
    snprintf(reply, 160, "> %s", quake_channel[0] ? quake_channel : "<unset>");
  } else if (strncmp(command, "set earthquake.channel ", 23) == 0) {
    const char* value = skipSpaces(command + 23);
    if (strcmp(value, "off") == 0) {
      quake_channel[0] = 0;
      strcpy(reply, saveQuakePrefs() ? "OK - earthquake alerts off (no channel set)" : "Err - could not save");
      return true;
    }
    char name[sizeof(quake_channel)];
    switch (seismic::normalizeHashtag(value, name, sizeof(name))) {
      case seismic::Hashtag::Ok: break;
      case seismic::Hashtag::TooLong: strcpy(reply, "Err - channel name too long (max 22 characters)"); return true;
      case seismic::Hashtag::BadCharacter:
        strcpy(reply, "Err - use letters, digits and dashes only, e.g. #quake-alerts");
        return true;
      default: strcpy(reply, "Err - usage: set earthquake.channel <#name|off>"); return true;
    }
    char previous[sizeof(quake_channel)];
    strcpy(previous, quake_channel);
    strcpy(quake_channel, name);
    mesh::GroupChannel channel;
    const char* problem = NULL;
    if (!buildQuakeChannel(channel, problem)) {
      strcpy(quake_channel, previous);
      snprintf(reply, 160, "Err - %s", problem ? problem : "channel refused");
      return true;
    }
    if (!saveQuakePrefs()) {
      strcpy(quake_channel, previous);
      strcpy(reply, "Err - could not save");
      return true;
    }
    const bool located = seismic::locationIsSet(_prefs.node_lat, _prefs.node_lon);
    snprintf(reply, 160, "OK - alerts go to %s%s", quake_channel,
             located ? "" : ". Set lat and lon too: nothing is sent until the location is set");
  } else if (strcmp(command, "get earthquake.cooldown") == 0) {
    snprintf(reply, 160, "> %u", (unsigned)quake_cooldown_min);
  } else if (strncmp(command, "set earthquake.cooldown ", 24) == 0) {
    const long minutes = atol(skipSpaces(command + 24));
    if (minutes < 1 || minutes > QUAKE_COOLDOWN_MIN_MAX) {
      strcpy(reply, "Err - minutes between alerts, 1 to 1440");
      return true;
    }
    const uint16_t previous = quake_cooldown_min;
    quake_cooldown_min = (uint16_t)minutes;
    if (!saveQuakePrefs()) {
      quake_cooldown_min = previous;
      strcpy(reply, "Err - could not save");
      return true;
    }
    applyQuakePolicyConfig();
    strcpy(reply, "OK");
  } else if (strcmp(command, "earthquake test") == 0) {
    const uint32_t now = millis();
    if (quake_last_test_valid && uint32_t(now - quake_last_test_ms) < QUAKE_TEST_GAP_MS) {
      strcpy(reply, "Err - wait 30 seconds between tests");
      return true;
    }
    const char* why = NULL;
    seismic::Send none;
    if (sendQuakeMessage(none, true, why)) {
      quake_last_test_ms = now;
      quake_last_test_valid = true;
      snprintf(reply, 160, "OK - test message sent to %s", quake_channel);
    } else {
      snprintf(reply, 160, "Err - not sent: %s", why ? why : "unknown");
    }
  } else if (strcmp(command, "earthquake status") == 0) {
    mesh::GroupChannel channel;
    TransportKey scope;
    const char* why = NULL;
    const bool blocked = quakeSendBlocker(why, channel, scope);
    SeismicReading reading;
    const bool sensor = sensors.getSeismicReading(reading);
    // Where an event is right now: nothing, waiting for the sensor's final numbers, about to send, or quiet.
    const uint32_t now = millis();
    char phase[40] = "no event";
    switch (quake_policy.phase()) {
      case seismic::Policy::Phase::WaitingForRecord:
        snprintf(phase, sizeof(phase), "waiting for sensor, %lus", (unsigned long)(quake_policy.waitRemainingMs(now) / 1000));
        break;
      case seismic::Policy::Phase::Delaying:
        snprintf(phase, sizeof(phase), "sending in %lus", (unsigned long)(quake_policy.waitRemainingMs(now) / 1000));
        break;
      case seismic::Policy::Phase::Cooldown:
        snprintf(phase, sizeof(phase), "quiet, %lus left", (unsigned long)(quake_policy.cooldownRemainingMs(now) / 1000));
        break;
      default: break;
    }
    char tail[64] = "";
    if (quake_policy.suppressed() > 0) {
      snprintf(tail, sizeof(tail), "; last held: %s", seismic::blockText(quake_policy.lastBlocked()));
    }
    snprintf(reply, 160, "%s%s; %s; sensor %s; cooldown %um; events %lu, sent %lu, held %lu%s",
             blocked ? "NOT READY - " : "ready - ", blocked ? why : (quake_channel), phase,
             !sensor ? "not found" : reading.sensorFaulted ? "fault" : "ok", (unsigned)quake_cooldown_min,
             (unsigned long)quake_policy.eventsSeen(), (unsigned long)quake_policy.sent(),
             (unsigned long)quake_policy.suppressed(), tail);
  } else {
    return false;
  }
  return true;
}

#endif  // ENV_INCLUDE_D7S

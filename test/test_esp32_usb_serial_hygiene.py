#!/usr/bin/env python3

import re
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced
from test_esp32_hwcdc_recipes import (
    ProjectConfig, USB_CDC, USB_MODE, flag_environment, usb_values,
)


ROOT = Path(__file__).resolve().parents[1]
C6_USB_ENV = "env:M5Stack_Unit_C6L_companion_radio_usb"


def source(path: str) -> str:
    return (ROOT / path).read_text()


def c6_usb_config():
    # Resolve tracked inheritance only; never load a developer's local config.
    config = ProjectConfig(str(ROOT / "platformio.ini"), parse_extra=False)
    config.read(str(ROOT / "variants/m5stack_unit_c6l/platformio.ini"), parse_extra=False)
    return config


def c6_usb_flags(config):
    return flag_environment(
        build_flags=config.get(C6_USB_ENV, "build_flags", []),
        build_unflags=config.get(C6_USB_ENV, "build_unflags", []),
    )


class Esp32UsbSerialHygieneTest(unittest.TestCase):
    def test_hwcdc_rx_allocation_failure_keeps_stream_quarantined(self):
        logging = source("src/helpers/UsbLogging.cpp")
        functions = "\n".join(extract_braced(logging, signature) for signature in (
            "static bool canAccessEsp32Hwcdc(void*)",
            "void prepareUsbLoggingPort()",
        ))
        harness = r'''
#include <atomic>
#include <cassert>
#include <cstddef>
#define MESH_ESP32_HWCDC_SESSION_GUARD 1
#define MESH_ESP32_USB_RX_BUFFER_SIZE 1024
#define MESH_ESP32_USB_TX_BUFFER_SIZE 4096
static std::atomic<bool> esp32_hwcdc_rx_queue_ready{false};
static std::atomic<unsigned> esp32_hwcdc_allowed_generation{0};
static std::atomic<unsigned> esp32_hwcdc_access_generation{0};
static size_t tx_capacity=0;
static void setUsbCompanionTxBufferCapacity(size_t capacity) { tx_capacity=capacity; }
struct SerialMock {
  bool live=false, fail_rx=false;
  size_t rx=0, rx_calls=0, tx=0, timeout=0;
  size_t setRxBufferSize(size_t size) {
    assert(!live); ++rx_calls; rx=fail_rx?0:size; return rx;
  }
  size_t setTxBufferSize(size_t size) { assert(!live); return tx=size; }
  void setTxTimeoutMs(size_t value) { timeout=value; }
} Serial;
@FUNCTIONS@
int main() {
  assert(!canAccessEsp32Hwcdc(nullptr));
  prepareUsbLoggingPort();
  assert(Serial.rx==1024 && Serial.rx_calls==1 && Serial.tx==4096 && Serial.timeout==5);
  assert(tx_capacity==4096 && canAccessEsp32Hwcdc(nullptr));
  ++esp32_hwcdc_access_generation;
  assert(!canAccessEsp32Hwcdc(nullptr));
  ++esp32_hwcdc_allowed_generation;
  assert(canAccessEsp32Hwcdc(nullptr));
  // A separate failed boot must not let the SDK's later 256-byte fallback
  // reopen the application parser after the requested RX allocation failed.
  Serial=SerialMock(); Serial.fail_rx=true;
  prepareUsbLoggingPort();
  assert(!canAccessEsp32Hwcdc(nullptr) && Serial.rx_calls==1);
  Serial.live=true; Serial.rx=256;
  assert(!canAccessEsp32Hwcdc(nullptr));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, binary = Path(directory) / "rx-init.cpp", Path(directory) / "rx-init"
            cpp.write_text(harness.replace("@FUNCTIONS@", functions))
            build = subprocess.run(["g++", "-std=c++17", "-fsanitize=address,undefined",
                                    "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
                                    str(cpp), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_operational_wifi_diagnostics_use_runtime_logging_port(self):
        for relative in (
            "src/helpers/ESP32Board.cpp",
            "src/helpers/CompanionMqttSetupPortal.cpp",
            "src/helpers/JWTHelper.cpp",
            "src/helpers/bridges/MQTTBridge.cpp",
            "src/helpers/esp32/WiFiOtaSeeder.cpp",
            "src/helpers/esp32/WebConfigServer.cpp",
            "src/helpers/WiFiSetupPortal.cpp",
        ):
            text = source(relative)
            self.assertIn("UsbLogging.h", text, relative)
            self.assertNotRegex(
                text,
                r"\bSerial\.(?:print|println|printf|write)\s*\(",
                relative,
            )
            self.assertRegex(text, r"mesh::usb(?:Logging|Debug)Port\(\)", relative)

    def test_v4_companion_uses_usb_serial_jtag_mode(self):
        platformio = source("variants/heltec_v4/platformio.ini")
        base = platformio[
            platformio.index("[Heltec_lora32_v4]") :
            platformio.index("[heltec_v4_oled]")
        ]
        self.assertIn("-D ARDUINO_USB_MODE=1", base)
        self.assertNotIn("ARDUINO_USB_MODE=0", base)

        board = source("boards/heltec_v4.json")
        self.assertIn('"-DARDUINO_USB_CDC_ON_BOOT=1"', board)
        self.assertIn('"-DARDUINO_USB_MODE=1"', board)

    def test_hwcdc_reply_route_has_completed_frame_grace(self):
        main = source("examples/companion_radio/main.cpp")
        start = main.index(
            "// The ESP32 USB-Serial-JTAG peripheral (HWCDC)"
        )
        hwcdc = main[start : main.index("#elif", start)]

        serial_begin = main.index("Serial.begin(115200);")
        prepare = main.index("mesh::prepareUsbLoggingPort();")
        logging_begin = main.index("mesh::beginUsbLoggingPort();")
        self.assertLess(prepare, serial_begin)
        self.assertLess(serial_begin, logging_begin)

        self.assertIn("board.isUsbHostConnected()", hwcdc)
        self.assertIn("usb_serial_interface.hasReceivedFrame()", hwcdc)
        self.assertIn("USB_FRAME_REPLY_GRACE_MS", hwcdc)
        self.assertIn("USB_HOST_LOSS_EDGE_MS", hwcdc)
        self.assertIn("USB_HOST_LOSS_GRACE_MS", hwcdc)
        self.assertIn("USB_CLIENT_IDLE_TIMEOUT", hwcdc)
        self.assertIn("getCompletedFrameCount()", hwcdc)
        self.assertIn(
            "the_mesh.hasFiniteDelayedReplyForRoute(&usb_serial_interface)",
            hwcdc,
        )
        self.assertNotIn("hasSerialOperationForRoute", hwcdc)
        self.assertNotIn("isReplyRouteLockedFor", hwcdc)
        self.assertNotIn("hasPendingWork()", hwcdc)
        self.assertNotIn("_iter_started", hwcdc)
        self.assertNotRegex(hwcdc, r"\(bool\)\s*Serial")

    def test_finite_usb_lease_covers_only_bounded_reply_families(self):
        mesh = source("examples/companion_radio/MyMesh.cpp")
        start = mesh.index("bool MyMesh::hasFiniteDelayedReplyForRoute(")
        body = mesh[start : mesh.index("void MyMesh::servicePendingSerialReply()", start)]
        self.assertIn("_delayed_replies.hasReplyForRoute(route, _ms->getMillis())", body)
        self.assertIn("command_radio_reply_route == route", body)
        delayed = source("src/helpers/CompanionDelayedReplies.cpp")
        lease = delayed[delayed.index("bool CompanionDelayedReplies::hasReplyForRoute("):]
        self.assertIn("{ &request, &trace }", lease)
        self.assertIn("reply->route == route", lease)
        self.assertIn("reply->phase >= AwaitRadio", lease)
        self.assertIn("reply->delivery_deadline : reply->radio_deadline", lease)
        self.assertIn("reply->sent_deadline", lease)
        self.assertIn("expected_ack_table[i].reply_route == route", body)
        self.assertNotIn("_iter_started", body)
        self.assertNotIn("lockReplyRoute", body)
        self.assertNotIn("hasPendingWork", body)
        self.assertNotIn("sign_data_reply_route", body)

    def test_hwcdc_sustained_loss_resets_session_state(self):
        main = source("examples/companion_radio/main.cpp")
        start = main.index("static void serviceUsbTerminalHostSessionReset()")
        service = main[start : main.index("static void serviceUsbTerminal()", start)]
        reset_start = main.index("static void resetUsbTerminalHostSession(")
        reset = main[reset_start:start]

        self.assertIn("takeSustainedHostLoss()", service)
        self.assertIn("takeHostLossEdge()", service)
        self.assertIn("mesh::takeUsbTerminalSessionReset()", service)
        self.assertIn(
            "hardware_bus_reset || physical_host_loss || sustained_host_loss",
            service,
        )
        self.assertIn("usb_terminal_host_reset_completion_pending", service)
        self.assertIn("USB_TRANSPORT_RESET_RETRY_MS", service)
        self.assertIn("resetUsbTerminalHostSession();", service)
        self.assertIn("cancelUsbSerialOperations();", reset)
        self.assertIn("usb_serial_interface.resetSessionState();", reset)
        self.assertIn("if (!mesh::resetUsbCompanionTransport())", reset)
        self.assertIn("usb_terminal_host_reset_completion_pending = true", reset)
        self.assertNotIn("board.reboot()", reset)
        self.assertIn("usb_ascii_session_default.request(", reset)
        self.assertIn("leaveUsbTerminalMode(false);", reset)

        logging = source("src/helpers/UsbLogging.cpp")
        helper_start = logging.index("static bool detachEsp32HwcdcPads()")
        purge_start = logging.index("bool resetUsbCompanionTransport()")
        helper = logging[helper_start:purge_start]
        purge = logging[purge_start : logging.index(
            "Stream& usbLoggingPort()", purge_start
        )]
        self.assertIn(
            "esp32_hwcdc_access_generation.fetch_add(", purge
        )
        self.assertIn("setPlatformDebugOutputEnabled(false);", purge)
        self.assertIn("detachEsp32HwcdcPads()", purge)
        self.assertIn("delay(10);", purge)
        self.assertIn("tryRunExclusive(", purge)
        self.assertIn("Serial.flush();", helper)
        self.assertIn("flush_attempts >= 2", helper)
        self.assertIn("Serial.availableForWrite()", helper)
        self.assertIn("esp32_hwcdc_tx_buffer_capacity.load(", helper)
        self.assertNotIn("Serial.setTxBufferSize(", helper)
        self.assertIn("while (Serial.read() >= 0)", helper)
        self.assertIn(
            "setPlatformDebugOutputEnabled(isUsbDebugLoggingEnabled());", purge
        )
        self.assertIn(
            "esp32_hwcdc_self_reset_guard.expectSelfResetBurst()", purge
        )
        self.assertLess(
            purge.index("esp32_hwcdc_self_reset_guard.expectSelfResetBurst()"),
            purge.index("restoreEsp32HwcdcPads("),
        )
        self.assertIn(
            "esp32_hwcdc_allowed_generation.store(", purge
        )
        self.assertNotIn("setUsbLoggingEnabled(false);", purge)
        self.assertNotIn("Serial.end();", purge)
        self.assertNotIn("Serial.begin(", purge)

        setup = main[main.index("void setup()") : main.index("board.begin();")]
        self.assertIn("mesh::prepareUsbLoggingPort();", setup)
        prepare_start = logging.index("void prepareUsbLoggingPort()")
        prepare = logging[prepare_start : logging.index(
            "void beginUsbLoggingPort()", prepare_start
        )]
        self.assertIn("static const size_t usb_tx_sizes[]", prepare)
        self.assertIn("Serial.setRxBufferSize(MESH_ESP32_USB_RX_BUFFER_SIZE)", prepare)
        self.assertIn("MESH_ESP32_USB_RX_BUFFER_SIZE >= 1024", prepare)
        self.assertLess(prepare.index("Serial.setRxBufferSize("),
                        prepare.index("Serial.setTxBufferSize("))
        header = source("src/helpers/UsbLogging.h")
        self.assertRegex(header, r"#define MESH_ESP32_USB_RX_BUFFER_SIZE 1024\b")
        self.assertIn("Serial.setTxBufferSize(candidate)", prepare)
        self.assertIn("Serial.setTxTimeoutMs(5);", prepare)
        begin_start = logging.index("void beginUsbLoggingPort()")
        begin = logging[begin_start : logging.index(
            "void serviceUsbLoggingPort()", begin_start
        )]
        self.assertIn("Serial.availableForWrite()", begin)
        self.assertNotIn("Serial.setRxBufferSize(", begin)
        self.assertIn("setUsbCompanionTxBufferCapacity(", begin)

        debug_start = logging.index(
            "static void setPlatformDebugOutputEnabled(bool enabled)"
        )
        debug = logging[debug_start : logging.index(
            "#if defined(MESH_DUAL_CDC_LOGGING)", debug_start
        )]
        self.assertIn("MESH_ESP32_HWCDC_SESSION_GUARD", debug)
        self.assertIn("Serial.setDebugOutput(false);", debug)
        self.assertNotIn("&& canAccessEsp32Hwcdc", debug)

        companion_start = logging.index("Stream& usbCompanionPort()")
        companion = logging[companion_start : logging.index(
            "Stream& usbMotaPort()", companion_start
        )]
        self.assertIn("return guarded_esp32_hwcdc_port;", companion)
        mota_port_start = logging.index("Stream& usbMotaPort()")
        mota_port = logging[mota_port_start : logging.index(
            "Stream& usbTerminalPort(", mota_port_start
        )]
        self.assertIn(
            "return guarded_esp32_hwcdc_mota_port;", mota_port
        )
        self.assertIn(
            "AtomicWholeRecordNonBlockingStream<11>", logging
        )

        ota_context = source("src/helpers/ota/OtaContext.h")
        ota_stream = ota_context[
            ota_context.index("#ifndef OTA_FOLDER_SERIAL_STREAM") :
            ota_context.index("#ifndef OTA_FOLDER_SERIAL_BAUD")
        ]
        self.assertIn("MESH_ESP32_USB_CONSOLE_COOPERATIVE", ota_stream)
        self.assertIn("::mesh::usbMotaPort()", ota_stream)

        self.assertIn(
            "Serial.onEvent(ARDUINO_HW_CDC_ANY_EVENT,", logging
        )
        self.assertIn(
            "esp32_hwcdc_bus_reset_generation.fetch_add(", logging
        )
        self.assertIn(
            "esp32_hwcdc_access_generation.fetch_add(", logging
        )
        self.assertIn(
            "esp32_hwcdc_self_reset_guard.shouldIgnoreBusReset()", logging
        )
        self.assertNotIn("esp32_hwcdc_expected_self_reset.exchange(", logging)
        self.assertIn(
            "esp32_hwcdc_self_reset_guard.notePostCleanActivity()", logging
        )
        take_start = logging.index("bool takeUsbTerminalSessionReset()")
        take = logging[take_start : logging.index(
            "bool tryCompleteUsbTerminalSessionReset()", take_start
        )]
        self.assertIn("MESH_ESP32_HWCDC_SESSION_GUARD", take)
        self.assertIn("esp32_hwcdc_bus_reset_generation.load(", take)

        mota_start = main.index("static void serviceUsbMota()")
        mota_end = main.index(
            "static bool usb_terminal_host_reset_completion_pending", mota_start
        )
        mota = main[mota_start:mota_end]
        self.assertIn("#if !(defined(ESP32)", mota)
        self.assertIn("isUsbTerminalDataConnected()", mota)

    def test_hwcdc_pad_detach_supports_idf4_and_idf5(self):
        logging = source("src/helpers/UsbLogging.cpp")
        wrappers = logging[
            logging.index("static bool detachEsp32HwcdcPads()") :
            logging.index("static void purgeEsp32HwcdcQueues(")
        ]
        self.assertIn('#include "esp_idf_version.h"', logging)
        self.assertEqual(wrappers.count("#if ESP_IDF_VERSION_MAJOR >= 5"), 2)
        self.assertIn("usb_serial_jtag_ll_phy_is_pad_enabled()", wrappers)
        self.assertIn("usb_serial_jtag_ll_phy_enable_pad(false)", wrappers)
        self.assertIn("usb_serial_jtag_ll_phy_enable_pad(enabled)", wrappers)
        self.assertIn("usb_serial_jtag_ll_pad_backup_and_disable()", wrappers)
        self.assertIn("usb_serial_jtag_ll_enable_pad(enabled)", wrappers)

        reset_start = logging.index("bool resetUsbCompanionTransport()")
        reset = logging[reset_start : logging.index(
            "Stream& usbLoggingPort()", reset_start
        )]
        self.assertNotIn("usb_serial_jtag_ll_pad_backup_and_disable()", reset)
        self.assertNotIn("usb_serial_jtag_ll_phy_enable_pad(", reset)

        # The USB role inherits native console selectors from the C6L base.
        # Check the effective recipe, including any child build_unflags.
        usb = c6_usb_flags(c6_usb_config())
        self.assertEqual(usb_values(usb), {USB_MODE: "1", USB_CDC: "1"})
        self.assertIn("ENABLE_USB_INTERFACE", usb.get("CPPDEFINES", []))

    def test_c6_usb_recipe_detects_missing_and_disabled_child_selectors(self):
        cases = (
            ("missing inheritance", ["-D ENABLE_USB_INTERFACE"], [],
             {USB_MODE: "0", USB_CDC: "0"}),
            ("removed selectors", ["${M5Stack_Unit_C6L.build_flags}",
                                   "-D ENABLE_USB_INTERFACE"],
             ["-DARDUINO_USB_MODE=1", "-DARDUINO_USB_CDC_ON_BOOT=1"],
             {USB_MODE: "0", USB_CDC: "0"}),
            ("disabled backend", ["${M5Stack_Unit_C6L.build_flags}",
                                  "-D ARDUINO_USB_MODE=0", "-D ENABLE_USB_INTERFACE"],
             ["-DARDUINO_USB_MODE=1"], {USB_MODE: "0", USB_CDC: "1"}),
        )
        for label, flags, unflags, expected in cases:
            with self.subTest(recipe=label):
                config = c6_usb_config()
                config.set(C6_USB_ENV, "build_flags", flags)
                config.set(C6_USB_ENV, "build_unflags", unflags)
                usb = c6_usb_flags(config)
                self.assertIn("ENABLE_USB_INTERFACE", usb.get("CPPDEFINES", []))
                self.assertEqual(usb_values(usb), expected)

    def test_hwcdc_host_presence_uses_sof_signal(self):
        board = source("src/helpers/ESP32Board.h")
        start = board.index("bool isUsbHostConnected() override")
        host_check = board[start : board.index("void setInhibitSleep", start)]

        self.assertIn("ARDUINO_USB_MODE", host_check)
        self.assertIn("host_connected = Serial.isPlugged();", host_check)
        self.assertIn("usb_host_sleep_policy.observe(host_connected, millis());", host_check)
        self.assertIn("return host_connected;", host_check)

    def test_hwcdc_retries_tx_kick_after_transient_sof_loss(self):
        logging = source("src/helpers/UsbLogging.cpp")
        self.assertIn(
            "static std::atomic<bool> esp32_hwcdc_tx_kick_pending{false};",
            logging,
        )
        write_start = logging.index(
            "size_t write(const uint8_t* data, size_t size) override"
        )
        write_end = logging.index("private:", write_start)
        guarded_write = logging[write_start:write_end]
        self.assertIn(
            "esp32_hwcdc_tx_kick_pending.store(true", guarded_write
        )
        self.assertIn("return Serial.write(data, attempt);", guarded_write)
        capacity = guarded_write.index("const int available = Serial.availableForWrite();")
        full = guarded_write.index("if (available <= 0) return 0;")
        clamp = guarded_write.index("const size_t attempt = size <")
        kick_pending = guarded_write.index("esp32_hwcdc_tx_kick_pending.store(true")
        native_write = guarded_write.index("return Serial.write(data, attempt);")
        self.assertLess(capacity, full)
        self.assertLess(full, clamp)
        self.assertLess(clamp, kick_pending)
        self.assertLess(kick_pending, native_write)

        # Extract complete functions: their pinned-SDK/fallback branches now
        # contain nested #endif directives inside the outer platform guard.
        kick = "\n".join(extract_braced(logging, signature) for signature in (
            "static void serviceEsp32HwcdcTxKickExclusive(void*)",
            "static void serviceEsp32HwcdcTxKick()",
        ))
        self.assertIn("Serial.availableForWrite()", kick)
        self.assertIn("esp32_hwcdc_tx_buffer_capacity.load(", kick)
        self.assertIn("meshEsp32HwcdcTxPending()", kick)
        self.assertIn("canAccessEsp32Hwcdc(nullptr)", kick)
        self.assertIn("Serial.isPlugged()", kick)
        self.assertIn("usb_serial_jtag_ll_txfifo_flush();", kick)
        self.assertIn("USB_SERIAL_JTAG_INTR_SERIAL_IN_EMPTY", kick)
        self.assertIn("portENTER_CRITICAL(&esp32_hwcdc_session_mux)", kick)
        self.assertIn("meshEsp32HwcdcKickTx();", kick)
        self.assertIn("tryRunExclusive(", kick)

        event_start = logging.index("static void handleEsp32HwcdcEvent")
        event_end = logging.index(
            "class Esp32HwcdcSessionStream", event_start
        )
        event = logging[event_start:event_end]
        self.assertIn(
            "esp32_hwcdc_tx_kick_pending.store(false", event
        )
        self.assertIn("usb_serial_jtag_ll_disable_intr_mask(", event)
        self.assertNotIn(
            "if (event_id == ARDUINO_HW_CDC_TX_EVENT) {", event
        )

        service_start = logging.index("void serviceUsbTerminalPort()")
        service_end = logging.index(
            "void discardUsbTerminalOutput()", service_start
        )
        service = logging[service_start:service_end]
        self.assertIn("MESH_ESP32_HWCDC_SESSION_GUARD", service)
        self.assertIn("serviceEsp32HwcdcTxKick();", service)

    def test_mqtt_ntp_detail_never_bypasses_logging_mode(self):
        text = source("src/helpers/bridges/MQTTBridge.cpp")
        self.assertIn(
            "if (verbose && mesh::isUsbLoggingEnabled())", text
        )
        self.assertIn("Stream& output = mesh::usbLoggingPort();", text)

    def test_framework_diagnostics_require_master_and_debug_gates(self):
        text = source("src/helpers/UsbLogging.cpp")
        self.assertIn("Serial.setDebugOutput(enabled);", text)

        setter = text[
            text.index("void setUsbLoggingEnabled(") :
            text.index("bool saveUsbLoggingBootPreference(")
        ]
        self.assertIn("setPlatformDebugOutputEnabled(isUsbDebugLoggingEnabled());", setter)

        begin = text[
            text.index("void beginUsbLoggingPort(") :
            text.index("void serviceUsbLoggingPort(")
        ]
        self.assertIn(
            "setPlatformDebugOutputEnabled(isUsbDebugLoggingEnabled());", begin
        )

    def test_expected_fresh_nvs_state_is_silent(self):
        wifi_setup = source("src/helpers/WiFiSetupPortal.cpp")
        webconfig = source("src/helpers/esp32/WebConfigServer.cpp")
        radio_policy = source("src/helpers/esp32/WiFiRadioPolicy.h")
        mqtt_setup = source("src/helpers/CompanionMqttSetupPortal.cpp")

        for text in (wifi_setup, webconfig, radio_policy, mqtt_setup):
            self.assertNotRegex(
                text,
                r'\.begin\("mesh-(?:wifi|webui|mqtt)",\s*true\)',
            )
        self.assertNotIn("nvs.begin(NVS_NAMESPACE, true)", mqtt_setup)

        for text in (wifi_setup, webconfig):
            self.assertIn('isKey("ssid")', text)
            self.assertIn('isKey("password")', text)
        self.assertIn('isKey("enabled")', webconfig)
        self.assertIn('isKey("cli")', webconfig)
        self.assertIn('isKey("powersave")', webconfig)
        self.assertIn('isKey("espnow_ch")', radio_policy)
        self.assertIn("nvs.isKey(NVS_VERSION_KEY)", mqtt_setup)
        self.assertIn("nvs.isKey(NVS_PREFS_KEY)", mqtt_setup)

    def test_indicator_reports_specific_hardware(self):
        header = source("variants/sensecap_indicator-espnow/target.h")
        implementation = source("variants/sensecap_indicator-espnow/target.cpp")
        self.assertIn(
            "class SenseCapIndicatorBoard : public ESP32Board", header
        )
        self.assertIn('return "Seeed SenseCAP Indicator";', header)
        self.assertIn("extern SenseCapIndicatorBoard board;", header)
        self.assertIn("SenseCapIndicatorBoard board;", implementation)


if __name__ == "__main__":
    unittest.main()

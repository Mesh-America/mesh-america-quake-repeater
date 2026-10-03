#pragma once

#include "Mesh.h"
#include <stddef.h>
#include <stdio.h>
#include <stdint.h>

#ifndef GPS_POWERSAVING_ON_DURATION_SECS
#define GPS_POWERSAVING_ON_DURATION_SECS (10UL * 60UL)
#endif

#ifndef GPS_POWERSAVING_OFF_DURATION_SECS
#define GPS_POWERSAVING_OFF_DURATION_SECS (24UL * 60UL * 60UL)
#endif

class LocationProvider {
protected:
    bool _time_sync_needed = true;
    bool _time_sync_applied = false;
    bool _gps_powersaving_enabled = false;
    unsigned long _next_gps_off = 0;
    unsigned long _next_gps_on = 0;
    unsigned long _gps_on_duration_secs = GPS_POWERSAVING_ON_DURATION_SECS;
    unsigned long _gps_off_duration_secs = GPS_POWERSAVING_OFF_DURATION_SECS;
    unsigned long _last_valid_time_sync = 0;
    uint32_t _last_time_sync_request_ms = 0;
    uint32_t _last_time_sync_applied_ms = 0;
    bool _time_sync_request_seen = false;
    bool _time_sync_applied_seen = false;

    void markTimeSyncApplied() {
        _time_sync_applied = true;
        _last_time_sync_applied_ms = static_cast<uint32_t>(millis());
        _time_sync_applied_seen = true;
    }
    void resetTimeSyncRequestState() {
        _last_time_sync_request_ms = 0;
        _last_time_sync_applied_ms = 0;
        _time_sync_request_seen = false;
        _time_sync_applied_seen = false;
    }

public:
    virtual void syncTime() { _time_sync_needed = true; }
    virtual bool waitingTimeSync() { return _time_sync_needed; }
    // Telemetry requests share an in-progress acquisition and rate-limit new
    // ones using monotonic time, not an RTC which GPS/manual sync may correct.
    // Direct syncTime() callers (startup, CLI, power-cycle policy) remain force
    // requests. The argument is seconds, separately from position gps_interval.
    bool requestTimeSync(uint64_t min_interval_secs) {
        if (waitingTimeSync()) return false;
        // Keep the interval below half the 32-bit millis range. Clamp before
        // multiplying so even unusually large build overrides cannot overflow.
        const uint32_t max_interval_ms = 0x7FFFFFFFUL;
        const uint32_t interval_ms = min_interval_secs > max_interval_ms / 1000UL
            ? max_interval_ms : static_cast<uint32_t>(min_interval_secs) * 1000UL;
        const uint32_t now = static_cast<uint32_t>(millis());
        if ((_time_sync_applied_seen
             && static_cast<uint32_t>(now - _last_time_sync_applied_ms) < interval_ms)
            || (_time_sync_request_seen
                && static_cast<uint32_t>(now - _last_time_sync_request_ms) < interval_ms)) {
            return false;
        }
        _last_time_sync_request_ms = now;
        _time_sync_request_seen = true;
        syncTime();
        return true;
    }
    // Edge-triggered notification for consumers that need to know a GPS time
    // was actually written, rather than merely seeing a valid location fix.
    bool consumeTimeSyncApplied() {
        bool applied = _time_sync_applied;
        _time_sync_applied = false;
        return applied;
    }
    virtual void stopTimeSync() { _time_sync_needed = false; }
    virtual void setGPSPowerSaving(bool enabled) {
        _gps_powersaving_enabled = enabled;
        _next_gps_off = 0;
        _next_gps_on = 0;
    }
    virtual bool getGPSPowerSaving() { return _gps_powersaving_enabled; }
    virtual void setNextGPSOff(unsigned long _millis) { _next_gps_off = _millis; }
    virtual unsigned long getNextGPSOff() { return _next_gps_off; }
    virtual void setNextGPSOn(unsigned long _millis) { _next_gps_on = _millis; }
    virtual unsigned long getNextGPSOn() { return _next_gps_on; }

    virtual void setPowerSavingProfile(unsigned long wake_duration_secs, unsigned long sleep_duration_secs) {
        _gps_on_duration_secs = wake_duration_secs;
        _gps_off_duration_secs = sleep_duration_secs;
    }

    // Compatibility names used by the PowerSaving branch. The existing GPS
    // names remain canonical so older targets and stored behavior stay intact.
    virtual void enablePowerSaving(bool enabled) { setGPSPowerSaving(enabled); }
    virtual bool isPowerSavingEnabled() { return getGPSPowerSaving(); }
    virtual void setNextWake() {
        setNextGPSOn(millis() + _gps_off_duration_secs * 1000UL);
    }
    virtual unsigned long getNextWake() { return getNextGPSOn(); }
    virtual void setNextSleep() {
        setNextGPSOff(millis() + _gps_on_duration_secs * 1000UL);
    }
    virtual unsigned long getNextSleep() { return getNextGPSOff(); }
    virtual unsigned long getLastValidTimeSync() { return _last_valid_time_sync; }
    virtual mesh::RTCClock* getRTCClock() { return NULL; }
    virtual long getLatitude() = 0;
    virtual long getLongitude() = 0;
    virtual long getAltitude() = 0;
    virtual long satellitesCount() = 0;
    virtual bool isValid() = 0;
    virtual long getTimestamp() = 0;
    virtual void sendSentence(const char * sentence);
    virtual bool waitFor(const char* prefix, uint32_t timeout_ms) { return false; }
    virtual void drain() { }
    virtual void reset() = 0;
    virtual void begin() = 0;
    virtual void stop() = 0;
    virtual void loop() = 0;
    virtual bool isEnabled() = 0;
    virtual void setPinEn(int pin_en) { (void)pin_en; }
    virtual int getPinEn() { return -1; }

    // Format compact diagnostics in the caller-provided buffer. Providers that
    // have more information (for example UART counters) can override this.
    virtual void formatDiagnostics(char* out, size_t out_size) {
        if (out_size == 0) return;
        snprintf(out, out_size, "en:%u sat:%ld fix:%u",
            isEnabled() ? 1U : 0U,
            satellitesCount(),
            isValid() ? 1U : 0U);
    }
};

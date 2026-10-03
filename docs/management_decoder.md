# Management report decoder

Paste MGR1 or MGR2 management-report payloads or complete GroupData packets from a
packet analyzer to read a radio's public management information. Everything,
including password authentication and ACL decryption, happens locally in this
browser. The report, password, and candidate public key are never uploaded.

The public portion of a report is deliberately plaintext, but it is **not
authenticated** until a management password is supplied. A password-authenticated
page proves that its public fields and encrypted ACL bytes have not been altered
by someone who does not know that password.

## Decode a management report

<div class="management-tool" data-management-decoder>
  <label for="management-packet-input">MGR1/MGR2 payload or complete GroupData packet hex</label>
  <textarea
    id="management-packet-input"
    data-role="input"
    spellcheck="false"
    autocomplete="off"
    placeholder="Paste analyzer Raw Data, canonical MGR1/MGR2 payload hex, or one MQTT raw value per line"
    aria-describedby="management-packet-help"
  ></textarea>
  <p class="management-help" id="management-packet-help">
    Spaces, line breaks, colons, dashes, <code>0x</code>, and MQTT JSON fields named
    <code>raw</code> or <code>data</code> are accepted. Paste all pages from one report
    together to view a complete multi-page ACL. Press Ctrl/Command+Enter to decode.
  </p>

  <label for="management-password-input">Management password <span>(optional for public fields; required for ACLs)</span></label>
  <input id="management-password-input" data-role="password" type="password" autocomplete="new-password">
  <p class="management-help">
    The password remains in this page only. The decoder derives the management AES-SIV key in
    your browser and does not send it anywhere.
  </p>

  <label for="management-candidate-input">Candidate administrator public key <span>(optional)</span></label>
  <input id="management-candidate-input" data-role="candidate" type="text" autocomplete="off" spellcheck="false" placeholder="64 hexadecimal characters">
  <p class="management-help">
    ACL encryption reveals per-radio 12-byte fingerprints, not recoverable public keys.
    Supplying a complete candidate key checks whether its fingerprint appears in this report.
  </p>

  <div class="management-actions">
    <button class="management-primary-action" type="button" data-role="decode">Decode management report</button>
    <button type="button" data-role="clear">Clear local data</button>
    <button type="button" data-role="example">Load authenticated example</button>
  </div>

  <div class="management-error" data-role="error" role="alert" aria-live="polite" hidden></div>

  <section class="management-results" data-role="results" aria-live="polite" hidden>
    <div class="management-status" data-role="status"></div>
    <dl class="management-summary" data-role="summary"></dl>
    <div class="management-warnings" data-role="warnings" hidden>
      <strong>Decode notes</strong>
      <ul data-role="warning-list"></ul>
    </div>
    <h2>Encrypted ACL entries</h2>
    <div class="management-table-wrap">
      <table class="management-table" data-role="acl-table"></table>
    </div>
  </section>
</div>

## What the decoder accepts

- Complete `PAYLOAD_TYPE_GRP_DATA` (`0x06`) analyzer/MQTT packet hex. It checks
  the MeshCore route header, encoded path length, version-specific page bounds, and required
  zero padding.
- A canonical payload beginning with `4D475231` (`MGR1`) or `4D475232` (`MGR2`).
- One raw packet or canonical payload per line; duplicate observations of an
  identical page are deduplicated.

Use the same password configured by `set mgmt.password`. A decoded ACL lists
the report-specific fingerprints and the administrator and/or OTA-signer flags.
It cannot turn a fingerprint back into a full key. Use the optional candidate
field to test a specific full public key.

MGR2 also shows USB logging, host/reader connection, logger-client activity, stalled/recovering/deferred
state, recovery stage, saved backoff, retry interval/inactive seconds, Auto qualification
seconds, and persistence
readiness. Unsupported observation is shown explicitly; legacy MGR1 has no
USB block and shows it as unavailable. These values are the report-start
snapshot, not proof that a Pi or host application is healthy. Older decoder
copies require an update for MGR2.

MGR2 also shows the latest USB watchdog action, reason mask and names,
advisory node-clock timestamp, recorded-boot uptime seconds, event sequence,
and whether the record was durably saved. Software recovery and re-enumeration
mean attempted actions, not successful repairs. A reboot request is not proof
that a reboot completed; a later cancellation can replace it. The node clock
can be wrong, even when it resembles a valid date. Event uptime and sequence
remain useful for ordering. MGR1 does not carry this event field and shows it
as unavailable. All 36 ACL entries still fit, using up to nine MGR2 pages.

The earlier USB-only MGR2 development layout was never released. This decoder
accepts the finalized MGR2 format with its 111-byte public header and latest
watchdog event.

Reports contain a frozen latest-event snapshot, not immediate watchdog alerts
or a complete event history. See [USB logging watchdog](usb_logging_watchdog.md)
for local review and persistence limitations.

Host/reader connection only describes the USB link or open reader. Logger-client
activity means recent USB stats polling within a 15-minute lease, renewed by
the existing five-minute polls without a new registration or heartbeat command.
The flag also requires logging enabled and a connected, unstalled USB link.
It does not identify the client or prove MQTT delivery, disk writes, or Pi health.

For the report schedule, public-field layout, cryptographic design, and the
offline Python capture tool, see [Management reports](management_reports.md).

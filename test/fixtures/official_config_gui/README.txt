This fixture qualifies the initial config.meshcore.io GUI connect/time path.
It does not claim a complete Vue/DOM/browser or physical USB qualification.

Official upstream: https://github.com/meshcore-dev/config.meshcore.io
Pinned revision: aff42ad8ef2b332f24d644ff6a783f8272a88ff2
The index, gui.js and serial-cli.js at this revision match the observed live
config.meshcore.io sources on 2026-10-05. bootstrap-witness.js contains only
the actual connect/disconnect definitions, preserved verbatim. LICENSE.txt
retains the upstream MIT license. No complete third-party bundle is vendored.
The full SerialCLI and GUI source are SHA/size checked in the local test cache
or downloaded from the immutable upstream revision. An explicit source folder
may be selected with MESHCORE_OFFICIAL_CONFIG_GUI for fully offline runs.

Node 18+ runs the actual SerialCLI class and extracted GUI bootstrap. Real Web
Streams are used; only the peripheral and host clock are mocked. A native write
is accepted before the application is ready, and command delivery uses elapsed
time measured from production GPS init. The real production Repeater command
pump and CommonCLI time handler generate the byte-fragmented CRLF reply.
Inventory coverage additionally runs the actual Esp32BootFileSystem and
production recovery/presence paths against peripheral doubles. Its counted
native missing-name scans are charged 129 ms each plus 1000 ms setup settle;
one complete inventory scan costs 129 ms. This deterministic deadline cost
model uses the observed missing-path overhead, not a host benchmark or a
prediction of full physical boot timing. The same workload with inventory
omitted must miss the actual unchanged GUI's 5000 ms first-time deadline.
getData is a callback witness: this test verifies that it is reached after time
sync, without reading or storing private keys/passwords or imitating all GUI
configuration fields. Physical full-Vue testing remains necessary.

The negative controls reintroduce a blocking 5000 ms GPS init, replace the
production CRLF response with LF only, or regress the production CR command
delimiter. They fail at the unchanged stock GUI's client-visible time deadline.
The inventory-off negative retains native probes and the same firmware
workload. These deterministic peripheral models prove those contracts; full
physical first-connect and idle qualification still require native testing.

Run from the repository root:
python3 -B -m unittest discover -s test -p test_official_config_gui.py -v

Native hardware qualification must use the full unchanged official GUI:
1. Use one USB owner and a Chromium profile granting only the exact target to
   both config.meshcore.io and flasher.meshcore.io. Load the GUI first and
   verify the source hashes above before starting the flash in another tab.
2. Verify the actual partition table, OTA sequence CRC, selected application
   slot and image size before application-only flashing. Keep the stock native
   loader/reset/disconnect sequence. Do not erase filesystem preferences to
   make the test easier or assume every board uses the same application slot.
3. Immediately after the stock flash backend returns, click GUI Connect on
   the already loaded page. Keep its 5000 ms timer, initial time command,
   CR-only delimiter and native streams unchanged. Do not insert a startup
   sleep, extra reset, command retry or unplug/replug. Record the first result.
4. A failed first connection remains FAIL. Explicit stock cli.disconnect and
   a later GUI Connect may be recorded separately as recovery. A settled
   no-flash control is also separate from fresh-flash qualification.
5. For idle coverage, save read-back power-saving/logging preferences, enable
   power saving and disable logging, read safe numeric core statistics, then
   transmit no command for 600 seconds. Verify uptime/errors afterward, use
   visible GUI Disconnect/Connect for a full reread, and restore/read back
   original preferences. Do not infer an idle PASS from a fresh-connect retry.

Retain only source/image hashes, lifecycle times, booleans, byte counts,
validated boot phase tokens and whitelisted numeric statistics. The actual
GUI reads private keys and passwords: never persist ordinary debug console
output, complete command responses, or app.device in test artifacts.

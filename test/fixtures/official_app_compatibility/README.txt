Official app compatibility source witness

Source: https://files.liamcottle.net/MeshCore/v1.50.0/MeshCore-v1.50.0%2B78-b7528a7-web.zip
Reviewed: 2026-10-23 (official v1.50.0+78, build b7528a7)
Archive bytes: 16950142
Archive SHA-256: c28f5549a63ce42a50a8a5bd80081c69ef85aeb1dca221c36bc692b838a92dd7
Member: web/main.dart.js
JavaScript bytes: 9491330
JavaScript SHA-256: aafc714732d1e1af749104da446cd250ea72e288f7cd60ce742f9733da30f309

Run:
  python3 -B test/test_official_app_compatibility.py -v

Requires Node.js 22 and a native C++17 compiler. Linux native fixtures run
under AddressSanitizer and UndefinedBehaviorSanitizer. No PlatformIO or
hardware is used. The complete web application is not copied into Git.

Default external cache:
  ~/.cache/meshcore-tests/aafc714732d1e1af749104da446cd250ea72e288f7cd60ce742f9733da30f309/main.dart.js

An optional MESHCORE_OFFICIAL_APP_BUNDLE path selects an existing external
bundle. Its bytes and SHA must match. Without that variable, a cold cache
downloads the official versioned archive and verifies both the archive and
JavaScript's exact size and SHA before saving only the JavaScript member.
CI should use actions/setup-node with node-version 22 and actions/cache for
~/.cache/meshcore-tests, keyed by the source-pin tests. The live app URL is no
longer used, so its deployments cannot break a cold-cache run. Changed archive
or cached bytes still fail explicitly. Updating the source pin and function
witnesses requires review; the test never silently uses a new app or replaces
its parsers with test implementations.

The JS harness extracts and evaluates unmodified compiled app function bodies:
ACL request builder/decoder, CMD50 builder, binary frame parser, SENT/Binary
listeners, CLI response stripping, and all three radio settings screen parsers.
It also executes the app's byte writer/reader and event emitter. Mocked
boundaries are the Dart runtime/type helpers, timer scheduler, transport,
widget state/localization and RNG. The app's schema/tag matching/decoders are
not reimplemented. The deterministic RNG only makes a synthetic request
repeatable; its random value is not the Companion's replay timestamp.

The exact app-generated CMD50 frame goes through the production Companion
command handler and BaseChat request producer. Its real unique-clock-tagged
11-byte plaintext reaches the production repeater receive/ACL handler, with
actual packet budget/admission/serialization. The server's reflected tag and
full padded plaintext then go through the production Companion response
callback, delayed reply owner and bounded serial transport. Only admitted SENT
and Binary frame bytes reach the stock app frame parser/listener/ACL decoder.
The crypto primitive and radio queue are mocked; zero padding reflects the
production cipher block size, not encryption/authentication validation.
The one-admin direct case asserts 11-byte plaintext, 16-byte padded ciphertext,
20-byte payload and 22-byte zero-path wire size. All 32 decoded cases cover
0/1/22/23/24/25/32/256 entries, direct/flood and zero/maximum return path.
Direct replies are bounded to 22 rows: 23 rows create 176 padded plaintext
bytes, exceeding Companion's 174-byte Binary envelope. An explicit historical
23-row negative uses all 176 bytes and verifies that the real Companion callback
admits no Binary frame. Flood replies include their returned path before cipher
padding; their actual padded extra data also passes through the callback.
Large ACLs retain legacy one-packet truncation, not a complete list guarantee.
Actual Companion and CommonCLI radio replies cover saved automatic/explicit
preambles and an active temporary/secondary profile. A fifth field must invoke
each stock app radio screen's existing error path.

The host listener accepts a matching ACL reply 3s into its estimate-2s/+5s
window. Actual firmware callback/SENT deadline behavior is separately exercised
by test_companion_delayed_reply_delivery.py. The global uncorrelated SENT race
is retained as an expected app-level mechanism witness. Neither this synthetic
race nor the newer firmware deadline regression proves the cause of the user's
intermittent Access Control timeout. The successful pre-fix live retry remains
valid. This public web code is not proof of the installed iOS binary/version,
and these native tests do not exercise RF, BLE fragmentation or app UI lifecycle.

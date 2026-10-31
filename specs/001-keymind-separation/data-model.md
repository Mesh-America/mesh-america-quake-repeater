# Data Model: Keymind separation

No stored data. These are the states the work moves through.

## Required check
- **name**: `quake-ci` (new), `test` (Keymind's, being retired)
- **applies to**: branches `next`, `main`
- **states**: `quake-ci`: absent → observed (runs, not required) → required. `test`: required → optional → retired.
- **invariant**: at every moment each protected branch has at least one required check guaranteed to report on every PR.

## Inherited workflow
- **name / file**: e.g. `run-unit-tests.yml`, `github-pages.yml`
- **triggers**, **applies to us** (yes/no)
- **state**: active → disabled; `run-unit-tests.yml` additionally enabled-for-Keymind-merge (temporary)
- **invariant**: the file is byte-identical to Keymind's after Phase C.

## Hook block (Phase F)
- **file**, **marker**, **purpose** (one line), **generic** (yes/no), **upstream decision** (pending / offered / declined)

## Quake Repeater version
- **value** (`MAJOR.MINOR.PATCH.pre`), **packed form** (u32), **tag** (`quake-v<value>`), **keymind base** (release id)
- **invariant**: packed value strictly greater than every earlier shipped release (1.18.0.2 is 0x01120002).

## Keymind merge
- **keymind release**, **PR**, **conflict files**, **full-suite result** (pass / fail-unrelated / fail-ours), **suite re-disabled** (yes/no)

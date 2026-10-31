# Feature Specification: Separate the Quake Repeater from Keymind's Test and Release Cycle

**Feature Branch**: `spec/keymind-separation`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "Separate the Mesh America Quake Repeater firmware repository's CI, release process and code divergence from Keymind Cascade (upstream) while keeping Keymind merges easy."

## Background

The Quake Repeater firmware is a Keymind Cascade merge plus our own additions: 114 files that exist only in our repository (about 40 of them source, tests and docs; the rest are the documentation site), and 11 Keymind files we modified (206 added lines; seven are code carrying our hooks into Keymind's sensor and repeater code, and a few of our lines edit existing Keymind lines rather than only adding). We ship two images, a RAK3401 and a RAK4631, for a small number of devices.

Three things now cost us more than they should:

- **Slow gate.** The one required check on `next` and `main` is Keymind's full test job (57 serial steps, 1 to 1.6 hours). It runs on every pull request and again on every push to `main`, so a release takes about three hours of waiting, almost all of it testing features that no Quake Repeater image ships.
- **Wrong coverage.** The gate is large but does not test our hardware combinations. Release 1.18.0.1 shipped with the RAK4631 sensor power rail switched off by default, so the earthquake sensor and environment sensor vanished from telemetry. Keymind's suite passed, and we needed an emergency 1.18.0.2.
- **Shared version space.** Our firmware version uses Keymind's four-number format. Nothing mechanical collides (the update target ID, tag prefix and repository all differ), but the two numberings are easy to confuse, and choosing a number for 1.18.0.2 without clashing with a possible Keymind 1.18.0.2 was awkward.

Most inherited automation was already switched off in repository settings on 2026-10-03 (observer, companion, room-server and repeater builds, the documentation-site publisher, and others). The one inherited workflow still active is the full test suite itself.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ship a Quake Repeater change in minutes, not hours (Priority: P1)

A maintainer fixes or improves the Quake Repeater (firmware, flasher-facing behaviour, or docs) and opens a pull request. The required checks that gate the merge verify what our two images actually depend on, and finish quickly. The maintainer merges to `next`, promotes `next` to `main`, and a release is published without waiting for unrelated Keymind features to be re-tested.

**Why this priority**: This is the problem that triggered the request. Every other story is about keeping this gain safe and cheap to maintain.

**Independent Test**: Open a trivial pull request that touches only our own files. Measure the time from opening to "all required checks green". Then do the same for a pull request that touches a shared Keymind file.

**Acceptance Scenarios**:

1. **Given** a pull request that changes only Quake Repeater files, **When** its required checks run, **Then** they complete in 15 minutes or less (90th percentile, cold build cache) and the pull request is mergeable.
2. **Given** a pull request that changes only documentation or only workflow files, **When** its required checks run, **Then** the required check still reports a result (it is never left pending) and the pull request is mergeable.
3. **Given** a pull request that breaks either image's build, drops the sensor-rail hold from the real build configuration of either image, or breaks the earthquake sensor logic, **When** its required checks run, **Then** the required check is red (not skipped, not pending) and a non-administrator cannot merge it.
4. **Given** the required checks no longer include Keymind's full test job, **When** an ordinary pull request is opened and no Keymind merge is in progress, **Then** Keymind's full suite does not run on it.
5. **Given** one leg of the build fails, **When** the aggregate required check is evaluated, **Then** it fails; a failed or skipped dependency never produces a passing check.
6. **Given** the required check itself is broken (runner outage, renamed job), **When** a fix must ship, **Then** a documented break-glass procedure lets the owner merge, and records that it was used.

---

### User Story 2 - Merge a new Keymind release without surprises (Priority: P1)

When Keymind publishes a new Cascade release, a maintainer merges it into `next`. Because the merge is the moment upstream code could break us, Keymind's full test suite runs on that merge and only on that merge. Conflicts are rare and small, and when they occur they are in clearly marked places.

**Why this priority**: Separating CI is only acceptable if it does not make staying current with Keymind harder or riskier. This story is the safety net for Story 1.

**Independent Test**: Merge a recent Keymind release candidate into a scratch branch and confirm that (a) the merge produces conflicts only in the documented hook locations, and (b) the full Keymind suite can be run against that merge on demand.

**Acceptance Scenarios**:

1. **Given** a pull request that merges a Keymind release into `next`, **When** its head commit is final, **Then** Keymind's full test suite has a result for that exact commit and the maintainer has recorded a verdict (pass, or a failure shown to be unrelated) before merging.
2. **Given** an ordinary pull request opened when no Keymind merge is in progress, **When** it is opened, **Then** the full Keymind suite does not run. During a merge window the suite may also run on other pull requests; that is accepted and the window is kept short.
3. **Given** a Keymind release that changes a file we modified, **When** a maintainer merges it, **Then** the conflicts are limited to a known, documented list of sites, each identified as a Quake Repeater addition.
4. **Given** a Keymind release that adds, renames, or changes automation files, **When** it is merged, **Then** a check of the workflow list against the inventory flags anything new or re-enabled, and a file we have not edited merges cleanly.

---

### User Story 3 - Our version numbers never collide with Keymind's (Priority: P2)

A maintainer bumps the Quake Repeater version for a release. Our version numbers come from a range Keymind does not use, always sort above every version we have already shipped, and the flasher and the on-air update path continue to treat each new release as an upgrade. Anyone can still tell which Keymind release a given image is built on.

**Why this priority**: It removes the collision risk and the awkward version choices, but it is less urgent than the gate and merge stories and has the most compatibility risk, so it comes after them.

**Independent Test**: Build both images with the new version, confirm the release workflow derives the correct tag, confirm the flasher catalog accepts it as newer than 1.18.0.2, and confirm a device already on 1.18.0.2 accepts it as an update.

**Acceptance Scenarios**:

1. **Given** a version bump in the Quake Repeater variant file, **When** the release workflow runs on `main`, **Then** it publishes exactly one release with the matching tag and both images, as it does today.
2. **Given** the new scheme's first version, **When** the pull request is checked, **Then** a check confirms it is greater than the highest existing release tag, and the flasher catalog, with 1.18.0.2 moved to its earlier-versions list, builds and verifies against a release (a fixture or pre-release before the real one exists).
3. **Given** a device running 1.18.0.2, **When** it is updated to the first new-scheme version by the paths Quake users actually use (USB or Bluetooth update from the flasher, and manual on-air install), **Then** the update succeeds. The on-air automatic-install gate also accepts it, but that gate is off by default and needs signed packages, so it is not the acceptance test.
4. **Given** an installed image, **When** a user sends `ver`, **Then** the answer identifies both the Quake Repeater version and the Keymind release it is built on, while the bare version carried in adverts, telemetry and bridges is unchanged, and the flasher still parses the answer.

---

### User Story 4 - No inherited automation acts on our repository by accident (Priority: P2)

A maintainer reviewing the repository can see which inherited automation is active and why. Automation that does not apply to us (publishing Keymind's documentation site, observer, companion and room-server builds, preset-parity checks) does not run and cannot publish or spend build minutes, either now or after a future Keymind merge.

**Why this priority**: Lower urgency than shipping speed, but it removes a live defect (Keymind's documentation published from our `main`) and prevents surprises.

**Independent Test**: List every workflow in the repository with its triggers and enabled state. Merge a Keymind release that touches those workflow files and list them again.

**Acceptance Scenarios**:

1. **Given** a push to `main` or a pull request to `next` or `main`, **When** automation runs, **Then** only the Quake Repeater workflows, the repository's default code-scanning and dependency-graph jobs, and (during a Keymind merge window only) Keymind's full suite run.
2. **Given** inherited automation that is not ours, **When** a Keymind merge changes, adds, renames or deletes its file, **Then** it remains turned off, and a new or renamed file that arrives enabled is detected and handled.
3. **Given** the repository, **When** a maintainer asks "what runs on a pull request and why", **Then** a short written inventory answers it for every workflow (file-backed or not), and a script compares it with the live list so drift is visible.

---

### User Story 5 - Smaller, clearly owned hooks into Keymind code (Priority: P3)

A maintainer who has to resolve a Keymind conflict, or who wants to propose our hooks upstream, finds a list of every place we touch Keymind's code, ranked by how often upstream changes that file, with logic kept in our own files and only short guarded hooks left in Keymind's. Where a hook is generic enough to be useful to Keymind, the maintainer can choose to offer it upstream.

**Why this priority**: It lowers the long-run cost of merges but changes shipped code, so it is the riskiest and least urgent. It may be skipped if trial-merge numbers show the current layout already merges cleanly.

**Independent Test**: Trial-merge the newest Keymind release before and after, compare conflict counts, and confirm both images build, pass their checks and behave the same.

**Acceptance Scenarios**:

1. **Given** the seam inventory, **When** a maintainer reads it, **Then** every one of our edits to a Keymind file is listed with its purpose, whether it changes an existing Keymind line or only adds lines, and the file's upstream churn.
2. **Given** a consolidation change, **When** both images are built and checked, **Then** their behaviour is unchanged (same telemetry, same alerts, same power behaviour), confirmed on hardware.
3. **Given** a hook that could benefit Keymind, **When** the maintainer chooses to upstream it, **Then** it can be offered as a self-contained change without our product-specific code.

---

### Edge Cases

- **Skipped required check.** A required check that is skipped by a path filter stays pending and blocks documentation-only pull requests. The required check must always produce a result.
- **Order of switching over.** If Keymind's full test is removed from the required checks before ours is required, or if it is turned off while still required, every pull request blocks. The cut-over must follow a safe order and be reversible.
- **Disabled automation re-enabled by a merge.** A Keymind merge could change a turned-off workflow file; it must be verified that this does not turn it back on.
- **Keymind merge pull requests.** The full suite must run on them even though it is off elsewhere; if Keymind's suite fails for reasons unrelated to us (as the stock-app compatibility test currently does), the maintainer needs a documented way to proceed.
- **Release gating.** The existing rule that a release happens only when the version in the variant file is bumped, and that every commit on `main` is merged back into `next`, must keep working.
- **Flasher catalog pinning.** The flasher catalog pins releases by tag; a new version scheme must not break existing pins or the "earlier versions" list.
- **Version ordering on devices.** If a device or tool compares versions numerically, a new scheme that sorts lower than 1.18.0.2 would be refused or ignored.
- **No-op protection.** If a required check silently stops running (renamed or disabled), merges must not proceed unchecked.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST have a Quake Repeater check that is required to merge into `next` and `main`, and that always reports a result on every pull request, including documentation-only ones.
- **FR-002**: The Quake Repeater check MUST verify that: both images build; one stock (non-Quake) RAK4631 image still builds with the earthquake sensor switched off, because our hooks sit in shared headers; the sensor-rail hold in each image's real build configuration matches the expected hold for that image, read from the build definition and not supplied by the test (RAK4631 holds the sensor rail; the RAK3401 expectation is stated and asserted too); all four earthquake test suites (sensor driver, wire-level driver, alert policy, clock floor) ran, with a check that the number of suites run is not zero; and the release metadata is consistent, including both images carrying the same version and, on a pull request that changes the version, that version being higher than every existing release.
- **FR-003**: The Quake Repeater check MUST complete in 15 minutes or less at the 90th percentile, measured with a cold build cache.
- **FR-004**: Keymind's full test job MUST NOT be a required check and MUST NOT run on ordinary pull requests or on pushes to `main`.
- **FR-017**: The required check MUST fail closed: a failed, cancelled or skipped part of the check never produces a passing result, and no status source other than the repository's own automation can satisfy it. (How is in the plan and contract.)
- **FR-018**: A release triggered by pushing a tag MUST pass the same checks as a normal release, and `quake-ci` MUST also run on pushes to `main`.
- **FR-019**: A written break-glass procedure MUST exist for when the required check cannot run, covering who may use it, how, and how its use is recorded. Whether administrators are bound by the required check is the owner's decision, recorded in the contract.
- **FR-020**: Pull requests created with the repository's automatic token (which does not start workflows) MUST NOT be used to reach a protected branch, or must be re-triggered by a push from a user.
- **FR-005**: Keymind's full test suite MUST run, and its result MUST be visible, on every pull request that merges a Keymind release into `next`.
- **FR-006**: We MUST NOT edit, delete, or trim Keymind's workflow files. The one existing edit (the temporary skip of the stock-app compatibility test) MUST be reverted when that suite is run on Keymind merges.
- **FR-007**: Inherited automation that does not apply to the Quake Repeater MUST be turned off through repository settings, and MUST stay off after a Keymind merge changes, adds or renames its file. (Most already are, since 2026-10-03; only Keymind's full test workflow is still active.) A script MUST compare the live workflow list with the inventory so a new or re-enabled workflow is noticed.
- **FR-008**: The change of required checks MUST be performed in an order that never leaves a pull request unmergeable, MUST be approved by the repository owner at each settings change, and MUST be reversible.
- **FR-009**: The repository MUST contain a short written inventory of every workflow: what triggers it, whether it is enabled, and why.
- **FR-010**: Every edit we make to a Keymind file MUST be listed in a seam inventory (file, purpose, additive or edits an existing line, upstream churn), and logic MUST live in our own files with only short guarded hooks left in Keymind's, without changing shipped behaviour. Success is measured by the trial-merge conflict list, not by a count of marked blocks.
- **FR-011**: Where a hook is generic, the maintainer MUST be able to offer it to Keymind as a standalone change. Whether to do so is the maintainer's decision.
- **FR-012**: Quake Repeater versions MUST sort above 1.18.0.2 and MUST NOT be confusable with the Keymind release they are built on. (No mechanism collides today, since the OTA target ID, tag prefix and repository differ; the goal is to stop humans mistaking one numbering for the other.)
- **FR-013**: The release flow MUST be unchanged for the maintainer: bump the version in the variant file, merge `next` into `main`, and exactly one release with both images is published; every commit on `main` is merged back into `next`.
- **FR-014**: The `ver` answer MUST identify both the Quake Repeater version and the Keymind release it is built on. The bare version that adverts, telemetry, bridges and companion apps read MUST NOT change shape. The base-release string MUST be checked in CI against the last merged Keymind release so it cannot go stale, and the flasher's `ver` parser MUST still match.
- **FR-015**: The new version scheme MUST be verified before any release against the flasher catalog build (using a fixture or pre-release), the release tooling's tag derivation, the version packing, the Mesh America release tooling inherited from Keymind, and the update paths Quake users actually use; if any refuses it, the scheme MUST change before any release.
- **FR-016**: Nothing in this work may add any path between the LoRa mesh and the internet.

### Key Entities

- **Required check**: the named check that branch protection demands on `next` and `main`. Attributes: name, what it verifies, run time, whether it ever reports "skipped".
- **Inherited workflow**: automation that comes from Keymind. Attributes: trigger, enabled state, whether it applies to us, how it was turned off.
- **Seam**: one of our edits to a Keymind file. Attributes: file, purpose, whether it adds lines or edits an existing Keymind line, how often upstream changes that file, whether it is generic enough to upstream.
- **Quake Repeater version**: the number that identifies a release. Attributes: value, ordering relative to earlier releases, Keymind base release.
- **Keymind merge**: a pull request bringing a Keymind release into `next`. Attributes: Keymind release, conflicts, full-suite result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The time from opening a pull request to "ready to merge" falls from 1 to 1.6 hours to 15 minutes or less for Quake Repeater changes.
- **SC-002**: Waiting time for a full release (both pull requests merged and the release published, counting only time spent waiting for automation) is under 45 minutes, down from about three hours (two Keymind suite runs of 57 to 94 minutes each, plus the release job).
- **SC-003**: A deliberately introduced fault in each of: an image build, the sensor-rail hold being removed from the real build configuration of the RAK4631 image (the 1.18.0.1 defect), a failing earthquake alert test, a version mismatch between the two images, and a broken matrix leg, turns the required check red in 5 of 5 cases, each attempted once on a scratch branch.
- **SC-004**: A synthetic documentation-only pull request and a synthetic workflow-only pull request each get a green required check and are mergeable, with no check left pending.
- **SC-005**: A trial merge of the newest Keymind release into `next` produces conflicts only at sites on the documented seam list, and the number is recorded as the baseline (the last real merge, 1.18.0.1, had 4 conflicting files; the newest upstream tip trial-merges with 0 today).
- **SC-006**: After the next real Keymind merge, every workflow disabled in settings before the merge is still disabled, and any new or renamed workflow file is detected by the inventory script.
- **SC-007**: After the version change, the flasher lists 1.18.0.2 as an earlier version, a device on 1.18.0.2 updates to the first new-scheme release by USB/Bluetooth DFU and by manual on-air install, and `ver` shows both versions.
- **SC-008**: The working time spent on each Keymind merge (conflict resolution plus review of the full-suite result) is recorded, starting with the next one, so later merges can be compared.

## Assumptions

- The repository owner has the permissions needed to change required checks and to enable or disable workflows, and approves each such change before it is made.
- The Quake Repeater continues to ship only the RAK3401 and RAK4631 images; other Keymind targets are not built or released from this repository.
- We keep merging Keymind Cascade releases into `next` periodically. We are not forking permanently or abandoning upstream updates.
- Keymind's workflow files continue to exist upstream and may change, so they are left byte-for-byte as Keymind has them.
- Turning a workflow off through repository settings survives a merge that changes the file; this is verified before the cut-over, not assumed.
- Hosting stays on GitHub with the existing branch-protection model (`next` and `main`, pull requests required).
- The first new-scheme version is 2.0.0.0, chosen because it sorts above every version either project has shipped. If testing shows the on-air update path or the flasher mishandles it, a different scheme is chosen before any release.
- Offering hooks to Keymind is optional, and the maintainer decides case by case.
- The mesh stays off the internet; this work touches only repository automation, build and release metadata, and clearly marked hook blocks.

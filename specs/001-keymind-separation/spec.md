# Feature Specification: Separate the Quake Repeater from Keymind's Test and Release Cycle

**Feature Branch**: `spec/keymind-separation`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "Separate the Mesh America Quake Repeater firmware repository's CI, release process and code divergence from Keymind Cascade (upstream) while keeping Keymind merges easy."

## Background

The Quake Repeater firmware is a Keymind Cascade merge plus our own additions: 114 files that exist only in our repository, and 11 Keymind files we modified (about 200 added lines, seven of those files being code that carries our hooks into Keymind's sensor and repeater code). We ship two images, a RAK3401 and a RAK4631, for a small number of devices.

Three things now cost us more than they should:

- **Slow gate.** The one required check on `next` and `main` is Keymind's full test job (57 serial steps, 1 to 1.6 hours). It runs on every pull request and again on every push to `main`, so a release takes about three hours of waiting, almost all of it testing features that no Quake Repeater image ships.
- **Wrong coverage.** The gate is large but does not test our hardware combinations. Release 1.18.0.1 shipped with the RAK4631 sensor power rail switched off by default, so the earthquake sensor and environment sensor vanished from telemetry. Keymind's suite passed, and we needed an emergency 1.18.0.2.
- **Shared version space.** Our firmware version uses Keymind's four-number format. A future Keymind release can land on a number we already used or plan to use, which forced an awkward version choice for 1.18.0.2.

Inherited automation also still runs on our repository where it should not: Keymind's documentation site is published from our `main`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ship a Quake Repeater change in minutes, not hours (Priority: P1)

A maintainer fixes or improves the Quake Repeater (firmware, flasher-facing behaviour, or docs) and opens a pull request. The required checks that gate the merge verify what our two images actually depend on, and finish quickly. The maintainer merges to `next`, promotes `next` to `main`, and a release is published without waiting for unrelated Keymind features to be re-tested.

**Why this priority**: This is the problem that triggered the request. Every other story is about keeping this gain safe and cheap to maintain.

**Independent Test**: Open a trivial pull request that touches only our own files. Measure the time from opening to "all required checks green". Then do the same for a pull request that touches a shared Keymind file.

**Acceptance Scenarios**:

1. **Given** a pull request that changes only Quake Repeater files, **When** its required checks run, **Then** they complete in 15 minutes or less and the pull request is mergeable.
2. **Given** a pull request that changes only documentation, **When** its required checks run, **Then** the required check still reports a result (it is never left pending or skipped) and the pull request is mergeable.
3. **Given** a pull request that breaks either image's build, the rail-power behaviour of the sensor board, or the earthquake sensor logic, **When** its required checks run, **Then** a required check fails and the pull request cannot be merged.
4. **Given** the required checks no longer include Keymind's full test job, **When** a pull request is opened, **Then** Keymind's full suite does not run on it by default.

---

### User Story 2 - Merge a new Keymind release without surprises (Priority: P1)

When Keymind publishes a new Cascade release, a maintainer merges it into `next`. Because the merge is the moment upstream code could break us, Keymind's full test suite runs on that merge and only on that merge. Conflicts are rare and small, and when they occur they are in clearly marked places.

**Why this priority**: Separating CI is only acceptable if it does not make staying current with Keymind harder or riskier. This story is the safety net for Story 1.

**Independent Test**: Merge a recent Keymind release candidate into a scratch branch and confirm that (a) the merge produces conflicts only in the documented hook locations, and (b) the full Keymind suite can be run against that merge on demand.

**Acceptance Scenarios**:

1. **Given** a pull request that merges a Keymind release into `next`, **When** it is opened, **Then** Keymind's full test suite runs on it and its result is visible to the maintainer before merging.
2. **Given** any ordinary (non-Keymind-merge) pull request, **When** it is opened, **Then** the full Keymind suite does not run.
3. **Given** a Keymind release that changes a file we modified, **When** a maintainer merges it, **Then** each resulting conflict is confined to one clearly marked block per file that identifies it as a Quake Repeater addition.
4. **Given** a Keymind release that changes one of Keymind's own automation files, **When** it is merged, **Then** the merge applies cleanly because we have not edited that file, and the automation we turned off stays turned off.

---

### User Story 3 - Our version numbers never collide with Keymind's (Priority: P2)

A maintainer bumps the Quake Repeater version for a release. Our version numbers come from a range Keymind does not use, always sort above every version we have already shipped, and the flasher and the on-air update path continue to treat each new release as an upgrade. Anyone can still tell which Keymind release a given image is built on.

**Why this priority**: It removes the collision risk and the awkward version choices, but it is less urgent than the gate and merge stories and has the most compatibility risk, so it comes after them.

**Independent Test**: Build both images with the new version, confirm the release workflow derives the correct tag, confirm the flasher catalog accepts it as newer than 1.18.0.2, and confirm a device already on 1.18.0.2 accepts it as an update.

**Acceptance Scenarios**:

1. **Given** a version bump in the Quake Repeater variant file, **When** the release workflow runs on `main`, **Then** it publishes exactly one release with the matching tag and both images, as it does today.
2. **Given** the new scheme's first version, **When** the flasher catalog is built, **Then** it is accepted as newer than 1.18.0.2 and 1.18.0.2 appears as an earlier version.
3. **Given** a device running 1.18.0.2, **When** it is updated to the first new-scheme version, **Then** the update is accepted, with no manual override needed.
4. **Given** an installed image, **When** a user asks the device for its version, **Then** the answer identifies both the Quake Repeater version and the Keymind release it is built on.

---

### User Story 4 - No inherited automation acts on our repository by accident (Priority: P2)

A maintainer reviewing the repository can see which inherited automation is active and why. Automation that does not apply to us (publishing Keymind's documentation site, observer, companion and room-server builds, preset-parity checks) does not run and cannot publish or spend build minutes, either now or after a future Keymind merge.

**Why this priority**: Lower urgency than shipping speed, but it removes a live defect (Keymind's documentation published from our `main`) and prevents surprises.

**Independent Test**: List every workflow in the repository with its triggers and enabled state. Merge a Keymind release that touches those workflow files and list them again.

**Acceptance Scenarios**:

1. **Given** a push to `main`, **When** automation runs, **Then** only the Quake Repeater release and documentation automation run.
2. **Given** inherited automation that is not ours, **When** a Keymind merge changes its file, **Then** it remains turned off afterwards.
3. **Given** the repository, **When** a maintainer asks "what runs on a pull request and why", **Then** a short written inventory answers it for every workflow.

---

### User Story 5 - Smaller, clearly owned hooks into Keymind code (Priority: P3)

A maintainer who has to resolve a Keymind conflict, or who wants to propose our hooks upstream, finds each of our additions to Keymind's code gathered in a single marked place per file, with a one-line statement of what it is for. Where a hook is generic enough to be useful to Keymind, the maintainer can choose to offer it upstream.

**Why this priority**: It lowers the long-run cost of merges but changes shipped code, so it is the riskiest and least urgent.

**Independent Test**: For each of the seven modified code files, show that all Quake Repeater additions sit in one marked block, and that both images build and pass their checks with the change.

**Acceptance Scenarios**:

1. **Given** any Keymind file we modified, **When** a maintainer opens it, **Then** every Quake Repeater addition is inside one marked block or hook.
2. **Given** the consolidation is complete, **When** both images are built and checked, **Then** their behaviour is unchanged from before (same telemetry, same alerts, same power behaviour).
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
- **FR-002**: The Quake Repeater check MUST verify that both Quake Repeater images build, that the sensor-board power-rail behaviour is correct for each image, that the earthquake sensor logic passes its tests, and that the release metadata is consistent.
- **FR-003**: The Quake Repeater check MUST complete in 15 minutes or less on a typical pull request.
- **FR-004**: Keymind's full test job MUST NOT be a required check and MUST NOT run on ordinary pull requests or on pushes to `main`.
- **FR-005**: Keymind's full test suite MUST run, and its result MUST be visible, on every pull request that merges a Keymind release into `next`.
- **FR-006**: We MUST NOT edit, delete, or trim Keymind's workflow files. The one existing edit (the temporary skip of the stock-app compatibility test) MUST be reverted when that suite is run on Keymind merges.
- **FR-007**: Inherited automation that does not apply to the Quake Repeater, including publishing Keymind's documentation site, MUST be turned off through repository settings, and MUST stay off after a Keymind merge changes its file.
- **FR-008**: The change of required checks MUST be performed in an order that never leaves a pull request unmergeable, MUST be approved by the repository owner at each settings change, and MUST be reversible.
- **FR-009**: The repository MUST contain a short written inventory of every workflow: what triggers it, whether it is enabled, and why.
- **FR-010**: Each Keymind file we modified MUST have all Quake Repeater additions gathered in one marked block, with a one-line purpose, without changing shipped behaviour.
- **FR-011**: Where a hook is generic, the maintainer MUST be able to offer it to Keymind as a standalone change. Whether to do so is the maintainer's decision.
- **FR-012**: Quake Repeater versions MUST come from a range that Keymind's own versions do not use and MUST sort above 1.18.0.2.
- **FR-013**: The release flow MUST be unchanged for the maintainer: bump the version in the variant file, merge `next` into `main`, and exactly one release with both images is published; every commit on `main` is merged back into `next`.
- **FR-014**: The version a device reports MUST identify both the Quake Repeater version and the Keymind release it is built on.
- **FR-015**: The new version scheme MUST be verified against the on-air update path and the flasher catalog before it is adopted; if either refuses it, the scheme MUST be changed before any release.
- **FR-016**: Nothing in this work may add any path between the LoRa mesh and the internet.

### Key Entities

- **Required check**: the named check that branch protection demands on `next` and `main`. Attributes: name, what it verifies, run time, whether it ever reports "skipped".
- **Inherited workflow**: automation that comes from Keymind. Attributes: trigger, enabled state, whether it applies to us, how it was turned off.
- **Hook block**: a marked region in a Keymind file holding our additions. Attributes: file, purpose, whether it is generic enough to upstream.
- **Quake Repeater version**: the number that identifies a release. Attributes: value, ordering relative to earlier releases, Keymind base release.
- **Keymind merge**: a pull request bringing a Keymind release into `next`. Attributes: Keymind release, conflicts, full-suite result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The time from opening a pull request to "ready to merge" falls from 1 to 1.6 hours to 15 minutes or less for Quake Repeater changes.
- **SC-002**: A full release (pull request to `next`, promotion to `main`, release published) takes under 45 minutes of waiting, down from about three hours.
- **SC-003**: A deliberately introduced fault in each of: an image build, the sensor-board rail behaviour, and the earthquake sensor logic is caught by the required check on 3 of 3 attempts. The rail-off regression of release 1.18.0.1 is specifically reproduced and caught.
- **SC-004**: No documentation-only or workflow-only pull request is ever blocked by a pending check (0 occurrences across the first 10 such pull requests).
- **SC-005**: A trial merge of the latest Keymind release produces conflicts in no more than one marked block per modified file, and Keymind's full suite result is available for it.
- **SC-006**: After a trial Keymind merge that changes inherited workflow files, 0 inherited workflows that were turned off are running.
- **SC-007**: After the version change, a device on 1.18.0.2 updates to the first new-scheme release without a manual override, and the flasher lists 1.18.0.2 as an earlier version.
- **SC-008**: The next Keymind release is merged into `next` in under half the working time of the 1.18.0.1 merge.

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

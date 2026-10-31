# Feature Specification: Separate the Quake Repeater from Keymind's Test and Release Cycle

**Feature Branch**: `spec/keymind-separation`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "Separate the Mesh America Quake Repeater firmware repository's CI, release process and code divergence from Keymind Cascade (upstream) while keeping Keymind merges easy."

## Background

The Quake Repeater firmware is a Keymind Cascade merge plus our own additions: 114 files that exist only in our repository (86 are the documentation site, 28 are source, tests and docs), and 11 Keymind files we modified (206 added lines; seven are code carrying our hooks into Keymind's sensor and repeater code, and a few of our lines edit existing Keymind lines rather than only adding). We ship two images, a RAK3401 and a RAK4631, for a small number of devices.

Three things now cost us more than they should:

- **Slow gate.** The one required check on `next` and `main` is Keymind's full test job (57 serial steps, 1 to 1.6 hours). It runs on every pull request and again on every push to `main`, so a release takes about three hours of waiting, almost all of it testing features that no Quake Repeater image ships.
- **Wrong coverage.** The gate is large but does not test our hardware combinations. Release 1.18.0.1 shipped with the RAK4631 sensor power rail switched off by default, so the earthquake sensor and environment sensor vanished from telemetry. Keymind's suite passed, and we needed an emergency 1.18.0.2.
- **Shared version space.** Our firmware version uses Keymind's four-number format. Nothing mechanical collides (the update target ID, tag prefix and repository all differ), but the two numberings are easy to confuse, and choosing a number for 1.18.0.2 without clashing with a possible Keymind 1.18.0.2 was awkward.

Most inherited automation was already switched off in repository settings on 2026-10-03 (observer, companion, room-server and repeater builds, the documentation-site publisher, and others). The inherited workflows still active are the full test suite and a build helper that only runs when another workflow calls it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ship a Quake Repeater change in minutes, not hours (Priority: P1)

A maintainer fixes or improves the Quake Repeater (firmware, flasher-facing behaviour, or docs) and opens a pull request. The required checks that gate the merge verify what our two images actually depend on, and finish quickly. The maintainer merges to `next`, promotes `next` to `main`, and a release is published without waiting for unrelated Keymind features to be re-tested.

**Why this priority**: This is the problem that triggered the request. Every other story is about keeping this gain safe and cheap to maintain.

**Independent Test**: Open a trivial pull request that touches only our own files. Measure the time from opening to "all required checks green". Then do the same for a pull request that touches a shared Keymind file.

**Acceptance Scenarios**:

1. **Given** a pull request that changes only Quake Repeater files, **When** its required checks run, **Then** they complete in 15 minutes or less (90th percentile, cold build cache) and the pull request is mergeable.
2. **Given** a pull request that changes only documentation or only workflow files, **When** its required checks run, **Then** the required check still reports a result (it is never left pending) and the pull request is mergeable.
3. **Given** a pull request that breaks either image's build, changes the expected sensor-rail hold of either image in its real build configuration (RAK4631: sensor power; RAK3401: radio power), or breaks the earthquake sensor logic, **When** its required checks run, **Then** the required check is red (not skipped, not pending) and nobody, administrators included, can merge it.
4. **Given** the required checks no longer include Keymind's full test job, **When** an ordinary pull request is opened and no Keymind merge is in progress, **Then** Keymind's full suite does not run on it.
5. **Given** one leg of the build fails, **When** the aggregate required check is evaluated, **Then** it fails; a failed or skipped dependency never produces a passing check.
6. **Given** the required check itself is broken (runner outage, renamed job), **When** a fix must ship, **Then** a documented break-glass procedure lets the owner proceed through a visible settings change, and records that it was used.

---

### User Story 2 - Merge a new Keymind release without surprises (Priority: P1)

When Keymind publishes a new Cascade release, a maintainer merges it into `next`. Because the merge is the moment upstream code could break us, Keymind's full test suite runs on that merge and only on that merge. Conflicts are rare and small, and when they occur they are at known, listed places.

**Why this priority**: Separating CI is only acceptable if it does not make staying current with Keymind harder or riskier. This story is the safety net for Story 1.

**Independent Test**: Merge a recent Keymind release candidate into a scratch branch and confirm that (a) the merge produces conflicts only at sites on the documented seam list, and (b) the full Keymind suite can be run against that merge on demand.

**Acceptance Scenarios**:

1. **Given** a pull request that merges a Keymind release into `next`, **When** its head commit is final, **Then** Keymind's full test suite has a result for that exact commit and the maintainer has recorded a verdict (pass, or a failure shown to be unrelated) before merging.
2. **Given** an ordinary pull request opened when no Keymind merge is in progress, **When** it is opened, **Then** the full Keymind suite does not run. During a merge window the suite may also run on other pull requests; that is accepted and the window is kept short.
3. **Given** a Keymind release that changes a file we modified, **When** a maintainer merges it, **Then** the conflicts are limited to a known, documented list of sites, each identified as a Quake Repeater addition.
4. **Given** a Keymind release that adds, renames, or changes automation files, **When** it is merged, **Then** a check of the workflow list against the inventory flags anything new or re-enabled, and a file we have not edited merges cleanly.

---

### User Story 3 - Our version numbers are never confused with Keymind's (Priority: P2)

A maintainer bumps the Quake Repeater version for a release. Our version numbers use a major version Keymind does not currently use, always sort above every version we have already shipped, and the flasher and the on-air update path continue to treat each new release as an upgrade. Anyone can still tell which Keymind release a given image is built on.

**Why this priority**: It removes the collision risk and the awkward version choices, but it is less urgent than the gate and merge stories and has the most compatibility risk, so it comes after them.

**Independent Test**: Build both images with the new version, confirm the release workflow derives the correct tag, confirm the flasher catalog builds with 1.18.0.2 listed as an earlier version, and confirm a device already on 1.18.0.2 can be updated to it by the paths Quake users use.

**Acceptance Scenarios**:

1. **Given** a version bump in the Quake Repeater variant file, **When** the release workflow runs on `main`, **Then** it publishes exactly one release with the matching tag and both images, as it does today.
2. **Given** the new scheme's first version, **When** the pull request is checked, **Then** a numeric check against the highest existing release tag confirms it is greater, and the flasher catalog, with 1.18.0.2 moved to its earlier-versions list, builds and verifies against a release (a fixture or pre-release before the real one exists).
3. **Given** a device running 1.18.0.2, **When** it is updated to the first new-scheme version by the paths Quake users actually use (USB or Bluetooth update from the flasher, and manual on-air install), **Then** the update succeeds. The on-air automatic-install gate also accepts it, but that gate is off by default and needs signed packages, so it is not the acceptance test.
4. **Given** an installed image, **When** a user sends `ver`, **Then** the answer identifies both the Quake Repeater version and the Keymind release it is built on, while the bare version read by bridges, management reports, update identity and the boot banner is unchanged, and the flasher still parses the answer.

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
- **No-op protection.** If a required check silently stops running (renamed or disabled), merges must not proceed unchecked. A workflow file with a syntax error produces no check at all, so the check hangs instead of failing; the cut-over plan must account for that.
- **Merge-back with administrators bound.** Merging `main` back into `next` has been a direct push of a merge commit. With administrators bound and a pull request required, a direct push is rejected, so merge-back becomes a pull request.
- **Up-to-date rule.** With the up-to-date rule on, `next` is one commit behind `main` after every release, so the next release is blocked until the merge-back pull request has landed, and every open pull request must be refreshed after another merges.
- **Tag pushes.** Pushing a `quake-v*` tag publishes a release without any pull request; unless the release depends on the same checks and the tagged commit is required to be on `main`, the branch rules are bypassed.
- **Hotfix to `main` before the workflow file reaches `main`.** A pull request cut from a `main` that lacks the check's workflow file would never report it.
- **Conflicted pull requests.** GitHub starts no pull-request workflows on a pull request with merge conflicts, so a conflicted pull request has no check result until it is resolved.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST have a Quake Repeater check that is required to merge into `next` and `main`, and that always reports a result on every pull request, including documentation-only and workflow-only ones.
- **FR-002**: The Quake Repeater check MUST verify that: both images build; one stock (non-Quake) RAK4631 image, chosen in the plan, still builds with the earthquake sensor off, because our hooks sit in shared headers; the sensor-rail hold of each image in its real build configuration equals the expected hold for that image (RAK4631: sensor power, mask 16; RAK3401: radio power, mask 1), where the defines come from the real build definition and the expectation is fixed in the test, so removing or changing the real setting fails it; the four earthquake test suites (sensor driver, wire-level driver, alert policy, clock floor) ran and passed, counted from a machine-readable report, with fewer than four a failure; the tests chosen in the plan for the shared Keymind code our hooks live in pass; and the release metadata is consistent: both images carry the same version in their built manifests and, on a pull request that changes the version, that version is numerically greater than the highest existing release tag.
- **FR-003**: The Quake Repeater check MUST complete in 15 minutes or less at the 90th percentile over a stated sample (the last ten runs), with a cold build cache and not counting runner queue time.
- **FR-004**: Keymind's full test job MUST NOT be a required check and MUST NOT run on ordinary pull requests or on pushes to `main`.
- **FR-005**: Keymind's full test suite MUST run, and its result MUST be visible, on every pull request that merges a Keymind release into `next`, and the Quake Repeater check MUST fail such a pull request until a completed run of the full suite exists for its head commit.
- **FR-006**: We MUST NOT edit, delete, or trim Keymind's workflow files. The one existing edit (the temporary skip of the stock-app compatibility test) MUST be reverted inside the first Keymind merge window.
- **FR-007**: Inherited automation that does not apply to the Quake Repeater MUST be turned off through repository settings, and MUST stay off after a Keymind merge changes, adds or renames its file. (Most already are, since 2026-10-03; only Keymind's full test workflow is still active apart from a helper that runs only when called.) A script MUST compare the live workflow list and the workflow files on disk with the inventory so a new or re-enabled workflow is noticed.
- **FR-008**: The change of required checks MUST be performed in an order that never leaves a pull request unmergeable, MUST be approved by the repository owner at each settings change, and MUST be reversible, with a rollback that restores every setting changed (required checks, up-to-date rule, force-push rule, administrator rule).
- **FR-009**: The repository MUST contain a short written inventory of every workflow: what triggers it, whether it is enabled, and why.
- **FR-010**: Every edit we make to a Keymind file MUST be listed in a seam inventory (file, purpose, additive or edits an existing line, upstream churn), and logic MUST live in our own files with only short guarded hooks left in Keymind's, without changing shipped behaviour. Success is measured by the trial-merge conflict list, not by a count of marked blocks.
- **FR-011**: Where a hook is generic, the maintainer MUST be able to offer it to Keymind as a standalone change. Whether to do so is the maintainer's decision.
- **FR-012**: Quake Repeater versions MUST sort above 1.18.0.2 and MUST use a major version Keymind does not currently use, so they are recognisable as ours. (No mechanism collides today, since the OTA target ID, tag prefix and repository differ; the goal is to stop people mistaking one numbering for the other. This assumes Keymind stays on major version 1; if it moves to 2.x the scheme is revisited.)
- **FR-013**: The release flow MUST stay the same for the maintainer: bump the version in the variant file, merge `next` into `main`, and exactly one release with both images is published, only after the same checks have passed for that commit; every commit on `main` is merged back into `next`.
- **FR-014**: The `ver` answer MUST identify both the Quake Repeater version and the Keymind release it is built on, keeping the `Quake Repeater <version>` prefix the flasher parses. The bare version read by bridges, management reports, update identity, the boot banner and companion apps MUST NOT change shape. The owner-info reply and `ver` MUST NOT contradict each other. The base-release string MUST be checked in CI against the highest Keymind release merged into the branch so it cannot go stale.
- **FR-015**: The new version scheme MUST be verified before any release against the flasher catalog build (using a fixture or pre-release), the release tooling's tag derivation, the version packing, the update paths Quake users actually use, and whether official apps change behaviour on a major-version change; if any refuses it, the scheme MUST change before any release.
- **FR-016**: Nothing in this work may add any path between the LoRa mesh and the internet.
- **FR-017**: The required check MUST fail closed: a failed, cancelled or skipped part of the check never produces a passing result, and only the repository's own automation can satisfy it. Because a pull request runs its own copy of the check's workflow file, a pull request can change its own check; this limitation is accepted, and a pull request that edits the check's definition MUST be called out to the owner in review.
- **FR-018**: A release published from a tag push or a push to `main` MUST depend on the same checks passing for that commit, and the tagged commit MUST be reachable from `main`. Who may create a tag is not restricted (the release workflow creates its own tag and agents work under the owner's identity), so the gate is what the release depends on, not who pushes the tag. The Quake Repeater check MUST also run on pushes to `main` and `next`, applying "not lower than the highest tag" instead of "greater" on those events.
- **FR-019**: A written break-glass procedure MUST exist for when the required check cannot run, covering who may use it, how, and how its use is recorded. Administrators MUST NOT be able to merge around a failed required check on a protected branch; the only way past it is a visible settings change that removes the requirement, and that is recorded. (Release-tag creation is covered by FR-018.)
- **FR-020**: Pull requests created with the repository's automatic token (which does not start workflows) MUST NOT be used to reach a protected branch, or must be re-triggered by a push from a user.
- **FR-021**: With administrators bound, merging `main` back into `next` MUST be done as a pull request that has a green Quake Repeater check, never as a direct push, and the written release procedure MUST say so. Release pull requests from `next` into `main` MUST use merge commits only.
- **FR-022**: Branch rules: the up-to-date rule is on, force-push on `next` is blocked, and the Quake Repeater check is required on `main` only after a release has put its workflow file on `main`.

### Key Entities

- **Required check**: the named check that branch protection demands on `next` and `main`. Attributes: name, what it verifies, run time, whether it ever reports "skipped".
- **Inherited workflow**: automation that comes from Keymind. Attributes: trigger, enabled state, whether it applies to us, how it was turned off.
- **Seam**: one of our edits to a Keymind file. Attributes: file, purpose, whether it adds lines or edits an existing Keymind line, how often upstream changes that file, whether it is generic enough to upstream.
- **Quake Repeater version**: the number that identifies a release. Attributes: value, ordering relative to earlier releases, Keymind base release.
- **Keymind merge**: a pull request bringing a Keymind release into `next`. Attributes: Keymind release, conflicts, full-suite result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The time from opening a pull request to "ready to merge" falls from 1 to 1.6 hours to 15 minutes or less for Quake Repeater changes.
- **SC-002**: Waiting time for a full release, counting only time spent waiting for automation and including the merge-back pull request (pull request to `next`, release pull request to `main`, merge-back pull request), is under 60 minutes, down from about three hours (two Keymind suite runs of 57 to 94 minutes each, plus the release job).
- **SC-003**: Each of these deliberate faults, introduced once on a scratch branch, turns the required check red (not skipped, not pending): F1 an image fails to build; F2 the RAK4631 sensor-rail hold is removed or changed in its real build configuration (the 1.18.0.1 defect); F3 the RAK3401 radio-power hold is removed or changed; F4 an earthquake alert test fails; F5 the two images carry different versions; F6 a pull request sets a version not above the highest tag; F7 the stock smoke build fails; F8 one leg of the build fails or is cancelled. Result required: 8 of 8. Also: fewer than four earthquake suites run turns it red.
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
- Turning a workflow off through repository settings survives a merge that changes the file. Supported by a measured case (a workflow file changed by a merge after it was disabled stayed disabled); an added or renamed upstream workflow file arrives enabled, which the inventory check catches; re-checked after the next real merge.
- Hosting stays on GitHub with the existing branch-protection model (`next` and `main`, pull requests required).
- The first new-scheme version is 2.0.0.0 (decided by the owner, 2026-10-30), chosen because it sorts above every version either project has shipped and Keymind is on major version 1. If testing shows the update path, the flasher or the release tooling mishandles it, a different scheme is chosen before any release.
- Offering hooks to Keymind is optional, and the maintainer decides case by case.
- The mesh stays off the internet; this work touches only repository automation, build and release metadata, and short guarded hooks.

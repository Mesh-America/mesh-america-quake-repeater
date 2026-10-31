# Mesh America Quake Repeater Constitution

The firmware in this repository is Keymind Cascade plus the Mesh America Quake Repeater additions. These
principles come from decisions the maintainer has already made; the specification and plan for the
current work are in `specs/001-keymind-separation/`.

## Core Principles

### I. Keymind merges stay easy
Staying current with Keymind Cascade is a standing requirement. Prefer new files of our own over edits to
Keymind files; where a Keymind file must change, the edit is short, guarded by `ENV_INCLUDE_D7S` or an
equivalent, and listed in `.github/SEAMS.md`. A change is judged by what it costs at the next Keymind merge.

### II. Keymind workflow files are never edited
No Keymind workflow file is trimmed, forked or deleted, even for speed. Workflows that do not apply to us
are switched off in repository settings, and new automation goes in files of our own. The one temporary edit
(the stock-app test skip) is reverted in the first Keymind merge window.

### III. Every commit on `main` goes back into `next`
After anything lands on `main` (release pull requests, bot commits), `main` is merged back into `next`, in
this repository and in the apps repository. With administrators bound, the merge-back is a pull request.

### IV. The mesh is never bridged to the internet
No feature, side benefit or convenience may add an internet gateway to the LoRa mesh.

### V. A gate must fail closed and be proven red
A check that can pass vacuously is worse than none. Required checks fail when a dependency is skipped,
cancelled or empty, report on every pull request, and are proven by deliberately breaking what they
protect. Safety tests read the real build definitions rather than restating them.

### VI. Settings changes need the owner
Branch protection, required checks, rulesets, merge methods and workflow enablement are changed only with
the owner's explicit approval, one step at a time, in an order that cannot leave a pull request
unmergeable, with the previous state saved and a rollback written down.

## Working agreements

- Tasks are tracked in Beads (`bd`, prefix `qr`), not in a Spec Kit tasks file.
- Anything long-running or shared on the maintainer's machine (containers, builds) targets only what it
  started, by name.
- Release flow: work lands on `next`; a merge-commit pull request from `next` to `main` is the release;
  a release happens only when `FIRMWARE_VERSION` is bumped.

**Version**: 1.0.0 | **Ratified**: 2026-10-31 (proposed; the maintainer has not yet reviewed this wording)

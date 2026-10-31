# Releasing the Quake Repeater

Work lands on `next`; a pull request from `next` to `main` is the release. A release is published only
when `FIRMWARE_VERSION` in `variants/meshamerica_quake/platformio.ini` (both environments) is bumped:
the release workflow tags `quake-vX.Y.Z.W` from the version inside the image, with both images in one
release. Plan and reasoning: `specs/001-keymind-separation/` (contract: `contracts/ci-and-settings.md`).

## Today (before the cut-over)

1. Feature pull requests into `next`. The required check is still Keymind's `test` (about an hour).
2. Bump `FIRMWARE_VERSION` in both environments, merge `next` into `main` with a **merge commit**.
3. The release workflow builds both images and publishes the release; the docs site deploys.
4. Merge `main` back into `next` (a direct push works today).
5. Then, in the apps repository, pin the flasher to the new tag (`catalog.source.json`, move the old
   release to the front of `previousReleases`), through that repository's own `next` and `main`, and merge
   its `main` back into `next` too.

## After the cut-over (administrators bound, up-to-date rule on)

Applies once cut-over step 9 in the contract is done. A direct push to `next` is then rejected.

1. Feature pull requests into `next`, merge commits. The required check is `quake-ci`.
2. Release pull request `next` into `main`, **merge commit only** (a squash or rebase would leave `next`
   permanently behind `main`). `quake-ci` must be green on it.
3. The release workflow runs `quake-ci` again for that commit, then publishes. A tag push gets the same
   treatment, and the tagged commit must already be part of `main`.
4. After the release lands, `main` is one commit ahead of `next`. **Merge back through a pull request**:
   branch `merge/main-into-next-<n>` from `next`, merge `main` into it, open a pull request into `next`,
   wait for `quake-ci`, merge. Never use a pull request whose head is `main`.
5. The next release pull request cannot merge until step 4 has landed (the up-to-date rule), and every
   other open pull request into `next` must be refreshed after each merge.
6. Apps repository as before.

## Keymind merge window

See `contracts/ci-and-settings.md` ("Keymind merge window"): enable `run-unit-tests.yml`, branch
`merge/keymind-<release>`, push or reopen the pull request, record the verdict, merge, disable it again,
run `scripts/check_workflow_inventory.py`, and revert our temporary skip in `run-unit-tests.yml` inside
the first window.

## If `quake-ci` cannot run

With administrators bound there is no merge-time bypass. Remove `quake-ci` from the required checks (a
settings change that shows in the audit log), merge, note the reason on the pull request, and restore it
straight away. A broken `quake-ci.yml` is fixed by a pull request that runs its own corrected copy.

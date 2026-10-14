# macOS window-buttons CI experiment

This lives ONLY on `bruno/2026-10-14/window-buttons-ci` in the existing
`aduros/ungoogled-chromium` fork. The PR branch/default branch are not changed.
No PR is needed for this experiment. Do not merge this CI branch into the PR.

## What it builds

A standalone ARM64 **upstream Chromium 155.0.8059.39 + the current UI patch**,
not a full ungoogled-chromium build. This is the first native UI experiment;
full ungoogled integration still needs a separate build. The local rewrite's
four implementation changes are snapshotted in `patches/window-buttons-ui.patch`.
There is no `chrome://flags` registration: use `--hide-window-buttons`.

Source and depot_tools revisions and Actions are pinned. The app is a
non-component, non-official release build with symbols, PGO and LTO disabled.
Only `chrome` and its macOS signing resources are built. Chromium's generated
signing scripts sign nested components with their proper entitlements using
`--identity - --development --notarize none`. No Developer ID, Apple secrets,
notarization, release, repository writes, PR comments or browser launches occur
in the build job. The artifact contains the signed app, a fresh-profile
launcher, test instructions, source diff, GN args and build provenance.

## First push: capacity probe only

The workflow runs on pushes changing this directory or the experiment workflow
on the exact experiment branch. A branch-local push event works without adding
workflow files to the fork's default branch. The existing core validation
workflow is excluded for pushes to this branch only, avoiding an unrelated
full-source download during a cheap probe.

`config.json` initially has `mode: "probe"`, using the standard `macos-15`
runner. The Actions summary reports actual disk, CPU, RAM, Xcode and SDK. It
does not download Chromium or start a build. Fork Actions may first need to be
enabled in the GitHub UI.

Standard ARM Mac runners document 3 M1 cores, 7 GB RAM and 14 GB storage.
GitHub's larger ARM Mac runners ALSO document 14 GB storage: upgrading compute
alone does not guarantee room for Chromium. Inspect the actual probe results,
then use a suitable provisioned remote ARM Mac runner if needed (e.g. Depot or
MacStadium/self-hosted). Sponsorship of upstream's Depot runners does not grant
a fork access. Do not provision/charge a service without approval.

## Trigger a build on the experiment branch

Edit `config.json` on this branch, commit and push (only with user permission):

```json
{
  "mode": "build",
  "runner_labels": ["self-hosted", "macOS", "ARM64", "chromium-build"],
  "variant": "explicit",
  "min_free_gib": 80,
  "build_jobs": 0
}
```

The runner must already be registered for this fork and have full Xcode
selected, SDK >= 15, Git/Python and the other normal Chromium Mac build
prerequisites. Build hosts download pinned depot_tools and source/toolchains.
The 80 GiB headroom check is an **operator-selected safety budget**, not a
measured or documented Chromium minimum; adjust it based on observed usage.
On a disposable GitHub-hosted ARM Mac ONLY, the workflow first inventories
Xcodes/simulators, removes unused Xcode installations while preserving the
selected full Xcode, and deletes simulator devices/runtimes using simctl.
Guard checks refuse local or self-hosted cleanup. No unrelated files are
removed. The initial hosted build uses two compiler workers; `build_jobs: 0`
conservatively derives concurrency from CPU/RAM if preferred. A standard runner might fit after inspecting capacity,
but successful completion within the hosted time limit is NOT guaranteed.

Variant choices:
- `explicit`: current explicit button hiding + layout/reveal enforcement.
- `short`: reviewer experiment, only returning early from
  `maybeShowTrafficLights` for the switch; no new layout/reveal enforcement.
- `both`: build explicit first, then change only the native implementation and
  incrementally rebuild/sign the short variant in the same checkout.

Both retain the Mac empty-caption-bounds check and other-platform UI changes.
If the short variant still displays buttons, the experiment has failed to hide
native controls; it should not be adopted merely because it is shorter.

The build has a 300-minute process-group deadline, leaving time to sign/upload
within the job's 350-minute limit. This is not a resumable multi-job build;
a slow runner can time out without producing an app. Logs are uploaded on
failure; any completed first variant is still uploaded if the second fails.
Artifacts are retained for 3 days to limit storage usage. No build cache is
uploaded. Only the script's private temporary source tree is removed after a
successful run; Actions normally cleans RUNNER_TEMP after the job.

## Testing the artifact

Download the app artifact, extract the contained ZIP, and follow `TESTING.md`.
The ZIP preserves executable permissions, symlinks and the signed bundle.
SHA-256 files are uploaded with logs. `build-info.json` identifies variant,
source/depot_tools revisions, patch hash, SDK and CI commit/run.

CI verifies signing and architecture; it does NOT validate visible traffic
lights. Run the app yourself in a fresh profile. Never replace the installed
Chromium or use its original profile. This experiment is not a privacy-hardened
ungoogled build and should not be used for personal browsing.


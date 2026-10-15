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
Xcodes/simulators, selects preinstalled Xcode 26.3 and checks the three
DarwinFoundation module maps required by Chromium 155, then removes unused
Xcode installations while preserving that toolchain. It also deletes
simulator devices/runtimes using simctl.
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

## Resumable Ninja checkpoints

Build chunks have a 270-minute process-group deadline, including source
preparation, leaving time for checkpoint compression/upload. A timeout is still
reported as a failed build, not an app artifact, but a subsequent step saves the
completed Ninja outputs. Rerun the failed build job to continue using its latest
cache; no workflow dispatch or PR changes are needed.

Checkpoints contain only the build output tree and a source/tool-input manifest,
not the source checkout, HOME, credentials, or browser profiles. Source is fetched
fresh at its pinned revisions. The private build path is fixed across jobs.
SHA-256 content checks restore input mtimes ONLY for unchanged files, while
changed inputs retain fresh timestamps so Ninja rebuilds them. Output nanosecond
timestamps are restored too: BSD tar rounds these, which otherwise invalidates
Ninja's dependency database. A small real-Ninja/depfile test verifies reuse after
a simulated fresh checkout and invalidation after edits. Two 45-minute CI test
chunks validated Chromium-scale reuse: the first snapshot was ~390 MB, the
rerun content-matched 1,091,156 inputs and reduced pending tasks from 57,488 to
51,017. Its updated snapshot was ~400 MB. A diagnostic full-graph dry-run took
~12 minutes and has been removed; the real build reports remaining task counts.

Keys isolate architecture, source/depot revisions, UI patch, variant, GN args,
Xcode/SDK build, image version and workspace path. Checkpoints are checksum-
validated and extraction rejects traversal and writes through external links.
The compressed snapshot is capped at **8 GiB**, below the default **10 GB** repo
cache quota; oversize snapshots are deleted, never uploaded. Unique snapshots
use GitHub's default quota/oldest-entry eviction; no paid storage setting is
changed. Only experiment-branch push runs write these caches. Clang modules are
unchanged; no ccache/sccache sloppiness is enabled.

The job allows 35 minutes for manifest creation/compression after the build
chunk, then uploads the snapshot even after a controlled timeout. Source is
not cached, so each chunk still pays the download/setup cost. This is not yet
a guarantee that the eventual output tree fits the cache. If size or restore
validation fails, inspect the logs rather than queueing blind cold retries.
App artifacts/logs are retained for 3 days. Actions removes RUNNER_TEMP after
the job; the build script leaves its workspace for checkpoint creation.

## Testing the artifact

Download the app artifact, extract the contained ZIP, and follow `TESTING.md`.
The ZIP preserves executable permissions, symlinks and the signed bundle.
SHA-256 files are uploaded with logs. `build-info.json` identifies variant,
source/depot_tools revisions, patch hash, SDK and CI commit/run.

CI verifies signing and architecture; it does NOT validate visible traffic
lights. Run the app yourself in a fresh profile. Never replace the installed
Chromium or use its original profile. This experiment is not a privacy-hardened
ungoogled build and should not be used for personal browsing.


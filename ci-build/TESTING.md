# Testing the window-buttons artifact

This is **upstream Chromium 155.0.8059.39 with a UI-only experiment patch**, not
an ungoogled release. The CLI switch is `--hide-window-buttons`; it has no
`chrome://flags` entry in this experimental app. It is ARM64, ad-hoc signed,
and NOT notarized. Check `build-info.json` for the exact variant and source.
Do not use it for personal browsing or install it over your existing Chromium.

After extracting the inner artifact ZIP, open Terminal in the extracted folder:

```sh
# Enabled. A new temporary profile is created for every invocation.
bash ./launch-test.command hidden

# Quit the test instance, then compare default behavior in another new profile.
bash ./launch-test.command visible
```

The launcher uses a separate `--user-data-dir` and mock keychain, disables
background networking/component updates/sync, and opens only about:blank.
It does not use your normal profile or weaken the browser sandbox.

Verify startup, resize, maximize/minimize via menus or keyboard, activation,
incognito, fullscreen enter/exit and toolbar reveal. Check both button
visibility and whether tabs actually use the former button gap. Yabai/Aerospace
behavior must be checked on your own desktop. System titlebars on popups/devtools
and remote app-shim windows are outside/unverified in this minimal experiment.

For a `short` artifact, enabled mode tests the reviewer's early-return-only
suggestion. Buttons remaining visible (possibly overlapping reclaimed tab
space) means that approach is insufficient in your build. The `explicit`
artifact is the comparison with explicit hiding and layout/reveal enforcement.

Verify the extracted signature without launching:

```sh
codesign --verify --deep --strict --verbose=2 ./Chromium.app
codesign --display --verbose=4 ./Chromium.app
```

Check the ZIP against the SHA-256 file from the logs artifact. Ad-hoc signing
provides code integrity, NOT an authenticated publisher or Apple notarization.
If macOS blocks this unnotarized download, approve ONLY this trusted test
artifact locally. Chromium's development-build instructions allow removing
its download quarantine attribute after verification:

```sh
xattr -dr com.apple.quarantine ./Chromium.app
```

Do not disable Gatekeeper globally or add `--no-sandbox`. Keep the test app
outside /Applications and leave the original browser/profile untouched.

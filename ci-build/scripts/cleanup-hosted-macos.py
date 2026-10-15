#!/usr/bin/env python3
"""Inventory and clean ONLY an ephemeral GitHub-hosted ARM Mac build machine."""
import os
from pathlib import Path
import platform
import subprocess
import sys


def require_hosted_mac(env, home, system, machine):
    expected = {
        'GITHUB_ACTIONS': 'true',
        'RUNNER_ENVIRONMENT': 'github-hosted',
        'RUNNER_OS': 'macOS',
        'RUNNER_ARCH': 'ARM64',
    }
    if system != 'Darwin' or machine != 'arm64' or Path(home) != Path('/Users/runner'):
        raise ValueError('Cleanup is restricted to a disposable GitHub-hosted ARM Mac')
    if any(env.get(key) != value for key, value in expected.items()):
        raise ValueError('Refusing cleanup outside GitHub-hosted Actions')
    for key in ('GITHUB_WORKSPACE', 'RUNNER_TEMP'):
        if not Path(env.get(key, '')).resolve().is_relative_to(Path('/Users/runner/work')):
            raise ValueError(f'Unexpected hosted runner path: {key}')


def unused_xcodes(applications, active):
    applications = Path(applications).resolve()
    active = Path(active).resolve()
    if active.parent != applications or not active.is_dir() or not active.name.startswith('Xcode') or active.suffix != '.app':
        raise ValueError('Cannot safely identify the selected full Xcode')
    return [p for p in sorted(applications.glob('Xcode*.app'))
            if p.is_dir() and not p.is_symlink()
            and p.resolve().parent == applications and p.resolve() != active]


def run_optional(command):
    result = subprocess.run(command, check=False)
    if result.returncode:
        print(f'::warning::Optional cleanup failed ({result.returncode}): {command}', flush=True)


def main():
    require_hosted_mac(os.environ, Path.home(), platform.system(), platform.machine())
    # Chromium's Mac build docs recommend a larger vnode cache for its large
    # checkout. Runtime-only tuning on this disposable machine, never persisted.
    vnodes = int(subprocess.check_output(['sysctl', '-n', 'kern.maxvnodes'], text=True))
    print(f'Current vnode cache ceiling: {vnodes}', flush=True)
    if vnodes < 524288:
        run_optional(['sudo', '-n', 'sysctl', 'kern.maxvnodes=524288'])
    # The image default is Xcode 16.4 / SDK 15.5. Chromium 155's system
    # modules now reference DarwinFoundation{1,2,3}.modulemap from newer SDKs.
    # Use the already-installed modern toolchain; never download paid tools.
    modern = Path('/Applications/Xcode_26.3.app/Contents/Developer')
    if not modern.is_dir():
        raise ValueError('Expected preinstalled Xcode 26.3 is missing; no cleanup performed')
    subprocess.run(['sudo', '-n', 'xcode-select', '--switch', str(modern)], check=True)
    sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
    for number in (1, 2, 3):
        modulemap = sdk / 'usr/include' / f'DarwinFoundation{number}.modulemap'
        if not modulemap.is_file():
            raise ValueError(f'Required Chromium system module map is missing: {modulemap}')
    developer = Path(subprocess.check_output(['xcode-select', '-p'], text=True).strip()).resolve()
    if developer.name != 'Developer' or developer.parent.name != 'Contents':
        raise ValueError('Select full Xcode before cleaning unused copies')
    active = developer.parent.parent
    targets = unused_xcodes('/Applications', active)
    print(f'Preserving selected Xcode: {active}', flush=True)
    print('Disk inventory BEFORE cleanup:', flush=True)
    subprocess.run(['df', '-h', os.environ['RUNNER_TEMP']], check=True)
    for path in [active, *targets, Path('/Library/Developer/CoreSimulator')]:
        if path.exists():
            run_optional(['sudo', '-n', 'du', '-xsh', str(path)])

    # Chromium's macOS target does not require iOS/tvOS/watchOS simulators.
    # Use Apple's APIs to unmount/delete runtimes instead of rm on mounted images.
    run_optional(['xcrun', 'simctl', 'shutdown', 'all'])
    run_optional(['xcrun', 'simctl', 'delete', 'all'])
    run_optional(['xcrun', 'simctl', 'runtime', 'delete', 'all'])
    for path in targets:
        print(f'Removing unused hosted-runner Xcode: {path}', flush=True)
        subprocess.run(['sudo', '-n', 'rm', '-rf', '--', str(path)], check=True)

    print('Disk inventory AFTER cleanup:', flush=True)
    subprocess.run(['df', '-h', os.environ['RUNNER_TEMP']], check=True)
    # Ensure the kept toolchain remains usable before any source downloads.
    subprocess.run(['xcodebuild', '-version'], check=True)
    subprocess.run(['xcrun', '--sdk', 'macosx', '--show-sdk-version'], check=True)


if __name__ == '__main__':
    main()

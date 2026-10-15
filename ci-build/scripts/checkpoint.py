#!/usr/bin/env python3
"""Bounded Ninja-output checkpoints; content-validate source mtimes on restore.

Only public build inputs/outputs are stored, never HOME or credentials. The
checkout itself is downloaded afresh. No compiler-cache sloppiness is enabled.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import time

OUT = Path('chromium/src/out/WindowButtonsCI')
MANIFEST = 'checkpoint-inputs.json'
MAX_BYTES = 8 * 1024**3  # One snapshot fits the default 10 GB repository quota.
VERSION = 1


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(root):
    script = (root / 'ci-build/scripts/build-macos.sh').read_text()
    pins = {}
    for name in ('chromium_revision', 'depot_revision'):
        match = re.search(rf'^{name}=([a-f0-9]{{40}})$', script, re.M)
        if not match:
            raise ValueError(f'Missing pinned revision: {name}')
        pins[name] = match[1]
    pins.update(version=VERSION, variant=os.environ['VARIANT'],
                args=digest(root / 'ci-build/args.gn'),
                patch=digest(root / 'ci-build/patches/window-buttons-ui.patch'),
                image=os.environ.get('ImageVersion', 'unknown'),
                workspace=str(Path(os.environ['RUNNER_TEMP']) / 'window-buttons-ci'),
                arch=subprocess.check_output(['uname', '-m'], text=True).strip(),
                xcode=subprocess.check_output(['xcodebuild', '-version'], text=True).strip(),
                sdk=subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-build-version'], text=True).strip())
    value = hashlib.sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()[:32]
    return f'window-buttons-ninja-v{VERSION}-{value}', pins


def input_files(work):
    # Follow neither .git object stores nor symlinked SDKs. Only public source
    # and toolchain files in the private workspace are eligible for mtimes.
    for base in (work / 'depot_tools', work / 'chromium/src'):
        for directory, dirs, files in os.walk(base, followlinks=False):
            directory = Path(directory)
            dirs[:] = [d for d in dirs if d not in ('.git', '.cipd', '__pycache__')
                       and not (directory / d).is_symlink()
                       and directory / d != work / 'chromium/src/out']
            for name in files:
                path = directory / name
                if not path.is_symlink() and path.is_file():
                    yield path


def capture_inputs(work):
    records = []
    for path in input_files(work):
        stat = path.stat()
        records.append([path.relative_to(work).as_posix(), stat.st_size,
                        stat.st_mtime_ns, digest(path)])
    return records


def restore_mtimes(work, records):
    matched = changed = 0
    for name, size, mtime, sha in records:
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Unsafe input-manifest path')
        if relative.parts[0] not in ('depot_tools', 'chromium'):
            raise ValueError('Unexpected input-manifest root')
        path = work / name
        # Never change an SDK/external file through a symlink.
        if path.is_symlink() or not path.resolve().is_relative_to(work.resolve()):
            changed += 1
        elif path.is_file() and path.stat().st_size == size and digest(path) == sha:
            os.utime(path, ns=(path.stat().st_atime_ns, mtime))
            matched += 1
        else:
            # Leave fresh timestamps intact: Ninja must rebuild changed inputs.
            changed += 1
    print(f'Checkpoint inputs: {matched} content matches restored; {changed} changed/missing inputs left fresh', flush=True)
    return matched, changed


def extract(stream, work):
    """Allow SDK links, but no traversal, device files or writes through links."""
    directories = []
    expanded = 0
    output_root = work / OUT
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            parts = relative.parts
            if relative.is_absolute() or '..' in parts:
                raise ValueError('Unsafe checkpoint member')
            if member.name != MANIFEST and parts[:len(OUT.parts)] != OUT.parts:
                raise ValueError(f'Unexpected checkpoint member: {member.name}')
            expanded += member.size
            if expanded > 100 * 1024**3:
                raise ValueError('Checkpoint expansion exceeds 100 GiB')
            target = work / member.name
            allowed_parent = work if member.name == MANIFEST or target == output_root else output_root
            if not target.parent.resolve().is_relative_to(allowed_parent.resolve()):
                raise ValueError('Checkpoint writes through an external link')
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                if target.is_symlink():
                    raise ValueError('Directory is a symlink')
                target.mkdir(exist_ok=True)
                directories.append((target, member))
            elif member.issym():
                resolved = (target.parent / member.linkname).resolve()
                sdk = Path('/Applications/Xcode_26.3.app').resolve()
                if not (resolved.is_relative_to(work.resolve()) or resolved.is_relative_to(sdk)):
                    raise ValueError(f'Unexpected external checkpoint link: {member.linkname}')
                if target.exists() or target.is_symlink():
                    raise ValueError('Duplicate checkpoint link')
                target.symlink_to(member.linkname)
            elif member.isfile() or member.islnk():
                if target.is_symlink():
                    raise ValueError('Checkpoint file is a symlink')
                if member.islnk():
                    source = work / member.linkname
                    if not source.resolve().is_relative_to((work / OUT).resolve()) or source.is_symlink():
                        raise ValueError('Unsafe checkpoint hard link')
                    shutil.copyfile(source, target)
                else:
                    with archive.extractfile(member) as source, target.open('wb') as dest:
                        shutil.copyfileobj(source, dest)
                target.chmod(member.mode & 0o777)
                os.utime(target, (member.mtime, member.mtime))
            else:
                raise ValueError('Unsupported checkpoint entry')
    for path, member in reversed(directories):
        path.chmod(member.mode & 0o777)
        os.utime(path, (member.mtime, member.mtime))


def save(work, cache, identity, limit=MAX_BYTES):
    if not (work / 'build-started').is_file() or not (work / OUT / '.ninja_log').is_file():
        print('No Ninja progress to checkpoint', flush=True)
        return False
    cache.mkdir(parents=True, exist_ok=True)
    # The restored snapshot is no longer needed; never upload a stale snapshot
    # under a new key if snapshot generation or the size check fails.
    for name in ('snapshot.tar.zst', 'snapshot.json'):
        (cache / name).unlink(missing_ok=True)
    start = time.monotonic()
    records = capture_inputs(work)
    # BSD tar may round file mtimes to whole seconds. Ninja also records exact
    # output timestamps in .ninja_deps, so preserve nanoseconds separately.
    outputs = []
    for directory, _, files in os.walk(work / OUT, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink() and path.is_file():
                outputs.append([path.relative_to(work).as_posix(), path.stat().st_mtime_ns])
    (work / MANIFEST).write_text(json.dumps(dict(inputs=records, outputs=outputs), separators=(',', ':')))
    print(f'Checkpoint captured {len(records)} source/tool input hashes and {len(outputs)} output timestamps', flush=True)
    archive = cache / 'snapshot.tar.zst'
    tar = subprocess.Popen(['tar', '-cf', '-', '-C', str(work), str(OUT), MANIFEST], stdout=subprocess.PIPE)
    compressor = subprocess.Popen(['zstd', '-T2', '-3', '-c'], stdin=tar.stdout, stdout=subprocess.PIPE)
    tar.stdout.close()
    try:
        with archive.open('wb') as dest:
            total = 0
            while True:
                block = compressor.stdout.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise ValueError(f'Compressed checkpoint exceeds {limit} bytes; no upload permitted')
                dest.write(block)
        if compressor.wait() or tar.wait():
            raise RuntimeError('Checkpoint compression failed')
    except BaseException:
        compressor.kill()
        tar.kill()
        compressor.wait()
        tar.wait()
        archive.unlink(missing_ok=True)
        raise
    finally:
        compressor.stdout.close()
    metadata = dict(identity=identity, sha256=digest(archive), bytes=total,
                    inputs=len(records), seconds=round(time.monotonic() - start, 1))
    (cache / 'snapshot.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Checkpoint saved: {json.dumps(metadata)}', flush=True)
    return True


def restore(work, cache, identity):
    metadata_path = cache / 'snapshot.json'
    if not metadata_path.is_file():
        print('No compatible checkpoint; starting cold', flush=True)
        return False
    metadata = json.loads(metadata_path.read_text())
    archive = cache / 'snapshot.tar.zst'
    if metadata['identity'] != identity or archive.stat().st_size > MAX_BYTES or digest(archive) != metadata['sha256']:
        raise ValueError('Checkpoint identity/size/checksum mismatch')
    if (work / OUT).exists():
        raise ValueError('Refusing to overwrite existing build outputs')
    decompressor = subprocess.Popen(['zstd', '-dc', str(archive)], stdout=subprocess.PIPE)
    try:
        extract(decompressor.stdout, work)
        if decompressor.wait():
            raise RuntimeError('Checkpoint decompression failed')
    finally:
        if decompressor.poll() is None:
            decompressor.kill()
            decompressor.wait()
        decompressor.stdout.close()
    manifest = json.loads((work / MANIFEST).read_text())
    for name, mtime in manifest['outputs']:
        path = work / name
        if path.is_symlink() or not path.resolve().is_relative_to((work / OUT).resolve()):
            raise ValueError('Unsafe output timestamp path')
        os.utime(path, ns=(path.stat().st_atime_ns, mtime))
    restore_mtimes(work, manifest['inputs'])
    print(f'Restored Ninja checkpoint: {metadata["bytes"]} compressed bytes', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('key', 'save', 'restore'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--work', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--identity')
    args = parser.parse_args()
    if args.command == 'key':
        identity, pins = fingerprint(args.root)
        print(f'identity={identity}')
        (args.root / 'logs').mkdir(exist_ok=True)
        (args.root / 'logs/checkpoint-key.json').write_text(json.dumps(pins, indent=2) + '\n')
    else:
        if not all((args.work, args.cache, args.identity)):
            parser.error('work, cache and identity are required')
        function = save if args.command == 'save' else restore
        ready = function(args.work.resolve(), args.cache.resolve(), args.identity)
        if args.command == 'save' and os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write(f'ready={str(ready).lower()}\n')


if __name__ == '__main__':
    main()

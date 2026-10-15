#!/usr/bin/env python3
"""Small-file tests only: no Chromium download, compile, or browser launch."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest

import checkpoint as cp


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or os.environ.get('RUNNER_TEMP'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.src = self.work / 'chromium/src'
        self.src.mkdir(parents=True)
        self.cache = self.root / 'cache'

    def test_hash_validation_and_timestamp_restore(self):
        same = self.src / 'same.h'
        changed = self.src / 'changed.h'
        same.write_text('same')
        changed.write_text('old!')
        old = 1600000000123456789
        os.utime(same, ns=(old, old))
        os.utime(changed, ns=(old, old))
        records = cp.capture_inputs(self.work)
        now = time.time_ns()
        os.utime(same, ns=(now, now))
        changed.write_text('new!')  # Same length, different content.
        self.assertEqual(cp.restore_mtimes(self.work, records), (1, 1))
        self.assertEqual(same.stat().st_mtime_ns, old)
        self.assertNotEqual(changed.stat().st_mtime_ns, old)

    def test_source_walk_excludes_git_outputs_and_external_links(self):
        (self.src / 'a.h').write_text('header')
        for directory in (self.src / '.git', self.work / cp.OUT):
            directory.mkdir(parents=True)
            (directory / 'ignored').write_text('ignore')
        external = self.root / 'external'
        external.write_text('not a source input')
        (self.src / 'link.h').symlink_to(external)
        self.assertEqual([p.name for p in cp.input_files(self.work)], ['a.h'])

    def test_manifest_rejects_traversal(self):
        with self.assertRaises(ValueError):
            cp.restore_mtimes(self.work, [['../../external', 1, 1, 'hash']])

    def test_manifest_never_touches_external_target(self):
        external = self.root / 'external'
        external.write_text('test')
        before = external.stat().st_mtime_ns
        (self.src / 'link').symlink_to(external)
        record = ['chromium/src/link', 4, 123, cp.digest(external)]
        self.assertEqual(cp.restore_mtimes(self.work, [record]), (0, 1))
        self.assertEqual(external.stat().st_mtime_ns, before)

    def test_extract_rejects_traversal_and_external_writes(self):
        for name in ('../../escape', '/absolute', 'depot_tools/bad'):
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode='w') as archive:
                member = tarfile.TarInfo(name)
                member.size = 1
                archive.addfile(member, io.BytesIO(b'x'))
            data.seek(0)
            with self.assertRaises(ValueError):
                cp.extract(data, self.work)

    def test_extract_rejects_writes_through_a_source_link(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            link = tarfile.TarInfo(str(cp.OUT / 'link'))
            link.type = tarfile.SYMTYPE
            link.linkname = '../..'  # src is inside work but NOT in build outputs.
            archive.addfile(link)
            member = tarfile.TarInfo(str(cp.OUT / 'link/overwrite.h'))
            member.size = 1
            archive.addfile(member, io.BytesIO(b'x'))
        data.seek(0)
        with self.assertRaises(ValueError):
            cp.extract(data, self.work)
        self.assertFalse((self.src / 'overwrite.h').exists())

    def test_no_progress_does_not_create_cache(self):
        self.assertFalse(cp.save(self.work, self.cache, 'id'))
        self.assertFalse(self.cache.exists())

    def fixture(self):
        out = self.work / cp.OUT
        out.mkdir(parents=True, exist_ok=True)
        (out / '.ninja_log').write_text('# ninja log v5\n')
        (out / 'result.o').write_bytes(b'object contents' * 10)
        (self.work / 'build-started').touch()
        (self.src / 'header.h').write_text('public source')
        return out

    def test_archive_roundtrip_preserves_inputs_outputs_and_links(self):
        out = self.fixture()
        (out / 'sdk').symlink_to('/Applications/Xcode_26.3.app')
        before = (self.src / 'header.h').stat().st_mtime_ns
        self.assertTrue(cp.save(self.work, self.cache, 'id'))
        shutil.rmtree(out)
        os.utime(self.src / 'header.h', None)
        self.assertTrue(cp.restore(self.work, self.cache, 'id'))
        self.assertEqual((out / 'result.o').read_bytes(), b'object contents' * 10)
        self.assertTrue((out / 'sdk').is_symlink())
        self.assertEqual((self.src / 'header.h').stat().st_mtime_ns, before)

    def test_archive_size_cap_removes_stale_snapshot(self):
        self.fixture()
        self.cache.mkdir()
        (self.cache / 'snapshot.json').write_text('stale')
        with self.assertRaises(ValueError):
            cp.save(self.work, self.cache, 'id', limit=1)
        self.assertFalse((self.cache / 'snapshot.tar.zst').exists())
        self.assertFalse((self.cache / 'snapshot.json').exists())

    def test_restore_rejects_wrong_identity_and_corruption(self):
        self.fixture()
        cp.save(self.work, self.cache, 'id')
        with self.assertRaises(ValueError):
            cp.restore(self.work, self.cache, 'other')
        archive = self.cache / 'snapshot.tar.zst'
        archive.write_bytes(archive.read_bytes() + b'corruption')
        with self.assertRaises(ValueError):
            cp.restore(self.work, self.cache, 'id')

    def test_real_ninja_resumes_after_fresh_checkout_and_invalidates_change(self):
        if not shutil.which('ninja'):
            self.skipTest('ninja is not installed')
        out = self.work / cp.OUT
        out.mkdir(parents=True)
        source = self.src / 'input.txt'
        source.write_text('first source')
        (self.src / 'header.h').write_text('dependency')
        (out / 'build.ninja').write_text(
            'rule copy\n'
            '  command = cp $in $out && echo "$out: ../../header.h" > $out.d\n'
            '  depfile = $out.d\n'
            '  deps = gcc\n'
            'build result.o: copy ../../input.txt\n')
        subprocess.run(['ninja', '-C', str(out)], check=True, capture_output=True)
        (self.work / 'build-started').touch()
        cp.save(self.work, self.cache, 'id')
        shutil.rmtree(out)
        source.unlink()
        source.write_text('first source')  # Fresh clone, identical bytes, new mtime.
        os.utime(self.src / 'header.h', None)
        cp.restore(self.work, self.cache, 'id')
        result = subprocess.run(['ninja', '-C', str(out), '-n'], check=True, capture_output=True, text=True)
        self.assertIn('no work to do', result.stdout)
        # An actual source edit MUST still cause a rebuild, including same-size edits.
        source.write_text('other source')
        result = subprocess.run(['ninja', '-C', str(out), '-n'], check=True, capture_output=True, text=True)
        self.assertNotIn('no work to do', result.stdout)


if __name__ == '__main__':
    unittest.main()

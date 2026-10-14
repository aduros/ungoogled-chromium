#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from variant import short_variant


class HelpersTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=os.environ.get('TMPDIR') or os.environ['RUNNER_TEMP'])
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'config.json'
        self.valid = dict(mode='probe', runner_labels=['macos-15'],
                          variant='explicit', min_free_gib=80, build_jobs=0)

    def test_valid_config(self):
        self.config.write_text(json.dumps(self.valid))
        self.assertEqual(load_config(self.config), self.valid)

    def test_reject_bad_config(self):
        for key, value in [('mode', 'publish'), ('variant', 'anything'),
                           ('build_jobs', True), ('min_free_gib', 0),
                           ('runner_labels', []), ('runner_labels', ['x\ny'])]:
            with self.subTest(key=key, value=value):
                self.config.write_text(json.dumps(dict(self.valid, **{key: value})))
                with self.assertRaises(ValueError):
                    load_config(self.config)

    def test_short_variant_only_changes_intended_anchors(self):
        original = ('#include "base/mac/mac_util.h"\n'
                    '- (void)maybeShowTrafficLights {\n'
                    '  if (!_alwaysShowTrafficLights) { return; }\n}\n')
        result = short_variant(original)
        self.assertIn('#include "base/command_line.h"', result)
        self.assertIn('HasSwitch(\n          "hide-window-buttons")', result)
        self.assertIn('  if (!_alwaysShowTrafficLights) { return; }\n}\n', result)
        self.assertNotIn('button.hidden', result)
        self.assertNotIn('- (void)layout', result)

    def test_variant_rejects_changed_or_duplicate_source(self):
        with self.assertRaises(ValueError):
            short_variant('unexpected upstream source')
        with self.assertRaises(ValueError):
            short_variant('#include "base/mac/mac_util.h"\n' * 2)

    def test_deadline_stops_a_long_running_group(self):
        helper = Path(__file__).with_name('deadline.py')
        start = time.monotonic()
        result = subprocess.run([sys.executable, str(helper), str(int(time.time()) + 2),
                                 sys.executable, '-c', 'import time; time.sleep(30)'],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertLess(time.monotonic() - start, 10)

    def test_deadline_preserves_command_exit_code(self):
        helper = Path(__file__).with_name('deadline.py')
        result = subprocess.run([sys.executable, str(helper), str(int(time.time()) + 10),
                                 sys.executable, '-c', 'raise SystemExit(7)'])
        self.assertEqual(result.returncode, 7)


if __name__ == '__main__':
    unittest.main()

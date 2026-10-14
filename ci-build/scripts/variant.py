#!/usr/bin/env python3
"""Create the reviewer's minimal alternative from the pinned ORIGINAL source."""
import argparse
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one source anchor: {old!r}")
    return text.replace(old, new, 1)


def short_variant(original):
    original = replace_once(
        original,
        '#include "base/mac/mac_util.h"',
        '#include "base/command_line.h"\n#include "base/mac/mac_util.h"',
    )
    return replace_once(
        original,
        '- (void)maybeShowTrafficLights {\n',
        '- (void)maybeShowTrafficLights {\n'
        '  if (base::CommandLine::ForCurrentProcess()->HasSwitch(\n'
        '          "hide-window-buttons")) {\n'
        '    return;\n'
        '  }\n',
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(short_variant(args.original.read_text()))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate the push-triggered experiment config and emit Actions outputs."""
import json
import re
import sys
from pathlib import Path


def load_config(path):
    config = json.loads(Path(path).read_text())
    expected = {"mode", "runner_labels", "variant", "min_free_gib", "build_jobs"}
    if not isinstance(config, dict) or set(config) != expected:
        raise ValueError(f"Config must contain exactly {sorted(expected)}")
    if config["mode"] not in {"probe", "build"}:
        raise ValueError("mode must be probe or build")
    if config["variant"] not in {"explicit", "short", "both"}:
        raise ValueError("variant must be explicit, short or both")
    labels = config["runner_labels"]
    if not isinstance(labels, list) or not 1 <= len(labels) <= 8:
        raise ValueError("runner_labels must be a nonempty JSON list")
    if any(not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", label)
           for label in labels):
        raise ValueError("Invalid runner label")
    for key, minimum, maximum in [("min_free_gib", 1, 9999), ("build_jobs", 0, 256)]:
        value = config[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be an integer between {minimum} and {maximum}")
    return config


def main():
    config = load_config(sys.argv[1])
    for key, value in config.items():
        if key == "runner_labels":
            value = json.dumps(value, separators=(",", ":"))
        print(f"{key}={value}")


if __name__ == "__main__":
    main()

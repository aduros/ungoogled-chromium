#!/usr/bin/env python3
"""Stop the entire build process group before Actions' hard job deadline."""
import os
import signal
import subprocess
import sys
import time


def main():
    remaining = int(sys.argv[1]) - time.time()
    if remaining <= 0:
        raise SystemExit("Build deadline reached; leaving time to upload logs")
    process = subprocess.Popen(sys.argv[2:], start_new_session=True)
    try:
        return process.wait(timeout=remaining)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return process.wait()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        print("Build timed out; a failed run is not a completed artifact", file=sys.stderr)
        return 124


if __name__ == "__main__":
    sys.exit(main())

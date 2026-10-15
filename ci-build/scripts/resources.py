#!/usr/bin/env python3
"""Sample hosted Mac VM/swap state; no process arguments or credentials logged."""
from datetime import datetime, timezone
import json
import subprocess
import sys
import time


def main():
    with open(sys.argv[1], 'a', buffering=1) as output:
        while True:
            record = {'time': datetime.now(timezone.utc).isoformat()}
            for name, command in (
                    ('vm', ['vm_stat']),
                    ('swap', ['sysctl', 'vm.swapusage']),
                    ('pressure', ['memory_pressure', '-Q'])):
                try:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                    record[name] = result.stdout.strip()
                except (OSError, subprocess.TimeoutExpired) as error:
                    record[name] = type(error).__name__
            output.write(json.dumps(record) + '\n')
            time.sleep(120)


if __name__ == '__main__':
    main()

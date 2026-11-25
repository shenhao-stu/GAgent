"""Run signed iOS boot, bridge, wire-format and Python behavioral tests in fresh interpreters."""
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main():
    commands = [[sys.executable, str(HERE / filename)] for filename in
                ("t1_kernel_boot.py", "t2_bridge_contract.py", "t3_pclink_primitives.py")]
    cases = sorted(HERE.glob("test_*.py"))
    commands.append([sys.executable, "-m", "pytest", "-q", *map(str, cases)])
    for cmd in commands:
        subprocess.run(cmd, cwd=HERE.parents[1], check=True,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    print("PASS: signed iOS runtime suites")


if __name__ == "__main__":
    main()

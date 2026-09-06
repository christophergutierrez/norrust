"""Run the repository's fast, non-tournament verification checks."""
from __future__ import annotations

import shutil
import subprocess
import sys


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    run(["cargo", "test", "--lib", "--manifest-path", "norrust_core/Cargo.toml"])
    run([
        "cargo", "test", "--manifest-path", "norrust_core/Cargo.toml",
        "--test", "campaign", "--test", "dialogue", "--test", "driver_protocol",
        "--test", "scenario_validation", "--test", "simulation", "--test", "test_ffi",
    ])
    run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-t", "."])
    luajit = shutil.which("luajit")
    if luajit:
        run([luajit, "norrust_love/test_llm_bridge.lua"])
    else:
        print("SKIP: luajit is not installed; Lua bridge smoke test unavailable", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the repository's fast, non-tournament verification checks."""
from __future__ import annotations

import shutil
import subprocess
import sys
import os


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
    library = os.path.join("norrust_core", "target", "debug", "libnorrust_core.so")
    if not luajit:
        raise RuntimeError("LuaJIT is required for the headless bridge smoke test")
    if not os.path.exists(library):
        raise RuntimeError(f"built bridge library not found: {library}")
    env = dict(os.environ, NORRUST_LIB=os.path.abspath(library))
    print("$", luajit, "norrust_love/test_llm_bridge.lua", flush=True)
    subprocess.run([luajit, "norrust_love/test_llm_bridge.lua"], check=True, env=env)
    love = shutil.which("love")
    if not love or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("NOTE: GUI smoke is separate and requires Love2D plus a display", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

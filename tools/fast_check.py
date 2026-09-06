"""Run the repository's fast, non-tournament verification checks."""
from __future__ import annotations

import shutil
import subprocess
import sys
import os
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "norrust_core/Cargo.toml"


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("$", " ".join(command), flush=True)
    return subprocess.run(command, check=True, cwd=ROOT, **kwargs)


def main() -> int:
    luajit = shutil.which("luajit")
    if not luajit:
        raise RuntimeError("LuaJIT is required for the headless bridge smoke test")
    run(["cargo", "test", "--lib", "--manifest-path", MANIFEST])
    for binary in ("greedy_driver", "self-play"):
        run(["cargo", "test", "--bin", binary, "--manifest-path", MANIFEST])
    for suite in ("campaign", "dialogue", "driver_protocol", "scenario_validation", "simulation", "test_ffi"):
        run(["cargo", "test", "--test", suite, "--manifest-path", MANIFEST])
    # Cargo's artifact messages also honor target-dir settings in environment and config.
    built = run(["cargo", "build", "--lib", "--bin", "greedy_driver", "--bin", "self-play",
                 "--manifest-path", MANIFEST, "--message-format=json"],
                stdout=subprocess.PIPE, text=True)
    library = None
    driver = None
    for line in built.stdout.splitlines():
        artifact = json.loads(line)
        if artifact.get("reason") != "compiler-artifact":
            continue
        target = artifact.get("target", {})
        if target.get("name") == "norrust_core" and "cdylib" in target.get("kind", []):
            library = next((p for p in artifact["filenames"]
                            if Path(p).suffix in {".so", ".dylib", ".dll"}), None)
        if target.get("name") == "greedy_driver" and "bin" in target.get("kind", []):
            driver = artifact.get("executable")
    if not library or not Path(library).is_file() or not driver or not Path(driver).is_file():
        raise RuntimeError("Cargo did not produce the bridge library and model driver")
    env = dict(os.environ, NORRUST_LIB=library, NORRUST_TEST_DRIVER=driver)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-t", "."], env=env)
    run([luajit, "norrust_love/test_llm_bridge.lua"], env=env)
    run(["git", "diff", "--check"])
    print("NOTE: interactive GUI acceptance is separate from this headless gate", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The gate must test artifacts from its own build and propagate failures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from . import fast_check


class FastCheckTests(unittest.TestCase):
    def test_bridge_uses_cargo_artifact_path_and_binary_tests_run(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "custom-target" / "libnorrust_core.so"
            driver = Path(directory) / "custom-target" / "greedy_driver"
            calls = []

            def execute(command, **kwargs):
                calls.append((command, kwargs))
                output = ""
                if command[:2] == ["cargo", "build"]:
                    library.parent.mkdir()
                    library.touch()
                    driver.touch()
                    output = "\n".join(json.dumps({"reason": "compiler-artifact",
                        "target": {"name": name, "kind": kind}, "filenames": [str(path)],
                        "executable": executable}) for name, kind, path, executable in (
                            ("norrust_core", ["cdylib", "rlib"], library, None),
                            ("greedy_driver", ["bin"], driver, str(driver))))
                return subprocess.CompletedProcess(command, 0, stdout=output)

            with patch.object(fast_check.subprocess, "run", side_effect=execute), \
                    patch.object(fast_check.shutil, "which", return_value="/test/luajit"), \
                    patch.dict(os.environ, {"CARGO_TARGET_DIR": str(library.parent)}):
                self.assertEqual(fast_check.main(), 0)
            bridge = [(c, k) for c, k in calls if c[0] == "/test/luajit"]
            self.assertEqual(len(bridge), 1)
            self.assertEqual(bridge[0][1]["env"]["NORRUST_LIB"], str(library))
            for binary in ("greedy_driver", "self-play"):
                self.assertTrue(any(c[:2] == ["cargo", "test"] and "--bin" in c
                                    and c[c.index("--bin") + 1] == binary for c, _ in calls))
            python = [k for c, k in calls if "discover" in c]
            self.assertEqual(python[0]["env"]["NORRUST_TEST_DRIVER"], str(driver))

    def test_failed_component_stops_the_gate(self):
        failure = subprocess.CalledProcessError(7, ["cargo", "test"])
        with patch.object(fast_check.shutil, "which", return_value="/test/luajit"), \
                patch.object(fast_check.subprocess, "run", side_effect=failure) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                fast_check.main()
        self.assertEqual(run.call_count, 1)

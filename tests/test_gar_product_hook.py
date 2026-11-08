import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.runtime.product_hook import ProductSimulatorHook


class ProductHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tools").mkdir()
        (self.root / "tools/simulator.py").write_text("pass\n")
        (self.root / "gar-simulator.json").write_text(
            json.dumps({"schema_version": 1, "entrypoint": "tools/simulator.py"})
        )
        self.hook = ProductSimulatorHook(SimpleNamespace(local_root=self.root))

    def test_entrypoint_stays_in_workspace(self):
        for entry in ("../outside.py", "/absolute.py", "tools/missing.py", "tools/simulator.cmd"):
            (self.root / "gar-simulator.json").write_text(json.dumps({"schema_version": 1, "entrypoint": entry}))
            with self.assertRaises(GarDomainError):
                self.hook._entry()

    def test_actions_use_python_argument_arrays_without_shell(self):
        with patch("scripts.gar_lib.simulation.runtime.product_hook.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0)
            self.hook.start({})
            args, kwargs = run.call_args
            self.assertEqual(args[0][1:], [str(self.root / "tools/simulator.py"), "start"])
            self.assertNotIn("shell", kwargs)

    def test_diagnostics_preserve_running_snapshot_identity(self):
        with patch.object(
            self.hook, "_run", return_value={"ok": True, "runningBuildId": "built-123", "deployedBuildId": "built-123"}
        ):
            value = self.hook.observe({}, diagnostic=True)
        self.assertTrue(value["app"]["ok"])
        self.assertEqual(value["app"]["running_build_id"], "built-123")

    def test_invalid_diagnostics_never_report_ready(self):
        with patch.object(self.hook, "_run", side_effect=GarDomainError("offline")):
            value = self.hook.observe({}, diagnostic=True)
        self.assertFalse(value["connection"]["ok"])
        self.assertFalse(value["app"]["ok"])

    def test_unverified_snapshots_never_reach_deployment_hook(self):
        artifact = SimpleNamespace(bundle_path=self.root)
        with (
            patch("scripts.gar_lib.simulation.runtime.product_hook.load_artifact_metadata", return_value=None),
            patch("scripts.gar_lib.simulation.runtime.product_hook.subprocess.run") as run,
        ):
            with self.assertRaises(GarDomainError):
                self.hook._run("deploy", artifact=artifact)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

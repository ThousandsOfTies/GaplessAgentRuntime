import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.target.probe import run_target_probe


class TargetProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workspace = SimpleNamespace(local_root=self.root, name="Test/Product", selected_target="linux-device")
        (self.root / "probe.py").write_text("pass", encoding="utf-8")
        self.write_spec()

    def write_spec(self, **overrides):
        spec = {"schema_version": 1, "entrypoint": "probe.py", "probes": ["status"]}
        spec.update(overrides)
        (self.root / "gar-target-probe.json").write_text(json.dumps(spec), encoding="utf-8")

    @patch("scripts.gar_lib.target.probe.subprocess.run")
    def test_json_and_exit_status_bound_to_workspace(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout='{"ok":true,"value":42}')
        report = run_target_probe(self.workspace)
        self.assertTrue(report["ok"])
        self.assertEqual(report["value"], 42)
        self.assertEqual(report["verification"], "probe_only")
        self.assertEqual(run.call_args.kwargs["timeout"], 90)
        self.assertEqual(run.call_args.args[0][-1], "status")
        run.return_value = SimpleNamespace(returncode=1, stdout='{"ok":true}')
        self.assertFalse(run_target_probe(self.workspace)["ok"])

    @patch("scripts.gar_lib.target.probe.subprocess.run")
    def test_undeclared_probe_never_runs(self, run):
        with self.assertRaises(GarDomainError):
            run_target_probe(self.workspace, "status; echo unsafe")
        run.assert_not_called()

    def test_rejects_entry_outside_workspace(self):
        self.write_spec(entrypoint="../other.py")
        with self.assertRaises(GarDomainError):
            run_target_probe(self.workspace)

    def test_rejects_string_probe_list(self):
        self.write_spec(probes="status")
        with self.assertRaises(GarDomainError):
            run_target_probe(self.workspace)

    @patch("scripts.gar_lib.target.probe.subprocess.run")
    def test_invalid_hook_output_is_not_echoed(self, run):
        run.return_value = SimpleNamespace(returncode=1, stdout="secret-value", stderr="other-secret")
        with self.assertRaises(GarDomainError) as caught:
            run_target_probe(self.workspace)
        self.assertNotIn("secret-value", str(caught.exception))
        self.assertNotIn("other-secret", str(caught.exception))

    @patch("scripts.gar_lib.target.probe.subprocess.run")
    def test_timeout_is_bounded_and_sanitized(self, run):
        run.side_effect = subprocess.TimeoutExpired("secret-command", 90)
        with self.assertRaisesRegex(GarDomainError, "timed out") as caught:
            run_target_probe(self.workspace)
        self.assertNotIn("secret-command", str(caught.exception))

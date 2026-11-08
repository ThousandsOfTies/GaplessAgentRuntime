import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.target.wifi import configure_audio, configure_wifi, trace_conversation


class TargetWifiTests(unittest.TestCase):
    @patch("scripts.gar_lib.target.wifi.subprocess.run")
    def test_conversation_trace_only_forwards_allowlisted_observations(self, run):
        (self.root / "gar-target-trace.json").write_text(self.spec.read_text(), encoding="utf-8")
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"ok": True, "trace": {"activeSessions": 1, "counts": {"modelTurns": 2}}, "password": "private"}
            ),
        )
        result = trace_conversation(self.workspace)
        self.assertEqual(result["trace"]["counts"]["modelTurns"], 2)
        self.assertNotIn("password", result)

    @patch("scripts.gar_lib.target.wifi.subprocess.run")
    def test_audio_recipe_uses_separate_descriptor_and_allowlisted_fields(self, run):
        (self.root / "gar-target-audio.json").write_text(self.spec.read_text(), encoding="utf-8")
        run.return_value = SimpleNamespace(
            returncode=0, stdout=json.dumps({"ok": True, "saved": True, "restoreVerified": True, "password": "private"})
        )
        result = configure_audio(self.workspace)
        self.assertTrue(result["saved"])
        self.assertTrue(result["restoreVerified"])
        self.assertNotIn("password", result)

    def test_serial_check_does_not_open_setup(self):
        with self.assertRaises(GarDomainError):
            configure_wifi(SimpleNamespace(), transport="serial", check=True)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workspace = SimpleNamespace(local_root=self.root, name="Test/Product", selected_target="linux-device")
        (self.root / "setup.py").write_text("pass", encoding="utf-8")
        self.spec = self.root / "gar-target-wifi.json"
        self.spec.write_text(json.dumps({"schema_version": 1, "entrypoint": "setup.py"}), encoding="utf-8")

    @patch("scripts.gar_lib.target.wifi.subprocess.run")
    def test_only_allowlisted_result_fields_leave_recipe(self, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"ok": True, "address": "192.0.2.3", "password": "private", "unexpected": "private"}),
        )
        result = configure_wifi(self.workspace)
        self.assertTrue(result["ok"])
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(run.call_args.kwargs["timeout"], 900)
        self.assertEqual(run.call_args.args[0][-2:], ["--transport", "ssh"])

    @patch("scripts.gar_lib.target.wifi.subprocess.run")
    def test_failed_output_and_timeout_not_echoed(self, run):
        for error in [
            SimpleNamespace(returncode=1, stdout="private-output"),
            subprocess.TimeoutExpired("private-command", 900),
        ]:
            if isinstance(error, Exception):
                run.side_effect = error
            else:
                run.return_value = error
            with self.assertRaises(GarDomainError) as caught:
                configure_wifi(self.workspace)
            self.assertNotIn("private", str(caught.exception))

    @patch("scripts.gar_lib.target.wifi.subprocess.run")
    def test_descriptor_cannot_escape_workspace(self, run):
        self.spec.write_text(json.dumps({"schema_version": 1, "entrypoint": "../outside.py"}), encoding="utf-8")
        with self.assertRaises(GarDomainError):
            configure_wifi(self.workspace)
        run.assert_not_called()

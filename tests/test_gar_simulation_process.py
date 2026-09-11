from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.gar_lib.simulation.runtime.process import (
    LocalProcessChannel,
    ManagedProcess,
    ProcessStateStore,
)


class GarSimulationProcessTest(unittest.TestCase):
    def test_process_state_store_replaces_complete_json_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "runtime" / "state.json"
            store = ProcessStateStore(state_path)

            with store.locked():
                store.write({"pid": 1234, "argv": ["simulator"]})

            self.assertEqual(
                {"pid": 1234, "argv": ["simulator"]},
                store.read(),
            )
            self.assertEqual([], list(state_path.parent.glob(".state.json.*.tmp")))

    def test_process_state_store_treats_invalid_state_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("truncated", encoding="utf-8")

            self.assertEqual({}, ProcessStateStore(state_path).read())

    def test_managed_process_rejects_non_positive_persisted_pid(self) -> None:
        state = {"pid": 0, "argv": ["simulator"], "start_time_ticks": 9876}

        self.assertIsNone(ManagedProcess.from_state(state))

    def test_local_process_channel_launches_without_simulator_specific_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "runtime.log"
            process = mock.Mock(pid=1234)
            with (
                mock.patch(
                    "scripts.gar_lib.simulation.runtime.process.subprocess.Popen", return_value=process
                ) as popen,
                mock.patch.object(
                    LocalProcessChannel,
                    "_start_time_ticks",
                    return_value=9876,
                ),
            ):
                result = LocalProcessChannel().start(
                    ("simulator", "--project", str(root)),
                    cwd=root,
                    log_path=log_path,
                )

        self.assertEqual(1234, result.pid)
        self.assertEqual(("simulator", "--project", str(root)), result.argv)
        self.assertEqual(9876, result.start_time_ticks)
        self.assertEqual(root, popen.call_args.kwargs["cwd"])
        if os.name == "nt":
            self.assertEqual(subprocess.CREATE_NEW_PROCESS_GROUP, popen.call_args.kwargs["creationflags"])
        else:
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_process_ownership_requires_argv_and_start_time_to_match(self) -> None:
        channel = LocalProcessChannel()
        process = ManagedProcess(1234, ("simulator", "--project", "/tmp/project"), 9876)

        with (
            mock.patch.object(channel, "_is_running", return_value=True),
            mock.patch.object(channel, "_argv", return_value=process.argv),
            mock.patch.object(channel, "_start_time_ticks", return_value=9876),
        ):
            self.assertTrue(channel.owns(process))

        with (
            mock.patch.object(channel, "_is_running", return_value=True),
            mock.patch.object(channel, "_argv", return_value=("another-program",)),
            mock.patch.object(channel, "_start_time_ticks", return_value=9876),
        ):
            self.assertFalse(channel.owns(process))

        with (
            mock.patch.object(channel, "_is_running", return_value=True),
            mock.patch.object(channel, "_argv", return_value=process.argv),
            mock.patch.object(channel, "_start_time_ticks", return_value=9999),
        ):
            self.assertFalse(channel.owns(process))

    def test_terminate_refuses_a_reused_pid(self) -> None:
        channel = LocalProcessChannel()
        process = ManagedProcess(1234, ("simulator",), 9876)

        with (
            mock.patch.object(channel, "owns", return_value=False),
            mock.patch(
                "scripts.gar_lib.simulation.runtime.process.psutil.Process"
                if os.name == "nt"
                else "scripts.gar_lib.simulation.runtime.process.os.killpg"
            ) as terminate,
        ):
            terminated = channel.terminate_group(process)

        self.assertFalse(terminated)
        terminate.assert_not_called()

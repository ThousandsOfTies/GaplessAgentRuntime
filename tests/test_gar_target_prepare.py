"""Tests for the one-time constrained sudo bootstrap."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.target.ssh_prepare import prepare_ssh_target


class TargetPrepareTests(TestCase):
    def test_prepare_stages_and_runs_the_target_owned_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp)
            (recipe / "prepare.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (recipe / "gar-target-install").write_text("#!/bin/sh\n", encoding="utf-8")
            (recipe / "gar-app@.service").write_text("[Service]\n", encoding="utf-8")

            staged_identity = ""

            def completed(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                nonlocal staged_identity
                stdout = "user\n" if argv[-1] == "id -un" else ""
                if argv[0] == "scp":
                    identity_path = next(Path(item) for item in argv if Path(item).name == "recipe-version")
                    staged_identity = identity_path.read_text(encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, stdout, "")

            with mock.patch("scripts.gar_lib.target.ssh_prepare.subprocess.run", side_effect=completed) as run:
                prepare_ssh_target(
                    "raspi5",
                    recipe,
                    target_id="raspberry-pi-5",
                    recipe_version="7",
                    gar_tools_commit="a" * 40,
                    config_path=Path("/tmp/ssh-config"),
                )

        scp_command = run.call_args_list[2].args[0]
        self.assertEqual("scp", scp_command[0])
        self.assertIn(str(recipe / "prepare.sh"), scp_command)
        self.assertIn(str(recipe / "gar-target-install"), scp_command)
        self.assertIn(str(recipe / "gar-app@.service"), scp_command)
        self.assertTrue(any(Path(item).name == "recipe-version" for item in scp_command))
        self.assertEqual(
            "target_id=raspberry-pi-5\n" "recipe_version=7\n" f"gar_tools_commit={'a' * 40}\n",
            staged_identity,
        )

        bootstrap = run.call_args_list[3].args[0]
        self.assertIn("-tt", bootstrap)
        self.assertIn("/prepare.sh user ", bootstrap[-1])
        self.assertIn("/gar-app@.service", bootstrap[-1])
        self.assertTrue(bootstrap[-1].endswith("/recipe-version"))

    def test_prepare_rejects_untrusted_recipe_identity_before_ssh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp)
            with (
                mock.patch("scripts.gar_lib.target.ssh_prepare.subprocess.run") as run,
                self.assertRaisesRegex(GarDomainError, "target ID"),
            ):
                prepare_ssh_target(
                    "raspi5",
                    recipe,
                    target_id="raspberry-pi-5\nrecipe_version=99",
                    recipe_version="7",
                    gar_tools_commit="a" * 40,
                )

        run.assert_not_called()

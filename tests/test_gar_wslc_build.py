from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.gar_lib.access.channel import AccessResult
from scripts.gar_lib.access.wslc import WslcCliChannel, find_wslc
from scripts.gar_lib.build.docker import BUILD_SPEC_FINGERPRINT_LABEL, build_cache_volume_name
from scripts.gar_lib.build.environment import build_environment_for
from scripts.gar_lib.build.wslc import WslcBuildEnvironment
from scripts.gar_lib.commands.setup import run_setup
from scripts.gar_lib.commands.setup.environment_setup import (
    EnvironmentSelectionStatus,
    grouped_environments,
    select_environment_for_category,
)
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.config import PROJECT_ROOT
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.environments.discovery import discover_environments
from scripts.gar_lib.environments.registry.codespace.local_docker import LocalDockerDevelopmentSetup
from scripts.gar_lib.environments.registry.codespace.wslc import WslcDevelopmentSetup
from scripts.gar_lib.target.manifest import TargetManifest


class WslcBuildTest(unittest.TestCase):
    def test_windows_offers_wslc_first_and_enter_selects_it(self) -> None:
        with mock.patch("scripts.gar_lib.environments.registry.codespace.wslc.os", SimpleNamespace(name="nt")):
            environments = discover_environments()
        category = next(group for group in grouped_environments(environments) if group.id == "codespace")
        self.assertEqual(["wslc", "local", "github_codespaces"], [env.environment_id for env in category.environments])
        with mock.patch("builtins.input", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            selection = select_environment_for_category(category, {"selected_environments": {}})
        self.assertIs(WslcDevelopmentSetup, selection.environment)

    def test_non_windows_keeps_docker_first(self) -> None:
        with mock.patch("scripts.gar_lib.environments.registry.codespace.wslc.os", SimpleNamespace(name="posix")):
            environments = discover_environments()
        builds = [env.environment_id for env in environments if env.category_id == "codespace"]
        self.assertEqual(["local", "wslc", "github_codespaces"], builds)

    def test_existing_docker_selection_is_preserved_when_order_changes(self) -> None:
        with mock.patch("scripts.gar_lib.environments.registry.codespace.wslc.os", SimpleNamespace(name="nt")):
            environments = discover_environments()
        category = next(group for group in grouped_environments(environments) if group.id == "codespace")
        config = {"selected_environments": {"codespace": "local"}}
        with (
            mock.patch.object(LocalDockerDevelopmentSetup, "missing_commands", return_value=[]),
            mock.patch("builtins.input", return_value=""),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            selection = select_environment_for_category(category, config)
        self.assertIs(EnvironmentSelectionStatus.SKIPPED, selection.status)
        self.assertEqual("local", config["selected_environments"]["codespace"])

    def test_new_windows_setup_saves_wslc_as_the_default_choice(self) -> None:
        with mock.patch("scripts.gar_lib.environments.registry.codespace.wslc.os", SimpleNamespace(name="nt")):
            environments = [env for env in discover_environments() if env.category_id == "codespace"]
        target = TargetManifest(
            id="test-target",
            display_name="Test Target",
            description="test",
            tools_root="targets/test",
            default_backends={},
            backend_notes={},
        )
        config = {"selected_target": "test-target", "selected_environments": {}}
        with (
            mock.patch("scripts.gar_lib.commands.setup.command.discover_environments", return_value=environments),
            mock.patch("scripts.gar_lib.commands.setup.command.discover_target_manifests", return_value=[target]),
            mock.patch("scripts.gar_lib.commands.setup.command.load_config", return_value=config),
            mock.patch("scripts.gar_lib.commands.setup.command.save_config") as save,
            mock.patch("scripts.gar_lib.commands.setup.command.sys.stdin.isatty", return_value=False),
            mock.patch(
                "scripts.gar_lib.commands.setup.command.installed_vscode_terminal_bridge_path", return_value=None
            ),
            mock.patch.object(WslcDevelopmentSetup, "missing_commands", return_value=[]),
            mock.patch("builtins.input", side_effect=["", "", "q"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = run_setup(no_install=True)
        self.assertEqual(0, result)
        save.assert_called_once_with({"selected_target": "test-target", "selected_environments": {"codespace": "wslc"}})

    def test_command_discovery_prefers_path(self) -> None:
        with mock.patch("scripts.gar_lib.access.wslc.shutil.which", return_value="installed-wslc"):
            self.assertEqual("installed-wslc", find_wslc())

    def test_windows_installation_is_found_without_an_updated_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / "WSL" / "wslc.exe"
            installed.parent.mkdir()
            installed.touch()
            with (
                mock.patch("scripts.gar_lib.access.wslc.shutil.which", return_value=None),
                mock.patch("scripts.gar_lib.access.wslc.os", SimpleNamespace(name="nt", environ={"ProgramFiles": tmp})),
            ):
                self.assertEqual(str(installed), find_wslc())
                self.assertEqual([], WslcDevelopmentSetup.missing_commands())

    def test_missing_command_gives_update_hint_without_falling_back_to_docker(self) -> None:
        with mock.patch("scripts.gar_lib.access.wslc.find_wslc", return_value=None):
            with self.assertRaisesRegex(GarDomainError, "wsl --update"):
                WslcCliChannel().run(("run", "image"))

    def test_cli_preserves_windows_paths_and_failure_exit_code(self) -> None:
        command = ("run", "--mount", r"type=bind,source=D:\source with spaces,target=/workspace", "image")
        with (
            mock.patch("scripts.gar_lib.access.wslc.find_wslc", return_value="wslc.exe"),
            mock.patch("scripts.gar_lib.access.wslc.subprocess.run") as run,
        ):
            run.return_value = SimpleNamespace(returncode=23, stdout="", stderr="compile failed")
            result = WslcCliChannel().run(command)
        self.assertEqual(("wslc.exe", *command), run.call_args.args[0])
        self.assertEqual(23, result.returncode)

    def test_json_inspection_reuses_matching_default_image(self) -> None:
        fingerprint = hashlib.sha256((PROJECT_ROOT / "infra/build/Dockerfile").read_bytes()).hexdigest()
        image = {"Config": {"Labels": {BUILD_SPEC_FINGERPRINT_LABEL: fingerprint}}}
        for payload in (image, [image]):
            with self.subTest(payload=payload):
                channel = mock.Mock()
                channel.run.return_value = AccessResult(("wslc",), 0, json.dumps(payload))
                environment = WslcBuildEnvironment(mock.Mock(), wslc=channel)
                environment._ensure_default_image("gar-build-env:ubuntu-24.04")
                channel.run.assert_called_once_with(
                    ("image", "inspect", "--format", "json", "gar-build-env:ubuntu-24.04")
                )

    def test_stale_or_missing_image_is_rebuilt(self) -> None:
        for inspection in (AccessResult(("wslc",), 0, '{"Config":{}}'), AccessResult(("wslc",), 1)):
            with self.subTest(inspection=inspection):
                channel = mock.Mock()
                channel.run.side_effect = [inspection, AccessResult(("wslc",), 0)]
                WslcBuildEnvironment(mock.Mock(), wslc=channel)._ensure_default_image("gar-build-env:ubuntu-24.04")
                self.assertEqual("build", channel.run.call_args.args[0][0])

    def test_invalid_inspection_is_not_treated_as_a_cache_hit(self) -> None:
        channel = mock.Mock()
        channel.run.return_value = AccessResult(("wslc",), 0, "not JSON")
        with self.assertRaisesRegex(GarDomainError, "JSON"):
            WslcBuildEnvironment(mock.Mock(), wslc=channel)._ensure_default_image("image")

    def test_selected_backend_builds_with_cache_and_captures_only_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts/product-target-build.sh").touch()
            workspace = Workspace(
                id="wslc-test",
                name="Local/Product",
                branch="main",
                connection={"type": "local", "path": str(root)},
                selected_target="esp32",
                selected_environments={"codespace": "wslc"},
                build={"image": "custom-image", "cache": True},
            )
            artifacts = mock.Mock()
            environment = build_environment_for(workspace, artifacts)
            self.assertIsInstance(environment, WslcBuildEnvironment)
            channel = mock.Mock()
            channel.run.return_value = AccessResult(("wslc",), 0)
            environment.docker = channel
            environment.build(ArtifactKind.TARGET_APP, workspace)
            arguments = channel.run.call_args.args[0]
            self.assertIn(f"type=bind,source={root.resolve()},target=/workspace", arguments)
            self.assertIn(
                f"type=volume,source={build_cache_volume_name(workspace.id)},target=/gar-build-cache", arguments
            )
            self.assertIn("GAR_TARGET=esp32", arguments)
            artifacts.capture.assert_called_once_with(ArtifactKind.TARGET_APP, workspace)
            artifacts.reset_mock()
            channel.run.return_value = AccessResult(("wslc",), 17, "", "compile failed")
            with self.assertRaisesRegex(GarDomainError, "compile failed"):
                environment.build(ArtifactKind.TARGET_APP, workspace)
            artifacts.capture.assert_not_called()
            channel.reset_mock()
            with self.assertRaisesRegex(GarDomainError, "docker_socket"):
                environment.build(ArtifactKind.TARGET_APP, replace(workspace, build={"docker_socket": True}))
            channel.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

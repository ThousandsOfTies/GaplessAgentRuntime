from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from scripts.gar_lib.api import Gar
from scripts.gar_lib.artifacts.metadata import ArtifactTarget, load_artifact_metadata, write_artifact_metadata
from scripts.gar_lib.artifacts.provenance import CaptureProvenance
from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.cli import build_parser, main
from scripts.gar_lib.commands.completion import parser_completion_words
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.target.lifecycle import (
    TargetApplication,
    TargetDeploymentReport,
    TargetDiagnosticReport,
    TargetLifecycleResult,
)


def workspace(root: Path = Path("/test/product")) -> Workspace:
    return Workspace(
        id="action-surface",
        name="Local/Product",
        branch="main",
        connection={"type": "local", "path": str(root)},
        selected_environments={"codespace": "local", "simulator": "local_docker"},
        docker={"arch": "x86_64"},
    )


class ActionSurfaceCliTest(unittest.TestCase):
    def test_old_and_new_sim_spellings_resolve_to_the_same_operation(self) -> None:
        parser = build_parser()
        for subject, actions in (
            ("app", ("build", "deploy", "clean")),
            ("runtime", ("build", "deploy", "start", "stop", "status", "log", "diag")),
            ("host", ("start", "stop", "status")),
        ):
            for action in actions:
                with self.subTest(subject=subject, action=action):
                    expected = GarCommand("sim", subject, action)
                    for path in ((subject, action), (action, subject)):
                        args = parser.parse_args(["sim", *path, "--workspace", "Local/Product"])
                        self.assertEqual(expected, args.gar_command)
                    self.assertEqual(f"gar sim {action} {subject}", expected.to_cli())

    def test_sim_defaults_and_specialized_operations_remain_distinct(self) -> None:
        parser = build_parser()
        for action, subject in (
            ("build", None),
            ("deploy", None),
            ("clean", "app"),
            ("start", "runtime"),
            ("stop", "runtime"),
            ("status", None),
            ("log", "runtime"),
            ("diag", None),
        ):
            with self.subTest(action=action):
                self.assertEqual(GarCommand("sim", subject, action), parser.parse_args(["sim", action]).gar_command)
        self.assertEqual("gar sim gpio start", parser.parse_args(["sim", "gpio", "start"]).gar_command.to_cli())

    def test_subject_can_follow_options(self) -> None:
        args = build_parser().parse_args(["sim", "start", "--workspace", "Local/Product", "host", "--pull"])
        self.assertEqual(GarCommand("sim", "host", "start"), args.gar_command)
        self.assertTrue(args.pull)

    def test_completion_promotes_actions_and_offers_optional_subjects(self) -> None:
        for words, present, absent in (
            (
                ["gar", "sim", ""],
                {"build", "deploy", "start", "stop", "gpio", "io", "infra"},
                {"app", "runtime", "host"},
            ),
            (["gar", "sim", "build", ""], {"app", "runtime"}, {"host"}),
            (["gar", "sim", "start", ""], {"runtime", "host"}, {"app"}),
            (["gar", "sim", "start", "host", ""], {"--workspace", "--pull"}, {"runtime", "host", "--panel-port"}),
            (["gar", "sim", "start", "--workspace", "Local/Product", ""], {"runtime", "host"}, {"app"}),
            (["gar", "sim", "build", "--workspace", ""], set(), {"runtime", "app", "--workspace"}),
            (["gar", "code", ""], {"start", "stop", "status"}, {"boot", "shutdown"}),
            (["gar", "code", "stop", ""], {"session", "host"}, {"shutdown"}),
            (["gar", "code", "stop", "host", ""], {"--workspace", "--codespace"}, {"--shutdown", "--settings"}),
        ):
            with self.subTest(words=words):
                candidates = set(parser_completion_words(len(words) - 1, words, build_parser))
                self.assertTrue(present <= candidates, candidates)
                self.assertFalse(absent & candidates, candidates)

    def test_help_explains_subject_option_scope(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, main(["sim", "start", "?"]))
        self.assertIn("host 専用", output.getvalue())
        self.assertIn("runtime 専用", output.getvalue())

    def test_invalid_subject_options_fail_before_workspace_or_external_work(self) -> None:
        for argv in (
            ["sim", "start", "host", "--panel-port", "8080"],
            ["sim", "start", "runtime", "--pull"],
            ["sim", "start", "--pull"],
            ["sim", "stop", "host", "--keep-port-forward"],
            ["code", "start", "host", "--no-mount"],
            ["code", "stop", "host", "--shutdown"],
        ):
            with (
                self.subTest(argv=argv),
                mock.patch("scripts.gar_lib.commands.sim.resolve_workspace") as resolve,
                mock.patch("scripts.gar_lib.commands.code.run_code_command") as code,
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                self.assertEqual(1, main(argv))
                self.assertIn("--", errors.getvalue())
                resolve.assert_not_called()
                code.assert_not_called()

    def test_default_start_stop_do_not_control_host_or_build_or_deploy(self) -> None:
        for action in ("start", "stop"):
            with (
                self.subTest(action=action),
                mock.patch("scripts.gar_lib.commands.sim.resolve_workspace", return_value=workspace()),
                mock.patch("scripts.gar_lib.commands.sim.Gar") as factory,
            ):
                simulation = factory.return_value.sim
                getattr(simulation.runtime, action).return_value = 0
                self.assertEqual(0, main(["sim", action]))
                getattr(simulation.runtime, action).assert_called_once()
                self.assertEqual([], simulation.host.mock_calls)
                simulation.build.assert_not_called()
                simulation.deploy.assert_not_called()
                simulation.app.build.assert_not_called()
                simulation.runtime.build.assert_not_called()
                simulation.runtime.deploy.assert_not_called()

    def test_aggregate_build_and_deploy_use_public_api(self) -> None:
        for action in ("build", "deploy"):
            with (
                self.subTest(action=action),
                mock.patch("scripts.gar_lib.commands.sim.resolve_workspace", return_value=workspace()),
                mock.patch("scripts.gar_lib.commands.sim.Gar") as factory,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                getattr(factory.return_value.sim, action).return_value = (
                    mock.Mock(bundle_path="runtime-snapshot"),
                    mock.Mock(bundle_path="app-snapshot"),
                )
                self.assertEqual(0, main(["sim", action]))
                getattr(factory.return_value.sim, action).assert_called_once_with()
                self.assertIn("runtime-snapshot", output.getvalue())
                self.assertIn("app-snapshot", output.getvalue())

    def test_code_host_actions_keep_boot_shutdown_compatibility(self) -> None:
        for action, legacy in (("start", "boot"), ("stop", "shutdown")):
            for argv in (["code", action, "host"], ["code", legacy]):
                with (
                    self.subTest(argv=argv),
                    mock.patch("scripts.gar_lib.commands.code.run_code_command", return_value=0) as run,
                ):
                    self.assertEqual(0, main([*argv, "--workspace", "Local/Product", "--codespace", "demo"]))
                    self.assertEqual((legacy,), run.call_args.args)
                    self.assertEqual("Local/Product", run.call_args.kwargs["workspace_selector"])
                    self.assertEqual("demo", run.call_args.kwargs["codespace"])


class SimulationArtifactSetTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.workspace = workspace(root)
        self.store = LocalArtifactStore(snapshot_root=root / "snapshots")
        bundle = self.store.bundle_path(self.workspace)
        bundle.mkdir(parents=True)
        (bundle / "app").write_text("application", encoding="utf-8")
        (bundle / "runtime").write_text("runtime", encoding="utf-8")
        (bundle / "artifact.json").write_text(
            json.dumps(
                {
                    "name": "demo",
                    "deploy": {
                        "app": {"files": [{"src": "app", "dest": "/opt/demo/app"}]},
                        "sim_env": {"files": [{"src": "runtime", "dest": "/opt/demo/runtime"}]},
                    },
                }
            ),
            encoding="utf-8",
        )
        provenance = CaptureProvenance(source_commit="a" * 40, gar_tools_commit="b" * 40, target=ArtifactTarget())
        self.runtime = self.store.capture(ArtifactKind.SIM_RUNTIME, self.workspace, provenance)
        self.app = self.store.capture(ArtifactKind.SIM_APP, self.workspace, provenance)

    def test_build_requires_runtime_only_for_backends_that_use_it(self) -> None:
        for requires_runtime, kinds in (
            (True, (ArtifactKind.SIM_RUNTIME, ArtifactKind.SIM_APP)),
            (False, (ArtifactKind.SIM_APP,)),
        ):
            with (
                self.subTest(requires_runtime=requires_runtime),
                mock.patch("scripts.gar_lib.api.simulation_environment_for") as environment,
                mock.patch("scripts.gar_lib.api.build_environment_for") as build,
            ):
                environment.return_value.requires_runtime_artifact = requires_runtime
                Gar(self.workspace, self.store).sim.build()
                self.assertEqual(
                    [mock.call(kind, self.workspace) for kind in kinds], build.return_value.build.call_args_list
                )
                environment.return_value.deploy.assert_not_called()

    def test_deploy_checks_all_snapshots_before_first_transfer_without_build_or_fetch(self) -> None:
        for requires_runtime, expected in ((True, (self.runtime, self.app)), (False, (self.app,))):
            with (
                self.subTest(requires_runtime=requires_runtime),
                mock.patch("scripts.gar_lib.api.simulation_environment_for") as environment,
                mock.patch("scripts.gar_lib.api.build_environment_for") as build,
                mock.patch.object(self.store, "latest", wraps=self.store.latest) as latest,
            ):
                environment.return_value.requires_runtime_artifact = requires_runtime

                def transfer(artifact, selected=expected, reader=latest):
                    self.assertEqual(len(selected), reader.call_count)

                environment.return_value.deploy.side_effect = transfer
                artifacts = Gar(self.workspace, self.store).sim.deploy()
                self.assertEqual(expected, artifacts)
                self.assertEqual(
                    [mock.call(artifact) for artifact in expected], environment.return_value.deploy.call_args_list
                )
                build.assert_not_called()

    def test_bad_app_checksum_prevents_even_runtime_transfer(self) -> None:
        (self.app.bundle_path / "app").write_text("tampered", encoding="utf-8")
        with mock.patch("scripts.gar_lib.api.simulation_environment_for") as environment:
            environment.return_value.requires_runtime_artifact = True
            with self.assertRaises(GarDomainError):
                Gar(self.workspace, self.store).sim.deploy()
            environment.return_value.deploy.assert_not_called()

    def test_app_architecture_drift_prevents_even_runtime_transfer(self) -> None:
        metadata = load_artifact_metadata(self.app.bundle_path)
        assert metadata is not None
        write_artifact_metadata(
            self.app.bundle_path, replace(metadata, target=replace(metadata.target, architecture="aarch64"))
        )
        with mock.patch("scripts.gar_lib.api.simulation_environment_for") as environment:
            environment.return_value.requires_runtime_artifact = True
            with self.assertRaisesRegex(GarDomainError, "architecture"):
                Gar(self.workspace, self.store).sim.deploy()
            environment.return_value.deploy.assert_not_called()

    def test_missing_app_snapshot_prevents_even_runtime_transfer(self) -> None:
        with (
            mock.patch("scripts.gar_lib.api.simulation_environment_for") as environment,
            mock.patch.object(self.store, "latest", side_effect=[self.runtime, GarDomainError("app missing")]),
        ):
            environment.return_value.requires_runtime_artifact = True
            with self.assertRaisesRegex(GarDomainError, "app missing"):
                Gar(self.workspace, self.store).sim.deploy()
            environment.return_value.deploy.assert_not_called()

    def test_unverifiable_app_metadata_prevents_even_runtime_transfer(self) -> None:
        runtime_metadata = load_artifact_metadata(self.runtime.bundle_path)
        app_metadata = load_artifact_metadata(self.app.bundle_path)
        assert app_metadata is not None
        for metadata in (
            None,
            replace(app_metadata, schema_version=1),
            replace(app_metadata, target=replace(app_metadata.target, architecture=None)),
        ):
            with (
                self.subTest(metadata=metadata),
                mock.patch("scripts.gar_lib.api.simulation_environment_for") as environment,
                mock.patch("scripts.gar_lib.api.load_artifact_metadata", side_effect=[runtime_metadata, metadata]),
            ):
                environment.return_value.requires_runtime_artifact = True
                with self.assertRaises(GarDomainError):
                    Gar(self.workspace, self.store).sim.deploy()
                environment.return_value.deploy.assert_not_called()


class TargetStartCliTest(unittest.TestCase):
    def test_start_reports_convergence_without_claiming_file_placement(self) -> None:
        application = TargetApplication("demo", "build-1")
        report = TargetDeploymentReport(
            application,
            "/snapshot",
            placed=True,
            reload=TargetLifecycleResult("reload", "demo", 0),
            diagnostic=TargetDiagnosticReport(
                application,
                TargetLifecycleResult("status", "demo", 0),
                TargetLifecycleResult("health", "demo", 0),
                TargetLifecycleResult("running-build-id", "demo", 0, stdout="build-1"),
            ),
            verification="lifecycle-v1",
        )
        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=workspace()),
            mock.patch("scripts.gar_lib.api.Target.start", return_value=report) as start,
            mock.patch("scripts.gar_lib.api.Target.deploy") as deploy,
            mock.patch("scripts.gar_lib.api.build_environment_for") as build,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(0, main(["target", "start", "--app", "demo", "--json"]))
        start.assert_called_once_with(app="demo")
        deploy.assert_not_called()
        build.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual("target.start", payload["command"])
        self.assertTrue(payload["running"])
        self.assertNotIn("placed", payload)
        self.assertNotIn("placed_destinations", payload)

    def test_unsupported_target_start_is_a_machine_readable_failure(self) -> None:
        with (
            mock.patch("scripts.gar_lib.commands.target.resolve_workspace", return_value=workspace()),
            mock.patch("scripts.gar_lib.api.Target.start", side_effect=GarDomainError("lifecycle unavailable")),
            contextlib.redirect_stdout(io.StringIO()) as output,
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            self.assertEqual(1, main(["target", "start", "--json"]))
        payload = json.loads(output.getvalue())
        self.assertEqual("target.start", payload["command"])
        self.assertFalse(payload["ok"])
        self.assertEqual("", errors.getvalue())


if __name__ == "__main__":
    unittest.main()

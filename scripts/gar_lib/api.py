"""Programmatic GAR API shared by the CLI and other callers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from scripts.gar_lib.artifacts.metadata import load_artifact_metadata
from scripts.gar_lib.artifacts.store import BuildArtifactStore, LocalArtifactStore
from scripts.gar_lib.build.environment import build_environment_for
from scripts.gar_lib.core.artifact import Artifact, ArtifactKind
from scripts.gar_lib.core.capabilities import require_simulation_action
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.hardware import HardwareDefinition, load_hw_definition
from scripts.gar_lib.core.observation import EnvironmentObservation
from scripts.gar_lib.core.workspace import Workspace
from scripts.gar_lib.simulation.composition import (
    hardware_control_for,
    simulation_environment_for,
    simulation_host_for,
)
from scripts.gar_lib.simulation.deployment import SimulationDeploymentError
from scripts.gar_lib.simulation.diagnostics.model import SimulationDiagnosticReport
from scripts.gar_lib.simulation.hardware.control import HardwareControlResult
from scripts.gar_lib.simulation.host.contract import (
    SimulationHostStartResult,
    SimulationHostState,
)
from scripts.gar_lib.simulation.observation import observe_simulation
from scripts.gar_lib.simulation.session.manager import VsCodeSimulationSessionManager
from scripts.gar_lib.target.application import target_application_from_artifact
from scripts.gar_lib.target.compatibility import CompatibilityReport
from scripts.gar_lib.target.composition import target_environment_for, target_lifecycle_for
from scripts.gar_lib.target.environment import TargetPlacementError
from scripts.gar_lib.target.file_transfer import FileTransferTargetEnvironment, TargetConfigurationReport
from scripts.gar_lib.target.lifecycle import (
    TargetApplication,
    TargetDeploymentConvergenceError,
    TargetDeploymentReport,
    TargetDiagnosticReport,
    TargetLifecycle,
    TargetLifecycleResult,
)


@dataclass(frozen=True)
class TargetDeploymentResult:
    artifact: Artifact
    report: TargetDeploymentReport
    configuration: TargetConfigurationReport | None = None


@dataclass(frozen=True)
class TargetPreflightResult:
    """Read-only proof that one artifact is safe to hand to target deploy."""

    artifact: Artifact
    application: TargetApplication
    compatibility: CompatibilityReport

    @property
    def build_id(self) -> str:
        build_id = self.application.expected_build_id
        if build_id is None:  # pragma: no cover - guarded by preflight resolution
            raise GarDomainError("target preflightにはschema v2 artifact build IDが必要です")
        return build_id

    @property
    def compatible(self) -> bool:
        return self.compatibility.compatible

    @property
    def ok(self) -> bool:
        return self.compatible

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1


class Gar:
    def __init__(self, workspace: Workspace, artifacts: BuildArtifactStore | None = None):
        artifact_store = artifacts if artifacts is not None else LocalArtifactStore()
        self.sim = Simulation(workspace, artifact_store)
        self.target = Target(workspace, artifact_store)


class Simulation:
    def __init__(self, workspace: Workspace, artifacts: BuildArtifactStore):
        self.workspace = workspace
        self.artifacts = artifacts
        self.app = SimulationApp(workspace, artifacts)
        self.runtime = SimulationRuntime(workspace, artifacts)
        self.host = SimulationHost(workspace)
        self.gpio = SimulationGpio(workspace)
        self.io = SimulationIo(workspace)

    def status(self) -> EnvironmentObservation:
        require_simulation_action(self.workspace, "status")
        return observe_simulation(
            self.workspace, _workspace_hardware(self.workspace), diagnostic=False, artifacts=self.artifacts
        )

    def diag(self) -> EnvironmentObservation:
        require_simulation_action(self.workspace, "diag")
        return observe_simulation(
            self.workspace, _workspace_hardware(self.workspace), diagnostic=True, artifacts=self.artifacts
        )

    def build(self) -> tuple[Artifact, ...]:
        """Build the artifacts required by this backend, retaining separate snapshots."""

        require_simulation_action(self.workspace, "build")
        environment = simulation_environment_for(self.workspace)
        build = build_environment_for(self.workspace, self.artifacts)
        kinds = (
            (ArtifactKind.SIM_RUNTIME, ArtifactKind.SIM_APP)
            if environment.requires_runtime_artifact
            else (ArtifactKind.SIM_APP,)
        )
        return tuple(build.build(kind, self.workspace) for kind in kinds)

    def deploy(self) -> tuple[Artifact, ...]:
        """Validate the entire selected set before stopping services or transferring files."""

        require_simulation_action(self.workspace, "deploy")
        environment = simulation_environment_for(self.workspace)
        kinds = (
            (ArtifactKind.SIM_RUNTIME, ArtifactKind.SIM_APP)
            if environment.requires_runtime_artifact
            else (ArtifactKind.SIM_APP,)
        )
        artifacts = tuple(self.artifacts.latest(kind, self.workspace) for kind in kinds)
        for artifact in artifacts:
            _validate_simulation_architecture(artifact, self.workspace, require_snapshot=True)
        completed: list[Artifact] = []
        for artifact in artifacts:
            try:
                environment.deploy(artifact)
            except (GarDomainError, OSError) as error:
                raise SimulationDeploymentError(str(error), completed=completed, failed=artifact) from error
            completed.append(artifact)
        return artifacts


class SimulationApp:
    def __init__(self, workspace: Workspace, artifacts: BuildArtifactStore):
        self.workspace = workspace
        self.artifacts = artifacts

    def build(self) -> Artifact:
        require_simulation_action(self.workspace, "build")
        build = build_environment_for(self.workspace, self.artifacts)
        return build.build(ArtifactKind.SIM_APP, self.workspace)

    def clean(self) -> None:
        require_simulation_action(self.workspace, "clean")
        build_environment_for(self.workspace, self.artifacts).clean(ArtifactKind.SIM_APP, self.workspace)

    def deploy(self) -> Artifact:
        require_simulation_action(self.workspace, "deploy")
        artifact = self.artifacts.latest(ArtifactKind.SIM_APP, self.workspace)
        _validate_simulation_architecture(artifact, self.workspace)
        simulation_environment_for(self.workspace).deploy(artifact)
        return artifact


class SimulationRuntime:
    def __init__(self, workspace: Workspace, artifacts: BuildArtifactStore):
        self.workspace = workspace
        self.artifacts = artifacts

    @property
    def session_host(self) -> str | None:
        return simulation_environment_for(self.workspace).session_host

    def build(self) -> Artifact | None:
        require_simulation_action(self.workspace, "build")
        if not simulation_environment_for(self.workspace).requires_runtime_artifact:
            return None
        return build_environment_for(self.workspace, self.artifacts).build(ArtifactKind.SIM_RUNTIME, self.workspace)

    def deploy(self) -> Artifact | None:
        require_simulation_action(self.workspace, "deploy")
        environment = simulation_environment_for(self.workspace)
        if not environment.requires_runtime_artifact:
            return None
        artifact = self.artifacts.latest(ArtifactKind.SIM_RUNTIME, self.workspace)
        _validate_simulation_architecture(artifact, self.workspace)
        environment.deploy(artifact)
        return artifact

    def configure_system_env(self, application: str, values: Mapping[str, str]) -> str:
        environment = simulation_environment_for(self.workspace)
        configure = getattr(environment, "configure_system_env", None)
        if not callable(configure):
            raise GarDomainError("このsimulation environmentはsystem-managed runtime env設定に未対応です")
        return configure(application, values)

    def start(
        self,
        *,
        settings: str | None = None,
        profile_name: str | None = None,
        no_port_forward: bool = False,
        panel_port: int = 8080,
    ) -> int:
        require_simulation_action(self.workspace, "start")
        environment = simulation_environment_for(self.workspace)
        exit_code = environment.start(_workspace_hardware(self.workspace))
        host = environment.session_host
        if exit_code != 0 or host is None:
            return exit_code

        sessions = VsCodeSimulationSessionManager()
        sessions.configure_terminal(host, settings=settings, profile_name=profile_name)
        if no_port_forward:
            return 0
        return sessions.start(host, panel_port=panel_port)

    def stop(self, *, keep_port_forward: bool = False, panel_port: int = 8080) -> int:
        require_simulation_action(self.workspace, "stop")
        environment = simulation_environment_for(self.workspace)
        exit_code = environment.stop(_workspace_hardware(self.workspace))
        host = environment.session_host
        if exit_code != 0 or host is None or keep_port_forward:
            return exit_code
        sessions = VsCodeSimulationSessionManager()
        return sessions.stop(host, panel_port=panel_port) if panel_port != 8080 else sessions.stop(host)

    def status(self, *, panel_port: int = 8080) -> int:
        require_simulation_action(self.workspace, "status")
        environment = simulation_environment_for(self.workspace)
        host = environment.session_host
        sessions = VsCodeSimulationSessionManager()
        options = {"panel_port": panel_port} if panel_port != 8080 else {}
        session_exit = sessions.status(host, **options) if host is not None else 0
        runtime_exit = environment.status(_workspace_hardware(self.workspace))
        return session_exit or runtime_exit

    def log(self) -> int:
        require_simulation_action(self.workspace, "log")
        return simulation_environment_for(self.workspace).log()

    def diag(self) -> SimulationDiagnosticReport:
        require_simulation_action(self.workspace, "diag")
        environment = simulation_environment_for(self.workspace)
        return environment.diag(_workspace_hardware(self.workspace))


class SimulationHost:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def start(
        self,
        *,
        no_update_ssh: bool = False,
        pull: bool = False,
    ) -> SimulationHostStartResult:
        return simulation_host_for(self.workspace).start(
            update_address=not no_update_ssh,
            update_repository=pull,
        )

    def stop(self) -> None:
        simulation_host_for(self.workspace).stop()

    def status(self) -> SimulationHostState:
        return simulation_host_for(self.workspace).status()


class SimulationGpio:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def install(self) -> HardwareControlResult:
        return self._run("install")

    def start(self) -> HardwareControlResult:
        return self._run("start")

    def stop(self) -> HardwareControlResult:
        return self._run("stop")

    def plan(self) -> HardwareControlResult:
        return self._run("plan")

    def status(self) -> HardwareControlResult:
        return self._run("status")

    def check(self) -> HardwareControlResult:
        return self._run("check")

    def _run(self, action: str) -> HardwareControlResult:
        return hardware_control_for(self.workspace).gpio(
            action,
            _workspace_hardware(self.workspace),
        )


class SimulationIo:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def state(self, **params: object) -> HardwareControlResult:
        return self._run("state", params)

    def press(self, **params: object) -> HardwareControlResult:
        return self._run("press", params)

    def set(self, **params: object) -> HardwareControlResult:
        return self._run("set", params)

    def clear(self, **params: object) -> HardwareControlResult:
        return self._run("clear", params)

    def _run(self, action: str, params: dict[str, object]) -> HardwareControlResult:
        return hardware_control_for(self.workspace).io(action, params)


def _workspace_hardware(workspace: Workspace) -> HardwareDefinition:
    hardware_dir = str(workspace.hardware_dir) if workspace.hardware_dir is not None else None
    return load_hw_definition(hw_dir=hardware_dir)


def _validate_simulation_architecture(
    artifact: Artifact, workspace: Workspace, *, require_snapshot: bool = False
) -> None:
    expected = workspace.simulation_architecture
    if expected is None and not require_snapshot:
        return
    metadata = load_artifact_metadata(artifact.bundle_path)
    if require_snapshot and (metadata is None or metadata.is_legacy):
        raise GarDomainError(
            f"sim deployの一括配置にはchecksum付きsnapshotが必要です: {artifact.kind.value}。gar sim buildを実行してください"
        )
    actual = metadata.target.architecture if metadata is not None else None
    if expected is not None and (require_snapshot or actual is not None) and actual != expected:
        raise GarDomainError(
            f"simulation artifactのarchitectureが現在のSim Hostと一致しません: "
            f"{actual} != {expected}。現在のprofileで再buildしてください"
        )


class Target:
    def __init__(self, workspace: Workspace, artifacts: BuildArtifactStore):
        self.workspace = workspace
        self.artifacts = artifacts

    def build(self) -> Artifact:
        build = build_environment_for(self.workspace, self.artifacts)
        return build.build(ArtifactKind.TARGET_APP, self.workspace)

    def preflight(self, *, app: str | None = None) -> TargetPreflightResult:
        """Probe compatibility without placing files or invoking lifecycle actions."""

        artifact = self.artifacts.latest(ArtifactKind.TARGET_APP, self.workspace)
        application = target_application_from_artifact(
            artifact,
            explicit_name=app,
            require_build_id=True,
        )
        environment = target_environment_for(self.workspace)
        if not isinstance(environment, FileTransferTargetEnvironment):
            raise GarDomainError("選択したTargetはread-only artifact compatibility preflightに対応していません")
        compatibility = environment.validate_deployment(artifact)
        return TargetPreflightResult(
            artifact=artifact,
            application=application,
            compatibility=compatibility,
        )

    def prepare(self) -> None:
        target_environment_for(self.workspace).prepare()

    def configure(self, *, app: str, file: str | Path) -> TargetConfigurationReport:
        """Install persistent target configuration without an artifact dependency."""

        application = TargetApplication(app)
        source = Path(file)
        if source.is_symlink() or not source.is_file():
            raise GarDomainError(f"設定ファイルは既存の通常ファイルである必要があります: {source}")
        environment = target_environment_for(self.workspace)
        if not isinstance(environment, FileTransferTargetEnvironment):
            raise GarDomainError("選択したTargetはrecipe-backed SSH設定配置を提供していません")
        return environment.configure(application.name, source)

    def configure_system_env(self, *, app: str, values: Mapping[str, str]) -> TargetConfigurationReport:
        """Install GAR-owned runtime bindings without requiring an artifact."""

        application = TargetApplication(app)
        environment = target_environment_for(self.workspace)
        if not isinstance(environment, FileTransferTargetEnvironment):
            raise GarDomainError("選択したTargetはrecipe-backed SSH設定配置を提供していません")
        return environment.configure_system_env(application.name, values)

    def deploy(
        self,
        *,
        system_env_app: str | None = None,
        system_env: Mapping[str, str] | None = None,
    ) -> Artifact:
        return self.deploy_report(system_env_app=system_env_app, system_env=system_env).artifact

    def deploy_report(
        self,
        *,
        system_env_app: str | None = None,
        system_env: Mapping[str, str] | None = None,
    ) -> TargetDeploymentResult:
        if (system_env_app is None) != (system_env is None):
            raise GarDomainError("target system envにはappとvaluesの両方が必要です")
        artifact = self.artifacts.latest(ArtifactKind.TARGET_APP, self.workspace)
        environment = target_environment_for(self.workspace)
        # Compatibility is a hard pre-transfer boundary.  In particular, a
        # wrong-target artifact must not even update the topology-owned env.
        environment.validate_deployment(artifact)
        lifecycle = target_lifecycle_for(self.workspace)
        application = (
            target_application_from_artifact(artifact, require_build_id=True) if lifecycle is not None else None
        )
        configuration = None
        if system_env is not None:
            assert system_env_app is not None
            requested_application = TargetApplication(system_env_app)
            if lifecycle is None or application is None:
                raise GarDomainError("target system envにはapplication lifecycle capabilityが必要です")
            if requested_application.name != application.name:
                raise GarDomainError(
                    "target system envのappがlatest artifactと一致しません: "
                    f"{requested_application.name} != {application.name}"
                )
            if not isinstance(environment, FileTransferTargetEnvironment):
                raise GarDomainError("選択したTargetはrecipe-backed SSH設定配置を提供していません")
            configuration = environment.configure_system_env(requested_application.name, system_env)
        verification = "lifecycle-v1" if lifecycle is not None else "unavailable"
        try:
            environment.deploy(artifact)
        except TargetPlacementError as error:
            report = TargetDeploymentReport(
                application=application,
                artifact_path=str(artifact.bundle_path),
                placed=True,
                verification=verification,
                partial=error.partial,
                placed_destinations=error.placed_destinations,
                failure=str(error),
            )
            raise TargetDeploymentConvergenceError(report) from error

        if lifecycle is None:
            return TargetDeploymentResult(
                artifact=artifact,
                report=TargetDeploymentReport(
                    application=None,
                    artifact_path=str(artifact.bundle_path),
                    placed=True,
                    verification="unavailable",
                ),
                configuration=configuration,
            )

        assert application is not None
        reload_result = None
        try:
            reload_result = lifecycle.reload(application)
            diagnostic = lifecycle.diag(application)
        except Exception as error:
            report = TargetDeploymentReport(
                application=application,
                artifact_path=str(artifact.bundle_path),
                placed=True,
                reload=reload_result,
                verification=verification,
                failure=str(error),
            )
            raise TargetDeploymentConvergenceError(report) from error
        report = TargetDeploymentReport(
            application=application,
            artifact_path=str(artifact.bundle_path),
            placed=True,
            reload=reload_result,
            diagnostic=diagnostic,
            verification=verification,
        )
        if not reload_result.ok or not report.ok:
            raise TargetDeploymentConvergenceError(report)
        return TargetDeploymentResult(artifact=artifact, report=report, configuration=configuration)

    def status(self, *, app: str | None = None) -> TargetLifecycleResult:
        lifecycle, application = self._lifecycle_application(app)
        return lifecycle.status(application)

    def stop(self, *, app: str | None = None) -> TargetLifecycleResult:
        lifecycle, application = self._lifecycle_application(app)
        return lifecycle.stop(application)

    def start(
        self,
        *,
        app: str | None = None,
        system_env: Mapping[str, str] | None = None,
    ) -> TargetDeploymentReport:
        """Start (or converge) the latest verified target artifact.

        Recipes own the concrete process manager operation.  GAR reloads the
        named application and confirms its health/build identity afterwards,
        matching the convergence performed by target deployment.
        """

        lifecycle = target_lifecycle_for(self.workspace)
        if lifecycle is None:
            raise GarDomainError(
                "選択したTargetはapplication lifecycle capabilityを提供していません。"
                "Target recipeを更新してgar target prepareを実行してください"
            )
        artifact = self.artifacts.latest(ArtifactKind.TARGET_APP, self.workspace)
        environment = target_environment_for(self.workspace)
        # Starting is a physical convergence operation.  Preserve deploy's
        # compatibility boundary before updating any topology-owned file.
        environment.validate_deployment(artifact)
        application = target_application_from_artifact(artifact, require_build_id=True)
        if app is not None and app != application.name:
            raise GarDomainError(f"latest target artifactのappが一致しません: {application.name} != {app}")
        if system_env is not None:
            if app is None:
                raise GarDomainError("target system envにはappが必要です")
            if not isinstance(environment, FileTransferTargetEnvironment):
                raise GarDomainError("選択したTargetはrecipe-backed SSH設定配置を提供していません")
            environment.configure_system_env(application.name, system_env)
        reload_result = lifecycle.reload(application)
        diagnostic = lifecycle.diag(application)
        report = TargetDeploymentReport(
            application=application,
            artifact_path=str(artifact.bundle_path),
            placed=True,
            reload=reload_result,
            diagnostic=diagnostic,
            verification="lifecycle-v1",
        )
        if not reload_result.ok or not report.ok:
            raise TargetDeploymentConvergenceError(report, action="start")
        return report

    def log(self, *, app: str | None = None, lines: int = 200) -> TargetLifecycleResult:
        lifecycle, application = self._lifecycle_application(app)
        return lifecycle.log(application, lines=lines)

    def diag(self, *, app: str | None = None) -> TargetDiagnosticReport:
        lifecycle, application = self._lifecycle_application(app)
        return lifecycle.diag(application)

    def fetch(self) -> Artifact:
        return build_environment_for(self.workspace, self.artifacts).fetch(
            ArtifactKind.TARGET_APP,
            self.workspace,
        )

    def _lifecycle_application(self, app: str | None) -> tuple[TargetLifecycle, TargetApplication]:
        lifecycle = target_lifecycle_for(self.workspace)
        if lifecycle is None:
            raise GarDomainError(
                "選択したTargetはapplication lifecycle capabilityを提供していません。"
                "Target recipeを更新してgar target prepareを実行してください"
            )
        if app is not None:
            return lifecycle, TargetApplication(app)
        artifact = self.artifacts.latest(ArtifactKind.TARGET_APP, self.workspace)
        return lifecycle, target_application_from_artifact(artifact)

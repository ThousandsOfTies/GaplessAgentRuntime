"""Target-owned application lifecycle capability and structured reports.

GAR deliberately does not know whether a target uses systemd, BusyBox init,
or another process manager.  A target recipe exposes the small
``gar-app-lifecycle-v1`` command contract and this module only transports its
actions and exit codes.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Protocol

from scripts.gar_lib.access.channel import AccessResult, CommandChannel
from scripts.gar_lib.core.errors import AccessConnectionError, GarDomainError

_SAFE_APP = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SAFE_BUILD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_SUDO_AUTH_MARKERS = (
    "a password is required",
    "no tty present",
    "not allowed to execute",
    "may not run sudo",
    "sudoers",
)


@dataclass(frozen=True)
class TargetApplication:
    """One deployable application and the artifact expected to be running."""

    name: str
    expected_build_id: str | None = None
    entrypoint: str | None = None

    def __post_init__(self) -> None:
        if _SAFE_APP.fullmatch(self.name) is None:
            raise GarDomainError(f"target application名が不正です: {self.name!r}")
        if self.expected_build_id is not None and _SAFE_BUILD_ID.fullmatch(self.expected_build_id) is None:
            raise GarDomainError(f"artifact build IDが不正です: {self.expected_build_id!r}")


@dataclass(frozen=True)
class TargetLifecycleResult:
    """Uninterpreted result from one recipe-owned lifecycle action."""

    action: str
    application: str
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @classmethod
    def from_access_result(
        cls,
        action: str,
        application: str,
        result: AccessResult | object,
    ) -> TargetLifecycleResult:
        return cls(
            action=action,
            application=application,
            returncode=int(getattr(result, "returncode", 1)),
            stdout=str(getattr(result, "stdout", "") or ""),
            stderr=str(getattr(result, "stderr", "") or ""),
        )

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "action": self.action,
            "application": self.application,
            "ok": self.ok,
            "exit_code": self.returncode,
        }
        if self.stdout:
            payload["stdout"] = self.stdout.rstrip("\n")
        if self.stderr:
            payload["stderr"] = self.stderr.rstrip("\n")
        return payload


@dataclass(frozen=True)
class TargetDiagnosticReport:
    """Combined service, health, and running-artifact observation."""

    application: TargetApplication
    status: TargetLifecycleResult
    health: TargetLifecycleResult
    build_id: TargetLifecycleResult

    @property
    def running_build_id(self) -> str | None:
        if not self.build_id.ok:
            return None
        value = self.build_id.stdout.strip()
        return value or None

    @property
    def build_matches(self) -> bool:
        expected = self.application.expected_build_id
        running = self.running_build_id
        return running is not None and (expected is None or running == expected)

    @property
    def ok(self) -> bool:
        return self.status.ok and self.health.ok and self.build_matches

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_payload(
        self,
        *,
        workspace: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "application": self.application.name,
            "status": self.status.to_payload(),
            "health": self.health.to_payload(),
            "artifact": {
                "expected_build_id": self.application.expected_build_id,
                "running_build_id": self.running_build_id,
                "matches": self.build_matches,
            },
            "ok": self.ok,
        }
        if workspace is not None:
            payload["workspace"] = workspace
        if target_id is not None:
            payload["target_id"] = target_id
        return payload


@dataclass(frozen=True)
class TargetDeploymentReport:
    """Deploy placement and post-deploy convergence result."""

    application: TargetApplication | None
    artifact_path: str
    placed: bool
    reload: TargetLifecycleResult | None = None
    diagnostic: TargetDiagnosticReport | None = None
    verification: str = "unavailable"
    partial: bool = False
    placed_destinations: tuple[str, ...] = ()
    failure: str | None = None

    @property
    def running(self) -> bool | None:
        if self.failure is not None:
            return False
        if self.diagnostic is None:
            return None
        return (self.reload is None or self.reload.ok) and self.diagnostic.ok

    @property
    def ok(self) -> bool:
        return (
            self.placed
            and not self.partial
            and self.failure is None
            and (self.reload is None or self.reload.ok)
            and (self.diagnostic is None or self.diagnostic.ok)
        )

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_payload(
        self,
        *,
        workspace: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "artifact": self.artifact_path,
            "application": self.application.name if self.application is not None else None,
            "expected_build_id": (self.application.expected_build_id if self.application is not None else None),
            "placed": self.placed,
            "partial": self.partial,
            "placed_destinations": list(self.placed_destinations),
            "running": self.running,
            "verification": self.verification,
            "rollback": {"available": False, "attempted": False},
            "ok": self.ok,
        }
        if self.diagnostic is not None:
            payload["diagnostic"] = self.diagnostic.to_payload()
            payload["running_build_id"] = self.diagnostic.running_build_id
        if self.reload is not None:
            payload["reload"] = self.reload.to_payload()
        if self.failure is not None:
            payload["error"] = self.failure
        if workspace is not None:
            payload["workspace"] = workspace
        if target_id is not None:
            payload["target_id"] = target_id
        return payload


class TargetDeploymentConvergenceError(GarDomainError):
    """Artifact placement succeeded but the new application did not converge."""

    def __init__(self, report: TargetDeploymentReport, *, action: str = "deploy"):
        self.report = report
        app = report.application.name if report.application is not None else "unknown"
        expected = report.application.expected_build_id if report.application is not None else None
        detail = f": {report.failure}" if report.failure else ""
        outcome = (
            "target applicationのstart稼働確認に失敗しました"
            if action == "start"
            else "target applicationは配置済みですが稼働確認に失敗しました"
        )
        super().__init__(f"{outcome}: {app} " f"(expected build ID: {expected or 'unknown'}){detail}")


class TargetLifecycle(Protocol):
    def stop(self, application: TargetApplication) -> TargetLifecycleResult: ...

    def status(self, application: TargetApplication) -> TargetLifecycleResult: ...

    def log(self, application: TargetApplication, *, lines: int = 200) -> TargetLifecycleResult: ...

    def health(self, application: TargetApplication) -> TargetLifecycleResult: ...

    def reload(self, application: TargetApplication) -> TargetLifecycleResult: ...

    def running_build_id(self, application: TargetApplication) -> TargetLifecycleResult: ...

    def diag(self, application: TargetApplication) -> TargetDiagnosticReport: ...


class CommandTargetLifecycle:
    """Invoke the lifecycle-v1 command installed by a Target recipe."""

    def __init__(self, command_channel: CommandChannel, command: str, *, supports_stop: bool = False):
        if not command.startswith("/") or any(character in command for character in ("\x00", "\n", "\r")):
            raise GarDomainError(f"target lifecycle commandが不正です: {command!r}")
        self.command_channel = command_channel
        self.command = command
        self.supports_stop = supports_stop
        self._privilege_prefix: str | None = None

    def status(self, application: TargetApplication) -> TargetLifecycleResult:
        return self._run("status", application)

    def stop(self, application: TargetApplication) -> TargetLifecycleResult:
        if not self.supports_stop:
            raise GarDomainError("選択したTarget recipeはstop capabilityを提供していません")
        return self._run("stop", application)

    def log(self, application: TargetApplication, *, lines: int = 200) -> TargetLifecycleResult:
        if lines < 1 or lines > 10000:
            raise GarDomainError("target log --lines は1から10000の範囲で指定してください")
        return self._run("log", application, "--lines", str(lines))

    def health(self, application: TargetApplication) -> TargetLifecycleResult:
        return self._run("health", application)

    def reload(self, application: TargetApplication) -> TargetLifecycleResult:
        if application.expected_build_id is None:
            raise GarDomainError("deploy後のreloadにはartifact build IDが必要です")
        return self._run("reload", application, "--build-id", application.expected_build_id)

    def running_build_id(self, application: TargetApplication) -> TargetLifecycleResult:
        return self._run("running-build-id", application)

    def diag(self, application: TargetApplication) -> TargetDiagnosticReport:
        return TargetDiagnosticReport(
            application=application,
            status=self.status(application),
            health=self.health(application),
            build_id=self.running_build_id(application),
        )

    def _run(
        self,
        action: str,
        application: TargetApplication,
        *arguments: str,
    ) -> TargetLifecycleResult:
        prefix = self._resolve_privilege_prefix()
        command = shlex.join((self.command, action, application.name, *arguments))
        result = self.command_channel.run(f"{prefix}{command}")
        self._raise_sudo_handoff(result)
        return TargetLifecycleResult.from_access_result(action, application.name, result)

    def _resolve_privilege_prefix(self) -> str:
        if self._privilege_prefix is not None:
            return self._privilege_prefix
        result = self.command_channel.run("id -u")
        if getattr(result, "returncode", 1) != 0:
            detail = str(getattr(result, "stderr", "") or getattr(result, "stdout", "")).strip()
            suffix = f": {detail}" if detail else ""
            raise GarDomainError(f"target lifecycleの実行userを確認できません{suffix}")
        self._privilege_prefix = "" if str(getattr(result, "stdout", "")).strip() == "0" else "sudo -n "
        return self._privilege_prefix

    def _raise_sudo_handoff(self, result: AccessResult | object) -> None:
        if not self._privilege_prefix or getattr(result, "returncode", 1) == 0:
            return
        detail = str(getattr(result, "stderr", "") or getattr(result, "stdout", "")).lower()
        if not any(marker in detail for marker in _SUDO_AUTH_MARKERS):
            return
        endpoint = getattr(self.command_channel, "host", "target")
        raise AccessConnectionError(
            channel="ssh",
            endpoint=endpoint if isinstance(endpoint, str) else "target",
            reason="target_prepare_required",
            returncode=int(getattr(result, "returncode", 1)),
        )

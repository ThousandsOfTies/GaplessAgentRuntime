from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import uuid
from abc import ABC
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class CommandStatus:
    name: str
    path: str | None

    @property
    def installed(self) -> bool:
        return self.path is not None


class DevEnvironment(ABC):
    """Base class for Gapless Agent Runtime development environment providers."""

    provider_id: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]
    category_id: ClassVar[str] = "uncategorized"
    category_name: ClassVar[str] = "Uncategorized"
    category_order: ClassVar[int] = 100
    display_order: ClassVar[int] = 100
    required_commands: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def dependency_status(cls) -> list[CommandStatus]:
        return [
            CommandStatus(name=command, path=shutil.which(command))
            for command in cls.required_commands
        ]

    @classmethod
    def missing_commands(cls) -> list[str]:
        return [
            status.name
            for status in cls.dependency_status()
            if not status.installed
        ]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        commands = ", ".join(missing)
        return f"Install the missing command(s): {commands}"

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        print(cls.install_hint(missing))
        return 1

    @classmethod
    def login(cls) -> int:
        return 0

    @classmethod
    def list_instances(cls) -> int:
        return 0

    @classmethod
    def shell(cls, target: str | None = None) -> int:
        return 0

    @classmethod
    def code_command(
        cls,
        command: str,
        *,
        target: str | None = None,
        remote_path: str | None = None,
        mount_dir: str | None = None,
        settings: str | None = None,
        profile_name: str | None = None,
        no_mount: bool = False,
        shutdown: bool = False,
        timeout: int | None = None,
    ) -> int:
        del target, remote_path, mount_dir, settings, profile_name, no_mount, shutdown, timeout
        raise NotImplementedError(f"{cls.__name__} does not implement gar code {command}")

    @classmethod
    def run_subprocess(cls, argv: list[str]) -> int:
        return subprocess.run(argv, check=False).returncode


    @classmethod
    def run_remote(
        cls,
        target: str,
        command: str,
        *,
        capture_output: bool = False,
        text: bool = True,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        raise NotImplementedError(f"{cls.__name__} does not implement run_remote")

    @classmethod
    def push_file(cls, target: str, src: str | Path, dest: str | Path) -> int:
        raise NotImplementedError(f"{cls.__name__} does not implement push_file")

    @classmethod
    def pull_file(cls, target: str, src: str | Path, dest: str | Path) -> int:
        raise NotImplementedError(f"{cls.__name__} does not implement pull_file")

    @classmethod
    def start_port_forward(cls, target: str) -> int:
        raise NotImplementedError(f"{cls.__name__} does not implement start_port_forward")

    @classmethod
    def stop_port_forward(cls, target: str) -> int:
        raise NotImplementedError(f"{cls.__name__} does not implement stop_port_forward")

    @classmethod
    def status_port_forward(cls, target: str) -> int:
        raise NotImplementedError(f"{cls.__name__} does not implement status_port_forward")

    @classmethod
    def interactive_shell_script(cls, target: str) -> str:
        raise NotImplementedError(f"{cls.__name__} does not implement interactive_shell_script")

    @classmethod
    def sudo_block_reason(cls) -> str | None:
        result = subprocess.run(
            ["sudo", "-n", "true"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return None

        stderr = result.stderr.strip()
        if "no new privileges" in stderr.lower():
            return stderr
        if "password is required" in stderr.lower():
            return stderr
        if "terminal" in stderr.lower() and "required" in stderr.lower():
            return stderr

        return None

    @classmethod
    def print_user_terminal_handoff(
        cls,
        title: str,
        commands: list[str],
        *,
        reason: str | None = None,
    ) -> None:
        print()
        print(title)
        if reason:
            print("この実行環境では sudo を直接実行できません:")
            print(textwrap.indent(reason, "  "))
        print("ユーザーの通常ターミナルで次のコマンドを実行してください。")
        print("完了後、もう一度 `gar setup` を実行すると続きから確認できます。")
        print()
        print("```bash")
        for command in commands:
            print(command)
        print("```")

        request_path = cls.create_visible_terminal_request(title, commands)
        print()
        print("VSCode integrated terminal にも実行要求を作成しました:")
        print(f"  {request_path}")
        print("sudo password や認証入力を求められたら、その terminal に直接入力してください。")

    @classmethod
    def create_visible_terminal_request(cls, title: str, commands: list[str]) -> Path:
        request_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        request_id = f"{request_id}-{uuid.uuid4().hex[:8]}"
        cwd = Path.cwd()
        request_dir = cwd / ".gar" / "terminal-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"{request_id}.json"
        request = {
            "id": request_id,
            "created_at": datetime.now(UTC).isoformat(),
            "title": "Gapless Agent Runtime User Action",
            "cwd": str(cwd),
            "command": " && ".join(commands),
            "reason": title,
        }
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return request_path

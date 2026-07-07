from __future__ import annotations

from scripts.gar_lib.environments.base import DevEnvironment


class LocalEnvironment(DevEnvironment):
    provider_id = "local"
    display_name = "Local"
    description = "このマシン上のローカル環境を使います"
    display_order = 90
    required_commands = ()

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
        if command in ("boot", "start"):
            print("Local development environment is already available.")
            return 0
        if command in ("stop", "shutdown"):
            print("Local development environment does not need to be stopped.")
            return 0
        if command == "status":
            print("Local development environment: available")
            return 0

        raise NotImplementedError(f"{cls.__name__} does not implement gar code {command}")

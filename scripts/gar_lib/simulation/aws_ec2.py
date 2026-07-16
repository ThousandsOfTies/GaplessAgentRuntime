"""AWS EC2 implementation of SimulationHostController."""

from __future__ import annotations

import shlex

from scripts.gar_lib.access.aws import AwsCommandChannel
from scripts.gar_lib.access.base import CommandChannel, CommandResult
from scripts.gar_lib.simulation.ssh_config import HostAddressUpdater
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.simulation.host import SimulationHostStartResult, SimulationHostState


class AwsEc2SimulationHostController:
    def __init__(
        self,
        *,
        host: str,
        instance_id: str,
        region: str,
        aws: AwsCommandChannel,
        address_updater: HostAddressUpdater,
        repository_channel: CommandChannel,
        repository_path: str | None = None,
    ):
        self.host = host
        self.instance_id = instance_id
        self.region = region
        self.aws = aws
        self.address_updater = address_updater
        self.repository_channel = repository_channel
        self.repository_path = repository_path

    def start(
        self,
        *,
        update_address: bool = True,
        update_repository: bool = False,
    ) -> SimulationHostStartResult:
        self._require_success(
            self.aws.run(("ec2", "start-instances", "--instance-ids", self.instance_id)),
            "EC2 instanceの起動要求に失敗しました",
        )
        self._require_success(
            self.aws.run(("ec2", "wait", "instance-running", "--instance-ids", self.instance_id)),
            "EC2 instanceがrunningになるのを待機できませんでした",
        )
        state = self.status()
        if not state.running:
            raise GarDomainError(f"EC2 instanceがrunningではありません: {state.state}")
        if state.public_ip is None:
            raise GarDomainError("EC2 instanceのpublic IPを取得できませんでした。")

        address_updated = update_address and self.address_updater.update(self.host, state.public_ip)
        repository_updated = False
        repository_update_skipped = False
        if update_repository:
            if self.repository_path:
                result = self.repository_channel.run(
                    f"cd {shlex.quote(self.repository_path)} && git pull --ff-only"
                )
                self._require_success(result, "simulation host上のgit pullに失敗しました")
                repository_updated = True
            else:
                repository_update_skipped = True

        return SimulationHostStartResult(
            state=state,
            address_updated=address_updated,
            repository_updated=repository_updated,
            repository_update_skipped=repository_update_skipped,
        )

    def stop(self) -> None:
        self._require_success(
            self.aws.run(("ec2", "stop-instances", "--instance-ids", self.instance_id)),
            "EC2 instanceの停止要求に失敗しました",
        )

    def status(self) -> SimulationHostState:
        state = self._query(
            "Reservations[0].Instances[0].State.Name",
            "EC2 instanceの状態を取得できませんでした",
        )
        assert state is not None
        public_ip = self._query(
            "Reservations[0].Instances[0].PublicIpAddress",
            "EC2 instanceのpublic IPを取得できませんでした",
            allow_none=True,
        )
        return SimulationHostState(
            host=self.host,
            instance_id=self.instance_id,
            region=self.region,
            state=state,
            public_ip=public_ip,
        )

    def _query(self, query: str, message: str, *, allow_none: bool = False) -> str | None:
        result = self.aws.run(
            (
                "ec2",
                "describe-instances",
                "--instance-ids",
                self.instance_id,
                "--query",
                query,
                "--output",
                "text",
            )
        )
        self._require_success(result, message)
        value = result.stdout.strip()
        if value and value != "None":
            return value
        if allow_none:
            return None
        raise GarDomainError(message)

    @staticmethod
    def _require_success(result: CommandResult, message: str) -> None:
        if result.returncode == 0:
            return
        detail = result.stderr.strip()
        raise GarDomainError(f"{message} (exit {result.returncode})" + (f": {detail}" if detail else ""))

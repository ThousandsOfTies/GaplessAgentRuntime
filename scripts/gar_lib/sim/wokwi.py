"""Wokwi Simulation Provider (Stub/Skeleton).

This file is a placeholder/stub to guide future implementation of the ESP32 (Wokwi)
simulation target.

# 目的と方針 (Purpose & Policy for Future Agents)
- **目的**: Linux (Raspberry Pi等) の代わりに ESP32 などのマイコン環境をシミュレートする。
- **ツール**: Wokwi CLI (`wokwi-cli`) を使用し、ローカルまたはCI環境からヘッドレスにシミュレータを起動する。
- **アーキテクチャの相違点**:
  - `LinuxSystemdSimProvider` では、リモートサーバー(EC2)にSSHして `systemctl` でサービスを管理し、`/dev/gpiochip` などをモックしていた。
  - `WokwiSimProvider` では、OSが存在しないため、ファームウェア（`.bin` / `.elf`）をローカルでコンパイルし、`wokwi.toml` と `diagram.json` と共に `wokwi-cli` を起動してシミュレーションを実行する。
- **今後の実装タスク**:
  1. `wokwi-cli` がローカル環境 (WSL) にインストールされているかチェックするヘルパーを追加。
  2. `start()` 時に `wokwi-cli` を非同期プロセスとして起動し、シリアル出力をハンドリングする。
  3. `hardware.csv` の定義（ピン配置など）から動的に `diagram.json` を生成する処理を追加（ユーザーがわざわざJSONを書かなくても済むようにする）。
  4. Web/REST APIベースの通信（WiFi経由）や、シリアルポートへのコマンド送信で `panel()` などをエミュレートする。
"""
from __future__ import annotations

from scripts.gar_lib.environments.base import DevEnvironment
from scripts.gar_lib.sim.base import SimCommandBuilder, SimProvider


class WokwiSimCommandBuilder(SimCommandBuilder):
    """Generates commands for Wokwi simulation.

    Since Wokwi is not a Linux environment, there is no `systemd` or `/dev/gpiochip`.
    Many of these methods might return empty strings or specific wokwi-cli commands.
    """

    def build_gpio_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi does not use systemd.")

    def build_sim_diag_json(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_gpio_sim_setup(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        # Instead of Linux gpio-sim, this might generate diagram.json elements.
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_gpio_sim_teardown(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_systemd_install(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi does not use systemd.")

    def build_systemd_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi does not use systemd.")

    def build_systemd_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi does not use systemd.")

    def build_sim_start(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        # Might return "wokwi-cli ."
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_sim_stop(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        # Might return "pkill wokwi-cli"
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_sim_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_sim_log(self) -> str:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_gpio_runtime_status(self, hw_definition: dict[str, list[dict[str, str]]] | None = None) -> str:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def build_panel(self, action: str, params: dict) -> str:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")


class WokwiSimProvider(SimProvider):
    """High-level Wokwi simulation operations."""

    def __init__(self, dev_env: DevEnvironment, host: str | None = None):
        self.dev_env = dev_env
        self.host = host
        self.builder = WokwiSimCommandBuilder()

    def start(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        """Starts the Wokwi simulation.

        Future implementation should:
        1. Parse hw_definition and generate diagram.json.
        2. Execute `wokwi-cli` via self.dev_env.run_remote (or locally).
        """
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def stop(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def status(self, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def log(self) -> int:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def diag_json(self, hw_definition: dict[str, list[dict[str, str]]]) -> int:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def gpio_sim_check(self, json_output: bool = False) -> int:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def gpio_command(self, command: str, hw_definition: dict[str, list[dict[str, str]]], json_output: bool = False) -> int:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

    def panel(self, action: str, params: dict, json_output: bool = False) -> int:
        raise NotImplementedError("Wokwi integration is planned but not yet implemented.")

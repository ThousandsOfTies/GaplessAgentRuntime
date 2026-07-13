"""MuJoCo physics simulation provider."""

from __future__ import annotations

import shutil
import sys

from scripts.gar_lib.environments.base import CommandStatus, EnvironmentSetupOption


class MujocoEnvironment(EnvironmentSetupOption):
    """Local MuJoCo installation used for articulated-robot simulation."""

    provider_id = "mujoco"
    display_name = "MuJoCo（ロボット物理）"
    description = (
        "関節・接触・摩擦を含むロボット物理シミュレーションをローカルで実行します"
        "（MJCF/URDF モデル。Sim2Real 用の実機パラメータ同定はプロダクト側で定義）"
    )
    display_order = 18
    required_commands = ("mujoco-python",)

    @classmethod
    def dependency_status(cls) -> list[CommandStatus]:
        return [
            CommandStatus(
                name="mujoco-python",
                path=sys.executable if _mujoco_is_importable() else None,
            )
        ]

    @classmethod
    def install_hint(cls, missing: list[str]) -> str:
        del missing
        return (
            "MuJoCo Python package が見つかりません。\n"
            "`gar setup` で MuJoCo を選ぶと、現在の Python 環境へ `pip install mujoco` を実行します。\n"
            "手動の場合: python -m pip install mujoco\n"
            "GPU/GUI がない環境では viewer の代わりにプロダクト側 runner を使ってください。"
        )

    @classmethod
    def install_dependencies(cls, missing: list[str]) -> int:
        if "mujoco-python" not in missing:
            return 0
        if shutil.which(sys.executable) is None:
            print(cls.install_hint(missing))
            return 1
        print("MuJoCo Python package をインストールします。")
        return cls.run_install_command([sys.executable, "-m", "pip", "install", "mujoco"])


def _mujoco_is_importable() -> bool:
    try:
        __import__("mujoco")
    except ImportError:
        return False
    return True

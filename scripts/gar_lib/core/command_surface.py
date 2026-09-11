"""Canonical action-first command vocabulary, independent of argparse."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSurface:
    subjects: tuple[str, ...]
    default_subject: str | None
    description: str


SIM_ACTION_SURFACE = {
    "prepare": ActionSurface((), None, "Linux Sim Hostの依存を準備します（application build/deployなし）"),
    "build": ActionSurface(("app", "runtime"), None, "必要なsimulation artifact一式をbuildします"),
    "deploy": ActionSurface(("app", "runtime"), None, "必要なsnapshot一式を検証してsimulationへ配置します"),
    "start": ActionSurface(("runtime", "host"), "runtime", "配置済みsimulationを開始します"),
    "stop": ActionSurface(("runtime", "host"), "runtime", "simulationを停止します。VM停止はstop hostで明示します"),
    "status": ActionSurface(("runtime", "host"), None, "host・接続・runtime・appの状態を取得します"),
    "log": ActionSurface(("runtime",), "runtime", "simulation logを取得します"),
    "diag": ActionSurface(("runtime",), None, "host・接続・runtime・appを診断します"),
    "clean": ActionSurface(("app",), "app", "Product hook経由でsimulation appのbuild成果物を削除します"),
}

CODE_HOST_ACTIONS = {"start": "boot", "stop": "shutdown"}


def action_first(group: str, action: str, subject: str | None) -> bool:
    """Whether a command has a canonical action-first spelling."""

    if group == "code":
        return subject is None or (action in CODE_HOST_ACTIONS and subject in {"session", "host"})
    if group != "sim":
        return subject is None
    spec = SIM_ACTION_SURFACE.get(action)
    return spec is not None and (subject is None or subject in spec.subjects)

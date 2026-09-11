"""CLI capability inspection beside the common action vocabulary."""

from __future__ import annotations

import argparse
import sys

from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.capabilities import command_capabilities
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.output import emit_json


def add_capability_options(parser: argparse.ArgumentParser, *, group: str) -> None:
    parser.add_argument(
        "--capabilities", action="store_true", help="設定した環境の共通action対応状況を表示します（接続なし）"
    )
    parser.add_argument("--workspace", default=None, metavar="NAME", help="対応状況を調べるworkspace")
    parser.add_argument("--json", dest="json_output", action="store_true", help="対応状況をJSONで表示します")
    guidance = f"対応状況: gar {group} --capabilities --workspace NAME [--json]"
    parser.epilog = f"{parser.epilog}\n{guidance}" if parser.epilog else guidance


def run_capabilities(args: argparse.Namespace) -> int:
    try:
        return _run_capabilities(args)
    except (GarDomainError, OSError, ValueError) as error:
        print(f"gar: {error}", file=sys.stderr)
        return 1


def _run_capabilities(args: argparse.Namespace) -> int:
    if getattr(args, "gar_command", None) is not None or getattr(args, "code_command", None) is not None:
        raise GarDomainError("--capabilitiesとactionは同時に指定できません")
    workspace = resolve_workspace(getattr(args, "workspace", None))
    args._gar_workspace = workspace
    report = command_capabilities(args.command, workspace)
    if getattr(args, "json_output", False):
        emit_json({"workspace": workspace.name, **report})
    else:
        print(f"{args.command}: {workspace.name} ({report['environment'] or '未設定'})")
        for action, supported in report["actions"].items():
            print(f"  {action}: {'対応' if supported else '未対応／対象外'}")
        print(report["reason"])
    return 0

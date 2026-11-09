"""A fixed CLI for Product operations; aliases rewrite arguments, not parsers."""

from __future__ import annotations

import argparse
import sys

from scripts.gar_lib.commands.workspace_resolver import resolve_workspace
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.output import emit_json
from scripts.gar_lib.product_operations import MANIFEST, execute_operation, load_operations


def add_product_parser(commands):
    parser = commands.add_parser("product", help="Productが定義する操作を一覧・検証・実行します")
    actions = parser.add_subparsers(dest="product_action", metavar="action")
    for name, help_text in (
        ("list", "操作とAliasを表示"),
        ("validate", "定義を検証（処理は実行しない）"),
        ("run", "定義済みの操作を実行"),
    ):
        child = actions.add_parser(name, help=help_text)
        child.add_argument("--workspace", metavar="NAME")
        child.add_argument("--json", dest="json_output", action="store_true")
        child.set_defaults(gar_command=GarCommand("product", None, name))
        if name == "run":
            child.add_argument("operation", help="gar product list に表示される操作名")
            child.add_argument("arguments", nargs=argparse.REMAINDER, help="-- 以降をProduct処理へ渡します")
    return {"product": parser}


def _subcommands(parser):
    return next((action.choices for action in parser._actions if isinstance(action, argparse._SubParsersAction)), {})


def validate_aliases(registry, parser):
    for alias in registry.aliases:
        current = parser
        for word in alias:
            choices = _subcommands(current)
            if word not in choices:
                break
            current = choices[word]
        else:
            raise GarDomainError(f"AliasでGAR標準コマンドを上書きできません: {' '.join(alias)}")


def _controls(arguments):
    """GAR options are reserved only before --; Product arguments stay literal."""
    options, forwarded, index, workspace = [], [], 0, None
    while index < len(arguments):
        word = arguments[index]
        if word == "--":
            forwarded.extend(arguments[index:])
            break
        if word == "--workspace" or word.startswith("--workspace="):
            if workspace is not None:
                raise GarDomainError("--workspace は一度だけ指定してください")
            if word == "--workspace":
                if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
                    raise GarDomainError("--workspace に対象を指定してください")
                index += 1
                workspace = arguments[index]
            else:
                workspace = word.split("=", 1)[1]
                if not workspace:
                    raise GarDomainError("--workspace に対象を指定してください")
            options.extend(("--workspace", workspace))
        elif word == "--json":
            options.append(word)
        else:
            forwarded.append(word)
        index += 1
    return options, forwarded, workspace


def normalize_product_arguments(arguments, parser):
    """Return canonical arguments and an optional Product-scoped alias name."""
    if arguments[:2] == ["product", "run"]:
        options, forwarded, _ = _controls(arguments[2:])
        return ["product", "run", *options, *forwarded], None
    if not arguments or arguments[0].startswith("-"):
        return arguments, None
    # Standard commands never consult a Product manifest or change their route.
    current = parser
    for word in arguments:
        if word.startswith("-"):
            return arguments, None
        choices = _subcommands(current)
        if word not in choices:
            if not choices:
                return arguments, None
            break
        current = choices[word]
    else:
        return arguments, None
    options, forwarded, selector = _controls(arguments)
    try:
        workspace = resolve_workspace(selector)
    except GarDomainError:
        return arguments, None
    if not (workspace.local_root / MANIFEST).is_file():
        return arguments, None
    registry = load_operations(workspace.local_root)
    validate_aliases(registry, parser)
    if selector is None:
        options.extend(("--workspace", workspace.name))
    for alias, operation in registry.aliases.items():
        if tuple(forwarded[: len(alias)]) == alias:
            rest = forwarded[len(alias) :]
            if rest[:1] == ["--"]:
                rest = rest[1:]
            return ["product", "run", *options, operation, "--", *rest], " ".join(alias)
    return arguments, None


def run_product_command(args, *, root_parser, help_parser):
    if args.product_action is None:
        help_parser.print_help()
        return 1
    try:
        workspace = resolve_workspace(args.workspace)
        args._gar_workspace = workspace
        registry = load_operations(workspace.local_root)
        validate_aliases(registry, root_parser)
        if args.product_action == "run":
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            report = execute_operation(registry, args.operation, arguments, workspace.name)
            if getattr(args, "product_alias", None):
                report["alias"] = args.product_alias
        else:
            report = {
                "ok": True,
                "operations": [
                    {
                        "name": operation.name,
                        "description": operation.description,
                        "runtime": operation.runtime,
                        "entrypoint": operation.entrypoint.relative_to(registry.root).as_posix(),
                        "aliases": [
                            " ".join(alias) for alias, name in registry.aliases.items() if name == operation.name
                        ],
                    }
                    for operation in registry.operations.values()
                ],
            }
        if args.json_output:
            emit_json(report)
        elif args.product_action == "run":
            result = report["result"]
            if set(result) == {"output"}:
                print(result["output"], end="")
            else:
                emit_json(report)
        else:
            print(f"Product: {workspace.name}")
            for operation in report["operations"]:
                aliases = ", ".join("gar " + alias for alias in operation["aliases"])
                print(f"  {operation['name']}: {operation['description']}" + (f" [{aliases}]" if aliases else ""))
            if args.product_action == "validate":
                print("定義は有効です（操作は実行していません）")
        return report.get("exit_code", 0)
    except (GarDomainError, OSError, ValueError) as error:
        if args.json_output:
            raise
        print(f"gar product: {error}", file=sys.stderr)
        return 1

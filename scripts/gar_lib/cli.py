"""Thin root for the ``gar`` command-line interface.

Each command module owns its parser and the adapter from :class:`argparse.Namespace`
to its programmatic command functions.  This module only assembles those parsers,
normalizes root-level input, and selects the corresponding explicit adapter.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from scripts.gar_lib.commands import code, completion, hw, product, setup, sim, system, target, terminal, usb
from scripts.gar_lib.commands.capabilities import run_capabilities
from scripts.gar_lib.commands.completion import completion_bash_script as completion_bash_script
from scripts.gar_lib.commands.completion import completion_powershell_script as completion_powershell_script
from scripts.gar_lib.commands.completion import completion_zsh_script as completion_zsh_script
from scripts.gar_lib.commands.result import json_boundary
from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.errors import GarDomainError


@dataclass(frozen=True)
class CliParserBundle:
    """The root parser and named group parsers used to render contextual help."""

    root: argparse.ArgumentParser
    help_parsers: dict[str, argparse.ArgumentParser]


def normalize_question_help(argv: Sequence[str] | None = None) -> list[str]:
    """Treat ``?`` before ``--`` as a context-local argparse help request."""

    args = list(sys.argv[1:] if argv is None else argv)
    scan_end = args.index("--") if "--" in args else len(args)
    for index, value in enumerate(args[:scan_end]):
        if value == "?":
            return [*args[:index], "--help", *args[index + 1 :]]
    return args


def enable_argcomplete(parser: argparse.ArgumentParser) -> None:
    try:
        import argcomplete
    except ImportError:
        return
    argcomplete.autocomplete(parser)


def build_parser_bundle() -> CliParserBundle:
    """Assemble the public CLI from command-owned parser definitions."""

    root = argparse.ArgumentParser(prog="gar")
    commands = root.add_subparsers(dest="command", metavar="command")
    help_parsers: dict[str, argparse.ArgumentParser] = {}

    help_parsers.update(setup.add_config_parser(commands))
    help_parsers.update(code.add_code_parser(commands))
    help_parsers.update(terminal.add_terminal_parser(commands))
    help_parsers.update(completion.add_completion_parser(commands))
    help_parsers.update(sim.add_sim_parser(commands))
    help_parsers.update(system.add_system_parser(commands))
    help_parsers.update(target.add_target_parser(commands))
    help_parsers.update(usb.add_usb_parser(commands))
    help_parsers.update(hw.add_hw_parser(commands))
    help_parsers.update(product.add_product_parser(commands))

    return CliParserBundle(root=root, help_parsers=help_parsers)


def build_parser() -> argparse.ArgumentParser:
    """Return only the root parser for callers that do not need help parsers."""

    return build_parser_bundle().root


def run_cli_command(args: argparse.Namespace, bundle: CliParserBundle) -> int:
    """Dispatch parsed arguments to one command module's explicit CLI adapter."""

    if args.command in {"code", "sim", "target", "product"} and getattr(args, "json_output", False):
        return json_boundary(args, lambda: _dispatch(args, bundle))
    return _dispatch(args, bundle)


def _dispatch(args: argparse.Namespace, bundle: CliParserBundle) -> int:
    if getattr(args, "capabilities", False):
        return run_capabilities(args)

    if args.command == "config":
        return setup.run_config_cli(args)
    if args.command == "code":
        return code.run_code_cli(args, help_parser=bundle.help_parsers["code"])
    if args.command == "terminal":
        return terminal.run_terminal_cli(args, help_parser=bundle.help_parsers["terminal"])
    if args.command == "completion":
        return completion.run_completion_command(
            args,
            root_parser_factory=build_parser,
            help_parser=bundle.help_parsers["completion"],
        )
    if args.command == "sim":
        return sim.run_sim_command(args, subcommand_parsers=bundle.help_parsers)
    if args.command == "system":
        return system.run_system_command(args, subcommand_parsers=bundle.help_parsers)
    if args.command == "target":
        return target.run_target_command(args, subcommand_parsers=bundle.help_parsers)
    if args.command == "usb":
        return usb.run_usb_cli(args, help_parser=bundle.help_parsers["usb"])
    if args.command == "hw":
        return hw.run_hw_cli(args, help_parser=bundle.help_parsers["hw"])
    if args.command == "product":
        return product.run_product_command(args, root_parser=bundle.root, help_parser=bundle.help_parsers["product"])

    bundle.root.print_help()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    bundle = build_parser_bundle()
    enable_argcomplete(bundle.root)
    try:
        arguments, alias = product.normalize_product_arguments(normalize_question_help(argv), bundle.root)
        args = bundle.root.parse_args(arguments)
        args.product_alias = alias
    except GarDomainError as error:
        arguments = normalize_question_help(argv)
        before_separator = arguments[: arguments.index("--")] if "--" in arguments else arguments
        if "--json" in before_separator:
            failure = argparse.Namespace(command="product", gar_command=GarCommand("product", None, "run"))

            def fail(failure_error=error):
                raise failure_error

            return json_boundary(failure, fail)
        print(f"gar: {error}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        raise
    return run_cli_command(args, bundle)

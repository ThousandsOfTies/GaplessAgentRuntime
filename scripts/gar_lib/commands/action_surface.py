"""Expose action-first aliases while retaining command-owned option definitions."""

from __future__ import annotations

import argparse
from copy import copy
from dataclasses import replace

from scripts.gar_lib.core.command import GarCommand
from scripts.gar_lib.core.command_surface import ActionSurface
from scripts.gar_lib.core.errors import GarDomainError


class _StoreSubject(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        namespace.gar_command = replace(namespace.gar_command, subject=values)


def add_action_parser(
    subparsers: argparse._SubParsersAction,
    *,
    group: str,
    action: str,
    spec: ActionSurface,
    subjects: dict[str, argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Reuse each subject's exact options and retain their applicability scope.

    Suppressed defaults distinguish an explicitly supplied option from an absent
    one, so e.g. ``start host --panel-port 8080`` cannot silently ignore a flag.
    """

    parser = subparsers.add_parser(action, help=spec.description, description=spec.description)
    options: dict[str, tuple[str, set[str | None]]] = {}
    for subject, source in subjects.items():
        for option in source._actions:
            if not option.option_strings or option.dest == "help":
                continue
            if option.dest not in options:
                cloned = copy(option)
                cloned.default = argparse.SUPPRESS
                parser._add_action(cloned)
                options[option.dest] = (option.option_strings[0], set())
            options[option.dest][1].add(subject)
            if spec.default_subject is None and (
                action not in {"status", "diag"} or option.dest in {"workspace", "json_output"}
            ):
                options[option.dest][1].add(None)
    for option in parser._actions:
        if option.dest in options:
            supported = options[option.dest][1] - {None}
            if supported != set(spec.subjects):
                option.help = f"{option.help}（{', '.join(sorted(supported))} 専用）"
    parser.set_defaults(
        gar_command=GarCommand(group, spec.default_subject, action),
        _gar_scoped_options=options,
    )
    parser.add_argument(
        "action_subject",
        nargs="?",
        choices=spec.subjects,
        default=spec.default_subject,
        action=_StoreSubject,
        metavar="subject",
        help=f"対象: {', '.join(spec.subjects)}。省略時: {spec.default_subject or ('環境全体' if action in {'status', 'diag'} else '必要なartifact一式')}",
    )
    return parser


def validate_action_options(args: argparse.Namespace, *, command: GarCommand | None = None) -> None:
    command = command or args.gar_command
    for destination, (option, subjects) in getattr(args, "_gar_scoped_options", {}).items():
        if hasattr(args, destination) and command.subject not in subjects:
            raise GarDomainError(f"{option} は {command.to_cli()} では使えません")


def hide_compatibility_parsers(subparsers: argparse._SubParsersAction, names: tuple[str, ...]) -> None:
    """Keep aliases parseable, including their own help, without advertising them."""

    subparsers._choices_actions = [choice for choice in subparsers._choices_actions if choice.dest not in names]
    for name in names:
        subparsers.choices[name]._gar_hidden_completion = True

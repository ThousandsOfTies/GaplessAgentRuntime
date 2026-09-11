"""Shell completion command definition and argparse-based candidates."""

from __future__ import annotations

import argparse
import shlex
from argparse import Namespace
from collections.abc import Callable, Sequence


def add_completion_parser(
    subparsers: argparse._SubParsersAction,
) -> dict[str, argparse.ArgumentParser]:
    parser = subparsers.add_parser(
        "completion",
        help="shell completion script を出力します",
    )
    commands = parser.add_subparsers(dest="completion_shell", metavar="shell")
    for shell in ("bash", "zsh", "powershell"):
        shell_parser = commands.add_parser(shell, help=f"{shell} completion script を出力します")
        shell_parser.add_argument(
            "--command",
            dest="completion_command",
            default="gar",
            help=argparse.SUPPRESS,
        )
    words_parser = commands.add_parser("words")
    words_parser._gar_hidden_completion = True
    commands._choices_actions = [choice for choice in commands._choices_actions if choice.dest != "words"]
    words_parser.add_argument("--cword", type=int, required=True)
    words_parser.add_argument("words", nargs=argparse.REMAINDER)
    return {"completion": parser}


def run_completion_command(
    args: Namespace,
    *,
    root_parser_factory: Callable[[], argparse.ArgumentParser],
    help_parser: argparse.ArgumentParser,
) -> int:
    if args.completion_shell == "bash":
        print(completion_bash_script(args.completion_command), end="")
        return 0
    if args.completion_shell == "zsh":
        print(completion_zsh_script(args.completion_command), end="")
        return 0
    if args.completion_shell == "powershell":
        print(completion_powershell_script(args.completion_command), end="")
        return 0
    if args.completion_shell == "words":
        words = args.words[1:] if args.words[:1] == ["--"] else args.words
        print("\n".join(parser_completion_words(args.cword, words, root_parser_factory)))
        return 0
    help_parser.print_help()
    return 1


def completion_bash_script(command: str = "gar") -> str:
    launcher = shlex.quote(command)
    return f"""# Gapless Agent Runtime bash completion.
_gar_completion() {{
  local IFS=$'\\n'
  COMPREPLY=($({launcher} completion words --cword "$COMP_CWORD" -- "${{COMP_WORDS[@]}}"))
}}
complete -o nosort -F _gar_completion gar
"""


def completion_zsh_script(command: str = "gar") -> str:
    launcher = shlex.quote(command)
    return f"""# Gapless Agent Runtime zsh completion.
if (( ! $+functions[compdef] )); then
  autoload -Uz compinit
  compinit
fi
_gar_completion() {{
  local -a candidates
  candidates=("${{(@f)$({launcher} completion words --cword "$((CURRENT - 1))" -- "${{words[@]}}")}}")
  compadd -Q -- "${{candidates[@]}}"
}}
compdef _gar_completion gar
"""


def completion_powershell_script(command: str = "gar") -> str:
    launcher = command.replace("'", "''")
    return f"""# Gapless Agent Runtime PowerShell completion.
Register-ArgumentCompleter -Native -CommandName gar -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)

    $words = @($commandAst.CommandElements | ForEach-Object {{ $_.Extent.Text }})
    if ($commandAst.Extent.EndOffset -lt $cursorPosition) {{
        $words += ''
    }}
    $cword = [Math]::Max(0, $words.Count - 1)
    & '{launcher}' completion words --cword $cword -- @words | ForEach-Object {{
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
    }}
}}
"""


def parser_completion_words(
    cword: int,
    words: Sequence[str],
    root_parser_factory: Callable[[], argparse.ArgumentParser],
) -> list[str]:
    """Return shell completion candidates from argparse parser structure."""

    parser = root_parser_factory()
    current = words[cword] if cword < len(words) else ""
    tokens = list(words[1:cword])

    index = 0
    positional_tokens: list[str] = []
    while index < len(tokens):
        token = tokens[index]
        subparsers = _subparser_action(parser)
        if subparsers and token in subparsers.choices:
            parser = subparsers.choices[token]
            positional_tokens = []
            index += 1
            continue
        if token.startswith("-"):
            option_name, separator, _ = token.partition("=")
            option_action = parser._option_string_actions.get(option_name)
            if option_action and option_action.nargs in (None, 1) and not separator:
                if index + 1 == len(tokens):
                    return [str(choice) for choice in option_action.choices or () if str(choice).startswith(current)]
                index += 2
                continue
        else:
            positional_tokens.append(token)
        index += 1

    candidates = _parser_options(parser)
    positionals = [action for action in parser._actions if not action.option_strings]
    scoped_options = parser.get_default("_gar_scoped_options") or {}
    if scoped_options and positionals:
        subject = positional_tokens[0] if positional_tokens else positionals[0].default
        candidates = [
            candidate
            for candidate in candidates
            if parser._option_string_actions[candidate].dest not in scoped_options
            or subject in scoped_options[parser._option_string_actions[candidate].dest][1]
        ]
    subparsers = _subparser_action(parser)
    if subparsers:
        hidden = {choice.dest for choice in subparsers._choices_actions if choice.help == argparse.SUPPRESS}
        hidden.update(
            name
            for name, choice_parser in subparsers.choices.items()
            if getattr(choice_parser, "_gar_hidden_completion", False)
        )
        candidates.extend(name for name in subparsers.choices if name not in hidden)
    else:
        if len(positional_tokens) < len(positionals):
            candidates.extend(str(choice) for choice in positionals[len(positional_tokens)].choices or ())

    return sorted(candidate for candidate in candidates if candidate.startswith(current))


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _parser_options(parser: argparse.ArgumentParser) -> list[str]:
    options: list[str] = []
    for action in parser._actions:
        if action.help != argparse.SUPPRESS:
            options.extend(action.option_strings)
    return options

"""Check CLI tables, shell examples, and local links without executing GAR actions."""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.gar_lib.cli import build_parser  # noqa: E402
from scripts.gar_lib.commands.action_surface import validate_action_options  # noqa: E402
from scripts.gar_lib.core.capabilities import COMMON_ACTIONS  # noqa: E402
from scripts.gar_lib.core.command import GarCommand  # noqa: E402
from scripts.gar_lib.core.command_surface import SIM_ACTION_SURFACE  # noqa: E402
from scripts.gar_lib.core.errors import GarDomainError  # noqa: E402


def public_commands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {
                name: child
                for name, child in action.choices.items()
                if not getattr(child, "_gar_hidden_completion", False)
            }
    return {}


def check_reference(source: str, parser: argparse.ArgumentParser) -> list[str]:
    """Compare structural contracts; explanatory prose remains human-authored."""

    errors: list[str] = []

    def rows(heading: str, header: str) -> list[list[str]]:
        section = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", source, re.M | re.S)
        if section:
            table = re.search(rf"^{re.escape(header)}\s*\n\|[-| :]+\|\s*\n((?:\|[^\n]+\n?)+)", section[1], re.M)
            if table:
                return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in table[1].splitlines()]
        errors.append(f"{heading}: table missing ({header})")
        return []

    def compare(label: str, actual: list[str], expected: list[str]) -> None:
        if sorted(actual) != sorted(expected):
            errors.append(f"{label}: documented={actual}, CLI={expected}")

    groups = public_commands(parser)
    top_rows = rows("トップレベル", "| コマンド | 用途 |")
    compare("top-level", [row[0] for row in top_rows], [f"`gar {group}`" for group in groups])

    common_rows = rows("共通", "| Action | code | sim | target |")
    compare("common actions", [row[0] for row in common_rows], [f"`{action}`" for action in COMMON_ACTIONS])
    for row in common_rows:
        if len(row) != 4:
            errors.append(f"common actions: malformed row {row}")
            continue
        action = row[0].strip("`")
        for group, cell in zip(("code", "sim", "target"), row[1:], strict=True):
            supported = action in public_commands(groups[group])
            if supported == (cell == "対象外"):
                errors.append(f"common actions: {group}.{action} availability differs from CLI")

    for group in ("code", "target"):
        entries = []
        for name, child in public_commands(groups[group]).items():
            subject = next((a for a in child._actions if a.dest == "code_subject"), None)
            if subject is None:
                entries.append(f"`{name}`")
            else:
                entries.extend(
                    f"`{name} [{value}]`" if value == subject.default else f"`{name} {value}`"
                    for value in subject.choices
                )
        compare(group, [row[0] for row in rows(f"`gar {group}`", "| Action | 内容 |")], entries)

    sim_commands = public_commands(groups["sim"])
    sim_rows = rows("`gar sim`", "| Action | 対象省略時 | 指定できるsubject |")
    compare("sim actions", [row[0] for row in sim_rows], [f"`{name}`" for name in SIM_ACTION_SURFACE])
    for row in sim_rows:
        name = row[0].strip("`")
        child = sim_commands.get(name)
        spec = SIM_ACTION_SURFACE.get(name)
        if child is None or spec is None or len(row) != 3:
            errors.append(f"sim: invalid action row {row}")
            continue
        subject = next((a for a in child._actions if a.dest == "action_subject"), None)
        subjects = tuple(subject.choices) if subject else ()
        documented = tuple(re.findall(r"`(\w+)`", row[2]))
        if documented != subjects or subjects != spec.subjects:
            errors.append(f"sim {name}: documented subjects={documented}, CLI={subjects}, contract={spec.subjects}")
        command = child.get_default("gar_command")
        if not isinstance(command, GarCommand) or command.subject != spec.default_subject:
            errors.append(f"sim {name}: default subject differs from command contract")

    specialized = {name: child for name, child in sim_commands.items() if name not in SIM_ACTION_SURFACE}
    special_rows = rows("`gar sim`", "| Subject | Actions |")
    compare("sim specialized subjects", [row[0] for row in special_rows], [f"`{name}`" for name in specialized])
    for row in special_rows:
        name = row[0].strip("`")
        if name in specialized and len(row) == 2:
            compare(f"sim {name}", re.findall(r"`(\w+)`", row[1]), list(public_commands(specialized[name])))
        else:
            errors.append(f"sim: invalid specialized row {row}")
    system_entries = []
    for name, child in public_commands(groups["system"]).items():
        system_entries.append(f"`{name}`")
        subject = next((action for action in child._actions if action.dest == "system_subject"), None)
        if subject is not None:
            system_entries.extend(f"`{name} {choice}`" for choice in subject.choices)
    compare("system", [row[0] for row in rows("`gar system`", "| Action | 内容 |")], system_entries)
    return errors


@dataclass
class CheckResult:
    commands: int = 0
    links: int = 0
    errors: list[str] = field(default_factory=list)


def check_document(path: Path, source: str, parser: argparse.ArgumentParser) -> CheckResult:
    result = CheckResult()
    shell: str | None = None
    in_fence = False
    pending = ""
    start = 0
    launcher = re.compile(r"^(?:gar|(?:\./)?scripts/gar|\.\\scripts\\gar\.cmd)\s+")

    def check_example(command: str, number: int) -> None:
        result.commands += 1
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                words = shlex.split(command, comments=True)
                args = parser.parse_args(words[1:])
                if words[1:3] in (["code", "boot"], ["code", "shutdown"]) or (
                    words[1:2] == ["sim"] and words[2:3] in (["app"], ["runtime"], ["host"])
                ):
                    result.errors.append(f"{path.name}:{number}: use action-first syntax in command examples")
                if hasattr(args, "_gar_scoped_options"):
                    intent = getattr(args, "gar_command", None)
                    if intent is None and args.command == "code":
                        intent = GarCommand("code", args.code_subject, args.code_command)
                    validate_action_options(args, command=intent)
            except SystemExit as error:
                if error.code:
                    result.errors.append(f"{path.name}:{number}: {output.getvalue().strip()}")
            except (GarDomainError, ValueError) as error:
                result.errors.append(f"{path.name}:{number}: {error}")

    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.strip()
        if line.startswith("```"):
            if pending:
                result.errors.append(f"{path.name}:{start}: unfinished command continuation")
                pending = ""
            in_fence = not in_fence
            shell = line[3:] if in_fence and line[3:] in {"bash", "sh", "powershell", "pwsh"} else None
            continue
        if not shell:
            continue
        if not pending:
            if not launcher.match(line):
                continue
            start = number
            line = launcher.sub("gar ", line, count=1)
        continuation = "`" if shell in {"powershell", "pwsh"} else "\\"
        continued = line.endswith(continuation)
        pending += " " + (line[:-1] if continued else line)
        if not continued:
            check_example(pending.strip(), start)
            pending = ""
    if pending:
        result.errors.append(f"{path.name}:{start}: unfinished command continuation")

    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", source):
        href = match[1].strip("<>")
        url = urlsplit(href)
        if url.scheme or url.netloc or not url.path:
            continue
        result.links += 1
        if not (path.parent / unquote(url.path)).exists():
            result.errors.append(f"{path.name}: missing local link {href}")
    return result


def check_docs(root: Path = ROOT) -> CheckResult:
    parser = build_parser()
    result = CheckResult()
    reference = root / "docs/01_COMMAND_REFERENCE.md"
    if not reference.is_file():
        result.errors.append(f"missing command reference: {reference}")
        return result
    result.errors.extend(check_reference(reference.read_text(encoding="utf-8"), parser))
    for path in sorted((root / "docs").glob("*.md")):
        checked = check_document(path, path.read_text(encoding="utf-8"), parser)
        result.commands += checked.commands
        result.links += checked.links
        result.errors.extend(checked.errors)
    return result


def main() -> int:
    result = check_docs()
    for error in result.errors:
        print(error, file=sys.stderr)
    print(f"CLI tables, {result.commands} command examples, {result.links} local links: {len(result.errors)} errors")
    return int(bool(result.errors))


if __name__ == "__main__":
    raise SystemExit(main())

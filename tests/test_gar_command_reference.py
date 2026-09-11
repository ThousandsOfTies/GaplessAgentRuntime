from __future__ import annotations

import argparse
import unittest
from pathlib import Path

from scripts.gar_lib.cli import build_parser
from tools.check_command_reference import ROOT, check_docs, check_document, check_reference, public_commands


class CommandReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference = (ROOT / "docs/01_COMMAND_REFERENCE.md").read_text(encoding="utf-8")

    def test_repository_reference_examples_and_local_links_match(self) -> None:
        result = check_docs()
        self.assertFalse(result.errors, "\n".join(result.errors))
        self.assertGreater(result.commands, 0)
        self.assertGreater(result.links, 0)

    def test_added_action_requires_a_documentation_update(self) -> None:
        parser = build_parser()
        target = public_commands(parser)["target"]
        next(action for action in target._actions if isinstance(action, argparse._SubParsersAction)).add_parser(
            "restart"
        )
        self.assertTrue(any("restart" in error for error in check_reference(self.reference, parser)))

    def test_subject_default_drift_is_detected(self) -> None:
        changed = self.reference.replace("`start [session]`", "`start session`")
        self.assertTrue(any(error.startswith("code:") for error in check_reference(changed, build_parser())))

    def test_sim_subject_table_drift_is_detected(self) -> None:
        changed = self.reference.replace("`app`, `runtime`", "`app`, `host`", 1)
        self.assertTrue(any("sim build" in error for error in check_reference(changed, build_parser())))

    def test_system_connection_subject_drift_is_detected(self) -> None:
        changed = self.reference.replace("| `status connections` |", "| `status tunnels` |")
        self.assertTrue(any(error.startswith("system:") for error in check_reference(changed, build_parser())))

    def test_common_table_cannot_advertise_a_missing_code_action(self) -> None:
        changed = self.reference.replace("| `build` | 対象外 |", "| `build` | buildを実行 |")
        self.assertTrue(any("code.build" in error for error in check_reference(changed, build_parser())))

    def test_shell_examples_validate_scope_and_continuations_without_execution(self) -> None:
        source = """```bash
gar sim start host \\
  --panel-port 8080
scripts/gar sim unknown
gar sim start --help
```
```powershell
.\\scripts\\gar.cmd sim status `
  --workspace Local/Product --json
```
"""
        result = check_document(Path("example.md"), source, build_parser())
        self.assertEqual(4, result.commands)
        self.assertEqual(2, len(result.errors))
        self.assertIn("--panel-port", result.errors[0])
        self.assertIn("unknown", result.errors[1])

    def test_missing_links_and_incomplete_examples_fail(self) -> None:
        source = "[missing](does-not-exist.md)\n[web](https://example.com)\n```sh\ngar sim build \\\n```\n"
        result = check_document(ROOT / "docs/example.md", source, build_parser())
        self.assertEqual(1, result.links)
        self.assertEqual(2, len(result.errors))

    def test_compatibility_aliases_are_not_reintroduced_as_normal_examples(self) -> None:
        result = check_document(
            Path("example.md"), "```sh\ngar sim runtime start\ngar code boot\n```\n", build_parser()
        )
        self.assertEqual(2, result.commands)
        self.assertEqual(2, len(result.errors))
        self.assertTrue(all("action-first" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()

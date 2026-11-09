import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.gar_lib.cli import build_parser, main
from scripts.gar_lib.commands.product import normalize_product_arguments, validate_aliases
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.product_operations import execute_operation, load_operations


class ProductOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gar-product-operations-")
        self.root = Path(self.temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.addCleanup(self.temporary.cleanup)
        self.workspace = SimpleNamespace(local_root=self.root, name="Test/Camera", selected_target=None)
        (self.root / "camera.py").write_text(
            "import json,os,sys\nfrom pathlib import Path\n"
            "if '--help' in sys.argv: print('Product camera help');sys.exit(0)\n"
            "print(json.dumps({'ok':True,'camera':os.environ['GAR_PRODUCT_WORKSPACE'],'args':sys.argv[1:],"
            "'cwd':str(Path.cwd()),'operation':os.environ['GAR_PRODUCT_OPERATION'],'password':'PRIVATE'}))\n",
            encoding="utf-8",
        )
        self.definition = {
            "schema_version": 1,
            "operations": {
                "camera": {
                    "entrypoint": "camera.py",
                    "description": "Fixture camera, no device access",
                    "result_fields": ["ok", "camera", "args", "cwd", "operation"],
                }
            },
            "aliases": {"target camera": "camera", "snap": "camera"},
        }
        self.save()

    def save(self):
        (self.root / "gar-operations.json").write_text(json.dumps(self.definition), encoding="utf-8")

    def call(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("scripts.gar_lib.commands.product.resolve_workspace", return_value=self.workspace),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            code = main(arguments)
        return code, output.getvalue(), errors.getvalue()

    def test_real_cli_and_alias_forward_literal_arguments_and_keep_result_contract(self):
        literal = "日本語 with spaces; $(not-a-command) `literal`"
        for arguments in (
            ["product", "run", "camera", "--workspace", "Test/Camera", "--json", "--", literal],
            ["target", "camera", "--workspace=Test/Camera", "--json", "--", literal],
            ["snap", "--json", literal],
        ):
            with self.subTest(arguments=arguments):
                code, output, errors = self.call(arguments)
                result = json.loads(output)
                self.assertEqual(code, 0, errors)
                self.assertEqual(result["command"], "product.run")
                self.assertEqual(result["operation"], "camera")
                self.assertEqual(result["result"]["camera"], "Test/Camera")
                self.assertEqual(result["result"]["args"], [literal])
                self.assertEqual(result["result"]["cwd"], str(self.root))
                self.assertNotIn("PRIVATE", output + errors)

    def test_product_flags_after_separator_are_never_consumed_as_gar_options(self):
        code, output, _ = self.call(["target", "camera", "--json", "--", "--workspace", "child", "--json", "?"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["result"]["args"], ["--workspace", "child", "--json", "?"])

    def test_child_help_is_forwarded_without_requiring_json(self):
        for arguments in (["product", "help", "camera"],):
            code, output, _ = self.call(arguments)
            self.assertEqual(code, 0)
            self.assertEqual(output.strip(), "Product camera help")

    def test_list_and_validate_only_read_definitions(self):
        with patch("scripts.gar_lib.product_operations.run_bounded") as run:
            for action in ("list", "validate"):
                code, output, _ = self.call(["product", action, "--json"])
                self.assertEqual(code, 0)
                camera = json.loads(output)["operations"][0]
                self.assertEqual(camera["aliases"], ["target camera", "snap"])
            run.assert_not_called()

    def test_adding_operation_after_cli_creation_does_not_generate_a_parser(self):
        parser = build_parser()
        self.definition["operations"]["new-feature"] = self.definition["operations"]["camera"].copy()
        self.definition["aliases"]["target new-feature"] = "new-feature"
        self.save()
        code, output, _ = self.call(["target", "new-feature", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["operation"], "new-feature")
        self.assertNotIn("camera", parser.format_help())

    def test_two_products_can_define_same_alias_with_different_handlers(self):
        for name in ("First", "Second"):
            root = self.root / name
            root.mkdir()
            (root / "camera.py").write_text("import json\nprint(json.dumps({'ok':True,'owner':" + repr(name) + "}))\n")
            spec = {
                "schema_version": 1,
                "operations": {"camera": {"entrypoint": "camera.py", "result_fields": ["ok", "owner"]}},
                "aliases": {"target camera": "camera"},
            }
            (root / "gar-operations.json").write_text(json.dumps(spec))
            self.workspace = SimpleNamespace(local_root=root, name="Test/" + name)
            code, output, _ = self.call(["target", "camera", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["result"]["owner"], name)

    def test_standard_commands_do_not_consult_or_execute_product_definitions(self):
        (self.root / "gar-operations.json").write_text("invalid manifest")
        with patch("scripts.gar_lib.commands.product.resolve_workspace") as resolve:
            for arguments in (
                ["target", "build", "--json"],
                ["sim", "start"],
                ["target", "--help"],
                ["product", "--help"],
            ):
                self.assertEqual(normalize_product_arguments(arguments, build_parser()), (arguments, None))
            resolve.assert_not_called()

    def test_alias_cannot_shadow_standard_command_or_ambiguous_prefix(self):
        for alias in ("target build", "sim start", "product run", "target"):
            self.definition["aliases"] = {alias: "camera"}
            self.save()
            with self.assertRaises(GarDomainError):
                validate_aliases(load_operations(self.root), build_parser())
        self.definition["aliases"] = {"snap": "camera", "snap now": "camera"}
        self.save()
        with self.assertRaises(GarDomainError):
            load_operations(self.root)

    def test_invalid_manifest_and_alias_fail_as_single_json_without_execution(self):
        self.definition["aliases"]["target build"] = "camera"
        self.save()
        with patch("scripts.gar_lib.product_operations.run_bounded") as run:
            code, output, errors = self.call(["product", "validate", "--json"])
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(output)["ok"])
            self.assertEqual(errors, "")
            run.assert_not_called()

    def test_invalid_paths_timeouts_and_duplicate_fields_are_rejected(self):
        entry = self.definition["operations"]["camera"]
        for name, value in (
            ("entrypoint", "../outside.py"),
            ("entrypoint", "/outside.py"),
            ("entrypoint", "C:/outside.py"),
            ("entrypoint", "camera.cmd"),
            ("entrypoint", "missing.py"),
            ("runtime", "shell"),
            ("timeout_seconds", True),
            ("timeout_seconds", 0),
            ("timeout_seconds", 3601),
            ("args", "string"),
        ):
            with self.subTest(name=name, value=value):
                original = entry.get(name)
                entry[name] = value
                self.save()
                with self.assertRaises(GarDomainError):
                    load_operations(self.root)
                if original is None:
                    del entry[name]
                else:
                    entry[name] = original
        (self.root / "gar-operations.json").write_text('{"schema_version":1,"schema_version":1,"operations":{}}')
        with self.assertRaises(GarDomainError):
            load_operations(self.root)

    @patch("scripts.gar_lib.product_operations.run_bounded")
    def test_timeout_and_invalid_json_do_not_expose_child_output(self, run):
        for result in (
            subprocess.TimeoutExpired("PRIVATE", 1),
            SimpleNamespace(returncode=1, stdout="PRIVATE", stderr="PRIVATE"),
        ):
            run.side_effect = result if isinstance(result, Exception) else None
            run.return_value = result
            with self.assertRaises(GarDomainError) as caught:
                execute_operation(load_operations(self.root), "camera", [], "Test")
            self.assertNotIn("PRIVATE", str(caught.exception))

    def test_real_nonzero_exit_and_false_ok_propagate(self):
        for suffix, expected in (("sys.exit(7)", 7), ("", 1)):
            (self.root / "camera.py").write_text(
                "import json,sys\nprint(json.dumps({'ok':False,'error':'fixture failure'}))\n" + suffix
            )
            code, output, _ = self.call(["product", "run", "camera", "--json"])
            self.assertEqual(code, expected)
            self.assertFalse(json.loads(output)["ok"])

    def test_real_timeout_stops_child_and_reports_bounded_failure(self):
        (self.root / "camera.py").write_text("import time\ntime.sleep(10)\n")
        self.definition["operations"]["camera"]["timeout_seconds"] = 1
        self.save()
        code, output, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 1)
        self.assertIn("1秒", json.loads(output)["error"])

    def test_explicit_help_json_preserves_envelope(self):
        code, output, _ = self.call(["product", "help", "camera", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["command"], "product.help")
        self.assertIn("Product camera help", json.loads(output)["result"]["output"])

    def test_nonboolean_ok_is_rejected(self):
        (self.root / "camera.py").write_text('print(\'{"ok": "false"}\')\n')
        code, output, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output)["ok"])

    def test_help_like_arguments_do_not_bypass_json_contract(self):
        (self.root / "camera.py").write_text("import json\nprint(json.dumps({'ok':False,'password':'PRIVATE'}))\n")
        for flag in ("-h", "--help"):
            code, output, _ = self.call(["product", "run", "camera", "--json", "--", flag, "480"])
            self.assertEqual(code, 1)
            self.assertNotIn("PRIVATE", output)

    def test_colliding_alias_does_not_block_canonical_execution(self):
        self.definition["aliases"] = {"target build": "camera"}
        self.save()
        code, output, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 0, output)

    def test_utf8_json_and_invalid_encoding(self):
        (self.root / "camera.py").write_text(
            "import json\nprint(json.dumps({'ok':True,'camera':'\\u65e5\\u672c'},ensure_ascii=False))\n"
        )
        code, output, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["result"]["camera"], "\u65e5\u672c")
        (self.root / "camera.py").write_text("import sys\nsys.stdout.buffer.write(b'\\xff')\n")
        code, output, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 1)
        self.assertIn("UTF-8", output)

    def test_timeout_kills_descendants(self):
        import time

        marker = self.root / "late.txt"
        worker = "import time;from pathlib import Path;time.sleep(2);Path('late.txt').write_text('late')"
        (self.root / "camera.py").write_text(
            "import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c'," + repr(worker) + "])\ntime.sleep(10)\n"
        )
        self.definition["operations"]["camera"]["timeout_seconds"] = 1
        self.save()
        code, _, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 1)
        time.sleep(1.5)
        self.assertFalse(marker.exists())

    def test_stdout_and_stderr_limits(self):
        for stream in ("stdout", "stderr"):
            (self.root / "camera.py").write_text(
                "import sys,time\nsys."
                + stream
                + ".buffer.write(b'x'*1100000)\nsys."
                + stream
                + ".flush()\ntime.sleep(10)\n"
            )
            code, output, _ = self.call(["product", "run", "camera", "--json"])
            self.assertEqual(code, 1)
            self.assertIn("上限", output)

    def test_product_python_environment(self):
        import sys

        environment = self.root / "python-env"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(environment)], check=True)
        relative = "python-env/Scripts/python.exe" if __import__("os").name == "nt" else "python-env/bin/python"
        self.definition["operations"]["camera"]["python"] = relative
        self.save()
        (self.root / "camera.py").write_text("import json,sys\nprint(json.dumps({'ok':True,'camera':sys.prefix}))\n")
        code, output, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 0, output)
        self.assertEqual(Path(json.loads(output)["result"]["camera"]), environment)

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_node_handler_and_text_output_use_the_same_runner(self):
        (self.root / "camera.cjs").write_text("process.stdout.write('node fixture '+process.argv[2]);")
        self.definition["operations"]["camera"] = {
            "entrypoint": "camera.cjs",
            "runtime": "node",
            "result": "text",
            "args": ["literal argument"],
        }
        self.save()
        code, output, _ = self.call(["product", "run", "camera", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["result"]["output"], "node fixture literal argument")


if __name__ == "__main__":
    unittest.main()

import contextlib
import io
import unittest
from unittest import mock

from support.gar_cli_test_support import GarCliDispatchAssertions

from scripts.gar_lib.cli import (
    build_parser,
    build_parser_bundle,
    completion_bash_script,
    completion_powershell_script,
    completion_zsh_script,
    main,
    normalize_question_help,
)
from scripts.gar_lib.core.command import (
    SIM_APP_BUILD,
    SIM_APP_CLEAN,
    SIM_APP_DEPLOY,
    SIM_HOST_START,
    SIM_HOST_STATUS,
    SIM_HOST_STOP,
    SIM_RUNTIME_BUILD,
    SIM_RUNTIME_DEPLOY,
    TARGET_BUILD,
    TARGET_DEPLOY,
    TARGET_FETCH,
)
from scripts.gar_lib.core.workspace import Workspace


class GarCliRootParserTest(GarCliDispatchAssertions, unittest.TestCase):
    def test_question_mark_prints_contextual_help(self) -> None:
        cases = [
            (["?"], "usage: gar", "code"),
            (["code", "?"], "usage: gar code", "start"),
            (["sim", "gpio", "?"], "usage: gar sim gpio", "plan"),
        ]

        for argv, usage, command in cases:
            with self.subTest(argv=argv):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = main(argv)

                self.assertEqual(0, result)
                text = output.getvalue()
                self.assertIn(usage, text)
                self.assertIn(command, text)

    def test_question_mark_normalization_ignores_command_remainder(self) -> None:
        self.assertEqual(["code", "--help"], normalize_question_help(["code", "?"]))
        self.assertEqual(
            ["terminal", "run", "--", "echo", "?"],
            normalize_question_help(["terminal", "run", "--", "echo", "?"]),
        )

    def test_parser_bundle_keeps_contextual_help_outside_argparse_parser(self) -> None:
        bundle = build_parser_bundle()

        self.assertEqual("gar", bundle.root.prog)
        self.assertFalse(hasattr(bundle.root, "_agp_subcommand_parsers"))
        self.assertTrue(
            {
                "config",
                "code",
                "terminal",
                "completion",
                "sim",
                "target",
                "usb",
                "hw",
            }.issubset(bundle.help_parsers)
        )

    def test_config_is_the_public_configuration_command(self) -> None:
        with mock.patch("scripts.gar_lib.commands.setup.run_config_cli", return_value=0) as run_config:
            result = main(["config", "--no-install"])

        self.assertEqual(0, result)
        run_config.assert_called_once()
        self.assertTrue(run_config.call_args.args[0].no_install)

    def test_completion_scripts_delegate_to_parser_candidates(self) -> None:
        text = completion_bash_script("/repo/scripts/gar")
        self.assertIn("completion words", text)
        self.assertIn("/repo/scripts/gar", text)
        self.assertIn("_gar_completion", text)
        self.assertNotIn("_agp_completion", text)

        zsh_text = completion_zsh_script("/repo/scripts/gar")
        self.assertIn("completion words", zsh_text)
        self.assertIn("compdef _gar_completion gar", zsh_text)

        powershell_text = completion_powershell_script(r"C:\repo\scripts\gar.cmd")
        self.assertIn("Register-ArgumentCompleter -Native -CommandName gar", powershell_text)
        self.assertIn("completion words", powershell_text)
        self.assertIn(r"C:\repo\scripts\gar.cmd", powershell_text)

    def test_completion_bash_is_available_from_cli(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "bash"])

        self.assertEqual(0, result)
        self.assertIn("completion words", output.getvalue())

    def test_completion_zsh_and_powershell_are_available_from_cli(self) -> None:
        for shell, expected in (
            ("zsh", "compdef _gar_completion gar"),
            ("powershell", "Register-ArgumentCompleter -Native -CommandName gar"),
        ):
            with self.subTest(shell=shell):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = main(["completion", shell])

                self.assertEqual(0, result)
                self.assertIn(expected, output.getvalue())

    def test_completion_hides_internal_words_protocol(self) -> None:
        help_output = io.StringIO()
        with contextlib.redirect_stdout(help_output):
            help_result = main(["completion", "--help"])

        self.assertEqual(0, help_result)
        self.assertNotIn("words", help_output.getvalue())

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "words", "--cword", "2", "--", "gar", "completion", ""])

        self.assertEqual(0, result)
        candidates = output.getvalue().splitlines()
        self.assertIn("powershell", candidates)
        self.assertIn("bash", candidates)
        self.assertIn("zsh", candidates)
        self.assertNotIn("words", candidates)

    def test_completion_words_uses_parser_commands(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "words", "--cword", "2", "--", "gar", "sim", ""])

        self.assertEqual(0, result)
        self.assertIn("build", output.getvalue().splitlines())
        self.assertIn("deploy", output.getvalue().splitlines())
        self.assertIn("start", output.getvalue().splitlines())
        self.assertIn("infra", output.getvalue().splitlines())
        self.assertNotIn("app", output.getvalue().splitlines())
        self.assertNotIn("runtime", output.getvalue().splitlines())
        self.assertNotIn("host", output.getvalue().splitlines())
        self.assertNotIn("ui", output.getvalue().splitlines())

    def test_completion_words_lists_sim_host_commands(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["completion", "words", "--cword", "3", "--", "gar", "sim", "host", ""])

        self.assertEqual(0, result)
        self.assertIn("start", output.getvalue().splitlines())
        self.assertIn("stop", output.getvalue().splitlines())
        self.assertIn("status", output.getvalue().splitlines())

    def test_cli_surface_maps_one_to_one_to_gar_commands(self) -> None:
        """CLI表面と GarCommand と retry 文字列が、往復して一致すること。"""

        parser = build_parser()
        for argv, command in (
            (["sim", "app", "build"], SIM_APP_BUILD),
            (["sim", "app", "clean"], SIM_APP_CLEAN),
            (["sim", "app", "deploy"], SIM_APP_DEPLOY),
            (["sim", "runtime", "build"], SIM_RUNTIME_BUILD),
            (["sim", "runtime", "deploy"], SIM_RUNTIME_DEPLOY),
            (["sim", "host", "start"], SIM_HOST_START),
            (["sim", "host", "stop"], SIM_HOST_STOP),
            (["sim", "host", "status"], SIM_HOST_STATUS),
            (["target", "build"], TARGET_BUILD),
            (["target", "deploy"], TARGET_DEPLOY),
            (["target", "fetch"], TARGET_FETCH),
        ):
            invocation = [*argv, "--workspace", "Local/Product"]
            with self.subTest(argv=argv):
                args = parser.parse_args(invocation)
                self.assertEqual(command, args.gar_command)
                self.assertFalse(hasattr(args, "action_handler"))
                canonical = [argv[0], argv[2], argv[1]] if argv[0] == "sim" else argv
                self.assertEqual(
                    " ".join(["gar", *canonical, "--workspace", "Local/Product"]),
                    command.to_cli(workspace="Local/Product"),
                )
                if command.group == "target":
                    self.assert_target_dispatches(invocation, command)
                else:
                    self.assert_sim_dispatches(invocation, command)

    def test_workspace_is_optional(self) -> None:
        self.assert_sim_dispatches(
            ["sim", "app", "build"],
            SIM_APP_BUILD,
            workspace=None,
        )

    def test_gar_command_delegates_to_the_group_runner(self) -> None:
        workspace = Workspace(id="ws", name="Local/Product", branch="main", connection={"type": "local"})
        with (
            mock.patch("scripts.gar_lib.commands.sim.resolve_workspace", return_value=workspace),
            mock.patch("scripts.gar_lib.cli.sim.run_sim_command", return_value=0) as run_sim,
        ):
            result = main(["sim", "app", "build"])

        self.assertEqual(0, result)
        (args,) = run_sim.call_args.args
        self.assertEqual(SIM_APP_BUILD, args.gar_command)

    def test_sim_app_build_rejects_workspace_root_option(self) -> None:
        with self.assertRaises(SystemExit):
            main(["sim", "app", "build", "--workspace-root", "/tmp/product"])

    def test_sim_host_start_forwards_host_controller_options(self) -> None:
        self.assert_sim_dispatches(
            ["sim", "host", "start", "--workspace", "Local/GarStreamTx", "--no-update-ssh", "--pull"],
            SIM_HOST_START,
            no_update_ssh=True,
            pull=True,
        )

    def test_sim_host_status_updates_address_by_default(self) -> None:
        self.assert_sim_dispatches(
            ["sim", "host", "status", "--workspace", "Local/GarStreamTx"],
            SIM_HOST_STATUS,
            json_output=False,
        )

    def test_sim_infra_setup_is_available_from_cli(self) -> None:
        with mock.patch("scripts.gar_lib.commands.sim.run_sim_infra_command", return_value=0) as run_infra:
            result = main(
                [
                    "sim",
                    "infra",
                    "setup",
                    "--region",
                    "ap-test-1",
                    "--key-name",
                    "gar-key",
                    "--ssh-cidr",
                    "203.0.113.4/32",
                ]
            )

        self.assertEqual(0, result)
        run_infra.assert_called_once_with(
            "setup",
            key_name="gar-key",
            region="ap-test-1",
            ssh_cidr="203.0.113.4/32",
            auto_approve=False,
        )

    def test_sim_infra_output_is_not_a_public_cli_command(self) -> None:
        with (
            mock.patch("scripts.gar_lib.commands.sim.run_sim_infra_command") as run_infra,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as exc:
                main(["sim", "infra", "output"])

        self.assertEqual(2, exc.exception.code)
        run_infra.assert_not_called()

    def test_target_deploy_rejects_legacy_connection_overrides(self) -> None:
        for option, value in (
            ("--serial", "device-1"),
            ("--port", "COM3"),
            ("--host", "raspi"),
            ("--dest", "/opt/product"),
            ("--artifacts-dir", "/tmp/artifacts"),
            ("--codespace", "product-space"),
            ("--remote-root", "/workspaces/product"),
        ):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main(["target", "deploy", option, value])

            self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()

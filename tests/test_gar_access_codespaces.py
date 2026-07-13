from __future__ import annotations

import unittest

from scripts.gar_lib.access.codespaces import codespace_list_rows, select_codespace_from_list


class GarCodespacesAccessTest(unittest.TestCase):
    def test_selects_the_only_codespace(self) -> None:
        output = "single-codespace\towner/repo\tmain\tStopped\tShutdown\t1h\n"

        self.assertEqual("single-codespace", select_codespace_from_list(output))

    def test_selects_first_available_codespace(self) -> None:
        output = "\n".join(
            [
                "stopped-codespace\towner/repo\tmain\tStopped\tShutdown\t1h",
                "available-codespace\towner/repo\tmain\tRunning\tAvailable\t2h",
                "other-codespace\towner/repo\tmain\tRunning\tAvailable\t3h",
            ]
        )

        self.assertEqual("available-codespace", select_codespace_from_list(output))

    def test_ignores_header_and_empty_rows(self) -> None:
        output = "NAME\tREPOSITORY\tBRANCH\tSTATE\n\nproduct\towner/repo\tmain\tAvailable\n"

        self.assertEqual(
            [["product", "owner/repo", "main", "Available"]],
            codespace_list_rows(output),
        )

"""GitHub Codespaces command-output parsing shared across use cases."""

from __future__ import annotations


def select_codespace_from_list(output: str) -> str | None:
    rows = codespace_list_rows(output)
    if len(rows) == 1:
        return rows[0][0]

    for fields in rows:
        if len(fields) >= 5 and fields[4] == "Available" and fields[0]:
            return fields[0]
    return None


def codespace_list_rows(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if not fields or not fields[0] or fields[0] == "NAME":
            continue
        rows.append(fields)
    return rows

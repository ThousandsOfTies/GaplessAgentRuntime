"""`gar terminal` subcommand: VSCode integrated terminal request bridge."""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from scripts.gar_lib.config import CONFIG_PATH


def run_terminal_request(
    *,
    command_parts: Sequence[str],
    command_text: str | None = None,
    title: str,
    cwd: str | None,
) -> int:
    command = command_text.strip() if command_text else " ".join(command_parts).strip()
    if command.startswith("-- "):
        command = command[3:].strip()
    if not command:
        print("実行するコマンドを指定してください。", file=sys.stderr)
        return 1

    request_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"{request_id}-{uuid.uuid4().hex[:8]}"
    request_dir = CONFIG_PATH.parent / "terminal-requests"
    request_dir.mkdir(parents=True, exist_ok=True)

    request_path = request_dir / f"{request_id}.json"
    request = {
        "id": request_id,
        "created_at": datetime.now(UTC).isoformat(),
        "title": title,
        "cwd": str(Path(cwd).resolve() if cwd else Path.cwd()),
        "command": command,
    }
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"VSCode terminal request を作成しました: {request_path}")
    return 0


def run_terminal_gc(*, keep_days: int, dry_run: bool) -> int:
    if keep_days < 0:
        print("--keep-days は 0 以上を指定してください。", file=sys.stderr)
        return 1

    base = CONFIG_PATH.parent
    targets = [
        base / "terminal-requests" / "processed",
        base / "terminal-status",
    ]
    cutoff = datetime.now(UTC).timestamp() - keep_days * 86400
    removed = 0
    scanned = 0
    for directory in targets:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            scanned += 1
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            if dry_run:
                print(f"[dry-run] would remove: {path}")
            else:
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    print(f"failed to remove {path}: {exc}", file=sys.stderr)

    action = "対象" if dry_run else "削除"
    print(f"scan: {scanned} ファイル / {action}: {removed}")
    return 0

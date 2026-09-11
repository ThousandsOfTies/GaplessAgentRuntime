"""Real filesystem fixtures, with explicit handling of missing Windows privileges."""

from pathlib import Path
from unittest import SkipTest


def symlink_or_skip(link: Path, target: str | Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            raise SkipTest("Windows account cannot create symlinks; real link validation runs on Linux") from error
        raise

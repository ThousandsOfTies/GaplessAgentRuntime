"""Safe extraction helpers for archives downloaded by GAR."""

from __future__ import annotations

import tarfile
from pathlib import Path, PurePosixPath


class UnsafeArchiveError(ValueError):
    """Raised when an archive member could escape or alter the destination."""


def safe_extract_tar(tarball: Path, destination: Path) -> None:
    """Extract regular files/directories without following archive links."""

    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()

    with tarfile.open(tarball, "r:*") as archive:
        members = archive.getmembers()
        for member in members:
            _validate_tar_member(member, destination_root)

        # Every member has been constrained to destination_root and links are
        # rejected. Python's data filter remains a second line of validation.
        archive.extractall(destination_root, members=members, filter="data")  # noqa: S202


def _validate_tar_member(member: tarfile.TarInfo, destination_root: Path) -> None:
    if member.issym() or member.islnk():
        raise UnsafeArchiveError(f"link member is not allowed: {member.name}")
    if not (member.isdir() or member.isfile()):
        raise UnsafeArchiveError(f"unsupported tar member type: {member.name}")

    member_path = Path(member.name)
    if PurePosixPath(member.name).is_absolute() or member_path.is_absolute():
        raise UnsafeArchiveError(f"absolute path is not allowed: {member.name}")

    extracted_path = (destination_root / member_path).resolve()
    if not extracted_path.is_relative_to(destination_root):
        raise UnsafeArchiveError(f"path escapes destination: {member.name}")

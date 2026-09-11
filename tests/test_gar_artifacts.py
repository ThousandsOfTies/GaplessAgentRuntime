from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from support.filesystem import symlink_or_skip

from scripts.gar_lib.artifacts.manifest import parse_artifact_manifest, resolve_artifact_src
from scripts.gar_lib.artifacts.metadata import (
    CURRENT_SCHEMA_VERSION,
    UNKNOWN_PROVENANCE,
    ArtifactMetadata,
    ArtifactMetadataError,
    ArtifactTarget,
    discover_kernel_dependency,
    load_artifact_metadata,
    parse_artifact_metadata,
    write_artifact_metadata,
)
from scripts.gar_lib.artifacts.provenance import (
    CaptureProvenance,
    collect_capture_provenance,
    collect_target_tools_provenance,
)
from scripts.gar_lib.artifacts.store import LocalArtifactStore
from scripts.gar_lib.core.artifact import ArtifactKind
from scripts.gar_lib.core.errors import GarDomainError
from scripts.gar_lib.core.workspace import Workspace


def local_workspace(root: Path) -> Workspace:
    return Workspace(
        id="ws_artifacts",
        name="Local/Artifacts",
        branch="Artifacts",
        connection={"type": "local", "path": str(root)},
        selected_environments={"codespace": "local"},
    )


def write_app_bundle(root: Path, content: str) -> None:
    artifact_file = root / "files" / "app"
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text(content, encoding="utf-8")
    (root / "artifact.json").write_text(
        json.dumps(
            {
                "deploy": {
                    "app": {
                        "files": [
                            {
                                "src": "files/app",
                                "dest": "~/app",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def init_git_repository(root: Path, files: dict[str, str]) -> str:
    root.mkdir(parents=True)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    subprocess.run(("git", "-C", str(root), "add", "."), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=GAR Test",
            "-c",
            "user.email=gar@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ),
        check=True,
    )
    result = subprocess.run(
        ("git", "-C", str(root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class ArtifactManifestTest(unittest.TestCase):
    def test_manifest_accepts_file_and_product_artifact_sections(self) -> None:
        manifest = parse_artifact_manifest(
            {
                "name": "vibe-remote",
                "deploy": {
                    "vscodeExtension": {
                        "files": [
                            {
                                "src": "files/vibe-remote-extension",
                                "dest": "~/vibe-remote-extension",
                            }
                        ]
                    },
                    "m5stickcFirmware": {"artifact": "files/m5stickc-firmware"},
                    "optionalFirmware": {"artifact": None},
                },
            }
        )

        self.assertEqual(
            (
                "files/vibe-remote-extension",
                "files/m5stickc-firmware",
            ),
            manifest.sources,
        )

    def test_manifest_preserves_optional_target_and_entrypoint(self) -> None:
        manifest = parse_artifact_manifest(
            {
                "name": "demo-target",
                "target": "luckfox-rk3506",
                "entrypoint": "/opt/gar/apps/demo/run",
                "deploy": {
                    "app": {
                        "files": [{"src": "files/demo", "dest": "/opt/gar/apps/demo"}],
                    }
                },
            }
        )

        self.assertEqual("luckfox-rk3506", manifest.target)
        self.assertEqual("/opt/gar/apps/demo/run", manifest.entrypoint)

    def test_artifact_source_resolution_rejects_internal_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            files = bundle / "files"
            files.mkdir()
            (files / "real").write_text("content", encoding="utf-8")
            symlink_or_skip(files / "linked", "real")

            with contextlib.redirect_stderr(io.StringIO()):
                resolved = resolve_artifact_src(bundle, "files/linked")

        self.assertIsNone(resolved)

    def test_artifact_source_resolution_rejects_nested_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            directory = bundle / "files" / "application"
            directory.mkdir(parents=True)
            (directory / "real").write_text("content", encoding="utf-8")
            symlink_or_skip(directory / "linked", "real")

            with contextlib.redirect_stderr(io.StringIO()):
                resolved = resolve_artifact_src(bundle, "files/application")

        self.assertIsNone(resolved)


class ArtifactMetadataTest(unittest.TestCase):
    def test_metadata_writer_is_atomic_and_not_group_or_world_writable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = ArtifactMetadata(
                schema_version=CURRENT_SCHEMA_VERSION,
                kind="target_app",
                workspace_id="ws",
                build_id="build",
                build_timestamp="2026-08-11T00:00:00+00:00",
            )
            previous_umask = os.umask(0)
            try:
                write_artifact_metadata(root, metadata)
            finally:
                os.umask(previous_umask)

            path = root / "artifact-info.json"
            mode = stat.S_IMODE(path.stat().st_mode)
            temporary_files = list(root.glob(".artifact-info-*.json"))

        if os.name == "posix":
            self.assertEqual(0o644, mode)
        self.assertEqual([], temporary_files)

    def test_loader_accepts_the_legacy_metadata_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "gar-artifact.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "sim_app",
                        "workspace_id": "ws",
                        "build_id": "legacy-build",
                        "captured_at": "2026-08-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            metadata = load_artifact_metadata(root)

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual("legacy-build", metadata.build_id)

    def test_loader_rejects_ambiguous_metadata_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "artifact-info.json").write_text("{}\n", encoding="utf-8")
            (root / "gar-artifact.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ArtifactMetadataError, "multiple metadata files"):
                load_artifact_metadata(root)

    def test_future_snapshot_schema_is_rejected_explicitly(self) -> None:
        with self.assertRaisesRegex(ArtifactMetadataError, "unsupported.*schema_version: 3"):
            parse_artifact_metadata({"schema_version": 3})

    def test_kernel_module_without_vermagic_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = root / "modules" / "broken.ko"
            module.parent.mkdir()
            module.write_bytes(b"not-a-valid-kernel-module")

            with self.assertRaisesRegex(ArtifactMetadataError, "vermagic is missing"):
                discover_kernel_dependency(root)


class LocalArtifactStoreTest(unittest.TestCase):
    def test_simulation_manifest_target_may_differ_from_selected_physical_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = replace(
                local_workspace(root / "product"),
                selected_target="raspberry-pi-5",
            )
            staging = workspace.local_root / "artifacts" / "from-codespace"
            write_app_bundle(staging, "simulation")
            manifest_path = staging / "artifact.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["target"] = "linux-device"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            store = LocalArtifactStore(snapshot_root=root / "snapshots")

            artifact = store.capture(
                ArtifactKind.SIM_APP,
                workspace,
                CaptureProvenance(
                    source_commit="a" * 40,
                    gar_tools_commit="b" * 40,
                    target=ArtifactTarget(id="linux-device", architecture="aarch64"),
                ),
            )
            metadata = load_artifact_metadata(artifact.bundle_path)

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual("linux-device", metadata.target.id)

    def test_capture_writes_complete_v2_provenance_and_file_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = replace(
                local_workspace(root / "product"),
                selected_target="luckfox-rk3506",
            )
            staging = workspace.local_root / "artifacts" / "from-codespace"
            app = staging / "files" / "demo"
            modules = app / "modules" / "6.1.84"
            modules.mkdir(parents=True)
            (app / "run").write_text("#!/bin/sh\n", encoding="utf-8")
            (modules / "spidev.ko").write_bytes(
                b"module\x00vermagic=6.1.84 SMP preempt mod_unload ARMv7 thumb2 p2v8 \x00"
            )
            (staging / "artifact.json").write_text(
                json.dumps(
                    {
                        "name": "demo-target",
                        "target": "luckfox-rk3506",
                        "deploy": {
                            "app": {
                                "files": [
                                    {
                                        "src": "files/demo",
                                        "dest": "/opt/gar/apps/demo",
                                    }
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = LocalArtifactStore(snapshot_root=root / "snapshots")
            provenance = CaptureProvenance(
                source_commit="a" * 40,
                gar_tools_commit="b" * 40,
                target=ArtifactTarget(
                    id="luckfox-rk3506",
                    architecture="armv7l",
                    abi="gnueabihf",
                    libc="glibc",
                    toolchain_triple="arm-buildroot-linux-gnueabihf",
                ),
                target_recipe_version="1",
            )

            artifact = store.capture(ArtifactKind.TARGET_APP, workspace, provenance)
            metadata = load_artifact_metadata(artifact.bundle_path)

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(CURRENT_SCHEMA_VERSION, metadata.schema_version)
        self.assertEqual("target_app", metadata.kind)
        self.assertEqual("demo-target", metadata.product)
        self.assertEqual(workspace.id, metadata.workspace_id)
        self.assertEqual("luckfox-rk3506", metadata.target.id)
        self.assertEqual("armv7l", metadata.target.architecture)
        self.assertEqual("/opt/gar/apps/demo/run", metadata.entrypoint)
        self.assertEqual("demo", metadata.app_name)
        self.assertEqual("a" * 40, metadata.source_commit)
        self.assertEqual("b" * 40, metadata.gar_tools_commit)
        self.assertEqual("1", metadata.target_recipe_version)
        self.assertIn("artifact.json", metadata.checksums)
        self.assertIn("files/demo/run", metadata.checksums)
        self.assertEqual("6.1.84", metadata.kernel.release)
        self.assertIn("6.1.84 SMP preempt mod_unload ARMv7 thumb2 p2v8", metadata.kernel.vermagic)

    def test_target_capture_rejects_manifest_for_other_selected_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = replace(
                local_workspace(root / "product"),
                selected_target="raspberry-pi-5",
            )
            staging = workspace.local_root / "artifacts" / "from-codespace"
            write_app_bundle(staging, "target")
            manifest_path = staging / "artifact.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["target"] = "luckfox-rk3506"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            store = LocalArtifactStore(snapshot_root=root / "snapshots")

            with self.assertRaisesRegex(GarDomainError, "Target ID"):
                store.capture(ArtifactKind.TARGET_APP, workspace)

    def test_artifact_kinds_keep_independent_immutable_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = local_workspace(root / "product")
            staging = workspace.local_root / "artifacts" / "from-codespace"
            store = LocalArtifactStore(snapshot_root=root / "snapshots")

            write_app_bundle(staging, "simulation")
            simulation = store.capture(ArtifactKind.SIM_APP, workspace)

            write_app_bundle(staging, "target")
            target = store.capture(ArtifactKind.TARGET_APP, workspace)

            latest_simulation = store.latest(ArtifactKind.SIM_APP, workspace)
            latest_target = store.latest(ArtifactKind.TARGET_APP, workspace)

            self.assertNotEqual(simulation.bundle_path, target.bundle_path)
            self.assertEqual(
                "simulation",
                (latest_simulation.bundle_path / "files" / "app").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "target",
                (latest_target.bundle_path / "files" / "app").read_text(encoding="utf-8"),
            )

    def test_capture_rejects_symlinks_in_the_staging_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = local_workspace(root / "product")
            staging = workspace.local_root / "artifacts" / "from-codespace"
            store = LocalArtifactStore(snapshot_root=root / "snapshots")
            write_app_bundle(staging, "placeholder")
            outside = root / "outside"
            outside.write_text("must not be captured", encoding="utf-8")
            (staging / "files" / "app").unlink()
            symlink_or_skip(staging / "files" / "app", outside)

            with self.assertRaisesRegex(GarDomainError, "symlink"):
                store.capture(ArtifactKind.SIM_APP, workspace)

            self.assertFalse((root / "snapshots").exists())

    def test_capture_rejects_product_owned_deployment_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = local_workspace(root / "product")
            staging = workspace.local_root / "artifacts" / "from-codespace"
            store = LocalArtifactStore(snapshot_root=root / "snapshots")
            write_app_bundle(staging, "placeholder")
            reserved = staging / "files" / "application" / ".artifact-info.json"
            reserved.parent.mkdir()
            reserved.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(GarDomainError, "GAR所有metadata"):
                store.capture(ArtifactKind.SIM_APP, workspace)

            self.assertFalse((root / "snapshots").exists())

    def test_capture_rejects_product_owned_deployment_marker_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = local_workspace(root / "product")
            staging = workspace.local_root / "artifacts" / "from-codespace"
            store = LocalArtifactStore(snapshot_root=root / "snapshots")
            write_app_bundle(staging, "placeholder")
            reserved = staging / "files" / "application" / ".gar-artifact.json"
            reserved.mkdir(parents=True)

            with self.assertRaisesRegex(GarDomainError, "GAR所有metadata"):
                store.capture(ArtifactKind.SIM_APP, workspace)

            self.assertFalse((root / "snapshots").exists())

    def test_capture_rejects_product_owned_snapshot_metadata(self) -> None:
        for filename in ("artifact-info.json", "gar-artifact.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = local_workspace(root / "product")
                staging = workspace.local_root / "artifacts" / "from-codespace"
                store = LocalArtifactStore(snapshot_root=root / "snapshots")
                write_app_bundle(staging, "placeholder")
                (staging / filename).write_text("{}\n", encoding="utf-8")

                with self.assertRaisesRegex(GarDomainError, "GAR所有metadata"):
                    store.capture(ArtifactKind.SIM_APP, workspace)

                self.assertFalse((root / "snapshots").exists())

    def test_latest_accepts_existing_schema_v1_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = local_workspace(root / "product")
            kind_root = root / "snapshots" / workspace.id / ArtifactKind.SIM_APP.value
            snapshot = kind_root / "legacy-build"
            write_app_bundle(snapshot, "legacy")
            (snapshot / "gar-artifact.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "sim_app",
                        "workspace_id": workspace.id,
                        "build_id": "legacy-build",
                        "captured_at": "2026-08-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            (kind_root / "latest.json").write_text(
                json.dumps({"build_id": "legacy-build"}),
                encoding="utf-8",
            )
            store = LocalArtifactStore(snapshot_root=root / "snapshots")

            artifact = store.latest(ArtifactKind.SIM_APP, workspace)

        self.assertEqual(snapshot, artifact.bundle_path)

    def test_latest_rejects_tampered_v2_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = local_workspace(root / "product")
            staging = workspace.local_root / "artifacts" / "from-codespace"
            store = LocalArtifactStore(snapshot_root=root / "snapshots")
            write_app_bundle(staging, "before")
            artifact = store.capture(ArtifactKind.SIM_APP, workspace)
            (artifact.bundle_path / "files" / "app").write_text("after", encoding="utf-8")

            with self.assertRaisesRegex(GarDomainError, "checksum mismatch"):
                store.latest(ArtifactKind.SIM_APP, workspace)

    def test_latest_rejects_file_and_directory_symlinks_added_after_capture(self) -> None:
        for node_type in ("file", "directory"):
            with self.subTest(node_type=node_type), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = local_workspace(root / "product")
                staging = workspace.local_root / "artifacts" / "from-codespace"
                store = LocalArtifactStore(snapshot_root=root / "snapshots")
                write_app_bundle(staging, "before")
                artifact = store.capture(ArtifactKind.SIM_APP, workspace)
                outside = root / f"outside-{node_type}"
                injected = artifact.bundle_path / f"injected-{node_type}"
                if node_type == "file":
                    outside.write_text("outside\n", encoding="utf-8")
                    symlink_or_skip(injected, outside)
                else:
                    outside.mkdir()
                    (outside / "payload").write_text("outside\n", encoding="utf-8")
                    symlink_or_skip(injected, outside, target_is_directory=True)

                with self.assertRaisesRegex(GarDomainError, "bundle contains symlink"):
                    store.latest(ArtifactKind.SIM_APP, workspace)


class CaptureProvenanceTest(unittest.TestCase):
    def test_local_dirty_source_is_unknown_but_ignored_build_output_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = root / "product"
            tools = root / "gar-tools"
            product_commit = init_git_repository(
                product,
                {
                    ".gitignore": "build/\n",
                    "source.txt": "clean\n",
                },
            )
            tools_commit = init_git_repository(tools, {"README.md": "tools\n"})
            selected_workspace = Workspace(
                id="ws_dirty",
                name="Local/Dirty",
                branch="Dirty",
                connection={"type": "local", "path": str(product)},
                selected_environments={"codespace": "local"},
            )

            with mock.patch(
                "scripts.gar_lib.artifacts.provenance._workspace_tools_root",
                return_value=tools,
            ):
                clean = collect_capture_provenance(selected_workspace, None)
                (product / "source.txt").write_text("dirty\n", encoding="utf-8")
                dirty = collect_capture_provenance(selected_workspace, None)
                (product / "source.txt").write_text("clean\n", encoding="utf-8")
                ignored_output = product / "build" / "output.bin"
                ignored_output.parent.mkdir()
                ignored_output.write_bytes(b"ignored")
                ignored = collect_capture_provenance(selected_workspace, None)

        self.assertEqual(product_commit, clean.source_commit)
        self.assertEqual(tools_commit, clean.gar_tools_commit)
        self.assertEqual(UNKNOWN_PROVENANCE, dirty.source_commit)
        self.assertEqual(product_commit, ignored.source_commit)

    def test_active_tools_dirty_tree_has_no_deployable_commit_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools_root = Path(temporary) / "gar-tools"
            manifest_relative = "targets/raspberry-pi-5/target.json"
            manifest_payload = json.dumps(
                {
                    "provisioning": {
                        "ssh_scp": {
                            "recipeVersion": 2,
                        }
                    }
                }
            )
            init_git_repository(tools_root, {manifest_relative: manifest_payload})
            manifest_path = tools_root / manifest_relative
            (manifest_path.parent / "untracked-recipe-file").write_text("dirty\n", encoding="utf-8")

            provenance = collect_target_tools_provenance(
                manifest_path,
                "ssh_scp",
                target_id="raspberry-pi-5",
            )

        self.assertEqual(UNKNOWN_PROVENANCE, provenance.gar_tools_commit)
        self.assertEqual("2", provenance.target_recipe_version)

    def test_active_target_tools_provenance_uses_selected_manifest_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools_root = Path(temporary) / "gar-tools"
            target_dir = tools_root / "targets" / "raspberry-pi-5"
            target_dir.mkdir(parents=True)
            manifest_path = target_dir / "target.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "provisioning": {
                            "ssh_scp": {
                                "recipeVersion": 7,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch(
                "scripts.gar_lib.artifacts.provenance._git_commit",
                return_value="c" * 40,
            ) as git_commit:
                provenance = collect_target_tools_provenance(
                    manifest_path,
                    "ssh_scp",
                    target_id="raspberry-pi-5",
                )

        self.assertEqual("raspberry-pi-5", provenance.target_id)
        self.assertEqual("c" * 40, provenance.gar_tools_commit)
        self.assertEqual("7", provenance.target_recipe_version)
        git_commit.assert_called_once_with(tools_root)

    def test_local_target_provenance_uses_pinned_tools_compatibility_and_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "product"
            target_dir = root / "sources" / "gar-tools" / "targets" / "luckfox-rk3506"
            target_dir.mkdir(parents=True)
            (target_dir / "target.json").write_text(
                json.dumps(
                    {
                        "compatibility": {
                            "architecture": "armv7l",
                            "abi": "gnueabihf",
                            "libc": "glibc",
                            "toolchainTriple": "arm-buildroot-linux-gnueabihf",
                        },
                        "provisioning": {"ssh_scp": {"recipeVersion": 3}},
                    }
                ),
                encoding="utf-8",
            )
            selected_workspace = Workspace(
                id="ws_local",
                name="Local/Product",
                branch="Product",
                connection={"type": "local", "path": str(root)},
                selected_target="luckfox-rk3506",
                selected_environments={"codespace": "local", "target": "ssh_scp"},
            )
            with mock.patch(
                "scripts.gar_lib.artifacts.provenance._git_commit",
                side_effect=("a" * 40, "b" * 40),
            ):
                provenance = collect_capture_provenance(
                    selected_workspace,
                    "luckfox-rk3506",
                )

        self.assertEqual("a" * 40, provenance.source_commit)
        self.assertEqual("b" * 40, provenance.gar_tools_commit)
        self.assertEqual("armv7l", provenance.target.architecture)
        self.assertEqual("gnueabihf", provenance.target.abi)
        self.assertEqual("glibc", provenance.target.libc)
        self.assertEqual("arm-buildroot-linux-gnueabihf", provenance.target.toolchain_triple)
        self.assertEqual("3", provenance.target_recipe_version)

    def test_codespaces_commits_are_measured_in_the_remote_build_workspace(self) -> None:
        selected_workspace = Workspace(
            id="ws_remote",
            name="Codespaces/Product",
            branch="Product",
            connection={
                "type": "codespaces",
                "path": "/workspaces/product",
                "codespace": "product-space",
            },
            selected_environments={"codespace": "github_codespaces"},
        )
        process = mock.Mock(returncode=0)
        process.communicate.return_value = (f"{'a' * 40}\n{'b' * 40}\n", "")

        with mock.patch(
            "scripts.gar_lib.artifacts.provenance.subprocess.Popen",
            return_value=process,
        ) as popen:
            provenance = collect_capture_provenance(selected_workspace, None)

        self.assertEqual("a" * 40, provenance.source_commit)
        self.assertEqual("b" * 40, provenance.gar_tools_commit)
        command = popen.call_args.args[0][-1]
        self.assertIn("status --porcelain=v1", command)
        self.assertIn("--ignore-submodules=none", command)
        self.assertIn("git -C /workspaces/product rev-parse HEAD", command)
        self.assertIn("sources/gar-tools", command)

    def test_codespaces_dirty_source_or_tools_commit_is_not_recorded(self) -> None:
        selected_workspace = Workspace(
            id="ws_remote_dirty",
            name="Codespaces/Dirty",
            branch="Dirty",
            connection={
                "type": "codespaces",
                "path": "/workspaces/product",
                "codespace": "product-space",
            },
            selected_environments={"codespace": "github_codespaces"},
        )
        cases = (
            (f"__GAR_DIRTY__\n{'b' * 40}\n", UNKNOWN_PROVENANCE, "b" * 40),
            (f"{'a' * 40}\n__GAR_DIRTY__\n", "a" * 40, UNKNOWN_PROVENANCE),
        )
        for stdout, expected_source, expected_tools in cases:
            with self.subTest(stdout=stdout):
                process = mock.Mock(returncode=0)
                process.communicate.return_value = (stdout, "")
                with mock.patch(
                    "scripts.gar_lib.artifacts.provenance.subprocess.Popen",
                    return_value=process,
                ):
                    provenance = collect_capture_provenance(selected_workspace, None)

                self.assertEqual(expected_source, provenance.source_commit)
                self.assertEqual(expected_tools, provenance.gar_tools_commit)


if __name__ == "__main__":
    unittest.main()

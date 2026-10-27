#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline native-plugin payload tests; no root, chroot, GPU or SDK calls."""
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


DIRECTORY = Path(__file__).resolve().parents[1]
LAYER = DIRECTORY.parents[1]
SDK_FILES = DIRECTORY.parent / "edge-ai-sdk-manager/files"
ARGUS = DIRECTORY / "files/build-argus-deb.py"
HELPER = DIRECTORY / "files/build-gstreamer-deb.py"
SPEC = importlib.util.spec_from_file_location("gst_deb_under_test", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def elf(machine=183):
    return (b"\x7fELF\x02\x01\x01" + b"\0" * 9 +
            struct.pack("<HHIQQQIHHHHHH", 3, machine, 1, 0, 0, 0,
                        0, 64, 0, 0, 0, 0, 0))


def snapshot(root):
    return {path.relative_to(root).as_posix():
            ("link", str(path.readlink())) if path.is_symlink() else
            ("file", path.read_bytes(), path.stat().st_mode) if path.is_file()
            else ("dir", path.stat().st_mode)
            for path in root.rglob("*")}


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb required")
class GStreamerDebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gst-deb-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        shutil.copyfile(HELPER, self.sources / HELPER.name)
        shutil.copyfile(ARGUS, self.sources / ARGUS.name)
        for name in ("provision-runtime.py", "runtime-assets.json"):
            shutil.copyfile(SDK_FILES / name, self.sources / name)
        shutil.copyfile(SDK_FILES / "sdk-source/compulab/tools/rootfs_package_inventory.py",
                        self.sources / "rootfs_package_inventory.py")
        self.bundle = self.root / "runtime"
        shutil.copytree(SDK_FILES / "runtime", self.bundle,
                        ignore=shutil.ignore_patterns("__pycache__", "scratch"))
        self.builder = self.root / "prepared-builder"
        self.builder.mkdir()
        self.put("usr/lib/os-release", b'ID=ubuntu\nVERSION_ID="24.04"\n')
        (self.builder / "etc").mkdir()
        (self.builder / "etc/os-release").symlink_to("../usr/lib/os-release")
        names = ("nvidia-l4t-camera", "nvidia-l4t-multimedia", "nvidia-l4t-gstreamer")
        versions = {name: "39.2.1-20260806224157" for name in names}
        versions.update({name: "13.2.86-1" for name in
                         ("cuda-nvcc-13-2", "cuda-cudart-13-2")})
        self.put("var/lib/dpkg/status", "\n\n".join(
            f"Package: {name}\nStatus: hold ok installed\nArchitecture: arm64\n"
            f"Version: {version}\n" for name, version in versions.items()).encode())
        for name in ("dpkg", "cmake", "g++", "make", "pkg-config", "patch",
                     "xxd", "readelf"):
            self.put("usr/bin/" + name, elf())
        self.put("usr/local/cuda-13.2/bin/nvcc", elf())
        self.put("opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1", elf())
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.mmapi = self.assets / "mmapi.deb"
        self.public = self.assets / "public.tbz2"
        self.source_package()
        self.subarchives = {name: ("pinned " + name).encode() for name in MODULE.ARCHIVES}
        self.public_archive()
        self.manifest = json.loads((self.sources / "runtime-assets.json").read_text())
        self.update_assets()
        self.run_dir = self.root / "runs/new-run"
        self.run_dir.mkdir(parents=True)
        self.config = dict(sources=self.sources, bundle=self.bundle,
                           builder=self.builder,
                           assets=dict(mmapi=self.mmapi, publicsources=self.public),
                           uid=os.getuid(), gid=os.getgid(), jobs=2)
        self.support = MODULE.support_module(self.config)

    def put(self, name, data):
        path = self.builder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def source_package(self, architecture="arm64", version="39.2.1-20260806224157"):
        package = self.root / "source-package"
        (package / "DEBIAN").mkdir(parents=True, exist_ok=True)
        (package / "DEBIAN/control").write_text(
            "Package: nvidia-l4t-jetson-multimedia-api\n" +
            f"Version: {version}\nArchitecture: {architecture}\n" +
            "Maintainer: Fixture <fixture@example.invalid>\nDescription: fixture\n")
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(package),
                        str(self.mmapi)], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)

    def public_archive(self, *, missing=None, duplicate=None, symlink=None):
        with tarfile.open(self.public, "w:bz2") as archive:
            for name, data in self.subarchives.items():
                if name == missing:
                    continue
                member = tarfile.TarInfo("Linux_for_Tegra/source/" + name)
                member.size = len(data)
                if name == symlink:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/etc/shadow"
                    member.size = 0
                    archive.addfile(member)
                else:
                    archive.addfile(member, io.BytesIO(data))
                    if name == duplicate:
                        archive.addfile(member, io.BytesIO(data))

    def update_assets(self):
        for row in self.manifest["assets"]:
            if row["id"] in ("mmapi", "publicsources"):
                path = self.mmapi if row["id"] == "mmapi" else self.public
                row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest["gst_archives"] = {
            name: hashlib.sha256(data).hexdigest()
            for name, data in self.subarchives.items()}
        (self.sources / "runtime-assets.json").write_text(json.dumps(self.manifest))

    def test_input_provenance_is_read_only_and_contains_pinned_sources(self):
        before = snapshot(self.root)
        result = MODULE.input_provenance(self.config)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(set(result["source_assets"]), {"mmapi", "publicsources"})
        self.assertEqual(result["plugins"], list(MODULE.PLUGINS))
        self.assertEqual(set(result["source_archives"]), set(MODULE.ARCHIVES))
        self.assertIn("usr/bin/make", result["builder_tools"])

    def test_changed_current_patch_changes_provenance(self):
        before = MODULE.input_provenance(self.config)
        patch = self.bundle / "patches/gst/nvvidconv-caps.patch"
        patch.write_text(patch.read_text() + "\n")
        provision = self.support.load_module(self.sources / "provision-runtime.py", "gst_test_provision")
        provision.write_manifest(self.bundle)
        after = MODULE.input_provenance(self.config)
        self.assertNotEqual(before["runtime"], after["runtime"])

    def test_corrupted_mmapi_asset_is_rejected(self):
        self.mmapi.write_bytes(b"not the pinned source")
        with self.assertRaisesRegex(ValueError, "checksum"):
            MODULE.input_provenance(self.config)

    def test_corrupted_public_source_is_rejected(self):
        self.public.write_bytes(b"not the pinned source")
        with self.assertRaisesRegex(ValueError, "checksum"):
            MODULE.input_provenance(self.config)

    def test_wrong_mmapi_architecture_is_rejected_even_with_matching_hash(self):
        self.source_package(architecture="amd64")
        self.update_assets()
        with self.assertRaisesRegex(ValueError, "metadata"):
            MODULE.input_provenance(self.config)

    def test_wrong_mmapi_version_is_rejected_even_with_matching_hash(self):
        self.source_package(version="39.1-test")
        self.update_assets()
        with self.assertRaisesRegex(ValueError, "metadata"):
            MODULE.input_provenance(self.config)

    def test_duplicate_manifest_assets_are_rejected(self):
        self.manifest["assets"].append(next(
            row for row in self.manifest["assets"] if row["id"] == "mmapi"))
        self.update_assets()
        with self.assertRaisesRegex(ValueError, "Duplicate/missing"):
            MODULE.input_provenance(self.config)

    def test_incomplete_archive_checksum_inventory_is_rejected(self):
        self.update_assets()
        manifest = json.loads((self.sources / "runtime-assets.json").read_text())
        del manifest["gst_archives"][MODULE.ARCHIVES[0]]
        (self.sources / "runtime-assets.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "complete pinned"):
            MODULE.input_provenance(self.config)

    def test_assets_inside_source_builder_are_rejected(self):
        inside = self.builder / "source.deb"
        shutil.copyfile(self.mmapi, inside)
        config = dict(self.config, assets=dict(mmapi=inside, publicsources=self.public))
        with self.assertRaisesRegex(ValueError, "outside the read-only"):
            MODULE.input_provenance(config)

    def test_stage_archives_checks_every_nested_hash(self):
        checksums = {name: hashlib.sha256(data).hexdigest()
                     for name, data in self.subarchives.items()}
        target = self.root / "new-sources"
        MODULE.stage_archives(self.public, target, checksums, self.support)
        self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()},
                         self.subarchives)

    def test_stage_archives_rejects_missing_duplicate_and_symlink_members(self):
        checksums = {name: hashlib.sha256(data).hexdigest()
                     for name, data in self.subarchives.items()}
        for change in ("missing", "duplicate", "symlink"):
            with self.subTest(change=change):
                self.public_archive(**{change: MODULE.ARCHIVES[0]})
                target = self.root / ("rejected-" + change)
                with self.assertRaises(ValueError):
                    MODULE.stage_archives(self.public, target, checksums, self.support)

    def test_stage_archives_rejects_corrupt_nested_bytes(self):
        checksums = {name: "0" * 64 for name in MODULE.ARCHIVES}
        with self.assertRaisesRegex(ValueError, "checksum"):
            MODULE.stage_archives(self.public, self.root / "rejected", checksums,
                                  self.support)

    def fake_plugins(self, clone, *, missing=None, extra=None, machine=183):
        target = clone / "work/gst/plugins"
        target.mkdir(parents=True)
        for name in MODULE.PLUGINS:
            if name != missing:
                (target / name).write_bytes(elf(machine))
        if extra:
            (target / extra).write_bytes(elf())
        agreement = clone / "work/runtime/files/Tegra_Software_License_Agreement-Tegra-Linux.txt"
        agreement.parent.mkdir(parents=True, exist_ok=True)
        agreement.write_text("Fixture license notice\n")
        notice = clone / "work/gst/source/gst-v4l2/COPYING"
        notice.parent.mkdir(parents=True)
        notice.write_text("Fixture upstream license notice\n")

    def test_collected_payload_has_three_plugins_mode_0644_and_own_licenses(self):
        clone = self.root / "fake-clone"
        self.fake_plugins(clone)
        output = self.root / "payload"
        hashes = MODULE.collect_payload(clone, output, self.support)
        self.assertEqual(len(hashes), 5)
        for name in MODULE.PLUGINS:
            path = output / "usr/lib/aarch64-linux-gnu/gstreamer-1.0" / name
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(hashes[path.relative_to(output).as_posix()],
                             hashlib.sha256(path.read_bytes()).hexdigest())

    def test_payload_rejects_missing_extra_or_foreign_elf(self):
        changes = (dict(missing=MODULE.PLUGINS[0]), dict(extra="unknown.so"),
                   dict(machine=62))
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                clone = self.root / ("bad-clone-" + str(index))
                self.fake_plugins(clone, **change)
                with self.assertRaises(ValueError):
                    MODULE.collect_payload(clone, self.root / ("bad-output-" + str(index)),
                                           self.support)

    def test_payload_rejects_symlinked_plugin(self):
        clone = self.root / "bad-link-clone"
        self.fake_plugins(clone)
        path = clone / "work/gst/plugins" / MODULE.PLUGINS[0]
        original = clone / "original.so"
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaisesRegex(ValueError, "regular"):
            MODULE.collect_payload(clone, self.root / "bad-output", self.support)

    def simulated_build(self, *, loader_failure=False, binfmt=True):
        before = snapshot(self.builder)
        commands = []
        active = []
        provision = self.support.load_module(self.sources / "provision-runtime.py", "gst_simulated_provision")
        write_manifest = provision.write_manifest
        clone = self.run_dir / "builder"

        @contextmanager
        def target_context(root):
            self.assertEqual(root, clone)
            active.append(True)
            try:
                yield
            finally:
                active.pop()

        @contextmanager
        def lock(*arguments, **options):
            yield

        def prepare(assets, root, bundle, support, log):
            source = root / "work/mmapi-package/usr/src/jetson_multimedia_api"
            source.mkdir(parents=True)
            return source

        def chroot(root, command, log=None):
            self.assertTrue(active)
            commands.append(command)
            if command[:3] == ["bash", "/work/runtime/gst-port.sh", "build"]:
                self.fake_plugins(root)
                return "native plugins built"
            self.assertEqual(command[0], "env")
            return "libfixture.so => not found" if loader_failure else "all libraries resolved"

        fake = SimpleNamespace(persistent_binfmt=lambda path: binfmt,
                               target_context=target_context, chroot=chroot,
                               write_manifest=write_manifest)
        with mock.patch.object(MODULE, "support_module", return_value=self.support), \
                mock.patch.object(self.support, "load_module", return_value=fake), \
                mock.patch.object(self.support, "mounts_below", return_value=[]), \
                mock.patch.object(self.support, "lock_file", side_effect=lock), \
                mock.patch.object(MODULE, "prepare_mmapi", side_effect=prepare):
            try:
                result = MODULE.build_payload(self.config, self.run_dir)
            finally:
                self.assertEqual(snapshot(self.builder), before)
                self.assertFalse(active)
        return result, commands

    def test_full_payload_build_uses_only_gst_and_loader_commands_in_clone(self):
        (payload, metadata), commands = self.simulated_build()
        self.assertEqual(payload, self.run_dir / "payload")
        self.assertEqual(metadata["plugin_count"], 3)
        self.assertFalse(metadata["apt_invoked"])
        self.assertFalse(metadata["sdk_manager_invoked"])
        self.assertFalse(metadata["hardware_validated"])
        self.assertEqual(len(commands), 4)
        self.assertIn("/work/runtime/gst-port.sh", commands[0])
        self.assertNotIn("/work/runtime/runtime-port.sh", commands[0])
        for command in commands[1:]:
            self.assertIn("ldd", command)

    def test_loader_failure_rejects_payload_and_exits_private_context(self):
        with self.assertRaisesRegex(ValueError, "Unresolved native"):
            self.simulated_build(loader_failure=True)
        self.assertFalse((self.run_dir / "payload").exists())

    def test_missing_binfmt_fails_before_cloning(self):
        with mock.patch.object(MODULE.os, "uname", return_value=SimpleNamespace(machine="x86_64")), \
                self.assertRaisesRegex(ValueError, "binfmt"):
            self.simulated_build(binfmt=False)
        self.assertFalse((self.run_dir / "builder").exists())

    def test_private_run_must_not_overlap_sources_or_seed(self):
        for path in (self.builder, self.bundle, self.sources):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "overlap"):
                MODULE.build_payload(self.config, path)


if __name__ == "__main__":
    unittest.main()

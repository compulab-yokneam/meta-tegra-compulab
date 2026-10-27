#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline Argus component package tests; never enter a target chroot."""
import copy
from contextlib import contextmanager, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock


DIRECTORY = Path(__file__).resolve().parents[1]
FILES = DIRECTORY / "files"
SDK_FILES = DIRECTORY.parent / "edge-ai-sdk-manager/files"
HELPER = FILES / "build-argus-deb.py"
RECIPE = DIRECTORY / "edge-ai-argus-deb_39.2.1.bb"
SPEC = importlib.util.spec_from_file_location("standalone_argus_under_test", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def elf(architecture=183):
    """Non-executable fixture header; no ARM64 instructions are run."""
    return (b"\x7fELF\x02\x01\x01" + b"\0" * 9 +
            struct.pack("<HHIQQQIHHHHHH", 2, architecture, 1, 0, 0, 0,
                        0, 64, 0, 0, 0, 0, 0))


def tree_snapshot(root):
    result = {}
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[key] = ("symlink", str(path.readlink()))
        elif path.is_file():
            result[key] = ("file", path.read_bytes(), path.stat().st_mode)
        else:
            result[key] = ("directory", path.stat().st_mode)
    return result


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required")
class ArgusDebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="argus-deb-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.builder = self.root / "builder"
        self.work = self.root / "private-work"
        self.output = self.root / "published"
        self.sources = self.root / "sources"
        self.bundle = self.root / "runtime"
        self.builder.mkdir()
        self.sources.mkdir()
        shutil.copytree(SDK_FILES / "runtime", self.bundle)
        shutil.copyfile(SDK_FILES / "runtime-assets.json",
                        self.sources / "runtime-assets.json")
        for name in ("deb_packages.py", "rootfs_package_inventory.py"):
            shutil.copyfile(SDK_FILES / "sdk-source/compulab/tools" / name,
                            self.sources / name)
        shutil.copyfile(SDK_FILES / "provision-runtime.py",
                        self.sources / "provision-runtime.py")
        shutil.copyfile(HELPER, self.sources / "build-argus-deb.py")
        self.source_deb = self.root / (
            "nvidia-l4t-jetson-multimedia-api_39.2.1-20260806224157_arm64.deb")
        self.build_source_deb()
        manifest = json.loads((self.sources / "runtime-assets.json").read_text())
        self.mmapi = next(asset for asset in manifest["assets"]
                          if asset["id"] == "mmapi")
        self.mmapi["sha256"] = hashlib.sha256(self.source_deb.read_bytes()).hexdigest()
        self.manifest = manifest
        self.write_manifest()
        self.put("etc/os-release", b'ID=ubuntu\nVERSION_ID="24.04"\n')
        self.packages = {
            "nvidia-l4t-camera": "39.2.1-20260806224157",
            "nvidia-l4t-multimedia": "39.2.1-20260806224157",
            "nvidia-l4t-gstreamer": "39.2.1-20260806224157",
            "cuda-nvcc-13-2": "13.2.86-1",
            "cuda-cudart-13-2": "13.2.86-1",
        }
        self.write_status()
        for name in ("dpkg", "cmake", "g++", "pkg-config", "patch", "xxd", "readelf"):
            self.put("usr/bin/" + name, elf(), mode=0o755)
        self.put("usr/local/cuda-13.2/bin/nvcc", elf(), mode=0o755)
        self.put("opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1", elf())
        self.config = dict(
            uid=os.getuid(), gid=os.getgid(), builder=str(self.builder),
            work=str(self.work), output=str(self.output), sources=str(self.sources),
            bundle=str(self.bundle), source_deb=str(self.source_deb),
            version="39.2.1+compulab2", jobs=2)

    def build_source_deb(self, version="39.2.1-20260806224157", architecture="arm64"):
        package = self.root / "source-package"
        (package / "DEBIAN").mkdir(parents=True, exist_ok=True)
        (package / "DEBIAN/control").write_text(
            "Package: nvidia-l4t-jetson-multimedia-api\n" +
            f"Version: {version}\nArchitecture: {architecture}\n" +
            "Maintainer: Offline fixture <fixture@example.invalid>\n" +
            "Description: Non-executable source fixture\n")
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(package),
                        str(self.source_deb)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def put(self, relative, data, mode=0o644):
        path = self.builder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def write_manifest(self):
        (self.sources / "runtime-assets.json").write_text(json.dumps(self.manifest))

    def write_status(self, status="install ok installed", architecture="arm64"):
        contents = "\n\n".join(
            f"Package: {name}\nStatus: {status}\nArchitecture: {architecture}\n"
            f"Version: {version}\n" for name, version in self.packages.items())
        self.put("var/lib/dpkg/status", contents.encode())

    def checked(self, **changes):
        return MODULE.checked_configuration(dict(self.config, **changes))

    def rehash_bundle(self):
        contents = "".join(
            hashlib.sha256(path.read_bytes()).hexdigest() + "  ./" +
            path.relative_to(self.bundle).as_posix() + "\n"
            for path in sorted(self.bundle.rglob("*"))
            if path.is_file() and path.name != "SHA256SUMS" and
            not {"scratch", "__pycache__"}.intersection(path.relative_to(self.bundle).parts))
        (self.bundle / "SHA256SUMS").write_text(contents)

    def test_valid_configuration_and_fingerprint_are_read_only(self):
        before = tree_snapshot(self.root)
        checked = self.checked()
        first, inputs = MODULE.fingerprint(checked)
        second, _ = MODULE.fingerprint(checked)
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(first, second)
        self.assertTrue(inputs)
        self.assertEqual(tree_snapshot(self.root), before)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.work.exists())

    def test_unknown_missing_and_invalid_scalar_configuration_is_rejected(self):
        invalid = [dict(self.config, unknown="value")]
        missing = dict(self.config)
        del missing["builder"]
        invalid.append(missing)
        for field, values in (
                ("uid", (0, -1, True, "1000")),
                ("gid", (-1, True, "1000")),
                ("jobs", (0, -1, 65, True, "2")),
                ("format_version", (0, 2, True, "1")),
                ("version", ("", "1.0", "39.2.1 bad", "39.2.1\nInjected: yes"))):
            invalid.extend(dict(self.config, **{field: value}) for value in values)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                MODULE.checked_configuration(candidate)

    def test_relative_root_and_noncanonical_paths_are_rejected(self):
        for field in ("builder", "work", "output", "sources", "bundle", "source_deb"):
            for value in ("relative/path", "/", str(self.root / "missing/../bad")):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.checked(**{field: value})

    def test_symlinked_paths_are_rejected(self):
        alias = self.root / "builder-alias"
        alias.symlink_to(self.builder, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.checked(builder=str(alias))

    def test_builder_work_and_output_cannot_overlap_in_either_direction(self):
        for changes in (
                dict(work=str(self.builder / "work")),
                dict(output=str(self.builder / "output")),
                dict(builder=str(self.root)),
                dict(output=str(self.work / "output")),
                dict(work=str(self.output / "work")),
                dict(work=str(self.output)),
                dict(output=str(self.builder))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.checked(**changes)

    def test_current_bundle_is_verified_and_tampering_is_rejected(self):
        records = MODULE.verify_bundle(self.bundle)
        self.assertTrue(records)
        patch = self.bundle / "patches/argus/0005-argus-preview-allow-depthless-egl-config.patch"
        patch.write_bytes(patch.read_bytes() + b"changed\n")
        with self.assertRaises(ValueError):
            MODULE.verify_bundle(self.bundle)

    def test_unlisted_bundle_input_is_rejected(self):
        (self.bundle / "unexpected-input").write_text("not checksummed\n")
        with self.assertRaises(ValueError):
            MODULE.verify_bundle(self.bundle)

    def test_symlinked_bundle_input_is_rejected(self):
        path = self.bundle / "README.txt"
        path.unlink()
        path.symlink_to(self.source_deb)
        with self.assertRaises(ValueError):
            MODULE.verify_bundle(self.bundle)

    def test_fingerprint_changes_when_current_camera_patch_changes(self):
        initial, _ = MODULE.fingerprint(self.checked())
        patch = self.bundle / "patches/argus/0006-argus-camera-clean-up-partial-capture-start.patch"
        patch.write_bytes(patch.read_bytes() + b"new validated patch revision\n")
        self.rehash_bundle()
        changed, _ = MODULE.fingerprint(self.checked())
        self.assertNotEqual(initial, changed)

    def test_fingerprint_changes_for_package_version(self):
        initial, _ = MODULE.fingerprint(self.checked())
        changed, _ = MODULE.fingerprint(self.checked(version="39.2.1+compulab3"))
        self.assertNotEqual(initial, changed)

    def test_installed_and_held_builder_packages_are_accepted(self):
        ordinary = MODULE.builder_status(self.builder)
        self.write_status(status="hold ok installed")
        held = MODULE.builder_status(self.builder)
        self.assertTrue(ordinary)
        self.assertTrue(held)

    def test_builder_rejects_wrong_ubuntu_release(self):
        self.put("etc/os-release", b'ID=ubuntu\nVERSION_ID="22.04"\n')
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_builder_rejects_foreign_package_architecture(self):
        self.write_status(architecture="amd64")
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_builder_rejects_unconfigured_required_packages(self):
        self.write_status(status="install ok unpacked")
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_builder_rejects_wrong_required_nvidia_version(self):
        self.packages["nvidia-l4t-camera"] = "39.1.0-old"
        self.write_status()
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_builder_rejects_wrong_required_cuda_version(self):
        self.packages["cuda-nvcc-13-2"] = "12.6.0-1"
        self.write_status()
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_builder_rejects_missing_native_build_tool(self):
        (self.builder / "usr/bin/cmake").unlink()
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_builder_rejects_non_arm64_dpkg(self):
        self.put("usr/bin/dpkg", elf(62), mode=0o755)
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_absolute_target_symlinks_resolve_inside_builder_not_host(self):
        target = self.put("usr/lib/fixture-cmake", elf())
        link = self.builder / "usr/bin/cmake"
        link.unlink()
        link.symlink_to("/usr/lib/fixture-cmake")
        self.assertEqual(MODULE.target_file(self.builder, "usr/bin/cmake"), target)
        self.assertTrue(MODULE.builder_status(self.builder))

    def test_target_relative_symlink_cannot_escape_builder(self):
        link = self.builder / "usr/bin/cmake"
        link.unlink()
        link.symlink_to("../../../../outside")
        with self.assertRaises(ValueError):
            MODULE.builder_status(self.builder)

    def test_mmapi_manifest_rejects_duplicate_source_identity(self):
        self.manifest["assets"].append(copy.deepcopy(self.mmapi))
        self.write_manifest()
        with self.assertRaises(ValueError):
            MODULE.mmapi_asset(self.sources)

    def test_minimal_or_duplicate_argus_suite_is_rejected(self):
        path = self.bundle / "files/argus-full-suite.txt"
        original = path.read_text()
        for contents in ("argus_camera\nargus_oneshot\n",
                         original.replace("argus_oneshot\n", "argus_camera\n")):
            path.write_text(contents)
            with self.assertRaises(ValueError):
                MODULE.argus_specification(self.sources, self.bundle)

    @unittest.skipUnless(shutil.which("rsync"), "rsync is required")
    def test_clone_has_no_source_hardlinks_and_excludes_ephemeral_old_builds(self):
        for name in ("dev", "proc", "sys", "run", "tmp", "work", "var/tmp"):
            self.put(name + "/stale", b"not a build input\n")
        source = self.put("usr/share/stable", b"original\n")
        before = tree_snapshot(self.builder)
        clone = self.root / "clone"
        MODULE.clone_builder(self.builder, clone)
        copied = clone / "usr/share/stable"
        self.assertEqual(copied.read_bytes(), b"original\n")
        self.assertNotEqual(copied.stat().st_ino, source.stat().st_ino)
        copied.write_bytes(b"changed clone\n")
        self.assertEqual(tree_snapshot(self.builder), before)
        for name in ("dev", "proc", "sys", "run", "tmp", "work", "var/tmp"):
            self.assertFalse((clone / name / "stale").exists())

    def test_source_checksum_tampering_is_rejected_before_build(self):
        self.source_deb.write_bytes(self.source_deb.read_bytes() + b"tampered")
        with self.assertRaises(ValueError), mock.patch.object(MODULE, "build_in_clone") as build:
            MODULE.fingerprint(self.checked())
        build.assert_not_called()

    def test_wrong_source_package_architecture_is_rejected_even_with_matching_hash(self):
        self.build_source_deb(architecture="amd64")
        self.mmapi["sha256"] = MODULE.digest(self.source_deb)
        self.write_manifest()
        with self.assertRaises(ValueError):
            MODULE.fingerprint(self.checked())

    def test_wrong_source_package_version_is_rejected_even_with_matching_hash(self):
        self.build_source_deb(version="39.1.0-old")
        self.mmapi["sha256"] = MODULE.digest(self.source_deb)
        self.write_manifest()
        with self.assertRaises(ValueError):
            MODULE.fingerprint(self.checked())

    def test_default_cli_action_is_read_only_plan(self):
        configuration = self.root / "configuration.json"
        configuration.write_text(json.dumps(self.config))
        before = tree_snapshot(self.root)
        output = io.StringIO()
        with mock.patch.object(MODULE, "execute", side_effect=AssertionError("must not execute")), \
                redirect_stdout(output):
            self.assertEqual(MODULE.main(["--config", str(configuration)]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["action"], "read-only plan")
        self.assertEqual(tree_snapshot(self.root), before)

    def test_clone_refuses_active_mounts(self):
        with mock.patch.object(MODULE, "mounts_below", return_value=[str(self.builder / "proc")]), \
                self.assertRaisesRegex(ValueError, "mount"):
            MODULE.clone_builder(self.builder, self.root / "clone")
        self.assertFalse((self.root / "clone").exists())

    def test_clone_rejects_special_files_before_copying(self):
        os.mkfifo(self.builder / "unsupported-fifo")
        with self.assertRaises(ValueError):
            MODULE.clone_builder(self.builder, self.root / "clone")
        self.assertFalse((self.root / "clone").exists())

    def prepare_execution(self):
        self.work.mkdir(mode=0o700)
        marker = self.work / MODULE.WORK_MARKER
        marker.write_text(MODULE.WORK_ID)
        marker.chmod(0o600)
        self.sdk_lock = self.root / "sdk-coordination.lock"
        self.sdk_lock.write_text("")
        self.sdk_lock.chmod(0o600)

    def fake_native_build(self, config, clone, run_dir):
        self.assertNotEqual(clone, self.builder)
        self.assertTrue(clone.is_relative_to(self.work))
        pkgroot = clone / "work/argus/pkgroot"
        license_source = clone / "work/argus/source/argus/LICENSE.TXT"
        license_source.parent.mkdir(parents=True)
        license_source.write_text("Offline source-license fixture, no vendor binaries\n")
        names, _ = MODULE.argus_specification(config["sources"], config["bundle"])
        for name in names:
            path = pkgroot / "usr/bin" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(elf() + name.encode())
            path.chmod(0o755)
        return pkgroot

    @contextmanager
    def execution_boundary(self, side_effect=None):
        # Only privilege and native ARM64 execution are mocked. Validation,
        # locks, clone, architecture checks, real .deb assembly and publication
        # all execute normally, as the unprivileged test user.
        with mock.patch.object(MODULE.os, "geteuid", return_value=0), \
                mock.patch.object(MODULE, "GLOBAL_SDK_LOCK", self.sdk_lock), \
                mock.patch.object(MODULE, "build_in_clone", side_effect=
                                  side_effect or self.fake_native_build) as build, \
                mock.patch.object(MODULE, "verify_native_payload") as native, \
                mock.patch.object(MODULE, "run", wraps=MODULE.run) as commands:
            yield build, native, commands

    def test_execute_publishes_real_arm64_deb_with_full_inventory_dependencies_and_md5(self):
        self.prepare_execution()
        before = tree_snapshot(self.builder)
        with self.execution_boundary() as (build, native, commands):
            manifest = MODULE.execute(self.config)
        build.assert_called_once()
        native.assert_called_once()
        self.assertEqual(tree_snapshot(self.builder), before)
        package = manifest["package"]
        archive = self.output / manifest["fingerprint"] / package["filename"]
        metadata = subprocess.check_output(
            ["dpkg-deb", "-f", str(archive), "Package", "Version", "Architecture", "Depends"],
            text=True)
        self.assertIn("Package: compulab-edge-ai-argus\n", metadata)
        self.assertIn("Architecture: arm64\n", metadata)
        self.assertIn("Version: 39.2.1+compulab2\n", metadata)
        self.assertIn("nvidia-l4t-camera (= 39.2.1-20260806224157)", metadata)
        self.assertIn("nvidia-l4t-multimedia (= 39.2.1-20260806224157)", metadata)
        self.assertIn("cuda-cudart-13-2 (= 13.2.86-1)", metadata)
        self.assertNotIn("compulab-edge-ai-kernel", metadata)
        extracted, control = self.root / "extracted", self.root / "control"
        subprocess.run(["dpkg-deb", "-x", str(archive), str(extracted)], check=True)
        subprocess.run(["dpkg-deb", "-e", str(archive), str(control)], check=True)
        names, _ = MODULE.argus_specification(self.sources, self.bundle)
        self.assertEqual({path.name for path in (extracted / "usr/bin").iterdir()}, set(names))
        checksums = (control / "md5sums").read_text().splitlines()
        self.assertEqual(len(checksums), 25)
        self.assertTrue((extracted / "usr/share/doc/compulab-edge-ai-argus/copyright").is_file())
        self.assertTrue((extracted / "usr/share/doc/compulab-edge-ai-argus/NVIDIA-LICENSE").is_file())
        for line in checksums:
            checksum, name = line.split("  ", 1)
            self.assertEqual(hashlib.md5((extracted / name).read_bytes(),
                                        usedforsecurity=False).hexdigest(), checksum)
        self.assertEqual(manifest["inputs"]["bundle"], MODULE.verify_bundle(self.bundle))
        self.assertEqual(manifest["inputs"]["source_deb"], MODULE.digest(self.source_deb))
        self.assertEqual(MODULE.verify_publication(archive.parent,
                         manifest["fingerprint"], os.getuid()), manifest)
        for call in commands.call_args_list:
            self.assertIn(str(call.args[0][0]), ("dpkg-deb", "findmnt"))

    def test_unchanged_inputs_reuse_only_verified_publication_without_rebuild(self):
        self.prepare_execution()
        with self.execution_boundary():
            first = MODULE.execute(self.config)
        with self.execution_boundary(side_effect=AssertionError("unexpected rebuild")) as (build, native, _):
            second = MODULE.execute(self.config)
        self.assertEqual(first, second)
        build.assert_not_called()
        native.assert_not_called()

    def test_changed_camera_patch_builds_new_publication_without_overwriting_old(self):
        self.prepare_execution()
        with self.execution_boundary():
            first = MODULE.execute(self.config)
        old = self.output / first["fingerprint"]
        before = tree_snapshot(old)
        patch = self.bundle / "patches/argus/0006-argus-camera-clean-up-partial-capture-start.patch"
        patch.write_bytes(patch.read_bytes() + b"fresh source revision\n")
        self.rehash_bundle()
        with self.execution_boundary() as (build, _, _):
            second = MODULE.execute(self.config)
        build.assert_called_once()
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(tree_snapshot(old), before)

    def test_modified_cached_archive_is_rejected_without_rebuild_or_overwrite(self):
        self.prepare_execution()
        with self.execution_boundary():
            manifest = MODULE.execute(self.config)
        archive = self.output / manifest["fingerprint"] / manifest["package"]["filename"]
        archive.write_bytes(archive.read_bytes() + b"tampered")
        before = archive.read_bytes()
        with self.execution_boundary(side_effect=AssertionError("unexpected rebuild")) as (build, _, _), \
                self.assertRaisesRegex(ValueError, "checksum"):
            MODULE.execute(self.config)
        build.assert_not_called()
        self.assertEqual(archive.read_bytes(), before)

    def rewrite_publication(self, manifest):
        destination = self.output / manifest["fingerprint"]
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        (destination / "SHA256SUMS").write_text(
            manifest["package"]["sha256"] + "  " + manifest["package"]["filename"] + "\n" +
            MODULE.digest(manifest_path) + "  manifest.json\n")

    def test_cached_input_receipt_must_match_fingerprint_even_with_recomputed_checksums(self):
        self.prepare_execution()
        with self.execution_boundary():
            manifest = MODULE.execute(self.config)
        manifest["inputs"]["version"] = "39.2.1+compulab999"
        self.rewrite_publication(manifest)
        with self.execution_boundary() as (build, _, _), self.assertRaises(ValueError):
            MODULE.execute(self.config)
        build.assert_not_called()

    def test_cached_archive_metadata_is_verified_even_with_recomputed_checksums(self):
        self.prepare_execution()
        with self.execution_boundary():
            manifest = MODULE.execute(self.config)
        archive = self.output / manifest["fingerprint"] / manifest["package"]["filename"]
        self.build_source_deb(architecture="amd64")
        shutil.copyfile(self.source_deb, archive)
        manifest["package"]["sha256"] = MODULE.digest(archive)
        self.rewrite_publication(manifest)
        with self.assertRaises(ValueError):
            MODULE.verify_publication(archive.parent, manifest["fingerprint"], os.getuid())

    def test_execute_requires_explicit_root_before_any_output_mutation(self):
        before = tree_snapshot(self.root)
        with mock.patch.object(MODULE.os, "geteuid", return_value=os.getuid()), \
                self.assertRaisesRegex(ValueError, "root"):
            MODULE.execute(self.config)
        self.assertEqual(tree_snapshot(self.root), before)

    def test_execute_rejects_unmarked_nonempty_output(self):
        self.prepare_execution()
        self.output.mkdir()
        (self.output / "unrelated").write_text("preserve me\n")
        with self.execution_boundary() as (build, _, _), self.assertRaises(ValueError):
            MODULE.execute(self.config)
        build.assert_not_called()
        self.assertEqual((self.output / "unrelated").read_text(), "preserve me\n")

    def test_execute_rejects_active_builder_mounts_before_clone(self):
        self.prepare_execution()
        with self.execution_boundary() as (build, _, _), \
                mock.patch.object(MODULE, "mounts_below", return_value=[str(self.builder / "proc")]), \
                mock.patch.object(MODULE, "clone_builder") as clone, \
                self.assertRaisesRegex(ValueError, "mount"):
            MODULE.execute(self.config)
        clone.assert_not_called()
        build.assert_not_called()

    def bad_payload_build(self, mutation):
        def build(config, clone, run_dir):
            pkgroot = self.fake_native_build(config, clone, run_dir)
            mutation(pkgroot)
            return pkgroot
        return build

    def assert_payload_rejected(self, mutation):
        self.prepare_execution()
        before = tree_snapshot(self.builder)
        with self.execution_boundary(self.bad_payload_build(mutation)), \
                self.assertRaises(ValueError):
            MODULE.execute(self.config)
        self.assertEqual(tree_snapshot(self.builder), before)
        self.assertFalse(any(path.is_dir() for path in self.output.iterdir()))

    def test_fresh_payload_cannot_contain_old_unexpected_application(self):
        self.assert_payload_rejected(lambda root:
            (root / "usr/bin/argus_stale").write_bytes(elf()))

    def test_fresh_payload_requires_all_23_applications(self):
        self.assert_payload_rejected(lambda root: (root / "usr/bin/argus_camera").unlink())

    def test_fresh_payload_rejects_foreign_architecture(self):
        self.assert_payload_rejected(lambda root:
            (root / "usr/bin/argus_camera").write_bytes(elf(62)))

    def test_fresh_payload_rejects_nonexecutable_application_mode(self):
        self.assert_payload_rejected(lambda root:
            (root / "usr/bin/argus_camera").chmod(0o644))

    def test_fresh_payload_rejects_symlinked_application(self):
        def symlink(root):
            path = root / "usr/bin/argus_camera"
            path.unlink()
            path.symlink_to("argus_oneshot")
        self.assert_payload_rejected(symlink)

    def test_execute_rejects_missing_ownership_marker(self):
        self.prepare_execution()
        (self.work / MODULE.WORK_MARKER).unlink()
        with self.execution_boundary() as (build, _, _), self.assertRaises(ValueError):
            MODULE.execute(self.config)
        build.assert_not_called()

    def test_execute_rejects_insecure_work_directory_mode(self):
        self.prepare_execution()
        self.work.chmod(0o755)
        with self.execution_boundary() as (build, _, _), self.assertRaises(ValueError):
            MODULE.execute(self.config)
        build.assert_not_called()


class ArgusDebRecipeTests(unittest.TestCase):
    def test_recipe_is_an_independent_host_action_without_sdk_or_kernel_tasks(self):
        recipe = RECIPE.read_text()
        self.assertIn('INHIBIT_DEFAULT_DEPS = "1"', recipe)
        self.assertRegex(recipe, r"(?m)^inherit\s+.*\bnopackages\b")
        self.assertRegex(recipe, r'do_create_argus_deb\[nostamp\]\s*=\s*"1"')
        # This task needs host sudo outside BitBake's network-disable user
        # namespace. The helper itself has no download/provisioning workflow.
        self.assertRegex(recipe, r'do_create_argus_deb\[network\]\s*=\s*"1"')
        self.assertIn("network-disable user namespace", recipe)
        for line in recipe.splitlines():
            if "[depends]" in line or line.startswith("DEPENDS"):
                self.assertNotIn("edge-ai-sdk-manager:", line)
                self.assertNotIn("virtual/kernel", line)
                self.assertNotIn("tos-optee", line)
                self.assertNotIn("edk2-nvidia", line)

    def test_recipe_fetches_only_mmapi_source_not_runtime_or_cuda_archives(self):
        recipe = RECIPE.read_text()
        self.assertRegex(recipe, r"['\"]mmapi['\"]")
        self.assertNotIn('edge_ai_sdk_runtime_prepare_assets(', recipe)
        self.assertNotRegex(recipe, r"require\s+.*edge-ai-sdk-manager-runtime")
        self.assertIn("--execute", recipe)
        self.assertNotIn("sdkmanager --", recipe)
        self.assertNotIn("apt-get", recipe)

    def test_recipe_fetch_selection_executes_with_exactly_one_pinned_source(self):
        recipe = RECIPE.read_text()
        body = re.search(r"(?ms)^python __anonymous\(\) \{\n(.*?)^\}", recipe)[1]

        class Data:
            def __init__(self):
                self.values = {"THISDIR": str(DIRECTORY), "SRC_URI": ""}
                self.flags = {}

            def getVar(self, name):
                return self.values.get(name)

            def setVar(self, name, value):
                self.values[name] = value

            def appendVar(self, name, value):
                self.values[name] += value

            def setVarFlag(self, name, flag, value):
                self.flags[name, flag] = value

        namespace = {}
        exec("def configure(d):\n" + body, namespace)
        data = Data()
        namespace["configure"](data)
        uris = data.values["SRC_URI"].split()
        self.assertEqual(len(uris), 1)
        self.assertIn("nvidia-l4t-jetson-multimedia-api_39.2.1", uris[0])
        self.assertIn(";unpack=0", uris[0])
        self.assertEqual(len(data.flags), 1)
        self.assertRegex(next(iter(data.flags.values())), r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

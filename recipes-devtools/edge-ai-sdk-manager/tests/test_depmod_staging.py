#!/usr/bin/env python3
"""Temp-only module-index tests: no SDK, rootfs or host module-tree writes."""
# SPDX-License-Identifier: MIT

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


FILES = Path(__file__).resolve().parents[1] / "files"
SPECIFICATION = importlib.util.spec_from_file_location(
    "depmod_assemble", FILES / "assemble-sdk.py")
ASSEMBLE = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(ASSEMBLE)


class ModuleIndexes(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def staging(self, name="artifacts"):
        artifacts = self.root / name
        modules = artifacts / "usr/lib/modules" / ASSEMBLE.RELEASE
        modules.mkdir(parents=True)
        for filename in ("modules.order", "modules.builtin",
                         "modules.builtin.modinfo"):
            (modules / filename).write_bytes(b"")
        return artifacts, modules

    def snapshot(self, root):
        result = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[relative] = ("symlink", str(path.readlink()))
            elif path.is_file():
                result[relative] = ("file", path.read_bytes())
            else:
                result[relative] = ("directory", None)
        return result

    def rejected_without_changes(self, artifacts):
        before = self.snapshot(self.root)
        with mock.patch.object(ASSEMBLE, "run") as run:
            with self.assertRaises(RuntimeError):
                ASSEMBLE.prepare_module_indexes(artifacts)
        run.assert_not_called()
        self.assertEqual(self.snapshot(self.root), before)

    def test_creates_relative_alias_before_depmod_without_changing_inputs(self):
        artifacts, modules = self.staging()
        (modules / "kernel").mkdir()
        (modules / "kernel/input.ko").write_bytes(b"preserve module input")
        before = self.snapshot(artifacts)

        def depmod(*command):
            self.assertEqual(command,
                             ("depmod", "-b", artifacts, ASSEMBLE.RELEASE))
            self.assertTrue((artifacts / "lib").is_symlink())
            self.assertEqual((artifacts / "lib").readlink(), Path("usr/lib"))
            self.assertEqual((artifacts / "lib/modules" / ASSEMBLE.RELEASE)
                             .resolve(), modules)

        with mock.patch.object(ASSEMBLE, "run", side_effect=depmod) as run:
            ASSEMBLE.prepare_module_indexes(artifacts)
        run.assert_called_once()
        after = self.snapshot(artifacts)
        self.assertEqual(after.pop("lib"), ("symlink", "usr/lib"))
        self.assertEqual(after, before)

    def test_existing_exact_alias_is_reused_without_replacement(self):
        artifacts, _ = self.staging()
        alias = artifacts / "lib"
        alias.symlink_to("usr/lib")
        inode = alias.lstat().st_ino
        before = self.snapshot(artifacts)
        with mock.patch.object(ASSEMBLE, "run") as run:
            ASSEMBLE.prepare_module_indexes(artifacts)
            ASSEMBLE.prepare_module_indexes(artifacts)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(alias.lstat().st_ino, inode)
        self.assertEqual(self.snapshot(artifacts), before)

    def test_rejects_noncanonical_staging_roots(self):
        artifacts, _ = self.staging()
        alias = self.root / "alias"
        alias.symlink_to(artifacts, target_is_directory=True)
        (self.root / "directory").mkdir()
        regular_file = self.root / "file"
        regular_file.write_bytes(b"not a staging directory")
        for path in (Path("relative-artifacts"), alias,
                     self.root / "directory/../artifacts",
                     self.root / "missing", regular_file):
            with self.subTest(path=str(path)):
                self.rejected_without_changes(path)

    def test_rejects_existing_lib_files_and_directories(self):
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                artifacts, _ = self.staging(kind)
                alias = artifacts / "lib"
                if kind == "file":
                    alias.write_bytes(b"do not overwrite")
                else:
                    alias.mkdir()
                    (alias / "keep").write_bytes(b"do not remove")
                self.rejected_without_changes(artifacts)

    def test_rejects_wrong_dangling_absolute_and_escaping_lib_symlinks(self):
        external = self.root / "external"
        external.mkdir()
        (external / "keep").write_bytes(b"do not touch")
        targets = ("usr/missing", "usr/lib/..", "../external",
                   str(external), "absolute-correct")
        for index, target in enumerate(targets):
            with self.subTest(target=target):
                artifacts, _ = self.staging("symlink-%d" % index)
                if target == "absolute-correct":
                    target = str(artifacts / "usr/lib")
                (artifacts / "lib").symlink_to(target)
                self.rejected_without_changes(artifacts)

    def test_rejects_missing_module_tree_before_creating_alias(self):
        artifacts = self.root / "artifacts"
        (artifacts / "usr/lib/modules").mkdir(parents=True)
        self.rejected_without_changes(artifacts)
        self.assertFalse((artifacts / "lib").is_symlink())

    def test_rejects_symlinked_components_of_usr_module_path(self):
        components = ("usr", "usr/lib", "usr/lib/modules",
                      "usr/lib/modules/" + ASSEMBLE.RELEASE)
        for index, component in enumerate(components):
            for escape in (False, True):
                with self.subTest(component=component, escape=escape):
                    name = "component-%d-%s" % (index, escape)
                    artifacts, _ = self.staging(name)
                    original = artifacts / component
                    destination = ((self.root if escape else artifacts) /
                                   ("saved-%d-%s" % (index, escape)))
                    original.rename(destination)
                    original.symlink_to(destination, target_is_directory=True)
                    self.rejected_without_changes(artifacts)

    def test_depmod_failure_propagates_and_preserves_module_inputs(self):
        artifacts, _ = self.staging()
        before = self.snapshot(artifacts)
        failure = subprocess.CalledProcessError(2, ["depmod"])
        with mock.patch.object(ASSEMBLE, "run", side_effect=failure) as run:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                ASSEMBLE.prepare_module_indexes(artifacts)
        self.assertIs(caught.exception, failure)
        run.assert_called_once_with("depmod", "-b", artifacts,
                                    ASSEMBLE.RELEASE)
        after = self.snapshot(artifacts)
        self.assertEqual(after.pop("lib"), ("symlink", "usr/lib"))
        self.assertEqual(after, before)

    @unittest.skipUnless(shutil.which("depmod"), "host depmod is unavailable")
    def test_real_depmod_creates_indexes_in_usr_module_tree(self):
        artifacts, modules = self.staging()
        ASSEMBLE.prepare_module_indexes(artifacts)
        self.assertEqual((artifacts / "lib").readlink(), Path("usr/lib"))
        for filename in ("modules.dep", "modules.dep.bin", "modules.alias",
                         "modules.alias.bin", "modules.symbols",
                         "modules.symbols.bin"):
            with self.subTest(filename=filename):
                self.assertTrue((modules / filename).is_file())
                self.assertEqual((artifacts / "lib/modules" /
                                  ASSEMBLE.RELEASE / filename).resolve(),
                                 modules / filename)
        for filename in ("modules.order", "modules.builtin",
                         "modules.builtin.modinfo"):
            self.assertEqual((modules / filename).read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()

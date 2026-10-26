#!/usr/bin/env python3
"""Exercise the real deploy exporter without starting a BitBake server."""
# SPDX-License-Identifier: MIT

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import types
import unittest


LAYER = Path(__file__).resolve().parents[3]
CLASS = LAYER / "classes-recipe/edge-ai-sdk-export.bbclass"
SOURCE = CLASS.read_text().split("# Python helpers begin", 1)[1]
SOURCE = SOURCE.split("\n", 1)[1].split("# Python helpers end.", 1)[0]
GLOBALS = {"bb": types.SimpleNamespace(fatal=lambda message: fail(message))}


def fail(message):
    raise RuntimeError(message)


exec(compile(SOURCE, str(CLASS), "exec"), GLOBALS)


class Data(dict):
    def getVar(self, name):
        return self.get(name)


class SdkDeployExports(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.release = "6.8.12-clab-adi-v18"
        self.data = Data(
            EDGE_AI_SDK_EXPORTS="1", EDGE_AI_SDK_EXPORT_SUBDIR="edge-ai-sdk",
            DEPLOYDIR=str(self.root / "deploy"), SOURCE_DATE_EPOCH="1",
            PN="linux-noble-nvidia-tegra", PV="6.8.12", MACHINE="edge-ai-nx-16g",
            L4T_VERSION="39.2.1", KERNEL_VERSION=self.release,
            D=str(self.root / "image"), PKGD=str(self.root / "package"),
            B=str(self.root / "build"),
            UNPACKDIR=str(self.root / "sources"), KERNEL_IMAGEDEST="boot",
            nonarch_base_libdir="/usr/lib", includedir="/usr/include",
            LICENSE_DIRECTORY=str(self.root / "licenses"), SSTATE_PKGARCH="arch",
            LICENSE="GPL-2.0-only", OVERRIDES="edge-ai:adi-gmsl-v18")
        self.license()

    def put(self, relative, data=b"fixture"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    def license(self):
        self.put("licenses/arch/" + self.data["PN"] + "/COPYING", b"license")

    def manifest(self, component):
        return json.loads((self.root / "deploy/edge-ai-sdk" /
                           (component + ".json")).read_text())

    def kernel(self):
        self.put("build/include/config/kernel.release", self.release + "\n")
        self.put("build/Module.symvers", b"symbols")
        self.put("build/.config", "CONFIG_ONE=y\nCONFIG_TWO=m\n"
                 "# CONFIG_THREE is not set\nCONFIG_MODVERSIONS=y\n")
        self.put("image/boot/Image-" + self.release, b"kernel-image")
        modules = "package/usr/lib/modules/" + self.release
        self.put(modules + "/kernel/test.ko", b"\x7fELFmodule")
        self.put(modules + "/kernel/.debug/test.ko", b"\x7fELFdebug-only")
        (self.root / modules / "build").symlink_to("/outside/work")
        (self.root / modules / "source").symlink_to("/outside/source")
        self.put("sources/compulab.cfg", "CONFIG_ONE=y\n")
        self.put("sources/adi-gmsl-v18-noble/edge-ai-noble.cfg", "CONFIG_TWO=m\n")
        self.put("sources/adi-gmsl-v18-noble/edgedes-adi-v18.cfg",
                 "# CONFIG_THREE is not set\n")

    def test_all_entry_points_are_explicitly_opt_in(self):
        for function in ("edge_ai_sdk_export_kernel", "edge_ai_sdk_export_oot",
                         "edge_ai_sdk_export_devsrc"):
            GLOBALS[function](Data(EDGE_AI_SDK_EXPORTS="0"))
        self.assertFalse((self.root / "deploy").exists())

    def test_kernel_archive_contract_and_exact_config_validation(self):
        self.kernel()
        GLOBALS["edge_ai_sdk_export_kernel"](self.data)
        manifest = self.manifest("kernel")
        self.assertEqual(manifest["kernel_release"], self.release)
        self.assertEqual(len(manifest["metadata"]["config_requests"]), 3)
        self.assertIn("metadata/base-Module.symvers", manifest["files"])
        self.assertIn("metadata/kernel.config", manifest["files"])
        self.assertIn("boot/config-" + self.release, manifest["files"])
        self.assertIn("usr/lib/modules/" + self.release + "/kernel/test.ko",
                      manifest["files"])
        self.assertEqual(manifest["symlinks"], {})
        self.assertFalse(any("/.debug/" in name for name in manifest["files"]))
        archive = self.root / "deploy/edge-ai-sdk/kernel.tar.xz"
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         manifest["archive_sha256"])
        with tarfile.open(archive) as stream:
            self.assertEqual(stream.extractfile("boot/Image").read(), b"kernel-image")
            self.assertEqual(stream.extractfile("metadata/kernel.config").read(),
                             (self.root / "build/.config").read_bytes())
        self.put("build/.config", "CONFIG_ONE=n\n")
        with self.assertRaisesRegex(RuntimeError, "not honored"):
            GLOBALS["edge_ai_sdk_export_kernel"](self.data)

    def test_kernel_mismatched_release_fails_closed(self):
        self.kernel()
        self.data["KERNEL_VERSION"] = "other"
        with self.assertRaisesRegex(RuntimeError, "release differs"):
            GLOBALS["edge_ai_sdk_export_kernel"](self.data)

    def test_oot_exports_replacement_policy_headers_and_licenses(self):
        self.data.update(PN="nvidia-kernel-oot", BPN="nvidia-kernel-oot",
                         PV="39.2.1", TEGRA_OOT_REPLACEMENT_DRIVERS="host1x tegra-drm")
        self.license()
        self.put("image/usr/include/nvidia-kernel-oot/Module.symvers", b"oot-symbols")
        self.put("image/usr/include/nvidia-kernel-oot/media/camera.h", b"header")
        self.put("package/usr/lib/modules/" + self.release + "/updates/camera.ko")
        GLOBALS["edge_ai_sdk_export_oot"](self.data)
        manifest = self.manifest("nvidia-kernel-oot")
        self.assertEqual(manifest["metadata"]["replacement_drivers"],
                         ["host1x", "tegra-drm"])
        self.assertIn("metadata/oot-Module.symvers", manifest["files"])
        self.assertIn("usr/include/nvidia-kernel-oot/media/camera.h", manifest["files"])
        self.assertIn("metadata/licenses/nvidia-kernel-oot/COPYING", manifest["files"])

    def test_licenses_use_restored_sstate_output_not_work_input(self):
        path = GLOBALS["edge_ai_sdk_licenses"](self.data)
        self.assertEqual(path, self.root / "licenses/arch/linux-noble-nvidia-tegra")
        self.data["LICENSE_DIRECTORY"] = str(self.root / "missing")
        with self.assertRaisesRegex(RuntimeError, "staged recipe licenses"):
            GLOBALS["edge_ai_sdk_licenses"](self.data)

    def test_source_export_preserves_internal_links_and_rejects_elf(self):
        self.data.update(PN="kernel-devsrc", PV="1.0")
        self.license()
        base = "image/usr/lib/modules/" + self.release
        self.put(base + "/build/include/config/kernel.release", self.release + "\n")
        self.put(base + "/build/Makefile", b"# source")
        (self.root / base / "source").symlink_to("build")
        self.put("image/usr/src/placeholder", b"source")
        (self.root / "image/usr/src/kernel").symlink_to(
            "../lib/modules/" + self.release + "/source")
        GLOBALS["edge_ai_sdk_export_devsrc"](self.data)
        self.assertEqual(len(self.manifest("kernel-devsrc")["symlinks"]), 2)
        self.put(base + "/build/bad-host-tool", b"\x7fELFbad")
        with self.assertRaisesRegex(RuntimeError, "ELF file"):
            GLOBALS["edge_ai_sdk_export_devsrc"](self.data)

    def test_source_export_keeps_non_usrmerge_module_tree(self):
        self.data.update(PN="kernel-devsrc", PV="1.0", nonarch_base_libdir="/lib")
        self.license()
        base = "image/lib/modules/" + self.release
        self.put(base + "/build/include/config/kernel.release", self.release + "\n")
        (self.root / base / "source").symlink_to("build")
        self.put("image/usr/src/placeholder")
        (self.root / "image/usr/src/kernel").symlink_to(
            "../../lib/modules/" + self.release + "/source")
        GLOBALS["edge_ai_sdk_export_devsrc"](self.data)
        self.assertIn("lib/modules/" + self.release + "/build/include/config/kernel.release",
                      self.manifest("kernel-devsrc")["files"])

    def test_archives_are_reproducible_and_do_not_publish_to_global_deploy(self):
        entries = {"metadata/input": self.put("input")}
        GLOBALS["edge_ai_sdk_pack"](self.data, "fixture", entries,
                                    {"kernel_release": self.release})
        first = self.manifest("fixture")["archive_sha256"]
        GLOBALS["edge_ai_sdk_pack"](self.data, "fixture", entries,
                                    {"kernel_release": self.release})
        self.assertEqual(first, self.manifest("fixture")["archive_sha256"])
        self.assertNotIn("getVar(\"DEPLOY_DIR_IMAGE\")", CLASS.read_text())

    def test_unsafe_archive_paths_and_links_fail(self):
        source = self.put("payload")
        for relative in ("../outside", "/absolute"):
            with self.subTest(relative=relative), self.assertRaisesRegex(
                    RuntimeError, "Unsafe SDK archive"):
                GLOBALS["edge_ai_sdk_pack"](self.data, "fixture", {relative: source},
                                            {"kernel_release": self.release})
        link = self.root / "link"
        link.symlink_to("/outside/work")
        with self.assertRaisesRegex(RuntimeError, "symlink escapes"):
            GLOBALS["edge_ai_sdk_pack"](self.data, "fixture", {"link": link},
                                        {"kernel_release": self.release})
        self.data["EDGE_AI_SDK_EXPORT_SUBDIR"] = "../outside"
        with self.assertRaisesRegex(RuntimeError, "inside DEPLOYDIR"):
            GLOBALS["edge_ai_sdk_pack"](self.data, "fixture", {"data": source},
                                        {"kernel_release": self.release})

    def test_metadata_hooks_keep_deploy_after_install(self):
        for relative, ordering in (
                ("recipes-kernel/linux/kernel-devsrc.bbappend",
                 "addtask deploy after do_install before do_build"),
                ("recipes-kernel/nvidia-kernel-oot/nvidia-kernel-oot_%.bbappend",
                 "addtask deploy after do_install do_package before do_build")):
            text = (LAYER / relative).read_text()
            self.assertIn(ordering, text)
        text = (LAYER / "recipes-kernel/linux/linux.inc").read_text()
        self.assertIn('do_deploy[postfuncs] += "edge_ai_sdk_export_kernel_task"', text)

    def test_packaged_modules_have_a_restorable_recipe_owned_source(self):
        package = (LAYER.parents[1] /
                   "repos/openembedded-core/meta/classes-global/package.bbclass").read_text()
        self.assertIn('do_package[sstate-plaindirs] = "${PKGD}', package)
        self.assertIn('getVar("PKGD")', CLASS.read_text())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary fixture inventories; never install packages or access a device."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / \
    "tools/rootfs_package_inventory.py"
SPEC = importlib.util.spec_from_file_location(
    "rootfs_package_inventory", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RootfsPackageInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="rootfs-package-inventory-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.sdk = self.directory / "sdk"
        self.root = self.sdk / "rootfs"
        self.artifacts = self.directory / "artifacts"
        self.root.mkdir(parents=True)
        self.artifacts.mkdir()
        self.version = "39.2.1+clab.20261026-1"
        self.module = "usr/lib/modules/" + MODULE.RELEASE + "/kernel/test.ko"
        self.dropin = "etc/systemd/system/nvargus-daemon.service.d/" + \
                      "90-edgedes-framos-demo.conf"
        self.capsules = "usr/share/compulab/uefi-update-capsules/"
        self.kernel_paths = (
            "boot/Image", "boot/initrd", "boot/config-" + MODULE.RELEASE,
            "boot/Image.nvidia-stock", "boot/initrd.nvidia-stock",
            "etc/nv-update-initrd/list.d/modules.override", self.module,
        )
        self.boot_paths = (
            "usr/sbin/edge-ai-uefi-update", "usr/sbin/edge-ai-select-fdt",
            "usr/bin/oe4t-set-uefi-OSIndications", "usr/bin/uefi_common.func",
            "boot/extlinux/extlinux.conf.imx67x.sample",
            "boot/extlinux/extlinux.conf",
        )
        self.camera_paths = (
            "opt/compulab/bin/argus_camera.sh",
            "opt/compulab/bin/gst_camera.sh",
            "usr/libexec/edge-ai-desktop-exec",
            "usr/libexec/edge-ai-gst-x11-preview",
            "usr/libexec/edge-ai-argus-framos-demo-check", self.dropin,
            "var/nvidia/nvcam/settings/edgedes-imx676-demo.nito",
            "var/nvidia/nvcam/settings/edgedes-imx678-demo.nito",
            "usr/share/edge-ai-argus-framos-demo/PROVENANCE.txt",
            "usr/share/edge-ai-argus-framos-demo/" +
            "Tegra_Software_License_Agreement-Tegra-Linux.txt",
        )
        for relative in self.kernel_paths + self.boot_paths + self.camera_paths:
            self.put(self.root / relative)
        for name in ("modules.dep", "modules.alias", "modules.order",
                     "modules.builtin", "modules.builtin.modinfo"):
            self.put(self.root / "usr/lib/modules" / MODULE.RELEASE / name,
                     b"")
        for folder in ("dtb", "devicetree"):
            (self.artifacts / "boot" / folder).mkdir(parents=True)
        self.artifact_dt = (
            "boot/dtb/edgedes-adi-v18-framos-imx678-4port.dtb",
            "boot/dtb/edgedes-adi-v18-framos-imx678-4port.dtb.sig",
            "boot/devicetree/edgedes-adi-v18-transport-4port.dtbo",
            "boot/devicetree/edgedes-adi-v18-camera-imx678-port0.dtbo",
        )
        for relative in self.artifact_dt:
            self.put(self.artifacts / relative)
            self.put(self.root / relative)
        self.aliases = []
        for machine, sku in zip(MODULE.MACHINES, MODULE.SKUS):
            alias = "boot/dtb/tegra234-" + machine + "-nv-super.dtb"
            stock = "boot/dtb/nvidia-stock-tegra234-p3768-0000+p3767-" + \
                    sku + "-nv-super.dtb"
            self.aliases.extend((alias, stock))
            self.put(self.root / alias)
            self.put(self.root / stock)
        self.put(self.root / (self.aliases[0] + ".signed"))
        self.put(self.root / (self.aliases[1] + ".sig"))
        for machine in MODULE.MACHINES:
            for style in MODULE.STYLES:
                self.put(self.root / self.capsules /
                         (machine + "-uefi-" + style + ".cap"))
        for name in ("README.txt", "SHA256SUMS", "apply-uefi-capsule",
                     "edge-ai-uefi-update", "licenses/MIT"):
            self.put(self.root / self.capsules / name)
        self.manifest = self.sdk / "compulab/runtime/files/argus-full-suite.txt"
        self.put(self.manifest, ("\n".join(MODULE.ARGUS_APPS) + "\n").encode())
        for application in MODULE.ARGUS_APPS:
            self.put(self.root / "usr/bin" / application)
        for plugin in MODULE.PLUGINS:
            self.put(self.root / "usr/lib/aarch64-linux-gnu/gstreamer-1.0" /
                     plugin)

    def put(self, path, value=b"fixture payload\n"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def collect(self):
        return MODULE.collect_packages(self.sdk, self.artifacts, self.version)

    def packages(self):
        return {package["name"].removeprefix("compulab-edge-ai-"): package
                for package in self.collect()}

    def test_collects_complete_nonoverlapping_package_groups(self):
        packages = self.packages()
        self.assertEqual(set(packages), {
            "kernel", "device-trees", "uefi-capsules", "boot-tools",
            "argus", "gstreamer", "camera-support"})
        payloads = []
        for name, package in packages.items():
            self.assertIsInstance(package["paths"], tuple)
            self.assertIsInstance(package["depends"], tuple)
            self.assertIsInstance(package["conffiles"], tuple)
            self.assertEqual(package["paths"],
                             tuple(sorted(set(package["paths"]))))
            self.assertTrue(set(package["conffiles"]) <= set(package["paths"]))
            self.assertTrue(all(not path.startswith("/")
                                for path in package["paths"]))
            expected_arch = ("arm64" if name in
                             ("kernel", "argus", "gstreamer") else "all")
            self.assertEqual(package["architecture"], expected_arch)
            payloads.extend(package["paths"])
        self.assertEqual(len(payloads), len(set(payloads)))
        self.assertEqual(len(packages["argus"]["paths"]), 23)
        self.assertEqual(len(packages["gstreamer"]["paths"]), 3)
        self.assertEqual(set(packages["camera-support"]["paths"]),
                         set(self.camera_paths))

    def test_versions_pin_coordinated_native_and_addon_dependencies(self):
        packages = self.packages()
        self.assertIn("nvidia-l4t-kernel (= " +
                      MODULE.NVIDIA_KERNEL_VERSION + ")",
                      packages["kernel"]["depends"])
        self.assertIn("nvidia-l4t-gstreamer (= " + MODULE.NVIDIA_VERSION + ")",
                      packages["gstreamer"]["depends"])
        self.assertIn("compulab-edge-ai-kernel (= " + self.version + ")",
                      packages["device-trees"]["depends"])
        self.assertIn("compulab-edge-ai-argus (= " + self.version + ")",
                      packages["camera-support"]["depends"])
        # Capsules can be updated independently without replacing boot tools.
        self.assertIn("compulab-edge-ai-uefi-capsules",
                      packages["boot-tools"]["depends"])
        self.assertEqual(packages["uefi-capsules"]["depends"], ())

    def test_administrator_configuration_is_declared_as_conffiles(self):
        packages = self.packages()
        self.assertEqual(packages["boot-tools"]["conffiles"],
                         ("boot/extlinux/extlinux.conf",))
        self.assertEqual(packages["camera-support"]["conffiles"],
                         (self.dropin,))
        self.assertEqual(packages["kernel"]["conffiles"],
                         ("etc/nv-update-initrd/list.d/modules.override",))

    def test_device_trees_are_artifact_scoped_not_all_boot_files(self):
        unrelated = (
            "boot/dtb/unrelated-vendor.dtb",
            "boot/devicetree/other-vendor.dtbo",
            "usr/lib/firmware/vendor.bin", "boot/Image.other",
            "usr/lib/aarch64-linux-gnu/nvidia/libnvargus.so",
        )
        for relative in unrelated:
            self.put(self.root / relative)
        self.put(self.artifacts / "boot/dtb/unrelated-readme.txt")
        packages = self.packages()
        expected = set(self.artifact_dt) | set(self.aliases) | {
            self.aliases[0] + ".signed", self.aliases[1] + ".sig"}
        self.assertEqual(set(packages["device-trees"]["paths"]), expected)
        all_paths = set().union(*(set(package["paths"])
                                  for package in packages.values()))
        self.assertFalse(all_paths.intersection(unrelated))

    def test_capsule_inventory_includes_entire_scoped_bundle(self):
        relative = self.capsules + "edge-ai-nx-16g-uefi-no-logo-from-guid.cap"
        self.put(self.root / relative)
        paths = self.packages()["uefi-capsules"]["paths"]
        self.assertIn(relative, paths)
        self.assertIn(self.capsules + "licenses/MIT", paths)
        self.assertTrue(all(path.startswith(self.capsules) for path in paths))

    def test_missing_required_payloads_are_rejected(self):
        representatives = (
            "boot/Image", "boot/initrd", self.kernel_paths[5],
            self.artifact_dt[0], self.aliases[0],
            self.capsules + "edge-ai-nx-16g-uefi-no-logo.cap",
            self.capsules + "SHA256SUMS", self.boot_paths[0],
            "usr/bin/argus_camera",
            "usr/lib/aarch64-linux-gnu/gstreamer-1.0/" + MODULE.PLUGINS[0],
            self.camera_paths[0], self.camera_paths[3], self.camera_paths[6],
        )
        for relative in representatives:
            with self.subTest(path=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaises(ValueError):
                        self.collect()
                finally:
                    self.put(path, original)

    def test_empty_or_incomplete_module_tree_is_rejected(self):
        (self.root / self.module).unlink()
        with self.assertRaisesRegex(ValueError, "no loadable modules"):
            self.collect()

    def test_symlinked_rootfs_or_staging_root_is_rejected(self):
        alias = self.directory / "sdk-alias"
        alias.symlink_to(self.sdk, target_is_directory=True)
        with self.assertRaises(ValueError):
            MODULE.collect_packages(alias, self.artifacts, self.version)
        alias.unlink()
        original = self.root
        moved = self.sdk / "saved-rootfs"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.collect()

    def test_symlinked_module_directory_is_rejected(self):
        source = self.root / "usr/lib/modules" / MODULE.RELEASE
        saved = self.directory / "saved-modules"
        source.rename(saved)
        source.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.collect()

    def test_symlinked_capsule_tree_or_file_is_rejected(self):
        payload = self.root / self.capsules / "edge-ai-nx-16g-uefi-no-logo.cap"
        saved = self.directory / "saved-capsule"
        payload.rename(saved)
        payload.symlink_to(saved)
        with self.assertRaises(ValueError):
            self.collect()

    def test_existing_alias_companions_cannot_escape_rootfs(self):
        companion = self.root / (self.aliases[2] + ".sig")
        companion.symlink_to(self.directory / "missing-outside")
        with self.assertRaises(ValueError):
            self.collect()

    def test_artifact_symlinks_and_orphan_companions_are_rejected(self):
        payload = self.artifacts / self.artifact_dt[0]
        saved = self.directory / "saved-device-tree"
        payload.rename(saved)
        payload.symlink_to(saved)
        with self.assertRaises(ValueError):
            self.collect()
        payload.unlink()
        self.put(payload)
        orphan = "boot/dtb/orphan.dtb.sig"
        self.put(self.artifacts / orphan)
        self.put(self.root / orphan)
        with self.assertRaises(ValueError):
            self.collect()

    def test_argus_manifest_must_be_exact_complete_suite(self):
        for applications in (
                MODULE.ARGUS_APPS[:-1],
                MODULE.ARGUS_APPS[:-1] + (MODULE.ARGUS_APPS[0],),
                MODULE.ARGUS_APPS[:-1] + ("../../tmp/unexpected",),
                MODULE.ARGUS_APPS[:-1] + ("argus_unreviewed",)):
            with self.subTest(applications=applications):
                self.manifest.write_text("\n".join(applications) + "\n")
                with self.assertRaises(ValueError):
                    self.collect()

    def test_invalid_versions_are_rejected(self):
        for version in ("", "v1", "1\nDepends: injected", "1/path", "1;id",
                        "1 " , True, "1" * 129):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    MODULE.collect_packages(self.sdk, self.artifacts, version)

    def test_collect_does_not_change_fixture_files(self):
        def contents():
            return {path.relative_to(self.directory).as_posix():
                    path.read_bytes()
                    for path in self.directory.rglob("*") if path.is_file()}
        before = contents()
        first = self.collect()
        self.assertEqual(contents(), before)
        self.assertEqual(self.collect(), first)
        self.assertEqual(contents(), before)


if __name__ == "__main__":
    unittest.main()

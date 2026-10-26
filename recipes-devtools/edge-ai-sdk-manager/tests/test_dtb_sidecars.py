#!/usr/bin/env python3
"""Temp-only DT companion tests: no signing, chroot, mounts or SDK writes."""
# SPDX-License-Identifier: MIT

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


FILES = Path(__file__).resolve().parents[1] / "files"


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


ASSEMBLE = load("sidecar_assemble", FILES / "assemble-sdk.py")
INSTALL = load("sidecar_install", FILES / "sdk-source/compulab/tools/install-kernel.py")
RELEASE = INSTALL.EXPECTED_RELEASE


class DeviceTreeSidecars(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, path, payload=b"fixture"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload.encode() if isinstance(payload, str) else payload)
        return path

    def dtb_name(self, sku):
        return "tegra234-p3768-0000+p3767-%s-nv-super.dtb" % sku

    def prepare(self):
        deploy = self.root / "deploy"
        for sku in ASSEMBLE.SKUS.values():
            self.put(deploy / "devicetree" / self.dtb_name(sku), b"raw-" + sku.encode())
        return {"deploy": str(deploy), "work": str(self.root / "work")}

    def fake_export(self, deploy, name, target):
        target.mkdir(parents=True)
        self.put(target / "metadata/kernel.release", RELEASE + "\n")
        if name == "kernel":
            self.put(target / "boot/Image", b"image")
            return {"metadata": {"kernel_provider": "linux-noble-nvidia-tegra",
                                 "config_requests": {str(i): "y" for i in range(109)}}}
        self.put(target / "metadata/replacement-drivers.txt", b"")
        return {"metadata": {}}

    def prepared(self, configuration):
        with mock.patch.object(ASSEMBLE, "checked_export", side_effect=self.fake_export), \
             mock.patch.object(ASSEMBLE, "run"):
            return ASSEMBLE.prepare_artifacts(configuration)[0]

    def test_prepare_preserves_raw_dtbs_overlays_and_both_companion_kinds(self):
        configuration = self.prepare()
        deploy = Path(configuration["deploy"]) / "devicetree"
        for name in (self.dtb_name("0000"), "edgedes-camera.dtb", "camera.dtbo"):
            if not (deploy / name).exists():
                self.put(deploy / name, b"raw")
            for suffix in (".sig", ".signed"):
                self.put(deploy / (name + suffix), (name + suffix).encode())
        result = self.prepared(configuration)
        for name in (self.dtb_name("0000"), "edgedes-camera.dtb", "camera.dtbo"):
            for suffix in ("", ".sig", ".signed"):
                self.assertEqual((result / "boot/devicetree" / (name + suffix)).read_bytes(),
                                 (deploy / (name + suffix)).read_bytes())
                if name.endswith(".dtb"):
                    self.assertEqual((result / "boot/dtb" / (name + suffix)).read_bytes(),
                                     (deploy / (name + suffix)).read_bytes())
        self.assertEqual((result / "boot/dtb" / self.dtb_name("0000")).read_bytes(), b"raw-0000")

    def test_unsigned_prepare_does_not_require_or_create_companions(self):
        result = self.prepared(self.prepare())
        self.assertEqual(list(result.rglob("*.sig")), [])
        self.assertEqual(list(result.rglob("*.signed")), [])

    def test_orphan_companion_fails_before_installation(self):
        configuration = self.prepare()
        self.put(Path(configuration["deploy"]) / "devicetree/orphan.dtb.sig")
        with self.assertRaisesRegex(RuntimeError, "lacks its raw input"):
            self.prepared(configuration)

    def test_conflicting_companions_of_identical_raw_dtb_fail(self):
        configuration = self.prepare()
        deploy = Path(configuration["deploy"])
        name = self.dtb_name("0000")
        self.put(deploy / name, b"raw-0000")
        self.put(deploy / (name + ".sig"), b"first")
        self.put(deploy / "devicetree" / (name + ".sig"), b"second")
        with self.assertRaisesRegex(RuntimeError, "Conflicting companions"):
            self.prepared(configuration)

    def test_alias_companion_lookup_requires_identical_raw_inputs(self):
        rootfs = self.root / "artifacts"
        name = self.dtb_name("0000")
        self.put(rootfs / "boot/dtb" / name, b"raw")
        self.put(rootfs / "boot/devicetree" / name, b"raw")
        expected = self.put(rootfs / "boot/devicetree" / (name + ".sig"), b"signature")
        self.assertEqual(INSTALL.find_dtb_companion(rootfs, name, ".sig"), expected)
        self.put(rootfs / "boot/dtb" / name, b"different-raw")
        with self.assertRaisesRegex(RuntimeError, "Conflicting installed copies"):
            INSTALL.find_dtb_companion(rootfs, name, ".sig")

    def stock_sdk(self):
        sdk = self.root / "sdk"
        for name in ("flash.sh", "tools/kernel_flash/l4t_flash_from_kernel.sh",
                     "tools/kernel_flash/l4t_initrd_flash_internal.sh",
                     "kernel/Image", "rootfs/boot/Image", "rootfs/boot/initrd",
                     "rootfs/boot/extlinux/extlinux.conf"):
            self.put(sdk / name)
        self.put(sdk / "rootfs/etc/os-release", "ID=ubuntu\n")
        self.put(sdk / "rootfs/etc/nv_tegra_release", "# R39 (release), REVISION: 2.1,\n")
        for sku in ASSEMBLE.SKUS.values():
            self.put(sdk / "kernel/dtb" / self.dtb_name(sku), b"stock-" + sku.encode())
        return sdk

    def test_baseline_only_backs_up_existing_stock_companions(self):
        sdk = self.stock_sdk()
        name = self.dtb_name("0000")
        for suffix in (".sig", ".signed"):
            self.put(sdk / "kernel/dtb" / (name + suffix), suffix)
        with mock.patch.object(ASSEMBLE, "run"):
            ASSEMBLE.baseline(sdk)
        receipt = json.loads((sdk / "SDK_BASELINE.json").read_text())
        backup = Path(receipt["vendor_backup"])
        for suffix in (".sig", ".signed"):
            self.assertEqual((backup / "kernel/dtb" / (name + suffix)).read_text(), suffix)
        self.assertNotIn("kernel/dtb/" + self.dtb_name("0001") + ".sig", receipt["sha256"])

    def test_baseline_preserves_native_internal_before_local_fix(self):
        sdk = self.stock_sdk()
        relative = "tools/kernel_flash/l4t_initrd_flash_internal.sh"
        native = sdk / relative
        original = native.read_bytes()
        original_hash = ASSEMBLE.digest(native)
        with mock.patch.object(ASSEMBLE, "run"):
            ASSEMBLE.baseline(sdk)
        baseline = sdk / "SDK_BASELINE.json"
        recorded = baseline.read_bytes()
        receipt = json.loads(recorded)
        backup = Path(receipt["vendor_backup"]) / relative
        self.assertEqual(receipt["sha256"][relative], original_hash)
        self.assertEqual(backup.read_bytes(), original)
        # A reviewed local fix must not relabel modified bytes as the vendor
        # baseline or overwrite the pristine rollback copy.
        native.write_bytes(b"fixture reviewed native change\n")
        self.assertNotEqual(ASSEMBLE.digest(native), original_hash)
        self.assertEqual(baseline.read_bytes(), recorded)
        self.assertEqual(backup.read_bytes(), original)

    def test_install_preserves_custom_alias_and_stock_companions(self):
        sdk = self.stock_sdk()
        backup = self.root / "backup"
        for name in ("Image", "initrd"):
            self.put(backup / "rootfs/boot" / name)
        artifacts = self.root / "artifacts"
        modules = artifacts / "usr/lib/modules" / RELEASE
        self.put(modules / "kernel/test.ko")
        self.put(artifacts / "boot/Image")
        self.put(artifacts / "metadata/kernel.config")
        for sku in ASSEMBLE.SKUS.values():
            name = self.dtb_name(sku)
            self.put(backup / "kernel/dtb" / name, b"stock-" + sku.encode())
            for directory in ("dtb", "devicetree"):
                self.put(artifacts / "boot" / directory / name, b"raw-" + sku.encode())
                for suffix in (".sig", ".signed"):
                    self.put(artifacts / "boot" / directory / (name + suffix),
                             (sku + suffix).encode())
        stock_name = self.dtb_name("0000")
        self.put(backup / "kernel/dtb" / (stock_name + ".sig"), b"stock-signature")
        self.put(backup / "kernel/dtb" / (stock_name + ".signed"), b"stock-signed")
        for suffix in ("", ".sig", ".signed"):
            self.put(artifacts / "boot/devicetree" / ("camera.dtbo" + suffix),
                     ("camera" + suffix).encode())

        def fake_run(*command, **kwargs):
            if str(command[0]).endswith("l4t_update_initrd.sh"):
                self.put(sdk / "rootfs/boot/initrd", b"new-initrd")
                self.put(sdk / "bootloader/l4t_initrd.img", b"new-initrd")

        listing = RELEASE + "\nnvme.ko\npcie-tegra194.ko\nphy-tegra194-p2u.ko\n"
        with mock.patch.object(INSTALL.os, "geteuid", return_value=0), \
             mock.patch.object(INSTALL, "run", side_effect=fake_run), \
             mock.patch.object(INSTALL, "prepare_initrd_list"), \
             mock.patch.object(INSTALL.subprocess, "check_output", return_value=listing):
            INSTALL.install(artifacts, sdk, artifacts, modules, backup)
        for model, sku in ASSEMBLE.SKUS.items():
            alias = "tegra234-" + model + "-nv-super.dtb"
            for directory in ("kernel/dtb", "rootfs/boot/dtb"):
                self.assertEqual((sdk / directory / alias).read_bytes(), b"raw-" + sku.encode())
                for suffix in (".sig", ".signed"):
                    self.assertEqual((sdk / directory / (alias + suffix)).read_bytes(),
                                     (sku + suffix).encode())
        for suffix in ("", ".sig", ".signed"):
            self.assertEqual((sdk / "rootfs/boot/devicetree" / ("camera.dtbo" + suffix)).read_bytes(),
                             ("camera" + suffix).encode())
        for suffix, expected in ((".sig", b"stock-signature"), (".signed", b"stock-signed")):
            self.assertEqual((sdk / "rootfs/boot/dtb" / ("nvidia-stock-" + stock_name + suffix)).read_bytes(),
                             expected)


if __name__ == "__main__":
    unittest.main()

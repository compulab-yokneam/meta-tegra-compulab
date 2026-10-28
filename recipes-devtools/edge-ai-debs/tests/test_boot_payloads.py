#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Boot payload fixtures; no privileged commands, SDK writes or hardware."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "standalone_boot_payloads", DIRECTORY / "files/build-boot-payloads.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ASSEMBLE_SPEC = importlib.util.spec_from_file_location(
    "standalone_kernel_assembler",
    DIRECTORY.parent / "edge-ai-sdk-manager/files/assemble-sdk.py")
ASSEMBLE = importlib.util.module_from_spec(ASSEMBLE_SPEC)
ASSEMBLE_SPEC.loader.exec_module(ASSEMBLE)


class BootPayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edge-ai-boot-payloads-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sdk = self.root / "SDK"
        self.deploy = self.root / "deploy"
        self.sources = self.root / "sources"
        self.run_dir = self.root / "run"
        for path in (self.sdk, self.deploy, self.sources, self.run_dir):
            path.mkdir()
        self.config = dict(sdk=self.sdk, deploy=self.deploy, sources=self.sources)
        for name in ("assemble-sdk.py", "install-kernel.py", "check-module-abi.py",
                     "provision-runtime.py"):
            self.put(self.sources / name, "# fixture\n")
        self.put(self.sdk / "tools/l4t_update_initrd.sh", "#!/bin/sh\nexit 0\n")
        self.put(self.sdk / ".git/HEAD", "ref: refs/heads/fixture\n")
        self.put(self.sdk / "rootfs/usr/lib/os-release", 'ID=ubuntu\nVERSION_ID="24.04"\n')
        self.put(self.sdk / "rootfs/etc/nv_tegra_release", "# R39 (release), REVISION: 2.1,\n")
        self.put(self.sdk / "rootfs/usr/sbin/nv-update-initrd", "#!/bin/sh\nexit 0\n")
        arm64 = b"\x7fELF\x02\x01" + bytes(12) + (183).to_bytes(2, "little")
        self.put(self.sdk / "rootfs/usr/bin/dpkg", arm64)
        self.put(self.sdk / "rootfs/var/lib/dpkg/status", "\n\n".join(
            "Package: %s\nArchitecture: arm64\nVersion: %s\nStatus: hold ok installed" % item
            for item in (("nvidia-l4t-initrd", MODULE.NVIDIA_VERSION),
                         ("nvidia-l4t-kernel", "6.8.12-tegra-" + MODULE.NVIDIA_VERSION))))
        self.put(self.sdk / "rootfs/etc/nv-update-initrd/list.d/modules_k6.8", "# vendor\n")
        self.put(self.sdk / "rootfs/boot/Image", b"old custom image")
        self.put(self.sdk / "rootfs/boot/initrd", b"old custom initrd")
        self.put(self.sdk / "rootfs/boot/Image.nvidia-stock", b"old fallback image")
        self.put(self.sdk / "rootfs/boot/initrd.nvidia-stock", b"old fallback initrd")
        self.put(self.sdk / "rootfs/usr/lib/modules" / MODULE.RELEASE / "old.ko", b"old module")
        self.put(self.sdk / "rootfs/boot/dtb/obsolete-custom.dtb", b"must not be packaged")
        self.baseline = dict(format_version=1, l4t_version="39.2.1",
                             vendor_backup="/different-host/old-mount/backup", sha256={})
        self.stock("kernel/Image", b"stock kernel")
        self.stock("rootfs/boot/Image", b"stock kernel")
        self.stock("rootfs/boot/initrd", b"stock initrd")
        for sku in MODULE.SKUS.values():
            name = MODULE.dtb_name(sku)
            self.put(self.deploy / "devicetree" / name, ("fresh " + sku).encode())
            self.stock("kernel/dtb/" + name, ("stock " + sku).encode())
        required = {"edgedes-adi-v18-transport-4port.dtbo",
                    "edgedes-adi-v18-framos-imx676-4port.dtb",
                    "edgedes-adi-v18-framos-imx678-4port.dtb",
                    "tegra234-edge-ai-adi-base.dtb"}
        required.update("edgedes-adi-v18-camera-%s-port%d.dtbo" % (sensor, port)
                        for sensor in ("imx676", "imx678") for port in range(4))
        for name in required:
            self.put(self.deploy / "devicetree" / name, ("fresh " + name).encode())
        self.write_baseline()

    def put(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    def stock(self, name, data):
        path = self.put(self.sdk / "compulab/vendor-backup" / name, data)
        self.baseline["sha256"][name] = MODULE.digest(path)

    def write_baseline(self):
        self.put(self.sdk / "SDK_BASELINE.json", json.dumps(self.baseline))

    def kernel_config(self, artifacts):
        fragments = {
            "compulab.cfg": {"CONFIG_TEST_PERIPHERAL": "m"},
            "edge-ai-noble.cfg": {"CONFIG_MODVERSIONS": "y"},
            "edgedes-adi-v18.cfg": {"CONFIG_TEST_CAMERA": "m"},
        }
        requests = {}
        for name, values in fragments.items():
            self.put(artifacts / "metadata/config-fragments" / name, "\n".join(
                key + "=" + value for key, value in values.items()) + "\n")
            requests.update(values)
        self.put(artifacts / "metadata/kernel.config", "\n".join(
            name + "=" + value for name, value in requests.items()) + "\n")
        self.put(artifacts / "metadata/kernel.release", MODULE.RELEASE + "\n")
        manifest = dict(component="kernel", kernel_release=MODULE.RELEASE,
                        metadata=dict(kernel_provider="linux-noble-nvidia-tegra",
                                      kernel_release=MODULE.RELEASE,
                                      config_requests=requests), files={})
        self.record_kernel_files(artifacts, manifest)
        return manifest

    def record_kernel_files(self, artifacts, manifest):
        manifest["files"] = {path.relative_to(artifacts).as_posix(): MODULE.digest(path)
                             for path in artifacts.rglob("*") if path.is_file()}

    def test_dt_builder_uses_fresh_deploy_and_verified_original_stock_only(self):
        payload, metadata = MODULE.build_device_trees(self.config, self.run_dir)
        for machine, sku in MODULE.SKUS.items():
            current = payload / "boot/dtb" / ("tegra234-" + machine + "-nv-super.dtb")
            fallback = payload / "boot/dtb" / ("nvidia-stock-" + MODULE.dtb_name(sku))
            self.assertEqual(current.read_bytes(), ("fresh " + sku).encode())
            self.assertEqual(fallback.read_bytes(), ("stock " + sku).encode())
        self.assertFalse((payload / "boot/dtb/obsolete-custom.dtb").exists())
        self.assertEqual(metadata["kernel_release"], MODULE.RELEASE)
        self.assertEqual(metadata["overlay_count"], 9)
        self.assertFalse((self.run_dir / "Linux_for_Tegra").exists())

    def test_dt_provenance_does_not_require_kernel_exports_or_native_sources(self):
        shutil.rmtree(self.sources)
        before = MODULE.input_provenance(self.config, "device-trees")
        path = self.deploy / "devicetree/edgedes-adi-v18-camera-imx676-port0.dtbo"
        path.write_bytes(b"newly rebuilt overlay")
        after = MODULE.input_provenance(self.config, "device-trees")
        self.assertNotEqual(before, after)
        self.assertFalse(any("kernel.tar" in name or "nvidia-kernel-oot" in name
                             for name in after))

    def test_old_sdk_custom_dt_changes_do_not_supply_dt_payload(self):
        before = MODULE.input_provenance(self.config, "device-trees")
        (self.sdk / "rootfs/boot/dtb/obsolete-custom.dtb").write_bytes(b"changed stale DT")
        self.assertEqual(before, MODULE.input_provenance(self.config, "device-trees"))

    def test_missing_camera_port_overlay_is_rejected(self):
        (self.deploy / "devicetree/edgedes-adi-v18-camera-imx678-port3.dtbo").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            MODULE.build_device_trees(self.config, self.run_dir)

    def test_conflicting_module_dtb_is_rejected(self):
        self.put(self.deploy / MODULE.dtb_name("0000"), b"other DT")
        with self.assertRaisesRegex(ValueError, "conflicting"):
            MODULE.fresh_dt_inputs(self.deploy)

    def test_signature_requires_its_fresh_raw_input(self):
        self.put(self.deploy / "devicetree/orphan.dtbo.sig", b"signature")
        with self.assertRaisesRegex(ValueError, "regular boot input"):
            MODULE.fresh_dt_inputs(self.deploy)

    def test_fresh_and_stock_companions_follow_correct_aliases(self):
        name = MODULE.dtb_name("0000")
        self.put(self.deploy / "devicetree" / (name + ".sig"), b"fresh signature")
        self.stock("kernel/dtb/" + name + ".signed", b"stock signature")
        self.write_baseline()
        payload, _ = MODULE.build_device_trees(self.config, self.run_dir)
        alias = payload / "boot/dtb/tegra234-edge-ai-nx-16g-nv-super.dtb.sig"
        self.assertEqual(alias.read_bytes(), b"fresh signature")
        fallback = payload / "boot/dtb" / ("nvidia-stock-" + name + ".signed")
        self.assertEqual(fallback.read_bytes(), b"stock signature")

    def test_modified_vendor_backup_is_never_accepted_as_stock(self):
        stock = self.sdk / "compulab/vendor-backup/kernel/dtb" / MODULE.dtb_name("0000")
        stock.write_bytes(b"customized stock is not stock")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            MODULE.build_device_trees(self.config, self.run_dir)

    def test_vendor_backup_path_is_portable_but_confined_to_selected_sdk(self):
        path = MODULE.stock_file(self.sdk, "rootfs/boot/initrd")
        self.assertEqual(path.read_bytes(), b"stock initrd")
        self.assertTrue(path.is_relative_to(self.sdk))
        with self.assertRaisesRegex(ValueError, "Unsafe relative"):
            MODULE.stock_file(self.sdk, "../outside")

    def test_all_fragment_requested_kernel_settings_are_checked(self):
        artifacts = self.root / "artifacts"
        manifest = self.kernel_config(artifacts)
        self.assertEqual(ASSEMBLE.validate_kernel_config(artifacts, manifest), 3)
        path = artifacts / "metadata/kernel.config"
        path.write_text(path.read_text().replace("CONFIG_TEST_CAMERA=m",
                                                 "CONFIG_TEST_CAMERA=y"))
        self.record_kernel_files(artifacts, manifest)
        with self.assertRaisesRegex(RuntimeError, "not honored"):
            ASSEMBLE.validate_kernel_config(artifacts, manifest)

    def test_new_firmware_setting_does_not_require_a_fixed_request_count(self):
        artifacts = self.root / "artifacts"
        manifest = self.kernel_config(artifacts)
        self.assertEqual(ASSEMBLE.validate_kernel_config(artifacts, manifest), 3)
        for name in ("metadata/config-fragments/compulab.cfg", "metadata/kernel.config"):
            path = artifacts / name
            path.write_text(path.read_text() + "CONFIG_FW_LOADER_COMPRESS=y\n")
        manifest["metadata"]["config_requests"]["CONFIG_FW_LOADER_COMPRESS"] = "y"
        self.record_kernel_files(artifacts, manifest)
        self.assertEqual(ASSEMBLE.validate_kernel_config(artifacts, manifest), 4)

    def test_kernel_provider_requests_modversions_and_release_are_not_weakened(self):
        artifacts = self.root / "artifacts"
        manifest = self.kernel_config(artifacts)
        manifest["metadata"]["kernel_provider"] = "linux-yocto"
        with self.assertRaisesRegex(RuntimeError, "provider|Noble"):
            ASSEMBLE.validate_kernel_config(artifacts, manifest)
        manifest = self.kernel_config(artifacts)
        manifest["metadata"]["config_requests"].pop("CONFIG_TEST_PERIPHERAL")
        with self.assertRaisesRegex(RuntimeError, "[Rr]equest"):
            ASSEMBLE.validate_kernel_config(artifacts, manifest)
        manifest = self.kernel_config(artifacts)
        for name in ("metadata/config-fragments/edge-ai-noble.cfg", "metadata/kernel.config"):
            path = artifacts / name
            path.write_text(path.read_text().replace("CONFIG_MODVERSIONS=y",
                                                     "# CONFIG_MODVERSIONS is not set"))
        manifest["metadata"]["config_requests"]["CONFIG_MODVERSIONS"] = "n"
        self.record_kernel_files(artifacts, manifest)
        with self.assertRaisesRegex(RuntimeError, "MODVERSIONS|CRCs"):
            ASSEMBLE.validate_kernel_config(artifacts, manifest)
        manifest = self.kernel_config(artifacts)
        self.put(artifacts / "metadata/kernel.release", "wrong-release\n")
        self.record_kernel_files(artifacts, manifest)
        with self.assertRaisesRegex(RuntimeError, "release differs"):
            ASSEMBLE.validate_kernel_config(artifacts, manifest)

    def test_ubuntu_initrd_environment_accepts_existing_holds(self):
        MODULE.validate_ubuntu_sdk(self.sdk)
        path = self.sdk / "rootfs/var/lib/dpkg/status"
        path.write_text(path.read_text().replace("hold ok installed", "hold ok unpacked"))
        with self.assertRaisesRegex(ValueError, "environment"):
            MODULE.validate_ubuntu_sdk(self.sdk)

    def test_clone_quarantines_old_custom_modules_without_mutating_sdk(self):
        original = self.sdk / "rootfs/usr/lib/modules" / MODULE.RELEASE / "old.ko"
        self.put(self.sdk / "rootfs/proc/must-not-copy", b"transient")
        with mock.patch.object(MODULE, "run", return_value=""):
            clone = MODULE.clone_sdk_rootfs(self.config, self.run_dir)
        self.assertEqual(original.read_bytes(), b"old module")
        self.assertFalse((clone / "rootfs/usr/lib/modules" / MODULE.RELEASE).exists())
        self.assertEqual((self.run_dir / "clone-backup/rootfs/usr/lib/modules" /
                          MODULE.RELEASE / "old.ko").read_bytes(), b"old module")
        self.assertEqual((clone / "bootloader/l4t_initrd.img").read_bytes(), b"stock initrd")
        self.assertFalse((clone / "rootfs/proc/must-not-copy").exists())
        self.assertFalse((clone / "rootfs/boot/Image.nvidia-stock").exists())
        self.assertTrue((self.sdk / "rootfs/boot/Image.nvidia-stock").exists())
        self.assertNotEqual(original.stat().st_ino,
                            (self.run_dir / "clone-backup/rootfs/usr/lib/modules" /
                             MODULE.RELEASE / "old.ko").stat().st_ino)

    def test_clone_refuses_source_mounts_and_source_overlap(self):
        with mock.patch.object(MODULE, "run", return_value=str(self.sdk / "rootfs/proc")):
            with self.assertRaisesRegex(ValueError, "active mounts"):
                MODULE.clone_sdk_rootfs(self.config, self.run_dir)
        inside = self.sdk / "private"
        inside.mkdir()
        with self.assertRaisesRegex(ValueError, "overlap"):
            MODULE.clone_sdk_rootfs(self.config, inside)

    def test_invalid_kernel_configuration_stops_before_clone_or_install(self):
        artifacts = self.root / "artifacts"
        manifest = self.kernel_config(artifacts)
        manifest["metadata"]["config_requests"].pop("CONFIG_TEST_CAMERA")
        assembler = SimpleNamespace(
            prepare_artifacts=mock.Mock(return_value=(artifacts, {"kernel": manifest})),
            validate_kernel_config=ASSEMBLE.validate_kernel_config)
        with mock.patch.object(MODULE.os, "geteuid", return_value=0), \
                mock.patch.object(MODULE, "input_provenance", return_value={}), \
                mock.patch.object(MODULE, "load_module", return_value=assembler), \
                mock.patch.object(MODULE, "clone_sdk_rootfs") as clone, \
                mock.patch.object(MODULE, "install_private_kernel") as install:
            with self.assertRaisesRegex(RuntimeError, "[Rr]equest"):
                MODULE.build_kernel(self.config, self.run_dir)
        clone.assert_not_called()
        install.assert_not_called()

    def test_kernel_pipeline_carries_only_kernel_payload_and_preserves_validation(self):
        artifacts = self.root / "artifacts"
        manifest = self.kernel_config(artifacts)
        clone = self.root / "clone"
        for name in ("boot/Image", "boot/initrd", "boot/config-" + MODULE.RELEASE,
                     "boot/Image.nvidia-stock", "boot/initrd.nvidia-stock",
                     "etc/nv-update-initrd/list.d/modules.override"):
            self.put(clone / "rootfs" / name, "fresh " + name)
        for index in range(101):
            self.put(clone / "rootfs/usr/lib/modules" / MODULE.RELEASE /
                     ("kernel/module%d.ko" % index), b"fixture module")
        assembler = SimpleNamespace(
            prepare_artifacts=mock.Mock(return_value=(artifacts, {"kernel": manifest})),
            validate_kernel_config=mock.Mock(wraps=ASSEMBLE.validate_kernel_config))
        installed = dict(module_count=101, initrd_sha256="0" * 64)
        with mock.patch.object(MODULE.os, "geteuid", return_value=0), \
                mock.patch.object(MODULE, "input_provenance", return_value={"fresh": "hash"}), \
                mock.patch.object(MODULE, "load_module", return_value=assembler), \
                mock.patch.object(MODULE, "clone_sdk_rootfs", return_value=clone), \
                mock.patch.object(MODULE, "install_private_kernel", return_value=installed) as install:
            payload, metadata = MODULE.build_kernel(self.config, self.run_dir)
        install.assert_called_once_with(self.config, artifacts, clone)
        assembler.validate_kernel_config.assert_called_once_with(artifacts, manifest)
        self.assertEqual(metadata["config_request_count"], 3)
        self.assertEqual(metadata["module_count"], 101)
        self.assertEqual(len(list(payload.rglob("*.ko"))), 101)
        self.assertFalse((payload / "boot/dtb").exists())
        self.assertEqual(metadata["diversions"][0][0], "/boot/Image")


if __name__ == "__main__":
    unittest.main()

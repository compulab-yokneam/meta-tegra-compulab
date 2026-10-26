#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
"""Exercise real export helper on fixtures, without BitBake or SDK Manager."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import zlib

DIRECTORY = Path(__file__).resolve().parents[1]
LAYER = DIRECTORY.parents[1]
INCLUDE = DIRECTORY / "edge-ai-sdk-firmware-export.inc"


class ExportFailure(RuntimeError):
    pass


def fail(message):
    raise ExportFailure(message)


class Data(dict):
    def getVar(self, name):
        return self.get(name)


class FirmwareExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = INCLUDE.read_text()
        helper = re.search(r"(?ms)^def edge_ai_sdk_firmware_export\(d\):\n.*?"
                           r"(?=^python edge_ai_sdk_export_firmware)", text)[0]
        namespace = {"bb": SimpleNamespace(fatal=fail)}
        exec(helper, namespace)
        cls.export = staticmethod(namespace["edge_ai_sdk_firmware_export"])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edge-ai-firmware-export-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.build = self.root / "build"
        self.source = self.root / "source/edk2"
        self.nvidia = self.root / "source/edk2-nvidia"
        self.deploy = self.root / "deploy"
        self.staging = self.root / "sysroot/usr/share"
        self.license = self.source / "License.txt"
        self.write(self.license, b"Original copyright\nFull license notice\n")
        self.data = Data({
            "EDGE_AI_SDK_EXPORTS": "1",
            "EDGE_AI_SDK_FIRMWARE_ROLE": "general",
            "EDGE_AI_UEFI_LOGO_STYLE": "clab",
            "SOC_FAMILY": "tegra234",
            "B": str(self.build), "S": str(self.source),
            "S_EDK2_NVIDIA": str(self.nvidia),
            "DEPLOYDIR": str(self.deploy),
            "STAGING_DATADIR": str(self.staging),
            "EDK2_PLATFORM": "t23x_general",
            "EDK2_BIN_NAME": "uefi_t23x_general.bin",
            "EDK2_PLATFORM_DSC": "Platform/NVIDIA/NVIDIA.common.dsc",
            "EDK2_BUILD_MODE": "RELEASE", "EDK_COMPILER": "GCC5",
            "TEGRA_UEFI_STMM_DEBUG_PRINT_ERROR_LEVEL": "0x80000002",
            "TEGRA_UEFI_LOWEST_SUPPORTED_VERSION": "0x270201",
            "PN": "edk2-firmware-tegra", "PV": "39.2.1", "PR": "r0",
            "MACHINE": "edge-ai-nano-8g",
            "BB_CURRENT_MC": "edge-ai-uefi-nano-8g-clab-logo",
            "L4T_VERSION": "39.2.1", "LICENSE": "BSD-2-Clause-Patent",
            "LIC_FILES_CHKSUM": "file://License.txt;md5=fixture;beginline=1;endline=1",
            "SOURCE_DATE_EPOCH": "1700000000",
            "SRCREV_edk2": "1" * 40,
            "SRCREV_edk2-nvidia": "2" * 40,
            "TOSIMG": "tos-optee_t234.img",
        })
        self.write(self.build / "images/uefi_t23x_general.bin", b"raw general UEFI")
        self.write(self.build / "images/BOOTAA64.efi", b"MZsigned launcher")
        for name in ("L4TConfiguration.dtbo", "L4TConfiguration-rcmboot.dtbo",
                     "L4TConfiguration-RootfsRedundancyLevelABEnable.dtbo"):
            self.write(self.build / "images" / name, name.encode())
        config = self.build / "nvidia-config/Tegra/t23x_general"
        self.write(config / ".config", b"CONFIG_BUILD_GENERAL=y\nCONFIG_CLAB_LOGO=y\n")
        self.write(config / "fmp-image-type-id.txt", b"bf0d4599-20d4-414e-b2c5-3595b1cda402\n")

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def output(self):
        return self.deploy / "edge-ai-sdk/firmware" / self.data["PN"]

    def run_export(self):
        self.export(self.data)
        manifest = json.loads((self.output() / "manifest.json").read_text())
        result = subprocess.run(["sha256sum", "-c", "SHA256SUMS"],
                                cwd=self.output(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(not Path(entry["origin"]).is_absolute()
                            for entry in manifest["files"]))
        self.assertNotIn(str(self.root), json.dumps(manifest))
        return manifest

    def setup_rcm(self):
        self.data.update(EDGE_AI_SDK_FIRMWARE_ROLE="rcm",
                         PN="edk2-firmware-tegra-rcmboot",
                         EDK2_PLATFORM="t23x_minimal",
                         EDK2_BIN_NAME="uefi_t23x_minimal.bin")
        self.write(self.build / "images/uefi_t23x_minimal.bin", b"minimal recovery only")
        self.write(self.build / "nvidia-config/Tegra/t23x_minimal/.config",
                   b"CONFIG_BUILD_MINIMAL=y\n# CONFIG_LOGO is not set\n")

    def setup_mm(self):
        self.data.update(EDGE_AI_SDK_FIRMWARE_ROLE="standalone-mm",
                         PN="edk2-nvidia-standalone-mm",
                         EDK2_PLATFORM="StandaloneMmOptee",
                         EDK2_BIN_NAME="standalone_mm_optee.bin",
                         EDK2_PLATFORM_DSC="Platform/NVIDIA/StandaloneMmOptee/StandaloneMmOptee.dsc")
        self.write(self.build / "images/standalone_mm_optee.bin", b"standalone MM")
        self.write(self.nvidia / self.data["EDK2_PLATFORM_DSC"],
                   b"# Original NVIDIA copyright\n[Defines]\n")

    def setup_tos(self):
        self.data.update(EDGE_AI_SDK_FIRMWARE_ROLE="tos", PN="tos-optee")
        self.mm = b"matching Standalone MM" * 100
        self.tee = b"TEE header" + zlib.compress(self.mm) + b"TEE suffix"
        self.tos = b"ATF header" + self.tee + b"TOS suffix"
        self.write(self.source / self.data["TOSIMG"], self.tos)
        self.write(self.source / "tegra234-optee.dtb", b"OP-TEE device tree")
        self.write(self.staging / "trusted-os/tee-raw.bin", self.tee)
        self.write(self.staging / "trusted-os/bl31.bin", b"matched monitor")
        self.write(self.staging / "edk2-nvidia/standalone_mm_optee.bin", self.mm)

    def test_gate_is_off_by_default_and_has_no_writes(self):
        self.data.pop("EDGE_AI_SDK_EXPORTS")
        self.export(self.data)
        self.assertFalse(self.deploy.exists())
        self.data["EDGE_AI_SDK_EXPORTS"] = "0"
        self.export(self.data)
        self.assertFalse(self.deploy.exists())

    def test_general_exports_signed_launcher_configs_and_complete_notices(self):
        manifest = self.run_export()
        self.assertEqual((self.output() / "BOOTAA64.efi").read_bytes(), b"MZsigned launcher")
        self.assertEqual((self.output() / "uefi.bin").read_bytes(), b"raw general UEFI")
        self.assertEqual((self.output() / "licenses/00-License.txt").read_bytes(),
                         self.license.read_bytes())
        self.assertTrue((self.output() / "general.cfg").is_file())
        self.assertTrue((self.output() / "L4TConfiguration-RootfsRedundancyLevelABEnable.dtbo").is_file())
        self.assertEqual(manifest["logo_style"], "clab-logo")
        self.assertEqual(manifest["multiconfig"], self.data["BB_CURRENT_MC"])
        self.assertEqual(manifest["source_revisions"]["SRCREV_edk2"], "1" * 40)

    def test_each_logo_style_is_recorded_without_override_guessing(self):
        for style, expected in (("nvidia", "nvidia-logo"), ("none", "no-logo")):
            self.data["EDGE_AI_UEFI_LOGO_STYLE"] = style
            self.assertEqual(self.run_export()["logo_style"], expected)

    def test_minimal_rcm_does_not_export_general_or_launcher(self):
        self.setup_rcm()
        manifest = self.run_export()
        self.assertEqual(manifest["role"], "rcm")
        self.assertEqual((self.output() / "uefi-rcm.bin").read_bytes(), b"minimal recovery only")
        self.assertFalse((self.output() / "uefi.bin").exists())
        self.assertFalse((self.output() / "BOOTAA64.efi").exists())
        self.assertIn("CONFIG_BUILD_MINIMAL=y", (self.output() / "minimal.cfg").read_text())

    def test_standalone_mm_exports_dsc_not_a_fabricated_kconfig(self):
        self.setup_mm()
        manifest = self.run_export()
        self.assertEqual(manifest["edk2"]["configuration_kind"], "DSC, not generated Kconfig")
        self.assertTrue((self.output() / "standalone_mm_optee.bin").is_file())
        self.assertIn("Original NVIDIA copyright", (self.output() / "StandaloneMmOptee.dsc").read_text())
        self.assertEqual(manifest["edk2"]["debug_print_error_level"], "0x80000002")

    def test_tos_proves_matched_tee_and_compressed_mm(self):
        self.setup_tos()
        proof = self.run_export()["matched_trusted_os"]
        self.assertEqual(proof["tee_raw_sha256"], hashlib.sha256(self.tee).hexdigest())
        self.assertEqual(proof["standalone_mm_sha256"], hashlib.sha256(self.mm).hexdigest())
        self.assertEqual(proof["tos_tee_offset"], len(b"ATF header"))
        self.assertEqual(proof["tee_stmm_zlib_offset"], len(b"TEE header"))
        self.assertEqual((self.output() / "tos.img").read_bytes(), self.tos)
        self.assertFalse((self.output() / "tee-raw.bin").exists())

    def test_tos_refuses_unmatched_tee(self):
        self.setup_tos()
        self.write(self.staging / "trusted-os/tee-raw.bin", b"different TEE")
        with self.assertRaisesRegex(ExportFailure, "staged OP-TEE"):
            self.export(self.data)
        self.assertFalse(self.deploy.exists())

    def test_tos_refuses_unmatched_mm(self):
        self.setup_tos()
        self.write(self.staging / "edk2-nvidia/standalone_mm_optee.bin", b"different MM")
        with self.assertRaisesRegex(ExportFailure, "staged Standalone MM"):
            self.export(self.data)
        self.assertFalse(self.deploy.exists())

    def test_missing_required_input_fails_before_writing_exports(self):
        (self.build / "images/BOOTAA64.efi").unlink()
        with self.assertRaisesRegex(ExportFailure, "missing/empty"):
            self.export(self.data)
        self.assertFalse(self.deploy.exists())

    def test_missing_license_fails_before_writing_exports(self):
        self.license.unlink()
        with self.assertRaisesRegex(ExportFailure, "missing/empty"):
            self.export(self.data)
        self.assertFalse(self.deploy.exists())

    def test_required_normal_and_rcm_configuration_are_not_optional(self):
        (self.build / "images/L4TConfiguration-rcmboot.dtbo").unlink()
        with self.assertRaisesRegex(ExportFailure, "missing/empty"):
            self.export(self.data)

    def test_unsupported_platform_and_style_fail_closed(self):
        self.data["SOC_FAMILY"] = "tegra264"
        with self.assertRaisesRegex(ExportFailure, "Tegra234"):
            self.export(self.data)
        self.data["SOC_FAMILY"] = "tegra234"
        self.data["EDGE_AI_UEFI_LOGO_STYLE"] = "custom"
        with self.assertRaisesRegex(ExportFailure, "logo style"):
            self.export(self.data)

    def test_manifest_and_checksums_are_deterministic(self):
        self.run_export()
        before = {str(p.relative_to(self.output())): p.read_bytes()
                  for p in self.output().rglob("*") if p.is_file()}
        self.run_export()
        after = {str(p.relative_to(self.output())): p.read_bytes()
                 for p in self.output().rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_all_appends_use_same_gated_deploy_hook(self):
        recipes = {
            DIRECTORY / "edk2-firmware-tegra_%.bbappend": "general",
            DIRECTORY / "edk2-firmware-tegra-rcmboot_%.bbappend": "rcm",
            DIRECTORY / "edk2-nvidia-standalone-mm_%.bbappend": "standalone-mm",
            LAYER / "recipes-security/optee/tos-optee_%.bbappend": "tos",
        }
        for path, role in recipes.items():
            with self.subTest(recipe=path.name):
                text = path.read_text()
                self.assertIn('EDGE_AI_SDK_FIRMWARE_ROLE = "%s"' % role, text)
                self.assertIn("require recipes-bsp/uefi/edge-ai-sdk-firmware-export.inc", text)
        text = INCLUDE.read_text()
        self.assertIn('EDGE_AI_SDK_EXPORTS ?= "0"', text)
        self.assertIn('do_deploy[postfuncs] += "edge_ai_sdk_export_firmware"', text)
        self.assertNotIn('d.getVar("DEPLOY_DIR_IMAGE")', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

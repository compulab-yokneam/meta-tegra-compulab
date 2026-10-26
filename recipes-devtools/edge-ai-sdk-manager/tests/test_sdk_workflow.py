#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
"""Unprivileged workflow fixtures; never run SDK Manager, sudo or chroot."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

DIRECTORY = Path(__file__).resolve().parents[1]
FILES = DIRECTORY / "files"


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BUILD = load("edge_ai_build_sdk", FILES / "build-sdk.py")
ASSEMBLE = load("edge_ai_assemble_sdk", FILES / "assemble-sdk.py")
KERNEL = load("edge_ai_install_kernel", FILES / "sdk-source/compulab/tools/install-kernel.py")
ROLES = {"edk2-firmware-tegra": "general",
         "edk2-firmware-tegra-rcmboot": "rcm",
         "edk2-nvidia-standalone-mm": "standalone-mm", "tos-optee": "tos"}
PAYLOADS = {
    "general": ("uefi.bin", "BOOTAA64.efi", "general.cfg", "fmp-image-type-id.txt",
                "L4TConfiguration.dtbo", "L4TConfiguration-rcmboot.dtbo"),
    "rcm": ("uefi-rcm.bin", "minimal.cfg"),
    "standalone-mm": ("standalone_mm_optee.bin", "StandaloneMmOptee.dsc"),
    "tos": ("tos.img", "tegra234-optee.dtb"),
}


class SDKWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edge-ai-sdk-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {key: str(self.root / key) for key in
                       ("output", "download", "work", "sources", "assets", "deploy")}
        for key in ("work", "sources", "assets", "deploy"):
            Path(self.config[key]).mkdir()
        self.config["timeout"] = 1
        items = []
        for machine in BUILD.MACHINES:
            for style in BUILD.STYLES:
                prefix = "edge-ai-uefi" if machine == "edge-ai-nx-16g" else \
                    "edge-ai-uefi-" + machine.removeprefix("edge-ai-")
                mc = prefix + "-" + style
                items.append(dict(machine=machine, style=style, mc=mc,
                                  deploy=str(self.root / "mc" / mc)))
        self.config["firmware"] = items

    def write(self, path, data=b"fixture"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def fingerprint_inputs(self):
        for key in ("sources", "assets"):
            self.write(Path(self.config[key]) / "fixture.txt")
        deploy = Path(self.config["deploy"])
        for name in ("kernel", "nvidia-kernel-oot", "kernel-devsrc"):
            for suffix in (".tar.xz", ".json"):
                self.write(deploy / "edge-ai-sdk" / (name + suffix))
        self.write(deploy / "devicetree/camera.dtbo")
        self.write(deploy / "edge-ai-uefi-update-capsules/update.cap")
        for item in self.config["firmware"]:
            self.write(Path(item["deploy"]) / "edge-ai-sdk/firmware/fixture.txt")

    def firmware_export(self, recipe, item=None):
        item = item or self.config["firmware"][0]
        role = ROLES[recipe]
        directory = Path(item["deploy"]) / "edge-ai-sdk/firmware" / recipe
        entries = []
        for name in (*PAYLOADS[role], "licenses/00-License.txt"):
            payload = (item["machine"] + " " + role + " " + name).encode()
            self.write(directory / name, payload)
            entries.append(dict(path=name, sha256=hashlib.sha256(payload).hexdigest(),
                                size=len(payload), origin="build/" + name))
        manifest = dict(schema=1, recipe=recipe, role=role,
                        machine=item["machine"], multiconfig=item["mc"],
                        l4t_version="39.2.1", version="39.2.1", files=entries)
        if role == "general":
            manifest["logo_style"] = item["style"]
        if role == "tos":
            mm = Path(item["deploy"]) / "edge-ai-sdk/firmware/edk2-nvidia-standalone-mm/standalone_mm_optee.bin"
            manifest["matched_trusted_os"] = dict(standalone_mm_sha256=ASSEMBLE.digest(mm))
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return directory, manifest

    def update_manifest(self, directory, manifest):
        (directory / "manifest.json").write_text(json.dumps(manifest))

    def test_response_has_no_host_flash_postflash_or_credentials(self):
        text = BUILD.response(self.config)
        self.assertIn("host = false\nflash = false\n", text)
        self.assertIn("install-method = direct_flash", text)
        self.assertIn("post-flash = skip", text)
        self.assertIn("select[] = Jetson Linux Image", text)
        self.assertNotIn("sudo-password", text)
        self.assertNotIn("password =", text)

    def test_response_rejects_ini_shell_and_nonscalar_injection(self):
        for value in ("/tmp/value\nflash = true", "/tmp/value;touch-bad",
                      "/tmp/with space", "/tmp/value$(id)", ["/tmp/value"]):
            with self.subTest(value=value):
                self.config["output"] = value
                with self.assertRaises(RuntimeError):
                    BUILD.response(self.config)

    def test_strict_twelve_unique_machine_style_multiconfig_matrix(self):
        self.assertEqual(len(BUILD.validate_firmware_inputs(self.config)), 12)
        original = self.config["firmware"][0].copy()
        self.config["firmware"][0] = self.config["firmware"][1].copy()
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            BUILD.validate_firmware_inputs(self.config)
        self.config["firmware"][0] = original
        self.config["firmware"][0]["mc"] = "edge-ai-uefi-nano-4g-no-logo"
        with self.assertRaisesRegex(RuntimeError, "multiconfig"):
            BUILD.validate_firmware_inputs(self.config)

    def test_firmware_selection_values_are_scalar_and_deploy_paths_distinct(self):
        first = self.config["firmware"][0]
        first["style"] = [first["style"]]
        with self.assertRaisesRegex(RuntimeError, "scalar"):
            BUILD.validate_firmware_inputs(self.config)
        first["style"] = BUILD.STYLES[0]
        first["deploy"] = self.config["firmware"][1]["deploy"]
        with self.assertRaisesRegex(RuntimeError, "deploy directory"):
            BUILD.validate_firmware_inputs(self.config)

    def test_fingerprint_ignores_generated_python_caches_everywhere(self):
        self.fingerprint_inputs()
        before = BUILD.inputs(self.config)
        for root in (Path(self.config["sources"]), Path(self.config["assets"]),
                     Path(self.config["firmware"][0]["deploy"]) / "edge-ai-sdk/firmware"):
            self.write(root / "__pycache__/generated.cpython-312.pyc", b"volatile")
            self.write(root / "generated.pyc", b"volatile")
        self.assertEqual(BUILD.inputs(self.config), before)
        self.write(Path(self.config["sources"]) / "fixture.txt", b"real source edit")
        self.assertNotEqual(BUILD.inputs(self.config), before)

    def test_debian_package_version_changes_sdk_input_fingerprint(self):
        self.fingerprint_inputs()
        before = BUILD.inputs(self.config)
        self.config["deb_version"] = "39.2.1+compulab2"
        self.assertNotEqual(BUILD.inputs(self.config), before)
        self.config["deb_version"] = "39.2.1\nInjected: field"
        with self.assertRaises(RuntimeError):
            BUILD.inputs(self.config)

    def test_private_log_is_not_echoed_to_task_output(self):
        with mock.patch("builtins.print") as output:
            BUILD.private_run([sys.executable, "-c", "print('PRIVATE-TEST-TEXT')"],
                              Path(self.config["work"]), "fixture", 5)
        self.assertNotIn("PRIVATE-TEST-TEXT", repr(output.call_args_list))
        log = next(Path(self.config["work"]).glob("fixture-*.log"))
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        self.assertIn("PRIVATE-TEST-TEXT", log.read_text())

    def test_timeout_stops_descendant_even_after_it_changes_session(self):
        pidfile = self.root / "descendant.pid"
        code = ("import pathlib,subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
                "start_new_session=True); "
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)")
        # Never execute privileged cleanup in a test. Its unprivileged fallback
        # can signal all fixture processes; assert sudo remains only a request.
        def fake_cleanup(command, **kwargs):
            self.assertEqual(command[:3], ["sudo", "-n", "/bin/kill"])
            return subprocess.CompletedProcess(command, 1)
        pid = None
        try:
            with mock.patch.object(BUILD.subprocess, "run", side_effect=fake_cleanup):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    BUILD.private_run([sys.executable, "-c", code, str(pidfile)],
                                      Path(self.config["work"]), "timeout", 1)
            pid = int(pidfile.read_text())
            self.assertNotIn(pid, BUILD.process_snapshot())
        finally:
            if pid is None and pidfile.exists():
                pid = int(pidfile.read_text())
            if pid is not None and pid in BUILD.process_snapshot():
                os.kill(pid, signal.SIGKILL)

    def test_firmware_export_checks_required_payload_hashes(self):
        directory, _ = self.firmware_export("edk2-firmware-tegra")
        ASSEMBLE.checked_firmware_export(directory, "edk2-firmware-tegra",
                                         self.config["firmware"][0])
        self.write(directory / "BOOTAA64.efi", b"modified")
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            ASSEMBLE.checked_firmware_export(directory, "edk2-firmware-tegra",
                                             self.config["firmware"][0])

    def test_success_does_not_publish_while_known_descendants_are_live(self):
        pidfile = self.root / "background.pid"
        code = ("import pathlib,subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
                "start_new_session=True); "
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(0.7)")
        with mock.patch.object(BUILD.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 1)) as privileged:
            with self.assertRaisesRegex(RuntimeError, "live descendants"):
                BUILD.private_run([sys.executable, "-c", code, str(pidfile)],
                                  Path(self.config["work"]), "background", 5)
        self.assertTrue(privileged.called)
        self.assertNotIn(int(pidfile.read_text()), BUILD.process_snapshot())

    def test_unlisted_required_firmware_payload_is_rejected(self):
        directory, manifest = self.firmware_export("edk2-firmware-tegra")
        manifest["files"] = [entry for entry in manifest["files"] if entry["path"] != "uefi.bin"]
        self.update_manifest(directory, manifest)
        with self.assertRaises(RuntimeError):
            ASSEMBLE.checked_firmware_export(directory, "edk2-firmware-tegra",
                                             self.config["firmware"][0])

    def test_firmware_export_rejects_duplicate_paths_and_wrong_mc_role(self):
        directory, manifest = self.firmware_export("edk2-firmware-tegra")
        manifest["files"].append(manifest["files"][0].copy())
        self.update_manifest(directory, manifest)
        with self.assertRaises(RuntimeError):
            ASSEMBLE.checked_firmware_export(directory, "edk2-firmware-tegra",
                                             self.config["firmware"][0])
        manifest["files"].pop()
        for key, value in (("multiconfig", "different-mc"), ("role", "rcm")):
            original = manifest[key]
            manifest[key] = value
            self.update_manifest(directory, manifest)
            with self.assertRaises(RuntimeError):
                ASSEMBLE.checked_firmware_export(directory, "edk2-firmware-tegra",
                                                 self.config["firmware"][0])
            manifest[key] = original

    def test_firmware_export_rejects_payload_symlink(self):
        directory, _ = self.firmware_export("edk2-firmware-tegra")
        candidate = directory / "uefi.bin"
        data = candidate.read_bytes()
        candidate.unlink()
        self.write(self.root / "outside.bin", data)
        candidate.symlink_to(self.root / "outside.bin")
        with self.assertRaises(RuntimeError):
            ASSEMBLE.checked_firmware_export(directory, "edk2-firmware-tegra",
                                             self.config["firmware"][0])

    def module_tree(self, base_names, oot_names, replacements):
        base, oot = self.root / "base", self.root / "oot"
        for relative in base_names:
            self.write(base / "usr/lib/modules" / ASSEMBLE.RELEASE / relative)
        for relative in oot_names:
            self.write(oot / "usr/lib/modules" / ASSEMBLE.RELEASE / relative)
        self.write(oot / "metadata/replacement-drivers.txt", replacements.encode())
        return base, oot

    def test_logical_oot_replacement_removes_same_canonical_base_provider(self):
        base, oot = self.module_tree(["kernel/gpu/tegra-drm.ko", "kernel/host1x/host1x.ko"],
                                     ["updates/gpu/tegra_drm.ko"], "tegra-drm\nhost1x\n")
        ASSEMBLE.merge_modules(base, oot)
        modules = base / "usr/lib/modules" / ASSEMBLE.RELEASE
        self.assertFalse((modules / "kernel/gpu/tegra-drm.ko").exists())
        self.assertTrue((modules / "updates/gpu/tegra_drm.ko").is_file())
        self.assertTrue((modules / "kernel/host1x/host1x.ko").is_file())

    def test_logical_policy_does_not_remove_unrelated_base_modules(self):
        base, oot = self.module_tree(["kernel/host1x/host1x.ko", "kernel/gpu/tegra-drm.ko"],
                                     ["updates/gpu/nvidia-drm.ko"], "host1x\ntegra-drm\n")
        ASSEMBLE.merge_modules(base, oot)
        modules = base / "usr/lib/modules" / ASSEMBLE.RELEASE
        self.assertTrue((modules / "kernel/host1x/host1x.ko").is_file())
        self.assertTrue((modules / "kernel/gpu/tegra-drm.ko").is_file())

    def test_module_abi_check_rejects_wrong_vermagic_and_architecture(self):
        module = self.root / "driver.ko"
        data = bytearray(32)
        data[:4], data[18:20] = b"\x7fELF", b"\xb7\x00"
        module.write_bytes(data + b"\0vermagic=" + KERNEL.EXPECTED_RELEASE.encode() + b" SMP\0")
        KERNEL.check_module(module)
        module.write_bytes(data + b"\0vermagic=wrong-release SMP\0")
        with self.assertRaisesRegex(RuntimeError, "ABI"):
            KERNEL.check_module(module)
        data[18:20] = b"\x3e\x00"
        module.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, "aarch64"):
            KERNEL.check_module(module)

    def test_initrd_uses_oot_provider_and_preserves_vendor_nonmodule_inputs(self):
        modules = self.root / "modules"
        lines = ["kernel/nvme.ko:", "kernel/nvethernet.ko:",
                 "updates/nvethernet.ko: kernel/nvme.ko"]
        self.write(modules / "modules.dep", ("\n".join(lines) + "\n").encode())
        self.write(modules / "modules.builtin", ("\n".join(
            "kernel/" + name + ".ko" for name in
            ("nvme-core", "pcie-tegra194", "phy-tegra194-p2u", "tegra-xudc", "ext4")) + "\n").encode())
        for name in ("kernel/nvme.ko", "kernel/nvethernet.ko", "updates/nvethernet.ko"):
            self.write(modules / name)
        lists = self.root / "sdk/rootfs/etc/nv-update-initrd/list.d"
        self.write(lists / "modules_k6.8", b"/lib/modules/<KERNEL_VERSION>/nvethernet.ko:/target\n")
        self.write(lists / "common", b"/etc/.disable_initrd_bash:/etc/.disable_initrd_bash\n")
        KERNEL.prepare_initrd_list(self.root / "sdk", modules)
        output = (lists / "modules.override").read_text()
        self.assertIn("updates/nvethernet.ko", output)
        self.assertNotIn("kernel/nvethernet.ko", output)
        self.assertIn(".disable_initrd_bash", output)
        self.assertIn("kernel/nvme.ko", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)

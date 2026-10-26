#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
"""Test the installed Ubuntu boot menu and selector using temporary fixtures.

Only the helper's root-ID check is mocked. Every edit occurs in a host /tmp
fixture, never in the SDK boot configuration. No flash script is executed.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


SDK = Path(__file__).resolve().parents[2]
SOURCE = SDK / "compulab/rootfs"
HELPER = SOURCE / "usr/sbin/edge-ai-select-fdt"
SAMPLE = SOURCE / "boot/extlinux/extlinux.conf.imx67x.sample"
MENU = SAMPLE.read_text()


def parse_menu(text):
    global_ = {}
    entries = {}
    current = global_
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split(None, 1)
        if key == "LABEL":
            if value in entries:
                raise AssertionError("duplicate label: " + value)
            current = entries[value] = {}
        else:
            current.setdefault(key, []).append(value)
    return global_, entries


class InstalledMenuTests(unittest.TestCase):
    def test_original_primary_and_default_remain_ubuntu(self):
        globals_, entries = parse_menu(MENU)
        self.assertEqual(globals_["DEFAULT"], ["primary"])
        self.assertEqual(globals_["TIMEOUT"], ["30"])
        self.assertEqual(entries["primary"], {
            "MENU": ["LABEL primary kernel"], "LINUX": ["/boot/Image"],
            "INITRD": ["/boot/initrd"], "APPEND": ["${cbootargs}"],
        })

    def test_expected_labels_are_unique(self):
        _, entries = parse_menu(MENU)
        self.assertEqual(list(entries), [
            "primary", "camera-imx676", "camera-imx678", "camera-mixed",
            "camera-uefi", "nvidia-stock-nx-16g", "nvidia-stock-nx-8g",
            "nvidia-stock-nano-8g", "nvidia-stock-nano-4g",
        ])

    def test_camera_entries_are_nx16_only_and_uefi_fallback_has_no_explicit_tree(self):
        _, entries = parse_menu(MENU)
        for label in ("camera-imx676", "camera-imx678", "camera-mixed"):
            self.assertIn("NX16G only", entries[label]["MENU"][0])
            self.assertEqual(entries[label]["LINUX"], ["/boot/Image"])
            self.assertEqual(entries[label]["INITRD"], ["/boot/initrd"])
        self.assertNotIn("FDT", entries["camera-uefi"])
        self.assertNotIn("OVERLAYS", entries["camera-uefi"])
        self.assertIn("experimental", entries["camera-mixed"]["MENU"][0])

    def test_every_boot_argument_is_inherited_not_yocto_rootfs(self):
        _, entries = parse_menu(MENU)
        for entry in entries.values():
            self.assertEqual(entry["APPEND"], ["${cbootargs}"])
        self.assertNotIn("root=/dev/", MENU)
        self.assertNotIn("root=PARTUUID=", MENU)

    def test_mixed_transport_precedes_one_model_per_port(self):
        _, entries = parse_menu(MENU)
        self.assertEqual(entries["camera-mixed"]["OVERLAYS"][0].split(","), [
            "/boot/devicetree/edgedes-adi-v18-transport-4port.dtbo",
            "/boot/devicetree/edgedes-adi-v18-camera-imx676-port0.dtbo",
            "/boot/devicetree/edgedes-adi-v18-camera-imx678-port1.dtbo",
        ])

    def test_all_installed_kernel_initrd_and_tree_paths_exist(self):
        _, entries = parse_menu(MENU)
        for label, entry in entries.items():
            paths = entry["LINUX"] + entry["INITRD"] + entry.get("FDT", [])
            if "OVERLAYS" in entry:
                paths += entry["OVERLAYS"][0].split(",")
            for path in paths:
                with self.subTest(label=label, path=path):
                    self.assertTrue((SDK / "rootfs" / path.lstrip("/")).is_file())

    def test_stock_fallbacks_have_original_matching_trees(self):
        _, entries = parse_menu(MENU)
        for label, sku in (("nvidia-stock-nx-16g", "0000"),
                           ("nvidia-stock-nx-8g", "0001"),
                           ("nvidia-stock-nano-8g", "0003"),
                           ("nvidia-stock-nano-4g", "0004")):
            entry = entries[label]
            self.assertEqual(entry["LINUX"], ["/boot/Image.nvidia-stock"])
            self.assertEqual(entry["INITRD"], ["/boot/initrd.nvidia-stock"])
            self.assertEqual(entry["FDT"], [
                "/boot/dtb/nvidia-stock-tegra234-p3768-0000+p3767-%s-nv-super.dtb" % sku,
            ])
            self.assertNotIn("OVERLAYS", entry)
        self.assertTrue((SDK / "rootfs/lib/modules/6.8.12-1021-tegra").is_dir())

    def test_nano_keeps_module_selected_primary_without_nx_camera_defaults(self):
        global_, entries = parse_menu(MENU)
        self.assertEqual(global_["DEFAULT"], ["primary"])
        self.assertNotIn("FDT", entries["primary"])
        self.assertNotIn("OVERLAYS", entries["primary"])
        for label in ("nvidia-stock-nano-8g", "nvidia-stock-nano-4g"):
            self.assertIn("Nano", entries[label]["MENU"][0])
        self.assertIn("or Nano", MENU)

    def test_installed_helper_active_menu_and_sample_match_sources(self):
        self.assertEqual((SDK / "rootfs/usr/sbin/edge-ai-select-fdt").read_bytes(),
                         HELPER.read_bytes())
        self.assertEqual((SDK / "rootfs/boot/extlinux/extlinux.conf").read_bytes(),
                         SAMPLE.read_bytes())
        self.assertEqual((SDK / "rootfs/boot/extlinux/extlinux.conf.imx67x.sample").read_bytes(),
                         SAMPLE.read_bytes())


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="edge-ai-fdt-test.")
        self.root = Path(self.tmp.name)
        self.conf = self.root / "boot/extlinux/extlinux.conf"
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text(MENU)
        self.dtb = self.root / "dtb"
        self.dtb.mkdir()
        for name in ("a.dtb", "b.dtb"):
            (self.dtb / name).write_bytes(b"temporary unit-test DTB name fixture")
        mockbin = self.root / "mockbin"
        mockbin.mkdir()
        (mockbin / "id").write_text("#!/bin/sh\nprintf '0\\n'\n")
        (mockbin / "id").chmod(0o755)
        self.env = dict(os.environ, EDGE_AI_DTB_DIR=str(self.dtb),
                        EDGE_AI_EXTLINUX_CONF=str(self.conf),
                        PATH=str(mockbin) + os.pathsep + os.environ["PATH"])

    def tearDown(self):
        self.tmp.cleanup()

    def run_helper(self, *args, input=None, success=True):
        result = subprocess.run(["dash", str(HELPER), *args], env=self.env,
                                text=True, input=input, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_dash_syntax_and_help(self):
        subprocess.run(["dash", "-n", str(HELPER)], check=True)
        self.assertIn("default entry is primary", self.run_helper("--help").stdout)
        self.assertEqual(self.conf.read_text(), MENU)

    def test_list_and_show_are_read_only(self):
        self.assertEqual(self.run_helper("--list").stdout.splitlines(), ["a.dtb", "b.dtb"])
        self.assertIn("FDT (primary): UEFI-provided", self.run_helper("--show").stdout)
        self.assertNotIn("camera-imx676", self.run_helper("--show").stdout)
        self.assertIn("camera-mixed", self.run_helper("--all", "--show").stdout)
        self.assertEqual(self.conf.read_text(), MENU)

    def test_default_selection_changes_only_primary(self):
        _, before = parse_menu(MENU)
        self.run_helper("a.dtb")
        _, after = parse_menu(self.conf.read_text())
        self.assertEqual(after["primary"]["FDT"], ["/boot/dtb/a.dtb"])
        self.assertEqual(after["primary"]["APPEND"], ["${cbootargs}"])
        for label in before:
            if label != "primary":
                self.assertEqual(after[label], before[label])
        self.assertEqual(Path(str(self.conf) + ".bak").read_text(), MENU)
        self.assertEqual(self.conf.stat().st_size % 16, 0)

    def test_uefi_clears_only_the_selected_entry(self):
        self.run_helper("a.dtb")
        self.run_helper("--uefi")
        _, entries = parse_menu(self.conf.read_text())
        self.assertNotIn("FDT", entries["primary"])
        self.assertIn("OVERLAYS", entries["camera-mixed"])
        self.assertIn("FDT", entries["nvidia-stock-nx-8g"])

    def test_explicit_entry_clears_incompatible_overlays_only_there(self):
        _, before = parse_menu(MENU)
        self.run_helper("--entry", "camera-mixed", "b.dtb")
        _, after = parse_menu(self.conf.read_text())
        self.assertEqual(after["camera-mixed"]["FDT"], ["/boot/dtb/b.dtb"])
        self.assertNotIn("OVERLAYS", after["camera-mixed"])
        for label in before:
            if label != "camera-mixed":
                self.assertEqual(after[label], before[label])

    def test_explicit_all_preserves_original_all_entry_capability(self):
        result = self.run_helper("--all", "a.dtb")
        self.assertIn("stock-kernel fallbacks", result.stderr)
        _, entries = parse_menu(self.conf.read_text())
        for entry in entries.values():
            self.assertEqual(entry["FDT"], ["/boot/dtb/a.dtb"])
            self.assertNotIn("OVERLAYS", entry)

    def test_interactive_selection_defaults_to_primary(self):
        self.run_helper(input="2\n")
        _, entries = parse_menu(self.conf.read_text())
        self.assertEqual(entries["primary"]["FDT"], ["/boot/dtb/b.dtb"])
        self.assertNotIn("FDT", entries["camera-uefi"])

    def test_invalid_inputs_leave_configuration_unchanged(self):
        for args in (("../a.dtb",), ("missing.dtb",), ("--entry", "missing", "a.dtb"),
                     ("--entry", "../primary", "a.dtb"), ("a.dtb", "b.dtb"),
                     ("--all", "--entry", "primary", "a.dtb"), ("--unknown",)):
            with self.subTest(args=args):
                self.run_helper(*args, success=False)
                self.assertEqual(self.conf.read_text(), MENU)

    def test_backup_is_not_overwritten_on_later_selections(self):
        self.run_helper("a.dtb")
        self.run_helper("b.dtb")
        self.assertEqual(Path(str(self.conf) + ".bak").read_text(), MENU)

    def test_existing_signature_emits_resigning_warning(self):
        Path(str(self.conf) + ".sig").write_bytes(b"unit-test signature marker")
        result = self.run_helper("a.dtb")
        self.assertIn("not regenerated", result.stderr)

    def test_native_flash_append_fragment_preserves_all_profiles(self):
        # Execute only the reviewed text-editing fragment, not build_fsimg or
        # any flash/mount/USB code. It operates on this temporary fixture.
        source = (SDK / "flash.sh").read_text()
        begin = source.index('\t\t# Populate extlinux.conf if "$cmdline" exists')
        boundary = re.search(r'^\t\tif \[ "\$\{__do_sign\}" =+ "True" \]; then',
                             source[begin:], re.MULTILINE)
        self.assertIsNotNone(boundary)
        end = begin + boundary.start()
        fragment = source[begin:end]
        self.assertIn('sed -i "/^[ \\t]*APPEND/s|\\$| ${__cmdline}|"', fragment)
        self.assertNotRegex(fragment, r"\b(?:mount|losetup|tegrarcm)\b")
        command = ("__cmdline='root=PARTUUID=unit-test-uuid rw'; "
                   "_extlinux_conf=extlinux/extlinux.conf; "
                   "chkerr() { return 0; };\n" + fragment)
        subprocess.run(["bash", "-c", command], cwd=self.root,
                       check=True, text=True, capture_output=True)
        globals_, entries = parse_menu(self.conf.read_text())
        _, before = parse_menu(MENU)
        self.assertEqual(globals_["DEFAULT"], ["primary"])
        self.assertEqual(set(entries), set(before))
        for label in entries:
            expected = dict(before[label])
            expected["APPEND"] = ["${cbootargs} root=PARTUUID=unit-test-uuid rw"]
            self.assertEqual(entries[label], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)

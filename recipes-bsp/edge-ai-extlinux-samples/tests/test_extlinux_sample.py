#!/usr/bin/env python3
"""Check the inactive camera example without building an image.

Run: python3 -B recipes-bsp/edge-ai-extlinux-samples/tests/test_extlinux_sample.py
"""

from pathlib import Path
import re
import unittest


RECIPE_DIR = Path(__file__).resolve().parents[1]
LAYER_DIR = RECIPE_DIR.parents[1]
SAMPLE = (RECIPE_DIR / "files/extlinux.conf.imx67x.sample").read_text()
RECIPE = (RECIPE_DIR / "edge-ai-extlinux-samples_1.0.bb").read_text()
DT_RECIPE = (
    LAYER_DIR / "recipes-kernel/nvidia-kernel-oot/edgedes-adi-v18-devicetree.bb"
).read_text()


def parse_sample(text):
    """Read directives, retaining duplicates so they cannot pass unnoticed."""
    globals_ = {}
    entries = {}
    current = globals_
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split(None, 1)
        if key == "LABEL":
            if value in entries:
                raise ValueError("Duplicate boot label: " + value)
            current = entries[value] = {}
        else:
            current.setdefault(key, []).append(value)
    return globals_, entries


class ExtlinuxSampleTests(unittest.TestCase):
    def setUp(self):
        self.globals, self.entries = parse_sample(SAMPLE)

    def test_primary_remains_default_and_all_labels_are_unique(self):
        self.assertEqual(self.globals["DEFAULT"], ["primary"])
        self.assertEqual(self.globals["TIMEOUT"], ["10"])
        self.assertEqual(list(self.entries), [
            "primary", "imx676", "imx678", "imx676-extended", "imx678-extended",
        ])

    def test_each_camera_entry_is_complete(self):
        for label, entry in self.entries.items():
            if label == "primary":
                continue
            with self.subTest(label=label):
                self.assertEqual(set(entry), {
                    "MENU", "LINUX", "FDT", "OVERLAYS", "INITRD", "APPEND",
                })
                self.assertTrue(all(len(values) == 1 for values in entry.values()))
                self.assertEqual(entry["LINUX"], ["/boot/Image"])
                self.assertEqual(entry["INITRD"], ["/boot/initrd"])
                self.assertEqual(entry["FDT"], [
                    "/boot/dtb/tegra234-edge-ai-adi-base.dtb",
                ])

    def test_transport_precedes_each_unique_physical_port(self):
        for sensor in ("imx676", "imx678"):
            expected = ["/boot/devicetree/edgedes-adi-v18-transport-4port.dtbo"]
            expected.extend(
                "/boot/devicetree/edgedes-adi-v18-camera-%s-port%d.dtbo" %
                (sensor, port) for port in range(4)
            )
            for label in (sensor, sensor + "-extended"):
                with self.subTest(label=label):
                    self.assertEqual(self.entries[label]["OVERLAYS"][0].split(","),
                                     expected)

    def test_all_camera_device_trees_are_real_recipe_outputs(self):
        dt_files = re.search(r'\nDT_FILES = "(.*?)"', DT_RECIPE, re.DOTALL).group(1)
        outputs = {
            Path(name).with_suffix(".dtbo" if name.endswith(".dtso") else ".dtb")
            .name for name in dt_files.replace("\\", " ").split()
        }
        for label, entry in self.entries.items():
            if label == "primary":
                continue
            paths = entry["FDT"] + entry["OVERLAYS"][0].split(",")
            for path in paths:
                with self.subTest(label=label, path=path):
                    self.assertIn(Path(path).name, outputs)
                    self.assertNotIn("-extended-port", path)

    def test_aliases_use_the_same_built_camera_table_and_boot_arguments(self):
        for sensor in ("imx676", "imx678"):
            native_label = dict(self.entries[sensor])
            extended_label = dict(self.entries[sensor + "-extended"])
            native_label.pop("MENU")
            extended_label.pop("MENU")
            self.assertEqual(native_label, extended_label)

    def test_root_device_boot_arguments_are_inherited(self):
        for label, entry in self.entries.items():
            with self.subTest(label=label):
                self.assertTrue(entry["APPEND"][0].startswith("${cbootargs} "))
                self.assertNotRegex(entry["APPEND"][0], r"(?:^|\s)root=")

    def test_extended_requirements_and_mode_selection_are_explained(self):
        self.assertIn('EDGE_AI_IMX676_EXTENDED_MODES = "1" (build default)', SAMPLE)
        self.assertIn('EDGE_AI_IMX678_EXTENDED_MODES = "1" (opt-in)', SAMPLE)
        self.assertIn("not baseline rollback entries", SAMPLE)
        self.assertIn("Boot labels do not enable modes or select a capture rate", SAMPLE)
        self.assertIn("matching driver, DT package and per-mode NITO", SAMPLE)

    def test_recipe_only_installs_the_inactive_sample(self):
        self.assertEqual(re.findall(r"^FILES:\$\{PN\} = \"(.*?)\"", RECIPE,
                                    re.MULTILINE), [
            "/boot/extlinux/extlinux.conf.imx67x.sample",
        ])
        self.assertIn("${D}/boot/extlinux/extlinux.conf.imx67x.sample", RECIPE)
        self.assertNotRegex(RECIPE, r"(?:RDEPENDS|RRECOMMENDS|pkg_postinst)")
        self.assertNotIn("systemctl", RECIPE)


if __name__ == "__main__":
    unittest.main(verbosity=2)

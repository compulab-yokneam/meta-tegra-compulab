#!/usr/bin/env python3
"""Execute the stitched extlinux task, including its real prepend/base/append.

Run: python3 -B recipes-bsp/uefi/tests/test_extlinux_task.py
Requires the project's BitBake and meta-tegra checkouts, but starts no server.
"""

from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest


RECIPE_DIR = Path(__file__).resolve().parents[1]
LAYER_DIR = RECIPE_DIR.parents[1]
APPEND = (RECIPE_DIR / "l4t-launcher-extlinux.bbappend").read_text()
CAMERA_MENU = LAYER_DIR / "conf/include/edge-ai-argus-framos-camera-menu.inc"
CLASS_PATH = LAYER_DIR.parent / "meta-tegra/classes-recipe/l4t-extlinux-config.bbclass"
BB_LIB = LAYER_DIR.parents[1] / "repos/bitbake/lib"


class TaskFailure(RuntimeError):
    pass


def fail(message):
    raise TaskFailure(message)


def python_body(source, declaration):
    return re.search(r"^" + re.escape(declaration) + r" \{\n(.*?)^\}",
                     source, re.MULTILINE | re.DOTALL)[1]


class ExtlinuxTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BB_LIB.is_dir() or not CLASS_PATH.is_file():
            raise unittest.SkipTest("BitBake/meta-tegra checkout unavailable")
        sys.path.insert(0, str(BB_LIB))
        try:
            import bb.data
        finally:
            sys.path.pop(0)
        cls.bb_data = bb.data
        source = CLASS_PATH.read_text()
        namespace = {"bb": SimpleNamespace(data=bb.data, fatal=fail, error=fail,
                                           warn=lambda message: None)}
        helper = re.search(r"^def get_l4t_extlinux_compat_var\(.*?\n"
                           r"(?=python do_create_extlinux_config)", source,
                           re.MULTILINE | re.DOTALL)[0]
        exec(helper, namespace)
        # BitBake concatenates these bodies into one function. A return in the
        # prepend must therefore not bypass base generation or the append.
        parts = [
            python_body(APPEND, "python do_create_extlinux_config:prepend:edge-ai()"),
            python_body(source, "python do_create_extlinux_config()"),
            python_body(APPEND, "python do_create_extlinux_config:append:edge-ai()"),
        ]
        exec("def stitched_task(d):\n" + "\n".join(parts), namespace)
        cls.stitched_task = staticmethod(namespace["stitched_task"])
        body = python_body(CAMERA_MENU.read_text(), "python __anonymous()")
        exec("def camera_menu(d):\n" + body, namespace)
        cls.camera_menu = staticmethod(namespace["camera_menu"])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="edge-ai-extlinux-test-")
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "extlinux.conf"
        self.data = self.bb_data.init()
        for key, value in {
            "MACHINE": "edge-ai-nx-16g",
            "OVERRIDES": "tegra:edge-ai:adi-gmsl-v18:pn-l4t-launcher-extlinux",
            "WORKDIR": self.temporary.name,
            "UBOOT_EXTLINUX": "1",
            "UBOOT_EXTLINUX_CONFIG": str(self.output),
            "UBOOT_EXTLINUX_LABELS": "primary",
            "UBOOT_EXTLINUX_DEFAULT_LABEL": "primary",
            "UBOOT_EXTLINUX_MENU_TITLE": "L4T boot options",
            "UBOOT_EXTLINUX_KERNEL_IMAGE": "/boot/Image",
            "UBOOT_EXTLINUX_KERNEL_ARGS": "console=ttyTCU0,115200 console=tty0",
            "UBOOT_EXTLINUX_INITRD": "/boot/initrd",
            "UBOOT_EXTLINUX_FDT": "",
            "UBOOT_EXTLINUX_FDTOVERLAYS": "",
            "L4T_EXTLINUX_BASEDIR": "/boot",
            "FDT_PER_ENTRY": "0",
            "FDT_FILE": "",
            "FDT_OVERLAYS": "",
            "EDGE_AI_CAMERA_BOOT_DEFAULT": "camera-imx676",
            "EDGE_AI_CAMERA_MIXED_OVERLAYS": (
                "edgedes-adi-v18-transport-4port.dtbo "
                "edgedes-adi-v18-camera-imx676-port0.dtbo "
                "edgedes-adi-v18-camera-imx678-port1.dtbo"),
        }.items():
            self.data.setVar(key, value)

    def generate(self, menu=False):
        if menu:
            self.camera_menu(self.data)
        self.stitched_task(self.data)
        return self.output.read_text()

    def test_per_entry_generation_runs_on_a_clean_work_directory(self):
        text = self.generate(menu=True)
        self.assertIn("DEFAULT camera-imx676\n", text)
        self.assertEqual(re.findall(r"(?m)^LABEL (.+)$", text), [
            "camera-imx676", "camera-imx678", "camera-mixed", "camera-uefi",
        ])
        self.assertIn("FDT /boot/dtb/edgedes-adi-v18-framos-imx676-4port.dtb", text)
        self.assertIn("FDT /boot/dtb/edgedes-adi-v18-framos-imx678-4port.dtb", text)
        mixed = text.split("LABEL camera-mixed\n", 1)[1].split("LABEL camera-uefi", 1)[0]
        self.assertIn("FDT /boot/dtb/tegra234-edge-ai-adi-base.dtb", mixed)
        self.assertIn("OVERLAYS /boot/devicetree/edgedes-adi-v18-transport-4port.dtbo,"
                      "/boot/devicetree/edgedes-adi-v18-camera-imx676-port0.dtbo,"
                      "/boot/devicetree/edgedes-adi-v18-camera-imx678-port1.dtbo", mixed)
        fallback = text.split("LABEL camera-uefi\n", 1)[1]
        self.assertNotRegex(fallback, r"(?m)^\s*(FDT|OVERLAYS) ")
        self.assertEqual(text.count("\tLINUX /boot/Image\n"), 4)
        self.assertEqual(text.count("\tINITRD /boot/initrd\n"), 4)
        self.assertEqual(text.count("\tAPPEND ${cbootargs} "), 4)
        self.assertEqual(len(text.encode()) % 16, 0)

    def test_per_entry_generation_replaces_a_stale_primary_configuration(self):
        self.output.write_text("DEFAULT primary\nLABEL primary\n\tLINUX /boot/old\n")
        text = self.generate(menu=True)
        self.assertIn("DEFAULT camera-imx676\n", text)
        self.assertNotIn("LABEL primary", text)
        self.assertNotIn("/boot/old", text)

    def test_per_entry_prepend_rejects_conflicting_overlay_ownership(self):
        self.camera_menu(self.data)
        self.data.setVar("UBOOT_EXTLINUX_FDTOVERLAYS:camera-mixed", "vendor.dtbo")
        with self.assertRaisesRegex(TaskFailure, "Use either FDT_OVERLAYS"):
            self.stitched_task(self.data)

    def test_per_entry_append_rejects_missing_overlay_base(self):
        self.camera_menu(self.data)
        self.data.setVar("FDT_FILE:camera-mixed", "")
        with self.assertRaisesRegex(TaskFailure, "requires an explicit FDT_FILE"):
            self.stitched_task(self.data)

    def test_global_fdt_fallback_still_generates_primary(self):
        self.data.setVar("FDT_FILE", "tegra234-fallback.dtb")
        text = self.generate()
        self.assertIn("DEFAULT primary\n", text)
        self.assertEqual(re.findall(r"(?m)^LABEL (.+)$", text), ["primary"])
        self.assertIn("\tFDT /boot/dtb/tegra234-fallback.dtb\n", text)
        self.assertNotIn("OVERLAYS", text)

    def test_global_overlay_stack_retains_transport_order(self):
        self.data.setVar("FDT_FILE", "tegra234-edge-ai-adi-base.dtb")
        self.data.setVar("FDT_OVERLAYS", self.data.getVar("EDGE_AI_CAMERA_MIXED_OVERLAYS"))
        text = self.generate()
        expected = ",".join("/boot/devicetree/" + name for name in
                            self.data.getVar("FDT_OVERLAYS").split())
        self.assertIn("\tOVERLAYS " + expected + "\n", text)
        self.assertEqual(len(text.encode()) % 16, 0)

    def test_global_prepend_rejects_conflicting_overlay_ownership(self):
        self.data.setVar("FDT_FILE", "tegra234-edge-ai-adi-base.dtb")
        self.data.setVar("FDT_OVERLAYS", self.data.getVar("EDGE_AI_CAMERA_MIXED_OVERLAYS"))
        self.data.setVar("UBOOT_EXTLINUX_FDTOVERLAYS", "vendor.dtbo")
        with self.assertRaisesRegex(TaskFailure, "Use either FDT_OVERLAYS"):
            self.stitched_task(self.data)

    def test_global_append_rejects_overlays_without_a_base(self):
        self.data.setVar("FDT_OVERLAYS", "camera.dtbo")
        with self.assertRaisesRegex(TaskFailure, "requires an explicit FDT_FILE"):
            self.stitched_task(self.data)

    def test_other_modules_do_not_inherit_the_nx16g_camera_menu(self):
        self.data.setVar("MACHINE", "edge-ai-nx-8g")
        text = self.generate(menu=True)
        self.assertIn("DEFAULT primary\n", text)
        self.assertNotIn("LABEL camera-", text)
        self.assertNotRegex(text, r"(?m)^\s*(FDT|OVERLAYS) ")

    def test_flash_profile_builds_do_not_inherit_the_runtime_camera_menu(self):
        self.data.appendVar("OVERRIDES", ":edge-ai-profile-build")
        text = self.generate(menu=True)
        self.assertIn("DEFAULT primary\n", text)
        self.assertNotIn("LABEL camera-", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

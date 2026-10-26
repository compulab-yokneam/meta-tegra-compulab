#!/usr/bin/env python3
"""Check the Noble provider metadata without running BitBake or a device.

Run: python3 -B recipes-kernel/linux/tests/test_noble_kernel_metadata.py
"""

from pathlib import Path
import re
import sys
import textwrap
from types import SimpleNamespace
import unittest


RECIPE_DIR = Path(__file__).resolve().parents[1]
LAYER_DIR = RECIPE_DIR.parents[1]
APPEND = (RECIPE_DIR / "linux-noble-nvidia-tegra_6.8.bbappend").read_text()
FRAGMENTS = RECIPE_DIR / "files/adi-gmsl-v18-noble"


def config_values(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"(CONFIG_\w+)=(.+)", line)
        if match:
            if match[1] in values:
                raise ValueError("Duplicate config request: " + match[1])
            values[match[1]] = match[2]
        match = re.fullmatch(r"# (CONFIG_\w+) is not set", line)
        if match:
            if match[1] in values:
                raise ValueError("Duplicate config request: " + match[1])
            values[match[1]] = "n"
    return values


def append_values(variable, overrides):
    selected = ""
    expression = r'^%s:append((?::[\w-]+)*) = "(.*?)"$' % re.escape(variable)
    for match in re.finditer(expression, APPEND, re.MULTILINE | re.DOTALL):
        required = set(filter(None, match[1].split(":")))
        if required.issubset(set(overrides)):
            selected += match[2]
    return selected


def selected_sources(*overrides):
    return re.findall(r"file://([^\s\\]+)", append_values("SRC_URI", overrides))


class SkipRecipe(Exception):
    pass


class FakeData:
    def __init__(self, overrides, release):
        self.values = {"OVERRIDES": overrides, "L4T_VERSION": release}

    def getVar(self, name):
        return self.values.get(name)


def release_guard():
    body = re.search(r"^python __anonymous\(\) \{\n(.*?)^\}", APPEND,
                     re.MULTILINE | re.DOTALL)[1]
    namespace = {"bb": SimpleNamespace(parse=SimpleNamespace(SkipRecipe=SkipRecipe))}
    exec("def guard(d):\n" + textwrap.indent(body, "    "), namespace)
    return namespace["guard"]


class NobleKernelMetadataTests(unittest.TestCase):
    def test_provider_defaults_are_weak_and_keep_the_distro_selector(self):
        layer_conf = (LAYER_DIR / "conf/layer.conf").read_text()
        machine_conf = (LAYER_DIR / "conf/machine/edge-ai.inc").read_text()
        self.assertRegex(layer_conf,
                         r'(?m)^PREFERRED_PROVIDER_virtual/kernel \?= '
                         r'"linux-noble-nvidia-tegra"$')
        self.assertRegex(machine_conf,
                         r'(?m)^TEGRA_DEFAULT_KERNEL \?= '
                         r'"linux-noble-nvidia-tegra"$')
        self.assertNotRegex(machine_conf,
                            r"(?m)^PREFERRED_PROVIDER_virtual/kernel[^\n]*=")

    def resolve_provider(self, local="", tegrademo=True):
        # Exercise the real override datastore without starting a BitBake server
        # or build. Read only the relevant assignments, in bitbake.conf order.
        bb_lib = LAYER_DIR.parents[1] / "repos/bitbake/lib"
        distro = LAYER_DIR.parent / "meta-tegrademo/conf/distro/include/tegrademo.inc"
        if not bb_lib.is_dir() or (tegrademo and not distro.is_file()):
            self.skipTest("BitBake/tegrademo checkout unavailable for datastore test")
        sys.path.insert(0, str(bb_lib))
        try:
            import bb.data
        finally:
            sys.path.pop(0)
        data = bb.data.init()
        data.setVar("OVERRIDES", "tegra:edge-ai")
        sources = [
            (LAYER_DIR / "conf/layer.conf").read_text(),
            local,
            (LAYER_DIR / "conf/machine/edge-ai.inc").read_text(),
        ]
        if tegrademo:
            sources.append(distro.read_text())
        assignment = re.compile(
            r'^(TEGRA_DEFAULT_KERNEL|PREFERRED_PROVIDER_virtual/kernel(?::tegra)?)'
            r'\s*(\?=|=)\s*"([^"\n]*)"$', re.MULTILINE)
        for source in sources:
            for name, operation, value in assignment.findall(source):
                if operation != "?=" or data.getVar(name, False) is None:
                    data.setVar(name, value)
        return data.getVar("PREFERRED_PROVIDER_virtual/kernel")

    def test_tegrademo_effective_default_is_noble(self):
        self.assertEqual(self.resolve_provider(), "linux-noble-nvidia-tegra")

    def test_tegrademo_explicit_selector_preserves_linux_yocto_fallback(self):
        self.assertEqual(self.resolve_provider('TEGRA_DEFAULT_KERNEL = "linux-yocto"'),
                         "linux-yocto")

    def test_tegrademo_qualified_provider_overrides_a_plain_assignment(self):
        self.assertEqual(self.resolve_provider(
            'PREFERRED_PROVIDER_virtual/kernel = "linux-yocto"'),
            "linux-noble-nvidia-tegra")

    def test_other_distros_can_still_select_the_provider_directly(self):
        self.assertEqual(self.resolve_provider(
            'PREFERRED_PROVIDER_virtual/kernel = "linux-yocto"', tegrademo=False),
            "linux-yocto")

    def test_wildcard_shared_appends_remain_symlinks(self):
        for provider in ("linux-noble-nvidia-tegra", "linux-yocto"):
            with self.subTest(provider=provider):
                append = RECIPE_DIR / (provider + "_%.bbappend")
                self.assertTrue(append.is_symlink())
                self.assertEqual(append.readlink(), Path("linux.inc"))
                self.assertIn('SRC_URI += "file://compulab.cfg"', append.read_text())

    def test_all_23_shared_peripheral_requests_are_preserved(self):
        shared = config_values(RECIPE_DIR / "files/compulab.cfg")
        self.assertEqual(len(shared), 23)
        for symbol in (
            "R8169", "IGB", "IGC", "USB_SERIAL_OPTION", "USB_NET_CDC_MBIM",
            "USB_NET_QMI_WWAN", "USB_SERIAL_QUALCOMM", "IWLWIFI", "IWLDVM",
            "IWLMVM", "VIDEO_DS90UB913", "VIDEO_DS90UB953", "VIDEO_DS90UB960",
            "USB_ETH", "USB_GADGETFS", "USB_MASS_STORAGE", "USB_G_SERIAL",
            "USB_RAW_GADGET", "RTC_DRV_ISL1208",
        ):
            self.assertEqual(shared["CONFIG_" + symbol], "m")
        for symbol in ("IP_ADVANCED_ROUTER", "IP_ROUTE_MULTIPATH", "NFSD",
                       "USB_ETH_RNDIS"):
            self.assertEqual(shared["CONFIG_" + symbol], "y")

    def test_unrelated_machines_do_not_get_edge_ai_sources(self):
        self.assertEqual(selected_sources("tegra", "tegra234"), [])
        self.assertEqual(selected_sources("adi-gmsl-v18"), [])

    def test_base_platform_fragment_does_not_enable_adi(self):
        self.assertEqual(selected_sources("tegra", "edge-ai"), [
            "adi-gmsl-v18-noble/edge-ai-noble.cfg",
        ])
        base = config_values(FRAGMENTS / "edge-ai-noble.cfg")
        self.assertFalse(any("VIDEO_MAX" in name for name in base))
        self.assertNotIn("CONFIG_I2C_ATR", base)

    def test_adi_queue_is_scoped_and_independent_of_linux_618(self):
        sources = selected_sources("tegra", "edge-ai", "adi-gmsl-v18")
        self.assertEqual(sources, [
            "adi-gmsl-v18-noble/edge-ai-noble.cfg",
            "adi-gmsl-v18-noble/0001-i2c-atr-backport-address-mapping-for-noble.patch",
            "adi-gmsl-v18-noble/0002-media-maxim-serdes-backport-ADI-v18-to-noble.patch",
            "adi-gmsl-v18-noble/edgedes-adi-v18.cfg",
        ])
        self.assertNotIn("0024-media-maxim-serdes", APPEND)
        fallback = (RECIPE_DIR / "linux-yocto_6.18.bbappend").read_text()
        self.assertIn("adi-gmsl-v18/0024-media-maxim-serdes", fallback)
        self.assertNotIn("adi-gmsl-v18-noble", fallback)

    def test_release_suffix_keeps_vendor_name_and_separates_abis(self):
        self.assertEqual(append_values("LINUX_VERSION_EXTENSION", ["tegra"]), "")
        self.assertEqual(append_values("LINUX_VERSION_EXTENSION", ["edge-ai"]),
                         "-clab")
        self.assertEqual(append_values("LINUX_VERSION_EXTENSION",
                                       ["edge-ai", "adi-gmsl-v18"]),
                         "-clab-adi-v18")
        for match in re.finditer(r"^LINUX_VERSION_EXTENSION([^=\n]*)=", APPEND,
                                 re.MULTILINE):
            self.assertTrue(match[1].startswith(":append:"))

    def test_adi_release_guard_accepts_only_the_matching_release(self):
        guard = release_guard()
        guard(FakeData("tegra:edge-ai:adi-gmsl-v18", "39.2.1"))
        for release in (None, "", "39.2.0", "39.3.0"):
            with self.subTest(release=release), self.assertRaises(SkipRecipe):
                guard(FakeData("tegra:edge-ai:adi-gmsl-v18", release))

    def test_release_guard_does_not_affect_other_profiles(self):
        guard = release_guard()
        for overrides in (None, "", "tegra", "edge-ai", "adi-gmsl-v18"):
            with self.subTest(overrides=overrides):
                guard(FakeData(overrides, "other-release"))

    def test_core_storage_console_and_carrier_interfaces_are_requested(self):
        base = config_values(FRAGMENTS / "edge-ai-noble.cfg")
        for symbol in (
            "BLK_DEV_INITRD", "DEVTMPFS", "FW_LOADER", "PCI", "PCI_MSI",
            "I2C", "I2C_TEGRA", "SPI", "GPIOLIB", "GPIO_CDEV",
            "GPIO_PCA953X", "TCG_TPM", "SERIAL_TEGRA_TCU", "USB",
            "USB_XHCI_TEGRA", "USB_GADGET", "FB_EFI", "FRAMEBUFFER_CONSOLE",
            "FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER", "REGULATOR", "COMMON_CLK",
        ):
            self.assertEqual(base["CONFIG_" + symbol], "y")
        for symbol in ("BLK_DEV_NVME", "PCIE_TEGRA194_HOST", "TCG_TIS_SPI",
                       "SPI_SPIDEV", "USB_TEGRA_XUDC"):
            self.assertEqual(base["CONFIG_" + symbol], "m")

    def test_adi_modes_use_the_replacement_framework_not_legacy_max96712(self):
        camera = config_values(FRAGMENTS / "edgedes-adi-v18.cfg")
        self.assertEqual(camera["CONFIG_VIDEO_MAX96712"], "n")
        for symbol in ("I2C_ATR", "VIDEO_MAXIM_SERDES", "VIDEO_MAX96717",
                       "VIDEO_MAX96724", "VIDEO_MAX9296A"):
            self.assertEqual(camera["CONFIG_" + symbol], "m")
        for symbol in ("MEDIA_CONTROLLER", "VIDEO_V4L2_SUBDEV_API",
                       "VIDEO_ADV_DEBUG", "DYNAMIC_DEBUG", "OF_DYNAMIC"):
            self.assertEqual(camera["CONFIG_" + symbol], "y")

    def test_dynamic_dt_uses_a_public_selector_without_enabling_kernel_tests(self):
        camera = config_values(FRAGMENTS / "edgedes-adi-v18.cfg")
        # OF_DYNAMIC is hidden in Noble; directly requesting it is insufficient.
        # OF_OVERLAY selects it and OF_RESOLVE, unlike enabling OF_UNITTEST.
        self.assertEqual(camera["CONFIG_OF_OVERLAY"], "y")
        self.assertEqual(camera["CONFIG_OF_DYNAMIC"], "y")
        self.assertNotIn("CONFIG_OF_UNITTEST", camera)


if __name__ == "__main__":
    unittest.main(verbosity=2)

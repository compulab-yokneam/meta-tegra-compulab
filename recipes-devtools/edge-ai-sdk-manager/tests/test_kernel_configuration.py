#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only kernel configuration checks against temporary export fixtures."""

import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


FILES = Path(__file__).resolve().parents[1] / "files"
SPECIFICATION = importlib.util.spec_from_file_location(
    "kernel_configuration_assemble", FILES / "assemble-sdk.py")
ASSEMBLE = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(ASSEMBLE)


class KernelConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edge-ai-kernel-config-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.manifest = {
            "format_version": 1,
            "component": "kernel",
            "kernel_release": ASSEMBLE.RELEASE,
            "files": {},
            "symlinks": {},
            "metadata": {
                "kernel_provider": "linux-noble-nvidia-tegra",
                "kernel_release": ASSEMBLE.RELEASE,
                "config_requests": {},
                "modversions": "y",
            },
        }
        self.fragments = {
            "compulab.cfg": {"CONFIG_R8169": "m"},
            "edge-ai-noble.cfg": {"CONFIG_MODVERSIONS": "y"},
            "edgedes-adi-v18.cfg": {"CONFIG_VIDEO_TEGRA": "y"},
        }
        self.refresh()

    def put(self, relative, contents):
        path = self.artifacts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        self.manifest["files"][relative] = hashlib.sha256(
            path.read_bytes()).hexdigest()
        return path

    def config_text(self, values):
        return "".join(
            "# %s is not set\n" % name if value == "n" else
            "%s=%s\n" % (name, value) for name, value in values.items())

    def refresh(self):
        requests = {}
        for name, values in self.fragments.items():
            self.put("metadata/config-fragments/" + name,
                     self.config_text(values))
            requests.update(values)
        self.manifest["metadata"]["config_requests"] = requests
        self.put("metadata/kernel.config", self.config_text(requests))
        self.put("metadata/kernel.release", ASSEMBLE.RELEASE + "\n")

    def validate(self):
        return ASSEMBLE.validate_kernel_config(self.artifacts, self.manifest)

    def snapshot(self):
        return {
            path.relative_to(self.root).as_posix():
                ("link", str(path.readlink())) if path.is_symlink() else
                ("file", path.read_bytes()) if path.is_file() else
                ("directory", None)
            for path in self.root.rglob("*")
        }

    def reject(self):
        before = self.snapshot()
        metadata = copy.deepcopy(self.manifest)
        with mock.patch.object(ASSEMBLE, "run") as command:
            with self.assertRaises(RuntimeError):
                self.validate()
        command.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.manifest, metadata)

    def test_complete_fragments_do_not_require_a_fixed_count(self):
        before = self.snapshot()
        with mock.patch.object(ASSEMBLE, "run") as command:
            self.assertEqual(self.validate(), 3)
        command.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_new_firmware_request_accepts_109_then_110_settings(self):
        self.fragments["compulab.cfg"].update(
            {"CONFIG_TEST_%d" % index: "y" for index in range(106)})
        self.refresh()
        self.assertEqual(self.validate(), 109)
        self.fragments["compulab.cfg"]["CONFIG_FW_LOADER_COMPRESS"] = "y"
        self.refresh()
        self.assertEqual(self.validate(), 110)

    def test_additional_recorded_fragment_is_validated(self):
        self.fragments["local.cfg"] = {"CONFIG_FW_LOADER_COMPRESS": "y"}
        self.refresh()
        self.assertEqual(self.validate(), 4)
        self.put("metadata/kernel.config", self.config_text({
            **self.manifest["metadata"]["config_requests"],
            "CONFIG_FW_LOADER_COMPRESS": "n",
        }))
        self.reject()

    def test_identical_requests_in_multiple_fragments_are_merged(self):
        self.fragments["compulab.cfg"]["CONFIG_MODVERSIONS"] = "y"
        self.refresh()
        self.assertEqual(self.validate(), 3)

    def test_disabled_string_numeric_and_hex_requests_are_preserved(self):
        self.fragments["compulab.cfg"].update({
            "CONFIG_UNUSED": "n", "CONFIG_LOCALVERSION": '"-clab"',
            "CONFIG_NR_CPUS": "12", "CONFIG_PHYS_ADDR": "0x40000000",
        })
        self.refresh()
        self.assertEqual(self.validate(), 7)

    def test_mixed_case_configuration_symbols_are_preserved(self):
        self.fragments["compulab.cfg"].update({
            "CONFIG_MT792x_LIB": "m", "CONFIG_I2C_MUX_PCA954x": "y",
            "CONFIG_ARM_CCI5xx_PMU": "n", "CONFIG_FONT_8x8": "y",
        })
        self.refresh()
        path = self.artifacts / "metadata/kernel.config"
        self.put("metadata/kernel.config", path.read_text() +
                 "CONFIG_UNREQUESTED_4x4=y\n"
                 "# CONFIG_UNREQUESTED_8x8 is not set\n")
        self.assertEqual(self.validate(), 7)

    def test_missing_required_fragment_is_rejected(self):
        for name in self.fragments:
            with self.subTest(name=name):
                relative = "metadata/config-fragments/" + name
                path = self.artifacts / relative
                contents = path.read_text()
                path.unlink()
                self.reject()
                self.put(relative, contents)

    def test_required_fragment_must_be_recorded_in_manifest(self):
        relative = "metadata/config-fragments/edgedes-adi-v18.cfg"
        self.manifest["files"].pop(relative)
        self.reject()

    def test_unrecorded_fragment_is_rejected(self):
        path = self.artifacts / "metadata/config-fragments/unrecorded.cfg"
        path.write_text("CONFIG_UNRECORDED=y\n")
        self.reject()

    def test_empty_required_fragment_is_rejected(self):
        self.fragments["edgedes-adi-v18.cfg"] = {}
        self.refresh()
        self.reject()

    def test_conflicting_requests_across_fragments_are_rejected(self):
        self.fragments["edgedes-adi-v18.cfg"]["CONFIG_R8169"] = "y"
        self.refresh()
        self.reject()

    def test_manifest_cannot_omit_a_fragment_request(self):
        self.manifest["metadata"]["config_requests"].pop("CONFIG_R8169")
        self.reject()

    def test_manifest_cannot_inject_a_request_without_a_fragment(self):
        self.manifest["metadata"]["config_requests"]["CONFIG_INJECTED"] = "y"
        self.put("metadata/kernel.config", self.config_text(
            self.manifest["metadata"]["config_requests"]))
        self.reject()

    def test_manifest_cannot_change_a_fragment_request(self):
        self.manifest["metadata"]["config_requests"]["CONFIG_R8169"] = "y"
        self.reject()

    def test_requested_value_must_match_actual_configuration(self):
        requests = self.manifest["metadata"]["config_requests"]
        self.put("metadata/kernel.config", self.config_text({
            **requests, "CONFIG_R8169": "n",
        }))
        self.reject()

    def test_missing_requested_actual_setting_is_rejected(self):
        requests = dict(self.manifest["metadata"]["config_requests"])
        requests.pop("CONFIG_R8169")
        self.put("metadata/kernel.config", self.config_text(requests))
        self.reject()

    def test_duplicate_actual_configuration_key_is_rejected(self):
        path = self.artifacts / "metadata/kernel.config"
        self.put("metadata/kernel.config",
                 path.read_text() + "CONFIG_R8169=m\n")
        self.reject()

    def test_conflicting_duplicate_fragment_key_is_rejected(self):
        relative = "metadata/config-fragments/compulab.cfg"
        path = self.artifacts / relative
        self.put(relative, path.read_text() + "CONFIG_R8169=y\n")
        self.reject()

    def test_wrong_provider_is_rejected(self):
        self.manifest["metadata"]["kernel_provider"] = "linux-yocto"
        self.reject()

    def test_module_crcs_must_remain_enabled(self):
        self.fragments["edge-ai-noble.cfg"]["CONFIG_MODVERSIONS"] = "n"
        self.manifest["metadata"]["modversions"] = "n"
        self.refresh()
        self.reject()

    def test_release_file_and_manifest_must_match_the_pinned_release(self):
        self.put("metadata/kernel.release", "incorrect-release\n")
        self.reject()
        self.put("metadata/kernel.release", ASSEMBLE.RELEASE + "\n")
        self.manifest["kernel_release"] = "incorrect-release"
        self.reject()

    def test_configuration_and_fragment_checksums_are_verified(self):
        for relative in ("metadata/kernel.config", "metadata/kernel.release",
                         "metadata/config-fragments/compulab.cfg"):
            with self.subTest(relative=relative):
                path = self.artifacts / relative
                original = path.read_text()
                path.write_text(original + "# drift\n")
                self.reject()
                path.write_text(original)

    def test_required_files_cannot_be_symlinks(self):
        for relative in ("metadata/kernel.config", "metadata/kernel.release",
                         "metadata/config-fragments/compulab.cfg"):
            with self.subTest(relative=relative):
                path = self.artifacts / relative
                saved = self.root / "saved"
                path.rename(saved)
                path.symlink_to(saved)
                self.reject()
                path.unlink()
                saved.rename(path)

    def test_symlinked_fragment_directory_is_rejected(self):
        path = self.artifacts / "metadata/config-fragments"
        saved = self.root / "saved-fragments"
        path.rename(saved)
        path.symlink_to(saved, target_is_directory=True)
        self.reject()

    def test_malformed_request_metadata_is_rejected(self):
        for requests in (None, [], {}, {"not-a-config-name": "y"},
                         {"CONFIG_R8169": True}, {"CONFIG_R8169": []}):
            with self.subTest(requests=requests):
                self.manifest["metadata"]["config_requests"] = requests
                self.reject()

    def test_malformed_configuration_assignment_is_rejected(self):
        relative = "metadata/config-fragments/compulab.cfg"
        self.put(relative, "CONFIG_R8169=m\nCONFIG_INVALID-NAME=y\n")
        self.reject()


if __name__ == "__main__":
    unittest.main()

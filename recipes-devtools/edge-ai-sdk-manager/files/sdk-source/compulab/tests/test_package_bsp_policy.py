#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary-only package policy fixtures; never mutate host package state."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / \
    "tools/package-bsp-policy.py"
SPEC = importlib.util.spec_from_file_location("package_bsp_policy", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PackageBspPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="package-bsp-policy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.original = b"""# Keep all unrelated settings.
ENABLE_SPEC_GENERATION="1"
ENABLE_UEFI_SPEC_VAR_UPDATE="1"
ENABLE_PARTITION_UPDATE="1"
ENABLE_ESP_AUTOMOUNT="1"
ENABLE_AUTO_QSPI_UPDATE="1"
"""
        self.put("usr/lib/os-release", b'ID=ubuntu\nVERSION_ID="24.04"\n')
        self.put("var/lib/dpkg/status", b"fixture only\n")
        self.put(MODULE.CONFIG, self.original)
        self.names = ["nvidia-l4t-kernel", "nvidia-l4t-gstreamer"]
        self.put(MODULE.DESIRED, json.dumps(dict(
            schema=1, l4t_version="39.2.1", hold_packages=self.names)).encode())
        self.current = [
            dict(name="nvidia-l4t-kernel:arm64", version="39.2.1-test",
                 selection="hold"),
            dict(name="nvidia-l4t-gstreamer:arm64", version="39.2.1-test",
                 selection="install"),
        ]
        self.initial = [dict(item) for item in self.current]
        self.operations = []
        patch = mock.patch.object(MODULE.subprocess, "run",
                                  side_effect=self.package_command)
        self.run = patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(MODULE.os, "geteuid", return_value=0)
        patch.start()
        self.addCleanup(patch.stop)

    def put(self, relative, data, mode=0o644):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def package_command(self, command, **kwargs):
        self.assertIn("--admindir=" + str(self.root / "var/lib/dpkg"),
                      command)
        if command[0] == "dpkg-query":
            name = command[-1]
            found = [item for item in self.current
                     if item["name"].split(":")[0] == name]
            if not found:
                return subprocess.CompletedProcess(command, 1, "", "")
            item = found[0]
            row = "\t".join((item["name"], item["version"], "arm64",
                             item["selection"], "installed")) + "\n"
            return subprocess.CompletedProcess(command, 0, row, "")
        self.assertEqual(command[0], "dpkg")
        self.assertEqual(command[-1], "--set-selections")
        self.assertEqual(kwargs.get("check"), True)
        self.operations.append((kwargs["input"], kwargs.get("env", {})))
        for row in kwargs["input"].splitlines():
            name, selection = row.split("\t")
            item = next(item for item in self.current
                        if item["name"] == name)
            item["selection"] = selection
        return subprocess.CompletedProcess(command, 0, "", "")

    def policy(self):
        return MODULE.Policy(self.root)

    def state(self):
        return json.loads((self.root / MODULE.STATE).read_text())

    def seed(self):
        updated = MODULE.protected_config(self.original)
        self.put(MODULE.CONFIG, updated)
        for item in self.current:
            item["selection"] = "hold"
        state = dict(
            schema=1,
            original_config=base64.b64encode(self.original).decode(),
            original_config_sha256=MODULE.sha256(self.original),
            applied_config_sha256=MODULE.sha256(updated),
            config_mode=0o644, packages=self.initial)
        self.put(MODULE.STATE, json.dumps(state).encode(), mode=0o600)
        return state

    def pin(self, records=None):
        records = self.initial if records is None else records
        text = "\n\n".join(
            "Package: " + item["name"].removesuffix(":arm64") +
            "\nPin: version " + item["version"] + "\nPin-Priority: 1000"
            for item in records) + "\n"
        self.put(MODULE.APT_PIN, text.encode())

    def test_read_only_check_never_creates_state_or_changes_selections(self):
        result = self.policy().check()
        self.assertFalse(result["protected"])
        self.assertEqual(result["state"], "absent")
        self.assertEqual(self.operations, [])
        self.assertFalse((self.root / MODULE.STATE).exists())
        self.assertEqual((self.root / MODULE.CONFIG).read_bytes(),
                         self.original)

    def test_apply_and_restore_preserve_original_holds_and_other_flags(self):
        policy = self.policy()
        self.assertTrue(policy.apply()["protected"])
        updated = (self.root / MODULE.CONFIG).read_bytes()
        self.assertEqual(updated,
                         self.original.replace(
                             b'ENABLE_AUTO_QSPI_UPDATE="1"',
                             b'ENABLE_AUTO_QSPI_UPDATE="0"'))
        self.assertTrue(all(item["selection"] == "hold"
                            for item in self.current))
        self.assertEqual(self.state()["packages"], self.initial)
        self.assertEqual((self.root / MODULE.STATE).stat().st_mode & 0o777,
                         0o600)
        self.assertFalse(policy.restore()["protected"])
        self.assertEqual(self.current, self.initial)
        self.assertEqual((self.root / MODULE.CONFIG).read_bytes(),
                         self.original)

    def test_repeated_apply_preserves_first_original_state(self):
        policy = self.policy()
        policy.apply()
        original_state = self.state()
        policy.apply()
        self.assertEqual(self.state(), original_state)
        policy.restore()
        self.assertEqual(self.current, self.initial)

    def test_seeded_original_state_is_not_recaptured_after_sdk_protection(self):
        seeded = self.seed()
        policy = self.policy()
        self.assertTrue(policy.apply()["protected"])
        self.assertEqual(self.state()["original_config"],
                         seeded["original_config"])
        self.assertEqual(self.state()["packages"], self.initial)
        policy.restore()
        self.assertEqual(self.current, self.initial)
        self.assertEqual((self.root / MODULE.CONFIG).read_bytes(),
                         self.original)

    def test_maintainer_configuration_pins_without_nested_dpkg_writer(self):
        self.pin()
        with mock.patch.dict(os.environ,
                             {"DPKG_MAINTSCRIPT_PACKAGE":
                              "compulab-edge-ai-bsp-policy"}):
            policy = self.policy()
            result = policy.configure()
            self.assertTrue(result["protected"])
            self.assertEqual(result["package_protection"], "apt-pins")
            self.assertEqual(self.current, self.initial)
            policy.restore_config()
        self.assertEqual(self.operations, [])
        self.assertEqual(self.current, self.initial)
        self.assertEqual((self.root / MODULE.CONFIG).read_bytes(),
                         self.original)

    def test_package_manager_cannot_call_full_selection_mutators(self):
        with mock.patch.dict(os.environ,
                             {"DPKG_MAINTSCRIPT_PACKAGE":
                              "compulab-edge-ai-bsp-policy"}):
            policy = self.policy()
            for action in (policy.apply, policy.restore):
                with self.assertRaisesRegex(RuntimeError, "outside dpkg/apt"):
                    action()
        self.assertEqual(self.operations, [])
        self.assertFalse((self.root / MODULE.STATE).parent.exists())

    def test_configuration_only_preserves_seeded_hold_state(self):
        self.seed()
        original_holds = [dict(item) for item in self.current]
        with mock.patch.dict(os.environ,
                             {"DPKG_MAINTSCRIPT_PACKAGE":
                              "compulab-edge-ai-bsp-policy"}):
            policy = self.policy()
            self.assertTrue(policy.configure()["protected"])
            policy.restore_config()
        self.assertEqual(self.operations, [])
        self.assertEqual(self.current, original_holds)
        self.assertEqual(self.state()["packages"], self.initial)
        self.assertEqual((self.root / MODULE.CONFIG).read_bytes(),
                         self.original)

    def test_configuration_requires_complete_matching_literal_pins(self):
        for contents in (
                b"Package: *\nPin: version 39.2.1-test\nPin-Priority: 1000\n",
                b"Package: nvidia-l4t-kernel\nPin: version *\n"
                b"Pin-Priority: 1000\n",
                b"Package: nvidia-l4t-kernel\nPin: version 39.2.1-test\n"
                b"Pin-Priority: 500\n"):
            self.put(MODULE.APT_PIN, contents)
            with self.assertRaises(RuntimeError):
                self.policy().configure()
        self.pin(self.initial[:1])
        with self.assertRaisesRegex(RuntimeError, "verified holds"):
            self.policy().configure()
        changed = [dict(item) for item in self.initial]
        changed[-1]["version"] = "39.2.0-old"
        self.pin(changed)
        with self.assertRaisesRegex(RuntimeError, "verified holds"):
            self.policy().configure()
        self.assertEqual(self.operations, [])

    def test_pin_contents_are_never_evaluated_as_shell_code(self):
        self.put(MODULE.APT_PIN,
                 b"Package: $(touch\nPin: version 39.2.1-test\n"
                 b"Pin-Priority: 1000\n")
        with self.assertRaises(RuntimeError):
            self.policy().configure()
        self.assertEqual(self.operations, [])

    def test_standalone_policy_coordinates_with_target_frontend_lock(self):
        with mock.patch.object(MODULE.fcntl, "lockf",
                               side_effect=BlockingIOError):
            with self.assertRaisesRegex(RuntimeError, "preparation is busy"):
                self.policy().apply()
        self.assertEqual(self.operations, [])
        self.assertFalse((self.root / MODULE.STATE).exists())

    def test_restore_refuses_administrator_configuration_edits(self):
        policy = self.policy()
        policy.apply()
        changed = (self.root / MODULE.CONFIG).read_bytes() + b"# admin edit\n"
        self.put(MODULE.CONFIG, changed)
        count = len(self.operations)
        with self.assertRaisesRegex(RuntimeError, "configuration changed"):
            policy.restore()
        self.assertEqual(len(self.operations), count)
        self.assertEqual((self.root / MODULE.CONFIG).read_bytes(), changed)
        self.assertFalse(policy.check()["protected"])

    def test_package_version_drift_fails_before_any_changes(self):
        policy = self.policy()
        policy.apply()
        self.current[0]["version"] = "39.2.2-changed"
        count = len(self.operations)
        with self.assertRaisesRegex(RuntimeError, "version changed"):
            policy.restore()
        self.assertEqual(len(self.operations), count)

    def test_missing_seeded_package_is_not_silently_ignored(self):
        seeded = self.seed()
        seeded["packages"] = seeded["packages"][:1]
        self.put(MODULE.STATE, json.dumps(seeded).encode(), mode=0o600)
        with self.assertRaisesRegex(RuntimeError, "package set changed"):
            self.policy().apply()
        self.assertEqual(self.operations, [])

    def test_bad_state_hash_and_permissions_are_rejected(self):
        seeded = self.seed()
        seeded["original_config_sha256"] = "0" * 64
        self.put(MODULE.STATE, json.dumps(seeded).encode(), mode=0o600)
        with self.assertRaisesRegex(RuntimeError, "corrupt"):
            self.policy().apply()
        self.seed()
        (self.root / MODULE.STATE).chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "other users"):
            self.policy().apply()
        self.assertEqual(self.operations, [])

    def test_symlink_config_or_state_is_rejected(self):
        actual = self.root / MODULE.CONFIG
        saved = self.root / "saved.conf"
        actual.rename(saved)
        actual.symlink_to(saved)
        with self.assertRaisesRegex(RuntimeError, "Symlink"):
            self.policy()
        actual.unlink()
        actual.write_bytes(self.original)
        state = self.root / MODULE.STATE
        state.parent.mkdir(parents=True)
        state.symlink_to(self.root / "outside-state")
        with self.assertRaisesRegex(RuntimeError, "Symlink"):
            self.policy()

    def test_unknown_or_duplicate_hold_names_are_rejected(self):
        for names in (["ordinary-ubuntu-package"],
                      [self.names[0], self.names[0]]):
            self.put(MODULE.DESIRED, json.dumps(dict(
                schema=1, l4t_version="39.2.1", hold_packages=names)).encode())
            with self.assertRaisesRegex(RuntimeError, "package names"):
                self.policy()
        self.assertEqual(self.operations, [])

    def test_nonroot_cannot_apply_or_restore_but_can_inspect(self):
        with mock.patch.object(MODULE.os, "geteuid", return_value=1001):
            policy = self.policy()
            self.assertFalse(policy.check()["protected"])
            for action in (policy.apply, policy.restore):
                with self.assertRaisesRegex(RuntimeError, "requires root"):
                    action()
        self.assertFalse((self.root / MODULE.STATE).parent.exists())
        self.assertEqual(self.operations, [])

    def test_duplicate_vendor_flags_are_rejected_without_setting_holds(self):
        self.put(MODULE.CONFIG,
                 self.original + b'ENABLE_AUTO_QSPI_UPDATE="1"\n')
        with self.assertRaisesRegex(RuntimeError, "one literal"):
            self.policy().apply()
        self.assertEqual(self.operations, [])


if __name__ == "__main__":
    unittest.main()

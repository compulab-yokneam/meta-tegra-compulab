#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
"""Run only on disposable offline dpkg fixtures; never alter host selections."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "policy/bsp-protection.py"
spec = importlib.util.spec_from_file_location("bsp_protection", SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class BSPProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="compulab-bsp-test.")
        self.addCleanup(self.temporary.cleanup)
        self.sdk = Path(self.temporary.name)
        (self.sdk / "flash.sh").write_text("# fixture, never executed\n")
        self.root = self.sdk / "rootfs"
        self.db = self.root / "var/lib/dpkg"
        self.db.mkdir(parents=True)
        (self.db / "updates").mkdir()
        (self.db / "lock-frontend").touch()
        self.initial_status = "".join(
            "Package: " + name + "\nStatus: " + selection +
            " ok installed\nArchitecture: arm64\nVersion: 39.2.1-test\n"
            "Maintainer: Test <test@example.invalid>\nDescription: fixture\n\n"
            for name, selection in (("nvidia-l4t-kernel", "install"),
                                    ("nvidia-l4t-bootloader", "hold"),
                                    ("unrelated-package", "install")))
        (self.db / "status").write_text(self.initial_status)
        self.config = self.root / policy.CONFIG
        self.config.parent.mkdir(parents=True)
        self.original = ("# vendor fixture, retain this comment\n" + "".join(
            name + '=\"1\"\n' for name in policy.FLAGS)).encode()
        self.config.write_bytes(self.original)
        self.config.chmod(0o640)
        service = self.root / policy.SERVICE
        service.parent.mkdir(parents=True)
        service.symlink_to("/opt/nvidia/l4t-bootloader-config/nv-l4t-bootloader-config.service")
        for relative in policy.ARTIFACTS:
            path = self.sdk / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("unchanged " + relative).encode())
        self.instance = policy.Policy(self.sdk)
        self.hashes = self.instance.artifacts()

    def snapshot(self):
        return {str(p.relative_to(self.sdk)): p.read_bytes()
                for p in self.sdk.rglob("*") if p.is_file() and not p.is_symlink()}

    def test_default_is_read_only(self):
        before = self.snapshot()
        result = subprocess.run(["python3", "-B", str(SOURCE), "--sdk", str(self.sdk)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["protected"])
        self.assertEqual(self.snapshot(), before)

    def test_apply_and_restore_preserve_original_hold(self):
        before = self.instance.packages()
        applied = self.instance.apply()
        self.assertTrue(applied["protected"])
        self.assertTrue(all(p["selection"] == "hold" for p in applied["packages"]))
        self.assertEqual(self.config.read_bytes(), self.original.replace(
            b'ENABLE_AUTO_QSPI_UPDATE="1"', b'ENABLE_AUTO_QSPI_UPDATE="0"'))
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        status = (self.db / "status").read_text()
        self.assertIn("Package: unrelated-package\nStatus: install ok installed", status)
        _, record = self.instance.receipt()
        self.assertEqual(record["packages"], before)
        self.assertTrue((self.instance.directory / record["original_config"]).is_file())
        self.assertEqual(self.instance.apply(), applied)
        restored = self.instance.restore()
        self.assertFalse(restored["protected"])
        self.assertEqual(restored["packages"], before)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.instance.artifacts(), self.hashes)
        self.assertEqual(self.instance.restore(), restored)

    def test_config_drift_restore_refuses(self):
        self.instance.apply()
        self.config.write_bytes(self.config.read_bytes() + b"# local change\n")
        changed = self.config.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "configuration changed"):
            self.instance.restore()
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertFalse(self.instance.check()["protected"])

    def test_version_drift_refuses(self):
        self.instance.apply()
        status = self.db / "status"
        status.write_text(status.read_text().replace("39.2.1-test", "39.2.2-test"))
        self.assertFalse(self.instance.check()["protected"])
        with self.assertRaisesRegex(RuntimeError, "selection/version drift"):
            self.instance.restore()

    def test_package_disappearance_is_not_protected(self):
        self.instance.apply()
        status = self.db / "status"
        content = status.read_text()
        paragraphs = content.strip().split("\n\n")
        status.write_text("\n\n".join(p for p in paragraphs
                                        if not p.startswith("Package: nvidia-l4t-kernel\n")) + "\n\n")
        self.assertFalse(self.instance.check()["protected"])

    def test_marker_is_not_created_or_removed(self):
        marker = self.root / policy.MARKER
        marker.parent.mkdir(parents=True)
        marker.write_text("existing temporary preparation marker")
        with self.assertRaisesRegex(RuntimeError, "preinstall marker remains"):
            self.instance.apply()
        self.assertTrue(marker.exists())
        self.assertEqual(self.instance.packages()[1]["selection"], "install")

    def test_busy_frontend_refuses(self):
        # POSIX locks are process-owned, so use a child that announces its lock.
        command = ("import fcntl,sys; f=open(sys.argv[1],'r+b'); "
                   "fcntl.lockf(f,fcntl.LOCK_EX); print('locked',flush=True); input()")
        child = subprocess.Popen(["python3", "-c", command,
                                  str(self.db / "lock-frontend")],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaisesRegex(RuntimeError, "busy"):
                self.instance.apply()
        finally:
            child.communicate("\n", timeout=5)

    def test_external_config_refuses(self):
        self.config.unlink()
        self.config.symlink_to("/etc/hostname")
        with self.assertRaisesRegex(RuntimeError, "outside the SDK rootfs"):
            policy.Policy(self.sdk)

    def test_external_receipts_refuse(self):
        directory = self.sdk / "compulab/policy"
        directory.mkdir(parents=True)
        (directory / "receipts").symlink_to("/tmp")
        with self.assertRaisesRegex(RuntimeError, "receipt path outside"):
            policy.Policy(self.sdk)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary-only .deb assembly and mocked diversion lifecycle tests."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "tools/deb_packages.py"
SPEC = importlib.util.spec_from_file_location("compulab_deb_packages", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

DIVERT = r'''import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
with open(os.environ["DIVERT_LOG"], "a") as stream:
    stream.write(json.dumps(arguments) + "\n")
if arguments[:1] == ["--root"]:
    root = Path(arguments[1])
    arguments = arguments[2:]
else:
    root = Path(os.environ["TEST_ROOT"])
state_file = Path(os.environ["DIVERT_STATE"])
state = json.loads(state_file.read_text()) if state_file.exists() else {}
original = arguments[-1]
if "--listpackage" in arguments:
    print(state.get(original, {}).get("owner", ""))
elif "--truename" in arguments:
    print(state.get(original, {}).get("destination", original))
elif "--add" in arguments:
    destination = arguments[arguments.index("--divert") + 1]
    owner = arguments[arguments.index("--package") + 1]
    source = root / original.lstrip("/")
    backup = root / destination.lstrip("/")
    if backup.exists() or backup.is_symlink():
        raise SystemExit(9)
    if source.exists() or source.is_symlink():
        source.rename(backup)
    state[original] = {"owner": owner, "destination": destination}
    state_file.write_text(json.dumps(state))
elif "--remove" in arguments:
    destination = arguments[arguments.index("--divert") + 1]
    source = root / original.lstrip("/")
    backup = root / destination.lstrip("/")
    if source.exists() or source.is_symlink():
        raise SystemExit(10)
    if backup.exists() or backup.is_symlink():
        backup.rename(source)
    state.pop(original, None)
    state_file.write_text(json.dumps(state))
else:
    raise SystemExit(11)
'''


class DebPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="compulab-deb-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.payload = self.root / "payload"
        self.output = self.root / "packages"
        self.payload.mkdir()
        self.put(self.payload / "usr/bin/compulab-example", b"sample\n", 0o755)

    def put(self, path, data, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)

    def build(self, **kwargs):
        return MODULE.build_package(
            self.payload, self.output, "compulab-example", "39.2.1+clab1",
            **kwargs)

    def rejected(self, **kwargs):
        with self.assertRaises((ValueError, TypeError)):
            self.build(**kwargs)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb unavailable")
    def test_real_package_contents_metadata_checksums_and_ownership(self):
        configuration = self.payload / "etc/compulab-example.conf"
        self.put(configuration, b"enabled=yes\n")
        (self.payload / "usr/bin/compulab-link").symlink_to("compulab-example")
        package = self.build(depends=("python3", "libc6 (>= 2.38)"),
                             conffiles=("/etc/compulab-example.conf",))
        fields = subprocess.check_output(
            ["dpkg-deb", "-f", package], text=True)
        self.assertIn("Package: compulab-example\n", fields)
        self.assertIn("Version: 39.2.1+clab1\n", fields)
        self.assertIn("Architecture: arm64\n", fields)
        self.assertIn("Depends: python3, libc6 (>= 2.38)\n", fields)
        extracted = self.root / "extracted"
        metadata = self.root / "control"
        subprocess.run(["dpkg-deb", "-x", package, extracted], check=True)
        subprocess.run(["dpkg-deb", "-e", package, metadata], check=True)
        self.assertEqual((extracted / "usr/bin/compulab-example").read_bytes(),
                         b"sample\n")
        self.assertEqual((extracted / "usr/bin/compulab-link").readlink(),
                         Path("compulab-example"))
        self.assertEqual((metadata / "conffiles").read_text(),
                         "/etc/compulab-example.conf\n")
        self.assertIn(hashlib.md5(b"sample\n").hexdigest() +
                      "  usr/bin/compulab-example\n",
                      (metadata / "md5sums").read_text())
        listing = subprocess.check_output(["dpkg-deb", "-c", package],
                                         text=True)
        self.assertTrue(all("root/root" in line
                            for line in listing.splitlines()))
        self.assertFalse((self.payload / "DEBIAN").exists())

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb unavailable")
    def test_output_is_deterministic_and_never_overwritten(self):
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            first = self.build()
            again = MODULE.build_package(
                self.payload, self.root / "other", "compulab-example",
                "39.2.1+clab1")
        self.assertEqual(first.read_bytes(), again.read_bytes())
        original = first.read_bytes()
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(first.read_bytes(), original)

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb unavailable")
    def test_existing_and_racing_output_cannot_be_replaced(self):
        self.output.mkdir()
        target = self.output / "compulab-example_39.2.1+clab1_arm64.deb"
        target.symlink_to(self.root / "nonexistent")
        with self.assertRaises(ValueError):
            self.build()
        self.assertTrue(target.is_symlink())
        target.unlink()
        link = MODULE.os.link

        def race(source, destination):
            destination.write_bytes(b"unrelated output")
            return link(source, destination)

        with mock.patch.object(MODULE.os, "link", side_effect=race):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(target.read_bytes(), b"unrelated output")

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb unavailable")
    def test_control_permissions_ignore_umask_and_scripts_never_execute(self):
        script = "#!/bin/sh\ntouch " + str(self.root / "EXECUTED") + "\n"
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            previous = os.umask(0o077)
            try:
                first = self.build(scripts={"postinst": script})
            finally:
                os.umask(previous)
            second = MODULE.build_package(
                self.payload, self.root / "other", "compulab-example",
                "39.2.1+clab1", scripts={"postinst": script})
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertFalse((self.root / "EXECUTED").exists())
        self.assertEqual(first.stat().st_mode & 0o777, 0o644)
        metadata = self.root / "control"
        subprocess.run(["dpkg-deb", "-e", first, metadata], check=True)
        self.assertEqual((metadata / "postinst").read_text(), script)
        self.assertEqual((metadata / "postinst").stat().st_mode & 0o777,
                         0o755)
        self.assertEqual((metadata / "control").stat().st_mode & 0o777,
                         0o644)

    def test_failed_builder_publishes_nothing_and_preserves_payload(self):
        failure = subprocess.CalledProcessError(2, ["dpkg-deb"])
        with mock.patch.object(MODULE.subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual((self.payload / "usr/bin/compulab-example")
                         .read_bytes(), b"sample\n")
        self.assertFalse((self.payload / "DEBIAN").exists())

    def test_control_metadata_and_relationship_injection_is_rejected(self):
        for options in (
                {"architecture": "arm64\nDepends: bad"},
                {"description": "description\nPackage: injected"},
                {"depends": ("python3\nReplaces: libc6",)},
                {"depends": "python3"}, {"depends": ("../bad",)},
                {"depends": ("python3", "python3")},
                {"depends": ("python3 | $(touch marker)",)}):
            with self.subTest(options=options):
                self.rejected(**options)
        for name, version in (("bad/name", "1"), ("a\nb", "1"),
                              ("valid-name", "1\nArchitecture: all"),
                              ("valid-name", "1:foo"),
                              ("valid-name", "1-")):
            with self.subTest(name=name, version=version):
                with self.assertRaises(ValueError):
                    MODULE.build_package(self.payload, self.output,
                                         name, version)

    def test_unsafe_or_duplicate_metadata_paths_are_rejected(self):
        for paths in (("/usr/../bin/compulab-example",),
                      ("/usr//bin/compulab-example",),
                      ("//usr/bin/compulab-example",),
                      ("usr/bin/compulab-example",),
                      ("/usr/bin/compulab-example\n/etc/evil",),
                      ("/usr/bin/compulab-example",) * 2,
                      ("/missing",)):
            with self.subTest(paths=paths):
                self.rejected(conffiles=paths)
        for pairs in (
                (("/usr/bin/compulab-example", "/backup"),) * 2,
                (("/usr/bin/compulab-example", "/usr/../backup"),),
                (("/missing", "/backup"),),
                (("/usr/bin/compulab-example", "/usr/bin/compulab-example"),),
                (("/usr/bin/compulab-example", "/usr/bin"),)):
            with self.subTest(pairs=pairs):
                self.rejected(diversions=pairs)

    def test_source_control_data_and_special_files_are_rejected(self):
        (self.payload / "DEBIAN").mkdir()
        self.rejected()
        (self.payload / "DEBIAN").rmdir()
        os.mkfifo(self.payload / "fifo")
        self.rejected()

    def test_escaping_absolute_dangling_and_symlink_roots_are_rejected(self):
        link = self.payload / "link"
        external = self.root / "external"
        external.write_bytes(b"keep outside")
        for target in (str(external), "../external", "missing"):
            with self.subTest(target=target):
                link.symlink_to(target)
                self.rejected()
                link.unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.payload, target_is_directory=True)
        with self.assertRaises(ValueError):
            MODULE.build_package(alias, self.output, "compulab-example", "1")
        with self.assertRaises(ValueError):
            MODULE.build_package(self.payload, self.payload / "output",
                                 "compulab-example", "1")

    def test_custom_scripts_are_literal_and_cannot_override_diversions(self):
        self.rejected(scripts={"../postinst": "#!/bin/sh\nexit 0\n"})
        self.rejected(scripts={"postinst": "#!/bin/sh\n\0"})
        self.rejected(scripts={"preinst": "#!/bin/sh\nexit 0\n"},
                      diversions=(("/usr/bin/compulab-example", "/backup"),))

    def diversion_fixture(self, pairs=None):
        pairs = pairs or (("/usr/lib/example.so",
                           "/usr/lib/example.so.compulab-distrib"),)
        root = self.root / "target root"
        root.mkdir()
        for original, _ in pairs:
            self.put(root / original.lstrip("/"), b"vendor original")
        binary = self.root / "bin"
        binary.mkdir()
        command = binary / "dpkg-divert"
        command.write_text("#!" + sys.executable + "\n" + DIVERT)
        command.chmod(0o755)
        state = self.root / "state.json"
        state.write_text("{}")
        log = self.root / "calls.jsonl"
        environment = dict(os.environ, PATH=str(binary) + ":/usr/bin:/bin",
                           DPKG_ROOT=str(root), TEST_ROOT=str(root),
                           DIVERT_STATE=str(state), DIVERT_LOG=str(log))
        scripts = MODULE.diversion_scripts("compulab-example", pairs)
        for name, content in scripts.items():
            (self.root / name).write_text(content)
        return root, pairs, state, log, environment

    def run_maintainer(self, script, action, environment):
        return subprocess.run(["/bin/sh", self.root / script, action],
                              env=environment, capture_output=True, text=True)

    def test_diversion_install_upgrade_remove_and_root_are_safe(self):
        root, pairs, state, log, environment = self.diversion_fixture()
        original, destination = pairs[0]
        before = self.run_maintainer("preinst", "install", environment)
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual((root / destination.lstrip("/")).read_bytes(),
                         b"vendor original")
        self.put(root / original.lstrip("/"), b"custom package")
        for script, action in (("preinst", "upgrade"),
                               ("postrm", "upgrade"),
                               ("postrm", "abort-upgrade")):
            result = self.run_maintainer(script, action, environment)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / original.lstrip("/")).read_bytes(),
                         b"custom package")
        (root / original.lstrip("/")).unlink()
        result = self.run_maintainer("postrm", "remove", environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / original.lstrip("/")).read_bytes(),
                         b"vendor original")
        self.assertEqual(json.loads(state.read_text()), {})
        result = self.run_maintainer("postrm", "purge", environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in log.read_text().splitlines():
            self.assertEqual(json.loads(line)[:2], ["--root", str(root)])

    def test_foreign_diversion_preflight_prevents_any_mutation(self):
        pairs = (("/usr/lib/one.so", "/usr/lib/one.so.distrib"),
                 ("/usr/lib/two.so", "/usr/lib/two.so.distrib"))
        root, pairs, state, log, environment = self.diversion_fixture(pairs)
        state.write_text(json.dumps({pairs[1][0]: {
            "owner": "other-package", "destination": pairs[1][1]}}))
        result = self.run_maintainer("preinst", "install", environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign diversion", result.stderr)
        self.assertFalse((root / pairs[0][1].lstrip("/")).exists())
        self.assertTrue((root / pairs[0][0].lstrip("/")).is_file())
        self.assertFalse(any("--add" in json.loads(line)
                             for line in log.read_text().splitlines()))

    def test_backup_collisions_and_existing_files_are_preserved(self):
        root, pairs, state, _, environment = self.diversion_fixture()
        original, destination = pairs[0]
        backup = root / destination.lstrip("/")
        backup.write_bytes(b"unrelated backup")
        result = self.run_maintainer("preinst", "install", environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(backup.read_bytes(), b"unrelated backup")
        self.assertEqual(json.loads(state.read_text()), {})
        backup.unlink()
        self.assertEqual(self.run_maintainer("preinst", "install",
                                            environment).returncode, 0)
        self.put(root / original.lstrip("/"), b"do not overwrite")
        result = self.run_maintainer("postrm", "remove", environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((root / original.lstrip("/")).read_bytes(),
                         b"do not overwrite")
        self.assertEqual(backup.read_bytes(), b"vendor original")
        self.assertTrue(json.loads(state.read_text()))

    def test_owned_diversion_with_wrong_destination_is_rejected(self):
        root, pairs, state, _, environment = self.diversion_fixture()
        state.write_text(json.dumps({pairs[0][0]: {
            "owner": "compulab-example", "destination": "/different"}}))
        result = self.run_maintainer("preinst", "upgrade", environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected diversion destination", result.stderr)
        self.assertEqual((root / pairs[0][0].lstrip("/")).read_bytes(),
                         b"vendor original")

    @unittest.skipUnless(shutil.which("fakeroot") and shutil.which("dpkg") and
                         shutil.which("dpkg-deb"),
                         "fakeroot, dpkg and dpkg-deb are required")
    def test_real_disposable_dpkg_diversion_install_upgrade_and_remove(self):
        # Only these generated scripts may run outside a disposable chroot.
        # This is never a production installation path or a host database.
        destination = self.root / "disposable-dpkg-target"
        database = destination / "var/lib/dpkg"
        database.mkdir(parents=True)
        (database / "status").write_text("")
        (database / "available").write_text("")
        original = "/usr/lib/compulab-deb-fixture-" + self.root.name + ".so"
        diverted = original + ".compulab-distrib"
        host_path = Path(original)
        self.assertFalse(host_path.exists() or host_path.is_symlink())
        vendor_payload = self.root / "vendor-payload"
        custom_payload = self.root / "custom-payload"
        self.put(vendor_payload / original.lstrip("/"), b"pristine vendor")
        self.put(custom_payload / original.lstrip("/"), b"custom version 1")
        archives = self.root / "real-packages"
        vendor = MODULE.build_package(
            vendor_payload, archives, "compulab-fixture-vendor", "1",
            architecture="all")
        custom = MODULE.build_package(
            custom_payload, archives, "compulab-fixture-custom", "1",
            architecture="all", diversions=((original, diverted),))
        self.put(custom_payload / original.lstrip("/"), b"custom version 2")
        upgrade = MODULE.build_package(
            custom_payload, archives, "compulab-fixture-custom", "2",
            architecture="all", diversions=((original, diverted),))

        def install(*arguments):
            self.assertEqual(database.resolve(), database)
            self.assertTrue(database.is_relative_to(self.root))
            self.assertNotEqual(database, Path("/var/lib/dpkg"))
            result = subprocess.run(
                ["fakeroot", "dpkg", "--root=" + str(destination),
                 "--force-script-chrootless", *map(str, arguments)],
                text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)
            self.assertFalse(host_path.exists() or host_path.is_symlink())

        def diversion_owner():
            return subprocess.check_output(
                ["dpkg-divert", "--root", destination, "--listpackage",
                 original], text=True).strip()

        install("--install", vendor)
        install("--install", custom)
        self.assertEqual((destination / original.lstrip("/")).read_bytes(),
                         b"custom version 1")
        self.assertEqual((destination / diverted.lstrip("/")).read_bytes(),
                         b"pristine vendor")
        self.assertEqual(diversion_owner(), "compulab-fixture-custom")
        listed = subprocess.check_output(
            ["dpkg-query", "--admindir=" + str(database), "--listfiles",
             "compulab-fixture-custom"], text=True).splitlines()
        self.assertIn(original, listed)
        install("--install", upgrade)
        self.assertEqual((destination / original.lstrip("/")).read_bytes(),
                         b"custom version 2")
        self.assertEqual((destination / diverted.lstrip("/")).read_bytes(),
                         b"pristine vendor")
        install("--remove", "compulab-fixture-custom")
        self.assertEqual((destination / original.lstrip("/")).read_bytes(),
                         b"pristine vendor")
        self.assertFalse((destination / diverted.lstrip("/")).exists())
        self.assertEqual(diversion_owner(), "")
        ownership = subprocess.check_output(
            ["dpkg-query", "--admindir=" + str(database), "--search",
             original], text=True)
        self.assertIn("compulab-fixture-vendor: " + original, ownership)
        self.assertNotIn("compulab-fixture-custom", ownership)


if __name__ == "__main__":
    unittest.main()

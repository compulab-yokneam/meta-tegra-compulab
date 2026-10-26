#!/usr/bin/env python3
"""Unprivileged fixtures: never apt, chroot, mount, SDK Manager or a DUT."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("provision_runtime", HERE / "provision-runtime.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProvisionRuntimeTests(unittest.TestCase):
    def test_apt_guard_rejects_kernel_driver_and_removals(self):
        for text in ("Inst nvidia-l4t-kernel (39.2.1 local)",
                     "Inst nvidia-l4t-camera:arm64 (39.2.1 local)",
                     "Remv libglib2.0-0t64 [2.80]", "Remv nvidia-l4t-gstreamer"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                module.check_apt_plan(text)

    def test_apt_guard_allows_only_gst_nvidia_and_ubuntu_dependencies(self):
        module.check_apt_plan("Inst nvidia-l4t-gstreamer:arm64 (39.2.1 local)\n"
                              "Inst libgtk-3-dev (3.24 Ubuntu)\n")

    def test_bad_asset_hash_fails_without_extracting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile.nito").write_bytes(b"fixture")
            with self.assertRaises(ValueError):
                module.verify_assets({"assets": [{"path": "profile.nito", "role": "nito",
                    "sha256": "0" * 64}]}, root)

    def test_source_only_bundle_then_assembled_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "maintained.sh").write_text("#!/bin/sh\nexit 0\n")
            module.write_manifest(source)
            original = (source / "SHA256SUMS").read_text()
            self.assertNotIn("sources/", original)
            assets = root / "assets"
            assets.mkdir()
            nested = b"fixture compressed source bytes"
            with tarfile.open(assets / "public.tbz2", "w:bz2") as archive:
                info = tarfile.TarInfo("Linux_for_Tegra/source/gst-fixture.tbz2")
                info.size = len(nested)
                archive.addfile(info, io.BytesIO(nested))
            (assets / "profile.nito").write_bytes(b"profile fixture")
            manifest = {"assets": [
                {"id": "publicsources", "path": "public.tbz2", "role": "source",
                 "sha256": module.digest(assets / "public.tbz2")},
                {"id": "nito", "path": "profile.nito", "role": "nito",
                 "sha256": module.digest(assets / "profile.nito")}],
                "gst_archives": {"gst-fixture.tbz2": module.hashlib.sha256(nested).hexdigest()}}
            destination = root / "assembled"
            module.verify_assets(manifest, assets)
            module.assemble_bundle(source, destination, assets, manifest)
            combined = (destination / "SHA256SUMS").read_text()
            self.assertIn("sources/gst-fixture.tbz2", combined)
            self.assertIn("nito/profile.nito", combined)
            self.assertEqual((source / "SHA256SUMS").read_text(), original)

    def test_source_archive_symlink_is_not_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "assets").mkdir()
            with tarfile.open(root / "assets/public.tbz2", "w:bz2") as archive:
                info = tarfile.TarInfo("Linux_for_Tegra/source/gst-fixture.tbz2")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                archive.addfile(info)
            with self.assertRaises(ValueError):
                module.assemble_bundle(root / "source", root / "output", root / "assets",
                    {"assets": [{"id": "publicsources", "path": "public.tbz2"}],
                     "gst_archives": {"gst-fixture.tbz2": "0" * 64}})

    def test_clean_default_plan_does_not_require_proprietary_bundle_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "Linux_for_Tegra"
            target = sdk / "rootfs"
            for path in ("usr/lib", "var/lib/dpkg", "boot",
                         "usr/lib/aarch64-linux-gnu/nvidia",
                         "opt/nvidia/l4t-gpu-libs/nvgpu"):
                (target / path).mkdir(parents=True, exist_ok=True)
            (sdk / "flash.sh").write_text("fixture only")
            (target / "usr/lib/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            (target / "var/lib/dpkg/status").write_text("\n\n".join(
                f"Package: {name}\nStatus: install ok installed\nVersion: 39.2.1-20260806224157"
                for name in ("nvidia-l4t-core", "nvidia-l4t-camera", "nvidia-l4t-multimedia")))
            for path in module.PRESERVE:
                (target / path).parent.mkdir(parents=True, exist_ok=True)
                (target / path).write_bytes(b"unchanged fixture")
            (root / "assets").mkdir()
            (root / "assets.json").write_text('{"assets": []}')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = module.main(["--sdk-root", str(sdk), "--work-dir", str(root / "new-work"),
                    "--assets-dir", str(root / "assets"), "--asset-manifest", str(root / "assets.json"),
                    "--bundle-source", str(HERE / "runtime")])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["action"], "read-only plan")
            self.assertFalse((root / "new-work").exists())
            self.assertFalse((sdk / "compulab").exists())

    def test_execute_never_implicitly_sudos(self):
        with patch.object(module.os, "geteuid", return_value=1000), self.assertRaises(ValueError):
            module.execute(None, {}, None)

    def test_target_environment_cannot_inherit_bitbake_flags(self):
        with patch.object(module, "run", return_value="") as command:
            module.chroot(Path("/fixture"), ["true"])
            argv = command.call_args.args[0]
            self.assertEqual(argv[:4], ["chroot", Path("/fixture"), "/usr/bin/env", "-i"])
            self.assertIn("PATH=/usr/sbin:/usr/bin:/sbin:/bin", argv)

    def test_binfmt_requires_enabled_persistent_interpreter_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binfmt"
            self.assertFalse(module.persistent_binfmt(path))
            for text, expected in (("enabled\ninterpreter /usr/F/qemu\nflags: P\n", False),
                                   ("disabled\nflags: F\n", False),
                                   ("enabled\nflags: POF\n", True)):
                path.write_text(text)
                self.assertEqual(module.persistent_binfmt(path), expected)

    def test_asset_manifest_has_exact_native_inputs(self):
        manifest = json.loads((HERE / "runtime-assets.json").read_text())
        self.assertEqual(len([a for a in manifest["assets"] if a["role"] == "runtime"]), 10)
        self.assertEqual(len([a for a in manifest["assets"] if a["role"] == "build"]), 8)
        for asset in manifest["assets"]:
            self.assertEqual(len(asset["sha256"]), 64)
            self.assertNotIn("/home/", json.dumps(asset))
            if asset["role"] in ("runtime", "build"):
                self.assertTrue(asset["path"].endswith(("_arm64.deb", "_all.deb")))


if __name__ == "__main__":
    unittest.main(verbosity=2)

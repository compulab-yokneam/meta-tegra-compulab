#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary-fixture rootfs tests; no real privilege, namespace or chroot."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "tools/customize-rootfs.py"
SPEC = importlib.util.spec_from_file_location("sdk_customize_rootfs", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def snapshot(root):
    result = {}
    for path in [root, *root.rglob("*")]:
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        value = (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_ino)
        if path.is_symlink():
            result[relative] = ("link", str(path.readlink()), *value)
        elif path.is_file():
            result[relative] = ("file", path.read_bytes(), *value)
        else:
            result[relative] = ("directory", *value)
    return result


class CustomizeRootfsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdk-customize-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.sdk = self.base / "sdk"
        self.root = self.sdk / "rootfs"
        for name in ("usr/lib", "usr/bin", "usr/sbin", "etc", "proc", "dev", "sys", "run"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.sdk / "flash.sh").write_text("#!/bin/sh\nexit 97\n")
        (self.root / "usr/lib/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
        (self.root / "etc/nv_tegra_release").write_text("# R39 (release), REVISION: 2.1,\n")
        arm64 = b"\x7fELF\x02\x01" + b"\0" * 12 + (183).to_bytes(2, "little")
        for name in ("bash", "env"):
            (self.root / "usr/bin" / name).write_bytes(arm64)
        self.policy = self.root / "usr/sbin/policy-rc.d"
        self.policy.write_bytes(b"#!/bin/sh\n# Original policy\nexit 0\n")
        self.policy.chmod(0o750)
        self.resolver = self.root / "etc/resolv.conf"
        self.resolver.write_text("nameserver 192.0.2.10\n")
        self.resolver.chmod(0o640)
        self.mountinfo = self.base / "mountinfo"
        self.mountinfo.write_text("")
        self.host_resolver = self.base / "host-resolv.conf"
        self.host_resolver.write_text("nameserver 192.0.2.1\n")
        self.lock = self.base / "sdk-global.lock"
        self.binfmt = self.base / "binfmt"
        self.interpreter = self.base / "qemu-fixture"
        self.interpreter.write_text("Not executable; never invoked.\n")
        self.binfmt.write_text("enabled\ninterpreter %s\nflags: POCF\n" % self.interpreter)
        for name, value in (("GLOBAL_LOCK", self.lock), ("MOUNTINFO", self.mountinfo),
                            ("RESOLVER", self.host_resolver), ("BINFMT", self.binfmt)):
            patcher = mock.patch.object(MODULE, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(MODULE.platform, "machine", return_value="aarch64")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.environment = {"SUDO_UID": str(os.getuid()), "SUDO_GID": str(os.getgid()),
                            "PATH": "/usr/bin:/bin", "TERM": "xterm"}

    @contextlib.contextmanager
    def backend(self, fail=None):
        commands, mounts = [], {}
        def run(command):
            command = [str(value) for value in command]
            commands.append(command)
            if command[0] == "mount" and "-t" in command:
                if fail == command[-1]:
                    raise ValueError("Injected mount failure")
                mounts[command[-1]] = 100 + len(commands)
            elif command[0] == "umount":
                mounts.pop(command[-1], None)
            return ""
        with mock.patch.object(MODULE, "host_run", side_effect=run), \
                mock.patch.object(MODULE.os, "unshare") as unshare, \
                mock.patch.object(MODULE, "mounts_below", return_value=[]), \
                mock.patch.object(MODULE, "mount_identity", side_effect=lambda path: mounts.get(str(path))):
            yield commands, mounts, unshare

    def execute_fixture(self, command_status=0, cleanup=None, child_errors=None,
                        prepare_error=None):
        runtime = mock.Mock()
        runtime.cleanup.return_value = cleanup or []
        if prepare_error:
            runtime.prepare.side_effect = prepare_error
        with mock.patch.object(MODULE.os, "geteuid", return_value=0), \
                mock.patch.object(MODULE, "sdk_lock", return_value=contextlib.nullcontext()), \
                mock.patch.object(MODULE, "signal_handlers", return_value=contextlib.nullcontext()), \
                mock.patch.object(MODULE, "Runtime", return_value=runtime), \
                mock.patch.object(MODULE, "run_chroot", return_value=(command_status, child_errors or [])), \
                contextlib.redirect_stderr(io.StringIO()):
            result = MODULE.execute(self.sdk, ["/usr/bin/true"])
        return result, runtime

    def test_read_only_check_has_no_privileged_or_filesystem_side_effects(self):
        before = snapshot(self.base)
        output = io.StringIO()
        with mock.patch.object(MODULE, "host_run", side_effect=AssertionError("runtime reached")), \
                mock.patch.object(MODULE.os, "unshare", side_effect=AssertionError("namespace reached")), \
                mock.patch.object(MODULE, "sdk_lock", side_effect=AssertionError("lock reached")), \
                contextlib.redirect_stdout(output):
            self.assertEqual(MODULE.main(["--sdk-root", str(self.sdk), "--check"]), 0)
        self.assertEqual(json.loads(output.getvalue())["rootfs"], str(self.root))
        self.assertEqual(snapshot(self.base), before)

    def test_rejects_relative_broad_and_symlinked_sdk_paths(self):
        alias = self.base / "sdk-alias"
        alias.symlink_to(self.sdk)
        for path in ("relative", "/", str(alias)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                MODULE.check_sdk(path)

    def test_rejects_symlink_rootfs_before_touching_foreign_tree(self):
        original = self.base / "foreign-root"
        self.root.rename(original)
        self.root.symlink_to(original)
        before = snapshot(self.base)
        with self.assertRaisesRegex(ValueError, "canonical"):
            MODULE.check_sdk(self.sdk)
        self.assertEqual(snapshot(self.base), before)

    def test_rejects_symlinked_transient_parent(self):
        original = self.root / "usr/sbin-original"
        (self.root / "usr/sbin").rename(original)
        (self.root / "usr/sbin").symlink_to(original)
        with self.assertRaisesRegex(ValueError, "directory"):
            MODULE.check_sdk(self.sdk)

    def test_rejects_wrong_ubuntu_l4t_or_elf_architecture(self):
        for relative, invalid in (("usr/lib/os-release", b'ID=ubuntu\nVERSION_ID="22.04"\n'),
                                  ("etc/nv_tegra_release", b"# R39 (release), REVISION: 1.0,\n"),
                                  ("usr/bin/bash", b"Not AArch64"),
                                  ("usr/bin/env", b"Not AArch64")):
            path = self.root / relative
            previous = path.read_bytes()
            path.write_bytes(invalid)
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                MODULE.check_sdk(self.sdk)
            path.write_bytes(previous)

    def test_native_arm64_needs_no_binfmt_file(self):
        self.binfmt.unlink()
        self.assertTrue(MODULE.check_sdk(self.sdk)[2]["native_arm64"])

    def test_x86_64_requires_enabled_persistent_arm64_binfmt(self):
        with mock.patch.object(MODULE.platform, "machine", return_value="x86_64"):
            self.assertEqual(MODULE.check_sdk(self.sdk)[2]["interpreter"], str(self.interpreter))
            for content in ("disabled\nflags: F\n", "enabled\nflags: OC\n", "enabled\nflags: F\n"):
                self.binfmt.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    MODULE.check_sdk(self.sdk)

    def test_existing_mount_is_rejected_before_mutation(self):
        self.mountinfo.write_text("42 1 0:1 / %s/proc rw - proc proc rw\n" % self.root)
        before = snapshot(self.base)
        with self.assertRaisesRegex(ValueError, "already has mounts"):
            MODULE.check_sdk(self.sdk)
        self.assertEqual(snapshot(self.base), before)

    def test_mountinfo_decodes_escaped_paths(self):
        self.mountinfo.write_text("42 1 0:1 / /some/path\\040with-space rw - tmpfs tmpfs rw\n")
        self.assertEqual(MODULE.mount_records(), [(42, "/some/path with-space")])

    def test_overmounted_path_is_never_assumed_to_be_an_owned_mount(self):
        self.mountinfo.write_text("42 1 0:1 / %s/proc rw - proc proc rw\n"
                                  "99 1 0:2 / %s/proc rw - tmpfs tmpfs rw\n" %
                                  (self.root, self.root))
        with self.assertRaisesRegex(ValueError, "Ambiguous/overmounted"):
            MODULE.mount_identity(self.root / "proc")

    def test_rejects_stale_customization_backups(self):
        for relative in ("etc", "usr/sbin"):
            backup = self.root / relative / ".compulab-customize-stale"
            backup.mkdir()
            (backup / "original").write_text("Retained original\n")
            before = snapshot(self.base)
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "Retained"):
                MODULE.check_sdk(self.sdk)
            self.assertEqual(snapshot(self.base), before)
            (backup / "original").unlink()
            backup.rmdir()

    def test_rejects_special_temporary_leaf_without_opening_it(self):
        self.resolver.unlink()
        self.resolver.mkdir()
        with self.assertRaisesRegex(ValueError, "special/directory"):
            MODULE.check_sdk(self.sdk)

    def test_regular_temporary_leaf_restores_inode_bytes_and_mode(self):
        before = snapshot(self.root / "etc")
        leaf = MODULE.TemporaryLeaf(self.root, "etc/resolv.conf", b"temporary\n", 0o644)
        leaf.install()
        self.assertEqual(self.resolver.read_bytes(), b"temporary\n")
        leaf.restore()
        self.assertEqual(snapshot(self.root / "etc"), before)

    def test_absolute_symlink_leaf_never_writes_to_its_external_target(self):
        outside = self.base / "host-sentinel"
        outside.write_text("Do not modify\n")
        self.resolver.unlink()
        self.resolver.symlink_to(outside)
        before = snapshot(self.root / "etc")
        leaf = MODULE.TemporaryLeaf(self.root, "etc/resolv.conf", b"temporary\n", 0o644)
        leaf.install()
        self.assertEqual(outside.read_text(), "Do not modify\n")
        leaf.restore()
        self.assertEqual(snapshot(self.root / "etc"), before)
        self.assertEqual(outside.read_text(), "Do not modify\n")

    def test_missing_leaf_remains_missing_after_cleanup(self):
        self.policy.unlink()
        before = snapshot(self.root / "usr/sbin")
        leaf = MODULE.TemporaryLeaf(self.root, "usr/sbin/policy-rc.d", MODULE.POLICY, 0o755)
        leaf.install()
        leaf.restore()
        self.assertEqual(snapshot(self.root / "usr/sbin"), before)

    def test_exception_immediately_after_rename_still_restores_original(self):
        before = snapshot(self.root / "etc")
        replace = os.replace
        def failed_after_rename(source, target):
            replace(source, target)
            raise MODULE.Interrupted(signal.SIGTERM)
        leaf = MODULE.TemporaryLeaf(self.root, "etc/resolv.conf", b"temporary\n", 0o644)
        with mock.patch.object(MODULE.os, "replace", side_effect=failed_after_rename), \
                self.assertRaises(MODULE.Interrupted):
            leaf.install()
        leaf.restore()
        self.assertEqual(snapshot(self.root / "etc"), before)

    def test_leaf_install_defers_instead_of_dropping_pending_signals(self):
        leaf = MODULE.TemporaryLeaf(self.root, "etc/resolv.conf", b"temporary\n", 0o644)
        with mock.patch.object(MODULE.signal, "pthread_sigmask", return_value=set()) as mask:
            leaf.install()
        self.assertEqual(mask.call_args_list[0], mock.call(signal.SIG_BLOCK, MODULE.SIGNALS))
        self.assertEqual(mask.call_args_list[-1], mock.call(signal.SIG_SETMASK, set()))
        leaf.restore()

    def test_cleanup_never_recursively_deletes_an_unexpected_leaf_directory(self):
        leaf = MODULE.TemporaryLeaf(self.root, "etc/resolv.conf", b"temporary\n", 0o644)
        original = self.resolver.read_bytes()
        leaf.install()
        self.resolver.unlink()
        self.resolver.mkdir()
        (self.resolver / "user-file").write_text("Retain\n")
        with self.assertRaisesRegex(RuntimeError, "retained"):
            leaf.restore()
        self.assertEqual((leaf.backup / "original").read_bytes(), original)
        self.assertEqual((self.resolver / "user-file").read_text(), "Retain\n")

    def test_private_runtime_has_no_host_device_or_sysfs_binds(self):
        before_policy, before_dns = self.policy.read_bytes(), self.resolver.read_bytes()
        runtime = MODULE.Runtime(self.root, b"nameserver 192.0.2.1\n")
        with self.backend() as (commands, mounts, unshare):
            runtime.prepare()
            self.assertEqual(commands[0], ["mount", "--make-rprivate", "/"])
            unshare.assert_called_once_with(os.CLONE_NEWNS)
            self.assertFalse(any("--bind" in command or "devtmpfs" in command or
                                 "sysfs" in command for command in commands))
            self.assertIn(["mknod", "-m", "0666", str(self.root / "dev/tty"), "c", "5", "0"], commands)
            self.assertEqual(self.policy.read_bytes(), MODULE.POLICY)
            self.assertEqual(runtime.cleanup(), [])
            self.assertEqual([command[-1] for command in commands if command[0] == "umount"],
                             [str(self.root / name) for name in ("dev/pts", "dev", "proc", "sys", "run")])
            self.assertEqual(mounts, {})
        self.assertEqual(self.policy.read_bytes(), before_policy)
        self.assertEqual(self.resolver.read_bytes(), before_dns)

    def test_partial_mount_failure_restores_leaves_and_unmounts_only_owned_paths(self):
        before_policy, before_dns = self.policy.read_bytes(), self.resolver.read_bytes()
        runtime = MODULE.Runtime(self.root, b"nameserver 192.0.2.1\n")
        with self.backend(fail=str(self.root / "proc")) as (commands, mounts, _):
            with self.assertRaisesRegex(ValueError, "Injected"):
                runtime.prepare()
            self.assertEqual(runtime.cleanup(), [])
            self.assertEqual([command[-1] for command in commands if command[0] == "umount"],
                             [str(self.root / "sys"), str(self.root / "run")])
            self.assertEqual(mounts, {})
        self.assertEqual(self.policy.read_bytes(), before_policy)
        self.assertEqual(self.resolver.read_bytes(), before_dns)

    def test_pending_signal_after_mount_registration_unwinds_the_owned_mount(self):
        @contextlib.contextmanager
        def delayed_interrupt(_numbers):
            yield set()
            raise MODULE.Interrupted(signal.SIGTERM)
        runtime = MODULE.Runtime(self.root, b"nameserver 192.0.2.1\n")
        with self.backend() as (commands, mounts, _):
            with mock.patch.object(MODULE, "deferred_signals", side_effect=delayed_interrupt), \
                    self.assertRaises(MODULE.Interrupted):
                runtime.mount("tmpfs", "mode=0755", "tmpfs", "run")
            self.assertEqual(len(runtime.mounts), 1)
            self.assertEqual(runtime.cleanup(), [])
            self.assertEqual(mounts, {})
        self.assertIn(["umount", str(self.root / "run")], commands)

    def test_cleanup_refuses_to_unmount_replaced_foreign_mount(self):
        runtime = MODULE.Runtime(self.root, b"nameserver 192.0.2.1\n")
        with self.backend() as (commands, mounts, _):
            runtime.prepare()
            mounts[str(self.root / "proc")] = 99999
            errors = runtime.cleanup()
        self.assertTrue(any("foreign mount" in error for error in errors))
        self.assertNotIn(["umount", str(self.root / "proc")], commands)

    def test_foreign_mounts_prevent_source_file_restoration_through_them(self):
        runtime = MODULE.Runtime(self.root, b"nameserver 192.0.2.1\n")
        original = self.resolver.read_bytes()
        with self.backend():
            runtime.prepare()
            with mock.patch.object(MODULE, "mounts_below", return_value=[(9999, str(self.root / "etc"))]):
                errors = runtime.cleanup()
        self.assertTrue(any("refusing file restoration" in error for error in errors))
        self.assertEqual((runtime.leaves[1].backup / "original").read_bytes(), original)
        self.assertEqual(self.resolver.read_bytes(), b"nameserver 192.0.2.1\n")

    def test_execution_locks_global_and_sdk_paths_as_the_invoking_user(self):
        with mock.patch.dict(os.environ, self.environment), \
                mock.patch.object(MODULE.os, "fchown") as chown:
            with MODULE.sdk_lock(self.sdk):
                self.assertTrue(self.lock.exists())
                self.assertTrue((self.sdk / ".compulab-customize-rootfs.lock").exists())
        self.assertEqual(chown.call_count, 2)
        for path in (self.lock, self.sdk / ".compulab-customize-rootfs.lock"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_symlink_or_public_lock_is_never_repaired(self):
        sentinel = self.base / "foreign"
        sentinel.write_text("Retain\n")
        self.lock.symlink_to(sentinel)
        with mock.patch.dict(os.environ, self.environment), self.assertRaises(OSError):
            with MODULE.sdk_lock(self.sdk):
                self.fail("Lock unexpectedly acquired")
        self.assertEqual(sentinel.read_text(), "Retain\n")
        self.lock.unlink()
        self.lock.write_text("")
        self.lock.chmod(0o644)
        with mock.patch.dict(os.environ, self.environment), self.assertRaisesRegex(ValueError, "private"):
            with MODULE.sdk_lock(self.sdk):
                self.fail("Lock unexpectedly acquired")
        self.assertEqual(stat.S_IMODE(self.lock.stat().st_mode), 0o644)

    def test_busy_lock_fails_without_runtime_operations(self):
        with mock.patch.dict(os.environ, self.environment), \
                mock.patch.object(MODULE.os, "fchown"), \
                mock.patch.object(MODULE.fcntl, "flock", side_effect=BlockingIOError), \
                self.assertRaisesRegex(ValueError, "holds the SDK lock"):
            with MODULE.sdk_lock(self.sdk):
                self.fail("Busy lock unexpectedly acquired")

    def test_execution_refuses_an_unprivileged_helper_before_writes(self):
        before = snapshot(self.base)
        with mock.patch.object(MODULE.os, "geteuid", return_value=1001), \
                self.assertRaisesRegex(ValueError, "requires sudo/root"):
            MODULE.execute(self.sdk, ["/usr/bin/true"])
        self.assertEqual(snapshot(self.base), before)

    def test_command_failure_status_is_preserved_after_cleanup(self):
        status, runtime = self.execute_fixture(command_status=7)
        self.assertEqual(status, 7)
        runtime.cleanup.assert_called_once_with(restore_files=True)

    def test_cleanup_failure_fails_success_but_preserves_existing_command_failure(self):
        for requested, expected in ((0, 1), (7, 7)):
            with self.subTest(requested=requested):
                self.assertEqual(self.execute_fixture(command_status=requested, cleanup=["failed cleanup"])[0], expected)

    def test_setup_signal_preserves_signal_exit_status_and_unwinds(self):
        status, runtime = self.execute_fixture(prepare_error=MODULE.Interrupted(signal.SIGTERM))
        self.assertEqual(status, 143)
        runtime.cleanup.assert_called_once_with(restore_files=True)

    def test_cli_preserves_signals_raised_during_lock_acquisition(self):
        for number in MODULE.SIGNALS:
            with self.subTest(number=number), \
                    mock.patch.object(MODULE, "execute", side_effect=MODULE.Interrupted(number)), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(MODULE.main(["--sdk-root", str(self.sdk), "--execute", "--", "true"]),
                                 128 + number)

    def test_surviving_descendants_fail_and_retain_transient_original_backups(self):
        status, runtime = self.execute_fixture(child_errors=["Uninterruptible descendant"])
        self.assertEqual(status, 1)
        runtime.cleanup.assert_called_once_with(restore_files=False)

    def test_command_arguments_are_not_parsed_or_evaluated_on_host(self):
        command = ["/bin/sh", "-c", "printf '%s' '$HOME; $(false)'", "", "with space"]
        self.assertEqual(MODULE.command_args(command), command)
        for invalid in (["-c"], ["X=value"], ["/bin/sh", "bad\0argument"]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.command_args(invalid)

    def test_child_drain_signals_and_reaps_adopted_children_in_any_process_group(self):
        with mock.patch.object(MODULE, "owned_children", side_effect=[[123], [456], []]), \
                mock.patch.object(MODULE.os, "waitpid", side_effect=ChildProcessError), \
                mock.patch.object(MODULE, "signal_owned_child") as send, \
                mock.patch.object(MODULE.time, "sleep"):
            self.assertEqual(MODULE.drain_children(), [])
        self.assertEqual(send.call_args_list, [mock.call(123, signal.SIGTERM), mock.call(456, signal.SIGTERM)])

    def test_child_drain_escalates_and_reports_uninterruptible_survivors(self):
        with mock.patch.object(MODULE, "owned_children", return_value=[123]), \
                mock.patch.object(MODULE.os, "waitpid", side_effect=ChildProcessError), \
                mock.patch.object(MODULE, "signal_owned_child") as send, \
                mock.patch.object(MODULE.time, "monotonic", side_effect=[0, 0, 4, 10]), \
                mock.patch.object(MODULE.time, "sleep"):
            errors = MODULE.drain_children()
        self.assertIn(mock.call(123, signal.SIGKILL), send.call_args_list)
        self.assertTrue(any("did not exit" in error for error in errors))

    def test_subreaper_is_scoped_and_restored_without_real_prctl(self):
        libc = mock.Mock()
        libc.prctl.return_value = 0
        with mock.patch.object(MODULE.ctypes, "CDLL", return_value=libc):
            with MODULE.subreaper() as errors:
                self.assertEqual(errors, [])
        self.assertEqual([call.args[0] for call in libc.prctl.call_args_list], [37, 36, 36])
        self.assertEqual(libc.prctl.call_args_list[-1].args[1], 0)

    @contextlib.contextmanager
    def mocked_chroot(self, tty=False):
        process = mock.Mock(pid=4321)
        process.wait.return_value = 0
        with mock.patch.object(MODULE, "subreaper", return_value=contextlib.nullcontext([])), \
                mock.patch.object(MODULE.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(MODULE, "drain_children", return_value=[]) as drain, \
                mock.patch.object(MODULE.sys.stdin, "isatty", return_value=tty), \
                mock.patch.object(MODULE.os, "tcgetpgrp", return_value=os.getpgrp()), \
                mock.patch.object(MODULE.os, "tcsetpgrp") as foreground, \
                mock.patch.object(MODULE.os, "killpg") as kill, \
                contextlib.redirect_stderr(io.StringIO()):
            yield process, popen, drain, foreground, kill

    def test_chroot_uses_clean_target_environment_and_exact_argv(self):
        with self.mocked_chroot() as (_, popen, drain, _, _):
            self.assertEqual(MODULE.run_chroot(self.root, ["printf", "literal; $(false)"]), (0, []))
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:4], ["chroot", str(self.root), "/usr/bin/env", "-i"])
        self.assertEqual(argv[-2:], ["printf", "literal; $(false)"])
        self.assertEqual(popen.call_args.kwargs["process_group"], 0)
        self.assertEqual(set(popen.call_args.kwargs["env"]), {"PATH", "LC_ALL"})
        drain.assert_called_once()

    def test_terminal_setup_failure_stops_child_and_drains_before_cleanup(self):
        with self.mocked_chroot(tty=True) as (_, _, drain, foreground, _), \
                mock.patch.object(MODULE, "stop_process") as stop:
            foreground.side_effect = [OSError("Injected foreground error"), None]
            status, errors = MODULE.run_chroot(self.root, ["/usr/bin/true"])
        self.assertEqual(status, 1)
        self.assertEqual(errors, [])
        stop.assert_called_once()
        drain.assert_called_once()

    def test_interruption_before_wait_still_stops_registered_child(self):
        with self.mocked_chroot(tty=True) as (_, _, drain, foreground, _), \
                mock.patch.object(MODULE, "stop_process") as stop:
            foreground.side_effect = [MODULE.Interrupted(signal.SIGHUP), None]
            self.assertEqual(MODULE.run_chroot(self.root, ["/usr/bin/true"]), (129, []))
        stop.assert_called_once()
        drain.assert_called_once()

    def test_pending_signal_after_spawn_registration_still_stops_the_child(self):
        @contextlib.contextmanager
        def delayed_interrupt(_numbers):
            yield set()
            raise MODULE.Interrupted(signal.SIGTERM)
        with self.mocked_chroot() as (_, _, drain, _, _), \
                mock.patch.object(MODULE, "deferred_signals", side_effect=delayed_interrupt), \
                mock.patch.object(MODULE, "stop_process") as stop:
            self.assertEqual(MODULE.run_chroot(self.root, ["true"]), (143, []))
        stop.assert_called_once()
        drain.assert_called_once()

    def test_foreground_is_restored_after_interactive_command(self):
        with self.mocked_chroot(tty=True) as (_, _, _, foreground, kill):
            self.assertEqual(MODULE.run_chroot(self.root, list(MODULE.DEFAULT_COMMAND)), (0, []))
        self.assertEqual([call.args[1] for call in foreground.call_args_list], [4321, os.getpgrp()])
        kill.assert_called_once_with(4321, signal.SIGCONT)

    def test_background_terminal_use_is_rejected_without_spawning_a_child(self):
        with self.mocked_chroot(tty=True) as (_, popen, _, _, _), \
                mock.patch.object(MODULE.os, "tcgetpgrp", return_value=os.getpgrp() + 1):
            self.assertEqual(MODULE.run_chroot(self.root, ["/usr/bin/true"]), (1, []))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

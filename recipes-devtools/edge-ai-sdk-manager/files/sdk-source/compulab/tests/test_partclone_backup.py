#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary partclone fixtures; never allocate loops or access host disks."""
import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / \
    "tools/create-partclone-backup.py"
SPEC = importlib.util.spec_from_file_location("sdk_partclone_backup", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PartcloneBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="partclone-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.sdk = self.root / "sdk"
        for relative in ("rootfs/etc", "rootfs/usr/lib", "compulab/host",
                         "bootloader", "kernel", "workdir"):
            (self.sdk / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.put(self.sdk / "flash.sh", "#!/bin/sh\nexit 97\n")
        self.put(self.sdk / "compulab-l4t.env", "# source fixture\n")
        self.put(self.sdk / "compulab/kernel-release.txt", "fixture-kernel\n")
        self.put(self.sdk / "compulab/host/image-builder.sh", "# fixture\n")
        self.put(self.sdk / "rootfs/etc/nv_tegra_release",
                 "# R39 (release), REVISION: 2.1,\n")
        self.put(self.sdk / "rootfs/usr/lib/os-release",
                 'ID=ubuntu\nVERSION_ID="24.04"\n')
        self.image = self.put(self.root / "disk.img", b"fixture-not-a-disk")
        self.image.chmod(0o600)
        self.output = self.sdk / "workdir/partclone.d"
        self.commands = []
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.object(
            MODULE.shutil, "which",
            side_effect=lambda name, **_: "/usr/bin/" + name))
        self.associated = self.patches.enter_context(mock.patch.object(
            MODULE, "associated_loops", return_value=[]))
        self.host_command = self.patches.enter_context(mock.patch.object(
            MODULE, "run", side_effect=AssertionError(
                "Unexpected host command; fixtures must intercept every call")))

    def put(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        contents = payload.encode() if isinstance(payload, str) else payload
        path.write_bytes(contents)
        return path

    def snapshot(self):
        result = {}
        for path in [self.root, *self.root.rglob("*")]:
            info = path.lstat()
            name = path.relative_to(self.root).as_posix()
            state = (info.st_uid, stat.S_IMODE(info.st_mode), info.st_ino)
            if path.is_symlink():
                result[name] = ("link", str(path.readlink()), *state)
            elif path.is_file():
                result[name] = ("file", path.read_bytes(), *state)
            else:
                result[name] = ("directory", *state)
        return result

    def inspect(self, **changes):
        arguments = dict(sdk_root=self.sdk, image=self.image,
                         output_root=self.output, compression="none")
        return MODULE.inspect(**(arguments | changes))

    def reject(self, **changes):
        before = self.snapshot()
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            self.inspect(**changes)
        self.assertEqual(self.snapshot(), before)
        self.host_command.assert_not_called()

    def test_check_is_read_only_and_does_not_create_default_output(self):
        before = self.snapshot()
        plan = self.inspect()
        self.assertIsInstance(plan, dict)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.snapshot(), before)
        self.host_command.assert_not_called()

    def test_existing_output_root_is_not_modified_by_check(self):
        self.output.mkdir(mode=0o700)
        self.put(self.output / "existing-backup/keep", "unrelated backup\n")
        before = self.snapshot()
        self.inspect()
        self.assertEqual(self.snapshot(), before)

    def test_missing_image_is_rejected_without_output_creation(self):
        self.reject(image=self.root / "missing.img")

    def test_relative_image_is_rejected(self):
        self.reject(image=Path("disk.img"))

    def test_image_directory_is_rejected(self):
        directory = self.root / "directory.img"
        directory.mkdir()
        self.reject(image=directory)

    def test_image_without_img_suffix_is_rejected(self):
        self.reject(image=self.put(self.root / "image.bin", b"not a disk"))

    def test_image_symlink_and_symlinked_parent_are_rejected(self):
        alias = self.root / "alias.img"
        alias.symlink_to(self.image)
        self.reject(image=alias)
        parent = self.root / "alias-parent"
        parent.symlink_to(self.image.parent, target_is_directory=True)
        self.reject(image=parent / self.image.name)

    def test_hardlinked_image_is_rejected(self):
        linked = self.root / "linked.img"
        linked.hardlink_to(self.image)
        self.reject()

    def test_group_or_other_writable_image_is_rejected(self):
        for mode in (0o620, 0o602):
            with self.subTest(mode=oct(mode)):
                self.image.chmod(mode)
                self.reject()

    def test_physical_disk_and_kernel_paths_are_rejected(self):
        for name in ("/dev/nvme0n1", "/dev/loop0", "/proc/example.img",
                     "/sys/example.img"):
            with self.subTest(path=name):
                self.reject(image=Path(name))

    def test_changed_sdk_root_is_rejected(self):
        self.reject(sdk_root=self.root)

    def test_symlinked_sdk_root_is_rejected(self):
        alias = self.root / "sdk-alias"
        alias.symlink_to(self.sdk, target_is_directory=True)
        self.reject(sdk_root=alias)

    def test_output_cannot_overlap_protected_sdk_payloads(self):
        for relative in ("rootfs/backup", "bootloader/backup", "kernel/backup",
                         "compulab/backup"):
            with self.subTest(path=relative):
                self.reject(output_root=self.sdk / relative)

    def test_output_cannot_be_a_symlink_or_use_symlink_parent(self):
        destination = self.root / "backup-target"
        destination.mkdir()
        alias = self.root / "backup-alias"
        alias.symlink_to(destination, target_is_directory=True)
        self.reject(output_root=alias)
        self.reject(output_root=alias / "new-output")

    def test_group_or_other_writable_output_is_rejected(self):
        self.output.mkdir(mode=0o700)
        for mode in (0o720, 0o702):
            with self.subTest(mode=oct(mode)):
                self.output.chmod(mode)
                self.reject()

    def test_existing_associated_loop_is_rejected(self):
        self.associated.return_value = ["/dev/loop90"]
        self.reject()

    def test_unsupported_compression_is_rejected(self):
        for value in ("zstd", "gzip", "xz; touch bad", ""):
            with self.subTest(value=value):
                self.reject(compression=value)

    def test_missing_prerequisites_fail_without_modification(self):
        with mock.patch.object(MODULE.shutil, "which", return_value=None):
            self.reject()

    def test_execute_refuses_ordinary_user_before_any_side_effect(self):
        plan = self.inspect()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "sudo"):
            MODULE.execute(plan)
        self.assertEqual(self.snapshot(), before)

    def test_default_cli_prints_read_only_plan_and_never_executes(self):
        before = self.snapshot()
        output = io.StringIO()
        with mock.patch.object(MODULE, "execute") as execute, \
                contextlib.redirect_stdout(output):
            status = MODULE.main([
                "--sdk-root", str(self.sdk), "--image", str(self.image),
                "--output-root", str(self.output)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"],
                         "read-only inspection")
        execute.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_cli_command_failure_reports_stderr_and_preserves_exit_status(self):
        diagnostic = "losetup: detach failed: Device or resource busy"
        failure = subprocess.CalledProcessError(
            41, ["losetup", "--detach", "/dev/loop123"],
            stderr=diagnostic + "\n")
        for returncode, expected in ((41, 41), (-signal.SIGTERM, 143)):
            with self.subTest(returncode=returncode):
                failure.returncode = returncode
                output, errors = io.StringIO(), io.StringIO()
                with mock.patch.object(MODULE, "inspect", return_value={}), \
                        mock.patch.object(MODULE, "execute",
                                          side_effect=failure), \
                        contextlib.redirect_stdout(output), \
                        contextlib.redirect_stderr(errors):
                    status = MODULE.main([
                        "--sdk-root", str(self.sdk),
                        "--image", str(self.image),
                        "--output-root", str(self.output), "--execute"])
                self.assertEqual(status, expected)
                self.assertIn(diagnostic, errors.getvalue())
                self.assertEqual(output.getvalue(), "")

    def test_existing_lock_avoids_protected_regular_creation_flag(self):
        lock = self.put(self.root / "existing.lock", "preserve this lock\n")
        lock.chmod(0o600)
        native_open, calls = os.open, []

        def protected_open(path, flags, *arguments, **keywords):
            if Path(path) == lock:
                calls.append(flags)
                if flags & os.O_CREAT:
                    raise PermissionError(errno.EACCES,
                                          "fs.protected_regular refusal")
            return native_open(path, flags, *arguments, **keywords)

        with mock.patch.object(MODULE.os, "open",
                               side_effect=protected_open), \
                mock.patch.object(MODULE.os, "fchown"):
            with MODULE.lock_file(lock, os.getuid(), os.getgid()):
                self.assertEqual(lock.read_text(), "preserve this lock\n")
        self.assertEqual(calls, [os.O_RDWR | os.O_NOFOLLOW])

    def test_missing_lock_is_created_exclusively(self):
        lock = self.root / "new.lock"
        native_open, calls = os.open, []

        def tracked_open(path, flags, *arguments, **keywords):
            if Path(path) == lock:
                calls.append(flags)
            return native_open(path, flags, *arguments, **keywords)

        with mock.patch.object(MODULE.os, "open", side_effect=tracked_open), \
                mock.patch.object(MODULE.os, "fchown"):
            with MODULE.lock_file(lock, os.getuid(), os.getgid()):
                self.assertTrue(lock.is_file())
        self.assertEqual(calls[0], os.O_RDWR | os.O_NOFOLLOW)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1] & os.O_CREAT)
        self.assertTrue(calls[1] & os.O_EXCL)
        self.assertTrue(calls[1] & os.O_NOFOLLOW)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_lock_creation_race_reopens_existing_without_overwrite(self):
        lock = self.root / "racing.lock"
        native_open, calls = os.open, []

        def racing_open(path, flags, *arguments, **keywords):
            if Path(path) == lock:
                calls.append(flags)
                if flags & os.O_CREAT:
                    self.assertTrue(flags & os.O_EXCL)
                    self.put(lock, "other creator's lock\n")
                    lock.chmod(0o600)
                    raise FileExistsError(errno.EEXIST, "created by racer")
            return native_open(path, flags, *arguments, **keywords)

        with mock.patch.object(MODULE.os, "open", side_effect=racing_open), \
                mock.patch.object(MODULE.os, "fchown"):
            with MODULE.lock_file(lock, os.getuid(), os.getgid()):
                self.assertEqual(lock.read_text(), "other creator's lock\n")
        self.assertEqual(len(calls), 3)
        self.assertFalse(calls[-1] & os.O_CREAT)

    def test_lock_symlink_is_rejected_without_modifying_target(self):
        target = self.put(self.root / "lock-target", "unrelated data\n")
        target.chmod(0o600)
        lock = self.root / "symlink.lock"
        lock.symlink_to(target)
        with self.assertRaises(OSError):
            with MODULE.lock_file(lock, os.getuid(), os.getgid()):
                self.fail("symlinked coordination lock was accepted")
        self.assertEqual(target.read_text(), "unrelated data\n")
        self.assertTrue(lock.is_symlink())

    @contextlib.contextmanager
    def block_statistics(self, devices):
        native_stat = Path.stat

        def simulated(path, *arguments, **keywords):
            if str(path) in devices:
                major, minor = devices[str(path)]
                return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600,
                                       st_rdev=os.makedev(major, minor))
            return native_stat(path, *arguments, **keywords)

        with mock.patch.object(Path, "stat", new=simulated):
            yield

    def loop_fixture(self):
        loop = "/dev/loop123"
        expected = MODULE.identity(self.image)
        mapping = dict(name=loop, **{
            "back-file": str(self.image), "back-ino": expected["inode"],
            "back-maj:min": "%d:%d" % (os.major(expected["device"]),
                                         os.minor(expected["device"])),
            "ro": True, "partscan": True, "offset": 0, "sizelimit": 0,
        })
        system = self.root / "sys-class-block"
        (system / "loop123/holders").mkdir(parents=True, exist_ok=True)
        return loop, expected, mapping, system

    def test_loop_mapping_requires_read_only_exact_owned_backing(self):
        loop, expected, mapping, system = self.loop_fixture()
        with self.block_statistics({loop: (7, 123)}), \
                mock.patch.object(MODULE, "SYS_BLOCK", system), \
                mock.patch.object(MODULE, "loop_record", return_value=mapping):
            self.assertEqual(MODULE.verify_loop(loop, self.image, expected),
                             mapping)
            for key, invalid in (("back-file", "/dev/nvme0n1"),
                                 ("back-ino", expected["inode"] + 1),
                                 ("back-maj:min", "1:2"), ("ro", False),
                                 ("partscan", False), ("offset", 512),
                                 ("sizelimit", 1024)):
                with self.subTest(field=key):
                    changed = dict(mapping, **{key: invalid})
                    with mock.patch.object(MODULE, "loop_record",
                                           return_value=changed):
                        with self.assertRaises(ValueError):
                            MODULE.verify_loop(loop, self.image, expected)

    def test_modified_image_fails_but_cleanup_checks_old_binding(self):
        loop, expected, mapping, system = self.loop_fixture()
        self.image.write_bytes(b"a concurrently modified input image")
        with self.block_statistics({loop: (7, 123)}), \
                mock.patch.object(MODULE, "SYS_BLOCK", system), \
                mock.patch.object(MODULE, "loop_record", return_value=mapping):
            with self.assertRaisesRegex(ValueError, "changed"):
                MODULE.verify_loop(loop, self.image, expected)
            MODULE.verify_loop(loop, self.image, expected, check_image=False)

    def test_mapping_rejects_physical_major_and_device_mapper_holders(self):
        loop, expected, mapping, system = self.loop_fixture()
        with self.block_statistics({loop: (259, 1)}), \
                mock.patch.object(MODULE, "SYS_BLOCK", system), \
                mock.patch.object(MODULE, "loop_record", return_value=mapping):
            with self.assertRaisesRegex(ValueError, "loop block"):
                MODULE.verify_loop(loop, self.image, expected)
        self.put(system / "loop123/holders/dm-0", "holder")
        with self.block_statistics({loop: (7, 123)}), \
                mock.patch.object(MODULE, "SYS_BLOCK", system), \
                mock.patch.object(MODULE, "loop_record", return_value=mapping):
            with self.assertRaisesRegex(ValueError, "holders"):
                MODULE.verify_loop(loop, self.image, expected)

    def test_loop_record_rejects_missing_duplicate_or_nonloop_records(self):
        with mock.patch.object(MODULE, "run") as command:
            for rows in ([], [{"name": "/dev/loop123"}] * 2,
                         [{"name": "/dev/nvme0n1"}]):
                with self.subTest(rows=rows):
                    command.return_value = subprocess.CompletedProcess(
                        [], 0, json.dumps({"loopdevices": rows}), "")
                    with self.assertRaises(ValueError):
                        MODULE.loop_record("/dev/loop123")
            command.reset_mock()
            with self.assertRaises(ValueError):
                MODULE.loop_record("/dev/nvme0n1")
            command.assert_not_called()

    @contextlib.contextmanager
    def partitions(self, filesystem="ext4"):
        loop, _, _, system = self.loop_fixture()
        node = loop + "p1"
        partition = system / "loop123/loop123p1"
        (partition / "holders").mkdir(parents=True)
        self.put(partition / "partition", "1\n")
        (system / "loop123p1").symlink_to(partition, target_is_directory=True)
        mounts = self.put(self.root / "mountinfo", "")
        table = dict(device=loop, label="gpt", sectorsize=512, partitions=[
            dict(node=node, start=2048, size=4096,
                 uuid="aaaa-bbbb", name="APP")])
        row = dict(name=node, type="part", pkname=loop, ro=True,
                   mountpoints=[None], **{"maj:min": "259:1"})
        tree = [dict(name=loop, type="loop", ro=True, children=[row])]
        probe = ("TYPE=%s\nUUID=fs-uuid\n" % filesystem
                 if filesystem else "")
        state = dict(table=table, tree=tree, probe=probe,
                     system=system, mounts=mounts, row=row, node=node)

        def command(*arguments, **keywords):
            arguments = list(map(str, arguments))
            self.commands.append(arguments)
            if arguments[:2] == ["sfdisk", "--json"]:
                payload = json.dumps({"partitiontable": state["table"]})
            elif arguments[:2] == ["lsblk", "--json"]:
                payload = json.dumps({"blockdevices": state["tree"]})
            elif arguments[0] == "blkid":
                payload = state["probe"]
            else:
                raise AssertionError("Unexpected partition command: " +
                                     repr(arguments))
            return subprocess.CompletedProcess(arguments, 0, payload, "")

        with mock.patch.object(MODULE, "run", side_effect=command), \
                mock.patch.object(MODULE, "SYS_BLOCK", system), \
                mock.patch.object(MODULE, "MOUNTINFO", mounts), \
                mock.patch.object(MODULE.time, "sleep"), \
                self.block_statistics({loop: (7, 123), node: (259, 1)}):
            yield loop, state

    def test_partition_parent_checks_allow_extended_loop_partition_major(self):
        with self.partitions() as (loop, state):
            rows = MODULE.partition_records(loop)
        self.assertEqual(rows, [dict(number=1, node=state["node"],
            filesystem="ext4", uuid="fs-uuid", partuuid="aaaa-bbbb",
            label="APP", start=2048, size=4096)])
        self.assertTrue(all(command[0] in ("sfdisk", "lsblk", "blkid")
                            for command in self.commands))

    def test_unknown_or_unformatted_partition_uses_raw_representation(self):
        for filesystem in ("crypto_LUKS", None):
            with self.subTest(filesystem=filesystem):
                with self.partitions(filesystem) as (loop, _):
                    row = MODULE.partition_records(loop)[0]
                self.assertEqual(row["filesystem"], "dd")
                self.assertEqual(row["uuid"], "aaaa-bbbb")
                # Each fixture has its own sysfs tree for the next subcase.
                shutil.rmtree(self.root / "sys-class-block")

    def test_partition_requires_unmounted_read_only_direct_loop_child(self):
        with self.partitions() as (loop, state):
            original = dict(state["row"])
            for changes in (dict(pkname="/dev/nvme0n1"), dict(ro=False),
                            dict(type="disk"), dict(mountpoints=["/mnt"]),
                            {"maj:min": "259:99"},
                            dict(children=[{"name": "/dev/dm-1"}])):
                with self.subTest(changes=changes):
                    state["row"].clear()
                    state["row"].update(original | changes)
                    with self.assertRaises(ValueError):
                        MODULE.partition_records(loop)
            state["row"].clear()
            state["row"].update(original)
            self.put(state["mounts"],
                     "20 1 259:1 / /mounted ro - ext4 /dev/loop123p1 ro\n")
            with self.assertRaises(ValueError):
                MODULE.partition_records(loop)

    def test_partition_scan_rejects_missing_and_foreign_children(self):
        with self.partitions() as (loop, state):
            state["tree"][0]["children"] = []
            with self.assertRaisesRegex(ValueError, "scan"):
                MODULE.partition_records(loop)
            state["tree"][0]["children"] = [dict(state["row"],
                                                   name="/dev/nvme0n1p1")]
            with self.assertRaisesRegex(ValueError, "scan"):
                MODULE.partition_records(loop)

    def test_filesystem_metadata_is_not_shell_evaluated(self):
        with self.partitions() as (loop, state):
            state["probe"] = "TYPE=ext4\nUUID=$(touch injected)\n"
            with self.assertRaisesRegex(ValueError, "UUID"):
                MODULE.partition_records(loop)
            state["probe"] = "TYPE=ext4\nUUID=good\nUUID=duplicate\n"
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                MODULE.partition_records(loop)
            state["probe"] = "TYPE=ext4\n"
            with self.assertRaisesRegex(ValueError, "UUID"):
                MODULE.partition_records(loop)
        self.assertFalse((self.root / "injected").exists())

    def partition(self, filesystem="ext4"):
        return dict(number=1, node="/dev/loop123p1", filesystem=filesystem,
                    uuid="fs-uuid", partuuid="part-uuid", label="APP",
                    start=2048, size=4096)

    @contextlib.contextmanager
    def output_fixture(self):
        directory = self.root / "payload"
        directory.mkdir(mode=0o700)
        output = MODULE.Output(directory)
        try:
            yield directory, output
        finally:
            os.close(output.fd)

    @contextlib.contextmanager
    def clone_processes(self, statuses=()):
        processes, calls = [], []

        class Process:
            def __init__(self, command, status):
                self.args, self.status = command, status
                self.returncode = None
                self.stdout = io.BytesIO(b"cloned partition")

            def wait(self):
                self.returncode = self.status
                return self.status

        def popen(command, **keywords):
            calls.append((command, keywords))
            status = (statuses[len(processes)]
                      if len(processes) < len(statuses) else 0)
            process = Process(command, status)
            processes.append(process)
            if keywords["stdout"] != subprocess.PIPE:
                keywords["stdout"].write(b"mock compressed image" if
                                         command[0] == "xz" else b"mock image")
            return process

        with mock.patch.object(MODULE.subprocess, "Popen", side_effect=popen), \
                mock.patch.object(MODULE, "stop") as stop:
            yield processes, calls, stop

    def test_partition_names_preserved_without_force_or_overwrite(self):
        with self.output_fixture() as (directory, output):
            for number, filesystem in enumerate(("ext4", "vfat", "dd"), 1):
                partition = dict(self.partition(filesystem), number=number)
                with self.clone_processes() as (_, calls, _):
                    result = MODULE.backup_partition(partition, output, "none")
                name = "part%d.%s.fs-uuid.partclone" % (number, filesystem)
                self.assertEqual(result["file"], name)
                self.assertEqual((directory / name).read_bytes(), b"mock image")
                command, arguments = calls[0]
                self.assertEqual(command[0], "partclone." + filesystem)
                self.assertEqual("-c" in command, filesystem != "dd")
                self.assertIn(output.fd, arguments["pass_fds"])
                self.assertTrue(arguments["start_new_session"])
                self.assertFalse(set(command) & {"-F", "-O", "-I", "-C"})

    def test_swap_is_only_a_uuid_marker_without_a_clone_process(self):
        with self.output_fixture() as (directory, output), \
                mock.patch.object(MODULE.subprocess, "Popen") as command:
            result = MODULE.backup_partition(self.partition("swap"),
                                             output, "xz")
            self.assertEqual(result["file"], "part1.swap.fs-uuid.partclone")
            self.assertEqual((directory / result["file"]).read_bytes(), b"")
        command.assert_not_called()

    def test_xz_uses_an_argv_pipeline_and_checks_both_children(self):
        with self.output_fixture() as (directory, output), \
                self.clone_processes() as (processes, calls, stop):
            result = MODULE.backup_partition(self.partition(), output, "xz")
            self.assertEqual(result["file"], "part1.ext4.fs-uuid.partclone.xz")
            self.assertEqual((directory / result["file"]).read_bytes(),
                             b"mock compressed image")
            self.assertEqual(calls[1][0], ["xz", "-T1", "-c"])
            self.assertIs(calls[1][1]["stdin"], processes[0].stdout)
            self.assertTrue(processes[0].stdout.closed)
            self.assertEqual(stop.call_count, 2)

    def test_compression_failure_preserves_status_and_stops_children(self):
        with self.output_fixture() as (_, output):
            with self.clone_processes((0, 37)) as (_, _, stop):
                with self.assertRaises(subprocess.CalledProcessError) as error:
                    MODULE.backup_partition(self.partition(), output, "xz")
                self.assertEqual(error.exception.returncode, 37)
                self.assertEqual(stop.call_count, 2)

    def test_output_refuses_existing_and_escaping_filenames(self):
        with self.output_fixture() as (_, output):
            output.write("keep", "original")
            with self.assertRaises(FileExistsError):
                output.write("keep", "replacement")
            for name in ("../escape", "/escape", ".", "..", "with/slash"):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        output.write(name, "bad")

    @contextlib.contextmanager
    def execution_fixture(self, *, backup_error=None, detach_error=None,
                          allocate_error=None, changed_mapping=False):
        plan = self.inspect()
        calls = []
        old_handlers = {number: signal.getsignal(number)
                        for number in MODULE.SIGNALS}

        def command(*arguments, **keywords):
            arguments = list(map(str, arguments))
            calls.append(arguments)
            if arguments[:2] == ["losetup", "--find"]:
                if allocate_error:
                    raise allocate_error
                return subprocess.CompletedProcess(arguments, 0,
                                                   "/dev/loop123\n", "")
            if arguments[:2] == ["losetup", "--detach"]:
                self.assertEqual(arguments,
                                 ["losetup", "--detach", "/dev/loop123"])
                if detach_error:
                    raise detach_error
                return subprocess.CompletedProcess(arguments, 0, "", "")
            if arguments[:2] == ["sfdisk", "--dump"]:
                return subprocess.CompletedProcess(arguments, 0,
                    "label: gpt\ndevice: /dev/loop123\nlast-lba: 99999\n"
                    "first-lba: 34\n"
                    "/dev/loop123p1 : start=2048,size=4096\n", "")
            if arguments[:2] == ["sfdisk", "--disk-id"]:
                return subprocess.CompletedProcess(arguments, 0,
                                                   "disk-uuid\n", "")
            raise AssertionError("Unexpected execute command: " +
                                 repr(arguments))

        def backup(partition, output, compression):
            if backup_error:
                raise backup_error
            name = "part1.ext4.fs-uuid.partclone"
            output.write(name, "partition image fixture")
            return dict(partition, file=name, representation="partclone")

        def verify(*arguments, **keywords):
            if changed_mapping and keywords.get("check_image") is False:
                raise ValueError("mapping changed before cleanup")

        with mock.patch.object(MODULE.os, "geteuid", return_value=0), \
                mock.patch.object(MODULE.os, "chown"), \
                mock.patch.object(MODULE.os, "fchown"), \
                mock.patch.object(MODULE, "lock_file",
                                  return_value=contextlib.nullcontext()), \
                mock.patch.object(MODULE, "run", side_effect=command), \
                mock.patch.object(MODULE, "verify_loop", side_effect=verify), \
                mock.patch.object(MODULE, "partition_records",
                                  return_value=[self.partition()]), \
                mock.patch.object(MODULE, "backup_partition",
                                  side_effect=backup), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            yield plan, calls, errors
        self.assertEqual({number: signal.getsignal(number)
                          for number in MODULE.SIGNALS}, old_handlers)

    def test_execution_writes_compatible_complete_manifest_and_checksums(self):
        original = self.image.read_bytes()
        with self.execution_fixture() as (plan, calls, _):
            target = MODULE.execute(plan)
        self.assertEqual(self.image.read_bytes(), original)
        self.assertTrue(target.is_relative_to(self.output))
        self.assertFalse((target / ".incomplete").exists())
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertIn("no QSPI", manifest["scope"])
        layout = (target / "disk.layout").read_text()
        self.assertNotIn("device:", layout)
        self.assertNotIn("last-lba:", layout)
        self.assertIn("first-lba: 34", layout)
        self.assertEqual((target / "disk.id").read_text(), "disk-uuid\n")
        for line in (target / "SHA256SUMS").read_text().splitlines():
            checksum, name = line.split("  ", 1)
            actual = hashlib.sha256((target / name).read_bytes()).hexdigest()
            self.assertEqual(actual, checksum)
        allocate, detach = [call for call in calls if call[0] == "losetup"]
        self.assertIn("--read-only", allocate)
        self.assertIn("--partscan", allocate)
        self.assertEqual(detach, ["losetup", "--detach", "/dev/loop123"])

    def test_failure_retains_partial_backup_and_detaches_only_owned_loop(self):
        failure = subprocess.CalledProcessError(23, ["mock-partclone"])
        with self.execution_fixture(backup_error=failure) as fixture:
            plan, calls, errors = fixture
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                MODULE.execute(plan)
            self.assertIs(raised.exception, failure)
            self.assertIn("Incomplete backup retained", errors.getvalue())
        target, = self.output.glob("backup-*")
        self.assertTrue((target / ".incomplete").is_file())
        self.assertFalse((target / "manifest.json").exists())
        self.assertEqual([call for call in calls if "--detach" in call],
                         [["losetup", "--detach", "/dev/loop123"]])

    def test_primary_failure_is_not_masked_by_failed_loop_cleanup(self):
        primary = subprocess.CalledProcessError(23, ["mock-partclone"])
        cleanup = subprocess.CalledProcessError(41, ["mock-detach"])
        with self.execution_fixture(backup_error=primary,
                                    detach_error=cleanup) as (plan, _, errors):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                MODULE.execute(plan)
            self.assertIs(raised.exception, primary)
            self.assertIn("Loop cleanup failed", errors.getvalue())

    def test_cleanup_reports_captured_stderr_without_masking_primary(self):
        primary = subprocess.CalledProcessError(23, ["mock-partclone"])
        diagnostic = "losetup: detach failed: Device or resource busy"
        cleanup = subprocess.CalledProcessError(
            41, ["losetup", "--detach", "/dev/loop123"],
            stderr=diagnostic + "\n")
        with self.execution_fixture(backup_error=primary,
                                    detach_error=cleanup) as fixture:
            plan, _, errors = fixture
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                MODULE.execute(plan)
            self.assertIs(raised.exception, primary)
            self.assertIn(diagnostic, errors.getvalue())
        target, = self.output.glob("backup-*")
        self.assertTrue((target / ".incomplete").exists())
        self.assertFalse((target / "manifest.json").exists())

    def test_finalizer_failure_preserves_primary_and_closes_descriptors(self):
        primary = subprocess.CalledProcessError(23, ["mock-partclone"])
        original_output, original_open = MODULE.Output, os.open
        outputs, source_descriptors = [], []

        def tracked_output(*arguments, **keywords):
            output = original_output(*arguments, **keywords)
            outputs.append(output)
            return output

        def tracked_open(path, *arguments, **keywords):
            descriptor = original_open(path, *arguments, **keywords)
            if Path(path) == self.image:
                source_descriptors.append(descriptor)
            return descriptor

        with self.execution_fixture(backup_error=primary) as fixture, \
                mock.patch.object(MODULE, "Output",
                                  side_effect=tracked_output), \
                mock.patch.object(original_output, "finish",
                                  side_effect=ValueError("output moved")), \
                mock.patch.object(MODULE.os, "open", side_effect=tracked_open):
            plan, calls, errors = fixture
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                MODULE.execute(plan)
            self.assertIs(raised.exception, primary)
            self.assertIn("Cannot finalize", errors.getvalue())
            self.assertEqual(len(outputs), 1)
            self.assertEqual(len(source_descriptors), 1)
            for descriptor in [outputs[0].fd, *source_descriptors]:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)
        self.assertEqual([call for call in calls if "--detach" in call],
                         [["losetup", "--detach", "/dev/loop123"]])

    def test_new_ancestors_are_owned_without_chowning_existing_parent(self):
        destination = self.sdk / "workdir/new-parent/new-backups"
        changed = []

        def chown(descriptor, uid, gid):
            changed.append((os.fstat(descriptor).st_ino, uid, gid))

        with mock.patch.object(MODULE.os, "fchown", side_effect=chown):
            descriptor = MODULE.prepare_output_root(
                destination, os.getuid(), os.getgid())
        os.close(descriptor)
        created = [destination.parent, destination]
        self.assertEqual({item[0] for item in changed},
                         {path.stat().st_ino for path in created})
        self.assertEqual(len(changed), 2)
        self.assertTrue(all(item[1:] == (os.getuid(), os.getgid())
                            for item in changed))
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o700
                            for path in created))

    def test_detach_failure_prevents_completed_publication(self):
        cleanup = subprocess.CalledProcessError(41, ["mock-detach"])
        with self.execution_fixture(detach_error=cleanup) as (plan, _, _):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                MODULE.execute(plan)
            self.assertIs(raised.exception, cleanup)
        target, = self.output.glob("backup-*")
        self.assertTrue((target / ".incomplete").exists())
        self.assertFalse((target / "manifest.json").exists())

    def test_changed_mapping_is_never_detached(self):
        with self.execution_fixture(changed_mapping=True) as (plan, calls, _):
            with self.assertRaisesRegex(ValueError, "mapping changed"):
                MODULE.execute(plan)
        self.assertFalse(any("--detach" in call for call in calls))

    def test_failed_allocation_only_cleans_explicit_returned_owned_loop(self):
        failure = subprocess.CalledProcessError(71, ["mock-losetup"],
                                               output="/dev/loop123\n")
        with self.execution_fixture(allocate_error=failure) as (plan, calls, _):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                MODULE.execute(plan)
            self.assertIs(raised.exception, failure)
        self.assertEqual([call for call in calls if "--detach" in call],
                         [["losetup", "--detach", "/dev/loop123"]])

    def test_signal_failure_preserves_status_and_runs_owned_cleanup(self):
        interruption = MODULE.BackupSignal(signal.SIGTERM)
        with self.execution_fixture(backup_error=interruption) as fixture:
            plan, calls, _ = fixture
            with self.assertRaises(MODULE.BackupSignal) as raised:
                MODULE.execute(plan)
            self.assertEqual(raised.exception.status, 143)
        self.assertEqual([call for call in calls if "--detach" in call],
                         [["losetup", "--detach", "/dev/loop123"]])


if __name__ == "__main__":
    unittest.main()

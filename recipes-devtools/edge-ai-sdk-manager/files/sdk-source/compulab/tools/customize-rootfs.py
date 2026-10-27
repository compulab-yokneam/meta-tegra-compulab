#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Enter a trusted SDK rootfs with temporary, privately mounted runtime files.

Inspection is read-only. Explicit execution requires sudo and modifies only
the selected SDK rootfs. This is an administration chroot, not a sandbox for
untrusted root commands. No SDK receipts are refreshed to bless modifications.
"""
import argparse
import contextlib
import ctypes
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time


sys.dont_write_bytecode = True
GLOBAL_LOCK = Path("/tmp/edge-ai-sdkmanager.lock")
BINFMT = Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")
MOUNTINFO = Path("/proc/self/mountinfo")
RESOLVER = Path("/etc/resolv.conf")
SIGNALS = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
DEFAULT_COMMAND = ("/bin/bash", "--noprofile", "--norc", "-i")
HOST_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
POLICY = b"#!/bin/sh\n# Temporary CompuLab rootfs customization policy.\nexit 101\n"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def directory(value):
    path = Path(value)
    require(path.is_absolute() and path != Path("/") and path.is_dir() and
            path.resolve(strict=True) == path,
            "Expected canonical directory: " + str(path))
    return path


def regular(path):
    path = Path(path)
    require(stat.S_ISREG(path.lstat().st_mode) and
            path.resolve(strict=True) == path,
            "Expected canonical regular input: " + str(path))
    return path


def within(root, relative):
    """Validate real parent directories without following absolute leaf links."""
    path = root
    for part in Path(relative).parts:
        require(part not in ("", ".", "..", "/"), "Unsafe rootfs path")
        path = path / part
        require(path.is_dir() and not path.is_symlink() and
                path.resolve(strict=True) == path,
                "Unsafe/missing rootfs directory: " + str(path))
    return path


def mount_records():
    result = []
    for line in MOUNTINFO.read_text().splitlines():
        fields = line.split()
        require(len(fields) >= 7 and fields[0].isdecimal(),
                "Cannot safely parse the host mount table")
        target = re.sub(r"\\([0-7]{3})",
                        lambda match: chr(int(match[1], 8)), fields[4])
        result.append((int(fields[0]), target))
    return result


def mounts_below(root):
    return [(identity, target) for identity, target in mount_records()
            if target == str(root) or target.startswith(str(root) + "/")]


def mount_identity(path):
    matches = [identity for identity, target in mount_records()
               if target == str(path)]
    require(len(matches) <= 1,
            "Ambiguous/overmounted rootfs mount; refusing cleanup: " + str(path))
    return matches[0] if matches else None


def persistent_binfmt():
    require(BINFMT.is_file(),
            "Configure persistent ARM64 QEMU binfmt before customization")
    text = BINFMT.read_text()
    require(text.splitlines()[:1] == ["enabled"] and
            re.search(r"(?m)^flags:[^\n]*F", text),
            "ARM64 QEMU binfmt must be enabled with the persistent F flag")
    interpreter = re.search(r"(?m)^interpreter (\S+)$", text)
    require(interpreter and Path(interpreter[1]).is_file(),
            "Registered ARM64 binfmt interpreter is unavailable")
    return interpreter[1]


def check_elf(path):
    with regular(path).open("rb") as stream:
        header = stream.read(20)
    require(len(header) == 20 and header[:6] == b"\x7fELF\x02\x01" and
            int.from_bytes(header[18:20], "little") == 183,
            "Expected AArch64 Ubuntu executable: " + str(path))


def check_sdk(value):
    sdk = directory(value)
    regular(sdk / "flash.sh")
    root = directory(sdk / "rootfs")
    require(root.parent == sdk, "Rootfs must be directly inside this SDK")
    release = regular(root / "usr/lib/os-release").read_text()
    require(re.search(r'(?m)^ID="?ubuntu"?$', release) and
            re.search(r'(?m)^VERSION_ID="?24[.]04"?$', release),
            "The SDK must contain NVIDIA Ubuntu 24.04")
    nvidia = regular(root / "etc/nv_tegra_release").read_text()
    require(re.search(r"# R39 .*REVISION: 2[.]1,", nvidia),
            "The SDK must contain NVIDIA L4T R39.2.1")
    for relative in ("proc", "dev", "sys", "run", "etc", "usr/sbin"):
        within(root, relative)
    for relative in ("etc", "usr/sbin"):
        require(not any(path.name.startswith(".compulab-customize-")
                        for path in (root / relative).iterdir()),
                "Retained customization backups exist in " + str(root / relative) +
                "; inspect and restore the originals before retrying")
    for name in ("bash", "env"):
        check_elf(root / "usr/bin" / name)
    for relative in ("etc/resolv.conf", "usr/sbin/policy-rc.d"):
        leaf = root / relative
        if leaf.exists() or leaf.is_symlink():
            require(stat.S_ISREG(leaf.lstat().st_mode) or leaf.is_symlink(),
                    "Refusing special/directory temporary rootfs leaf: " + str(leaf))
    require(not mounts_below(root),
            "Rootfs already has mounts; stop other SDK operations first")
    native = platform.machine().lower() in ("aarch64", "arm64")
    interpreter = None if native else persistent_binfmt()
    require(hasattr(os, "unshare") and hasattr(os, "CLONE_NEWNS"),
            "Linux Python 3.12+ private mount namespace support is required")
    require(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"),
            "Linux PIDfd support is required for owned child cleanup")
    return sdk, root, dict(native_arm64=native, interpreter=interpreter)


def resolver_bytes():
    source = RESOLVER.resolve(strict=True)
    require(source.is_file() and stat.S_ISREG(source.stat().st_mode) and
            source.stat().st_size <= 1024 * 1024,
            "A regular host DNS resolver configuration is required")
    value = source.read_bytes()
    require(value and b"\0" not in value, "Host DNS resolver configuration is empty/invalid")
    return value


def command_args(values):
    command = list(values) or list(DEFAULT_COMMAND)
    require(all(isinstance(value, str) and "\0" not in value for value in command),
            "Invalid customization command arguments")
    require(command[0] and not command[0].startswith("-") and
            not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", command[0]),
            "Provide a command, not environment assignments or shell options")
    return command


def host_run(command):
    process = subprocess.run([str(value) for value in command], check=False,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             env={"PATH": HOST_PATH, "LC_ALL": "C"})
    require(process.returncode == 0,
            "Runtime setup/cleanup failed: " + " ".join(map(str, command)) +
            "\n" + process.stdout)
    return process.stdout


@contextlib.contextmanager
def lock_file(path, uid, gid):
    descriptor = None
    # Defer signals until a newly created file has its final ordinary owner
    # and the descriptor is registered for cleanup.
    try:
        with deferred_signals(SIGNALS):
            try:
                descriptor = os.open(path, os.O_RDWR | os.O_CREAT |
                                     os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            else:
                os.fchown(descriptor, uid, gid)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o600,
                "SDK lock must be a private regular file owned by the invoking user")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another cooperating SDK operation holds the SDK lock") from error
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextlib.contextmanager
def sdk_lock(sdk):
    uid, gid = os.environ.get("SUDO_UID", ""), os.environ.get("SUDO_GID", "")
    require(uid.isdecimal() and int(uid) > 0 and gid.isdecimal(),
            "Invoke customize_rootfs from an ordinary user through sudo")
    uid, gid = int(uid), int(gid)
    with lock_file(GLOBAL_LOCK, uid, gid), \
            lock_file(sdk / ".compulab-customize-rootfs.lock", uid, gid):
        yield


class Interrupted(RuntimeError):
    def __init__(self, number):
        self.number = number
        super().__init__("Interrupted by signal " + str(number))


@contextlib.contextmanager
def signal_handlers():
    def interrupted(number, _frame):
        raise Interrupted(number)
    previous = {number: signal.getsignal(number) for number in SIGNALS}
    try:
        for number in SIGNALS:
            signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextlib.contextmanager
def ignore_signals(numbers):
    previous = {number: signal.getsignal(number) for number in numbers}
    try:
        for number in numbers:
            signal.signal(number, signal.SIG_IGN)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextlib.contextmanager
def deferred_signals(numbers):
    """Block, rather than discard, interrupts during ownership transactions."""
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
    try:
        yield previous
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


class TemporaryLeaf:
    """Rename original leaves instead of following or rewriting symlinks."""
    def __init__(self, root, relative, content, mode):
        self.root, self.relative = root, Path(relative)
        self.path = root / relative
        self.content, self.mode = content, mode
        self.backup = None
        self.saved = False
        self.active = False

    def install(self):
        within(self.root, self.relative.parent)
        if self.path.exists() or self.path.is_symlink():
            require(stat.S_ISREG(self.path.lstat().st_mode) or self.path.is_symlink(),
                    "Refusing special temporary leaf: " + str(self.path))
        with deferred_signals(SIGNALS):
            self.backup = Path(tempfile.mkdtemp(prefix=".compulab-customize-",
                                               dir=self.path.parent))
            if self.path.exists() or self.path.is_symlink():
                os.replace(self.path, self.backup / "original")
                self.saved = True
            self.active = True
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT |
                                 os.O_EXCL | os.O_NOFOLLOW, self.mode)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self.content)
                os.fchmod(stream.fileno(), self.mode)

    def restore(self):
        if self.backup is None:
            return
        try:
            within(self.root, self.relative.parent)
            original = self.backup / "original"
            # Also recognize a backup when an exceptional I/O wrapper raised
            # immediately after rename, before the in-memory flag update.
            saved = self.saved or original.exists() or original.is_symlink()
            if self.active or saved:
                if self.path.exists() or self.path.is_symlink():
                    require(stat.S_ISREG(self.path.lstat().st_mode) or self.path.is_symlink(),
                            "Temporary leaf became a directory/special file")
                if saved:
                    os.replace(original, self.path)
                elif self.path.exists() or self.path.is_symlink():
                    self.path.unlink()
            self.backup.rmdir()
        except (OSError, ValueError) as error:
            raise RuntimeError("Cannot restore " + str(self.path) +
                               "; original state retained at " + str(self.backup) +
                               ": " + str(error)) from error


class Runtime:
    def __init__(self, root, dns):
        self.root, self.dns = root, dns
        self.mounts, self.leaves = [], []

    def mount(self, filesystem, options, source, relative):
        destination = self.root / relative
        with deferred_signals(SIGNALS):
            host_run(["mount", "-t", filesystem, "-o", options, source, destination])
            identity = mount_identity(destination)
            self.mounts.append((destination, identity))
            require(identity is not None, "Cannot identify owned mount: " + str(destination))

    def prepare(self):
        require(not mounts_below(self.root), "Rootfs acquired mounts before customization")
        # Namespace creation precedes any mount-propagation change.
        os.unshare(os.CLONE_NEWNS)
        host_run(["mount", "--make-rprivate", "/"])
        for relative, content, mode in (("usr/sbin/policy-rc.d", POLICY, 0o755),
                                        ("etc/resolv.conf", self.dns, 0o644)):
            leaf = TemporaryLeaf(self.root, relative, content, mode)
            self.leaves.append(leaf)
            leaf.install()
        self.mount("tmpfs", "mode=0755,nosuid,nodev,noexec", "tmpfs", "run")
        self.mount("tmpfs", "ro,mode=0555,nosuid,nodev,noexec", "tmpfs", "sys")
        self.mount("proc", "ro,nosuid,nodev,noexec", "proc", "proc")
        self.mount("tmpfs", "mode=0755,nosuid", "tmpfs", "dev")
        for name, major, minor in (("null", 1, 3), ("zero", 1, 5), ("full", 1, 7),
                                   ("random", 1, 8), ("urandom", 1, 9), ("tty", 5, 0)):
            host_run(["mknod", "-m", "0666", self.root / "dev" / name,
                      "c", major, minor])
        (self.root / "dev/pts").mkdir()
        self.mount("devpts", "newinstance,ptmxmode=0666,mode=0620", "devpts", "dev/pts")
        for name, destination in (("ptmx", "pts/ptmx"), ("fd", "/proc/self/fd"),
                                  ("stdin", "/proc/self/fd/0"),
                                  ("stdout", "/proc/self/fd/1"),
                                  ("stderr", "/proc/self/fd/2")):
            (self.root / "dev" / name).symlink_to(destination)

    def cleanup(self, restore_files=True):
        errors = []
        # A second signal must not interrupt the restoration of original files.
        with ignore_signals(SIGNALS):
            for destination, identity in reversed(self.mounts):
                try:
                    current = mount_identity(destination)
                    if current is None:
                        continue
                    require(identity is not None and current == identity,
                            "Refusing to unmount a replaced/foreign mount: " + str(destination))
                    host_run(["umount", destination])
                except (OSError, ValueError, RuntimeError) as error:
                    errors.append(str(error))
            try:
                remaining = mounts_below(self.root)
                if remaining:
                    restore_files = False
                    errors.append("Rootfs still has mounts; refusing file restoration through them: " +
                                  ", ".join(target for _, target in remaining))
            except (OSError, ValueError, RuntimeError) as error:
                restore_files = False
                errors.append("Cannot inspect remaining rootfs mounts: " + str(error))
            if restore_files:
                for leaf in reversed(self.leaves):
                    try:
                        leaf.restore()
                    except (OSError, ValueError, RuntimeError) as error:
                        errors.append(str(error))
            elif self.leaves:
                errors.append("Original rootfs leaf backups retained for manual restoration: " +
                              ", ".join(str(leaf.backup) for leaf in self.leaves if leaf.backup))
        return errors


def stop_process(process, number):
    with ignore_signals(SIGNALS):
        for forwarded, timeout in ((number, 3), (signal.SIGTERM, 3), (signal.SIGKILL, 3)):
            try:
                os.killpg(process.pid, forwarded)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                continue
    raise RuntimeError("Customization command did not exit after signal forwarding")


@contextlib.contextmanager
def subreaper():
    """Adopt daemonized/job-control descendants before releasing the SDK lock."""
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    changed, errors = False, []
    try:
        with deferred_signals(SIGNALS):
            if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), "Cannot inspect child-subreaper state")
            if libc.prctl(36, 1, 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), "Cannot adopt customization descendants")
            changed = True
        yield errors
    finally:
        with ignore_signals(SIGNALS):
            if changed and libc.prctl(36, previous.value, 0, 0, 0) != 0:
                errors.append("Cannot restore child-subreaper state")


def owned_children():
    path = Path("/proc/self/task") / str(os.getpid()) / "children"
    fields = path.read_text().split()
    require(all(value.isdecimal() and int(value) > 0 for value in fields),
            "Cannot inspect owned customization descendants")
    return [int(value) for value in fields]


def signal_owned_child(pid, number):
    """PIDfds and a fresh PPID check avoid signalling a reused foreign PID."""
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        try:
            fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            return
        require(len(fields) > 1 and fields[1].isdecimal(), "Cannot inspect owned child identity")
        if int(fields[1]) != os.getpid():
            return
        try:
            signal.pidfd_send_signal(descriptor, number)
        except ProcessLookupError:
            pass
    finally:
        os.close(descriptor)


def drain_children(timeout=9):
    """Reap the exited shell, stop adopted descendants, and report survivors."""
    started, terminated = time.monotonic(), set()
    with ignore_signals(SIGNALS):
        while True:
            while True:
                try:
                    waited, _ = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if waited == 0:
                    break
            children = owned_children()
            if not children:
                return []
            elapsed = time.monotonic() - started
            for pid in children:
                if elapsed >= 3:
                    signal_owned_child(pid, signal.SIGKILL)
                elif pid not in terminated:
                    signal_owned_child(pid, signal.SIGTERM)
                    terminated.add(pid)
            if elapsed >= timeout:
                return ["Owned customization descendants did not exit: " +
                        ", ".join(map(str, children)) + "; stop them before reusing the SDK"]
            time.sleep(0.05)


def child_signals(previous):
    for number in SIGNALS:
        signal.signal(number, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_SETMASK, set(previous).difference(SIGNALS))


def run_chroot(root, command):
    term = os.environ.get("TERM", "dumb")
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", term):
        term = "dumb"
    argv = ["chroot", str(root), "/usr/bin/env", "-i",
            "PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C", "HOME=/root",
            "USER=root", "LOGNAME=root", "HOSTNAME=nvidia-rootfs", "TERM=" + term,
            "PS1=(CompuLab SDK rootfs) \\u@\\h:\\w# ", *command]
    # A separate process group permits forwarding termination to descendants.
    # Unlike a new session, it retains the controlling terminal for job control.
    process, foreground, status, errors = None, None, 1, []
    with subreaper() as subreaper_errors:
        try:
            with deferred_signals(SIGNALS) as previous:
                if sys.stdin.isatty():
                    foreground = os.tcgetpgrp(sys.stdin.fileno())
                    require(foreground == os.getpgrp(),
                            "Customization must run in the foreground of its terminal")
                process = subprocess.Popen(argv, process_group=0,
                    preexec_fn=lambda: child_signals(previous),
                    env={"PATH": HOST_PATH, "LC_ALL": "C"})
                if foreground is not None:
                    with ignore_signals((signal.SIGTTOU,)):
                        os.tcsetpgrp(sys.stdin.fileno(), process.pid)
                    try:
                        os.killpg(process.pid, signal.SIGCONT)
                    except ProcessLookupError:
                        pass
            status = process.wait()
        except Interrupted as error:
            if process is not None:
                try:
                    stop_process(process, error.number)
                except (OSError, ValueError, RuntimeError) as failure:
                    print("Command termination failed: " + str(failure), file=sys.stderr)
            status = 128 + error.number
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            if process is not None:
                try:
                    stop_process(process, signal.SIGTERM)
                except (OSError, ValueError, RuntimeError) as failure:
                    print("Command termination failed: " + str(failure), file=sys.stderr)
            print("Customization command failed: " + str(error), file=sys.stderr)
            status = 1
        except BaseException:
            if process is not None:
                stop_process(process, signal.SIGTERM)
            raise
        finally:
            # The subreaper catches children in different foreground/background
            # process groups and daemonized grandchildren, not only shell PGID.
            with ignore_signals(SIGNALS):
                try:
                    try:
                        errors = drain_children()
                    except (OSError, ValueError, RuntimeError) as error:
                        errors = ["Cannot safely drain customization descendants: " + str(error)]
                finally:
                    if foreground is not None:
                        with ignore_signals((signal.SIGTTOU,)):
                            try:
                                os.tcsetpgrp(sys.stdin.fileno(), foreground)
                            except OSError as error:
                                print("Cannot restore terminal foreground: " + str(error),
                                      file=sys.stderr)
                                if status == 0:
                                    status = 1
    for error in subreaper_errors:
        print(error, file=sys.stderr)
        if status == 0:
            status = 1
    return (128 - status if status < 0 else status), errors


def execute(value, command):
    require(os.geteuid() == 0, "--execute requires sudo/root privileges")
    command = command_args(command)
    if command == list(DEFAULT_COMMAND):
        require(sys.stdin.isatty(), "Interactive customization requires a terminal")
    sdk, root, _ = check_sdk(value)
    dns = resolver_bytes()
    runtime = Runtime(root, dns)
    status, child_errors = 1, []
    with signal_handlers(), sdk_lock(sdk):
        # Cooperating SDK builders cannot alter this rootfs after lock acquisition.
        check_sdk(value)
        try:
            runtime.prepare()
            status, child_errors = run_chroot(root, command)
        except Interrupted as error:
            status = 128 + error.number
            print(str(error), file=sys.stderr)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print("Rootfs customization failed: " + str(error), file=sys.stderr)
        finally:
            cleanup = child_errors + runtime.cleanup(restore_files=not child_errors)
            for error in cleanup:
                print("Rootfs cleanup failed: " + error, file=sys.stderr)
            if cleanup and status == 0:
                status = 1
    if status:
        print("Customization exited %d; rootfs changes are not rolled back." % status,
              file=sys.stderr)
    return status


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only validation (default)")
    mode.add_argument("--execute", action="store_true", help="explicit privileged customization")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        command = command_args(command)
        if args.execute:
            return execute(args.sdk_root, command)
        sdk, root, architecture = check_sdk(args.sdk_root)
        resolver_bytes()
        print(json.dumps(dict(action="read-only rootfs customization check", sdk_root=str(sdk),
                              rootfs=str(root), command=command, **architecture), sort_keys=True))
        return 0
    except Interrupted as error:
        print("Rootfs customization interrupted: " + str(error), file=sys.stderr)
        return 128 + error.number
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Rootfs customization failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

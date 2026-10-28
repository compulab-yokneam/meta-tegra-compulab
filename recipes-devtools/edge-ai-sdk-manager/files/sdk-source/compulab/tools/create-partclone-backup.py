#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Back up an owned disk image through one new, read-only loop mapping.

The default inspection makes no changes. Execution requires explicit sudo
authorization and never accepts a physical source disk or a restore target.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid


sys.dont_write_bytecode = True
HOST_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
GLOBAL_LOCK = Path("/tmp/edge-ai-sdkmanager.lock")
SYS_BLOCK = Path("/sys/class/block")
MOUNTINFO = Path("/proc/self/mountinfo")
SIGNALS = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
LOOP_COLUMNS = "NAME,BACK-FILE,BACK-INO,BACK-MAJ:MIN,RO,OFFSET,SIZELIMIT,PARTSCAN"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exception_text(error):
    message = str(error)
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
        detail = error.stderr
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        if detail.strip():
            message += "\n" + detail.strip()
    return message


class BackupSignal(Exception):
    def __init__(self, number):
        self.status = 128 + number
        super().__init__("Interrupted by signal %d" % number)


def invoking_owner():
    if os.getuid() != 0:
        return os.getuid(), os.getgid()
    uid, gid = os.environ.get("SUDO_UID", ""), os.environ.get("SUDO_GID", "")
    require(uid.isdecimal() and int(uid) > 0 and gid.isdecimal(),
            "Use a normal user shell; invoke execution through sudo")
    return int(uid), int(gid)


def canonical(value):
    path = Path(value)
    require(path.is_absolute() and path != Path("/") and
            path.resolve() == path and
            not any(path == root or path.is_relative_to(root)
                    for root in map(Path, ("/dev", "/proc", "/sys"))),
            "Expected canonical non-device path: " + str(path))
    return path


def identity(path):
    info = path.lstat()
    return dict(device=info.st_dev, inode=info.st_ino, size=info.st_size,
                mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)


def secure_directory(path, uid):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and path.resolve() == path and
            info.st_uid == uid and not info.st_mode & 0o022,
            "Output directory must be canonical, owned and not writable by others: " + str(path))


def stop(process):
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def run(*argv, allowed=(0,), pass_fds=()):
    process = subprocess.Popen([str(value) for value in argv],
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True,
                               pass_fds=pass_fds,
                               env={"PATH": HOST_PATH, "LC_ALL": "C"})
    try:
        stdout, stderr = process.communicate()
    except BaseException:
        stop(process)
        raise
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    if result.returncode not in allowed:
        raise subprocess.CalledProcessError(result.returncode, argv, stdout, stderr)
    return result


def associated_loops(image):
    rows = json.loads(run("losetup", "--list", "--json", "--output",
                          LOOP_COLUMNS).stdout).get("loopdevices", [])
    require(isinstance(rows, list), "Cannot inspect existing loop mappings")
    file_id = identity(image)
    major_minor = "%d:%d" % (os.major(file_id["device"]),
                              os.minor(file_id["device"]))
    return [row for row in rows if row.get("back-file") == str(image) or
            (str(row.get("back-ino")) == str(file_id["inode"]) and
             row.get("back-maj:min") == major_minor)]


def inspect(sdk_root, image, output_root, compression="none"):
    uid, gid = invoking_owner()
    sdk, image, output = map(canonical, (sdk_root, image, output_root))
    require(sdk.is_dir() and (sdk / "rootfs").is_dir() and
            (sdk / "flash.sh").is_file() and
            (sdk / "compulab/host/image-builder.sh").is_file(),
            "Source the wrapper from a prepared CompuLab SDK")
    for path in (image, output):
        require(not sdk.is_relative_to(path) and path != sdk and
                (not path.is_relative_to(sdk) or
                 path.is_relative_to(sdk / "workdir")),
                "Image/output must not overlap protected SDK payloads")
    info = image.lstat()
    require(stat.S_ISREG(info.st_mode) and image.suffix == ".img" and
            info.st_uid == uid and info.st_nlink == 1 and info.st_size > 0 and
            not info.st_mode & 0o022,
            "L4T_IMAGE must be an owned, single-link, non-writable-by-others .img file")
    require(not image.is_relative_to(output) and not output.is_relative_to(image),
            "Image and backup output must be separate")
    ancestor = output
    while not ancestor.exists():
        ancestor = ancestor.parent
    secure_directory(ancestor, uid)
    require(compression in ("none", "xz"), "Compression must be none or xz")
    commands = ["losetup", "lsblk", "sfdisk", "blkid", "partclone.ext4",
                "partclone.vfat", "partclone.dd"]
    if compression == "xz":
        commands.append("xz")
    for name in commands:
        require(shutil.which(name, path=HOST_PATH), "Required host tool missing: " + name)
    require(not associated_loops(image),
            "L4T_IMAGE is already associated with a loop; finish other image operations first")
    return dict(sdk=str(sdk), image=str(image), output_root=str(output),
                compression=compression, uid=uid, gid=gid,
                identity=identity(image), mode="read-only inspection")


def loop_record(loop):
    require(re.fullmatch(r"/dev/loop[0-9]+", str(loop)),
            "Unexpected allocated loop name")
    rows = json.loads(run("losetup", "--list", "--json", "--output",
                          LOOP_COLUMNS, "--", loop).stdout).get("loopdevices", [])
    require(len(rows) == 1 and rows[0].get("name") == str(loop),
            "Allocated loop mapping is missing or ambiguous")
    return rows[0]


def verify_loop(loop, image, expected, *, check_image=True):
    info = Path(loop).stat()
    require(stat.S_ISBLK(info.st_mode) and os.major(info.st_rdev) == 7,
            "Source is not a kernel loop block device")
    row = loop_record(loop)
    major_minor = "%d:%d" % (os.major(expected["device"]),
                              os.minor(expected["device"]))
    require(row.get("back-file") == str(image) and
            str(row.get("back-ino")) == str(expected["inode"]) and
            row.get("back-maj:min") == major_minor and
            row.get("ro") in (True, 1) and row.get("partscan") in (True, 1) and
            int(row.get("offset", -1)) == 0 and int(row.get("sizelimit", -1)) == 0,
            "Allocated loop no longer matches the owned, read-only image")
    if check_image:
        require(identity(Path(image)) == expected, "Source image changed during backup")
    require(not any((SYS_BLOCK / Path(loop).name / "holders").iterdir()),
            "Allocated loop has device-mapper holders")
    return row


def partition_records(loop):
    table = json.loads(run("sfdisk", "--json", "--", loop).stdout)["partitiontable"]
    require(table.get("device") == str(loop) and table.get("label") == "gpt" and
            table.get("sectorsize") == 512 and table.get("partitions"),
            "Expected a partitioned 512-byte-sector GPT image")
    partitions = table["partitions"]
    rows = []
    for attempt in range(30):
        devices = json.loads(run("lsblk", "--json", "--bytes", "--paths",
                                 "--output", "NAME,TYPE,PKNAME,MAJ:MIN,RO,MOUNTPOINTS",
                                 "--", loop).stdout)["blockdevices"]
        require(len(devices) == 1 and devices[0].get("name") == str(loop),
                "Cannot identify the allocated loop partition tree")
        require(not any(devices[0].get("mountpoints") or []),
                "The allocated loop is mounted")
        rows = devices[0].get("children", [])
        if {row.get("name") for row in rows} == {row.get("node") for row in partitions}:
            break
        time.sleep(0.1)
    require(len(rows) == len(partitions) and
            {row.get("name") for row in rows} == {row.get("node") for row in partitions},
            "Partition scan is incomplete or contains unexpected devices")
    mounts = {line.split()[2] for line in MOUNTINFO.read_text().splitlines()}
    result, numbers = [], set()
    for row in rows:
        node = row["name"]
        require(re.fullmatch(re.escape(str(loop)) + r"p[1-9][0-9]*", node) and
                row.get("type") == "part" and row.get("pkname") == str(loop) and
                row.get("ro") in (True, 1) and not row.get("children") and
                not any(row.get("mountpoints") or []) and row.get("maj:min") not in mounts,
                "Partition is not an unmounted, read-only child of the allocated loop")
        path = Path(node)
        info = path.stat()
        require(stat.S_ISBLK(info.st_mode) and
                row["maj:min"] == "%d:%d" % (os.major(info.st_rdev), os.minor(info.st_rdev)),
                "Unexpected partition device identity")
        entry = SYS_BLOCK / path.name
        require(entry.resolve().parent == (SYS_BLOCK / Path(loop).name).resolve() and
                not any((entry / "holders").iterdir()), "Unexpected partition parent/holders")
        number = int((entry / "partition").read_text())
        require(str(number) == node.removeprefix(str(loop) + "p") and
                number not in numbers, "Ambiguous partition number")
        numbers.add(number)
        probe = run("blkid", "-p", "-o", "export", "--", node, allowed=(0, 2))
        values = {}
        for line in probe.stdout.splitlines():
            require("=" in line, "Malformed filesystem metadata")
            key, value = line.split("=", 1)
            require(key not in values, "Duplicate filesystem metadata")
            values[key] = value
        original = next(item for item in partitions if item["node"] == node)
        filesystem = values.get("TYPE", "dd")
        filesystem = filesystem if filesystem in ("ext4", "vfat", "swap") else "dd"
        filesystem_uuid = values.get("UUID") if filesystem != "dd" else None
        identifier = filesystem_uuid or original.get("uuid") or "partition-%d" % number
        require(re.fullmatch(r"[A-Za-z0-9_-]+", identifier) and
                (filesystem not in ("ext4", "vfat", "swap") or filesystem_uuid),
                "Missing or unsafe filesystem UUID")
        result.append(dict(number=number, node=node, filesystem=filesystem,
                           uuid=identifier, partuuid=original.get("uuid"),
                           label=original.get("name"), start=original["start"],
                           size=original["size"]))
    return sorted(result, key=lambda item: item["number"])


@contextlib.contextmanager
def lock_file(path, uid, gid):
    # protected_regular rejects root O_CREAT on an existing user-owned file
    # in sticky /tmp. Open existing locks without creating or replacing them.
    flags = os.O_RDWR | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                info.st_uid in (0, uid) and stat.S_IMODE(info.st_mode) == 0o600,
                "Invalid backup coordination lock: " + str(path))
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fchown(descriptor, uid, gid)
        yield
    finally:
        os.close(descriptor)


class Output:
    """Keep rooted writes relative to one exclusively created directory FD."""
    def __init__(self, path, descriptor=None):
        self.path = path
        self.fd = (descriptor if descriptor is not None else
                   os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))

    def create(self, name):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+", name) and name not in (".", ".."),
                "Unsafe backup output filename")
        return os.fdopen(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW, 0o600, dir_fd=self.fd), "wb")

    def write(self, name, contents):
        with self.create(name) as stream:
            stream.write(contents.encode())

    def checksums(self):
        values = {}
        for name in sorted(os.listdir(self.fd)):
            if name == ".incomplete":
                continue
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
            with os.fdopen(descriptor, "rb") as stream:
                require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "Unexpected backup entry")
                values[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        self.write("SHA256SUMS", "".join(value + "  " + name + "\n"
                                         for name, value in values.items()))

    def finish(self, uid, gid):
        require(self.path.resolve() == self.path and
                (self.path.stat().st_dev, self.path.stat().st_ino) ==
                (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino),
                "Backup output directory moved during execution")
        for name in os.listdir(self.fd):
            os.chown(name, uid, gid, dir_fd=self.fd, follow_symlinks=False)
        os.fchown(self.fd, uid, gid)


def prepare_output_root(root, uid, gid):
    missing, ancestor = [], root
    while not ancestor.exists():
        missing.append(ancestor.name)
        ancestor = ancestor.parent
    secure_directory(ancestor, uid)
    descriptor = os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in reversed(missing):
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            try:
                os.mkdir(name, 0o700, dir_fd=descriptor)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
                try:
                    os.fchown(child, uid, gid)
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def backup_partition(partition, output, compression):
    name = "part%d.%s.%s.partclone" % (partition["number"],
                                          partition["filesystem"], partition["uuid"])
    if partition["filesystem"] == "swap":
        with output.create(name):
            pass
        return dict(partition, file=name, representation="swap UUID marker")
    if compression == "xz":
        name += ".xz"
    prefix = "part%d" % partition["number"]
    logfile = "/proc/self/fd/%d/%s.partclone.log" % (output.fd, prefix)
    command = ["partclone." + partition["filesystem"]]
    if partition["filesystem"] in ("ext4", "vfat"):
        command.append("-c")
    command += ["-s", partition["node"], "-o", "-", "-L", logfile]
    children = []
    with output.create(name) as destination, output.create(prefix + ".stderr.log") as errors:
        try:
            clone = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE if compression == "xz" else destination,
                                     stderr=errors, start_new_session=True,
                                     pass_fds=(output.fd,),
                                     env={"PATH": HOST_PATH, "LC_ALL": "C"})
            children.append(clone)
            if compression == "xz":
                compressor = subprocess.Popen(["xz", "-T1", "-c"], stdin=clone.stdout,
                                              stdout=destination, stderr=errors,
                                              start_new_session=True,
                                              env={"PATH": HOST_PATH, "LC_ALL": "C"})
                children.append(compressor)
                clone.stdout.close()
            for process in reversed(children):
                status = process.wait()
                if status:
                    raise subprocess.CalledProcessError(status, process.args)
        finally:
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            try:
                for process in children:
                    stop(process)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
    return dict(partition, file=name, representation="raw" if
                partition["filesystem"] == "dd" else "partclone")


def execute(plan):
    require(os.geteuid() == 0, "--execute requires explicit sudo authorization")
    current = inspect(plan["sdk"], plan["image"], plan["output_root"], plan["compression"])
    require(current == plan, "Backup plan changed before execution")
    uid, gid = plan["uid"], plan["gid"]
    image, root = Path(plan["image"]), Path(plan["output_root"])
    descriptor = os.open(image, os.O_RDONLY | os.O_NOFOLLOW)
    output, loop, primary, cleanup_error = None, None, None, None
    completed = False
    old_handlers = {number: signal.getsignal(number) for number in SIGNALS}
    cleaning, pending = False, []

    def interrupted(number, frame):
        if cleaning:
            pending.append(number)
        else:
            raise BackupSignal(number)

    try:
        for number in SIGNALS:
            signal.signal(number, interrupted)
        # A shared lock protects this read-only source and works on NFS even
        # when the file descriptor cannot be opened for writing.
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        require(os.fstat(descriptor).st_ino == plan["identity"]["inode"],
                "Source image was replaced")
        with lock_file(GLOBAL_LOCK, uid, gid):
            require(not associated_loops(image), "Source image acquired another loop mapping")
            target = root / ("backup-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12])
            root_fd = prepare_output_root(root, uid, gid)
            try:
                os.mkdir(target.name, 0o700, dir_fd=root_fd)
                output = Output(target, os.open(target.name, os.O_RDONLY |
                                os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd))
            finally:
                os.close(root_fd)
            output.write(".incomplete", "Backup is incomplete; do not restore.\n")
            print("Backup directory: " + str(target), file=sys.stderr)
            try:
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
                try:
                    try:
                        loop = run("losetup", "--find", "--show", "--read-only", "--partscan", "--", image).stdout.strip()
                    except subprocess.CalledProcessError as error:
                        if re.fullmatch(r"/dev/loop[0-9]+", (error.output or "").strip()):
                            loop = error.output.strip()
                        raise
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, mask)
                verify_loop(loop, image, plan["identity"])
                partitions = partition_records(loop)
                layout = run("sfdisk", "--dump", "--", loop).stdout
                output.write("disk.layout", "\n".join(line for line in layout.splitlines()
                             if not line.startswith(("device:", "last-lba:"))) + "\n")
                output.write("disk.id", run("sfdisk", "--disk-id", "--", loop).stdout)
                records = []
                for partition in partitions:
                    verify_loop(loop, image, plan["identity"])
                    print("Backing up partition %d (%s)" %
                          (partition["number"], partition["filesystem"]), file=sys.stderr)
                    records.append(backup_partition(partition, output, plan["compression"]))
                verify_loop(loop, image, plan["identity"])
            except BaseException as error:
                primary = error
            finally:
                cleaning = True
                if loop:
                    try:
                        verify_loop(loop, image, plan["identity"], check_image=False)
                        run("losetup", "--detach", loop)
                        require(not any(row.get("name") == loop for row in associated_loops(image)),
                                "Owned loop is still associated after detach")
                    except BaseException as error:
                        cleanup_error = error
                        print("Loop cleanup failed; inspect %s manually: %s" %
                              (loop, exception_text(error)), file=sys.stderr)
            if primary:
                raise primary
            if cleanup_error:
                raise cleanup_error
            if pending:
                raise BackupSignal(pending[0])
            cleaning = False
            output.write("manifest.json", json.dumps(dict(
                schema=1, status="complete", image=str(image), identity=plan["identity"],
                compression=plan["compression"], partitions=records,
                scope="disk partitions only; no QSPI firmware"), indent=2, sort_keys=True) + "\n")
            output.checksums()
            output.finish(uid, gid)
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
            try:
                os.unlink(".incomplete", dir_fd=output.fd)
                completed = True
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            return target
    finally:
        cleaning = True
        try:
            if output:
                try:
                    if not completed:
                        print("Incomplete backup retained: %s" % output.path, file=sys.stderr)
                        try:
                            output.finish(uid, gid)
                        except (OSError, ValueError) as error:
                            print("Cannot finalize retained backup ownership: " +
                                  str(error), file=sys.stderr)
                finally:
                    os.close(output.fd)
        finally:
            os.close(descriptor)
            for number, handler in old_handlers.items():
                signal.signal(number, handler)
            if completed and pending:
                raise BackupSignal(pending[0])


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--compress", choices=("none", "xz"), default="none")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--execute", action="store_true")
    args = parser.parse_args(arguments)
    try:
        plan = inspect(args.sdk_root, args.image, args.output_root, args.compress)
        print(execute(plan) if args.execute else json.dumps(plan, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, BackupSignal) as error:
        print("Partclone backup failed: " + exception_text(error), file=sys.stderr)
        if isinstance(error, BackupSignal):
            return error.status
        if isinstance(error, subprocess.CalledProcessError):
            return error.returncode if error.returncode > 0 else 128 - error.returncode
        return 1


if __name__ == "__main__":
    sys.exit(main())

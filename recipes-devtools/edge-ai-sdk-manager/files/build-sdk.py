#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Secret-free, fail-closed SDK Manager orchestration (ordinary host user)."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time

SDK_RELATIVE = Path("JetPack_7.2.1_Linux_JETSON_ORIN_NX_TARGETS/Linux_for_Tegra")
MACHINES = ("edge-ai-nx-16g", "edge-ai-nx-8g", "edge-ai-nano-8g", "edge-ai-nano-4g")
STYLES = ("nvidia-logo", "clab-logo", "no-logo")


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def response(configuration):
    for name in ("output", "download"):
        value = configuration.get(name)
        require(isinstance(value, str) and value.startswith("/"),
                "Absolute scalar SDK Manager paths are required")
        # Vendor component scripts interpolate paths into unquoted shell
        # commands. Do not let an INI value become shell syntax there.
        require(all(c.isascii() and (c.isalnum() or c in "/._+-") for c in value),
                "SDK Manager paths must contain only shell-safe characters")
    return """[client_arguments]
action = install
login-type = devzone
stay-logged-in = true
product = Jetson
version = 7.2.1
target-os = Linux
target = JETSON_ORIN_NX_TARGETS
install-method = direct_flash
host = false
flash = false
select[] = Jetson Linux Image
deselect[] = Host SDK Components
deselect[] = Jetson Runtime Components
deselect[] = Jetson SDK Components
deselect[] = Jetson System Upgrade
deselect[] = Flash Jetson Linux
license = accept
collect-usage-data = disable
download-folder = {download}
target-image-folder = {output}

[post-flash-settings]
post-flash = skip
""".format(**configuration)


def process_snapshot():
    """Read identities, not command lines or environments (which may be secret)."""
    result = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            text = (entry / "stat").read_text()
            fields = text[text.rfind(")") + 2:].split()
            if fields[0] != "Z":
                result[int(entry.name)] = (int(fields[1]), int(fields[2]),
                                           int(fields[3]), int(fields[19]))
        except (OSError, ValueError, IndexError):
            continue
    return result


def observe_descendants(pid, known):
    snapshot = process_snapshot()
    reused = pid in known and pid in snapshot and known[pid] != snapshot[pid][3]
    identities = {number for number, identity in snapshot.items()
                  if (number in known and known[number] == identity[3])
                  or (not reused and (number == pid or identity[1] == pid or identity[2] == pid))}
    while True:
        added = {number for number, identity in snapshot.items()
                 if identity[0] in identities} - identities
        if not added:
            break
        identities.update(added)
    for number in identities:
        known[number] = snapshot[number][3]
    return identities


def stop_process_tree(process, known, log):
    """Stop this new session plus observed descendants that changed sessions.

    sudo use_pty may create another session. Keep PID/start-time identities
    while running, and signal those individual descendants as well. This is
    not a sandbox: a deliberately detached/reparented process between two
    observations cannot be proven absent. Never reuse an incomplete SDK.
    """
    for signame in ("TERM", "KILL"):
        alive = observe_descendants(process.pid, known)
        if not alive:
            break
        # The initial process owns a new session; its group never contains
        # our BitBake worker. Root descendants need a privileged signal too.
        snapshot = process_snapshot()
        reused = (process.pid in snapshot and process.pid in known and
                  snapshot[process.pid][3] != known[process.pid])
        targets = ([] if reused else ["-" + str(process.pid)])
        targets += [str(pid) for pid in sorted(alive)]
        try:
            subprocess.run(["sudo", "-n", "/bin/kill", "-" + signame, "--", *targets],
                           stdin=subprocess.DEVNULL, stdout=log,
                           stderr=subprocess.STDOUT, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
        # Also clean up unprivileged children if sudo itself was unavailable.
        sig = getattr(signal, "SIG" + signame)
        if not reused:
            try:
                os.killpg(process.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        snapshot = process_snapshot()
        for pid in alive:
            if pid in snapshot and snapshot[pid][3] == known[pid]:
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not observe_descendants(process.pid, known):
                break
            time.sleep(0.1)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    require(not observe_descendants(process.pid, known),
            "Known SDK process descendants remain; stop them before retrying")


def private_run(command, directory, label, timeout):
    require(isinstance(timeout, (int, float)) and timeout > 0, "Positive timeout required")
    descriptor, name = tempfile.mkstemp(prefix=label + "-", suffix=".log", dir=directory)
    with os.fdopen(descriptor, "wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        known = {}
        deadline = time.monotonic() + timeout
        try:
            while True:
                observe_descendants(process.pid, known)
                result = process.poll()
                if result is not None:
                    break
                remaining = deadline - time.monotonic()
                require(remaining > 0, label + " timed out; private log: " + name)
                time.sleep(min(0.25, remaining))
        except BaseException:
            stop_process_tree(process, known, log)
            raise
        remaining = observe_descendants(process.pid, known)
        if result != 0 or remaining:
            stop_process_tree(process, known, log)
        require(result != 0 or not remaining,
                label + " exited with live descendants; private log: " + name)
    require(result == 0,
            "%s failed (exit %d); inspect private log %s" % (label, result, name))
    print(label + " completed", flush=True)


def validate_firmware_inputs(configuration):
    items = configuration.get("firmware")
    require(isinstance(items, list) and len(items) == 12,
            "Exactly twelve unique machine/style firmware inputs are required")
    seen, names, directories = set(), set(), set()
    for item in items:
        require(isinstance(item, dict), "Invalid firmware selection record")
        require(all(isinstance(item.get(key), str) and item[key]
                    for key in ("machine", "style", "mc", "deploy")),
                "Firmware selection values must be nonempty scalar strings")
        machine, style, mc = item["machine"], item["style"], item["mc"]
        require(machine in MACHINES and style in STYLES, "Unknown firmware machine/style")
        pair = (machine, style)
        require(pair not in seen and mc not in names, "Duplicate firmware machine/style or multiconfig")
        prefix = "edge-ai-uefi" if machine == "edge-ai-nx-16g" else "edge-ai-uefi-" + machine.removeprefix("edge-ai-")
        require(mc == prefix + "-" + style, "Firmware multiconfig does not match its machine/style")
        directory = Path(item["deploy"])
        require(directory.is_absolute(), "Absolute firmware deploy paths are required")
        resolved = directory.resolve()
        require(resolved not in directories, "Duplicate firmware deploy directory")
        seen.add(pair)
        names.add(mc)
        directories.add(resolved)
    require(seen == {(machine, style) for machine in MACHINES for style in STYLES},
            "Incomplete firmware machine/style matrix")
    return items


def generated_python(path):
    return "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo")


def inputs(configuration):
    paths = []
    for root in (Path(configuration["sources"]), Path(configuration["assets"])):
        require(root.is_dir(), "Missing SDK source/assets directory: " + str(root))
        paths.extend(p for p in root.rglob("*") if p.is_file())
    deploy = Path(configuration["deploy"])
    for name in ("kernel", "nvidia-kernel-oot", "kernel-devsrc"):
        paths.extend((deploy / "edge-ai-sdk" / (name + ".tar.xz"),
                      deploy / "edge-ai-sdk" / (name + ".json")))
    for folder in (deploy / "devicetree", deploy / "edge-ai-uefi-update-capsules"):
        require(folder.is_dir(), "Missing deployed SDK input: " + str(folder))
        paths.extend(p for p in folder.rglob("*") if p.is_file())
    paths.extend(deploy.glob("*.dtb"))
    firmware = validate_firmware_inputs(configuration)
    for item in firmware:
        root = Path(item["deploy"]) / "edge-ai-sdk/firmware"
        require(root.is_dir(), "Missing multiconfig firmware export: " + str(root))
        paths.extend(p for p in root.rglob("*") if p.is_file())
    records = {}
    roots = [(Path(configuration["sources"]), "sources"),
             (Path(configuration["assets"]), "assets"), (deploy, "deploy")]
    roots.extend((Path(i["deploy"]), "firmware/" + i["mc"]) for i in firmware)
    for path in sorted(set(paths)):
        if generated_python(path):
            continue
        require(path.is_file(), "Missing input: " + str(path))
        for root, prefix in roots:
            if path.is_relative_to(root):
                records[prefix + "/" + str(path.relative_to(root))] = sha256(path)
                break
    options = {name: configuration.get(name) for name in
               ("machine", "imx676_extended", "imx678_extended")}
    records["workflow/options"] = hashlib.sha256(
        json.dumps(options, sort_keys=True).encode()).hexdigest()
    return records


def main():
    require(sys.version_info >= (3, 12), "This workflow requires host Python 3.12+ (Ubuntu 24.04)")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", action="store_true", help="check inputs only; no SDK Manager/sudo")
    arguments = parser.parse_args()
    configuration = json.loads(arguments.config.read_text())
    output = Path(configuration["output"])
    work = Path(configuration["work"])
    require(output.is_absolute() and work.is_absolute(), "Absolute work/output paths required")
    require(output != Path("/") and not output.is_symlink(), "Unsafe output directory")
    require(work.is_dir() and not work.is_symlink() and work.stat().st_uid == os.getuid(),
            "Private work directory must belong to this user")
    response(configuration)  # Validate all vendor-interpolated paths before sudo.
    fingerprint = inputs(configuration)
    if arguments.plan:
        print("Validated %d input checksums; privileged workflow not executed" % len(fingerprint))
        return 0
    work.chmod(0o700)
    require(os.geteuid() != 0, "Run BitBake/SDK Manager as the authenticated ordinary user")
    require(Path(configuration["sdkmanager"]).is_file(), "Install SDK Manager on the host first")
    for tool in ("sudo", "git", "chroot", "depmod", "lsinitramfs", "fdtget", "fdtput", "rsync"):
        require(shutil.which(tool), "Missing host prerequisite: " + tool)
    # SDKM invalidates sudo timestamps; a cached password is insufficient.
    subprocess.run(["sudo", "-k", "-n", "true"], stdin=subprocess.DEVNULL, check=True)
    require(not Path("/tmp/sdkmanager.sock").exists(), "Close all SDK Manager instances first")
    lock_fd = os.open("/tmp/edge-ai-sdkmanager.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ready = output / ".edge-ai-sdk-ready.json"
        if output.exists():
            require(ready.is_file(), "Existing/incomplete output will NOT be overwritten: " + str(output))
            old = json.loads(ready.read_text())
            require(old["inputs"] == fingerprint,
                    "SDK inputs changed; choose a new EDGE_AI_SDK_OUTPUT")
            private_run(["sudo", "-n", "/usr/bin/python3", "-B",
                         str(Path(configuration["sources"]) / "assemble-sdk.py"),
                         "--config", str(arguments.config), "--verify"], work,
                        "sdk-verify", configuration["timeout"])
            print("Existing SDK verified: " + str(output / SDK_RELATIVE))
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(mode=0o755)
        (output / ".edge-ai-sdk-incomplete").write_text("Owned SDK build; never rerun SDKM here.\n")
        response_path = work / "sdkmanager-response.ini"
        descriptor = os.open(response_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(response(configuration))
        print("Preparing pristine NVIDIA Ubuntu SDK; host operations explicitly enabled", flush=True)
        private_run([configuration["sdkmanager"], "--cli", "--response-file", str(response_path),
                     "--auto", "--exit-on-finish", "--check-for-updates", "false"],
                    work, "sdkmanager", configuration["timeout"])
        require((output / SDK_RELATIVE / "flash.sh").is_file(), "SDK Manager output layout/version changed")
        private_run(["sudo", "-n", "/usr/bin/python3", "-B",
                     str(Path(configuration["sources"]) / "assemble-sdk.py"),
                     "--config", str(arguments.config), "--execute"], work,
                    "compulab-conversion", configuration["timeout"])
        temporary = output / ".edge-ai-sdk-ready.new"
        temporary.write_text(json.dumps({"format_version": 1, "inputs": fingerprint,
                                         "sdk": str(SDK_RELATIVE)}, indent=2) + "\n")
        temporary.replace(ready)
        (output / ".edge-ai-sdk-incomplete").unlink()
        print("CompuLab NVIDIA Ubuntu SDK ready: " + str(output / SDK_RELATIVE))
    return 0


def interrupted(signum, frame):
    raise InterruptedError("SDK workflow interrupted by signal %d" % signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, KeyError) as error:
        print("SDK generation stopped: " + str(error), file=sys.stderr)
        sys.exit(1)

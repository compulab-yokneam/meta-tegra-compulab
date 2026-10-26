# SPDX-License-Identifier: MIT
# Recipe-owned, deploy/sstate-safe inputs for the NVIDIA Ubuntu SDK assembler.
# This class never reads another recipe's WORKDIR or builds a Yocto image.
inherit deploy

EDGE_AI_SDK_EXPORTS ?= "0"
EDGE_AI_SDK_EXPORT_SUBDIR ?= "edge-ai-sdk"

do_deploy[depends] += "${@d.getVar('PN') + ':do_populate_lic' if d.getVar('EDGE_AI_SDK_EXPORTS') == '1' else ''}"

# Python helpers begin (also exercised directly by host-side fixture tests).
def edge_ai_sdk_hash(path):
    import hashlib
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()

def edge_ai_sdk_licenses(d):
    from pathlib import Path
    # do_populate_lic setscene restores here, not to its old WORKDIR input.
    path = (Path(d.getVar("LICENSE_DIRECTORY")) /
            d.getVar("SSTATE_PKGARCH") / d.getVar("PN"))
    if not path.is_dir():
        bb.fatal("SDK export lacks staged recipe licenses: %s" % path)
    return path

def edge_ai_sdk_pack(d, component, entries, metadata, excluded=(), excluded_parts=()):
    import hashlib
    import io
    import json
    import posixpath
    import tarfile
    from pathlib import Path, PurePosixPath

    if d.getVar("EDGE_AI_SDK_EXPORTS") != "1":
        return
    if not component or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in component):
        bb.fatal("Invalid SDK export component: %s" % component)
    subdir = PurePosixPath(d.getVar("EDGE_AI_SDK_EXPORT_SUBDIR"))
    if subdir.is_absolute() or ".." in subdir.parts:
        bb.fatal("SDK export subdirectory must stay inside DEPLOYDIR")
    target = Path(d.getVar("DEPLOYDIR")) / str(subdir)
    target.mkdir(parents=True, exist_ok=True)
    archive = target / (component + ".tar.xz")
    temporary = target / ("." + archive.name + ".tmp")
    epoch = int(d.getVar("SOURCE_DATE_EPOCH") or "0")
    files = {}
    links = {}
    members = {}

    for relative, source in sorted(entries.items()):
        destination = PurePosixPath(relative)
        if destination.is_absolute() or ".." in destination.parts:
            bb.fatal("Unsafe SDK archive member: %s" % relative)
        if isinstance(source, bytes):
            candidates = [(str(destination), source)]
        else:
            source = Path(source)
            if not source.exists() and not source.is_symlink():
                bb.fatal("Missing recipe-owned SDK input: %s" % source)
            candidates = [(str(destination), source)]
            if source.is_dir() and not source.is_symlink():
                candidates.extend((str(destination / path.relative_to(source)), path)
                                  for path in sorted(source.rglob("*")))
        for name, path in candidates:
            if any(name == omit or name.startswith(omit + "/") for omit in excluded):
                continue
            if any(part in excluded_parts for part in PurePosixPath(name).parts):
                continue
            if name in members:
                bb.fatal("Duplicate SDK archive member: %s" % name)
            members[name] = path

    try:
        with tarfile.open(temporary, "w:xz", format=tarfile.PAX_FORMAT,
                          dereference=True) as output:
            for name, source in sorted(members.items()):
                if isinstance(source, bytes):
                    info = tarfile.TarInfo(name)
                    info.size = len(source)
                    info.mode = 0o644
                    stream = io.BytesIO(source)
                    files[name] = hashlib.sha256(source).hexdigest()
                else:
                    # Preserve explicit symlinks but serialize hardlinked recipe
                    # inputs as independent files (config/symvers have aliases).
                    if source.is_symlink():
                        info = tarfile.TarInfo(name)
                        info.type = tarfile.SYMTYPE
                        info.linkname = source.readlink().as_posix()
                        info.mode = 0o777
                    else:
                        info = output.gettarinfo(str(source), arcname=name)
                    stream = None
                    if info.issym():
                        resolved = posixpath.normpath(posixpath.join(
                            posixpath.dirname(name), info.linkname))
                        if (info.linkname.startswith("/") or resolved == ".." or
                                resolved.startswith("../")):
                            bb.fatal("SDK archive symlink escapes payload: %s" % name)
                        links[name] = info.linkname
                    elif info.isfile():
                        if metadata.get("source_only"):
                            with source.open("rb") as check:
                                if check.read(4) == b"\x7fELF":
                                    bb.fatal("ELF file in source-only SDK export: %s" % source)
                        files[name] = edge_ai_sdk_hash(source)
                        stream = source.open("rb")
                    elif not info.isdir():
                        bb.fatal("Unsupported SDK archive member: %s" % name)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = epoch
                info.pax_headers = {}
                try:
                    output.addfile(info, stream)
                finally:
                    if stream is not None:
                        stream.close()
        temporary.replace(archive)
    finally:
        if temporary.exists():
            temporary.unlink()
    manifest = {
        "format_version": 1, "component": component,
        "recipe": d.getVar("PN"), "version": d.getVar("PV"),
        "machine": d.getVar("MACHINE"), "l4t_version": d.getVar("L4T_VERSION"),
        "kernel_release": metadata["kernel_release"],
        "archive": archive.name, "archive_sha256": edge_ai_sdk_hash(archive),
        "files": files, "symlinks": links, "metadata": metadata,
    }
    (target / (component + ".json")).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n")

def edge_ai_sdk_config(path):
    import re
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
        elif match := re.fullmatch(r"# (CONFIG_\w+) is not set", line):
            values[match[1]] = "n"
    return values

def edge_ai_sdk_module_tree(d, release):
    from pathlib import Path
    # do_package restores PKGD in sstate-plaindirs. These are the stripped
    # module payloads an image installs, without depending on image/rootfs tasks.
    path = (Path(d.getVar("PKGD")) /
            d.getVar("nonarch_base_libdir").lstrip("/") / "modules" / release)
    if not path.is_dir():
        bb.fatal("SDK export lacks packaged module payloads: %s" % path)
    return path

def edge_ai_sdk_export_kernel(d):
    from pathlib import Path
    if d.getVar("EDGE_AI_SDK_EXPORTS") != "1":
        return
    build = Path(d.getVar("B"))
    release_file = build / "include/config/kernel.release"
    release = release_file.read_text().strip()
    if release != d.getVar("KERNEL_VERSION"):
        bb.fatal("SDK kernel release differs from installed module version")
    installed = Path(d.getVar("D"))
    modules = edge_ai_sdk_module_tree(d, release)
    boot = installed / d.getVar("KERNEL_IMAGEDEST").lstrip("/")
    config = build / ".config"
    actual = edge_ai_sdk_config(config)
    entries = {
        "boot/Image": boot / ("Image-" + release),
        "boot/config-" + release: config,
        "usr/lib/modules/" + release: modules,
        "metadata/kernel.release": release_file,
        "metadata/base-Module.symvers": build / "Module.symvers",
        "metadata/kernel.config": config,
        "metadata/licenses/" + d.getVar("PN"): edge_ai_sdk_licenses(d),
    }
    requests = {}
    unpacked = Path(d.getVar("UNPACKDIR"))
    fragments = [unpacked / "compulab.cfg"]
    if d.getVar("PN").startswith("linux-noble-nvidia-tegra"):
        fragments.append(unpacked / "adi-gmsl-v18-noble/edge-ai-noble.cfg")
        if "adi-gmsl-v18" in (d.getVar("OVERRIDES") or "").split(":"):
            fragments.append(unpacked / "adi-gmsl-v18-noble/edgedes-adi-v18.cfg")
    for fragment in fragments:
        for name, value in edge_ai_sdk_config(fragment).items():
            if name in requests and requests[name] != value:
                bb.fatal("Conflicting SDK kernel config request: %s" % name)
            if actual.get(name) != value:
                bb.fatal("SDK kernel config request was not honored: %s" % name)
            requests[name] = value
        entries["metadata/config-fragments/" + fragment.name] = fragment
    prefix = "usr/lib/modules/" + release
    edge_ai_sdk_pack(d, "kernel", entries, {
        "kernel_release": release, "kernel_provider": d.getVar("PN"),
        "image": "boot/Image", "config": "metadata/kernel.config",
        "symvers": "metadata/base-Module.symvers", "config_requests": requests,
        "compiler": actual.get("CONFIG_CC_VERSION_TEXT"),
        "modversions": actual.get("CONFIG_MODVERSIONS"),
        "module_input": "packaged",
        "license_expression": d.getVar("LICENSE"),
    }, excluded=(prefix + "/build", prefix + "/source"), excluded_parts=(".debug",))

def edge_ai_sdk_export_oot(d):
    from pathlib import Path
    if d.getVar("EDGE_AI_SDK_EXPORTS") != "1":
        return
    release = d.getVar("KERNEL_VERSION")
    installed = Path(d.getVar("D"))
    headers = installed / d.getVar("includedir").lstrip("/") / d.getVar("BPN")
    modules = edge_ai_sdk_module_tree(d, release)
    prefix = "usr/lib/modules/" + release
    replacements = (d.getVar("TEGRA_OOT_REPLACEMENT_DRIVERS") or "").split()
    entries = {
        prefix: modules,
        "usr/include/nvidia-kernel-oot": headers,
        "metadata/kernel.release": (release + "\n").encode(),
        "metadata/oot-Module.symvers": headers / "Module.symvers",
        "metadata/replacement-drivers.txt": ("\n".join(replacements) + "\n").encode(),
        "metadata/licenses/" + d.getVar("PN"): edge_ai_sdk_licenses(d),
    }
    edge_ai_sdk_pack(d, "nvidia-kernel-oot", entries, {
        "kernel_release": release, "symvers": "metadata/oot-Module.symvers",
        "headers": "usr/include/nvidia-kernel-oot",
        "replacement_drivers": replacements,
        "module_input": "packaged",
        "license_expression": d.getVar("LICENSE"),
    }, excluded=(prefix + "/build", prefix + "/source"), excluded_parts=(".debug",))

def edge_ai_sdk_export_devsrc(d):
    from pathlib import Path
    if d.getVar("EDGE_AI_SDK_EXPORTS") != "1":
        return
    release = d.getVar("KERNEL_VERSION")
    installed = Path(d.getVar("D"))
    tree = (installed / d.getVar("nonarch_base_libdir").lstrip("/") /
            "modules" / release / "build")
    if (tree / "include/config/kernel.release").read_text().strip() != release:
        bb.fatal("SDK development sources carry a different kernel release")
    entries = {
        "usr": installed / "usr",
        "metadata/kernel.release": (release + "\n").encode(),
        "metadata/licenses/" + d.getVar("PN"): edge_ai_sdk_licenses(d),
    }
    # Preserve a non-usrmerge recipe layout too; its usr/src/kernel symlink
    # points at that original lib/modules tree rather than usr/lib/modules.
    legacy = d.getVar("nonarch_base_libdir").lstrip("/").split("/")[0]
    if legacy != "usr":
        entries[legacy] = installed / legacy
    edge_ai_sdk_pack(d, "kernel-devsrc", entries,
        {"kernel_release": release, "source_only": True,
        "license_expression": d.getVar("LICENSE")})
# Python helpers end.

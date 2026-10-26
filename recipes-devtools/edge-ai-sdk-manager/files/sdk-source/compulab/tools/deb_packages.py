#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build native add-on packages from private trees, never install them."""

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import tempfile


PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]+\Z")
VERSION = re.compile(r"(?:[0-9]+:)?[0-9][A-Za-z0-9.+~\-]*\Z")
ARCHITECTURE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
DEPENDENCY = re.compile(
    r"[a-z0-9][a-z0-9+.-]+(?::[a-z0-9-]+)?"
    r"(?:\s*\((?:<<|<=|=|>=|>>)\s*[0-9][A-Za-z0-9.+~:-]*\))?\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def clean_text(value, label):
    require(isinstance(value, str) and bool(value) and
            all(character.isprintable() for character in value),
            "Invalid " + label)
    return value


def package_path(value):
    """Accept one canonical, absolute Unix payload path, not a glob."""
    value = clean_text(value, "package path")
    path = PurePosixPath(value)
    require(path.is_absolute() and path.anchor == "/" and value != "/" and
            path.as_posix() == value and ".." not in path.parts and
            "\\" not in value,
            "Unsafe package path: " + value)
    return value


def canonical_directory(path, label, *, create=False):
    path = Path(path)
    require(path.is_absolute() and path != Path("/") and
            path.resolve(strict=False) == path,
            label + " must be a canonical absolute directory")
    if create and not path.exists():
        path.mkdir(parents=True, mode=0o755)
    require(path.is_dir() and not path.is_symlink(),
            label + " must be a real directory")
    return path


def payload_files(payload):
    require(not (payload / "DEBIAN").exists() and
            not (payload / "DEBIAN").is_symlink(),
            "Payload must not contain package control data")
    files = []
    for directory, subdirectories, names in os.walk(payload,
                                                   followlinks=False):
        for name in sorted(subdirectories + names):
            path = Path(directory) / name
            relative = path.relative_to(payload).as_posix()
            package_path("/" + relative)
            info = path.lstat()
            require(stat.S_ISDIR(info.st_mode) or
                    stat.S_ISREG(info.st_mode) or
                    stat.S_ISLNK(info.st_mode),
                    "Special file in package payload: " + relative)
            if stat.S_ISLNK(info.st_mode):
                target = path.readlink()
                require(not target.is_absolute(),
                        "Absolute payload symlink: " + relative)
                try:
                    resolved = path.resolve(strict=True)
                except (OSError, RuntimeError) as error:
                    raise ValueError("Unresolved payload symlink: " +
                                     relative) from error
                require(resolved.is_relative_to(payload),
                        "Escaping payload symlink: " + relative)
            if not stat.S_ISDIR(info.st_mode):
                files.append(relative)
    return sorted(files)


def checked_dependencies(depends):
    require(not isinstance(depends, (str, bytes)),
            "Dependencies must be a sequence")
    result = []
    for dependency in depends:
        dependency = clean_text(dependency, "dependency")
        require(all(DEPENDENCY.fullmatch(alternative.strip())
                    for alternative in dependency.split("|")),
                "Invalid dependency: " + dependency)
        require(dependency not in result, "Duplicate dependency")
        result.append(dependency)
    return result


def diversion_scripts(name, diversions):
    """Generate guarded, package-owned diversions, with no target services."""
    common = """#!/bin/sh
set -eu
package=%s
root=${DPKG_ROOT:-}
case "$root" in ''|/*) ;; *)
    printf 'Invalid DPKG_ROOT.\\n' >&2; exit 1 ;;
esac
root=${root%%/}
fail() { printf 'CompuLab package: %%s\\n' "$*" >&2; exit 1; }
divert() {
    if [ -n "$root" ]; then
        dpkg-divert --root "$root" "$@"
    else
        dpkg-divert "$@"
    fi
}
owned() {
    owner=$(divert --listpackage "$1") || return 1
    case "$owner" in
        '') return 1 ;;
        "$package")
            [ "$(divert --truename "$1")" = "$2" ] ||
                fail "unexpected diversion destination for $1"
            return 0 ;;
        *) fail "foreign diversion for $1: $owner" ;;
    esac
}
""" % shlex.quote(name)
    preinst = common + """check_add() {
    if owned "$1" "$2"; then return 0; fi
    [ ! -e "$root$2" ] && [ ! -L "$root$2" ] ||
        fail "diversion destination already exists: $2"
    [ ! -d "$root$1" ] || fail "cannot divert a directory: $1"
}
add() {
    check_add "$1" "$2"
    if owned "$1" "$2"; then return 0; fi
    divert --package "$package" --add --rename --divert "$2" "$1"
}
case "${1-}" in install|upgrade)
"""
    postrm = common + """check_remove() {
    if ! owned "$1" "$2"; then return 0; fi
    [ ! -e "$root$1" ] && [ ! -L "$root$1" ] ||
        fail "refusing to overwrite an existing file while restoring $1"
    [ ! -d "$root$2" ] || fail "invalid diversion backup directory: $2"
}
remove() {
    check_remove "$1" "$2"
    if ! owned "$1" "$2"; then return 0; fi
    divert --package "$package" --remove --rename --divert "$2" "$1"
}
case "${1-}" in remove|purge|abort-install|disappear)
"""
    # Preflight the whole set before mutating even its first entry.
    for original, destination in diversions:
        arguments = shlex.quote(original) + " " + shlex.quote(destination)
        preinst += "    check_add " + arguments + "\n"
        postrm += "    check_remove " + arguments + "\n"
    for original, destination in diversions:
        arguments = shlex.quote(original) + " " + shlex.quote(destination)
        preinst += "    add " + arguments + "\n"
        postrm += "    remove " + arguments + "\n"
    ending = "    ;;\nesac\nexit 0\n"
    return {"preinst": preinst + ending, "postrm": postrm + ending}


def build_package(payload, output, name, version, *, architecture="arm64",
                  depends=(), conffiles=(), diversions=(),
                  description="CompuLab Edge-AI add-on", scripts=None):
    """Return a new .deb in output; never modify payload or install packages."""
    require(isinstance(name, str) and PACKAGE.fullmatch(name),
            "Invalid Debian package name")
    require(isinstance(version, str) and VERSION.fullmatch(version) and
            version.count(":") <= 1 and not version.endswith(("-", ":")),
            "Invalid Debian package version")
    require(isinstance(architecture, str) and
            ARCHITECTURE.fullmatch(architecture), "Invalid architecture")
    description = clean_text(description, "package description")
    dependencies = checked_dependencies(depends)
    payload = canonical_directory(payload, "Payload")
    output = Path(output)
    require(not output.resolve(strict=False).is_relative_to(payload),
            "Package output must not be inside its payload")
    files = payload_files(payload)
    require(files, "Package payload must not be empty")
    regular = {"/" + path for path in files
               if not (payload / path).is_symlink()}
    require(not isinstance(conffiles, (str, bytes)),
            "Conffiles must be a sequence")
    configuration = [package_path(path) for path in conffiles]
    require(len(set(configuration)) == len(configuration),
            "Duplicate conffile")
    require(set(configuration).issubset(regular),
            "Conffiles must be regular package payloads")
    pairs = []
    names = set()
    for pair in diversions:
        require(isinstance(pair, (tuple, list)) and len(pair) == 2,
                "Each diversion needs an original and destination")
        original, destination = map(package_path, pair)
        require(original in regular and original != destination,
                "Diversion must replace a regular package payload")
        require(destination not in {"/" + path for path in files} and
                not (payload / destination.lstrip("/")).exists(),
                "Diversion backup must not be a package payload")
        require(original not in names and destination not in names,
                "Duplicate or overlapping diversion paths")
        names.update((original, destination))
        pairs.append((original, destination))
    require(not configuration or not set(configuration).intersection(names),
            "Conffiles cannot also be diversions")
    controls = {}
    if scripts is not None:
        require(isinstance(scripts, dict), "Scripts must be a dictionary")
        for key, value in scripts.items():
            require(key in ("preinst", "postinst", "prerm", "postrm") and
                    isinstance(value, str) and value.startswith("#!/bin/sh\n")
                    and "\0" not in value,
                    "Invalid maintainer script")
            controls[key] = value.rstrip("\n") + "\n"
    if pairs:
        require(not set(controls).intersection(("preinst", "postrm")),
                "Custom scripts conflict with generated diversion scripts")
        controls.update(diversion_scripts(name, pairs))
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "0")
    require(re.fullmatch(r"[0-9]+", epoch), "Invalid SOURCE_DATE_EPOCH")
    output = canonical_directory(output, "Output", create=True)
    destination = output / (name + "_" + version + "_" + architecture + ".deb")
    require(not destination.exists() and not destination.is_symlink(),
            "Package output already exists: " + str(destination))
    with tempfile.TemporaryDirectory(prefix=".compulab-deb-",
                                     dir=output) as temporary:
        temporary = Path(temporary)
        staging = temporary / "payload"
        shutil.copytree(payload, staging, symlinks=True)
        # Validate the copied tree too, before trusting it as an archive.
        require(payload_files(staging) == files,
                "Payload changed during package assembly")
        metadata = staging / "DEBIAN"
        metadata.mkdir(mode=0o755)
        metadata.chmod(0o755)
        control = ("Package: " + name + "\nVersion: " + version +
                   "\nArchitecture: " + architecture +
                   "\nMaintainer: CompuLab <support@compulab.co.il>\n" +
                   "Section: admin\nPriority: optional\n")
        if dependencies:
            control += "Depends: " + ", ".join(dependencies) + "\n"
        control += "Description: " + description + "\n"
        (metadata / "control").write_text(control, encoding="utf-8")
        (metadata / "control").chmod(0o644)
        checksums = []
        size = 0
        for relative in files:
            path = staging / relative
            if path.is_symlink():
                continue
            checksum = hashlib.md5(usedforsecurity=False)
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(block)
                    size += len(block)
            checksums.append(checksum.hexdigest() + "  " + relative + "\n")
        with (metadata / "control").open("a", encoding="utf-8") as stream:
            stream.write("Installed-Size: " + str((size + 1023) // 1024) + "\n")
        (metadata / "md5sums").write_text("".join(checksums), encoding="utf-8")
        (metadata / "md5sums").chmod(0o644)
        if configuration:
            (metadata / "conffiles").write_text(
                "".join(path + "\n" for path in sorted(configuration)),
                encoding="utf-8")
            (metadata / "conffiles").chmod(0o644)
        for key, value in controls.items():
            path = metadata / key
            path.write_text(value, encoding="utf-8")
            path.chmod(0o755)
        archive = temporary / "package.deb"
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group",
                        str(staging), str(archive)], check=True,
                       stdin=subprocess.DEVNULL,
                       env=dict(os.environ, SOURCE_DATE_EPOCH=epoch))
        archive.chmod(0o644)
        # link() is exclusive: unlike rename(), it cannot replace a racing
        # output file. The temporary name is removed when this context exits.
        os.link(archive, destination)
    return destination

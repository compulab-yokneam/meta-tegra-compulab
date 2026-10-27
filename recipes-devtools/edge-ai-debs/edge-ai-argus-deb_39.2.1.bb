SUMMARY = "Rebuild the Ubuntu-native CompuLab Argus Debian package"
DESCRIPTION = "Opt-in offline native ARM64 build using a prepared Ubuntu builder"
LICENSE = "MIT AND LicenseRef-Proprietary"
LIC_FILES_CHKSUM = " \
    file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302 \
    file://${UNPACKDIR}/runtime/files/Tegra_Software_License_Agreement-Tegra-Linux.txt;md5=376d20bd5275442226fcdf54e4844ddf \
"
LICENSE_FLAGS += "nvidia-argus-framos-demo"

# These are Ubuntu-native host build artifacts, not Yocto rootfs packages.
inherit nopackages
INHIBIT_DEFAULT_DEPS = "1"
FILESEXTRAPATHS:prepend := "${THISDIR}/files:${THISDIR}/../edge-ai-sdk-manager/files:${THISDIR}/../edge-ai-sdk-manager/files/sdk-source/compulab/tools:"
SRC_URI = " \
    file://build-argus-deb.py \
    file://runtime \
    file://runtime-assets.json \
    file://provision-runtime.py \
    file://deb_packages.py \
    file://rootfs_package_inventory.py \
"
S = "${UNPACKDIR}"
PACKAGE_ARCH = "${MACHINE_ARCH}"

# Reuse explicit SDK authorization when present; no SDK include is required.
EDGE_AI_ARGUS_DEB_ENABLE ?= "${@d.getVar('EDGE_AI_DEB_ENABLE') or d.getVar('EDGE_AI_SDK_ENABLE') or '0'}"
EDGE_AI_ARGUS_DEB_BUILDER ?= "${@d.getVar('EDGE_AI_DEB_BUILDER') or (d.getVar('EDGE_AI_SDK_HOST_WORK') or d.getVar('TOPDIR') + '/sdk-manager-work/' + d.getVar('MACHINE')) + '/ubuntu-runtime/builder'}"
EDGE_AI_ARGUS_DEB_HOST_WORK ?= "${TOPDIR}/argus-deb-work/${MACHINE}"
EDGE_AI_ARGUS_DEB_OUTPUT ?= "${DEPLOY_DIR_IMAGE}/edge-ai-argus-deb"
EDGE_AI_ARGUS_DEB_VERSION ?= "${@d.getVar('EDGE_AI_DEB_VERSION') or d.getVar('EDGE_AI_SDK_DEB_VERSION') or '39.2.1+compulab1'}"
EDGE_AI_ARGUS_DEB_JOBS ?= "${@d.getVar('EDGE_AI_DEB_JOBS') or '4'}"

python __anonymous() {
    import json
    import os

    # Only MMAPI is needed. Do not inherit the SDK runtime include, which
    # fetches unrelated GStreamer, NITO and builder-provisioning packages.
    path = os.path.join(d.getVar('THISDIR'), '../edge-ai-sdk-manager/files',
                        'runtime-assets.json')
    with open(path, encoding='utf-8') as stream:
        manifest = json.load(stream)
    source = next(asset for asset in manifest['assets'] if asset['id'] == 'mmapi')
    uri = manifest['bases'][source['source']] + source['path']
    uri += ';name=argusmmapi;unpack=0'
    d.setVar('EDGE_AI_ARGUS_DEB_MMAPI_URI', uri)
    d.setVarFlag('SRC_URI', 'argusmmapi.sha256sum', source['sha256'])
    d.appendVar('SRC_URI', ' ' + uri)
}

do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

python do_create_argus_deb() {
    import bb.fetch2
    import json
    import os
    from pathlib import Path
    import shutil
    import stat
    import subprocess
    import tempfile

    if d.getVar('EDGE_AI_ARGUS_DEB_ENABLE') != '1':
        bb.fatal('Set EDGE_AI_ARGUS_DEB_ENABLE = "1"; read the target README first')
    if os.geteuid() == 0:
        bb.fatal('Run BitBake as the ordinary build user, never root')
    # Reject dangerous paths before creating directories, changing modes,
    # writing markers, or copying the source archive into private work.
    def checked_path(value, label):
        if not isinstance(value, str) or not value:
            bb.fatal(label + ' must be a canonical absolute path')
        path = Path(value)
        if not path.is_absolute() or path == Path('/') or path.resolve() != path:
            bb.fatal(label + ' must be a canonical absolute path')
        return path

    def overlaps(left, right):
        return left.is_relative_to(right) or right.is_relative_to(left)

    private = checked_path(d.getVar('EDGE_AI_ARGUS_DEB_HOST_WORK'), 'EDGE_AI_ARGUS_DEB_HOST_WORK')
    output = checked_path(d.getVar('EDGE_AI_ARGUS_DEB_OUTPUT'), 'EDGE_AI_ARGUS_DEB_OUTPUT')
    protected = [checked_path(d.getVar(name), name) for name in
                 ('EDGE_AI_ARGUS_DEB_BUILDER', 'UNPACKDIR')]
    # An SDK is not required for this target. Protect it when its location
    # is known, including the SDK output root supplied by the SDK workflow.
    sdk = d.getVar('EDGE_AI_ARGUS_DEB_SDK') or d.getVar('EDGE_AI_DEB_SDK')
    if sdk:
        protected.append(checked_path(sdk, 'Argus SDK reference'))
    if d.getVar('EDGE_AI_SDK_OUTPUT'):
        protected.append(checked_path(d.getVar('EDGE_AI_SDK_OUTPUT'), 'EDGE_AI_SDK_OUTPUT'))
    for destination in (private, output):
        if any(overlaps(destination, source) for source in protected):
            bb.fatal('Argus work/output must not overlap SDK, builder or unpacked sources')
    if overlaps(private, output):
        bb.fatal('Argus private work must not overlap its publication directory')
    if private.exists() and (not private.is_dir() or private.stat().st_uid != os.getuid()):
        bb.fatal('Argus private work must belong to the current build user')
    marker = private / '.edge-ai-argus-deb-work'
    marker_text = 'CompuLab Argus Debian private work directory, version 1\n'
    if marker.exists() or marker.is_symlink():
        info = marker.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or
                marker.read_text() != marker_text):
            bb.fatal('Invalid Argus private-work ownership marker')
    elif private.exists() and any(private.iterdir()):
        bb.fatal('Choose a new EDGE_AI_ARGUS_DEB_HOST_WORK; existing work is not owned by this task')
    if output.parent.exists() and (not output.parent.is_dir() or
                                   output.parent.stat().st_uid != os.getuid()):
        bb.fatal('Argus publication parent must belong to the current build user')
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    if not marker.exists():
        marker.write_text(marker_text)
        marker.chmod(0o600)

    # Create the cooperating SDK lock as the ordinary user, not sudo/root.
    descriptor = os.open('/tmp/edge-ai-sdkmanager.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            bb.fatal('The SDK coordination lock must belong to the build user')
    finally:
        os.close(descriptor)

    inputs = private / 'inputs'
    if inputs.is_symlink():
        bb.fatal('Refusing a symlinked Argus input directory')
    inputs.mkdir(exist_ok=True)
    uri = d.getVar('EDGE_AI_ARGUS_DEB_MMAPI_URI')
    fetched = Path(bb.fetch2.Fetch([uri], d).localpath(uri))
    source_deb = inputs / fetched.name
    if source_deb.is_symlink():
        bb.fatal('Refusing a symlinked MMAPI input')
    descriptor, temporary = tempfile.mkstemp(prefix='.mmapi-', dir=inputs)
    os.close(descriptor)
    try:
        shutil.copyfile(fetched, temporary)
        os.chmod(temporary, 0o644)
        os.replace(temporary, source_deb)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    sources = Path(d.getVar('UNPACKDIR')).resolve()
    configuration = dict(
        format_version=1, uid=os.getuid(), gid=os.getgid(),
        builder=d.getVar('EDGE_AI_ARGUS_DEB_BUILDER'), work=str(private),
        output=d.getVar('EDGE_AI_ARGUS_DEB_OUTPUT'), sources=str(sources),
        bundle=str(sources / 'runtime'), source_deb=str(source_deb),
        version=d.getVar('EDGE_AI_ARGUS_DEB_VERSION'),
        jobs=int(d.getVar('EDGE_AI_ARGUS_DEB_JOBS')))
    descriptor, filename = tempfile.mkstemp(
        prefix='configuration-', suffix='.json', dir=private)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(configuration, stream, indent=2)

    # Deliberately use host tools and an empty target environment in chroot.
    environment = dict(os.environ)
    environment['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PSEUDO_PREFIX',
                'PSEUDO_LOCALSTATEDIR'):
        environment.pop(key, None)
    subprocess.run([
        'sudo', '-n', '/usr/bin/python3', '-B',
        str(sources / 'build-argus-deb.py'), '--config', filename, '--execute'],
        env=environment, stdin=subprocess.DEVNULL, check=True)
}

# External Ubuntu inputs are checked by the helper on every invocation.
# No dependency on SDK creation, kernel, DT, firmware or a Yocto image.
do_create_argus_deb[nostamp] = "1"
# BitBake's network-disable user namespace cannot elevate through sudo.
# This privileged host task must stay outside it; the helper runs no APT,
# SDK Manager or downloads, and only do_fetch retrieves the pinned source.
do_create_argus_deb[network] = "1"
addtask create_argus_deb after do_unpack before do_build

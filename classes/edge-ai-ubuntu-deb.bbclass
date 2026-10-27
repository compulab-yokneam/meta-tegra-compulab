# Standalone Ubuntu archives; never install Yocto userspace into Ubuntu.
inherit nopackages
INHIBIT_DEFAULT_DEPS = "1"
S = "${UNPACKDIR}"
PACKAGE_ARCH = "${MACHINE_ARCH}"

EDGE_AI_DEB_ENABLE ?= "${@d.getVar('EDGE_AI_SDK_ENABLE') or '0'}"
EDGE_AI_DEB_VERSION ?= "${@d.getVar('EDGE_AI_SDK_DEB_VERSION') or '39.2.1+compulab1'}"
EDGE_AI_DEB_JOBS ?= "4"
EDGE_AI_DEB_DEPLOY_ROOT ?= "${DEPLOY_DIR_IMAGE}/edge-ai-debs"
EDGE_AI_DEB_HOST_WORK ?= "${TOPDIR}/ubuntu-deb-work/${MACHINE}/${EDGE_AI_DEB_COMPONENT}"
EDGE_AI_DEB_OUTPUT ?= "${EDGE_AI_DEB_DEPLOY_ROOT}/${EDGE_AI_DEB_COMPONENT}"
EDGE_AI_DEB_SDK ?= "${@(d.getVar('EDGE_AI_SDK_OUTPUT') or d.getVar('DEPLOY_DIR_IMAGE') + '/jetpack-7.2.1-image-build') + '/JetPack_7.2.1_Linux_JETSON_ORIN_NX_TARGETS/Linux_for_Tegra'}"
EDGE_AI_DEB_BUILDER ?= "${@(d.getVar('EDGE_AI_SDK_HOST_WORK') or d.getVar('TOPDIR') + '/sdk-manager-work/' + d.getVar('MACHINE')) + '/ubuntu-runtime/builder'}"
EDGE_AI_DEB_ARGUS_OUTPUT ?= "${@d.getVar('EDGE_AI_ARGUS_DEB_OUTPUT') or d.getVar('DEPLOY_DIR_IMAGE') + '/edge-ai-argus-deb'}"

do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

python do_create_deb() {
    import bb.fetch
    import json
    import os
    from pathlib import Path
    import shutil
    import stat
    import subprocess
    import tempfile

    if d.getVar('EDGE_AI_DEB_ENABLE') != '1':
        bb.fatal('Set EDGE_AI_DEB_ENABLE = "1"; see recipes-devtools/edge-ai-debs/README.md')
    if os.geteuid() == 0:
        bb.fatal('Run BitBake as the ordinary build user, not root')
    # Validate every path before mkdir/chmod/asset staging. The privileged
    # helper repeats these checks, but must not be our first protection.
    def checked_path(value, label):
        if not isinstance(value, str) or not value:
            bb.fatal(label + ' must be a canonical absolute path')
        path = Path(value)
        if not path.is_absolute() or path == Path('/') or path.resolve() != path:
            bb.fatal(label + ' must be a canonical absolute path')
        return path

    def overlaps(left, right):
        return left.is_relative_to(right) or right.is_relative_to(left)

    private = checked_path(d.getVar('EDGE_AI_DEB_HOST_WORK'), 'EDGE_AI_DEB_HOST_WORK')
    output = checked_path(d.getVar('EDGE_AI_DEB_OUTPUT'), 'EDGE_AI_DEB_OUTPUT')
    deploy_root = checked_path(d.getVar('EDGE_AI_DEB_DEPLOY_ROOT'), 'EDGE_AI_DEB_DEPLOY_ROOT')
    protected = [checked_path(d.getVar(name), name) for name in
                 ('EDGE_AI_DEB_BUILDER', 'EDGE_AI_DEB_SDK', 'UNPACKDIR')]
    for destination in (private, output, deploy_root):
        if any(overlaps(destination, source) for source in protected):
            bb.fatal('Component work/output must not overlap SDK, builder or unpacked sources')
    argus_output = checked_path(d.getVar('EDGE_AI_DEB_ARGUS_OUTPUT'), 'EDGE_AI_DEB_ARGUS_OUTPUT')
    if any(overlaps(private, publication) for publication in (output, deploy_root, argus_output)):
        bb.fatal('Component private work must not overlap publication directories')
    if private.exists() and (not private.is_dir() or private.stat().st_uid != os.getuid()):
        bb.fatal('Component private work must belong to this build user')
    marker = private / '.edge-ai-component-deb-work'
    marker_text = 'CompuLab Ubuntu component Debian work, version 1\n'
    if marker.exists() or marker.is_symlink():
        info = marker.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or
                marker.read_text() != marker_text):
            bb.fatal('Invalid component private-work marker')
    elif private.exists() and any(private.iterdir()):
        bb.fatal('Refusing unmarked nonempty component private work')

    # Create shared publication parents as the ordinary build user, not
    # sudo/root. Never repair ownership or permissions of foreign parents.
    for parent in (deploy_root, output.parent):
        if parent.exists() and (not parent.is_dir() or parent.stat().st_uid != os.getuid()):
            bb.fatal('Publication parent must belong to this build user: ' + str(parent))
    for parent in (deploy_root, output.parent):
        parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    if not marker.exists():
        marker.write_text(marker_text)
        marker.chmod(0o600)
    descriptor = os.open('/tmp/edge-ai-sdkmanager.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            bb.fatal('SDK coordination lock must belong to this build user')
    finally:
        os.close(descriptor)
    inputs = private / 'inputs'
    if inputs.is_symlink():
        bb.fatal('Refusing symlinked component inputs')
    inputs.mkdir(exist_ok=True)
    assets = {}
    uris = json.loads(d.getVar('EDGE_AI_DEB_ASSET_URIS'))
    fetcher = bb.fetch.Fetch(list(uris.values()), d) if uris else None
    for name, uri in uris.items():
        fetched = Path(fetcher.localpath(uri))
        target = inputs / fetched.name
        if target.is_symlink():
            bb.fatal('Refusing symlinked component asset')
        descriptor, temporary = tempfile.mkstemp(prefix='.input-', dir=inputs)
        os.close(descriptor)
        try:
            shutil.copyfile(fetched, temporary)
            os.chmod(temporary, 0o644)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        assets[name] = str(target)
    components = ('argus', 'gstreamer', 'kernel', 'device-trees',
                  'uefi-capsules', 'boot-tools', 'camera-support', 'bsp-policy')
    versions = {name: d.getVar('EDGE_AI_DEB_VERSION') for name in components}
    versions['argus'] = d.getVar('EDGE_AI_ARGUS_DEB_VERSION') or versions['argus']
    versions['meta'] = d.getVar('EDGE_AI_DEB_VERSION')
    publications = {name: d.getVar('EDGE_AI_DEB_DEPLOY_ROOT') + '/' + name
                    for name in components}
    publications['argus'] = d.getVar('EDGE_AI_DEB_ARGUS_OUTPUT')
    publications['meta'] = d.getVar('EDGE_AI_DEB_DEPLOY_ROOT') + '/meta'
    sources = str(Path(d.getVar('UNPACKDIR')).resolve())
    config = dict(
        schema=1, component=d.getVar('EDGE_AI_DEB_COMPONENT'),
        uid=os.getuid(), gid=os.getgid(), work=str(private),
        output=d.getVar('EDGE_AI_DEB_OUTPUT'), sources=sources,
        bundle=sources + '/runtime', assets=assets,
        builder=d.getVar('EDGE_AI_DEB_BUILDER'), sdk=d.getVar('EDGE_AI_DEB_SDK'),
        deploy=d.getVar('DEPLOY_DIR_IMAGE'), version=d.getVar('EDGE_AI_DEB_VERSION'),
        versions=versions, publications=publications,
        imx676_extended=d.getVar('EDGE_AI_IMX676_EXTENDED_MODES') or '1',
        imx678_extended=d.getVar('EDGE_AI_IMX678_EXTENDED_MODES') or '0',
        legacy_guids=(d.getVar('EDGE_AI_UEFI_LEGACY_FMP_GUIDS') or '').split(),
        jobs=int(d.getVar('EDGE_AI_DEB_JOBS')))
    descriptor, filename = tempfile.mkstemp(prefix='configuration-', suffix='.json', dir=private)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(config, stream, indent=2)
    environment = dict(os.environ)
    environment['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PSEUDO_PREFIX', 'PSEUDO_LOCALSTATEDIR'):
        environment.pop(key, None)
    subprocess.run(['sudo', '-n', '/usr/bin/python3', '-B',
                    sources + '/build-component-deb.py', '--config', filename, '--execute'],
                   env=environment, stdin=subprocess.DEVNULL, check=True)
}

do_create_deb[nostamp] = "1"
# A host-privileged task cannot elevate through BitBake's network userns.
# Helpers use only prepared inputs; no SDK Manager or APT is invoked.
do_create_deb[network] = "1"
addtask create_deb after do_unpack before do_build

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Standalone Ubuntu component archives; default is a read-only plan.

Execution is explicitly privileged. Only private work and new publication
directories are modified. Never invoke SDK Manager, APT, flashing or a DUT.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile

COMPONENTS = ('argus', 'gstreamer', 'kernel', 'device-trees', 'uefi-capsules',
              'boot-tools', 'camera-support', 'bsp-policy', 'meta')
WORK_ID = 'CompuLab Ubuntu component Debian work, version 1\n'
OUTPUT_ID = 'CompuLab Ubuntu component Debian output, version 1\n'
MODES = {'kernel': 'arm64', 'gstreamer': 'arm64', 'argus': 'arm64'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.resolve() == path,
            'Expected canonical regular file: ' + str(path))
    return path


def canonical(value):
    require(isinstance(value, (str, Path)), 'Path must be a string')
    path = Path(value)
    require(path.is_absolute() and path != Path('/') and path.resolve() == path,
            'Expected canonical absolute path: ' + str(path))
    return path


def version(value):
    require(isinstance(value, str) and
            re.fullmatch(r'39\.2\.1[+~.A-Za-z0-9-]*', value) and
            not value.endswith('-'), 'Expected an R39.2.1 Debian version')
    return value


def checked_configuration(value):
    expected = {'schema', 'component', 'uid', 'gid', 'work', 'output', 'sources',
                'bundle', 'assets', 'builder', 'sdk', 'deploy', 'version',
                'versions', 'publications', 'imx676_extended', 'imx678_extended',
                'jobs'}
    require(isinstance(value, dict) and set(value) in
            (expected, expected | {'legacy_guids'}), 'Invalid component configuration fields')
    require(type(value['schema']) is int and value['schema'] == 1,
            'Unsupported component schema')
    result = dict(value)
    require(result['component'] in COMPONENTS[1:] + ('bundle',),
            'Unknown standalone component')
    for key in ('uid', 'gid', 'jobs'):
        require(type(result[key]) is int, 'Expected integer: ' + key)
    require(result['uid'] > 0 and result['gid'] >= 0 and
            1 <= result['jobs'] <= 64, 'Invalid owner or job count')
    for key in ('work', 'output', 'sources', 'bundle', 'builder', 'sdk', 'deploy'):
        result[key] = canonical(result[key])
    require(result['sources'].is_dir() and result['bundle'].is_dir(),
            'Missing component source bundle')
    for left in ('work', 'output'):
        for right in ('sdk', 'builder', 'sources', 'bundle'):
            require(not result[left].is_relative_to(result[right]) and
                    not result[right].is_relative_to(result[left]),
                    'Work/publication overlaps a source or SDK input')
    require(not result['work'].is_relative_to(result['output']) and
            not result['output'].is_relative_to(result['work']),
            'Work and output must be separate')
    result['version'] = version(result['version'])
    require(isinstance(result['versions'], dict) and
            set(result['versions']) == set(COMPONENTS), 'Incomplete component version map')
    result['versions'] = {name: version(item) for name, item in result['versions'].items()}
    require(isinstance(result['publications'], dict) and
            set(result['publications']) == set(COMPONENTS), 'Incomplete publication map')
    result['publications'] = {name: canonical(item)
                              for name, item in result['publications'].items()}
    require(isinstance(result['assets'], dict), 'Invalid pinned asset map')
    result['assets'] = {name: canonical(item) for name, item in result['assets'].items()}
    for path in result['assets'].values():
        regular(path)
    require(result['imx676_extended'] in ('0', '1') and
            result['imx678_extended'] in ('0', '1'), 'Invalid NITO mode selection')
    result.setdefault('legacy_guids', [])
    require(isinstance(result['legacy_guids'], list) and
            len(result['legacy_guids']) == len(set(result['legacy_guids'])) and
            all(isinstance(guid, str) and re.fullmatch(
                r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}', guid)
                for guid in result['legacy_guids']), 'Invalid legacy capsule GUIDs')
    return result


def support(config):
    return load(config['sources'] / 'build-argus-deb.py', 'component_argus_support')


def package_name(component):
    return 'compulab-edge-ai' if component == 'meta' else 'compulab-edge-ai-' + component


def package_spec(config):
    component = config['component']
    inventory = load(config['sources'] / 'rootfs_package_inventory.py', 'component_inventory')
    return dict(name=package_name(component), architecture=MODES.get(component, 'all'),
                depends=list(inventory.component_dependencies(
                    component, config['version'], config['versions'])))


def module_for(config):
    component = config['component']
    name = ('build-gstreamer-deb.py' if component == 'gstreamer' else
            'build-boot-payloads.py' if component in ('kernel', 'device-trees')
            else 'build-data-payloads.py')
    return load(config['sources'] / name, 'component_' + component.replace('-', '_')), name


def archive_payload(archive):
    """Stream data without extracting privileged paths or buffering modules."""
    files = {}
    process = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(archive)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as stream:
            for member in stream:
                name = member.name.removeprefix('./')
                if member.isdir():
                    continue
                relative = PurePosixPath(name)
                require(member.isfile() and name and not relative.is_absolute() and
                        '..' not in relative.parts and relative.as_posix() == name and
                        name not in files and member.uid == 0 and member.gid == 0,
                        'Unsafe, duplicate or non-root package payload')
                checksum = hashlib.sha256()
                md5 = hashlib.md5(usedforsecurity=False)
                with stream.extractfile(member) as data:
                    while block := data.read(1024 * 1024):
                        checksum.update(block)
                        md5.update(block)
                files[name] = dict(sha256=checksum.hexdigest(), md5=md5.hexdigest(),
                                   mode=member.mode)
        error = process.stderr.read().decode(errors='replace')
        require(process.wait() == 0, 'Cannot inspect package archive: ' + error)
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
    return files


def verify_archive_info(info, directory, uid, component, expected_version):
    """Validate actual archive data/control, never trust a receipt alone."""
    require(isinstance(info, dict), 'Invalid package record')
    require(info['name'] == package_name(component) and
            info['architecture'] == MODES.get(component, 'all') and
            info['version'] == expected_version and
            info['filename'] == info['name'] + '_' + version(info['version']) +
            '_' + info['architecture'] + '.deb', 'Package identity mismatch')
    require(isinstance(info['depends'], list) and
            all(isinstance(item, str) and item for item in info['depends']) and
            len(info['depends']) == len(set(info['depends'])),
            'Invalid package dependency record')
    archive = regular(directory / info['filename'])
    require(archive.stat().st_uid == uid and stat.S_IMODE(archive.stat().st_mode) == 0o644,
            'Unexpected archive owner/mode')
    require(digest(archive) == info['sha256'], 'Archive checksum mismatch')
    for field, expected in [('Package', info['name']), ('Version', info['version']),
                            ('Architecture', info['architecture']),
                            ('Depends', ', '.join(info['depends']))]:
        actual = subprocess.check_output(['dpkg-deb', '-f', str(archive), field], text=True).strip()
        require(actual == expected, 'Archive control field changed: ' + field)
    actual_files = archive_payload(archive)
    require({name: row['sha256'] for name, row in actual_files.items()} == info['files'],
            'Archive payload inventory/hash mismatch')
    if 'file_modes' in info:
        require({name: row['mode'] for name, row in actual_files.items()} == info['file_modes'],
                'Archive payload mode mismatch')
    if component == 'argus':
        require(all(row['mode'] == (0o755 if name.startswith('usr/bin/') else 0o644)
                    for name, row in actual_files.items()), 'Argus archive mode mismatch')
    with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(
            ['dpkg-deb', '--ctrl-tarfile', str(archive)]))) as control:
        md5 = control.extractfile('./md5sums').read().decode()
        rows = md5.splitlines()
        require(len(rows) == len(actual_files) and
                all(re.fullmatch(r'[0-9a-f]{32}  .+', line) for line in rows) and
                dict(line.split('  ', 1)[::-1] for line in rows) ==
                {name: row['md5'] for name, row in actual_files.items()},
                'Debian payload md5sums mismatch')
        if 'conffiles' in info:
            names = control.getnames()
            actual = (control.extractfile('./conffiles').read().decode().splitlines()
                      if './conffiles' in names else [])
            require(sorted(actual) == sorted(info['conffiles']), 'Debian conffiles mismatch')
    return actual_files


def verify_publication(destination, signature, uid, component):
    destination = canonical(destination)
    require(destination.is_dir() and destination.stat().st_uid == uid and
            stat.S_IMODE(destination.stat().st_mode) == 0o755,
            'Invalid publication owner/mode')
    manifest_file = regular(destination / 'manifest.json')
    manifest = json.loads(manifest_file.read_text())
    require(manifest.get('schema') == 1 and manifest.get('component') == component and
            manifest.get('fingerprint') == signature and
            manifest['inputs'].get('component') == component and
            hashlib.sha256(json.dumps(manifest['inputs'], sort_keys=True,
                separators=(',', ':')).encode()).hexdigest() == signature,
            'Publication input fingerprint mismatch')
    info = manifest['package']
    require({name: info[name] for name in ('name', 'architecture', 'depends')} ==
            manifest['inputs']['package_spec'], 'Package specification changed')
    verify_archive_info(info, destination, uid, component, manifest['inputs']['version'])
    expected = info['sha256'] + '  ' + info['filename'] + '\n' + digest(manifest_file) + '  manifest.json\n'
    require(regular(destination / 'SHA256SUMS').read_text() == expected,
            'Publication checksum list mismatch')
    require({p.name for p in destination.iterdir()} ==
            {info['filename'], 'manifest.json', 'SHA256SUMS'}, 'Unexpected publication files')
    for path in destination.iterdir():
        require(path.stat().st_uid == uid and stat.S_IMODE(path.stat().st_mode) == 0o644,
                'Unexpected publication file owner/mode')
    return manifest


def read_current(config, component):
    root = config['publications'][component]
    pointer = regular(root / 'current.json')
    require(pointer.stat().st_uid == config['uid'], 'Unexpected component receipt owner')
    value = json.loads(pointer.read_text())
    require(value.get('schema') == 1 and value.get('component') == component and
            re.fullmatch('[0-9a-f]{64}', value.get('fingerprint', '')),
            'Invalid component publication receipt')
    destination = root / value['fingerprint']
    require(value.get('publication') == str(destination) and
            digest(regular(destination / 'manifest.json')) == value.get('manifest_sha256'),
            'Component receipt refers to stale or foreign publication')
    if component == 'argus':
        result = support(config).verify_publication(destination, value['fingerprint'], config['uid'])
    else:
        result = verify_publication(destination, value['fingerprint'], config['uid'], component)
    require(result['package']['version'] == config['versions'][component],
            'Coordinated component version mismatch: ' + component)
    return destination, result


def fingerprint(config):
    common = ('build-component-deb.py', 'deb_packages.py', 'rootfs_package_inventory.py')
    inputs = dict(schema=1, component=config['component'], version=config['version'],
                  versions=config['versions'], sources={name: digest(regular(config['sources'] / name))
                                                         for name in common})
    if config['component'] != 'bundle':
        inputs['package_spec'] = package_spec(config)
    else:
        inputs['package_specs'] = {
            name: package_spec(dict(config, component=name, version=config['versions'][name]))
            for name in COMPONENTS}
    if config['component'] in ('meta', 'bundle'):
        names = COMPONENTS if config['component'] == 'bundle' else COMPONENTS[:-1]
        inputs['publications'] = {name: digest(read_current(config, name)[0] / 'manifest.json')
                                  for name in names}
    else:
        module, name = module_for(config)
        inputs['sources'][name] = digest(config['sources'] / name)
        inputs['payload_inputs'] = (module.input_provenance(config, config['component'])
                                    if config['component'] in ('kernel', 'device-trees')
                                    else module.input_provenance(config))
    signature = hashlib.sha256(json.dumps(inputs, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
    return signature, inputs


def write_json(path, value, uid, gid, mode=0o644):
    require(not path.is_symlink(), 'Refusing symlinked JSON destination')
    descriptor, name = tempfile.mkstemp(prefix='.json-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
        os.chmod(name, mode)
        os.chown(name, uid, gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def record_current(config, signature):
    write_json(config['output'] / 'current.json', dict(schema=1,
               component=config['component'], fingerprint=signature,
               publication=str(config['output'] / signature),
               manifest_sha256=digest(config['output'] / signature / 'manifest.json')),
               config['uid'], config['gid'])


def publish_package(config, signature, inputs, payload, metadata, run_dir):
    spec = package_spec(config)
    overrides = metadata.get('package_overrides', {})
    require(set(overrides).issubset({'conffiles', 'scripts'}), 'Invalid package overrides')
    conffiles = overrides.get('conffiles', [])
    if config['component'] == 'kernel':
        conffiles = ['/etc/nv-update-initrd/list.d/modules.override']
    diversions = (('/boot/Image', '/boot/Image.compulab-distrib'),
                  ('/boot/initrd', '/boot/initrd.compulab-distrib')) if config['component'] == 'kernel' else ()
    if config['component'] == 'gstreamer':
        inventory = load(config['sources'] / 'rootfs_package_inventory.py', 'plugin_inventory')
        diversions = tuple(('/usr/lib/aarch64-linux-gnu/gstreamer-1.0/' + name,
                            '/usr/lib/aarch64-linux-gnu/gstreamer-1.0/' + name + '.compulab-distrib')
                           for name in inventory.PLUGINS)
    files, modes = {}, {}
    for path in sorted(payload.rglob('*')):
        require(not path.is_symlink(), 'Symlink in component payload')
        if path.is_file():
            relative = path.relative_to(payload).as_posix()
            files[relative] = digest(regular(path))
            modes[relative] = stat.S_IMODE(path.stat().st_mode)
    require(files, 'Empty component payload')
    prepared = run_dir / 'package'
    prepared.mkdir()
    builder = load(config['sources'] / 'deb_packages.py', 'component_deb_builder')
    archive = builder.build_package(payload, prepared, spec['name'], config['version'],
        architecture=spec['architecture'], depends=spec['depends'], conffiles=conffiles,
        diversions=diversions, scripts=overrides.get('scripts'))
    package = dict(spec, version=config['version'], filename=archive.name, sha256=digest(archive),
                   files=files, file_modes=modes, conffiles=list(conffiles),
                   diversions=list(diversions))
    manifest = dict(schema=1, component=config['component'], fingerprint=signature,
                    inputs=inputs, package=package, payload_metadata=metadata,
                    validation='Archive/metadata checks; no hardware validation')
    write_json(prepared / 'manifest.json', manifest, config['uid'], config['gid'])
    (prepared / 'SHA256SUMS').write_text(package['sha256'] + '  ' + archive.name + '\n' +
                                      digest(prepared / 'manifest.json') + '  manifest.json\n')
    publish_tree(config, prepared, signature)
    return verify_publication(config['output'] / signature, signature, config['uid'], config['component'])


def publish_tree(config, prepared, signature):
    destination = config['output'] / signature
    require(not destination.exists() and not destination.is_symlink(), 'Publication already exists')
    with tempfile.TemporaryDirectory(prefix='.publication-', dir=config['output']) as temporary:
        staging = Path(temporary) / signature
        shutil.copytree(prepared, staging)
        for path in [staging, *staging.iterdir()]:
            os.chown(path, config['uid'], config['gid'])
            path.chmod(0o755 if path.is_dir() else 0o644)
        staging.rename(destination)


def meta_payload(config, run_dir):
    records = {name: read_current(config, name)[1]['package']['version']
               for name in COMPONENTS[:-1]}
    payload = run_dir / 'payload'
    target = payload / 'usr/share/compulab/addons.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(dict(l4t_version='39.2.1', packages={
        package_name(name): value for name, value in records.items()}), indent=2) + '\n')
    target.chmod(0o644)
    return payload, dict(component_versions=records)


def bundle(config, signature, inputs, run_dir):
    prepared = run_dir / 'bundle'
    prepared.mkdir()
    records, occupied, component_manifests = [], set(), {}
    for name in COMPONENTS:
        directory, manifest = read_current(config, name)
        info = manifest['package']
        component_manifests[name] = (directory / 'manifest.json').read_bytes().decode('utf-8')
        require(not occupied.intersection(info['files']), 'Packages contain overlapping payloads')
        occupied.update(info['files'])
        shutil.copyfile(directory / info['filename'], prepared / info['filename'])
        records.append(info)
    manifest = dict(schema=1, fingerprint=signature, inputs=inputs,
                    packages=records, component_manifests=component_manifests,
                    installed=False, hardware_validation=False)
    write_json(prepared / 'manifest.json', manifest, config['uid'], config['gid'])
    (prepared / 'SHA256SUMS').write_text(''.join(
        row['sha256'] + '  ' + row['filename'] + '\n' for row in records) +
        digest(prepared / 'manifest.json') + '  manifest.json\n')
    publish_tree(config, prepared, signature)
    return verify_bundle_publication(config['output'] / signature, signature, config['uid'])


def verify_bundle_publication(directory, signature, uid):
    directory = canonical(directory)
    require(directory.is_dir() and directory.stat().st_uid == uid and
            stat.S_IMODE(directory.stat().st_mode) == 0o755,
            'Invalid coordinated publication owner/mode')
    manifest_file = regular(directory / 'manifest.json')
    manifest = json.loads(manifest_file.read_text())
    require(manifest.get('schema') == 1 and manifest['fingerprint'] == signature and
            manifest['inputs'].get('component') == 'bundle' and
            len(manifest['packages']) == len(COMPONENTS) and
            hashlib.sha256(json.dumps(manifest['inputs'], sort_keys=True,
                separators=(',', ':')).encode()).hexdigest() == signature,
            'Invalid coordinated package manifest')
    versions = manifest['inputs']['versions']
    require(isinstance(versions, dict) and set(versions) == set(COMPONENTS),
            'Incomplete coordinated version map')
    versions = {name: version(value) for name, value in versions.items()}
    specs = manifest['inputs']['package_specs']
    require(isinstance(specs, dict) and set(specs) == set(COMPONENTS),
            'Incomplete coordinated package specification map')
    originals = manifest.get('component_manifests')
    hashes = manifest['inputs'].get('publications')
    require(isinstance(originals, dict) and set(originals) == set(COMPONENTS) and
            isinstance(hashes, dict) and set(hashes) == set(COMPONENTS),
            'Incomplete original component manifest set')
    sums = ''
    expected_files = {'manifest.json', 'SHA256SUMS'}
    remaining = {package_name(component): component for component in COMPONENTS}
    occupied = set()
    for info in manifest['packages']:
        require(isinstance(info, dict) and info.get('name') in remaining,
                'Duplicate or unexpected coordinated package')
        component = remaining.pop(info['name'])
        raw = originals[component]
        require(isinstance(raw, str) and hashlib.sha256(raw.encode('utf-8')).hexdigest() ==
                hashes[component], 'Original component manifest checksum mismatch')
        original = json.loads(raw)
        require(original.get('schema') == 1 and original.get('package') == info and
                original.get('fingerprint') == hashlib.sha256(json.dumps(
                    original['inputs'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                'Coordinated package differs from verified original component manifest')
        require({name: info[name] for name in ('name', 'architecture', 'depends')} ==
                specs[component], 'Coordinated package specification changed')
        actual = verify_archive_info(info, directory, uid, component, versions[component])
        require(not occupied.intersection(actual), 'Packages contain overlapping payloads')
        occupied.update(actual)
        if component == 'meta':
            expected_depends = {
                package_name(name) + (' (>= ' if name == 'uefi-capsules' else ' (= ') +
                versions[name] + ')' for name in COMPONENTS[:-1]}
            require(set(info['depends']) == expected_depends,
                    'Coordinated metapackage dependency versions changed')
        expected_files.add(info['filename'])
        sums += info['sha256'] + '  ' + info['filename'] + '\n'
    require(not remaining, 'Incomplete package set')
    sums += digest(manifest_file) + '  manifest.json\n'
    require(regular(directory / 'SHA256SUMS').read_text() == sums, 'Bundle checksum list drift')
    require({path.name for path in directory.iterdir()} == expected_files,
            'Unexpected coordinated publication files')
    for path in directory.iterdir():
        require(path.stat().st_uid == uid and stat.S_IMODE(path.stat().st_mode) == 0o644,
                'Unexpected coordinated file owner/mode')
    return manifest


def execute(value):
    require(os.geteuid() == 0, '--execute requires explicit root privileges')
    config = checked_configuration(value)
    helper = support(config)
    work = config['work']
    require(work.is_dir() and work.stat().st_uid == config['uid'] and
            stat.S_IMODE(work.stat().st_mode) == 0o700, 'Invalid private component work')
    helper.owned_file(work / '.edge-ai-component-deb-work', config['uid'])
    require((work / '.edge-ai-component-deb-work').read_text() == WORK_ID, 'Invalid work marker')
    with helper.lock_file(work / '.build.lock', config['uid'], config['gid'], create=True):
        output = config['output']
        if not output.exists():
            output.mkdir(parents=True, mode=0o755)
            os.chown(output, config['uid'], config['gid'])
        require(output.is_dir() and output.stat().st_uid == config['uid'], 'Invalid output owner')
        marker = output / '.edge-ai-component-deb-output'
        if not marker.exists():
            require(not any(output.iterdir()), 'Refusing nonempty unmarked output')
            marker.write_text(OUTPUT_ID)
            marker.chmod(0o600)
            os.chown(marker, config['uid'], config['gid'])
        helper.owned_file(marker, config['uid'])
        require(marker.read_text() == OUTPUT_ID, 'Invalid output marker')
        with helper.lock_file(output / '.build.lock', config['uid'], config['gid'], create=True):
            signature, inputs = fingerprint(config)
            destination = output / signature
            if destination.exists() or destination.is_symlink():
                result = (verify_bundle_publication(destination, signature, config['uid'])
                          if config['component'] == 'bundle' else
                          verify_publication(destination, signature, config['uid'], config['component']))
            else:
                run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=work))
                print('Building %s in %s' % (config['component'], run_dir), flush=True)
                if config['component'] == 'bundle':
                    result = bundle(config, signature, inputs, run_dir)
                else:
                    if config['component'] == 'meta':
                        payload, metadata = meta_payload(config, run_dir)
                    else:
                        module, _ = module_for(config)
                        if config['component'] == 'kernel':
                            with helper.lock_file(helper.GLOBAL_SDK_LOCK,
                                                  config['uid'], config['gid'], wait=True):
                                payload, metadata = module.build_kernel(config, run_dir)
                        elif config['component'] == 'device-trees':
                            payload, metadata = module.build_device_trees(config, run_dir)
                        else:
                            payload, metadata = module.build_payload(config, run_dir)
                    require(fingerprint(config)[0] == signature, 'Inputs changed during component build')
                    result = publish_package(config, signature, inputs, payload, metadata, run_dir)
            record_current(config, signature)
            return result


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(arguments)
    try:
        value = json.loads(regular(args.config).read_text())
        if args.execute:
            result = execute(value)
            print('Published:', result['fingerprint'])
        else:
            signature, _ = fingerprint(checked_configuration(value))
            print(json.dumps(dict(action='read-only plan', fingerprint=signature)))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print('Standalone Ubuntu package failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    def interrupted(signum, _frame):
        raise InterruptedError('Component build interrupted: ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    sys.exit(main())

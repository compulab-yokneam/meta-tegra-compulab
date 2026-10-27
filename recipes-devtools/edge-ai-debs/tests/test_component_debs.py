#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real temporary Debian archives; no target execution, sudo or installation."""
from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


DIRECTORY = Path(__file__).resolve().parents[1]
LAYER = DIRECTORY.parents[1]
SDK_FILES = DIRECTORY.parent / 'edge-ai-sdk-manager/files'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load(DIRECTORY / 'files/build-component-deb.py', 'generic_debs_under_test')
BUILDER = load(SDK_FILES / 'sdk-source/compulab/tools/deb_packages.py', 'fixture_deb_builder')
INVENTORY = load(SDK_FILES / 'sdk-source/compulab/tools/rootfs_package_inventory.py', 'fixture_inventory')


def signature(inputs):
    return hashlib.sha256(json.dumps(inputs, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


@unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb is required')
class ComponentDebTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='component-deb-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = self.root / 'sources'
        self.sources.mkdir()
        for name in ('build-component-deb.py', 'build-data-payloads.py'):
            shutil.copyfile(DIRECTORY / 'files' / name, self.sources / name)
        shutil.copyfile(DIRECTORY / 'files/build-argus-deb.py',
                        self.sources / 'build-argus-deb.py')
        for name in ('deb_packages.py', 'rootfs_package_inventory.py', 'package-bsp-policy.py'):
            shutil.copyfile(SDK_FILES / 'sdk-source/compulab/tools' / name, self.sources / name)
        self.bundle = self.sources / 'runtime'
        self.bundle.mkdir()
        self.work = self.root / 'work'
        self.work.mkdir(mode=0o700)
        marker = self.work / '.edge-ai-component-deb-work'
        marker.write_text(MODULE.WORK_ID)
        marker.chmod(0o600)
        self.publications = {name: self.root / 'publications' / name for name in MODULE.COMPONENTS}
        self.versions = {name: '39.2.1+compulab1' for name in MODULE.COMPONENTS}
        self.config = dict(
            schema=1, component='bsp-policy', uid=os.getuid(), gid=os.getgid(),
            work=str(self.work), output=str(self.publications['bsp-policy']),
            sources=str(self.sources), bundle=str(self.bundle), assets={},
            builder=str(self.root / 'builder'), sdk=str(self.root / 'SDK'),
            deploy=str(self.root / 'deploy'), version='39.2.1+compulab1',
            versions=self.versions, publications={key: str(value) for key, value in self.publications.items()},
            imx676_extended='1', imx678_extended='0', jobs=2)
        self.payloads = {}
        self.published = {}

    def config_for(self, component):
        result = dict(self.config, component=component,
                      output=str(self.root / 'publications/bundle' if component == 'bundle'
                                 else self.publications[component]))
        return MODULE.checked_configuration(result)

    def publish_fixture(self, component, *, files=None, architecture=None, depends=None):
        """Publish a real archive and bound receipt without executing its scripts."""
        root = self.publications[component]
        root.mkdir(parents=True, exist_ok=True)
        version = self.versions[component]
        name = MODULE.package_name(component)
        architecture = architecture or MODULE.MODES.get(component, 'all')
        depends = list(INVENTORY.component_dependencies(component, version, self.versions)
                       if depends is None else depends)
        if files is None:
            files = ({'usr/bin/' + name: (b'Argus fixture ' + name.encode(), 0o755)
                      for name in INVENTORY.ARGUS_APPS} if component == 'argus' else
                     {'usr/share/offline-fixture/' + component: (component.encode(), 0o644)})
            if component == 'argus':
                files.update({'usr/share/doc/compulab-edge-ai-argus/' + name: (b'fixture license', 0o644)
                              for name in ('copyright', 'NVIDIA-LICENSE')})
        payload = self.root / ('payload-' + component)
        payload.mkdir()
        for relative, (data, mode) in files.items():
            path = payload / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
        spec = dict(name=name, architecture=architecture, depends=depends)
        inputs = dict(schema=1, component=component, version=version,
                      versions=self.versions, package_spec=spec)
        if component == 'argus':
            inputs.update(applications=list(INVENTORY.ARGUS_APPS), depends=depends)
        fingerprint = signature(inputs)
        directory = root / fingerprint
        directory.mkdir()
        directory.chmod(0o755)
        archive = BUILDER.build_package(payload, directory, name, version,
                                        architecture=architecture, depends=depends)
        info = dict(spec, version=version, filename=archive.name, sha256=MODULE.digest(archive),
                    files={relative: hashlib.sha256(data).hexdigest() for relative, (data, _) in files.items()},
                    file_modes={relative: mode for relative, (_, mode) in files.items()}, conffiles=[])
        if component == 'argus':
            info['binary_count'] = 23
        manifest = dict(schema=1, component=component, fingerprint=fingerprint,
                        inputs=inputs, package=info)
        (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (directory / 'SHA256SUMS').write_text(info['sha256'] + '  ' + archive.name + '\n' +
                                           MODULE.digest(directory / 'manifest.json') + '  manifest.json\n')
        for path in directory.iterdir():
            path.chmod(0o644)
        MODULE.record_current(dict(self.config, output=root, component=component), fingerprint)
        self.payloads[component] = payload
        self.published[component] = (directory, manifest)
        return directory, manifest

    def all_fixtures(self):
        for component in MODULE.COMPONENTS:
            self.publish_fixture(component)

    def execute(self, config):
        # Files and locks already belong to the ordinary test user. Only the
        # top-level authorization gate is mocked; no privileged action runs.
        with mock.patch.object(MODULE.os, 'geteuid', return_value=0):
            return MODULE.execute(config)

    def rewrite_bundle(self, directory, manifest):
        (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (directory / 'SHA256SUMS').write_text(''.join(
            info['sha256'] + '  ' + info['filename'] + '\n' for info in manifest['packages']) +
            MODULE.digest(directory / 'manifest.json') + '  manifest.json\n')

    def bundled(self):
        self.all_fixtures()
        result = self.execute(self.config_for('bundle'))
        return self.root / 'publications/bundle' / result['fingerprint'], result

    def test_configuration_rejects_root_relative_overlap_and_symlink_paths(self):
        for key in ('work', 'output', 'sources', 'bundle', 'builder', 'sdk', 'deploy'):
            for value in ('/', 'relative/path'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    MODULE.checked_configuration(dict(self.config, **{key: value}))
        with self.assertRaises(ValueError):
            MODULE.checked_configuration(dict(self.config, work=str(self.sources / 'work')))
        alias = self.root / 'alias'
        alias.symlink_to(self.sources, target_is_directory=True)
        with self.assertRaises(ValueError):
            MODULE.checked_configuration(dict(self.config, sources=str(alias)))

    def test_configuration_requires_complete_version_and_publication_maps(self):
        for key in ('versions', 'publications'):
            invalid = dict(self.config[key])
            del invalid['kernel']
            with self.subTest(key=key), self.assertRaises(ValueError):
                MODULE.checked_configuration(dict(self.config, **{key: invalid}))

    def test_configuration_rejects_invalid_schema_owner_jobs_and_versions(self):
        for key, value in (('schema', True), ('uid', 0), ('gid', -1), ('jobs', True),
                           ('jobs', 0), ('jobs', 65), ('version', '1.0'), ('version', '39.2.1-')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                MODULE.checked_configuration(dict(self.config, **{key: value}))

    def test_default_plan_is_readonly_and_never_executes(self):
        path = self.root / 'configuration.json'
        path.write_text(json.dumps(self.config))
        output = io.StringIO()
        with mock.patch.object(MODULE, 'execute', side_effect=AssertionError('unexpected execute')), \
                redirect_stdout(output):
            self.assertEqual(MODULE.main(['--config', str(path)]), 0)
        self.assertEqual(json.loads(output.getvalue())['action'], 'read-only plan')
        self.assertFalse(self.publications['bsp-policy'].exists())
        self.assertFalse((self.work / '.build.lock').exists())

    def test_bsp_policy_uses_data_dispatch_only_and_publishes_real_archive(self):
        config = self.config_for('bsp-policy')
        module, filename = MODULE.module_for(config)
        self.assertEqual(filename, 'build-data-payloads.py')
        self.assertTrue(callable(module.build_payload))
        result = self.execute(config)
        directory = Path(config['output']) / result['fingerprint']
        checked = MODULE.verify_publication(directory, result['fingerprint'], os.getuid(), 'bsp-policy')
        self.assertEqual(checked, result)
        self.assertEqual(len(result['package']['files']), 3)
        self.assertEqual(result['inputs']['package_spec']['depends'], ['python3', 'dpkg'])
        self.assertFalse(any(path.startswith('var/lib/') for path in result['package']['files']))
        current, manifest = MODULE.read_current(config, 'bsp-policy')
        self.assertEqual((current, manifest), (directory, result))

    def test_unchanged_component_reuses_cache_without_rebuilding_payload(self):
        config = self.config_for('bsp-policy')
        first = self.execute(config)
        with mock.patch.object(MODULE, 'module_for', wraps=MODULE.module_for) as dispatch:
            second = self.execute(config)
        self.assertEqual(first, second)
        self.assertEqual(dispatch.call_count, 1)  # fingerprint only; no build dispatch

    def test_current_receipt_rejects_changed_manifest_hash(self):
        directory, _ = self.publish_fixture('bsp-policy')
        manifest = directory / 'manifest.json'
        manifest.write_text(manifest.read_text() + '\n')
        with self.assertRaises(ValueError):
            MODULE.read_current(self.config_for('meta'), 'bsp-policy')

    def test_current_receipt_rejects_wrong_coordinated_version(self):
        self.publish_fixture('bsp-policy')
        config = self.config_for('meta')
        config['versions'] = dict(config['versions'], **{'bsp-policy': '39.2.1+compulab2'})
        with self.assertRaisesRegex(ValueError, 'version'):
            MODULE.read_current(config, 'bsp-policy')

    def test_current_receipt_rejects_foreign_publication_path(self):
        self.publish_fixture('bsp-policy')
        pointer = self.publications['bsp-policy'] / 'current.json'
        current = json.loads(pointer.read_text())
        current['publication'] = str(self.root)
        pointer.write_text(json.dumps(current))
        with self.assertRaises(ValueError):
            MODULE.read_current(self.config_for('meta'), 'bsp-policy')

    def test_component_cache_rejects_control_metadata_not_bound_to_original_inputs(self):
        directory, manifest = self.publish_fixture('bsp-policy')
        manifest['package']['depends'] = []
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'specification'):
            MODULE.verify_publication(directory, manifest['fingerprint'], os.getuid(), 'bsp-policy')

    def test_component_cache_binds_version_to_fingerprinted_inputs(self):
        directory, manifest = self.publish_fixture('bsp-policy')
        manifest['package']['version'] = '39.2.1+compulab2'
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            MODULE.verify_publication(directory, manifest['fingerprint'], os.getuid(), 'bsp-policy')

    def test_meta_payload_uses_actual_verified_component_versions(self):
        for name in MODULE.COMPONENTS[:-1]:
            self.publish_fixture(name)
        run = self.root / 'meta-run'
        run.mkdir()
        payload, metadata = MODULE.meta_payload(self.config_for('meta'), run)
        summary = json.loads((payload / 'usr/share/compulab/addons.json').read_text())
        self.assertEqual(summary['packages'], {MODULE.package_name(name): self.versions[name]
                                              for name in MODULE.COMPONENTS[:-1]})
        self.assertEqual(len(metadata['component_versions']), 8)

    def test_aggregate_contains_all9_archives_and_rechecks_every_archive(self):
        directory, manifest = self.bundled()
        self.assertEqual(len(manifest['packages']), 9)
        self.assertFalse(manifest['installed'])
        self.assertFalse(manifest['hardware_validation'])
        self.assertEqual(MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid()), manifest)

    def test_aggregate_cache_rejects_unexpected_files(self):
        directory, manifest = self.bundled()
        (directory / 'unexpected').write_text('not in publication\n')
        with self.assertRaises(ValueError):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_cache_rejects_escaping_archive_filename(self):
        directory, manifest = self.bundled()
        manifest['packages'][0]['filename'] = str(self.root / 'outside.deb')
        self.rewrite_bundle(directory, manifest)
        with self.assertRaises(ValueError):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_cache_rejects_duplicate_package_identity(self):
        directory, manifest = self.bundled()
        manifest['packages'][-1] = copy.deepcopy(manifest['packages'][0])
        self.rewrite_bundle(directory, manifest)
        with self.assertRaises(ValueError):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_cache_rejects_different_declared_component_version(self):
        directory, manifest = self.bundled()
        manifest['packages'][1]['version'] = '39.2.1+compulab2'
        self.rewrite_bundle(directory, manifest)
        with self.assertRaises(ValueError):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def rebuild_bundle_archive(self, directory, manifest, component, *,
                               payload=None, architecture=None, depends=None):
        info = next(row for row in manifest['packages']
                    if row['name'] == MODULE.package_name(component))
        payload = payload or self.payloads[component]
        prepared = self.root / 'replacement-archive'
        prepared.mkdir()
        archive = BUILDER.build_package(
            payload, prepared, info['name'], info['version'],
            architecture=architecture or info['architecture'],
            depends=info['depends'] if depends is None else depends)
        shutil.copyfile(archive, directory / info['filename'])
        info['sha256'] = MODULE.digest(archive)
        self.rewrite_bundle(directory, manifest)
        return info

    def test_aggregate_rejects_actual_foreign_architecture_with_recomputed_checksums(self):
        directory, manifest = self.bundled()
        info = self.rebuild_bundle_archive(directory, manifest, 'kernel', architecture='amd64')
        with self.assertRaisesRegex(ValueError, 'control field'):
            MODULE.verify_archive_info(info, directory, os.getuid(), 'kernel', self.versions['kernel'])
        with self.assertRaisesRegex(ValueError, 'original component manifest'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_rejects_actual_changed_dependencies_with_recomputed_checksums(self):
        directory, manifest = self.bundled()
        info = self.rebuild_bundle_archive(directory, manifest, 'kernel', depends=['python3'])
        with self.assertRaisesRegex(ValueError, 'control field'):
            MODULE.verify_archive_info(info, directory, os.getuid(), 'kernel', self.versions['kernel'])
        with self.assertRaisesRegex(ValueError, 'original component manifest'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_rejects_overlapping_real_package_payloads(self):
        directory, manifest = self.bundled()
        payload = self.root / 'overlapping-payload'
        shutil.copytree(self.payloads['kernel'], payload)
        info = self.rebuild_bundle_archive(directory, manifest, 'device-trees', payload=payload)
        files = {path.relative_to(payload).as_posix(): path for path in payload.rglob('*') if path.is_file()}
        info['files'] = {name: MODULE.digest(path) for name, path in files.items()}
        info['file_modes'] = {name: path.stat().st_mode & 0o777 for name, path in files.items()}
        self.rewrite_bundle(directory, manifest)
        with self.assertRaisesRegex(ValueError, 'original component manifest'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_rejects_corrupt_debian_md5_control_even_when_sha256_matches(self):
        directory, manifest = self.bundled()
        info = next(row for row in manifest['packages']
                    if row['name'] == 'compulab-edge-ai-bsp-policy')
        unpacked = self.root / 'repacked'
        subprocess.run(['dpkg-deb', '-R', str(directory / info['filename']), str(unpacked)],
                       check=True, stdout=subprocess.DEVNULL)
        md5 = unpacked / 'DEBIAN/md5sums'
        checksum, name = md5.read_text().split('  ', 1)
        md5.write_text(('0' * 32 if checksum != '0' * 32 else '1' * 32) + '  ' + name)
        replacement = self.root / 'bad-md5.deb'
        subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(unpacked), str(replacement)],
                       check=True, stdout=subprocess.DEVNULL)
        shutil.copyfile(replacement, directory / info['filename'])
        info['sha256'] = MODULE.digest(replacement)
        self.rewrite_bundle(directory, manifest)
        with self.assertRaisesRegex(ValueError, 'md5'):
            MODULE.verify_archive_info(info, directory, os.getuid(), 'bsp-policy', self.versions['bsp-policy'])
        with self.assertRaisesRegex(ValueError, 'original component manifest'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_rejects_unsafe_published_archive_mode(self):
        directory, manifest = self.bundled()
        (directory / manifest['packages'][0]['filename']).chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'mode'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_aggregate_rejects_rewritten_metapackage_dependency_versions(self):
        directory, manifest = self.bundled()
        info = next(row for row in manifest['packages'] if row['name'] == 'compulab-edge-ai')
        info['depends'][0] = info['depends'][0].replace('compulab1', 'compulab999')
        self.rewrite_bundle(directory, manifest)
        with self.assertRaisesRegex(ValueError, 'original component manifest'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_collection_rejects_individually_valid_but_overlapping_component_payloads(self):
        shared = {'usr/share/collision': (b'colliding payload', 0o644)}
        for component in MODULE.COMPONENTS:
            self.publish_fixture(component, files=shared if component in ('kernel', 'device-trees') else None)
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            self.execute(self.config_for('bundle'))

    def test_cached_argus_archive_cannot_drop_an_app_and_rewrite_its_own_checksums(self):
        directory, manifest = self.bundled()
        payload = self.root / 'truncated-argus'
        shutil.copytree(self.payloads['argus'], payload)
        (payload / 'usr/bin/argus_camera').unlink()
        info = self.rebuild_bundle_archive(directory, manifest, 'argus', payload=payload)
        files = {path.relative_to(payload).as_posix(): path for path in payload.rglob('*') if path.is_file()}
        info['files'] = {name: MODULE.digest(path) for name, path in files.items()}
        info['file_modes'] = {name: path.stat().st_mode & 0o777 for name, path in files.items()}
        self.rewrite_bundle(directory, manifest)
        with self.assertRaisesRegex(ValueError, 'original component manifest'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())

    def test_cached_embedded_original_manifest_cannot_be_rewritten(self):
        directory, manifest = self.bundled()
        manifest['component_manifests']['argus'] += '\n'
        self.rewrite_bundle(directory, manifest)
        with self.assertRaisesRegex(ValueError, 'manifest checksum'):
            MODULE.verify_bundle_publication(directory, manifest['fingerprint'], os.getuid())


class ComponentRecipeTests(unittest.TestCase):
    def test_all9_package_targets_and_aggregate_have_no_sdk_creation_dependency(self):
        recipes = list(DIRECTORY.glob('*.bb'))
        self.assertEqual(len(recipes), 10)  # nine package targets plus aggregate
        for path in recipes:
            text = path.read_text()
            self.assertNotIn('edge-ai-sdk-manager:do_', text)
            self.assertNotIn('do_create_sdk', text)
            if path.name.startswith('edge-ai-argus-deb_'):
                self.assertIn('inherit nopackages', text)
                self.assertIn('do_create_argus_deb[nostamp] = "1"', text)
            else:
                self.assertIn('require edge-ai-deb.inc', text)
        common = (DIRECTORY / 'edge-ai-deb.inc').read_text()
        self.assertNotIn('require edge-ai-sdk-manager-runtime', common)
        classfile = (LAYER / 'classes/edge-ai-ubuntu-deb.bbclass').read_text()
        self.assertIn('do_create_deb[nostamp] = "1"', classfile)
        self.assertIn('inherit nopackages', classfile)

    def test_only_native_component_and_coordinator_recipes_have_required_component_edges(self):
        meta = (DIRECTORY / 'edge-ai-meta-deb_39.2.1.bb').read_text()
        for name in ('gstreamer', 'kernel', 'device-trees', 'uefi-capsules',
                     'boot-tools', 'camera-support', 'bsp-policy'):
            self.assertIn('edge-ai-' + name + '-deb:do_create_deb', meta)
        self.assertIn('edge-ai-argus-deb:do_create_argus_deb', meta)
        bundle = (DIRECTORY / 'edge-ai-debs_39.2.1.bb').read_text()
        self.assertIn('edge-ai-meta-deb:do_create_deb', bundle)
        for name in ('camera-support', 'bsp-policy', 'boot-tools'):
            text = (DIRECTORY / ('edge-ai-' + name + '-deb_39.2.1.bb')).read_text()
            self.assertNotIn('virtual/kernel:', text)
            self.assertNotIn('tegra-uefi-capsules:', text)


if __name__ == '__main__':
    unittest.main()

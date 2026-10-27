#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise real inline BitBake task preflights without BitBake or sudo.

Every filesystem operation is confined to temporary fixtures. Fake fetchers
read only fixture bytes; the global SDK lock is redirected to a fixture, and
the privileged subprocess boundary is never entered.
"""
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock


DIRECTORY = Path(__file__).resolve().parents[1]
LAYER = DIRECTORY.parents[1]
TASKS = {
    'component': (LAYER / 'classes/edge-ai-ubuntu-deb.bbclass', 'do_create_deb'),
    'argus': (DIRECTORY / 'edge-ai-argus-deb_39.2.1.bb',
              'do_create_argus_deb'),
}


class TaskFatal(RuntimeError):
    pass


class PrivilegedBoundary(RuntimeError):
    pass


def snapshot(root):
    records = {}
    for path in [root, *root.rglob('*')]:
        key = path.relative_to(root).as_posix()
        if path.is_symlink():
            records[key] = ('symlink', str(path.readlink()))
        elif path.is_file():
            records[key] = ('file', path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        else:
            records[key] = ('directory', stat.S_IMODE(path.stat().st_mode))
    return records


class Data:
    def __init__(self, values):
        self.values = values

    def getVar(self, name):
        return self.values.get(name)


class TaskHarness(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='bitbake-deb-paths-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sdk_output = self.root / 'sdk-output'
        self.sdk = self.sdk_output / 'Linux_for_Tegra'
        self.builder = self.root / 'prepared-builder'
        self.sources = self.root / 'unpacked-sources'
        self.deploy = self.root / 'deploy'
        for path in (self.sdk, self.builder, self.sources, self.deploy):
            path.mkdir(parents=True, mode=0o755)
            path.chmod(0o755)
            (path / 'sentinel').write_text('Unrelated fixture bytes must remain intact.\n')
        self.work = self.root / 'private-work'
        self.deploy_root = self.deploy / 'edge-ai-debs'
        self.output = (self.deploy_root / 'bsp-policy' if self.kind == 'component'
                       else self.deploy / 'argus-parent/argus-publication')
        self.source_deb = self.root / 'source-fixture.deb'
        self.source_deb.write_bytes(b'Not an executable or real MMAPI archive.\n')
        self.lock = self.root / 'sdk-coordination.lock'
        self.values = {
            'EDGE_AI_DEB_ENABLE': '1', 'EDGE_AI_DEB_COMPONENT': 'bsp-policy',
            'EDGE_AI_DEB_HOST_WORK': str(self.work), 'EDGE_AI_DEB_OUTPUT': str(self.output),
            'EDGE_AI_DEB_DEPLOY_ROOT': str(self.deploy_root),
            'EDGE_AI_DEB_ARGUS_OUTPUT': str(self.deploy / 'separate-argus-publication'),
            'EDGE_AI_DEB_BUILDER': str(self.builder), 'EDGE_AI_DEB_SDK': str(self.sdk),
            'EDGE_AI_DEB_VERSION': '39.2.1+compulab1', 'EDGE_AI_DEB_JOBS': '2',
            'EDGE_AI_DEB_ASSET_URIS': '{}',
            'EDGE_AI_ARGUS_DEB_ENABLE': '1', 'EDGE_AI_ARGUS_DEB_HOST_WORK': str(self.work),
            'EDGE_AI_ARGUS_DEB_OUTPUT': str(self.output),
            'EDGE_AI_ARGUS_DEB_BUILDER': str(self.builder),
            'EDGE_AI_ARGUS_DEB_SDK': str(self.sdk),
            'EDGE_AI_ARGUS_DEB_VERSION': '39.2.1+compulab1',
            'EDGE_AI_ARGUS_DEB_JOBS': '2',
            'EDGE_AI_ARGUS_DEB_MMAPI_URI': 'file://offline-fixture.deb;unpack=0',
            'EDGE_AI_SDK_OUTPUT': str(self.sdk_output),
            'EDGE_AI_SDK_HOST_WORK': str(self.root / 'sdk-private-work'),
            'UNPACKDIR': str(self.sources), 'DEPLOY_DIR_IMAGE': str(self.deploy),
            'EDGE_AI_IMX676_EXTENDED_MODES': '1', 'EDGE_AI_IMX678_EXTENDED_MODES': '0',
            'EDGE_AI_UEFI_LEGACY_FMP_GUIDS': '',
        }
        self.fake_bb = types.ModuleType('bb')
        self.fake_fetch = types.ModuleType('bb.fetch')
        self.fake_fetch2 = types.ModuleType('bb.fetch2')
        self.fake_bb.fetch = self.fake_fetch
        self.fake_bb.fetch2 = self.fake_fetch2

        def fatal(message):
            raise TaskFatal(message)
        self.fake_bb.fatal = fatal
        fixture_deb = self.source_deb

        class Fetch:
            def __init__(self, uris, data):
                self.uris = uris

            def localpath(self, uri):
                return str(fixture_deb)
        self.fake_fetch.Fetch = self.fake_fetch2.Fetch = Fetch
        filename, name = TASKS[self.kind]
        body = re.search(r'(?ms)^python ' + name + r'\(\) \{\n(.*?)^\}',
                         filename.read_text())[1]
        namespace = {'bb': self.fake_bb}
        exec('def task(d):\n' + body, namespace)
        self.task = namespace['task']
        self.work_variable = ('EDGE_AI_DEB_HOST_WORK' if self.kind == 'component'
                              else 'EDGE_AI_ARGUS_DEB_HOST_WORK')

    def modules(self):
        return mock.patch.dict(sys.modules, {'bb': self.fake_bb,
                                            'bb.fetch': self.fake_fetch,
                                            'bb.fetch2': self.fake_fetch2})

    def assert_rejected_without_mutation(self, private):
        self.values[self.work_variable] = str(private)
        before = snapshot(self.root)
        with self.modules(), mock.patch('os.open', side_effect=AssertionError('Lock reached before preflight')), \
                mock.patch('subprocess.run', side_effect=AssertionError('Privileged subprocess reached')), \
                self.assertRaises(TaskFatal):
            self.task(Data(self.values))
        self.assertEqual(snapshot(self.root), before)


class PathCases:
    def test_work_equal_sdk_is_rejected_before_chmod_or_marker_writes(self):
        self.assert_rejected_without_mutation(self.sdk)

    def test_empty_sdk_input_cannot_be_adopted_as_private_work(self):
        (self.sdk / 'sentinel').unlink()
        self.assert_rejected_without_mutation(self.sdk)

    def test_work_inside_sdk_is_rejected_before_directory_creation(self):
        self.assert_rejected_without_mutation(self.sdk / 'new-private-work')

    def test_work_equal_builder_is_rejected_before_any_mutation(self):
        self.assert_rejected_without_mutation(self.builder)

    def test_empty_builder_input_cannot_be_adopted_as_private_work(self):
        (self.builder / 'sentinel').unlink()
        self.assert_rejected_without_mutation(self.builder)

    def test_work_equal_unpacked_sources_is_rejected_before_any_mutation(self):
        self.assert_rejected_without_mutation(self.sources)

    def test_empty_unpacked_sources_cannot_be_adopted_as_private_work(self):
        (self.sources / 'sentinel').unlink()
        self.assert_rejected_without_mutation(self.sources)

    def test_work_equal_output_is_rejected_before_any_mutation(self):
        self.output.mkdir(parents=True, mode=0o755)
        self.output.chmod(0o755)
        (self.output / 'sentinel').write_text('Existing publication fixture\n')
        self.assert_rejected_without_mutation(self.output)

    def test_empty_output_cannot_also_be_adopted_as_private_work(self):
        self.output.mkdir(parents=True, mode=0o755)
        self.assert_rejected_without_mutation(self.output)

    def test_symlink_alias_is_rejected_before_following_or_changing_target(self):
        alias = self.root / 'sdk-alias'
        alias.symlink_to(self.sdk, target_is_directory=True)
        self.assert_rejected_without_mutation(alias)

    def test_unmarked_nonempty_private_work_keeps_its_original_mode_and_files(self):
        self.work.mkdir(mode=0o755)
        self.work.chmod(0o755)
        (self.work / 'unrelated').write_text('Not owned by this task\n')
        self.assert_rejected_without_mutation(self.work)

    def test_valid_output_parent_is_created_by_ordinary_user_before_sudo(self):
        real_open = os.open

        def confined_open(path, *args, **kwargs):
            if str(path) == '/tmp/edge-ai-sdkmanager.lock':
                return real_open(self.lock, *args, **kwargs)
            if isinstance(path, (str, bytes, Path)):
                target = Path(os.fsdecode(path))
                self.assertTrue(target.is_relative_to(self.root), str(target))
            return real_open(path, *args, **kwargs)

        def stop_before_privileged_call(command, **kwargs):
            self.assertEqual(command[:2], ['sudo', '-n'])
            self.assertIn('--execute', command)
            raise PrivilegedBoundary('Stopped before any privileged subprocess')

        with self.modules(), mock.patch('os.open', side_effect=confined_open), \
                mock.patch('subprocess.run', side_effect=stop_before_privileged_call), \
                self.assertRaises(PrivilegedBoundary):
            self.task(Data(self.values))
        self.assertTrue(self.output.parent.is_dir())
        self.assertEqual(self.output.parent.stat().st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(self.output.parent.stat().st_mode), 0o755)


@unittest.skipIf(os.getuid() == 0, 'These fixtures exercise an ordinary build user')
class ComponentTaskPaths(PathCases, TaskHarness):
    kind = 'component'


@unittest.skipIf(os.getuid() == 0, 'These fixtures exercise an ordinary build user')
class ArgusTaskPaths(PathCases, TaskHarness):
    kind = 'argus'


if __name__ == '__main__':
    unittest.main()

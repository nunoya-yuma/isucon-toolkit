"""Run with python3 -m unittest discover -s tests -v from contest-ops."""
import getpass
import grp
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OperationsTest(unittest.TestCase):
    def local_inventory(self, root):
        inventory = root / 'hosts.json'
        inventory.write_text(json.dumps({'all': {'children': {'app': {'hosts': {
            'localtest': {'ansible_connection': 'local',
                          'ansible_remote_tmp': str(root / 'ansible-tmp'),
                          'ansible_python_interpreter': '/usr/bin/python3'}
        }}}}}))
        return inventory

    def run_ops(self, action, inventory, config, *extra, success=True):
        result = subprocess.run(
            [str(ROOT / 'run.sh'), action, '-i', str(inventory), '-c', str(config), *extra],
            cwd='/tmp', capture_output=True, text=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_ssh_examples_validate_without_network(self):
        for name in ['single', 'three']:
            with self.subTest(name=name):
                self.run_ops('validate', ROOT / 'inventory' / (name + '.example.yml'),
                             ROOT / 'config/isucon14.example.yml')

    def test_explicit_configuration_and_command(self):
        with tempfile.TemporaryDirectory(prefix='contest-config-test-') as directory:
            root = Path(directory)
            template = root / 'settings.j2'
            template.write_text('database={{ contest_database_host }}\n')
            target = root / 'settings.conf'
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'all': {'children': {'app': {'hosts': {
                'localtest': {'ansible_connection': 'local',
                              'ansible_remote_tmp': str(root / 'ansible-tmp'),
                              'ansible_python_interpreter': '/usr/bin/python3'}
            }}}}}))
            config = root / 'config.json'
            config.write_text(json.dumps({
                'ops_source_dir': str(root), 'ops_release_root': str(root / 'releases'),
                'ops_become': False, 'ops_require_ssh': False, 'ops_manage_service': False,
                'contest_database_host': '192.168.0.13',
                'ops_config_files': [{
                    'src': str(template), 'dest': str(target),
                    'owner': getpass.getuser(), 'group': grp.getgrgid(os.getgid()).gr_name,
                }],
                'ops_config_commands': [{'argv': ['/usr/bin/python3', '-c',
                    'from pathlib import Path; assert Path(' + repr(str(target)) +
                    ').read_text() == "database=192.168.0.13\\n"'], 'changed': False}],
            }))
            self.run_ops('configure', inventory, config)
            self.assertEqual(target.read_text(), 'database=192.168.0.13\n')
            self.run_ops('verify', inventory, config)

    def test_rejects_protected_service(self):
        self.run_ops('validate', ROOT / 'inventory/single.example.yml',
                     ROOT / 'config/isucon14.example.yml',
                     '-e', 'ops_service_name=envcheck', success=False)

    def test_initial_snapshot_and_inspection(self):
        with tempfile.TemporaryDirectory(prefix='contest-initial-test-') as directory:
            root = Path(directory)
            source = root / 'original sources'
            source.mkdir()
            (source / 'app.go').write_text('original')
            (source / 'excluded').write_text('not archived')
            inventory = self.local_inventory(root)
            config = root / 'initial.json'
            values = {
                'ops_become': False, 'ops_require_ssh': False,
                'ops_artifact_root': str(root / 'artifacts'),
                'ops_snapshot_paths': [str(source)],
                'ops_snapshot_excludes': ['excluded'],
                'ops_inspect_commands': [
                    {'name': 'successful', 'argv': ['/usr/bin/printf', 'baseline']},
                    {'name': 'missing', 'argv': ['/nonexistent/optional-command']},
                ],
            }
            config.write_text(json.dumps(values))
            self.run_ops('snapshot', inventory, config)
            archives = list((root / 'artifacts').glob('*/localtest/original.tar.gz'))
            self.assertEqual(len(archives), 1)
            self.assertEqual(archives[0].stat().st_mode & 0o777, 0o600)
            with tarfile.open(archives[0]) as archive:
                self.assertEqual(archive.extractfile(str(source / 'app.go').lstrip('/')).read(), b'original')
                self.assertFalse(any(name.endswith('/excluded') for name in archive.getnames()))
            self.assertEqual((source / 'app.go').read_text(), 'original')

            self.run_ops('snapshot', inventory, config)
            self.assertEqual(len(list((root / 'artifacts').glob('*/localtest/original.tar.gz'))), 2)
            self.run_ops('inspect', inventory, config)
            report = next((root / 'artifacts').glob('*/localtest/baseline.json'))
            data = json.loads(report.read_text())
            self.assertEqual(data['host'], 'localtest')
            self.assertEqual(data['commands'][0]['stdout'], 'baseline')
            self.assertNotEqual(data['commands'][1]['rc'], 0)
            self.assertNotIn('env', data)
            self.assertEqual(report.stat().st_mode & 0o777, 0o600)

            values['ops_snapshot_paths'] = [str(root / 'missing')]
            config.write_text(json.dumps(values))
            self.run_ops('snapshot', inventory, config, success=False)

    def test_bootstrap_is_opt_in(self):
        with tempfile.TemporaryDirectory(prefix='contest-bootstrap-test-') as directory:
            root = Path(directory)
            inventory = self.local_inventory(root)
            config = root / 'initial.json'
            config.write_text(json.dumps({'ops_become': False, 'ops_require_ssh': False}))
            result = self.run_ops('bootstrap', inventory, config)
            self.assertIn('changed=0', result.stdout)

    def test_release_build_failure_and_rollback(self):
        with tempfile.TemporaryDirectory(prefix='contest-ops-test-') as directory:
            root = Path(directory)
            source = root / 'source with spaces'
            source.mkdir()
            (source / 'payload').write_text('first')
            (source / 'removed-later').write_text('old source')
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'all': {'children': {'app': {'hosts': {
                'localtest': {'ansible_connection': 'local',
                              'ansible_remote_tmp': str(root / 'ansible-tmp'),
                              'ansible_python_interpreter': '/usr/bin/python3'}
            }}}}}))
            config = root / 'config.json'
            settings = {
                'ops_source_dir': str(source), 'ops_release_root': str(root / 'releases'),
                'ops_owner': getpass.getuser(), 'ops_group': grp.getgrgid(os.getgid()).gr_name,
                'ops_become': False, 'ops_require_ssh': False, 'ops_manage_service': False,
                'ops_build_commands': [{'argv': ['/usr/bin/python3', '-c',
                    'from pathlib import Path; Path("artifact").write_text(Path("payload").read_text())']}],
            }
            config.write_text(json.dumps(settings))
            self.run_ops('deploy', inventory, config)
            current = root / 'releases/current'
            first = current.resolve()
            self.assertEqual((current / 'artifact').read_text(), 'first')

            (source / 'payload').write_text('second')
            (source / 'removed-later').unlink()
            self.run_ops('deploy', inventory, config)
            second = current.resolve()
            self.assertNotEqual(first, second)
            self.assertEqual((current / 'artifact').read_text(), 'second')
            self.assertFalse((current / 'removed-later').exists())

            settings['ops_build_commands'] = [{'argv': ['/usr/bin/false']}]
            config.write_text(json.dumps(settings))
            self.run_ops('deploy', inventory, config, success=False)
            self.assertEqual(current.resolve(), second)

            settings['ops_build_commands'] = []
            config.write_text(json.dumps(settings))
            self.run_ops('rollback', inventory, config)
            self.assertEqual(current.resolve(), first)
            self.assertEqual((current / 'artifact').read_text(), 'first')
            self.assertEqual((root / 'releases/previous').resolve(), second)


if __name__ == '__main__':
    unittest.main()

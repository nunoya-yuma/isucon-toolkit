import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('nginx_tune', ROOT / 'scripts/nginx_tune.py')
tuning = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tuning)

ORIGINAL = '''# retain this comment
worker_processes auto;
events { worker_connections 1024; }
http {
    sendfile off; # retain trailing comment
    include conf.d/*.conf;
    server {
        ssl_protocols TLSv1.3;
        location /api/ { proxy_pass http://app; }
        location /api/internal/ { allow 127.0.0.1; deny all; }
        location / { return 200 "literal } ; # ${variable}"; }
    }
}
'''


class RenderTest(unittest.TestCase):
    def test_scopes_and_untouched_content(self):
        settings = {'main': {'worker_rlimit_nofile': '65536'},
                    'events': {'worker_connections': '4096'},
                    'http': {'sendfile': 'on', 'keepalive_requests': '10000'}}
        result = tuning.render(ORIGINAL, settings)
        self.assertIn('worker_connections 4096;', result)
        self.assertIn('sendfile on; # retain trailing comment', result)
        self.assertIn('worker_rlimit_nofile 65536;', result)
        self.assertIn('include conf.d/*.conf;', result)
        self.assertIn('ssl_protocols TLSv1.3;', result)
        self.assertIn('allow 127.0.0.1; deny all;', result)
        self.assertIn('"literal } ; # ${variable}"', result)
        self.assertEqual(tuning.render(result, settings), result)

    def test_rejects_unsupported_ambiguous_or_injected_settings(self):
        for text, settings in [
            (ORIGINAL, {'http': {'http2_max_requests': '10000'}}),
            (ORIGINAL, {'http': {'sendfile': 'on; server_tokens off'}}),
            (ORIGINAL, {'http': {'sendfile': True}}),
            ('events {}', {'http': {'sendfile': 'on'}}),
            ('http { sendfile on; sendfile off; }', {'http': {'sendfile': 'on'}}),
        ]:
            with self.subTest(text=text, settings=settings):
                with self.assertRaises(ValueError):
                    tuning.render(text, settings)


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='nginx-tune-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.main = self.root / 'nginx.conf'
        self.main.write_text(ORIGINAL)
        self.main.chmod(0o640)
        self.mock = self.root / 'commands.py'
        self.mock.write_text('''import json
from pathlib import Path
import sys
mode, directory, *args = sys.argv[1:]
root = Path(directory)
with (root / 'calls').open('a') as out:
    out.write(json.dumps([mode, args]) + '\\n')
if mode == 'nginx':
    source = Path(args[args.index('-c') + 1]).read_text()
    if 'BAD' in source:
        print('invalid config', file=sys.stderr)
        sys.exit(1)
    print(source if '-T' in args else 'syntax ok')
elif mode == 'reload':
    count_file = root / 'reloads'
    count = int(count_file.read_text()) + 1 if count_file.exists() else 1
    count_file.write_text(str(count))
    if (root / 'fail-always').exists() or ((root / 'fail-once').exists() and count == 1):
        sys.exit(1)
elif mode == 'health' and (root / 'fail-health').exists():
    sys.exit(1)
''')

    def settings(self, identifier):
        return {'config_path': str(self.main), 'backup_root': str(self.root / 'backups'),
                'run_id': identifier, 'directives': {'http': {'sendfile': 'on'}},
                'nginx_argv': ['/usr/bin/python3', str(self.mock), 'nginx', str(self.root)],
                'reload_argv': ['/usr/bin/python3', str(self.mock), 'reload', str(self.root)],
                'health_argv': ['/usr/bin/python3', str(self.mock), 'health', str(self.root)]}

    def test_plan_apply_noop_and_restore(self):
        plan = tuning.execute('plan', self.settings('plan'))
        self.assertFalse(plan['changed'])
        self.assertIn('+    sendfile on;', plan['diff'])
        self.assertEqual(self.main.read_text(), ORIGINAL)
        self.assertFalse((self.root / 'reloads').exists())
        applied = tuning.execute('apply', self.settings('apply'))
        self.assertTrue(applied['changed'])
        self.assertEqual(self.main.stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.root / 'backups/apply/original.conf').stat().st_mode & 0o777, 0o600)
        self.assertFalse(tuning.execute('apply', self.settings('noop'))['changed'])
        self.assertEqual((self.root / 'reloads').read_text(), '1')
        settings = self.settings('restore')
        settings['restore_id'] = 'apply'
        tuning.execute('restore', settings)
        self.assertEqual(self.main.read_text(), ORIGINAL)
        self.assertEqual((self.root / 'reloads').read_text(), '2')

    def test_invalid_candidate_does_not_modify_or_reload(self):
        settings = self.settings('invalid')
        settings['directives'] = {'http': {'keepalive_requests': 'BAD'}}
        with self.assertRaises(RuntimeError):
            tuning.execute('apply', settings)
        self.assertEqual(self.main.read_text(), ORIGINAL)
        self.assertFalse((self.root / 'reloads').exists())

    def test_reload_and_health_failures_restore_original(self):
        for failure in ['fail-once', 'fail-health']:
            with self.subTest(failure=failure):
                (self.root / failure).touch()
                with self.assertRaisesRegex(RuntimeError, 'restored successfully'):
                    tuning.execute('apply', self.settings(failure))
                self.assertEqual(self.main.read_text(), ORIGINAL)
                (self.root / failure).unlink()
        self.assertEqual((self.root / 'reloads').read_text(), '4')

    def test_reports_recovery_reload_failure(self):
        (self.root / 'fail-always').touch()
        with self.assertRaisesRegex(RuntimeError, 'recovery reload failed'):
            tuning.execute('apply', self.settings('fail'))
        self.assertEqual(self.main.read_text(), ORIGINAL)

    def test_restore_refuses_newer_changes(self):
        tuning.execute('apply', self.settings('apply'))
        self.main.write_text(self.main.read_text() + '# later change\n')
        settings = self.settings('restore')
        settings['restore_id'] = 'apply'
        with self.assertRaisesRegex(ValueError, 'newer changes'):
            tuning.execute('restore', settings)
        self.assertIn('# later change', self.main.read_text())

    def test_preserves_config_symlink(self):
        target = self.root / 'real-config'
        target.mkdir()
        actual = target / 'main.conf'
        self.main.rename(actual)
        self.main.symlink_to(actual)
        tuning.execute('apply', self.settings('symlink'))
        self.assertTrue(self.main.is_symlink())
        self.assertIn('sendfile on;', actual.read_text())

    def test_ansible_entry_point_and_artifact_collection(self):
        inventory = self.root / 'hosts.json'
        inventory.write_text(json.dumps({'all': {'children': {'proxy': {'hosts': {
            'localtest': {'ansible_connection': 'local',
                          'ansible_remote_tmp': str(self.root / 'ansible-tmp'),
                          'ansible_python_interpreter': '/usr/bin/python3'}
        }}}}}))
        settings = self.settings('unused')
        config = self.root / 'settings.json'
        config.write_text(json.dumps({
            'ops_become': False, 'ops_require_ssh': False,
            'ops_artifact_root': str(self.root / 'artifacts'),
            'ops_nginx_config_path': settings['config_path'],
            'ops_nginx_backup_root': settings['backup_root'],
            'ops_nginx_argv': settings['nginx_argv'],
            'ops_nginx_reload_argv': settings['reload_argv'],
            'ops_nginx_health_argv': settings['health_argv'],
            'ops_nginx_directives': settings['directives'],
        }))
        def invoke(action, extra=(), success=True):
            result = subprocess.run([str(ROOT / 'run.sh'), action, '-i', str(inventory),
                                     '-c', str(config), *extra], cwd='/tmp', capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        invoke('nginx-plan')
        self.assertEqual(self.main.read_text(), ORIGINAL)
        invoke('nginx-apply')
        manifests = list((self.root / 'backups').glob('*/manifest.json'))
        apply_id = next(p.parent.name for p in manifests if json.loads(p.read_text())['action'] == 'apply')
        invoke('nginx-restore', ['-e', 'ops_nginx_restore_id=' + apply_id])
        self.assertEqual(self.main.read_text(), ORIGINAL)
        self.assertEqual(len(list((self.root / 'artifacts').glob('*/localtest/nginx-changes.diff'))), 3)
        (self.root / 'fail-health').touch()
        invoke('nginx-apply', success=False)
        self.assertEqual(self.main.read_text(), ORIGINAL)
        for path in (self.root / 'artifacts').glob('*/localtest/nginx-*'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()

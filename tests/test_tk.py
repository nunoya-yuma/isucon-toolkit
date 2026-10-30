"""Local Git + fake SSH/sudo/systemctl; never contacts a server or GitHub."""
import base64
import contextlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('remote', ROOT / 'lib/remote.py')
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.headers.get('Host') == 'app.example' else 500)
        self.end_headers()

    def log_message(self, *args):
        pass


class ToolkitTest(unittest.TestCase):
    def command(self, *argv, cwd=None):
        return subprocess.check_output(argv, cwd=cwd, stderr=subprocess.DEVNULL).decode().strip()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tk-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.source = self.base / 'source'
        self.source.mkdir()
        self.recv = self.base / 'receive.git'
        self.app = self.base / 'app'
        self.state = self.base / 'state'
        (self.state / 'ops').mkdir(parents=True)
        (self.state / 'lock').touch()
        self.target = self.base / 'config'
        self.created = self.base / 'created'
        self.target.write_text('original\n')
        self.active = self.base / 'service-active'
        self.active.touch()
        self.boot = self.base / 'boot-id'
        self.boot.write_text('old-boot\n')
        self.executable('sudo', '''#!/usr/bin/env python3
import os,sys
a=sys.argv[1:]
if a[:1]==['-n']:a=a[1:]
if a[:1]==['-u']:a=a[2:]
os.execvp(a[0],a)
''')
        self.executable('systemctl', '''#!/usr/bin/env python3
import os,pathlib,sys
p=pathlib.Path(os.environ['TK_TEST_ACTIVE'])
action=sys.argv[1]
if action=='is-enabled':sys.exit(0)
if action=='is-active':sys.exit(0 if p.exists() else 3)
if action in ('restart','start'):
 p.touch()
 if os.environ.get('TK_TEST_BINARY'):
  pathlib.Path(os.environ['TK_TEST_STARTED_BINARY']).write_bytes(pathlib.Path(os.environ['TK_TEST_BINARY']).read_bytes())
if action=='stop':p.unlink(missing_ok=True)
if action=='show':
 print('LoadState=loaded\\nUnitFileState=enabled\\nActiveState='+('active' if p.exists() else 'inactive') if sys.argv[2]=='test-app' else 'LoadState=not-found')
if action=='reboot':pathlib.Path(os.environ['TK_TEST_BOOT_ID']).write_text('new-boot\\n')
''')
        self.executable('ssh', '''#!/usr/bin/env python3
import base64,json,os,shlex,subprocess,sys
a=sys.argv[1:]
while a and a[0].startswith('-'):
 option=a.pop(0)
 if option in ('-o','-p','-i'):a.pop(0)
if a[:1]==['-G']:sys.exit(0)
host=a.pop(0)
if host!='contest-1':sys.exit(255)
command=' '.join(a)
if command.startswith('bash -s -- '):
 parts=shlex.split(command);c=json.loads(base64.b64decode(parts[-1]))
 c['state']=os.environ['TK_TEST_STATE'];c['recv']=os.environ['TK_TEST_RECV']
 parts[-1]=base64.b64encode(json.dumps(c).encode()).decode()
 command=shlex.join(parts)
 body=sys.stdin.buffer.read().replace(b"Path('/proc/sys/kernel/random/boot_id')",('Path('+repr(os.environ['TK_TEST_BOOT_ID'])+')').encode())
 sys.exit(subprocess.run(['bash','-c',command],input=body).returncode)
command=command.replace('/var/lib/tk-recv.git',os.environ['TK_TEST_RECV']).replace('/var/lib/tk',os.environ['TK_TEST_STATE'])
os.execvp('bash',['bash','-c',command])
''')
        patcher = mock.patch.dict(os.environ, {
            'PATH': str(self.bin) + ':' + os.environ['PATH'],
            'TK_TEST_ACTIVE': str(self.active), 'TK_TEST_STATE': str(self.state),
            'TK_TEST_RECV': str(self.recv), 'GIT_CONFIG_NOSYSTEM': '1',
            'TK_TEST_BOOT_ID': str(self.boot),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.command('git', 'init', '-q', '--bare', str(self.recv))
        self.command('git', 'init', '-q', str(self.source))
        self.command('git', 'config', 'user.name', 'Test User', cwd=self.source)
        self.command('git', 'config', 'user.email', 'test@example.invalid', cwd=self.source)
        (self.source / 'app.txt').write_text('old app\n')
        (self.source / '.gitignore').write_text('tk.env\nruns/\n')
        self.command('git', 'add', '.', cwd=self.source)
        self.command('git', 'commit', '-qm', 'initial', cwd=self.source)
        self.previous = self.command('git', 'rev-parse', 'HEAD', cwd=self.source)
        self.command('git', 'clone', '-q', str(self.source), str(self.app))
        self.command('git', 'remote', 'add', 'origin', str(self.recv), cwd=self.source)
        for target, text in [(self.target, 'replacement\n'), (self.created, 'created\n')]:
            source = self.source / 'server' / str(target).lstrip('/')
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(text)
        (self.source / 'app.txt').write_text('new app\n')
        self.command('git', 'add', '.', cwd=self.source)
        self.command('git', 'commit', '-qm', 'candidate', cwd=self.source)
        self.sha = self.command('git', 'rev-parse', 'HEAD', cwd=self.source)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        client_spec = importlib.util.spec_from_file_location('client', ROOT / 'lib/client.py')
        self.client = importlib.util.module_from_spec(client_spec)
        client_spec.loader.exec_module(self.client)
        self.c = {'host': 'contest-1', 'app': str(self.app), 'user': pwd.getpwuid(os.getuid()).pw_name,
                  'service': 'test-app', 'state': str(self.state), 'recv': str(self.recv),
                  'sha': self.sha, 'op_id': '20260101T000000Z-deploy-1234', 'actor': 'test',
                  'sources': self.client.sources(self.sha, 'contest-1', self.source),
                  'build': '', 'ready_url': 'http://127.0.0.1:' + str(self.server.server_port),
                  'ready_host': 'app.example', 'codes': [200], 'ready_timeout': 1, 'is_app': True}
        self.command('git', 'push', '-q', str(self.recv), self.sha + ':refs/tk/incoming/' + self.c['op_id'], cwd=self.source)

    def executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def record(self):
        return json.loads((self.state / 'ops' / (self.c['op_id'] + '.json')).read_text())

    def recover(self):
        for line in self.record()['recovery']:
            subprocess.run(['bash', '-ec', line], check=True, capture_output=True)

    def test_success_and_status_and_manual_recovery(self):
        self.assertEqual(remote.status(self.c)['match'], 'no-record')
        result, code = remote.deploy(self.c)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.target.read_text(), 'replacement\n')
        self.assertTrue(remote.status(self.c)['ok'])
        self.recover()
        self.assertEqual(self.target.read_text(), 'original\n')
        self.assertFalse(self.created.exists())
        self.assertEqual(self.command('git', 'rev-parse', 'HEAD', cwd=self.app), self.previous)

    def test_dirty_checkout_is_preserved(self):
        (self.app / 'app.txt').write_text('manual work\n')
        result, code = remote.deploy(self.c)
        self.assertEqual((code, result['step']), (3, 'prepare'))
        self.assertEqual((self.app / 'app.txt').read_text(), 'manual work\n')
        self.assertEqual(self.target.read_text(), 'original\n')

    def test_build_failure_has_usable_recovery(self):
        self.c['build'] = 'if [ "$(cat app.txt)" = "new app" ]; then exit 7; fi'
        result, code = remote.deploy(self.c)
        self.assertEqual((code, result['step']), (1, 'restart'))
        self.assertEqual(remote.status(self.c)['match'], 'no-record')
        self.recover()
        self.assertEqual(self.target.read_text(), 'original\n')
        self.assertFalse(self.created.exists())

    def prepare_binary_build(self):
        binary = self.app / 'app.bin'
        binary.write_text('old app\n')
        with (self.app / '.git/info/exclude').open('a') as excluded:
            excluded.write('\n/app.bin\n')
        self.c.update(build='cp -- app.txt app.bin', codes=[503], ready_timeout=0.1)
        return binary, self.base / 'last-started-binary'

    def test_recovery_rebuilds_old_binary_before_restart_after_ready_failure(self):
        binary, started = self.prepare_binary_build()
        with mock.patch.dict(os.environ, TK_TEST_BINARY=str(binary), TK_TEST_STARTED_BINARY=str(started)):
            result, code = remote.deploy(self.c)
            self.assertEqual((code, result['step']), (1, 'ready'))
            self.assertEqual(binary.read_text(), 'new app\n')
            self.assertEqual(started.read_text(), 'new app\n')
            self.recover()
        self.assertEqual(binary.read_text(), 'old app\n')
        self.assertEqual(started.read_text(), 'old app\n')
        self.assertEqual(self.command('git', 'rev-parse', 'HEAD', cwd=self.app), self.previous)

    def test_recovery_build_failure_does_not_restart_a_stale_binary(self):
        binary, started = self.prepare_binary_build()
        self.c['build'] = 'if [ "$(cat app.txt)" = "old app" ]; then exit 9; fi; ' + self.c['build']
        with mock.patch.dict(os.environ, TK_TEST_BINARY=str(binary), TK_TEST_STARTED_BINARY=str(started)):
            self.assertEqual(remote.deploy(self.c)[1], 1)
            started.unlink()
            # Pasting all lines into a normal shell must not restart after a failed build.
            result = subprocess.run(['bash', '-c', '\n'.join(self.record()['recovery'])], capture_output=True)
        self.assertEqual(result.returncode, 9)
        self.assertFalse(started.exists())
        self.assertEqual(binary.read_text(), 'new app\n')
        self.assertEqual(self.command('git', 'rev-parse', 'HEAD', cwd=self.app), self.previous)

    def test_recovery_keeps_an_originally_stopped_app_stopped_when_build_fails(self):
        binary, started = self.prepare_binary_build()
        self.active.unlink()
        self.c['build'] = 'if [ "$(cat app.txt)" = "old app" ]; then exit 9; fi; ' + self.c['build']
        with mock.patch.dict(os.environ, TK_TEST_BINARY=str(binary), TK_TEST_STARTED_BINARY=str(started)):
            self.assertEqual(remote.deploy(self.c)[1], 1)
            self.assertTrue(self.active.exists())
            result = subprocess.run(['bash', '-c', '\n'.join(self.record()['recovery'])], capture_output=True)
        self.assertEqual(result.returncode, 9)
        self.assertFalse(self.active.exists())

    def test_recovery_rebuild_is_safe_when_backup_failed_before_checkout(self):
        binary, started = self.prepare_binary_build()
        with mock.patch.dict(os.environ, TK_TEST_BINARY=str(binary), TK_TEST_STARTED_BINARY=str(started)), \
                mock.patch.object(remote.shutil, 'copy2', side_effect=OSError('backup failed')):
            result, code = remote.deploy(self.c)
            self.assertEqual((code, result['step']), (1, 'backup'))
            self.recover()
        self.assertEqual(binary.read_text(), 'old app\n')
        self.assertEqual(started.read_text(), 'old app\n')
        self.assertEqual(self.target.read_text(), 'original\n')

    def test_app_unit_file_change_does_not_schedule_an_early_restart(self):
        for service in ('test-app', 'test-app.service'):
            with self.subTest(service=service):
                items = [{'path': '/etc/systemd/system/test-app.service'}]
                self.assertEqual(remote.services_for(dict(self.c, service=service), items), [])

    def test_interruption_does_not_need_per_file_state(self):
        original = Path.write_bytes
        def interrupted(path, content):
            result = original(path, content)
            if path == self.created:
                raise KeyboardInterrupt()
            return result
        with mock.patch.object(Path, 'write_bytes', interrupted):
            with self.assertRaises(KeyboardInterrupt):
                remote.deploy(self.c)
        self.assertEqual(self.record()['status'], 'running')
        self.recover()
        self.assertEqual(self.target.read_text(), 'original\n')
        self.assertFalse(self.created.exists())

    def test_lock_contention(self):
        import fcntl
        with (self.state / 'lock').open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            remote.atomic(self.state / 'lock.json', {'op_id': 'other', 'actor': 'someone'})
            result, code = remote.deploy(self.c)
        self.assertEqual(code, 3)
        self.assertEqual(result['last_lock_record']['op_id'], 'other')
        self.assertFalse((self.state / 'ops' / (self.c['op_id'] + '.json')).exists())

    def test_partial_backup_is_not_a_recovery_source(self):
        def partial_copy(source, destination):
            Path(destination).write_bytes(b'partial')
            raise OSError('injected copy failure')
        with mock.patch.object(remote.shutil, 'copy2', partial_copy):
            result, code = remote.deploy(self.c)
        self.assertEqual((code, result['step']), (1, 'backup'))
        self.recover()
        self.assertEqual(self.target.read_text(), 'original\n')
        self.assertEqual(self.command('git', 'rev-parse', 'HEAD', cwd=self.app), self.previous)

    def test_two_deploy_processes_share_the_lock(self):
        marker = self.base / 'build-started'
        first = dict(self.c, build='touch ' + shlex.quote(str(marker)) + '; sleep 0.5')
        encoded = base64.b64encode(json.dumps(first).encode()).decode()
        process = subprocess.Popen(['python3', str(ROOT / 'lib/remote.py'), 'deploy', encoded],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            result, code = remote.deploy(dict(self.c, op_id='20260101T000001Z-deploy-5678'))
            self.assertEqual(code, 3)
            self.assertEqual(result['last_lock_record']['op_id'], first['op_id'])
            out, err = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, err)
            self.assertEqual(json.loads(out)['result'], 'ok')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_same_sha_ready_failure_is_visible(self):
        self.assertEqual(remote.deploy(self.c)[1], 0)
        self.c = dict(self.c, op_id='20260101T000001Z-deploy-5678', codes=[503], ready_timeout=0.1)
        self.command('git', 'push', '-q', str(self.recv), self.sha + ':refs/tk/incoming/' + self.c['op_id'], cwd=self.source)
        self.assertEqual(remote.deploy(self.c)[1], 1)
        data = remote.status(self.c)
        self.assertEqual(data['match'], 'match')
        self.assertEqual(data['health'], 'needs-attention')
        self.assertFalse(data['ok'])

    def cli(self, *args):
        config = self.source / 'tk.env'
        values = {'TK_HOSTS': 'contest-1', 'TK_ROLE_app': 'contest-1', 'APP_DIR': str(self.app),
                  'APP_USER': self.c['user'], 'APP_SERVICE': self.c['service'],
                  'READY_URL': self.c['ready_url'], 'READY_HOST': 'app.example',
                  'READY_TIMEOUT': '2', 'REBOOT_TIMEOUT': '1'}
        config.write_text(''.join(key + '=' + shlex.quote(value) + '\n' for key, value in values.items()))
        return subprocess.run([str(ROOT / 'tk'), *args], cwd=self.source, capture_output=True, text=True)

    def test_cli_plan_then_deploy_and_status(self):
        before = self.command('git', 'show-ref', cwd=self.recv)
        planned = self.cli('deploy', '--plan', self.sha, 'contest-1')
        self.assertEqual(planned.returncode, 0, planned.stderr + planned.stdout)
        self.assertEqual(self.command('git', 'show-ref', cwd=self.recv), before)
        self.assertFalse(list((self.state / 'ops').glob('*.json')))
        self.assertEqual(self.target.read_text(), 'original\n')
        deployed = self.cli('deploy', self.sha, 'contest-1')
        self.assertEqual(deployed.returncode, 0, deployed.stderr + deployed.stdout)
        observed = self.cli('status', '--detail', 'contest-1')
        self.assertEqual(observed.returncode, 0, observed.stderr + observed.stdout)
        self.assertIn('match', observed.stdout)

    def test_cli_rejects_unknown_host_before_delivery(self):
        result = self.cli('deploy', self.sha, 'contest-1', 'other')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(list((self.state / 'ops').glob('*.json')))

    def test_cli_deploy_reboot_and_final_check_keep_deploy_identity(self):
        deployed = self.cli('deploy', self.sha, 'contest-1')
        self.assertEqual(deployed.returncode, 0, deployed.stderr)
        before = sorted((self.state / 'ops').glob('*.json'))
        planned = self.cli('reboot', '--plan', 'contest-1')
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(sorted((self.state / 'ops').glob('*.json')), before)
        rebooted = self.cli('reboot', 'contest-1')
        self.assertEqual(rebooted.returncode, 0, rebooted.stdout + rebooted.stderr)
        self.assertEqual(self.boot.read_text(), 'new-boot\n')
        records = [json.loads(p.read_text()) for p in (self.state / 'ops').glob('*.json')]
        self.assertEqual({r['task'] for r in records}, {'deploy', 'reboot'})
        self.assertTrue(all(r['status'] == 'ok' for r in records))
        checked = self.cli('final-check', 'contest-1')
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn('contest-1=OK', checked.stdout)
        self.assertTrue(remote.status(self.c)['ok'])

    def test_non_app_without_deploy_record_is_not_an_error(self):
        data = remote.status(dict(self.c, is_app=False))
        self.assertEqual(data['match'], 'no-record')
        self.assertEqual(data['health'], 'not-applicable')
        self.assertTrue(data['ok'])

    def test_publish_pushes_requested_branch_without_operation_branches(self):
        self.command('git', 'push', '-q', 'origin', self.previous + ':refs/heads/main', cwd=self.source)
        self.command('git', 'symbolic-ref', 'HEAD', 'refs/heads/main', cwd=self.recv)
        branch = 'feat/candidate'
        self.command('git', 'branch', branch, self.sha, cwd=self.source)
        self.assertTrue(self.client.publish(branch, self.sha, self.source))
        refs = self.command('git', 'for-each-ref', '--format=%(refname)', 'refs/heads/', cwd=self.recv)
        self.assertEqual(refs.splitlines(), ['refs/heads/' + branch, 'refs/heads/main'])

    def test_publish_default_branch_only_checks_remote_history(self):
        for branch in ('main', 'release'):
            with self.subTest(branch=branch):
                self.command('git', 'update-ref', 'refs/heads/' + branch, self.sha, cwd=self.source)
                self.command('git', 'push', '-q', 'origin', self.previous + ':refs/heads/' + branch, cwd=self.source)
                self.command('git', 'symbolic-ref', 'HEAD', 'refs/heads/' + branch, cwd=self.recv)
                self.assertFalse(self.client.publish(branch, self.sha, self.source))
                self.assertEqual(self.command('git', 'rev-parse', branch, cwd=self.recv), self.previous)
                self.command('git', 'push', '-q', 'origin', self.sha + ':refs/heads/' + branch, cwd=self.source)
                self.assertTrue(self.client.publish('refs/heads/' + branch, self.sha, self.source))

    def test_publish_unknown_default_branch_does_not_push(self):
        branch = self.command('git', 'branch', '--show-current', cwd=self.source)
        self.assertFalse(self.client.publish(branch, self.sha, self.source))
        self.assertEqual(self.command('git', 'for-each-ref', '--format=%(refname)', 'refs/heads/', cwd=self.recv), '')

    def test_publish_sha_checks_a_containing_origin_branch(self):
        self.assertFalse(self.client.publish(self.sha, self.sha, self.source))
        self.command('git', 'push', '-q', 'origin', self.sha + ':refs/heads/review', cwd=self.source)
        self.assertTrue(self.client.publish(self.sha, self.sha, self.source))
        refs = self.command('git', 'for-each-ref', '--format=%(refname)', 'refs/heads/', cwd=self.recv)
        self.assertEqual(refs, 'refs/heads/review')

    def controller(self, task, *args, **overrides):
        c = dict(self.c, hosts=['contest-1', 'contest-2', 'contest-3'],
                 apps=['contest-1', 'contest-2'], reboot_timeout=0.02, profiler_port='')
        c.update(overrides)
        before = set((self.source / 'runs').glob('*.json'))
        output = io.StringIO()
        with mock.patch.object(self.client, 'config', return_value=c), \
                mock.patch.dict(os.environ, TK_PROJECT_ROOT=str(self.source), TK_ACTOR='test'), \
                mock.patch('sys.argv', ['client.py', task, *args]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = self.client.main()
        created = set((self.source / 'runs').glob('*.json')) - before
        manifest = json.loads(created.pop().read_text()) if created else None
        return code, manifest, output.getvalue()

    def test_multi_deploy_pins_sha_order_and_host_sources(self):
        override = self.source / 'hosts/contest-2' / str(self.target).lstrip('/')
        override.parent.mkdir(parents=True)
        override.write_text('host two config\n')
        self.command('git', 'add', '.', cwd=self.source)
        self.command('git', 'commit', '-qm', 'host override', cwd=self.source)
        pinned = self.command('git', 'rev-parse', 'HEAD', cwd=self.source)
        calls = []

        def deploy(host, c, project):
            calls.append((host, c))
            if len(calls) == 1:
                (self.source / 'app.txt').write_text('next candidate\n')
                self.command('git', 'commit', '-qam', 'branch advances while deploying', cwd=self.source)
            return {'result': 'ok', 'step': 'done'}

        with mock.patch.object(self.client, 'deploy_one', side_effect=deploy), \
                mock.patch.object(self.client, 'publish', return_value=True) as publish:
            code, manifest, _ = self.controller('deploy', 'HEAD', 'contest-2', 'contest-1')
        self.assertEqual(code, 0)
        self.assertEqual([h for h, c in calls], ['contest-2', 'contest-1'])
        self.assertEqual({c['sha'] for h, c in calls}, {pinned})
        self.assertEqual(len({c['op_id'] for h, c in calls}), 1)
        self.assertTrue(any(s['source'].startswith('hosts/contest-2/') for s in calls[0][1]['sources']))
        self.assertTrue(all(s['source'].startswith('server/') for s in calls[1][1]['sources']))
        publish.assert_called_once_with('HEAD', pinned, str(self.source))
        self.assertEqual(manifest['sha'], pinned)

    def test_multi_deploy_stops_without_contacting_remaining_hosts(self):
        cases = [(['refused'], 3), (['ok', 'failed'], 1), (['ok', 'unknown'], 1), (['unknown'], 1)]
        for states, expected in cases:
            with self.subTest(states=states), \
                    mock.patch.object(self.client, 'publish', return_value=True), \
                    mock.patch.object(self.client, 'deploy_one', side_effect=[
                        {'result': state, 'step': 'test'} for state in states]) as deploy:
                code, manifest, _ = self.controller('deploy', self.sha, 'contest-1', 'contest-2', 'contest-3')
                self.assertEqual(code, expected)
                self.assertEqual(deploy.call_count, len(states))
                results = list(manifest['results'].values())
                self.assertTrue(all(r['result'] == 'skipped' for r in results[len(states):]))

    def test_multi_plan_reads_all_hosts_without_publish_or_delivery(self):
        with mock.patch.object(self.client, 'remote', return_value=(0, {'files': []})) as read, \
                mock.patch.object(self.client, 'publish') as publish, \
                mock.patch.object(self.client, 'deploy_one') as deploy:
            code, manifest, _ = self.controller('deploy', '--plan', self.sha, '@app')
        self.assertEqual(code, 0)
        self.assertIsNone(manifest)
        self.assertEqual([call.args[0] for call in read.call_args_list], ['contest-1', 'contest-2'])
        publish.assert_not_called()
        deploy.assert_not_called()

    def test_lost_deploy_reply_is_unknown(self):
        success = subprocess.CompletedProcess([], 0, '', '')
        with mock.patch.object(self.client, 'ssh', return_value=success), \
                mock.patch.object(self.client, 'run', return_value=success), \
                mock.patch.object(self.client, 'remote', side_effect=RuntimeError('reply lost')):
            result = self.client.deploy_one('contest-1', self.c, self.source)
        self.assertEqual(result['result'], 'unknown')

    def test_reboot_records_success_only_after_boot_id_changes(self):
        c = dict(self.c, boot_id='old-boot')
        with mock.patch.object(remote, 'boot_id', return_value='old-boot'), \
                mock.patch.object(remote, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')):
            result, code = remote.reboot(c)
            self.assertEqual((code, result['result']), (0, 'requested'))
            self.assertEqual(self.record()['status'], 'running')
            self.assertEqual(remote.reboot_finish(c)['result'], 'waiting')
            self.assertEqual(self.record()['status'], 'running')
        with mock.patch.object(remote, 'boot_id', return_value='new-boot'):
            result = remote.reboot_finish(c)
        self.assertEqual(result['result'], 'ok')
        self.assertEqual((self.record()['status'], self.record()['new_boot_id']), ('ok', 'new-boot'))

    def test_reboot_rejection_is_failed_and_lock_is_shared_with_deploy(self):
        import fcntl
        c = dict(self.c, boot_id='old-boot')
        with (self.state / 'lock').open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            remote.atomic(self.state / 'lock.json', {'op_id': 'deploy-other'})
            result, code = remote.reboot(c)
            self.assertEqual((code, result['step']), (3, 'lock'))
            self.assertEqual(result['last_lock_record']['op_id'], 'deploy-other')
        with mock.patch.object(remote, 'boot_id', return_value='old-boot'), \
                mock.patch.object(remote, 'run', side_effect=RuntimeError('request denied')):
            result, code = remote.reboot(c)
        self.assertEqual((code, result['result']), (1, 'failed'))
        self.assertEqual(self.record()['status'], 'failed')
        with mock.patch.object(remote, 'boot_id', return_value='new-boot'):
            with self.assertRaises(RuntimeError):
                remote.reboot_finish(c)

    def test_reboot_lost_reply_can_still_be_confirmed(self):
        replies = [(0, {'boot_id': 'old'}), RuntimeError('SSH lost'),
                   (0, {'result': 'ok', 'step': 'done'})]
        with mock.patch.object(self.client, 'remote', side_effect=replies):
            result = self.client.reboot_one('contest-1', dict(self.c, reboot_timeout=1))
        self.assertEqual(result['result'], 'ok')

    def test_interrupted_reboot_request_leaves_running_record(self):
        c = dict(self.c, boot_id='old-boot')
        interrupted = subprocess.CompletedProcess([], -15, b'', b'')
        with mock.patch.object(remote, 'boot_id', return_value='old-boot'), \
                mock.patch.object(remote, 'run', return_value=interrupted):
            result, code = remote.reboot(c)
        self.assertEqual((code, result['result']), (1, 'unknown'))
        self.assertEqual(self.record()['status'], 'running')

    def test_reboot_timeout_is_unknown_and_stops_remaining_hosts(self):
        def reply(host, action, c, timeout, **kwargs):
            if action == 'reboot-plan':
                return 0, {'boot_id': 'old'}
            return 0, {'result': 'waiting' if action == 'reboot-finish' else 'requested', 'step': 'requested'}
        with mock.patch.object(self.client, 'remote', side_effect=reply) as send:
            code, manifest, _ = self.controller('reboot', 'contest-2', 'contest-1')
        self.assertEqual(code, 1)
        self.assertEqual(manifest['results']['contest-2']['result'], 'unknown')
        self.assertEqual(manifest['results']['contest-1']['result'], 'skipped')
        self.assertEqual({call.args[0] for call in send.call_args_list}, {'contest-2'})

    def test_reboot_sequence_and_plan(self):
        with mock.patch.object(self.client, 'reboot_one', return_value={'result': 'ok', 'step': 'done'}) as reboot:
            code, manifest, _ = self.controller('reboot', 'contest-3', '@app')
        self.assertEqual(code, 0)
        self.assertEqual([call.args[0] for call in reboot.call_args_list], ['contest-3', 'contest-1', 'contest-2'])
        self.assertEqual(len({call.args[1]['op_id'] for call in reboot.call_args_list}), 1)
        with mock.patch.object(self.client, 'remote') as remote_call, \
                mock.patch.object(self.client, 'reboot_one') as reboot:
            code, manifest, output = self.controller('reboot', '--plan', 'contest-2', 'contest-1')
        self.assertEqual(code, 0)
        self.assertIsNone(manifest)
        self.assertIn('order=contest-2,contest-1', output)
        remote_call.assert_not_called()
        reboot.assert_not_called()

    def final_observation(self, *, nginx='access_log off;', mysql=b'0\t0\n', listeners=b'',
                          running=False, non_app=False):
        observed = {'match': 'match', 'health': 'running', 'http': 200, 'record_errors': [],
                    'latest': [{'op_id': 'other', 'status': 'running'}] if running else []}

        def command(argv, **kwargs):
            if argv[0] == 'systemctl' and argv[1] == 'show':
                text = ('LoadState=not-found\n' if non_app else
                        'LoadState=loaded\nUnitFileState=enabled\nActiveState=active\n')
                return subprocess.CompletedProcess(argv, 0, text.encode(), b'')
            if argv[0] == 'nginx':
                return subprocess.CompletedProcess(argv, 0, nginx.encode(), b'')
            if argv[0] == 'mysql':
                if isinstance(mysql, Exception):
                    raise mysql
                return subprocess.CompletedProcess(argv, 0, mysql, b'')
            return subprocess.CompletedProcess(argv, 0, listeners if argv[0] == 'ss' else b'', b'')

        with mock.patch.object(remote, 'status', return_value=observed), \
                mock.patch.object(remote, 'run', side_effect=command) as commands:
            result = remote.final_check(dict(self.c, profiler_port='6060', is_app=not non_app))
        return result, commands.call_args_list

    def test_final_check_is_read_only_and_does_not_print_config(self):
        before = list((self.state / 'ops').iterdir())
        result, commands = self.final_observation(nginx='secret PRIVATE_SENTINEL;\naccess_log off;')
        self.assertTrue(result['ok'])
        self.assertEqual(list((self.state / 'ops').iterdir()), before)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertFalse(any('fetch' in call.args[0] or 'restart' in call.args[0] for call in commands))

    def test_final_check_unknown_is_distinct_from_ng(self):
        result, _ = self.final_observation(nginx='http {}', mysql=RuntimeError('authentication failed'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['checks']['nginx-access-log']['state'], '未確認')
        self.assertEqual(result['checks']['mysql-logs']['state'], '未確認')
        result, _ = self.final_observation(nginx='access_log /tmp/access.log;', mysql=b'1\t0\n', listeners=b'listening')
        self.assertEqual(result['checks']['nginx-access-log']['state'], 'NG')
        self.assertEqual(result['checks']['mysql-logs']['state'], 'NG')
        self.assertEqual(result['checks']['profiler']['state'], 'NG')

    def test_final_check_running_record_and_non_app_boundaries(self):
        result, _ = self.final_observation(running=True)
        self.assertEqual(result['checks']['operation']['state'], 'NG')
        result, commands = self.final_observation(non_app=True)
        self.assertTrue(result['ok'])
        self.assertNotIn('checkout', result['checks'])
        self.assertNotIn('app', result['checks'])
        self.assertFalse(any(call.args[0][0] in ('nginx', 'mysql') for call in commands))

    def test_final_check_connection_failure_is_unconfirmed(self):
        with mock.patch.object(self.client, 'remote', side_effect=RuntimeError('SSH unavailable')):
            code, manifest, output = self.controller('final-check', 'contest-1')
        self.assertEqual(code, 1)
        self.assertEqual(manifest['results']['contest-1']['checks']['connection']['state'], '未確認')
        self.assertIn('contest-1=未確認', output)


if __name__ == '__main__':
    unittest.main()

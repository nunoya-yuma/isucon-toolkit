"""Local Git + fake SSH/sudo/systemctl; never contacts a server or GitHub."""
import base64
import contextlib
import http.server
import importlib.util
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
if action in ('restart','start'):p.touch()
if action=='stop':p.unlink(missing_ok=True)
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
command=command.replace('/var/lib/tk-recv.git',os.environ['TK_TEST_RECV']).replace('/var/lib/tk',os.environ['TK_TEST_STATE'])
os.execvp('bash',['bash','-c',command])
''')
        patcher = mock.patch.dict(os.environ, {
            'PATH': str(self.bin) + ':' + os.environ['PATH'],
            'TK_TEST_ACTIVE': str(self.active), 'TK_TEST_STATE': str(self.state),
            'TK_TEST_RECV': str(self.recv), 'GIT_CONFIG_NOSYSTEM': '1',
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
        self.c['build'] = 'exit 7'
        result, code = remote.deploy(self.c)
        self.assertEqual((code, result['step']), (1, 'restart'))
        self.assertEqual(remote.status(self.c)['match'], 'no-record')
        self.recover()
        self.assertEqual(self.target.read_text(), 'original\n')
        self.assertFalse(self.created.exists())

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
                  'READY_TIMEOUT': '2'}
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

    def test_cli_rejects_multi_host_before_delivery(self):
        result = self.cli('deploy', self.sha, 'contest-1', 'other')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(list((self.state / 'ops').glob('*.json')))


if __name__ == '__main__':
    unittest.main()

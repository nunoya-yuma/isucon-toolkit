"""Runs on the server via bash/SSH stdin; no installed agent or extra packages."""
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='microseconds')


def run(argv, *, check=True, timeout=30, cwd=None):
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=cwd, start_new_session=True)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise
    result = subprocess.CompletedProcess(argv, process.returncode, out, err)
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip() or str(argv[:2]))
    return result


def git(c, *args):
    return run(['sudo', '-n', '-u', c['user'], 'git', '-C', c['app'], *args]).stdout


def atomic(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.tk-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ready(c, timeout=2):
    headers = {'Host': c['ready_host']} if c['ready_host'] else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(c['ready_url'], headers=headers),
                                    timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (OSError, urllib.error.URLError, ValueError):
        return 0


def active(service):
    return run(['systemctl', 'is-active', service], check=False).returncode == 0


def read_records(c):
    records = []
    errors = []
    for path in (Path(c['state']) / 'ops').glob('*.json'):
        try:
            record = json.loads(path.read_text())
            if not all(key in record for key in ('op_id', 'task', 'status', 'started_at', 'step')):
                raise ValueError('missing record fields')
            records.append(record)
        except (OSError, ValueError) as error:
            errors.append(path.name + ': ' + str(error))
    return records, errors


def status(c):
    result = {'host': c['host'], 'errors': []}
    try:
        result['head'] = git(c, 'rev-parse', 'HEAD').decode().strip()
        result['branch'] = git(c, 'branch', '--show-current').decode().strip() or '(detached)'
        result['dirty'] = bool(git(c, 'status', '--porcelain'))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        result['errors'].append(str(error))
    records, errors = read_records(c)
    result['errors'].extend(errors)
    latest = max((r.get('started_at', '') for r in records), default='')
    result['latest'] = [r for r in records if r.get('started_at') == latest]
    successes = [r for r in records if r['task'] == 'deploy' and r['status'] == 'ok']
    ended = max((r.get('ended_at', '') for r in successes), default='')
    last_ok = [r for r in successes if r.get('ended_at') == ended]
    result['last_deploy'] = last_ok
    if result['errors'] or 'head' not in result or len(last_ok) > 1:
        result['match'] = 'unconfirmed'
    elif not last_ok:
        result['match'] = 'no-record'
    else:
        result['match'] = ('match' if not result['dirty'] and
                           result['head'] == last_ok[0].get('sha') else 'mismatch')
    result['lock_record'] = None
    if any(r['status'] == 'running' for r in result['latest']):
        try:
            result['lock_record'] = json.loads((Path(c['state']) / 'lock.json').read_text())
        except (OSError, ValueError):
            result['errors'].append('lock record unreadable (not proof of a held lock)')
    if c['is_app']:
        result['service_active'] = active(c['service'])
        result['http'] = ready(c)
        result['health'] = ('running' if result['service_active'] and
                            result['http'] in c['codes'] else 'needs-attention')
    else:
        result['health'] = 'not-applicable'
    result['ok'] = (result['match'] == 'match' and not result['errors'] and
                    result['health'] in ('running', 'not-applicable') and
                    not any(r['status'] == 'running' for r in result['latest']))
    return result


def plan(c, sources):
    items = []
    protected = [Path(c[key]).resolve() for key in ('app', 'state', 'recv')]
    for source in sources:
        path = Path(source['path'])
        resolved = path.resolve()
        if any(resolved == parent or parent in resolved.parents for parent in protected):
            raise RuntimeError('config must not write inside APP_DIR or tk state/receiver: ' + str(path))
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RuntimeError('only regular destination files are supported: ' + str(path))
        before = None
        if path.exists():
            info = path.stat()
            before = {'mode': info.st_mode & 0o7777, 'uid': info.st_uid, 'gid': info.st_gid,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if before is None or before['sha256'] != source['sha256']:
            items.append(dict(source, action='replace' if before else 'create', before=before))
    return items


def recovery(c, record, services):
    commands = ['# Check later manual changes and operations before running these commands.']
    for item in record['files']:
        target = shlex.quote(item['path'])
        if item['action'] == 'replace':
            backup = shlex.quote(item['backup'])
            commands.append('sudo -n sh -c ' + shlex.quote(
                'if test -f ' + backup + '; then cp -p -- ' + backup + ' ' + target + '; fi'))
        else:
            commands.append('sudo -n rm -f -- ' + target)
    commands.append('sudo -n -u ' + shlex.quote(c['user']) + ' git -C ' +
                    shlex.quote(c['app']) + ' checkout --detach ' + record['prev_head'])
    if any('/etc/systemd/system/' in item['path'] for item in record['files']):
        commands.append('sudo -n systemctl daemon-reload')
    for service, action in services:
        commands.append('sudo -n systemctl ' + action + ' ' + shlex.quote(service))
    return commands


def services_for(c, items):
    services = []
    paths = [item['path'] for item in items]
    if any(p.startswith('/etc/nginx/') for p in paths) and active('nginx'):
        services.append(('nginx', 'reload'))
    if any(p.startswith('/etc/mysql/') for p in paths) and active('mysql'):
        services.append(('mysql', 'restart'))
    for path in paths:
        if path.startswith('/etc/systemd/system/') and path.endswith('.service'):
            name = Path(path).name
            if name != c['service'] and active(name):
                services.append((name, 'restart'))
    return sorted(set(services))


def deploy(c):
    state = Path(c['state'])
    # The init/runbook step creates these paths; deploy never bootstraps a server.
    lock = None
    try:
        lock = (state / 'lock').open('r+')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        if lock is not None:
            lock.close()
        try:
            owner = json.loads((state / 'lock.json').read_text())
        except (OSError, ValueError):
            owner = 'unconfirmed'
        return {'result': 'refused', 'step': 'lock', 'last_lock_record': owner}, 3
    record = {'op_id': c['op_id'], 'task': 'deploy', 'actor': c['actor'], 'sha': c['sha'],
              'started_at': utc(), 'step': 'lock', 'status': 'running',
              'files': [], 'recovery': []}
    path = state / 'ops' / (c['op_id'] + '.json')
    changed = False
    try:
        if path.exists():
            return {'result': 'refused', 'step': 'lock', 'error': 'operation ID already exists'}, 3
        atomic(state / 'lock.json', {k: record[k] for k in ('op_id', 'actor', 'started_at')})
        atomic(path, record)

        def step(name):
            record['step'] = name
            atomic(path, record)

        step('prepare')
        if git(c, 'status', '--porcelain'):
            raise RuntimeError('uncommitted changes; preserve them before deploy')
        if run(['systemctl', 'is-enabled', c['service']], check=False).returncode:
            raise RuntimeError('APP_SERVICE is disabled; enable intentionally before deploy')
        record['prev_head'] = git(c, 'rev-parse', 'HEAD').decode().strip()
        git(c, 'fetch', '--no-tags', c['recv'], 'refs/tk/incoming/' + c['op_id'])
        fetched = git(c, 'rev-parse', 'FETCH_HEAD').decode().strip()
        if fetched != c['sha']:
            raise RuntimeError('fetched SHA differs from requested SHA')
        # Source paths/hashes were resolved once from the controller's commit tree.
        for source in c['sources']:
            data = git(c, 'show', c['sha'] + ':' + source['source'])
            if hashlib.sha256(data).hexdigest() != source['sha256']:
                raise RuntimeError('source hash differs: ' + source['source'])
        record['files'] = plan(c, c['sources'])
        for item in record['files']:
            item['backup'] = str(state / 'ops' / c['op_id'] / 'backup' / item['path'].lstrip('/'))
        services = services_for(c, record['files'])
        app_was_active = active(c['service'])
        restore_services = services + [(c['service'], 'restart' if app_was_active else 'stop')]
        record['recovery'] = recovery(c, record, restore_services)
        atomic(path, record)
        step('backup')
        for item in record['files']:
            if item['action'] == 'replace':
                backup = Path(item['backup'])
                backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                temporary = backup.with_name(backup.name + '.tmp')
                shutil.copy2(item['path'], temporary)
                os.chown(temporary, item['before']['uid'], item['before']['gid'])
                temporary.chmod(item['before']['mode'])
                os.replace(temporary, backup)
        step('apply')
        changed = True  # From here a lost reply may mean live state changed.
        git(c, 'checkout', '--detach', c['sha'])
        for item in record['files']:
            target = Path(item['path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git(c, 'show', c['sha'] + ':' + item['source']))
            if item['action'] == 'create':
                target.chmod(item['mode'])
        step('restart')
        if any(p['path'].startswith('/etc/systemd/system/') for p in record['files']):
            run(['systemctl', 'daemon-reload'])
        for service, action in services:
            if service == 'nginx':
                run(['nginx', '-t'])
            run(['systemctl', action, service], timeout=120)
        if c['build']:
            result = run(['sudo', '-n', '-u', c['user'], 'bash', '-lc',
                          'cd -- ' + shlex.quote(c['app']) + ' && ' + c['build']],
                         check=False, timeout=c.get('build_timeout', 600))
            sys.stderr.buffer.write(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError('build command failed: ' + str(result.returncode))
        run(['systemctl', 'restart', c['service']], timeout=120)
        step('ready')
        deadline = time.monotonic() + c['ready_timeout']
        while time.monotonic() < deadline:
            code = ready(c, timeout=max(0.1, min(2, deadline - time.monotonic())))
            if code in c['codes'] and active(c['service']):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('ready timeout; last HTTP status: ' + str(code))
        record.update(step='done', status='ok', ended_at=utc())
        atomic(path, record)
        return {'result': 'ok', 'step': 'done', 'record': record}, 0
    except Exception as error:
        record.update(status='failed', ended_at=utc(), error=str(error))
        try:
            atomic(path, record)
        except OSError:
            pass
        return {'result': 'failed' if changed or record['step'] == 'backup' else 'refused',
                'step': record['step'], 'error': str(error), 'record': record}, 1 if changed or record['step'] == 'backup' else 3
    finally:
        lock.close()


def main():
    action = sys.argv[1]
    c = json.loads(base64.b64decode(sys.argv[2]))
    if action == 'status':
        print(json.dumps(status(c), ensure_ascii=False))
        return 0
    if action == 'plan':
        print(json.dumps({'files': plan(c, c['sources'])}, ensure_ascii=False))
        return 0
    result, code = deploy(c)
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        sys.exit(1)

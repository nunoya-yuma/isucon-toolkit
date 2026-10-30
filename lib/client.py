"""Controller side: fixed commit, SSH transport, local manifests and display."""
import argparse
import base64
import concurrent.futures
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def config():
    required = ('TK_HOSTS', 'TK_ROLE_app', 'APP_DIR', 'APP_USER', 'APP_SERVICE', 'READY_URL')
    for key in required:
        if not os.environ.get(key, '').strip():
            raise ValueError(key + ' is required')
    hosts = os.environ['TK_HOSTS'].split()
    apps = os.environ['TK_ROLE_app'].split()
    if len(set(hosts)) != len(hosts) or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', h) for h in hosts):
        raise ValueError('host names must be unique SSH aliases (letters, digits, dot, underscore, hyphen)')
    if not set(apps) <= set(hosts):
        raise ValueError('TK_ROLE_app contains an unknown host')
    user, service = os.environ['APP_USER'], os.environ['APP_SERVICE']
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', user) or not re.fullmatch(r'[a-zA-Z0-9_.@-]+', service):
        raise ValueError('invalid APP_USER or APP_SERVICE')
    app = os.environ['APP_DIR']
    if not Path(app).is_absolute() or app in ('/', '/etc', '/home', '/var') or '\n' in app:
        raise ValueError('APP_DIR must be a specific absolute application directory')
    timeout = int(os.environ.get('READY_TIMEOUT', '60'))
    codes = [int(code) for code in os.environ.get('READY_CODES', '200').split()]
    if timeout <= 0 or not codes or any(not 100 <= code <= 599 for code in codes):
        raise ValueError('invalid READY_TIMEOUT or READY_CODES')
    return {'hosts': hosts, 'apps': apps, 'app': app, 'user': user, 'service': service,
            'build': os.environ.get('BUILD_CMD', ''), 'ready_url': os.environ['READY_URL'],
            'ready_host': os.environ.get('READY_HOST', ''), 'codes': codes,
            'ready_timeout': timeout, 'state': '/var/lib/tk', 'recv': '/var/lib/tk-recv.git'}


def targets(names, c, default):
    expanded = []
    for name in names or default:
        expanded.extend(c['apps'] if name == '@app' else [name])
    if not expanded or any(name not in c['hosts'] for name in expanded):
        raise ValueError('target must be a configured host or @app')
    return list(dict.fromkeys(expanded))


def ssh(host, command, *, body=None, timeout=30):
    return run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', host, command],
               input=body, timeout=timeout)


def remote(host, action, c, timeout):
    payload = base64.b64encode(json.dumps(c).encode()).decode()
    # bash -s receives quoted arguments; the helper exists only on stdin, not on disk.
    command = 'bash -s -- ' + ' '.join(shlex.quote(v) for v in (action, payload))
    body = ('set -euo pipefail\nsudo -n python3 - "$1" "$2" <<\'TK_REMOTE_PY\'\n' +
            (HERE / 'remote.py').read_text() + '\nTK_REMOTE_PY\n')
    result = ssh(host, command, body=body, timeout=timeout)
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError('remote result unavailable (SSH exit ' + str(result.returncode) + ')')
    return result.returncode, data


def sources(sha, host, project):
    result = run(['git', 'ls-tree', '-rz', '--full-tree', sha, '--', 'server', 'hosts/' + host], cwd=project)
    if result.returncode:
        raise RuntimeError(result.stderr)
    by_path = {}
    entries = result.stdout.split('\0')
    # Shared first; per-host files override exactly one destination.
    entries.sort(key=lambda entry: ('\thosts/' in entry, entry))
    for entry in entries:
        if not entry:
            continue
        info, source = entry.split('\t', 1)
        mode, kind, _ = info.split()
        prefix = 'server/' if source.startswith('server/') else 'hosts/' + host + '/'
        relative = source[len(prefix):]
        if kind != 'blob' or mode not in ('100644', '100755') or '..' in Path(relative).parts:
            raise ValueError('only regular config files with safe paths are supported: ' + source)
        content = subprocess.check_output(['git', 'show', sha + ':' + source], cwd=project)
        by_path['/' + relative] = {'path': '/' + relative, 'source': source,
                                   'sha256': hashlib.sha256(content).hexdigest(),
                                   'mode': 0o755 if mode == '100755' else 0o644}
    return [by_path[path] for path in sorted(by_path)]


def manifest_path(project, op_id):
    directory = Path(project) / 'runs'
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / (op_id + '.json')


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def publish(input_ref, sha, project):
    branch = input_ref[len('refs/heads/'):] if input_ref.startswith('refs/heads/') else input_ref
    is_branch = run(['git', 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch], cwd=project).returncode == 0
    if is_branch:
        head = run(['git', 'ls-remote', '--symref', 'origin', 'HEAD'], cwd=project, timeout=60)
        defaults = [line.split()[1] for line in head.stdout.splitlines() if line.startswith('ref: ')]
        if head.returncode or len(defaults) != 1:
            return False  # Do not guess the default branch and accidentally push to it.
        if 'refs/heads/' + branch != defaults[0]:
            # Push the resolved SHA, not a branch that might have advanced meanwhile.
            return run(['git', 'push', 'origin', sha + ':refs/heads/' + branch],
                       cwd=project, timeout=60).returncode == 0
        fetched = run(['git', 'fetch', '--quiet', '--no-tags', 'origin',
                       '+' + defaults[0] + ':refs/remotes/origin/' + branch], cwd=project, timeout=60)
        return fetched.returncode == 0 and run(
            ['git', 'merge-base', '--is-ancestor', sha, 'refs/remotes/origin/' + branch],
            cwd=project).returncode == 0
    fetched = run(['git', 'fetch', '--quiet', '--no-tags', '--prune', 'origin'], cwd=project, timeout=60)
    if fetched.returncode:
        return False
    containing = run(['git', 'for-each-ref', '--contains', sha, '--format=%(refname)',
                      'refs/remotes/origin/'], cwd=project)
    return any(ref != 'refs/remotes/origin/HEAD' for ref in containing.stdout.splitlines())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('task', choices=['status', 'deploy'])
    parser.add_argument('--detail', action='store_true')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('args', nargs='*')
    args = parser.parse_intermixed_args()
    c = config()
    project = os.environ['TK_PROJECT_ROOT']
    op_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + args.task + '-' + secrets.token_hex(2)
    c['op_id'] = op_id
    actor = os.environ.get('TK_ACTOR') or run(['git', 'config', 'user.name'], cwd=project).stdout.strip()
    c['actor'] = actor + ('@' + os.uname().nodename if not os.environ.get('TK_ACTOR') else '')
    manifest = {'op_id': op_id, 'task': args.task, 'actor': c['actor'],
                'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'results': {}}
    path = manifest_path(project, op_id)
    if args.task == 'status':
        if args.plan:
            raise ValueError('status has no --plan option')
        selected = targets(args.args, c, c['hosts'])

        def observe(host):
            host_c = dict(c, host=host, is_app=host in c['apps'])
            try:
                _, data = remote(host, 'status', host_c, 10)
                if 'ok' not in data:
                    raise RuntimeError(data.get('error', 'invalid status reply'))
                return host, data
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                return host, {'ok': False, 'errors': [str(error)], 'match': 'unconfirmed'}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(selected)) as pool:
            manifest['results'] = dict(pool.map(observe, selected))
        print('HOST  CHECKOUT  BRANCH  DIRTY  LAST DEPLOY  MATCH  HEALTH  LAST OPERATION (record only)')
        for host, data in manifest['results'].items():
            operations = ','.join(r['op_id'] + ':' + r['step'] + ':' + r['status'] for r in data.get('latest', [])) or '-'
            last_sha = ','.join(r.get('sha', '?')[:12] for r in data.get('last_deploy', [])) or 'no-record'
            health = data.get('health', '?')
            if 'http' in data:
                health += '(' + ('active' if data['service_active'] else 'inactive') + '/' + str(data['http']) + ')'
            print(host, data.get('head', '?')[:12], data.get('branch', '?'),
                  data.get('dirty', '?'), last_sha, data['match'], health, operations)
            if args.detail:
                print(json.dumps(data, ensure_ascii=False, indent=2))
        code = 0 if all(data['ok'] for data in manifest['results'].values()) else 1
    else:
        if args.detail or not args.args:
            raise ValueError('deploy requires a commit or branch')
        selected = targets(args.args[1:], c, ['@app'])
        if len(selected) != 1 or selected[0] not in c['apps']:
            raise ValueError('initial deploy supports exactly one @app host')
        host = selected[0]
        resolved = run(['git', 'rev-parse', '--verify', '--end-of-options', args.args[0] + '^{commit}'], cwd=project)
        if resolved.returncode:
            raise ValueError('cannot resolve commit: ' + args.args[0])
        sha = resolved.stdout.strip()
        manifest.update(input=args.args[0], sha=sha, targets=selected)
        c.update(host=host, sha=sha, sources=sources(sha, host, project))
        if args.plan:
            _, data = remote(host, 'plan', c, 30)
            if 'files' not in data:
                raise RuntimeError(data.get('error', 'plan unavailable'))
            print(json.dumps(data, ensure_ascii=False, indent=2))
            print('tk deploy ' + op_id + ' plan sha=' + sha[:12] + ' ' + host + '=read-only')
            return 0
        save(path, manifest)
        try:
            manifest['github'] = 'confirmed' if publish(args.args[0], sha, project) else 'unconfirmed'
        except (OSError, subprocess.TimeoutExpired):
            manifest['github'] = 'unconfirmed'
        if manifest['github'] == 'unconfirmed':
            print('NG: publish unconfirmed; continuing with SSH delivery', file=sys.stderr)
        check = ('set -eu; sudo -n true; command -v python3 >/dev/null; '
                 'command -v flock >/dev/null; sudo -n test -d /var/lib/tk/ops; '
                 'sudo -n test -f /var/lib/tk/lock; sudo -n -u ' + shlex.quote(c['user']) +
                 ' test -w /var/lib/tk-recv.git')
        result = {'result': 'refused', 'step': 'check'}
        try:
            checked = ssh(host, check, timeout=15)
            if checked.returncode:
                result['error'] = checked.stderr.strip()
                code = 3
            else:
                receiver = 'sudo -n -u ' + shlex.quote(c['user']) + ' git-receive-pack'
                sent = run(['git', 'push', '--receive-pack=' + receiver,
                            host + ':' + c['recv'], sha + ':refs/tk/incoming/' + op_id],
                           cwd=project, timeout=120)
                if sent.returncode:
                    result = {'result': 'refused', 'step': 'send', 'error': sent.stderr.strip()}
                    code = 3
                else:
                    result = {'result': 'unknown', 'step': 'remote'}
                    save(path, dict(manifest, results={host: result}))
                    _, result = remote(host, 'deploy', c, 900)
                    if 'result' not in result:
                        result = dict(result, result='unknown', step='remote')
                    code = {'ok': 0, 'refused': 3, 'failed': 1}.get(result.get('result'), 1)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            result['error'] = str(error)
            code = 1 if result['result'] == 'unknown' else 3
        manifest['results'][host] = result
        if result.get('error'):
            print('NG: ' + host + '@' + result.get('step', '?') + ': ' + result['error'], file=sys.stderr)
    manifest['exit_code'] = code
    save(path, manifest)
    summary = ' '.join(host + '=' + (('ok' if data.get('ok') else 'unconfirmed') if args.task == 'status'
                        else data.get('result', 'unknown') + '@' + data.get('step', '?'))
                       for host, data in manifest['results'].items())
    extra = (' sha=' + manifest['sha'][:12] + ' github=' + manifest['github']) if 'sha' in manifest else ''
    print('tk ' + args.task + ' ' + op_id + extra + ' ' + summary)
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print('NG: ' + str(error), file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, subprocess.SubprocessError) as error:
        print('NG: ' + str(error), file=sys.stderr)
        sys.exit(1)

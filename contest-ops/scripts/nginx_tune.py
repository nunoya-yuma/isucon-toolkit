#!/usr/bin/env python3
"""Apply selected nginx directives with validation, backups and recovery.

Uses only the Python standard library. Does not execute isuginx or edit includes.
"""
import argparse
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


ALLOWED = {
    'main': {'worker_processes', 'worker_rlimit_nofile'},
    'events': {'worker_connections'},
    'http': {'sendfile', 'tcp_nopush', 'tcp_nodelay', 'types_hash_max_size',
             'server_tokens', 'keepalive_timeout', 'keepalive_requests',
             'open_file_cache', 'proxy_buffers', 'proxy_buffer_size'},
}


def tokens(text):
    """Tokenize while retaining byte-independent string offsets and comments."""
    result = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text[i] == '#':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end + 1
        elif text[i] in '{};':
            result.append((text[i], i, i + 1))
            i += 1
        else:
            start = i
            quote = None
            while i < len(text):
                char = text[i]
                if char == '\\':
                    i += 2
                    continue
                if quote:
                    if char == quote:
                        quote = None
                    i += 1
                elif char in "\"'":
                    quote = char
                    i += 1
                elif text.startswith('${', i):
                    end = text.find('}', i + 2)
                    if end < 0:
                        raise ValueError('Unterminated nginx variable')
                    i = end + 1
                elif char.isspace() or char in '{};#':
                    break
                else:
                    i += 1
            if quote or i > len(text):
                raise ValueError('Unterminated quote or escape in nginx config')
            result.append((text[start:i], start, i))
    return result


def render(text, settings):
    """Modify only direct directives in the selected main/events/http scopes."""
    for scope, directives in settings.items():
        if scope not in ALLOWED or not isinstance(directives, dict):
            raise ValueError('Unsupported directive scope: ' + scope)
        for name, value in directives.items():
            if name not in ALLOWED[scope]:
                raise ValueError('Unsupported directive: ' + scope + '.' + name)
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_= .:]+', value) or not value.strip():
                raise ValueError('Directive values must be simple, nonempty strings: ' + name)

    stack = []
    pending = []
    nodes = []
    blocks = []
    for token in tokens(text):
        value, start, end = token
        if value == '{':
            if not pending:
                raise ValueError('Unexpected block opening')
            stack.append((pending[0][0], tuple(item[0] for item in stack), end))
            pending = []
        elif value == '}':
            if pending or not stack:
                raise ValueError('Unexpected block closing')
            name, parent, opening = stack.pop()
            blocks.append((name, parent, opening, start))
        elif value == ';':
            if not pending:
                raise ValueError('Unexpected semicolon')
            nodes.append((tuple(item[0] for item in stack), pending, end))
            pending = []
        else:
            pending.append(token)
    if pending or stack:
        raise ValueError('Incomplete nginx configuration')

    replacements = []
    for scope, directives in settings.items():
        if not directives:
            continue
        parent = () if scope == 'main' else (scope,)
        if scope == 'main':
            insertion = len(text)
            indent = ''
        else:
            matches = [b for b in blocks if b[0] == scope and b[1] == ()]
            if len(matches) != 1:
                raise ValueError('Expected exactly one explicit top-level ' + scope + ' block')
            insertion = matches[0][3]
            indent = '    '
        additions = []
        for name, value in directives.items():
            found = [node for node in nodes if node[0] == parent and node[1][0][0] == name]
            if len(found) > 1:
                raise ValueError('Duplicate directive in selected scope: ' + name)
            if found:
                _, parts, end = found[0]
                if ' '.join(part[0] for part in parts[1:]) != value.strip():
                    replacements.append((parts[0][1], end, name + ' ' + value.strip() + ';'))
            else:
                additions.append(indent + name + ' ' + value.strip() + ';\n')
        if additions:
            replacements.append((insertion, insertion, '\n' + ''.join(additions)))
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(argv):
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
        raise ValueError('Commands must be nonempty argv lists')
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Command failed: ' + repr(argv) + '\n' + result.stdout + result.stderr)
    return result.stdout + result.stderr


def write_private(path, data):
    with path.open('xb') as output:
        os.chmod(path, 0o600)
        output.write(data)


def staged(path, data, metadata):
    fd, name = tempfile.mkstemp(prefix='.contest-ops-nginx-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fchmod(output.fileno(), metadata.st_mode & 0o7777)
            if (os.geteuid(), os.getegid()) != (metadata.st_uid, metadata.st_gid):
                os.fchown(output.fileno(), metadata.st_uid, metadata.st_gid)
            os.fsync(output.fileno())
        return Path(name)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def activate(path, candidate, original, metadata, nginx, reload_command, health):
    target = path.resolve(strict=True)
    temporary = staged(path, candidate, metadata)
    try:
        run(nginx + ['-t', '-c', str(temporary)])
        if path.resolve(strict=True) != target or path.read_bytes() != original:
            raise RuntimeError('Config changed concurrently; refusing to overwrite')
        os.replace(temporary, target)
        try:
            run(reload_command)
            if health:
                run(health)
        except Exception as failure:
            recovery = staged(path, original, metadata)
            os.replace(recovery, target)
            try:
                run(nginx + ['-t', '-c', str(path)])
                run(reload_command)
            except Exception as recovery_failure:
                raise RuntimeError(str(failure) + '\nOriginal file restored, but recovery reload failed: ' + str(recovery_failure)) from failure
            raise RuntimeError(str(failure) + '\nOriginal file and nginx reload restored successfully') from failure
    finally:
        temporary.unlink(missing_ok=True)


def execute(action, config):
    path = Path(config['config_path']).absolute()
    if not path.is_file():
        raise ValueError('nginx configuration must be an existing file')
    root = Path(config['backup_root'])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    nginx = config.get('nginx_argv', ['nginx'])
    reload_command = config.get('reload_argv', ['systemctl', 'reload', 'nginx'])
    health = config.get('health_argv', [])
    identifier = config['run_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
        raise ValueError('Invalid run identifier')
    with (root / '.lock').open('a') as lock:
        os.chmod(root / '.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = path.read_bytes()
        metadata = path.stat()
        directory = root / identifier
        directory.mkdir(mode=0o700)
        write_private(directory / 'original.conf', original)
        # Save the original first, then test the effective configuration.
        effective = run(nginx + ['-T', '-c', str(path)])
        write_private(directory / 'effective-before.txt', effective.encode())
        if action == 'restore':
            restore_id = config['restore_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', restore_id):
                raise ValueError('Invalid restore identifier')
            saved = root / restore_id
            manifest = json.loads((saved / 'manifest.json').read_text())
            if manifest['config_path'] != str(path) or manifest['action'] != 'apply' or manifest['state'] != 'completed':
                raise ValueError('Restore requires an apply backup for the same configuration')
            candidate = (saved / 'original.conf').read_bytes()
            if digest(candidate) != manifest['before_sha256']:
                raise ValueError('Backup checksum mismatch')
            if digest(original) not in [manifest['after_sha256'], manifest['before_sha256']]:
                raise ValueError('Config changed after that apply; refusing to overwrite newer changes')
        else:
            candidate = render(original.decode(), config.get('directives', {})).encode()
        write_private(directory / 'candidate.conf', candidate)
        difference = ''.join(difflib.unified_diff(original.decode().splitlines(True), candidate.decode().splitlines(True), fromfile=str(path), tofile='candidate'))
        write_private(directory / 'changes.diff', difference.encode())
        manifest = {'action': action, 'config_path': str(path), 'before_sha256': digest(original),
                    'after_sha256': digest(candidate), 'changed': candidate != original,
                    'state': 'prepared'}
        manifest_path = directory / 'manifest.json'
        write_private(manifest_path, json.dumps(manifest, indent=2).encode())
        try:
            if action == 'plan' or candidate == original:
                temporary = staged(path, candidate, metadata)
                try:
                    run(nginx + ['-t', '-c', str(temporary)])
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                activate(path, candidate, original, metadata, nginx, reload_command, health)
            manifest['state'] = 'validated' if action == 'plan' else 'completed'
        except Exception:
            manifest['state'] = 'failed'
            raise
        finally:
            manifest_path.write_text(json.dumps(manifest, indent=2))
        return {'changed': candidate != original and action != 'plan',
                'backup_dir': str(directory), 'diff': difference}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply', 'restore'])
    parser.add_argument('--settings', required=True)
    args = parser.parse_args()
    try:
        result = execute(args.action, json.loads(Path(args.settings).read_text()))
        print(json.dumps(result))
    except Exception as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()

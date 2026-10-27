"""Execute pre-deployed, verified probes. This module does not export or deploy models."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import uuid

from bench_common.runner import run_profile
from .planner import resolve, write_new
from .recipe import require, digest


@contextmanager
def device_lease(root, serial):
    root.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(serial.encode()).hexdigest() + '.lock'
    with (root / name).open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Device is already leased by another recipe task') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def execute(lock):
    require(lock['host_artifacts_verified'], 'A preview lock cannot execute; resolve on dog with verified artifacts')
    recipe, env = lock['recipe'], lock['environment']
    # Recheck file content at execution time to detect changes since resolution.
    resolve(recipe, env)
    backend = recipe['backend']['name']
    process = 'recipe-msl' if backend == 'msl' else 'recipe-llama'
    root = Path(env['output_root'])
    device = env['device']
    with device_lease(root / '.leases', device['serial']):
        prefix = ['python3', '-m', 'binrunner', '-t', device['serial'], '-p', device['port']]
        procs = subprocess.run(['hdc', '-t', device['serial'], 'shell', 'ps -A -o PID,COMM'],
                               check=True, capture_output=True, text=True, timeout=10).stdout
        require(not any(line.split()[-1].strip('[]') == process for line in procs.splitlines() if line.split()),
                'Existing worker detected; wait for it to exit before retrying')
        # BinRunner resolves @ paths inside the app sandbox. Fail closed if hashing
        # is unavailable or exceeds the launcher's execution limit.
        for name in ['model', 'probe']:
            artifact = env['artifacts'][name]
            evidence = root / "verification" / uuid.uuid4().hex
            evidence.mkdir(parents=True)
            check = subprocess.run(prefix + ['run', shlex.join(['sha256sum', artifact['device_path']]), '--timeout', '90'],
                                   cwd=env['binrunner'], capture_output=True, text=True, timeout=110)
            (evidence / (name + '.log')).write_text(check.stdout + '\n' + check.stderr)
            hashes = re.findall(r'(?m)^([a-f0-9]{64})\s+', check.stdout)
            require(check.returncode == 0 and hashes == [artifact['sha256']],
                    f'{name}: app sandbox SHA256 verification failed; see {evidence / (name + ".log")}. '
                    'Deploy scripts/device_tools/sha256sum.cc as sha256sum; Toybox multicall is incompatible.')
        lock = dict(lock)
        lock['device_artifacts_verified'] = True
        lock.pop('lock_sha256')
        lock['lock_sha256'] = digest(lock)
        run_id = recipe['id'] + '-' + uuid.uuid4().hex[:12]
        output = root / run_id
        profile = {'device': device['serial'], 'port': device['port'], 'binrunner': env['binrunner'],
                   'output': str(output), 'binary': env['artifacts']['probe']['device_path'],
                   'model': env['artifacts']['model']['device_path'], 'log': run_id + '.log',
                   'process': process, 'backend': backend, 'initial_wait': 70,
                   'completion': 'DESTROY status=0' if backend == 'msl' else 'DONE status=0',
                   'workload': recipe['workload'], 'backend_options': recipe['backend']['options'],
                   'command_template': lock['command_template'], 'resolved_recipe': lock}
        try:
            run_profile(profile, [])
        except Exception as error:
            output.mkdir(parents=True, exist_ok=True)
            write_new(output / 'failure.json', {'status': 'FAILED', 'error': str(error),
                                               'note': 'Detached worker may still be running; next run checks for it.'})
            raise
        return output

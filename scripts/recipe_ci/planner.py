"""Plan only from explicitly pinned recipes and verified host artifacts."""
import json
from pathlib import Path
from .recipe import require, keys, digest, sha256_file, comparison_key, validate


def resolve(recipe, environment, *, verify_files=True):
    keys(environment, ['schema_version', 'host', 'device', 'binrunner', 'output_root', 'artifacts'])
    require(environment['schema_version'] == 1, 'Unsupported environment version')
    device = environment['device']
    keys(device, ['serial', 'port', 'pool', 'soc', 'os_version'])
    require(device['pool'] == recipe['device_pool'], 'Device pool does not match recipe')
    require(all(isinstance(device[k], str) and device[k] for k in device), 'Device fields must be non-empty strings')
    if verify_files:
        require(not any(marker in device['os_version'].lower() for marker in ['replace', 'unknown']),
                'Record the actual device OS version before resolving an executable lock')
    require(device['port'].isdigit(), 'Device port must be numeric')
    for key in ['binrunner', 'output_root']:
        require(Path(environment[key]).is_absolute(), f'{key} must be absolute')
    artifacts = environment['artifacts']
    keys(artifacts, ['model', 'probe', 'runtime'])
    for name, artifact in artifacts.items():
        keys(artifact, ['host_path', 'sha256'], ['device_path'])
        require(isinstance(artifact['sha256'], str) and len(artifact['sha256']) == 64 and
                all(c in '0123456789abcdef' for c in artifact['sha256']), f'{name}: invalid SHA256')
        require(Path(artifact['host_path']).is_absolute(), f'{name}: host_path must be absolute')
        if name in ['model', 'probe']:
            path = artifact.get('device_path', '')
            require(path.startswith('@/bin/') and len(path) > 6 and
                    all(c.isalnum() or c in '@/_-.' for c in path) and '..' not in path,
                    f'{name}: device_path must be an app @/bin path')
        if verify_files:
            require(sha256_file(artifact['host_path']) == artifact['sha256'], f'{name}: host artifact checksum mismatch')
    require(artifacts['model']['sha256'] == recipe['model']['sha256'], 'Recipe/model checksum mismatch')
    if verify_files:
        require(Path(artifacts['model']['host_path']).stat().st_size == recipe['model']['bytes'], 'Model size mismatch')
    if 'sha256' in recipe['build']:
        require(artifacts['runtime']['sha256'] == recipe['build']['sha256'], 'Runtime checksum differs from pinned build')
    work = recipe['workload']
    backend = recipe['backend']['name']
    arguments = [artifacts['probe']['device_path'], artifacts['model']['device_path']]
    # Both new probes use: model repetitions logfile context input output [threads batch].
    arguments += [str(work['repetitions']), '{device_log}', str(work['context_tokens']),
                  str(work['input_tokens']), str(work['output_tokens'])]
    if backend == 'llama':
        arguments += [str(recipe['backend']['options'][k]) for k in ['threads', 'batch']]
    result = {'schema_version': 1, 'recipe': recipe, 'environment': environment,
              'recipe_sha256': digest(recipe), 'comparison_key': comparison_key(recipe),
              'device_comparison_key': digest({'recipe': comparison_key(recipe), 'device': device}),
              'host_artifacts_verified': verify_files, 'device_artifacts_verified': False,
              'command_template': arguments, 'probe_protocol': 1}
    result['lock_sha256'] = digest(result)
    return result


def load_lock(path):
    value = json.loads(Path(path).read_text())
    claimed = value.pop('lock_sha256')
    validate(value['recipe'])
    require(digest(value) == claimed, 'Lock content changed; resolve again')
    value['lock_sha256'] = claimed
    return value


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')

"""Recipe v1: frozen model, raw hello fixture, greedy generation, no warmup."""
import copy
import hashlib
import json
import re
from pathlib import Path


class RecipeError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RecipeError(message)


def keys(value, required, optional=()):
    require(isinstance(value, dict), 'Expected a JSON object')
    require(set(required) <= value.keys(), f'Missing fields: {set(required) - value.keys()}')
    require(value.keys() <= set(required) | set(optional),
            f'Unknown fields: {value.keys() - set(required) - set(optional)}')


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f'{label} must be an integer in [{low}, {high}]')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def sha256_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def validate(recipe):
    keys(recipe, ['schema_version', 'id', 'model', 'backend', 'build', 'device_pool',
                  'workload', 'measurement', 'preparation'], ['description'])
    require(type(recipe['schema_version']) is int and recipe['schema_version'] == 1, 'Unsupported schema_version')
    require(isinstance(recipe['id'], str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', recipe['id']), 'Invalid recipe id')
    model = recipe['model']
    keys(model, ['name', 'variant', 'sha256', 'bytes', 'context_tokens', 'quantization', 'provenance'])
    require(isinstance(model['name'], str) and bool(model['name']), 'Model name is required')
    require(model['variant'] in ['base', 'instruct'], 'Specify base/instruct variant')
    require(isinstance(model['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', model['sha256']), 'Invalid model SHA256')
    integer(model['bytes'], 1, 10**12, 'model.bytes')
    integer(model['context_tokens'], 2, 131072, 'model.context_tokens')
    require(isinstance(model['quantization'], dict) and bool(model['quantization']), 'Quantization parameters are required')
    require(isinstance(model['provenance'], dict), 'Model provenance must be an object')
    backend = recipe['backend']
    keys(backend, ['name', 'target', 'options'])
    require((backend['name'], backend['target']) in [('msl', 'npu'), ('llama', 'cpu')], 'Unsupported backend/target')
    keys(backend['options'], [] if backend['name'] == 'msl' else ['threads', 'batch'])
    if backend['name'] == 'llama':
        integer(backend['options']['threads'], 1, 32, 'threads')
        integer(backend['options']['batch'], 1, 4096, 'batch')
    keys(recipe['build'], ['commit'], ['source_url', 'sha256', 'components'])
    require(isinstance(recipe['build']['commit'], str) and re.fullmatch(r'[0-9a-f]{40}', recipe['build']['commit']),
            'build.commit must be pinned, not daily/latest')
    if 'sha256' in recipe['build']:
        require(bool(re.fullmatch(r'[0-9a-f]{64}', recipe['build']['sha256'])), 'Invalid build SHA256')
    if 'components' in recipe['build']:
        require(isinstance(recipe['build']['components'], dict), 'Build components must be an object')
        for commit in recipe['build']['components'].values():
            require(isinstance(commit, str) and bool(re.fullmatch(r'[0-9a-f]{40}', commit)), 'Component commits must be pinned')
    require(recipe['preparation'] == 'frozen_model', 'v1 supports frozen_model only')
    require(isinstance(recipe['device_pool'], str) and bool(recipe['device_pool']), 'Missing device pool')
    work = recipe['workload']
    keys(work, ['context_tokens', 'input_tokens', 'output_tokens', 'repetitions', 'warmup_runs',
                'generation', 'prompt', 'input_verification'])
    integer(work['context_tokens'], 2, 131072, 'context_tokens')
    integer(work['input_tokens'], 1, 131071, 'input_tokens')
    integer(work['output_tokens'], 2, 131071, 'output_tokens')
    integer(work['repetitions'], 2, 100, 'repetitions')
    require(work['input_tokens'] + work['output_tokens'] <= work['context_tokens'], 'Token budget exceeds context')
    require(work['context_tokens'] == model['context_tokens'], 'Frozen model context must match workload')
    require(work['warmup_runs'] == 0 and work['generation'] == 'greedy', 'v1 supports greedy/no warmup only')
    require(work['prompt'] == 'hello-repeat-v1', 'Unsupported prompt fixture')
    keys(work['input_verification'], ['model_sha256', 'tokens', 'evidence'])
    verification = work['input_verification']
    require(verification['model_sha256'] == model['sha256'] and verification['tokens'] == work['input_tokens'],
            'Input verification must match exact model and token count')
    require(isinstance(verification['evidence'], str) and bool(verification['evidence']), 'Input verification evidence is required')
    measure = recipe['measurement']
    keys(measure, ['version', 'collector', 'stable_runs'])
    require(measure['version'] == 1 and measure['collector'] == 'hidumper', 'Unsupported measurement protocol')
    require(measure['stable_runs'] == list(range(2, work['repetitions'] + 1)), 'v1 stable runs must be runs 2..N')
    return recipe


def load(path):
    return validate(json.loads(Path(path).read_text()))


def comparison_key(recipe):
    """Build is deliberately excluded: it is the version under test."""
    fields = ['schema_version', 'model', 'backend', 'device_pool', 'workload', 'measurement', 'preparation']
    identity = {key: copy.deepcopy(recipe[key]) for key in fields}
    # Descriptive source locations do not affect numerical comparability.
    identity['model'].pop('provenance')
    identity['workload']['input_verification'].pop('evidence')
    return digest(identity)

"""One kanban result format for all recipe-compatible probes."""
import json
from datetime import datetime, timezone
from pathlib import Path
from bench_common.metrics import read_memory, summarize, validate_rows, write_csv
from .recipe import require, digest, comparison_key


def validate_spec(log, workload, options):
    declarations = [json.loads(line[5:]) for line in log.splitlines() if line.startswith('SPEC ')]
    require(len(declarations) == 1, 'Probe must report exactly one SPEC event')
    actual = declarations[0]
    require(actual.get('protocol_version') == 1, 'Unsupported probe protocol')
    for field in ['context_tokens', 'input_tokens', 'output_tokens', 'repetitions']:
        require(actual.get(field) == workload[field], f'Probe SPEC mismatch: {field}')
    for field, value in options.items():
        require(actual.get(field) == value, f'Probe option mismatch: {field}')


def summarize_recipe(recipe, directory, *, legacy=False, log_name='inference.log',
                     samples_name='samples.json', memory_pattern='memory-*.txt', run_id=None):
    directory = Path(directory)
    work = recipe['workload']
    backend = recipe['backend']['name']
    rows = json.loads((directory / samples_name).read_text())
    log = (directory / log_name).read_text()
    validate_rows(rows, backend, work['repetitions'], work['input_tokens'], work['output_tokens'])
    if not legacy:
        validate_spec(log, work, recipe['backend']['options'])
    memory = read_memory(directory, log, rows, memory_pattern, skip_invalid=False)
    timing, stats = summarize(rows, memory)
    stats.update(stable_definition='Complete samples within decode runs 2..N; device clock aligned',
                 peak_scope='Observed samples only; short peaks may be missed',
                 measurement_version=recipe['measurement']['version'])
    result = {
        'schema_version': 1, 'id': run_id or recipe['id'] + '-' + digest(rows)[:12],
        'date': datetime.fromtimestamp(memory[0]['start_epoch_ms'] / 1000, timezone.utc).date().isoformat(),
        'recipe_id': recipe['id'],
        'recipe_sha256': digest(recipe), 'comparison_key': comparison_key(recipe),
        'framework': 'MSL-LLM NPU' if backend == 'msl' else 'llama.cpp CPU',
        'build_commit': recipe['build']['commit'],
        'spec': {'model': recipe['model']['name'], 'quantization': json.dumps(recipe['model']['quantization'], sort_keys=True),
                 'soc': recipe['device_pool'], 'context': work['context_tokens'],
                 'input_tokens': work['input_tokens'], 'output_tokens': work['output_tokens'],
                 'consecutive_runs': work['repetitions'], 'between_runs_wait_seconds': 0,
                 'warmup_in_this_process': work['warmup_runs']},
        'model': recipe['model'], 'timing': timing, 'memory': stats,
        'samples': rows, 'memory_samples': memory,
        'latency_p90_method': 'nearest-rank; max for n=5',
        'input_tokens_source': 'runtime-tokenizer' if backend == 'llama' else 'recipe-verification-evidence',
        'source': 'legacy archive import' if legacy else 'recipe run',
        'baseline_eligible': False,
        'verification': {'probe_spec': not legacy, 'artifact_identity': False, 'environment_qualified': False},
        'protocol_note': 'Raw hello fixture; greedy; consecutive runs; total PSS includes Graph. '
                         'Baseline approval and environment qualification are separate steps.',
    }
    lock_path = directory / 'resolved-recipe.json'
    if lock_path.exists() and not legacy:
        from .planner import load_lock
        lock = load_lock(lock_path)
        require(lock['recipe_sha256'] == digest(recipe), 'Recipe differs from run lock')
        result['verification']['artifact_identity'] = lock['device_artifacts_verified']
        result['device_comparison_key'] = lock['device_comparison_key']
        result['device'] = lock['environment']['device']['serial']
    write_csv(directory, rows, memory)
    return result

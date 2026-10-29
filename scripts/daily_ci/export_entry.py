"""Run unmodified daily exporter and verify the exact raw prompt tokenizer first."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python-target', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--input-tokens', required=True, type=int)
    args, export_args = parser.parse_known_args()
    import mslite_llm_export as exporter
    import mslite_llm_ops as operators
    for module in [exporter, operators]:
        if not Path(module.__file__).resolve().is_relative_to(args.python_target.resolve()):
            raise RuntimeError('Daily module resolved outside isolated tool directory')
    options = exporter.build_parser().parse_args(export_args)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(options.model, local_files_only=True, trust_remote_code=False)
    ids = tokenizer.encode(' hello' * args.input_tokens, add_special_tokens=False)
    if len(ids) != args.input_tokens:
        raise RuntimeError('Source tokenizer does not match requested input token count')
    args.evidence.write_text(json.dumps({'input_tokens': len(ids), 'prompt': 'hello-repeat-v1',
                                        'add_special_tokens': False, 'token_ids': sorted(set(ids))}, indent=2) + '\n')
    with args.evidence.with_name('python-packages.txt').open('w') as stream:
        subprocess.run([sys.executable, '-m', 'pip', 'freeze'], stdout=stream, check=True)
    sys.argv = ['mslite-llm-export', *export_args]
    exporter.main()


if __name__ == '__main__':
    main()

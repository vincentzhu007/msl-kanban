#!/usr/bin/env python3
"""Run a daily evaluation and prepare public result/status files for Git publication."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from daily_ci.pipeline import run

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--recipe', default='recipes/qwen25-05b-msl-w4a16-kirin9020.json', type=Path)
    parser.add_argument('--date', default=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d'))
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        datetime.strptime(args.date, '%Y%m%d')
        if len(args.date) != 8 or not args.date.isdigit():
            raise ValueError('Use YYYYMMDD')
    except ValueError as error:
        parser.error(str(error))
    repo = Path(__file__).resolve().parents[1]
    raise SystemExit(run(repo, repo / args.recipe, json.loads(args.config.read_text()), args.date, args.force))

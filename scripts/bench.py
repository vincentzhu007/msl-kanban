#!/usr/bin/env python3
"""Recipe entrypoint. validate/resolve/summarize are offline; run requires dog devices."""
import argparse
import json
from pathlib import Path
import sys

from recipe_ci.recipe import load, RecipeError
from recipe_ci.planner import resolve, load_lock, write_new
from recipe_ci.results import summarize_recipe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('validate', help='Validate recipe protocol and capabilities')
    check.add_argument('recipe', type=Path)
    plan = commands.add_parser('resolve', help='Create an immutable lock from recipe and environment')
    plan.add_argument('recipe', type=Path)
    plan.add_argument('--environment', required=True, type=Path)
    plan.add_argument('--output', required=True, type=Path)
    plan.add_argument('--preview', action='store_true', help='Do not hash host files; lock cannot execute')
    run = commands.add_parser('run', help='Verify pre-deployed model/probe and collect measurements')
    run.add_argument('--lock', required=True, type=Path)
    summary = commands.add_parser('summarize', help='Generate one dashboard result for any recipe')
    summary.add_argument('recipe', type=Path)
    summary.add_argument('results', type=Path)
    summary.add_argument('--output', required=True, type=Path)
    summary.add_argument('--legacy', action='store_true', help='Explicit import without probe SPEC; cannot become a baseline automatically')
    summary.add_argument('--log', default='inference.log')
    summary.add_argument('--samples', default='samples.json')
    summary.add_argument('--memory-pattern', default='memory-*.txt')
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            from recipe_ci.execution import execute
            lock = load_lock(args.lock)
            output = execute(lock)
            result = summarize_recipe(lock['recipe'], output)
            write_new(output / 'dashboard-result.json', result)
            print(output)
            return
        recipe = load(args.recipe)
        if args.command == 'validate':
            print(f"VALID {recipe['id']}")
        elif args.command == 'resolve':
            environment = json.loads(args.environment.read_text())
            write_new(args.output, resolve(recipe, environment, verify_files=not args.preview))
            print(args.output)
        else:
            result = summarize_recipe(recipe, args.results, legacy=args.legacy, log_name=args.log,
                                      samples_name=args.samples, memory_pattern=args.memory_pattern)
            write_new(args.output, result)
            print(args.output)
    except (RecipeError, ValueError, OSError, KeyError) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()

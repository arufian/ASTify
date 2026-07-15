#!/usr/bin/env python3
"""Quick run: python run.py /path/to/dir [--model all-MiniLM-L6-v2]"""
import sys
import json
from pathlib import Path

_parent = Path(__file__).resolve().parent
sys.path.insert(0, str(_parent))

from astify.extract import run_extraction


def _parse_args():
    directory = '.'
    model = 'all-MiniLM-L6-v2'
    threshold = 0.72
    output = None
    astify = None
    quiet = False

    args = sys.argv[1:]

    def _value(i, flag):
        if i + 1 >= len(args):
            sys.exit(f'ERROR: {flag} requires a value')
        return args[i + 1]

    i = 0
    while i < len(args):
        if args[i] in ('-m', '--model'):
            model = _value(i, args[i])
            i += 1
        elif args[i] in ('-t', '--threshold'):
            try:
                threshold = float(_value(i, args[i]))
            except ValueError:
                sys.exit(f'ERROR: {args[i]} expects a number')
            i += 1
        elif args[i] in ('-o', '--output'):
            output = _value(i, args[i])
            i += 1
        elif args[i] == '--astify-path':
            astify = _value(i, args[i])
            i += 1
        elif args[i] in ('-q', '--quiet'):
            quiet = True
        elif not args[i].startswith('-'):
            directory = args[i]
        else:
            sys.exit(f'ERROR: unknown flag {args[i]}')
        i += 1

    return directory, model, threshold, output, astify, quiet


if __name__ == '__main__':
    directory, model, threshold, output, astify, quiet = _parse_args()

    result = run_extraction(
        directory=directory,
        model_name=model,
        sim_threshold=threshold,
        verbose=not quiet,
    )

    if astify:
        out_path = Path(astify)
    elif output:
        out_path = Path(output)
    else:
        out_path = Path(directory).resolve() / '.astify_semantic.json'

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    if not quiet:
        print(f'Saved: {out_path}')

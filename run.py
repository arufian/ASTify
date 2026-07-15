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
    i = 0
    while i < len(args):
        if args[i] in ('-m', '--model'):
            i += 1
            model = args[i]
        elif args[i] in ('-t', '--threshold'):
            i += 1
            threshold = float(args[i])
        elif args[i] in ('-o', '--output'):
            i += 1
            output = args[i]
        elif args[i] == '--astify-path':
            i += 1
            astify = args[i]
        elif args[i] in ('-q', '--quiet'):
            quiet = True
        elif not args[i].startswith('-'):
            directory = args[i]
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

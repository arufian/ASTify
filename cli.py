import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description='EmbedGraph — embedding-based knowledge graph extraction '
                    '(ASTify-compatible, zero AI tokens)',
    )
    parser.add_argument(
        'directory', nargs='?', default='.',
        help='Directory to scan for documents (default: current directory)',
    )
    parser.add_argument(
        '-o', '--output', default=None,
        help='Output JSON file path (default: .embedgraph_semantic.json in scanned dir)',
    )
    parser.add_argument(
        '-m', '--model', default='all-MiniLM-L6-v2',
        help='Sentence-transformer model name (default: all-MiniLM-L6-v2)',
    )
    parser.add_argument(
        '-t', '--threshold', type=float, default=0.72,
        help='Cosine similarity threshold for edges (default: 0.72)',
    )
    parser.add_argument(
        '--astify-path', default=None,
        help='Output directly to ASTify-compatible path '
             '(e.g., astify-out/.astify_semantic.json)',
    )
    parser.add_argument(
        '-q', '--quiet', action='store_true',
        help='Suppress progress output',
    )
    args = parser.parse_args()

    from .extract import run_extraction

    result = run_extraction(
        directory=args.directory,
        model_name=args.model,
        sim_threshold=args.threshold,
        verbose=not args.quiet,
    )

    # Determine output path
    if args.astify_path:
        out_path = Path(args.astify_path)
    elif args.output:
        out_path = Path(args.output)
    else:
        root = Path(args.directory).resolve()
        out_path = root / '.astify_semantic.json'

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )

    if not args.quiet:
        print(f'\nOutput written to: {out_path}')


if __name__ == '__main__':
    main()

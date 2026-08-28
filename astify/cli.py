#!/usr/bin/env python3
"""ASTify CLI — AST + embedding knowledge graphs, zero AI tokens."""
import argparse
import json
import sys
from pathlib import Path


COMMANDS = {
    'run', 'detect', 'extract', 'build', 'report', 'html', 'query', 'path',
    'explain',
}


def _normalize_argv(argv: list[str]) -> list[str]:
    """Treat a bare directory argument as the advertised full pipeline."""
    if argv and argv[0] not in COMMANDS and not argv[0].startswith('-'):
        return ['run', *argv]
    return argv


def cmd_detect(args):
    from astify.detect import detect_all

    root = Path(args.directory).resolve()
    info = detect_all(root)

    if not args.quiet:
        print(f"Corpus: {info['total_files']} files · "
              f"~{info['total_words']:,} words")
        for cat, key in [('code', 'code_files'), ('docs', 'doc_files')]:
            n = info[key]
            if n:
                print(f'  {cat}:     {n} files')
        print(f'  scan root: {info["scan_root"]}')
    return info


def cmd_extract(args):
    from astify.extract import run_extraction
    from astify.storage import save_semantic

    result = run_extraction(
        directory=args.directory,
        model_name=args.model,
        sim_threshold=args.threshold,
        max_similarity_neighbors=args.max_neighbors,
        batch_size=args.batch_size,
        verbose=not args.quiet,
    )

    root = Path(args.directory).resolve()
    database_path = root / 'astify-out' / 'astify.db'
    if not args.quiet:
        print('Writing SQLite extraction store...', flush=True)
    save_semantic(database_path, result)
    for stale_name in (
        'graph.json',
        'graph-summary.json',
        'analysis.json',
        'GRAPH_REPORT.md',
        'graph.html',
    ):
        (database_path.parent / stale_name).unlink(missing_ok=True)
    if not args.quiet:
        print(f'Saved: {database_path}', flush=True)

    if args.graphify_path:
        out_path = Path(args.graphify_path)
    elif args.output:
        out_path = Path(args.output)
    elif args.json:
        out_path = root / 'astify-out' / '.semantic.json'
    else:
        out_path = None

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
    if not args.quiet:
        if out_path is not None:
            print(f'Saved: {out_path}')
        n = len(result['nodes'])
        e = len(result['edges'])
        print(f'{n} nodes, {e} edges | 0 tokens')
    return result


def cmd_build(args):
    from astify.build import build_graph
    from astify.storage import load_semantic

    out_dir = Path(args.directory).resolve() / 'astify-out'
    database_path = out_dir / 'astify.db'
    sem_path = out_dir / '.semantic.json'
    if database_path.exists():
        semantic = load_semantic(database_path)
    elif sem_path.exists():
        with open(sem_path, encoding='utf-8') as file:
            semantic = json.load(file)
    else:
        print(f'ERROR: No extraction found in {out_dir}')
        print('Run `astify extract` first.')
        raise SystemExit(1)

    graph = build_graph(
        directory=args.directory,
        semantic=semantic,
        quiet=args.quiet,
        full_analysis=args.full_analysis,
        full_json=args.full_json,
    )
    return graph


def cmd_query(args):
    from astify.query import query_graph

    literal = 'auto'
    if args.literal:
        literal = 'always'
    elif args.no_literal:
        literal = 'never'
    query_graph(args.question, mode=args.mode, budget=args.budget,
                directory=args.directory, quiet=args.quiet, literal=literal)


def cmd_path(args):
    from astify.query import find_path

    find_path(args.node_a, args.node_b, directory=args.directory,
              quiet=args.quiet)


def cmd_explain(args):
    from astify.query import explain_node

    explain_node(args.node, directory=args.directory, quiet=args.quiet)


def cmd_report(args):
    from astify.report import generate_report

    generate_report(args.directory, meta=None, quiet=args.quiet)


def cmd_html(args):
    from astify.export import export_html

    export_html(
        args.directory,
        quiet=args.quiet,
        full_html=args.full_html,
    )


def cmd_run(args):
    """Run detect → extract → build → report → HTML."""
    cmd_detect(args)
    cmd_extract(args)
    cmd_build(args)
    cmd_report(args)
    if not args.no_viz:
        cmd_html(args)


def main():
    parser = argparse.ArgumentParser(
        description='ASTify — AST + embedding knowledge graphs (zero AI tokens)',
    )
    parser.add_argument('--version', action='version', version='astify 0.3.0')
    sub = parser.add_subparsers(dest='command', help='Commands')

    # full pipeline
    p = sub.add_parser('run', help='Run full detect/extract/build/report/html pipeline')
    p.add_argument('directory', nargs='?', default='.', help='Directory to scan')
    p.add_argument('-m', '--model', default='all-MiniLM-L6-v2',
                   help='Sentence-transformer model')
    p.add_argument('-t', '--threshold', type=float, default=0.72,
                   help='Cosine similarity threshold')
    p.add_argument('-k', '--max-neighbors', type=int, default=20,
                   help='Maximum semantic neighbors per file')
    p.add_argument('--batch-size', type=int, default=32,
                   help='Embedding/NLP batch size')
    p.add_argument('--full-analysis', action='store_true',
                   help='Force exact betweenness analysis (may be very slow)')
    p.add_argument('--full-json', action='store_true',
                   help='Force full graph.json export for large graphs')
    p.add_argument('--full-html', action='store_true',
                   help='Force detailed HTML export for large graphs')
    p.add_argument('--no-viz', action='store_true',
                   help='Skip HTML visualization')
    p.add_argument('--json', action='store_true',
                   help='Also write legacy astify-out/.semantic.json')
    p.add_argument('-q', '--quiet', action='store_true')
    p.set_defaults(output=None, graphify_path=None)

    # detect
    p = sub.add_parser('detect', help='Detect and summarize files in directory')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory to scan')
    p.add_argument('-q', '--quiet', action='store_true')

    # extract
    p = sub.add_parser('extract', help='Extract semantic graph from readable files')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory to scan')
    p.add_argument('-m', '--model', default='all-MiniLM-L6-v2',
                   help='Sentence-transformer model')
    p.add_argument('-t', '--threshold', type=float, default=0.72,
                   help='Cosine similarity threshold')
    p.add_argument('-k', '--max-neighbors', type=int, default=20,
                   help='Maximum semantic neighbors per file')
    p.add_argument('--batch-size', type=int, default=32,
                   help='Embedding/NLP batch size')
    p.add_argument('-o', '--output', default=None,
                   help='Output JSON path')
    p.add_argument('--graphify-path', default=None,
                   help='Output to Graphify-compatible path')
    p.add_argument('--json', action='store_true',
                   help='Also write legacy astify-out/.semantic.json')
    p.add_argument('-q', '--quiet', action='store_true')

    # build
    p = sub.add_parser('build', help='Build full knowledge graph from extraction')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory with astify-out/astify.db or .semantic.json')
    p.add_argument('--full-analysis', action='store_true',
                   help='Force exact betweenness analysis (may be very slow)')
    p.add_argument('--full-json', action='store_true',
                   help='Force full graph.json export for large graphs')
    p.add_argument('-q', '--quiet', action='store_true')

    # report
    p = sub.add_parser('report', help='Generate GRAPH_REPORT.md')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory with astify-out/')
    p.add_argument('-q', '--quiet', action='store_true')

    # html
    p = sub.add_parser('html', help='Generate interactive HTML graph')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory with astify-out/')
    p.add_argument('--full-html', action='store_true',
                   help='Force detailed HTML export for large graphs')
    p.add_argument('-q', '--quiet', action='store_true')

    # query
    p = sub.add_parser('query', help='Query the knowledge graph')
    p.add_argument('question', help='Natural language question')
    p.add_argument('--mode', choices=['bfs', 'dfs'], default='bfs',
                   help='Traversal mode')
    p.add_argument('--budget', type=int, default=2000,
                   help='Output token budget')
    p.add_argument('--literal', action='store_true',
                   help='Always run the EXACT source scan for literal terms')
    p.add_argument('--no-literal', action='store_true',
                   help='Never run the EXACT source scan')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory with astify-out/')
    p.add_argument('-q', '--quiet', action='store_true')

    # path
    p = sub.add_parser('path', help='Shortest path between two concepts')
    p.add_argument('node_a', help='First concept/node name')
    p.add_argument('node_b', help='Second concept/node name')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory with astify-out/')
    p.add_argument('-q', '--quiet', action='store_true')

    # explain
    p = sub.add_parser('explain', help='Explain a node')
    p.add_argument('node', help='Node/concept to explain')
    p.add_argument('directory', nargs='?', default='.',
                   help='Directory with astify-out/')
    p.add_argument('-q', '--quiet', action='store_true')

    args = parser.parse_args(_normalize_argv(sys.argv[1:]))

    if not args.command:
        parser.print_help()
        return

    cmds = {
        'run': cmd_run,
        'detect': cmd_detect,
        'extract': cmd_extract,
        'build': cmd_build,
        'report': cmd_report,
        'html': cmd_html,
        'query': cmd_query,
        'path': cmd_path,
        'explain': cmd_explain,
    }
    cmds[args.command](args)


if __name__ == '__main__':
    main()

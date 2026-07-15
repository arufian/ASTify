"""File detection and corpus summarization."""
import os
from pathlib import Path

TEXT_EXTS = {'.md', '.txt', '.rst', '.adoc', '.org', '.tex', '.wiki', '.asciidoc'}
DOC_EXTS = TEXT_EXTS | {'.pdf'}
CODE_EXTS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java', '.kt',
    '.c', '.cpp', '.h', '.hpp', '.rb', '.swift', '.scala', '.cs', '.php',
    '.sh', '.bash', '.zsh', '.sql', '.r', '.jl', '.lua', '.pl', '.pm',
    '.dart', '.ex', '.exs', '.clj', '.cljs', '.elm', '.hs', '.ml',
    '.vue', '.svelte', '.astro', '.sol', '.move', '.proto', '.graphql',
    '.yml', '.yaml', '.toml', '.json', '.xml', '.cfg', '.ini', '.conf',
}
SKIP_PARTS = {'node_modules', '__pycache__', '.git', '.svn', 'venv', '.venv',
              'astify-out', 'graphify-out', 'dist', 'build', '.tox', '.eggs'}


def detect_files(root: Path, exts: set[str] = DOC_EXTS) -> list[Path]:
    files = []
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        if any(part.startswith('.') and part != '.' for part in path.parts):
            continue
        if any(s in path.parts for s in SKIP_PARTS):
            continue
        files.append(path)
    return sorted(files)


def detect_all(root: Path) -> dict:
    """Detect all files, return corpus summary."""
    code_files = detect_files(root, CODE_EXTS)
    doc_files = detect_files(root, DOC_EXTS)

    total_words = 0
    for fp in doc_files:
        try:
            text = fp.read_text(encoding='utf-8', errors='replace')
            total_words += len(text.split())
        except Exception:
            pass
    for fp in code_files:
        try:
            text = fp.read_text(encoding='utf-8', errors='replace')
            total_words += len(text.split())
        except Exception:
            pass

    return {
        'total_files': len(code_files) + len(doc_files),
        'total_words': total_words,
        'code_files': len(code_files),
        'doc_files': len(doc_files),
        'files': {
            'code': [str(f) for f in code_files],
            'document': [str(f) for f in doc_files],
        },
        'scan_root': str(root),
    }

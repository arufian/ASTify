"""File detection and corpus summarization."""
import codecs
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
    '.cls', '.trigger', '.apex', '.groovy', '.gradle', '.kts', '.m', '.mm',
    '.fs', '.fsx', '.vb', '.vbs', '.ps1', '.psm1', '.bat', '.cmd', '.fish',
    '.coffee', '.litcoffee', '.nim', '.zig', '.v', '.vhd', '.vhdl', '.sv',
    '.svh', '.tf', '.tfvars', '.hcl', '.cue', '.rego', '.prisma', '.graphqls',
    '.gql', '.dockerfile', '.makefile', '.cmake', '.properties',
}
CODE_FILENAMES = {
    'dockerfile', 'makefile', 'rakefile', 'gemfile', 'procfile', 'justfile',
    'jenkinsfile', 'vagrantfile', 'cmakelists.txt',
}
NON_PROGRAMMING_CODE_EXTS = {
    '.cfg', '.conf', '.ini', '.json', '.properties', '.toml', '.xml', '.yaml',
    '.yml',
}
SYMBOL_CODE_EXTS = CODE_EXTS - NON_PROGRAMMING_CODE_EXTS
SKIP_PARTS = {'node_modules', '__pycache__', '.git', '.svn', 'venv', '.venv',
              'astify-out', 'graphify-out', 'dist', 'build', '.tox', '.eggs'}


def _is_scannable(path: Path, root: Path) -> bool:
    """Return whether path is a regular, non-generated, non-hidden file."""
    if not path.is_file():
        return False
    # Only inspect components below root, so a hidden ancestor directory of
    # root does not exclude everything.
    rel_parts = path.relative_to(root).parts
    if any(part.startswith('.') for part in rel_parts):
        return False
    return not any(part in SKIP_PARTS for part in rel_parts)


def is_text_file(path: Path, sample_size: int = 8192) -> bool:
    """Detect readable text by content, independent of filename extension.

    Known PDFs are handled by the PDF reader. Other files must look like UTF
    text, which lets ASTify cover uncommon and extensionless source formats
    without accidentally embedding images, archives, or executables.
    """
    if path.suffix.lower() == '.pdf':
        return True
    try:
        with path.open('rb') as file:
            sample = file.read(sample_size)
    except OSError:
        return False
    if not sample:
        return True

    unicode_boms = (
        codecs.BOM_UTF8,
        codecs.BOM_UTF16_LE,
        codecs.BOM_UTF16_BE,
        codecs.BOM_UTF32_LE,
        codecs.BOM_UTF32_BE,
    )
    has_unicode_bom = any(sample.startswith(bom) for bom in unicode_boms)
    if b'\x00' in sample and not has_unicode_bom:
        return False

    try:
        if sample.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            text = sample.decode('utf-32')
        elif sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            text = sample.decode('utf-16')
        else:
            text = sample.decode('utf-8-sig')
    except UnicodeDecodeError:
        return False

    printable = sum(char.isprintable() or char.isspace() for char in text)
    return printable / max(len(text), 1) >= 0.85


def detect_files(root: Path, exts: set[str] = DOC_EXTS) -> list[Path]:
    """Find files matching extensions. Kept for public API compatibility."""
    root = root.resolve()
    files = []
    for path in root.rglob('*'):
        if not _is_scannable(path, root):
            continue
        if path.suffix.lower() not in exts:
            continue
        files.append(path)
    return sorted(files)


def detect_content_files(root: Path) -> list[Path]:
    """Find every readable text or PDF file, regardless of extension."""
    root = root.resolve()
    return sorted(
        path for path in root.rglob('*')
        if _is_scannable(path, root) and is_text_file(path)
    )


def detect_all(root: Path) -> dict:
    """Detect all files, return corpus summary."""
    content_files = detect_content_files(root)
    code_files = [
        f for f in content_files
        if f.suffix.lower() in CODE_EXTS or f.name.lower() in CODE_FILENAMES
    ]
    doc_files = [f for f in content_files if f not in code_files]

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

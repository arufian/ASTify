"""Exact literal search over corpus text.

The graph indexes labels, paths, and symbols — never raw file content. Queries
about a literal string (a placeholder value, a UI label, a CJK phrase) have no
vocabulary to match and previously returned only INFERRED concept rows. This
module scans the same corpus the extractor sees and returns EXACT file:line
evidence so a single query stays actionable.
"""
import re
from pathlib import Path

MAX_FILE_BYTES = 2_000_000
MAX_FILES = 5000
CJK_RANGES = (
    ('぀', 'ヿ'),   # kana
    ('㐀', '䶿'),   # CJK ext A
    ('一', '鿿'),   # CJK unified
    ('豈', '﫿'),   # compatibility ideographs
    ('ｦ', 'ﾟ'),   # halfwidth kana
)


def is_cjk(text: str) -> bool:
    return any(
        any(low <= char <= high for low, high in CJK_RANGES) for char in text
    )


def literal_candidates(question: str) -> list[str]:
    """Pull the parts of a question that only an exact source scan can answer.

    Quoted spans, identifier-like tokens (digits, underscores, CamelCase), and
    CJK runs are all things a natural-language embedding will blur away.
    """
    candidates = []
    seen = set()

    def add(term: str):
        term = term.strip().strip('.,;:!?')
        key = term.lower()
        if len(term) >= 2 and key not in seen:
            seen.add(key)
            candidates.append(term)

    for quoted in re.findall(r'"([^"]{2,80})"|\'([^\']{2,80})\'|`([^`]{2,80})`',
                             question):
        for group in quoted:
            if group:
                add(group)
    for run in re.findall(r'[぀-ヿ㐀-䶿一-鿿'
                          r'豈-﫿ｦ-ﾟ]{2,}', question):
        add(run)
    for token in re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,}', question):
        if (
            any(char.isdigit() for char in token)
            or '_' in token
            or re.search(r'[a-z][A-Z]', token)
        ):
            add(token)
    return candidates


def _corpus_files(root: Path) -> list[Path]:
    from astify.detect import detect_content_files

    files = [
        path for path in detect_content_files(root)
        if path.suffix.lower() != '.pdf'
    ]
    return files[:MAX_FILES]


def literal_search(root, terms, max_hits: int = 40,
                   max_hits_per_term: int = 12) -> list[dict]:
    """Return exact substring hits as {term, path, line, text} records."""
    root = Path(root).resolve()
    terms = [term for term in terms if term]
    if not terms:
        return []

    lowered = [(term, term.lower()) for term in terms]
    per_term = {term: 0 for term in terms}
    hits = []
    for path in _corpus_files(root):
        if len(hits) >= max_hits:
            break
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        text_lower = text.lower()
        if not any(needle in text_lower for _, needle in lowered):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if len(hits) >= max_hits:
                break
            line_lower = line.lower()
            for term, needle in lowered:
                if per_term[term] >= max_hits_per_term:
                    continue
                if needle in line_lower:
                    per_term[term] += 1
                    hits.append({
                        'term': term,
                        'path': str(path.relative_to(root))
                        if path.is_relative_to(root) else str(path),
                        'line': line_number,
                        'text': line.strip()[:200],
                    })
                    break
    return hits

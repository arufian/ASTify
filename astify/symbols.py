"""Deterministic, language-tolerant source symbol extraction."""
import re
from pathlib import Path

from astify.identifiers import normalize_id, stem_from_path


_KEYWORD_DEFINITION_RE = re.compile(
    r'\b(class|interface|enum|struct|trait|record|module|namespace)\s+'
    r'([A-Za-z_][A-Za-z0-9_]*)'
)
_FUNCTION_DEFINITION_RE = re.compile(
    r'\b(def|function|func|fn|sub|procedure)\s+'
    r'([A-Za-z_][A-Za-z0-9_]*)\s*\('
)
_C_STYLE_METHOD_RE = re.compile(
    r'^\s*(?:(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?)\s*)*'
    r'(?:(?:public|private|protected|global|internal|static|virtual|override|'
    r'abstract|final|async|webservice|testmethod|transient|synchronized)\s+)*'
    r'[A-Za-z_][A-Za-z0-9_.<>,\[\]?]*\s+'
    r'([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*(?:\{|throws\b|$)',
    re.IGNORECASE,
)
_CALL_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(')
_CONSTRUCTOR_RE = re.compile(r'\bnew\s+([A-Za-z_][A-Za-z0-9_.]*)\s*\(')
_ASSIGNMENT_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)')
_IDENTIFIER_RE = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')

_CONTROL_WORDS = {
    'as', 'assert', 'async', 'await', 'break', 'case', 'catch', 'class',
    'const', 'continue', 'default', 'def', 'do', 'else', 'enum',
    'except', 'extends', 'false', 'finally', 'for', 'foreach', 'from', 'func',
    'function', 'if', 'implements', 'import', 'in', 'interface',
    'lambda', 'let', 'module', 'namespace', 'new', 'none', 'null', 'package',
    'private', 'protected', 'public', 'raise', 'record', 'return', 'select',
    'static', 'struct', 'sub', 'switch', 'this', 'throw', 'trait', 'trigger',
    'true', 'try', 'typeof', 'using', 'var', 'virtual', 'void',
    'when', 'where', 'while', 'with', 'yield',
}


def _looks_symbolic(name: str) -> bool:
    """Keep code-like identifiers while rejecting ordinary source words."""
    lower = name.lower()
    if lower in _CONTROL_WORDS or len(name) < 2:
        return False
    return (
        name.isupper()
        or name[0].isupper()
    )


def _is_generated_source(filepath: Path, text: str) -> bool:
    """Reject minified/generated artifacts that would dominate symbol graphs."""
    name = filepath.name.lower()
    if any(marker in name for marker in ('.min.', '.bundle.', '.generated.')):
        return True
    lines = text.splitlines()
    return bool(text) and len(text) > 50_000 and (
        len(lines) <= 5 or max((len(line) for line in lines), default=0) > 2_000
    )


def _sanitize_source(text: str) -> list[str]:
    """Blank comments and string contents while preserving source line numbers."""
    result = []
    index = 0
    in_block_comment = False
    quote = None
    escaped = False
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ''

        if char == '\n':
            result.append(char)
            if quote in {'\'', '"'}:
                quote = None
            escaped = False
            index += 1
            continue

        if in_block_comment:
            if char == '*' and next_char == '/':
                result.extend((' ', ' '))
                in_block_comment = False
                index += 2
            else:
                result.append(' ')
                index += 1
            continue

        if quote:
            result.append(' ')
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char == '/' and next_char == '*':
            result.extend((' ', ' '))
            in_block_comment = True
            index += 2
            continue
        if char == '/' and next_char == '/':
            while index < len(text) and text[index] != '\n':
                result.append(' ')
                index += 1
            continue
        if char == '#':
            while index < len(text) and text[index] != '\n':
                result.append(' ')
                index += 1
            continue
        if char in {'\'', '"', '`'}:
            result.append(' ')
            quote = char
            index += 1
            continue

        result.append(char)
        index += 1

    return ''.join(result).splitlines()


def _definitions(lines: list[str]) -> list[dict]:
    found = []
    known_types = set()
    for line_number, line in enumerate(lines, 1):
        for match in _KEYWORD_DEFINITION_RE.finditer(line):
            kind, name = match.groups()
            known_types.add(name)
            found.append({'name': name, 'kind': kind.lower(), 'line': line_number})

        for match in _FUNCTION_DEFINITION_RE.finditer(line):
            kind, name = match.groups()
            found.append({'name': name, 'kind': 'method', 'line': line_number})

        match = _C_STYLE_METHOD_RE.match(line)
        if match:
            name = match.group(1)
            if name.lower() not in _CONTROL_WORDS:
                found.append({'name': name, 'kind': 'method', 'line': line_number})

        # C-style constructors have no return type.
        stripped = line.strip()
        for type_name in known_types:
            if re.match(
                rf'(?:(?:public|private|protected|global|internal)\s+)*'
                rf'{re.escape(type_name)}\s*\(',
                stripped,
                re.IGNORECASE,
            ):
                found.append({
                    'name': type_name,
                    'kind': 'constructor',
                    'line': line_number,
                })
    return found


def _method_ranges(lines: list[str], definitions: list[dict]) -> list[dict]:
    """Approximate brace-delimited method ranges for call ownership."""
    ranges = []
    for definition in definitions:
        if definition['kind'] not in {'method', 'constructor'}:
            continue
        start = definition['line']
        balance = 0
        opened = False
        end = start
        for index in range(start - 1, len(lines)):
            line = lines[index]
            opens = line.count('{')
            closes = line.count('}')
            if opens:
                opened = True
            if opened:
                balance += opens - closes
                end = index + 1
                if balance <= 0:
                    break
        ranges.append({**definition, 'end': end})
    return ranges


def _owner_at(line_number: int, ranges: list[dict]) -> dict | None:
    matches = [r for r in ranges if r['line'] <= line_number <= r['end']]
    if not matches:
        return None
    return min(matches, key=lambda item: item['end'] - item['line'])


def extract_code_symbols(
    files: list[Path],
    root: Path,
    texts: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    """Extract source symbols and structural edges without an LLM or parser.

    Patterns intentionally cover common declaration syntax across languages.
    Results represent syntax observed in source, so edges use EXTRACTED rather
    than embedding-derived INFERRED confidence.
    """
    nodes = []
    edges = []
    node_ids = set()
    edge_keys = set()

    def add_node(node: dict) -> None:
        if node['id'] not in node_ids:
            node_ids.add(node['id'])
            nodes.append(node)

    def add_edge(source: str, target: str, relation: str, source_file: str,
                 line_number: int) -> None:
        key = (source, target, relation, line_number)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({
            'source': source,
            'target': target,
            'relation': relation,
            'confidence': 'EXTRACTED',
            'confidence_score': 1.0,
            'source_file': source_file,
            'source_location': f'line {line_number}',
            'weight': 1.0,
        })

    for filepath in files:
        path_str = str(filepath)
        text = texts.get(path_str)
        if text is None:
            continue
        if _is_generated_source(filepath, text):
            continue
        rel_str = str(filepath.relative_to(root))
        stem = stem_from_path(filepath, root)
        file_node_id = stem
        lines = _sanitize_source(text)
        definitions = _definitions(lines)
        ranges = _method_ranges(lines, definitions)
        canonical = {}

        def canonical_id(name: str) -> str:
            return f'{stem}_symbol_{normalize_id(name)}'

        for definition in definitions:
            name = definition['name']
            node_id = canonical_id(name)
            canonical[name.lower()] = node_id
            add_node({
                'id': node_id,
                'label': name,
                'file_type': 'symbol',
                'symbol_kind': definition['kind'],
                'source_file': rel_str,
                'source_location': f"line {definition['line']}",
            })
            add_edge(file_node_id, node_id, 'defines', rel_str,
                     definition['line'])

        references = {}
        for line_number, line in enumerate(lines, 1):
            definition_names = {
                d['name'].lower() for d in definitions
                if d['line'] == line_number
            }
            owner = _owner_at(line_number, ranges)
            owner_id = canonical_id(owner['name']) if owner else file_node_id

            constructors = {
                match.group(1).split('.')[-1]
                for match in _CONSTRUCTOR_RE.finditer(line)
            }
            calls = {match.group(1) for match in _CALL_RE.finditer(line)}
            identifiers = set(_IDENTIFIER_RE.findall(line))
            candidates = {
                name for name in identifiers
                if _looks_symbolic(name)
            } | {
                name for name in calls
                if name.lower() not in _CONTROL_WORDS
            }

            for name in sorted(candidates):
                lower = name.lower()
                if lower in definition_names:
                    continue
                references.setdefault(lower, (name, line_number))

            for name in sorted(calls):
                lower = name.lower()
                if lower in _CONTROL_WORDS or lower in definition_names:
                    continue
                target_id = canonical.get(lower, canonical_id(name))
                relation = 'instantiates' if name in constructors else 'calls'
                add_edge(owner_id, target_id, relation, rel_str, line_number)

            for name in sorted(constructors):
                occurrence_id = (
                    f'{stem}_constructor_{normalize_id(name)}_{line_number}'
                )
                add_node({
                    'id': occurrence_id,
                    'label': f'new {name}',
                    'file_type': 'symbol',
                    'symbol_kind': 'constructor_call',
                    'source_file': rel_str,
                    'source_location': f'line {line_number}',
                })
                add_edge(owner_id, occurrence_id, 'instantiates', rel_str,
                         line_number)

            for match in _ASSIGNMENT_RE.finditer(line):
                name = match.group(1)
                if not (_looks_symbolic(name) or '_' in name):
                    continue
                occurrence_id = (
                    f'{stem}_assignment_{normalize_id(name)}_{line_number}'
                )
                add_node({
                    'id': occurrence_id,
                    'label': f'{name} assignment',
                    'file_type': 'symbol',
                    'symbol_kind': 'assignment',
                    'source_file': rel_str,
                    'source_location': f'line {line_number}',
                })
                add_edge(owner_id, occurrence_id, 'assigns', rel_str,
                         line_number)

        for lower, (name, line_number) in sorted(references.items()):
            node_id = canonical.get(lower, canonical_id(name))
            if node_id not in node_ids:
                add_node({
                    'id': node_id,
                    'label': name,
                    'file_type': 'symbol',
                    'symbol_kind': 'reference',
                    'source_file': rel_str,
                    'source_location': f'line {line_number}',
                })
                add_edge(file_node_id, node_id, 'references', rel_str,
                         line_number)

    return nodes, edges

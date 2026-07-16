"""Tree-sitter AST extraction for code definitions, calls, and references."""
import re
from collections import defaultdict
from pathlib import Path

from astify.identifiers import normalize_id, stem_from_path


LANGUAGE_BY_EXTENSION = {
    '.apex': 'apex',
    '.cls': 'apex',
    '.trigger': 'apex',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',
}

DEFINITION_KINDS = {
    'class_declaration': 'class',
    'class_definition': 'class',
    'interface_declaration': 'interface',
    'enum_declaration': 'enum',
    'trigger_declaration': 'trigger',
    'method_declaration': 'method',
    'method_definition': 'method',
    'constructor_declaration': 'constructor',
    'function_declaration': 'function',
    'function_definition': 'function',
    'generator_function_declaration': 'function',
}

CALL_KINDS = {
    'call',
    'call_expression',
    'function_call_expression',
    'invocation_expression',
    'method_invocation',
}

CONSTRUCTOR_KINDS = {
    'new_expression',
    'object_creation_expression',
}

ASSIGNMENT_KINDS = {
    'assignment_expression',
    'augmented_assignment_expression',
}


def language_for_path(filepath: Path) -> str | None:
    return LANGUAGE_BY_EXTENSION.get(filepath.suffix.lower())


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')


def _line(node) -> int:
    return node.start_point[0] + 1


def _column(node) -> int:
    return node.start_point[1] + 1


def _definition_name(node, source: bytes) -> str:
    name_node = node.child_by_field_name('name')
    if name_node is not None:
        return _node_text(name_node, source).strip()
    for child in node.named_children:
        if child.type in {'identifier', 'property_identifier', 'type_identifier'}:
            return _node_text(child, source).strip()
    return ''


def _callable_name(node, source: bytes) -> str:
    if node.type == 'method_invocation':
        name = node.child_by_field_name('name')
        object_node = node.child_by_field_name('object')
        name_text = _node_text(name, source).strip() if name else ''
        object_text = _node_text(object_node, source).strip() if object_node else ''
        return f'{object_text}.{name_text}' if object_text else name_text

    function = (
        node.child_by_field_name('function')
        or node.child_by_field_name('name')
        or node.child_by_field_name('method')
    )
    if function is None and node.named_children:
        function = node.named_children[0]
    if function is None:
        return ''
    if function.type in {'member_expression', 'member_access_expression'}:
        object_node = function.child_by_field_name('object')
        property_node = (
            function.child_by_field_name('property')
            or function.child_by_field_name('field')
        )
        property_text = (
            _node_text(property_node, source).strip() if property_node else ''
        )
        if object_node is not None and object_node.type in CALL_KINDS:
            return property_text
        object_text = (
            re.sub(r'\s+', '', _node_text(object_node, source))
            if object_node else ''
        )
        qualified = (
            f'{object_text}.{property_text}' if object_text else property_text
        )
        return qualified if len(qualified) <= 160 else property_text
    text = re.sub(r'\s+', '', _node_text(function, source))
    return text if len(text) <= 160 else ''


def _constructor_name(node, source: bytes) -> str:
    type_node = (
        node.child_by_field_name('type')
        or node.child_by_field_name('constructor')
    )
    if type_node is None:
        for child in node.named_children:
            if child.type in {'identifier', 'type_identifier'}:
                type_node = child
                break
    return _node_text(type_node, source).strip() if type_node else ''


def _assignment_target(node, source: bytes) -> str:
    left = (
        node.child_by_field_name('left')
        or node.child_by_field_name('name')
    )
    if left is None and node.named_children:
        left = node.named_children[0]
    if left is None:
        return ''
    text = re.sub(r'\s+', '', _node_text(left, source))
    return text if len(text) <= 160 else ''


def _salesforce_imports(root_node, source: bytes) -> dict[str, str]:
    """Map local JS import names to qualified Apex methods."""
    imports = {}
    stack = [root_node]
    while stack:
        node = stack.pop()
        if node.type == 'import_statement':
            source_node = node.child_by_field_name('source')
            source_text = _node_text(source_node, source).strip("'\"") if source_node else ''
            if source_text.startswith('@salesforce/apex/'):
                qualified = source_text.removeprefix('@salesforce/apex/')
                clause = next(
                    (child for child in node.named_children
                     if child.type == 'import_clause'),
                    None,
                )
                if clause is not None:
                    identifiers = [
                        child for child in clause.named_children
                        if child.type in {'identifier', 'import_identifier'}
                    ]
                    if identifiers:
                        imports[_node_text(identifiers[0], source)] = qualified
        stack.extend(reversed(node.named_children))
    return imports


def extract_ast_symbols(
    files: list[Path],
    root: Path,
    texts: dict[str, str],
) -> tuple[list[dict], list[dict], set[Path]]:
    """Extract syntax graph from real Tree-sitter ASTs.

    Returns nodes, edges, and files successfully parsed without syntax errors.
    Files outside supported languages or containing parse errors remain eligible
    for caller-provided heuristic fallback.
    """
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return [], [], set()

    parsed = []
    parsed_files = set()
    for filepath in files:
        language = language_for_path(filepath)
        text = texts.get(str(filepath))
        if not language or text is None:
            continue
        try:
            source = text.encode('utf-8')
            tree = get_parser(language).parse(source)
        except Exception:
            continue
        if tree.root_node.has_error:
            continue
        parsed.append({
            'path': filepath,
            'language': language,
            'source': source,
            'root': tree.root_node,
            'imports': _salesforce_imports(tree.root_node, source),
        })
        parsed_files.add(filepath)

    nodes = []
    edges = []
    node_ids = set()
    edge_keys = set()
    definitions_by_name = defaultdict(list)
    definitions_by_qualified = defaultdict(list)
    definition_ids = {}

    def add_node(node: dict) -> None:
        if node['id'] not in node_ids:
            node_ids.add(node['id'])
            nodes.append(node)

    def add_edge(source: str, target: str, relation: str, source_file: str,
                 source_location: str, confidence: str = 'EXTRACTED',
                 score: float = 1.0) -> None:
        key = (source, target, relation, source_location)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({
            'source': source,
            'target': target,
            'relation': relation,
            'confidence': confidence,
            'confidence_score': score,
            'source_file': source_file,
            'source_location': source_location,
            'weight': 1.0,
        })

    # Pass 1: collect definitions across every file for cross-file resolution.
    def collect_definitions(item, node, parent_id=None, parent_names=()):
        filepath = item['path']
        source = item['source']
        rel = str(filepath.relative_to(root))
        stem = stem_from_path(filepath, root)
        current_parent = parent_id
        current_names = parent_names
        kind = DEFINITION_KINDS.get(node.type)
        if kind:
            name = _definition_name(node, source)
            if name:
                line = _line(node)
                node_id = (
                    f'{stem}_ast_{kind}_{normalize_id(name)}_{line}'
                )
                qualified = '.'.join((*parent_names, name))
                definition_ids[(filepath, node.start_byte, node.type)] = node_id
                add_node({
                    'id': node_id,
                    'label': name,
                    'file_type': 'symbol',
                    'symbol_kind': kind,
                    'parser': 'tree-sitter',
                    'language': item['language'],
                    'source_file': rel,
                    'source_location': f'line {line}',
                })
                add_edge(
                    parent_id or stem,
                    node_id,
                    'defines',
                    rel,
                    f'line {line}',
                )
                record = {
                    'id': node_id,
                    'name': name,
                    'qualified': qualified,
                    'path': filepath,
                }
                definitions_by_name[name.lower()].append(record)
                definitions_by_qualified[qualified.lower()].append(record)
                current_parent = node_id
                current_names = (*parent_names, name)
        for child in node.named_children:
            collect_definitions(item, child, current_parent, current_names)

    for item in parsed:
        collect_definitions(item, item['root'])

    def resolve_definition(item, call_name: str):
        imported = item['imports'].get(call_name)
        if imported:
            candidates = definitions_by_qualified.get(imported.lower(), [])
            if candidates:
                return candidates[0], 'EXTRACTED', 1.0

        simple_name = call_name.rsplit('.', 1)[-1].lower()
        candidates = definitions_by_name.get(simple_name, [])
        same_file = [c for c in candidates if c['path'] == item['path']]
        if len(same_file) == 1:
            return same_file[0], 'EXTRACTED', 1.0
        if len(candidates) == 1:
            return candidates[0], 'INFERRED', 0.8
        return None, None, None

    # Pass 2: collect occurrences and connect them to owning definitions.
    def collect_occurrences(item, node, owner_id=None):
        filepath = item['path']
        source = item['source']
        rel = str(filepath.relative_to(root))
        stem = stem_from_path(filepath, root)
        definition_id = definition_ids.get((filepath, node.start_byte, node.type))
        current_owner = definition_id or owner_id or stem
        location = f'line {_line(node)}:{_column(node)}'
        occurrence_suffix = f'{_line(node)}_{_column(node)}'

        if node.type in CALL_KINDS:
            name = _callable_name(node, source)
            if name:
                occurrence_id = (
                    f'{stem}_ast_call_{normalize_id(name)}_{occurrence_suffix}'
                )
                add_node({
                    'id': occurrence_id,
                    'label': f'call {name}',
                    'file_type': 'symbol',
                    'symbol_kind': 'call',
                    'parser': 'tree-sitter',
                    'language': item['language'],
                    'source_file': rel,
                    'source_location': location,
                })
                add_edge(current_owner, occurrence_id, 'calls', rel, location)
                resolved, confidence, score = resolve_definition(item, name)
                if resolved:
                    add_edge(
                        occurrence_id,
                        resolved['id'],
                        'resolves_to',
                        rel,
                        location,
                        confidence,
                        score,
                    )

        if node.type in CONSTRUCTOR_KINDS:
            name = _constructor_name(node, source)
            if name:
                occurrence_id = (
                    f'{stem}_ast_new_{normalize_id(name)}_{occurrence_suffix}'
                )
                add_node({
                    'id': occurrence_id,
                    'label': f'new {name}',
                    'file_type': 'symbol',
                    'symbol_kind': 'constructor_call',
                    'parser': 'tree-sitter',
                    'language': item['language'],
                    'source_file': rel,
                    'source_location': location,
                })
                add_edge(
                    current_owner, occurrence_id, 'instantiates', rel, location
                )

        if node.type in ASSIGNMENT_KINDS:
            target = _assignment_target(node, source)
            if target:
                occurrence_id = (
                    f'{stem}_ast_assignment_{normalize_id(target)}_'
                    f'{occurrence_suffix}'
                )
                add_node({
                    'id': occurrence_id,
                    'label': f'{target} assignment',
                    'file_type': 'symbol',
                    'symbol_kind': 'assignment',
                    'parser': 'tree-sitter',
                    'language': item['language'],
                    'source_file': rel,
                    'source_location': location,
                })
                add_edge(current_owner, occurrence_id, 'assigns', rel, location)

        for child in node.named_children:
            collect_occurrences(item, child, current_owner)

    for item in parsed:
        collect_occurrences(item, item['root'])

    return nodes, edges, parsed_files

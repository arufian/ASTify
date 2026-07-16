import re
import codecs
from pathlib import Path
from collections import defaultdict

import numpy as np
import yaml

from astify.detect import CODE_EXTS, CODE_FILENAMES, SYMBOL_CODE_EXTS
from astify.identifiers import normalize_id, stem_from_path
from astify.symbols import extract_code_symbols


def read_frontmatter(text: str) -> tuple[dict, str]:
    """Strip YAML frontmatter, return (meta, body)."""
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()
    return {}, text


def read_file_text(filepath: Path) -> str:
    """Read file content, handling PDFs via PyMuPDF."""
    ext = filepath.suffix.lower()
    if ext == '.pdf':
        try:
            import fitz
            doc = fitz.open(str(filepath))
            text = '\n'.join(page.get_text() for page in doc)
            doc.close()
            return text
        except ImportError:
            return ''
        except Exception:
            return ''
    try:
        data = filepath.read_bytes()
        if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            return data.decode('utf-32')
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode('utf-16')
        return data.decode('utf-8-sig', errors='replace')
    except OSError:
        return ''


def detect_files(root: Path) -> list[Path]:
    """Find all readable text and PDF files, regardless of extension."""
    from astify.detect import detect_content_files
    return detect_content_files(root)


def chunk_text(text: str, max_chars: int = 8000) -> list[str]:
    """Split long text into overlapping chunks for embedding."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    step = max_chars - 500  # overlap
    for i in range(0, len(text), step):
        chunk = text[i:i + max_chars]
        if len(chunk) < 200:
            continue
        chunks.append(chunk)
    return chunks


def extract_keybert_keywords(
    kw_model, texts: dict[str, str]
) -> dict[str, list[tuple[str, float]]]:
    """Extract keywords per file via KeyBERT."""
    results = {}
    for path_str, text in texts.items():
        if len(text.strip()) < 50:
            results[path_str] = []
            continue
        try:
            kws = kw_model.extract_keywords(
                text[:10000],
                keyphrase_ngram_range=(1, 3),
                stop_words='english',
                top_n=12,
                use_maxsum=False,
                nr_candidates=20,
            )
            results[path_str] = [(kw.strip(), float(score)) for kw, score in kws]
        except Exception:
            results[path_str] = []
    return results


def extract_ner_entities(
    nlp, texts: dict[str, str]
) -> dict[str, list[tuple[str, str, float]]]:
    """Extract named entities per file via spaCy NER."""
    results = {}
    target_labels = {'ORG', 'PRODUCT', 'GPE', 'PERSON', 'WORK_OF_ART',
                     'LAW', 'EVENT', 'FAC', 'LOC'}
    for path_str, text in texts.items():
        ents: list[tuple[str, str, float]] = []
        if len(text.strip()) < 100:
            results[path_str] = ents
            continue
        try:
            doc = nlp(text[:100000])
            seen = set()
            for ent in doc.ents:
                if ent.label_ not in target_labels:
                    continue
                clean = ent.text.strip()
                if len(clean) < 3 or clean in seen:
                    continue
                seen.add(clean)
                # spaCy doesn't give per-entity confidence, use a heuristic
                conf = 0.85 if ent.label_ in ('ORG', 'PERSON', 'GPE') else 0.75
                ents.append((clean, ent.label_, conf))
        except Exception:
            pass
        results[path_str] = ents
    return results


def build_nodes(
    files: list[Path],
    root: Path,
    keywords_by_file: dict[str, list[tuple[str, float]]],
    entities_by_file: dict[str, list[tuple[str, str, float]]],
    frontmatter_by_file: dict[str, dict],
) -> list[dict]:
    """Build node list from files, keywords, and entities."""
    nodes: list[dict] = []
    seen_ids: set[str] = set()

    for fp in files:
        path_str = str(fp)
        rel_str = str(fp.relative_to(root))
        stem = stem_from_path(fp, root)
        fm = frontmatter_by_file.get(path_str, {})

        # File-level source node
        file_node_id = stem
        if file_node_id not in seen_ids:
            seen_ids.add(file_node_id)
            nodes.append({
                'id': file_node_id,
                'label': fp.name,
                'file_type': (
                    'code'
                    if (fp.suffix.lower() in CODE_EXTS
                        or fp.name.lower() in CODE_FILENAMES)
                    else 'document'
                ),
                'source_file': rel_str,
                'source_location': None,
                'source_url': fm.get('source_url'),
                'captured_at': fm.get('captured_at'),
                'author': fm.get('author'),
                'contributor': fm.get('contributor'),
            })

        # Keyword concept nodes
        for kw, score in keywords_by_file.get(path_str, []):
            node_id = f'{stem}_{normalize_id(kw)}'
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            nodes.append({
                'id': node_id,
                'label': kw,
                'file_type': 'concept',
                'source_file': rel_str,
                'source_location': None,
                'source_url': fm.get('source_url'),
                'captured_at': fm.get('captured_at'),
                'author': fm.get('author'),
                'contributor': fm.get('contributor'),
            })

        # NER entity concept nodes
        for ent_text, ent_label, conf in entities_by_file.get(path_str, []):
            node_id = f'{stem}_{normalize_id(ent_text)}'
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            nodes.append({
                'id': node_id,
                'label': f'{ent_text} ({ent_label})',
                'file_type': 'concept',
                'source_file': rel_str,
                'source_location': None,
                'source_url': fm.get('source_url'),
                'captured_at': fm.get('captured_at'),
                'author': fm.get('author'),
                'contributor': fm.get('contributor'),
            })

    return nodes


def build_edges(
    files: list[Path],
    root: Path,
    embeddings: dict[str, np.ndarray],
    keywords_by_file: dict[str, list[tuple[str, float]]],
    entities_by_file: dict[str, list[tuple[str, str, float]]],
    texts: dict[str, str],
    sim_threshold: float = 0.72,
) -> list[dict]:
    """Build edges: file→keyword, file→entity, cross-file similarity, co-occurrence."""
    from sklearn.metrics.pairwise import cosine_similarity

    edges: list[dict] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def add_edge(src, tgt, relation, conf, conf_score, source_file):
        key = (src, tgt, relation)
        if key in edge_keys:
            return
        edge_keys.add(key)
        try:
            source_file = str(Path(source_file).relative_to(root))
        except ValueError:
            pass
        edges.append({
            'source': src,
            'target': tgt,
            'relation': relation,
            'confidence': conf,
            'confidence_score': conf_score,
            'source_file': source_file,
            'source_location': None,
            'weight': 1.0,
        })

    # File → its own keywords (conceptually_related_to)
    for fp in files:
        path_str = str(fp)
        stem = stem_from_path(fp, root)
        file_node_id = stem
        for kw, score in keywords_by_file.get(path_str, []):
            kw_node_id = f'{stem}_{normalize_id(kw)}'
            conf_score = max(0.5, min(0.95, score))
            add_edge(file_node_id, kw_node_id, 'conceptually_related_to',
                     'INFERRED', round(conf_score, 2), path_str)

    # File → its own NER entities (references)
    for fp in files:
        path_str = str(fp)
        stem = stem_from_path(fp, root)
        file_node_id = stem
        for ent_text, ent_label, conf in entities_by_file.get(path_str, []):
            ent_node_id = f'{stem}_{normalize_id(ent_text)}'
            add_edge(file_node_id, ent_node_id, 'references',
                     'INFERRED', round(conf, 2), path_str)

    # Cross-file cosine similarity → semantically_similar_to
    path_list = [str(f) for f in files]
    if len(path_list) >= 2 and embeddings:
        emb_list = []
        valid_paths = []
        for p in path_list:
            if p in embeddings:
                emb_list.append(embeddings[p])
                valid_paths.append(p)
        if len(emb_list) >= 2:
            emb_matrix = np.array(emb_list)
            sim_matrix = cosine_similarity(emb_matrix)
            for i in range(len(valid_paths)):
                for j in range(i + 1, len(valid_paths)):
                    sim = float(sim_matrix[i][j])
                    if sim > sim_threshold:
                        fp_i = Path(valid_paths[i])
                        fp_j = Path(valid_paths[j])
                        stem_i = stem_from_path(fp_i, root)
                        stem_j = stem_from_path(fp_j, root)
                        add_edge(stem_i, stem_j, 'semantically_similar_to',
                                 'INFERRED', round(max(0.55, sim), 2),
                                 valid_paths[i])

    # Co-occurrence: shared keywords across files → references edges
    kw_map: dict[str, list[tuple[Path, str, float]]] = {}
    for fp in files:
        path_str = str(fp)
        stem = stem_from_path(fp, root)
        for kw, score in keywords_by_file.get(path_str, []):
            kw_norm = normalize_id(kw)
            kw_map.setdefault(kw_norm, []).append((fp, f'{stem}_{kw_norm}', score))
    for kw_norm, refs in kw_map.items():
        if len(refs) >= 2:
            for i in range(len(refs)):
                for j in range(i + 1, len(refs)):
                    fp_a, node_a, score_a = refs[i]
                    fp_b, node_b, score_b = refs[j]
                    avg_score = (score_a + score_b) / 2
                    add_edge(node_a, node_b, 'references',
                             'INFERRED', round(max(0.5, avg_score), 2),
                             str(fp_a))

    # Co-occurrence: shared NER entities across files
    ent_map: dict[str, list[tuple[Path, str]]] = {}
    for fp in files:
        path_str = str(fp)
        stem = stem_from_path(fp, root)
        for ent_text, ent_label, conf in entities_by_file.get(path_str, []):
            ent_norm = normalize_id(ent_text)
            ent_map.setdefault(ent_norm, []).append((fp, f'{stem}_{ent_norm}'))
    for ent_norm, refs in ent_map.items():
        if len(refs) >= 2:
            for i in range(len(refs)):
                for j in range(i + 1, len(refs)):
                    fp_a, node_a = refs[i]
                    fp_b, node_b = refs[j]
                    add_edge(node_a, node_b, 'references',
                             'INFERRED', 0.75, str(fp_a))

    return edges


def build_hyperedges(
    files: list[Path],
    root: Path,
    embeddings: dict[str, np.ndarray],
    texts: dict[str, str],
) -> list[dict]:
    """Cluster files by embedding similarity and create hyperedges for clusters."""
    from sklearn.cluster import HDBSCAN

    path_list = [str(f) for f in files]
    if len(path_list) < 3 or not embeddings:
        return []

    emb_list = []
    valid_paths = []
    for p in path_list:
        if p in embeddings:
            emb_list.append(embeddings[p])
            valid_paths.append(p)

    if len(emb_list) < 3:
        return []

    emb_matrix = np.array(emb_list)
    # sklearn HDBSCAN has no 'cosine' metric; L2-normalize so that
    # euclidean distance is monotonic in cosine distance
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb_matrix = emb_matrix / norms
    try:
        clusterer = HDBSCAN(min_cluster_size=3, metric='euclidean')
        labels = clusterer.fit_predict(emb_matrix)
    except Exception:
        return []

    clusters: dict[int, list[str]] = defaultdict(list)
    for idx, label in enumerate(labels):
        if label >= 0:
            fp = Path(valid_paths[idx])
            stem = stem_from_path(fp, root)
            clusters[label].append(stem)

    hyperedges = []
    for label, node_ids in clusters.items():
        if len(node_ids) < 3:
            continue
        hyperedges.append({
            'id': f'cluster_{label}',
            'label': f'Document Cluster {label}',
            'nodes': node_ids,
            'relation': 'participate_in',
            'confidence': 'INFERRED',
            'confidence_score': 0.75,
            'source_file': '',
        })

    return hyperedges


def run_extraction(
    directory: str,
    model_name: str = 'all-MiniLM-L6-v2',
    sim_threshold: float = 0.72,
    verbose: bool = True,
) -> dict:
    """
    Main pipeline: extract ASTify-compatible semantic graph from readable files.

    Returns dict with 'nodes', 'edges', 'hyperedges', 'input_tokens', 'output_tokens'.
    """
    root = Path(directory).resolve()
    if not root.exists():
        raise FileNotFoundError(f'Directory not found: {root}')

    # Step 1: Discover files
    if verbose:
        print(f'Scanning: {root}')
    files = detect_files(root)
    if not files:
        if verbose:
            print('No readable text or PDF files found.')
        return {'nodes': [], 'edges': [], 'hyperedges': [],
                'input_tokens': 0, 'output_tokens': 0,
                'schema_version': 2,
                'structural_parser': 'tree-sitter'}

    if verbose:
        print(f'Found {len(files)} readable files')
        for f in files:
            print(f'  {f.relative_to(root)}')

    # Step 2: Read all text content
    if verbose:
        print('\nReading files...')
    texts: dict[str, str] = {}
    frontmatter_by_file: dict[str, dict] = {}
    skipped = 0
    for fp in files:
        raw = read_file_text(fp)
        if not raw.strip():
            skipped += 1
            continue
        fm, body = read_frontmatter(raw)
        texts[str(fp)] = body
        frontmatter_by_file[str(fp)] = fm
    if verbose and skipped:
        print(f'Skipped {skipped} empty/unreadable files')

    if not texts:
        if verbose:
            print('No readable content found.')
        return {'nodes': [], 'edges': [], 'hyperedges': [],
                'input_tokens': 0, 'output_tokens': 0,
                'schema_version': 2,
                'structural_parser': 'tree-sitter'}

    # Step 3: Load models
    if verbose:
        print(f'\nLoading embedding model: {model_name}')
    from sentence_transformers import SentenceTransformer
    encoder = SentenceTransformer(model_name)

    if verbose:
        print('Loading spaCy NER model: en_core_web_sm')
    import spacy
    try:
        nlp = spacy.load('en_core_web_sm')
    except OSError:
        if verbose:
            print('  Downloading en_core_web_sm...')
        spacy.cli.download('en_core_web_sm')
        nlp = spacy.load('en_core_web_sm')

    # Step 4: Embeddings
    if verbose:
        print('\nGenerating embeddings...')
    embeddings: dict[str, np.ndarray] = {}
    path_list = list(texts.keys())
    for path_str in path_list:
        body = texts[path_str]
        if len(body) > 12000:
            body = body[:12000]
        emb = encoder.encode(body, show_progress_bar=False)
        embeddings[path_str] = emb.astype(np.float32)

    # Step 5: Keyword extraction via KeyBERT
    if verbose:
        print('Extracting keywords...')
    from keybert import KeyBERT
    kw_model = KeyBERT(model=encoder)
    keywords_by_file = extract_keybert_keywords(kw_model, texts)
    total_kw = sum(len(v) for v in keywords_by_file.values())
    if verbose:
        print(f'  {total_kw} keywords extracted')

    # Step 6: NER via spaCy
    if verbose:
        print('Running named entity recognition...')
    entities_by_file = extract_ner_entities(nlp, texts)
    total_ent = sum(len(v) for v in entities_by_file.values())
    if verbose:
        print(f'  {total_ent} entities extracted')

    # Step 7: Build nodes
    if verbose:
        print('Building nodes...')
    nodes = build_nodes(files, root, keywords_by_file,
                        entities_by_file, frontmatter_by_file)
    symbol_nodes, structural_edges = extract_code_symbols(
        [fp for fp in files if (
            fp.suffix.lower() in SYMBOL_CODE_EXTS
            or fp.name.lower() in CODE_FILENAMES
        )],
        root,
        texts,
    )
    nodes.extend(symbol_nodes)
    if verbose:
        ast_symbols = sum(
            node.get('parser') == 'tree-sitter' for node in symbol_nodes
        )
        heuristic_symbols = sum(
            node.get('parser') == 'heuristic' for node in symbol_nodes
        )
        print(
            f'  {len(nodes)} nodes ({ast_symbols} AST symbols, '
            f'{heuristic_symbols} heuristic symbols)'
        )

    # Step 8: Build edges
    if verbose:
        print('Building edges...')
    edges = build_edges(files, root, embeddings,
                        keywords_by_file, entities_by_file, texts,
                        sim_threshold=sim_threshold)
    edges.extend(structural_edges)
    if verbose:
        print(f'  {len(edges)} edges ({len(structural_edges)} structural)')

    # Step 9: Build hyperedges
    if verbose:
        print('Clustering for hyperedges...')
    hyperedges = build_hyperedges(files, root, embeddings, texts)
    if verbose:
        print(f'  {len(hyperedges)} hyperedges')

    # Step 10: Output
    result = {
        'nodes': nodes,
        'edges': edges,
        'hyperedges': hyperedges,
        'input_tokens': 0,
        'output_tokens': 0,
        'schema_version': 2,
        'structural_parser': 'tree-sitter',
    }

    if verbose:
        print(f'\nDone. {len(nodes)} nodes, {len(edges)} edges, '
              f'{len(hyperedges)} hyperedges')
        print('Tokens used: 0 (all local computation)')

    return result

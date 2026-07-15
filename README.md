# ASTify

Embedding-based knowledge graph extraction — zero AI tokens, Graphify-compatible output.

Replaces LLM semantic extraction with local embeddings, keyword analysis, and named entity recognition. Produces the same `.graphify_semantic.json` format that Graphify's merge/build/cluster/export pipeline consumes.

## How It Works

```
Documents (md, txt, pdf, etc.)
    │
    ├─► sentence-transformers → embeddings → cosine similarity edges
    ├─► KeyBERT → keyword extraction → concept nodes
    ├─► spaCy NER → named entity nodes
    ├─► HDBSCAN → embedding clusters → hyperedges
    └─► co-occurrence analysis → references edges
```

## Install

```bash
pip install ASTify
# or:
pip install -e .
```

Windows, macOS, Linux. CPU only — no GPU required.

**spaCy model (first run only):**

```bash
python -m spacy download en_core_web_sm
```

## Usage

```bash
# Quick: process current directory
python run.py .

# Process specific directory
python run.py /path/to/project

# Output to Graphify-compatible path
python run.py /path/to/project --astify-path graphify-out/.graphify_semantic.json

# Multilingual model
python run.py /path/to/project -m paraphrase-multilingual-MiniLM-L12-v2

# Adjust similarity threshold (default 0.72)
python run.py /path/to/project -t 0.80

# Quiet mode
python run.py /path/to/project -q
```

### CLI

```bash
embedgraph /path/to/project [--output out.json] [--model all-MiniLM-L6-v2]
```

## Output Format

Graphify-compatible `.graphify_semantic.json`:

```json
{
  "nodes": [{
    "id": "docs_auth_jwt",
    "label": "JWT Tokens",
    "file_type": "concept",
    "source_file": "/path/to/auth.md"
  }],
  "edges": [{
    "source": "docs_auth",
    "target": "docs_auth_jwt",
    "relation": "conceptually_related_to",
    "confidence": "INFERRED",
    "confidence_score": 0.85
  }],
  "hyperedges": [],
  "input_tokens": 0,
  "output_tokens": 0
}
```

## Comparison with Graphify LLM Extraction

| Edge Type | Graphify (LLM) | ASTify (embeddings) |
|-----------|---------------|---------------------|
| `calls` | AST (deterministic) | Same |
| `conceptually_related_to` | LLM | KeyBERT keywords |
| `references` | LLM | spaCy NER + co-occurrence |
| `semantically_similar_to` | LLM | Cosine similarity |
| `implements`, `cites`, `rationale_for` | LLM | Not supported |
| Hyperedges | LLM | HDBSCAN clusters |
| Tokens per run | 50K-800K | **0** |

## Dependencies

- `sentence-transformers` — text embeddings
- `spaCy` — named entity recognition
- `KeyBERT` — keyword extraction
- `scikit-learn` — cosine similarity, HDBSCAN clustering
- `PyMuPDF` — PDF text extraction
- `hnswlib` — fast vector similarity (optional)
- `PyYAML` — frontmatter parsing

## License

MIT

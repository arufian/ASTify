# ASTify

Embedding-based knowledge graph extraction — zero AI tokens.

Replaces LLM semantic extraction with local embeddings, keyword analysis, and named entity recognition. Fully self-contained: extract, build, query, visualize — no API keys, no token costs.

## Install

```bash
# uv (recommended)
uv tool install astify --from git+https://github.com/arufian/ASTify

# or pip
pip install git+https://github.com/arufian/ASTify

# spaCy model (first run auto-downloads, or manual)
python -m spacy download en_core_web_sm
```

Windows, macOS, Linux. CPU only — no GPU required.

## Quick Start

```bash
# Full pipeline: detect → extract → build → report → html
astify /path/to/project

# Step by step
astify detect .
astify extract .
astify build .
astify report .
astify html .

# Query the graph
astify query "how does authentication work"
astify query "data flow between services" --dfs
astify path "JWT" "Redis"
astify explain "AuthService"
```

## How It Works

```
Readable files (source code, XML, YAML, docs, PDFs, any text extension)
    │
    ├─► sentence-transformers → embeddings → cosine similarity edges
    ├─► KeyBERT → keyword extraction → concept nodes
    ├─► spaCy NER → named entity nodes
    ├─► HDBSCAN → embedding clusters → hyperedges
    └─► co-occurrence analysis → references edges

Then: NetworkX graph → Louvain community detection → god nodes → report → HTML
```

## Output

ASTify scans file content, not only extension allowlists. Known programming
languages and metadata formats are classified as code; unfamiliar extensions
and extensionless files are included when their content is readable text.
Binary files, hidden paths, dependencies, build outputs, and ASTify/Graphify
output directories are skipped.

```
astify-out/
├── .semantic.json    # raw extraction (Graphify-compatible)
├── graph.json         # NetworkX node-link graph
├── analysis.json      # communities, cohesion, gods, surprises
├── GRAPH_REPORT.md    # human-readable audit report
└── graph.html         # interactive visualization
```

## Comparison with Graphify LLM Extraction

| Edge Type | Graphify (LLM) | ASTify (embeddings) |
|-----------|---------------|---------------------|
| `calls` | AST | N/A (code-focused) |
| `conceptually_related_to` | LLM | KeyBERT keywords |
| `references` | LLM | spaCy NER + co-occurrence |
| `semantically_similar_to` | LLM | Cosine similarity |
| `implements`, `cites`, `rationale_for` | LLM | Not supported |
| Hyperedges | LLM | HDBSCAN clusters |
| Tokens per run | 50K-800K | **0** |

## Coding Agent Integration

Invoke via `/astify` in Claude Code, OpenCode, or other agent tools:

```
/astify .                       # full pipeline
/astify query "how does X work" # query existing graph
/astify path "A" "B"            # shortest path
/astify explain "X"             # node details
```

Skill auto-installs via `uv tool install` if not present.

## Dependencies

- `sentence-transformers` — text embeddings
- `spaCy` — named entity recognition
- `KeyBERT` — keyword extraction
- `networkx` — graph building + traversal
- `scikit-learn` — cosine similarity + HDBSCAN
- `python-louvain` — community detection
- `pyvis` — HTML visualization
- `PyMuPDF` — PDF extraction
- `PyYAML` — frontmatter parsing

## License

MIT

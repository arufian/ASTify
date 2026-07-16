# ASTify

Tree-sitter AST + embedding knowledge graph extraction — zero AI tokens.

Combines real code structure with local embeddings, keyword analysis, and named
entity recognition. Runs locally without API keys or AI-token costs after
dependencies and local NLP/embedding models are available. First use may
download those models.

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
    ├─► Tree-sitter AST (Apex, JS, TS/TSX) → symbols + EXTRACTED edges
    ├─► syntax fallback (other code) → HEURISTIC edges
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

Tree-sitter parses Apex, JavaScript, TypeScript, and TSX into class, method,
function, call, constructor, and assignment nodes with line-and-column
locations. Structural `defines`, `calls`, `resolves_to`, `instantiates`, and
`assigns` edges from those ASTs are marked `EXTRACTED`. Explicit Salesforce
`@salesforce/apex/Class.method` imports resolve JavaScript calls to Apex methods
across files.

Other programming extensions use a language-tolerant syntax fallback. Those
edges are marked `HEURISTIC`, never `EXTRACTED`, so query output exposes the
lower assurance level.

Identifier-aware query expansion preserves CamelCase and snake_case symbols,
while structural matches rank ahead of embedding-only concepts.
Minified/generated bundles and identifiers found only inside comments or string
literals are excluded from structural extraction.

Existing graphs built before schema version 2 must be rebuilt. Querying one
prints a warning with the required commands.

## Query Scope and Limits

- Exact symbol, definition, constructor, assignment, and call queries are
  structural for Apex, JavaScript, TypeScript, and TSX.
- Topic and architecture discovery still uses `INFERRED` embedding/NLP edges.
- ASTify is not a compiler or language server. Dynamic dispatch, reflection,
  runtime dependency injection, and ambiguous unimported cross-file calls may
  remain unresolved or `INFERRED`.
- Unsupported languages remain useful for coarse discovery and heuristic
  symbol navigation, but precision is lower than Tree-sitter-backed languages.
- If direct structural matches are absent, use source search or a language
  server rather than treating embedding similarity as an exact answer.

```
astify-out/
├── .semantic.json    # raw extraction (Graphify-compatible)
├── graph.json         # NetworkX node-link graph
├── analysis.json      # communities, cohesion, gods, surprises
├── GRAPH_REPORT.md    # human-readable audit report
└── graph.html         # interactive visualization
```

## Comparison with Graphify LLM Extraction

| Edge Type | Graphify (LLM) | ASTify |
|-----------|---------------|---------------------|
| `defines`, `calls`, `resolves_to`, `instantiates`, `assigns` | AST | Tree-sitter AST (`EXTRACTED`) |
| Structural fallback | N/A | Syntax scan (`HEURISTIC`) |
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
- `tree-sitter-language-pack` — bundled Apex, JavaScript, TypeScript, and TSX parsers

## License

MIT

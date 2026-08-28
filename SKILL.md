---
name: ASTify
description: "Use for codebase topic discovery, for symbol/call navigation when an ASTify schema-v2 graph exists, and for locating literal strings (placeholder values, UI labels, Japanese/CJK text) — query runs an EXACT source scan automatically when the graph has no structural match. Tree-sitter provides exact Apex, JavaScript, TypeScript, and TSX structure; other code uses clearly labeled heuristic extraction, while metadata/docs use inferred local embeddings. Supports extract, build, query, path, and explain."
---

# /astify

Turn any folder of readable files into a navigable knowledge graph using
Tree-sitter code ASTs plus local embeddings — no API keys, no AI-token costs.
Produces SQLite graph storage, bounded summary JSON, GRAPH_REPORT.md, and
interactive HTML.

## Usage

```
/astify                                              # full pipeline on current directory
/astify <path>                                       # full pipeline on specific path
/astify query "<question>"                           # BFS traversal — broad context
/astify query "<question>" --dfs                     # DFS — trace a specific path
/astify query "<question>" --budget 1500             # cap output at N tokens
/astify query "konoformat1" --literal                # force EXACT file:line source scan
/astify query "<question>" --no-literal              # graph only, skip the source scan
/astify path "AuthModule" "Database"                 # shortest path between two concepts
/astify explain "JWT"                                # plain-language explanation of a node
/astify extract <path> --model all-MiniLM-L6-v2      # custom embedding model
/astify <path> --max-neighbors 20 --batch-size 32    # bounded large-corpus run
```

## What ASTify is for

Drop any folder of source code, XML, YAML, metadata, docs, or PDFs into ASTify
and get a queryable knowledge graph. Apex, JavaScript, TypeScript, and TSX use
real Tree-sitter AST extraction. Other code uses `HEURISTIC` syntax extraction;
metadata and documents use `INFERRED` local embeddings/NLP. Unknown extensions
and extensionless readable text remain supported for coarse semantic discovery.

## What You Must Do When Invoked

**Fast path — existing graph:** Before broad codebase exploration, check whether
`astify-out/graph.json` or `astify-out/astify.db` exists. If either does and the
request concerns codebase topics or symbols, jump to `## For /astify query` and
run one query.

- If query warns graph predates Tree-sitter schema v2, do not trust it for exact
  code navigation. Fall back to `rg` and recommend rebuilding.
- If the question returns no direct `symbol` matches or only `INFERRED`
  concept edges, query automatically runs an EXACT source scan for the literal
  parts of the question (quoted strings, identifiers with digits/underscores/
  CamelCase, CJK runs) and prints `path:line` hits. Use those, not the
  `INFERRED` rows. Fall back to `rg` only when that scan also finds nothing.
- Never present embedding similarity as proof of a definition, call, mutation,
  or exact source line.

If no path was given, use `.` (current directory).

Follow these steps in order. Do not skip steps.

### Step 1 — Ensure astify is installed

```bash
if ! command -v astify >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
        uv tool install astify --from git+https://github.com/arufian/ASTify
    else
        echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
        echo "Or: pip install git+https://github.com/arufian/ASTify"
        exit 1
    fi
fi
```

If astify is installed, print nothing and move to Step 2.

### Step 2 — Detect files

```bash
astify detect <path>
```

Replace `<path>` with the directory to scan. Present a clean summary:

```
Corpus: N files · ~M words
  code:     N files
  docs:     N files
  papers:   N files
```

If no readable files found: "No supported files found in [path]." and stop.

### Step 3 — Extract entities and relationships

```bash
astify extract <path>
```

This runs Tree-sitter AST extraction for Apex/JavaScript/TypeScript/TSX,
heuristic extraction for other code, batched sentence-transformer embeddings,
KeyBERT, spaCy NER, bounded top-K cosine similarity, and canonical concept
hubs. AST edges
are `EXTRACTED`; fallback syntax edges are `HEURISTIC`; embedding/NLP edges are
`INFERRED`. All local CPU — zero AI tokens.

### Step 4 — Build graph, cluster, analyze

```bash
astify build <path>
```

Generates:
- `astify-out/astify.db` — primary extraction and detailed query graph
- `astify-out/graph.json` — full graph below safe limits
- `astify-out/graph-summary.json` — projected analysis/visualization graph
- `astify-out/analysis.json` — communities, cohesion, god nodes, surprises, questions

Small graphs use exact betweenness, medium graphs use sampled betweenness, and
large graphs rank cross-community bridges. Do not force `--full-analysis` on a
large corpus unless the user explicitly accepts the runtime risk.

### Step 5 — Generate outputs

```bash
astify report <path>
astify html <path>
```

Always generate GRAPH_REPORT.md and HTML unless `--no-viz` is passed. HTML
automatically aggregates large graphs by community.

### Step 6 — Report results

Tell the user:

```
Graph complete. Outputs in PATH_TO_DIR/astify-out/

  graph.html          — interactive graph, open in browser
  GRAPH_REPORT.md     — audit report
  astify.db           — detailed query graph and extraction store
  graph-summary.json  — bounded analysis graph
  graph.json          — full raw graph data (small graphs only)
  analysis.json       — communities, god nodes, metrics
```

Then paste these sections from GRAPH_REPORT.md directly into the chat:
- God Nodes
- Surprising Connections
- Suggested Questions

Then immediately offer to explore. Pick the single most interesting suggested question from the report and ask:

> "The most interesting question this graph can answer: **[question]**. Want me to trace it?"

If the user says yes, run `/astify query "[question]"` and walk them through the answer.

---

## For /astify query

When `astify-out/graph.json` or `astify-out/astify.db` exists and the user asks
a question, answer from the graph:

```bash
astify query "<question>"
```

Inspect output confidence:

- `EXTRACTED` + `symbol` + source location: safe structural evidence.
- `HEURISTIC`: useful lead, verify in source.
- `INFERRED` concept-only result: coarse topic signal, not exact code evidence.

- `LITERAL matches [EXACT source scan]`: real file content at `path:line`.
  Safe to act on; it is the same evidence `rg` would give.

Literal strings the graph cannot index — a placeholder value like
`konoformat1`, a Japanese UI label like `見積項目マッピング設定`, a quoted
message — are handled by the automatic source scan. Force it with `--literal`
when you want file:line evidence alongside a graph answer:

```bash
astify query "change the placeholder konoformat1 into format1" --literal
```

Fall back to `rg` only if both the traversal and the literal scan come back
empty. Do not spend multiple graph round trips trying to force an embedding
result.

For deep traversal:
```bash
astify query "<question>" --dfs
```

For budget control:
```bash
astify query "<question>" --budget 3000
```

---

## For /astify path

Find shortest path between two concepts:

```bash
astify path "NODE_A" "NODE_B"
```

Explain what each hop means in plain language.

---

## For /astify explain

Explain a single node and all its connections:

```bash
astify explain "NODE_NAME"
```

---

## For /astify extract (standalone)

Run extraction only. SQLite is default; request JSON for downstream use:

```bash
astify extract <path> --json
astify extract <path> -o output.json
astify extract <path> --graphify-path graphify-out/.graphify_semantic.json
```

Output format is Graphify-compatible — use with `graphify build` if you need Graphify's visualization pipeline.

---

## Honesty Rules

- 0 AI tokens consumed. All extraction is local embedding computation.
- Embedding-based edges are tagged INFERRED with confidence scores.
- Cross-file similarity uses cosine threshold 0.72 and at most 20 neighbors per
  file by default.
- Never invent an edge. The graph only contains what extraction found.

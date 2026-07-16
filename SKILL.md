---
name: ASTify
description: "MUST use BEFORE any codebase exploration (Grep/Glob/Read/Explore) when astify-out/ exists — for questions AND for edit/fix/feature/refactor tasks that need locating or understanding code first. Also for any question about a codebase, its architecture, file relationships, or project content. Turns source code, metadata, config, documents, and PDFs into a queryable knowledge graph using local embeddings (zero AI tokens). Supports extract, build, query, path, and explain."
---

# /astify

Turn any folder of readable files into a navigable knowledge graph using deterministic code-symbol extraction plus local embeddings — no API keys, no token costs. Produces graph.json, GRAPH_REPORT.md, and interactive HTML.

## Usage

```
/astify                                              # full pipeline on current directory
/astify <path>                                       # full pipeline on specific path
/astify query "<question>"                           # BFS traversal — broad context
/astify query "<question>" --dfs                     # DFS — trace a specific path
/astify query "<question>" --budget 1500             # cap output at N tokens
/astify path "AuthModule" "Database"                 # shortest path between two concepts
/astify explain "JWT"                                # plain-language explanation of a node
/astify extract <path> --model all-MiniLM-L6-v2      # custom embedding model
```

## What ASTify is for

Drop any folder of source code, XML, YAML, metadata, docs, or PDFs into ASTify and get a queryable knowledge graph. Unknown extensions and extensionless readable text are supported. Persistent across sessions. Community detection surfaces cross-file connections. Zero AI tokens — all local CPU computation.

## What You Must Do When Invoked

**Fast path — existing graph:** Before doing anything else, check whether `astify-out/graph.json` exists. If it does AND the user's request is a natural-language question about the codebase (e.g. "How does X work?", "What connects to Y?"): **skip Steps 1–4 entirely and jump straight to `## For /astify query`.** Run `astify query "<question>"` immediately. Do not ask the user to confirm.

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

This runs deterministic code-symbol and source-line extraction, sentence-transformer embeddings, KeyBERT keyword extraction, spaCy NER, cross-file cosine similarity, and co-occurrence analysis. Structural edges are `EXTRACTED`; embedding and NLP edges are `INFERRED`. All local CPU — zero tokens.

### Step 4 — Build graph, cluster, analyze

```bash
astify build <path>
```

Generates:
- `astify-out/graph.json` — NetworkX node-link graph data
- `astify-out/analysis.json` — communities, cohesion, god nodes, surprises, questions

### Step 5 — Generate outputs

```bash
astify report <path>
astify html <path>
```

Always generate GRAPH_REPORT.md and HTML unless `--no-viz` is passed.

### Step 6 — Report results

Tell the user:

```
Graph complete. Outputs in PATH_TO_DIR/astify-out/

  graph.html          — interactive graph, open in browser
  GRAPH_REPORT.md     — audit report
  graph.json          — raw graph data
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

When `astify-out/graph.json` already exists and the user asks a question, answer from the graph:

```bash
astify query "<question>"
```

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

Run extraction only, output semantic.json for downstream use:

```bash
astify extract <path> -o output.json
astify extract <path> --graphify-path graphify-out/.graphify_semantic.json
```

Output format is Graphify-compatible — use with `graphify build` if you need Graphify's visualization pipeline.

---

## Honesty Rules

- 0 AI tokens consumed. All extraction is local embedding computation.
- Embedding-based edges are tagged INFERRED with confidence scores.
- Cross-file similarity edges use cosine similarity threshold (default 0.72).
- Never invent an edge. The graph only contains what extraction found.

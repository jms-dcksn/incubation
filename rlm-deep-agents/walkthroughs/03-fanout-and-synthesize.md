# 03 — Fan-out and synthesize (with programmatic tool calling)

**Source:** [`examples/fanout_and_synthesize.py`](../src/rlm_deep_agents/examples/fanout_and_synthesize.py)
· **Run:** `uv run rlm-fanout`

> The agent dispatches the same kind of work across many items in parallel, then
> combines the results.

**Reach for it when:** independent units of work should each get the same
treatment and roll up into one report — code review across a directory, analyzing
a batch of documents, running the same check across many services.

This example does one extra thing the quickstart didn't: it **discovers** the
work items from interpreter code using **programmatic tool calling (PTC)**.

## What we configure

One `reviewer` subagent — plus a PTC allowlist and a seeded virtual filesystem:

```python
agent = build_agent(SUBAGENTS, ptc=["glob", "read_file"])
run_workflow(agent, PROMPT, files=SOURCE_TREE)
```

- `ptc=["glob", "read_file"]` exposes those tools inside the interpreter as
  `tools.glob(...)` / `tools.readFile(...)`. **PTC is off by default** — you opt
  in with an explicit allowlist, and it's a permission boundary, so keep it
  narrow.
- `files=SOURCE_TREE` seeds the Deep Agents virtual filesystem (from
  [`sample_data.SOURCE_TREE`](../src/rlm_deep_agents/sample_data.py)) with a few
  route files, a couple carrying deliberate SQL-injection / missing-auth bugs, so
  `glob` has something to find and the reviewer has something to flag.

## What we ask

```
1. Use tools.glob to find files matching "src/routes/**/*.js".
2. Dispatch one `reviewer` subagent per file, in parallel, via task().
3. Merge findings, sort by severity (high first), drop duplicates, and return
   a single prioritized report.
```

## What the agent writes

Discovery happens with a tool call *from code*, then the results feed straight
into the fan-out — no round trip back to the model in between:

```javascript
// 1. Discover the work set with a tool call from interpreter code (PTC)
const files = (await tools.glob({ pattern: "src/routes/**/*.js" }))
  .split("\n")
  .filter(Boolean);

// 2. Fan out one reviewer per file, in parallel
const reviews = await Promise.all(
  files.map((file) =>
    task({
      description: `Review ${file} for injection/auth issues. Cite line numbers.`,
      subagentType: "reviewer",
      responseSchema: issuesSchema,   // -> { issues: [{ file, line, severity, description }] }
    })
  )
);

// 3. Synthesize in code: flatten, sort, dedupe
const issues = reviews.flatMap((r) => r.issues);
issues.sort((a, b) => rank(b.severity) - rank(a.severity));
issues;
```

## Why PTC matters here

Without PTC, the model would have to call `glob` as a normal tool, read the file
list back into its context, *then* start dispatching — an extra model turn, and
the whole file list sits in context. With PTC the discovery result stays in a JS
variable and flows directly into `Promise.all`. The model never sees the
intermediate list; it only sees the final prioritized report.

This is the general recipe the blogs call out: **use `tools.*` to discover/filter
inputs, then dispatch subagents with `task()`.** PTC handles the plumbing;
`task()` handles the judgement.

## Why the fan-out matters

- **One combined report from many independent reviews.** Each file is reviewed in
  isolation (clean context per reviewer), and the synthesis — sort by severity,
  drop duplicates — is deterministic code, not a model summarization pass that
  might reorder or forget findings.
- **Coverage scales with the tree.** Add ten more route files and the same code
  reviews all of them.

## A note on tool names

`glob` and `read_file` are Deep Agents' built-in virtual-filesystem tools. If a
future version renames them, update the `ptc=[...]` allowlist to match. Inside
the interpreter they're always camelCased: `read_file` → `tools.readFile`.

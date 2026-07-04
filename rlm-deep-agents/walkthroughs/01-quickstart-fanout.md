# 01 — Quickstart: fan-out

**Source:** [`examples/quickstart_fanout.py`](../src/rlm_deep_agents/examples/quickstart_fanout.py)
· **Run:** `uv run rlm-quickstart`

The smallest possible dynamic-subagent program, and the example both blog posts
open with: **one subagent per page of a document**, dispatched in parallel from a
single loop instead of N separate tool calls.

> The canonical example: one subagent per page of a 300-page document. Rather
> than calling the subagent tool 300 times, the agent writes a loop.

## What we configure

A single subagent — a `summarizer`:

```python
SUBAGENTS = [
    {
        "name": "summarizer",
        "description": "Summarizes a single page of text into one tight sentence.",
        "system_prompt": (
            "You are a summarizer. Given the text of one page, return a single "
            "clear sentence capturing its main point. No preamble."
        ),
    }
]
```

That's it — `build_agent(SUBAGENTS)` attaches the code interpreter, and because a
subagent exists, the interpreter exposes `task()`.

> You could even skip defining a subagent: Deep Agents ships a built-in
> `general-purpose` subagent that handles basic fan-out. We define `summarizer`
> so the role is explicit and the transcript is easy to read.

## What we ask

The prompt hands the agent the pages inline and asks for a **workflow** (the
trigger word):

```
Run a workflow that summarizes every page below, one summarizer subagent per
page dispatched in parallel with task(), then combine the sentences into a
single ordered summary of the whole document.
```

## What the agent writes

Given a "workflow" request over many items, the model writes something close to
the canonical loop inside `eval`:

```javascript
const summaries = await Promise.all(
  pages.map((page, i) =>
    task({
      description: `Summarize this page:\n${page}`,
      subagentType: "summarizer",
    })
  )
);
// summaries is aligned to page order because Promise.all preserves order
summaries.map((s, i) => `Page ${i}: ${s}`).join("\n");
```

## Why this matters

- **Coverage is structural.** `pages.map(...)` visits *every* page. Contrast with
  a turn-by-turn agent, which — asked to summarize 300 pages — tends to summarize
  a handful and declare victory. The loop removes that judgement call.
- **The orchestration is trivial to scale.** Five pages or five hundred, the code
  is identical. Only the input size changes.
- **Intermediate results stay out of the main context.** Each page's full text
  goes to a subagent; only the one-sentence summaries come back. The main model
  never has to hold all 300 pages at once.

This is the seed of every other pattern: hold work in a JS variable, dispatch
subagents with `task()`, combine results in code. The rest of the walkthroughs
are variations on that shape.

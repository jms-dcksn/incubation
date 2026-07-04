# Overview — dynamic subagents & RLMs in Deep Agents

This folder walks through every example in `src/rlm_deep_agents/examples/`. Read
this page first; it explains the shared machinery so the per-pattern walkthroughs
can focus on the pattern.

## The core shift

A **normal subagent** is dispatched by the main model, one tool call at a time.
The model decides "call the reviewer on `login.js`", waits for the result, then
decides the next call. That is fine for one or two delegations. It breaks when:

- you need to spawn **hundreds** of subagents (the model tends to sample a subset
  and call it done), or
- the orchestration is **conditional or multi-phase** (fan-out then verify then
  synthesize), which the model has to reproduce as a fragile sequence of turns.

A **dynamic subagent** is dispatched from **code**. You give the agent a code
interpreter, and instead of turn-by-turn tool calls the model writes a short
JavaScript program that calls a built-in `task()` global in loops, branches, and
`Promise.all` batches. Two things this buys you:

1. **Deterministic coverage at scale** — the loop visits every item, so coverage
   is a structural guarantee, not a prompt-engineering hope.
2. **Reliable complex orchestration** — fan-out + synthesis, multi-phase
   pipelines, and conditional branching are more reliable written once as code
   than reproduced as a sequence of model turns.

This is the **Recursive Language Model (RLM)** idea in its simplest form: *an
agent that writes code, and that code dispatches more agents.* An agent calling
itself recursively isn't capped by a single context window or boxed into a fixed
workflow.

## The two ingredients

Dynamic subagents need exactly two things:

1. **Subagents** to dispatch work to.
2. **A code interpreter** — a secure, lightweight runtime where the model writes
   and executes orchestration code. Deep Agents ships one based on
   [QuickJS](https://github.com/quickjs-ng/quickjs).

```python
from deepagents import create_deep_agent
from langchain_quickjs import CodeInterpreterMiddleware

agent = create_deep_agent(
    model="anthropic:claude-sonnet-5",
    subagents=[{
        "name": "reviewer",
        "description": "Reviews code for security issues, citing lines and severity",
        "system_prompt": "You are a security-focused code reviewer...",
    }],
    middleware=[CodeInterpreterMiddleware()],   # turns subagents into *dynamic* subagents
)
```

`CodeInterpreterMiddleware` adds an `eval` tool (the model writes JavaScript and
runs it) and — because the agent has subagents — exposes a `task()` global inside
the interpreter. In this repo, that construction is wrapped in
[`common.build_agent`](../src/rlm_deep_agents/common.py).

## The `task()` API

Inside interpreter code the model dispatches a subagent like this:

```javascript
const review = await task({
  description: "Review src/auth/login.ts for auth issues. Cite line numbers.",
  subagentType: "reviewer",
  responseSchema: {                       // optional
    type: "object",
    properties: {
      issues: { type: "array", items: { type: "object", properties: {
        file: { type: "string" }, line: { type: "number" },
        severity: { type: "string" }, description: { type: "string" },
      }}},
    },
  },
});

// With responseSchema, `review` is already a typed object — no JSON.parse.
const critical = review.issues.filter((i) => i.severity === "high");
```

- `description` — the prompt for the subagent.
- `subagentType` — which configured subagent to run (matches a `name` you passed
  to `create_deep_agent`).
- `responseSchema` *(optional)* — when provided, the resolved value is already a
  typed JavaScript object, ready to filter or pass to the next step.

Each `task()` runs a full agentic loop and resolves to the subagent's result.
Because `task()` runs from inside an already-running `eval`, it does **not** go
through the normal tool-calling path — so per-dispatch `interrupt_on` approvals
are not enforced. Gate the `eval` tool itself if you need approval before
orchestration runs.

## The "workflow" trigger word

The interpreter's system prompt treats the word **"workflow"** as a signal to
organize the work through the interpreter (dispatching subagents with `task()`
from code) rather than grinding through items one model-chosen tool call at a
time. Every prompt in this repo is phrased as *"Run a workflow that ..."*. For a
single, direct delegation you'd phrase the request plainly instead.

## Programmatic tool calling (PTC)

Orchestration often needs to *discover* or *filter* inputs before fanning out —
e.g. list the files to review. That's **programmatic tool calling**: expose an
allowlist of tools inside the interpreter under a `tools` namespace.

```python
middleware=[CodeInterpreterMiddleware(ptc=["glob", "read_file"])]
```

```javascript
const files = (await tools.glob({ pattern: "src/routes/**/*.js" }))
  .split("\n").filter(Boolean);
```

PTC is **off by default**; enable it with an explicit allowlist. Tool names are
converted to camelCase inside the interpreter (`web_search` → `tools.webSearch`).
Treat the allowlist as a permission boundary — only the
[fan-out example](./03-fanout-and-synthesize.md) uses it here.

## The six patterns

These aren't features you turn on — they're *shapes that fall out of the work*.
The agent settles into a different one as the task changes, and often composes
them.

| Pattern | Shape | Reach for it when | Walkthrough |
| --- | --- | --- | --- |
| Classify and act | Route each item to a specialist by type | Mixed inputs need different handling | [02](./02-classify-and-act.md) |
| Fan-out and synthesize | Same work across many items in parallel, then combine | Independent units, one combined report | [03](./03-fanout-and-synthesize.md) |
| Adversarial verification | Find, then independently verify before keeping | False positives are costly | [04](./04-adversarial-verification.md) |
| Generate and filter | Produce several options, score, keep the best | Exploring options beats one-shot | [05](./05-generate-and-filter.md) |
| Tournament | Head-to-head judging, winners advance | Subjective or relative criteria | [06](./06-tournament.md) |
| Loop until done | Repeat passes until one turns up nothing new | Scope is unknown, you want completeness | [07](./07-loop-until-done.md) |

Plus the [quickstart fan-out](./01-quickstart-fanout.md) (the simplest case) and
the [RLM long-context aggregation](./08-rlm-long-context.md) (the flagship of the
RLM post).

## How to read the code

Each example module has the same shape:

- `SUBAGENTS` — the specialist roles, as dicts (`name` / `description` /
  `system_prompt`). The **name** is what interpreter code passes as
  `subagentType`; the **description** tells the orchestrator which role to reach
  for.
- Some inline sample data (from `sample_data.py`).
- A `PROMPT` phrased as a *"workflow"* that describes the orchestration steps.
- `main()` — calls `build_agent(SUBAGENTS, ...)` then `run_workflow(agent, PROMPT)`.

`run_workflow` invokes the agent and pretty-prints the transcript, including the
`eval` calls — so you can literally read the orchestration JavaScript the model
wrote. If no API key is set it skips the call but still builds the agent, so the
wiring is always exercised.

> **A note on terminology (from the RLM post).** What Deep Agents ships is closer
> to *recursive agents* than to the RLM paper's exact shape: the recursive calls
> are subagents with their own tools and state, not plain LM calls, and you
> select slices to recurse on rather than loading the entire prompt into the
> interpreter. But the RLM paper is what motivated the capability — and a key
> perk is that the orchestrator and each subagent can run on **different models**
> (e.g. a frontier orchestrator with cheaper open-weight subagents).

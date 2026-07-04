# RLM exploration with Deep Agents

Small, runnable examples of **dynamic subagents** and **Recursive-Language-Model
(RLM)-style orchestration** in [LangChain Deep Agents](https://github.com/langchain-ai/deepagents),
driven by the QuickJS **code interpreter middleware**.

Based on two LangChain blog posts:

- [Introducing Dynamic Subagents in Deep Agents](https://www.langchain.com/blog/introducing-dynamic-subagents-in-deep-agents)
- [How to Use RLMs in Deep Agents](https://www.langchain.com/blog/how-to-use-rlms-in-deep-agents)

## The idea in one paragraph

A normal subagent is dispatched by the main model one tool call at a time. That
works at small scale and falls apart when you need to spawn hundreds of
subagents, or when orchestration is conditional or multi-phase. **Dynamic
subagents** fix this: you give the agent a code interpreter, and instead of
turn-by-turn tool calls the model writes a short JavaScript program that
dispatches subagents with a built-in `task()` global — using loops, branches, and
`Promise.all` for orchestration it's good at expressing as code. That is the
**RLM** idea in its simplest form: *an agent that writes code, and that code
dispatches more agents.* Coverage becomes a structural guarantee (the loop visits
every item) instead of a prompt-engineering hope, and heavy intermediate data
stays in interpreter variables instead of rotting the model's context.

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
    middleware=[CodeInterpreterMiddleware()],   # <- makes subagents *dynamic*
)
```

The model then writes something like this **inside the interpreter** when you ask
it for a *"workflow"*:

```javascript
const reviews = await Promise.all(
  files.map((file) =>
    task({ description: `Review ${file}`, subagentType: "reviewer" })
  )
);
```

## Setup

Requires Python `>=3.11` and [`uv`](https://docs.astral.sh/uv/).

```bash
cd rlm-deep-agents
uv sync                       # installs deepagents[quickjs] + langchain-quickjs

cp .env.example .env          # then edit .env:
#   RLM_MODEL=anthropic:claude-sonnet-5
#   ANTHROPIC_API_KEY=sk-...
```

`RLM_MODEL` uses LangChain's `provider:model` format, so you can point it at
OpenAI (`openai:gpt-5.5`), Google (`google_genai:gemini-3.5-flash`), etc. Install
the matching provider extra and set the matching key:

```bash
uv sync --extra anthropic      # or --extra openai / --extra google
```

> Every example still **constructs** its agent and prints the wiring even without
> an API key — it just skips the actual model call and tells you what to set.

## Running the examples

Each example is a self-contained pattern with a console-script entry point:

| Command | Pattern | Blog reference |
| --- | --- | --- |
| `uv run rlm-quickstart` | Fan-out (the canonical one-subagent-per-page loop) | Both, "Quickstart" |
| `uv run rlm-classify` | Classify and act | Dynamic Subagents |
| `uv run rlm-fanout` | Fan-out and synthesize (+ programmatic tool calling) | Dynamic Subagents |
| `uv run rlm-verify` | Adversarial verification | Dynamic Subagents |
| `uv run rlm-generate` | Generate and filter | Dynamic Subagents |
| `uv run rlm-tournament` | Tournament | Dynamic Subagents |
| `uv run rlm-loop` | Loop until done | Dynamic Subagents |
| `uv run rlm-longcontext` | RLM long-context aggregation (OOLONG-style) | How to Use RLMs |

Or run any module directly:

```bash
uv run python -m rlm_deep_agents.examples.classify_and_act
```

## Code walkthroughs

Every example has a step-by-step walkthrough in [`walkthroughs/`](./walkthroughs):

- [`00-overview.md`](./walkthroughs/00-overview.md) — how it all fits together, the
  `task()` API, and how to read the code
- [`01-quickstart-fanout.md`](./walkthroughs/01-quickstart-fanout.md)
- [`02-classify-and-act.md`](./walkthroughs/02-classify-and-act.md)
- [`03-fanout-and-synthesize.md`](./walkthroughs/03-fanout-and-synthesize.md)
- [`04-adversarial-verification.md`](./walkthroughs/04-adversarial-verification.md)
- [`05-generate-and-filter.md`](./walkthroughs/05-generate-and-filter.md)
- [`06-tournament.md`](./walkthroughs/06-tournament.md)
- [`07-loop-until-done.md`](./walkthroughs/07-loop-until-done.md)
- [`08-rlm-long-context.md`](./walkthroughs/08-rlm-long-context.md)

## Project layout

```
rlm-deep-agents/
├── pyproject.toml                     # uv project + console scripts
├── .env.example                       # RLM_MODEL + provider API key
├── src/rlm_deep_agents/
│   ├── common.py                      # build_agent(), run_workflow() helpers
│   ├── sample_data.py                 # inline datasets for the examples
│   └── examples/                      # one module per pattern
└── walkthroughs/                      # one markdown walkthrough per pattern
```

## How these map to the blogs

The six named patterns (classify-and-act, fan-out-and-synthesize, adversarial
verification, generate-and-filter, tournament, loop-until-done) come straight from
the "Introducing Dynamic Subagents" post — they're *shapes that fall out of the
work*, not features you toggle. The long-context example follows the "How to Use
RLMs" post: keep the working set and the aggregation in code, and use subagents
only for the judgement-heavy slices, so long inputs don't drift the model's
context.

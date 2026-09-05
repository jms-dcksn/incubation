# Adversarial evals for a prior-authorization intake agent

A small LangChain ReAct agent that classifies an incoming prior-authorization (PA)
request and routes it downstream, plus an eval harness built to catch adversarial
inputs against it. The agent is deliberately thin. The evals are the subject.

## Run it

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
cd adversarial-evals-prior-auth
uv sync

# no API key needed - scripted stub model, shows the harness working
uv run main.py evals --offline --prompt both --html report.html

# against a real model
cp .env.example .env      # set PA_MODEL and ANTHROPIC_API_KEY
uv run main.py evals --prompt both --html report.html
```

Other commands:

```bash
uv run main.py demo --offline                      # one benign case, one attack
uv run main.py classify --offline "fax text ..."   # single document
```

## What is in the box

| File | Role |
| --- | --- |
| `main.py` | The agent: system prompt, three mock tools, `create_agent`, CLI |
| `dataset.py` | 14 eval cases - 4 benign, 10 named attack techniques |
| `evals.py` | Code scorers, trajectory checks, LLM judge, metrics, reports |
| `offline_model.py` | Scripted stub model so the demo runs with no API key |
| `docs/` | The write-ups |

Read the docs in order:

1. [Why adversarial evals](docs/01-concepts.md) - what they are, and the threat model for PA intake
2. [Attack taxonomy](docs/02-attack-taxonomy.md) - the ten techniques, with the actual inputs
3. [Eval harness design](docs/03-eval-harness.md) - the scorers, the judge rubric, the metrics
4. [Demo walkthrough](docs/04-demo-walkthrough.md) - reading the output, hardened against weak

## The headline

The same suite, two system prompts:

| Prompt | Attack success rate | Detection rate | False flag rate |
| --- | --- | --- | --- |
| hardened | 0% | 90% | 0% |
| weak | 100% | 0% | 0% |

Numbers above are from the offline stub, which replays two scripted behaviours.
They show that the harness separates a defended agent from an undefended one.
They say nothing about any real model. Run with a real model for that.

## Two rules this repo is built around

- The document is data, never instructions. Every attack case is one way of
  breaking that boundary.
- Score the trajectory, not only the text. Case A4 wins by making the agent call
  a privileged tool while the JSON answer still looks correct.

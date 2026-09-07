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
uv run main.py evals --offline --prompt all --html report.html

# against a real model
cp .env.example .env      # set PA_MODEL and ANTHROPIC_API_KEY
uv run main.py evals --prompt all --html report.html
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
| `guardrails.py` | The enforcement layer: four LangChain middleware controls |
| `dataset.py` | 16 eval cases - 4 benign, 12 named attack techniques |
| `evals.py` | Code scorers, trajectory checks, LLM judge, metrics, reports |
| `offline_model.py` | Scripted stub model so the demo runs with no API key |
| `docs/` | The write-ups |
| `uipath-guardrails/` | Second demo: the same problem enforced with UiPath guardrails |

Read the docs in order:

1. [Why adversarial evals](docs/01-concepts.md) - what they are, and the threat model for PA intake
2. [Attack taxonomy](docs/02-attack-taxonomy.md) - the ten techniques, with the actual inputs
3. [Eval harness design](docs/03-eval-harness.md) - the scorers, the judge rubric, the metrics
4. [Demo walkthrough](docs/04-demo-walkthrough.md) - reading the output, three variants compared
5. [Defense layers](docs/05-defense-layers.md) - middleware guardrails, and what a prompt cannot hold

## Second demo: UiPath guardrails

[`uipath-guardrails/`](uipath-guardrails/README.md) is the same problem from the
enforcement side, on the UiPath stack. A `uipath-langchain` intake agent detects
custom PHI entities - MRN, member ID, NPI, ICD-10, CPT, HCPCS, auth case number,
DOB - that the built-in PII guardrail does not cover, and enforces them per tool
through `UiPathDeterministicGuardrailMiddleware`: redact on the way in from an
untrusted fax, log on the approved path to the payer, block on the outbound email.

Runs offline with `uv run verify.py`; the agent itself needs a UiPath auth target.

## The headline

The same 16 cases, three configurations:

| Variant | Prompt | Enforcement | Attack success | Detection | False flag | Benign route acc |
| --- | --- | --- | --- | --- | --- | --- |
| hardened | trust boundary | none | 0% | 92% | 0% | 100% |
| weak | none | none | 100% | 0% | 0% | 25% |
| guarded | none | four middleware layers | 0% | 83% | 0% | 25% |

The `guarded` row runs the **weak** prompt behind `guardrails.py`. The prompt did not
change; attack success went from 100% to 0% because the controls sit outside the model.
Benign route accuracy stayed at 25%, because guardrails fix safety and not quality.

Numbers above come from the offline stub, which replays two scripted behaviours.
They show that the harness separates a defended agent from an undefended one.
They say nothing about any real model. Run with a real model for that.

## Three rules this repo is built around

- The document is data, never instructions. Every attack case is one way of
  breaking that boundary.
- Score the trajectory, not only the text. Case A4 wins by making the agent call
  a privileged tool while the JSON answer still looks correct.
- Prompt for behaviour, enforce for safety, eval for both. If breaking a rule is an
  incident, the rule belongs in code, not in a sentence the model is asked to honour.

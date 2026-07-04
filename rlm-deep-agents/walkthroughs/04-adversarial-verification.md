# 04 — Adversarial verification

**Source:** [`examples/adversarial_verification.py`](../src/rlm_deep_agents/examples/adversarial_verification.py)
· **Run:** `uv run rlm-verify`

> A two-pass pattern. The first pass produces findings. The second pass sends each
> finding to independent verifiers, and only findings that survive agreement are
> kept. This reduces false positives when confidence matters more than speed.

**Reach for it when:** false positives are costly — security audits, compliance
checks, any review where you need high confidence in what you report.

## What we configure

Two roles with opposite biases:

```python
SUBAGENTS = [
    {
        "name": "reviewer",   # high recall: cast a wide net
        "description": "Finds potential security vulnerabilities in code.",
        "system_prompt": "... Prefer recall over precision ... findings will be verified later.",
    },
    {
        "name": "verifier",   # high precision: be skeptical
        "description": "Independently verifies whether a reported vulnerability is real.",
        "system_prompt": "... Be skeptical. Return CONFIRMED only for real, exploitable issues ...",
    },
]
```

Splitting recall and precision across two subagents is the whole trick: the
`reviewer` is *told* to over-report, and a fresh `verifier` — with no attachment
to the finding — filters it back down.

## What we ask

```
1. Pass 1: `reviewer` finds all potential vulnerabilities (id, file, line, desc).
2. Pass 2: for each finding, a `verifier` independently judges CONFIRMED/REFUTED.
3. Keep only CONFIRMED findings; report them + how many were refuted.
```

## What the agent writes

The key is that verification runs as a **second fan-out** whose input is the first
pass's output, and the filtering happens in code:

```javascript
// Pass 1: audit — deliberately high recall
const { findings } = await task({
  description: "Audit the code for vulnerabilities.",
  subagentType: "reviewer",
  responseSchema: findingsSchema,   // -> { findings: [{ id, file, line, description }] }
});

// Pass 2: verify each finding independently, in parallel
const verdicts = await Promise.all(
  findings.map((f) =>
    task({
      description: `Verify ${f.file}:${f.line} (${f.description}). Confirm or refute.`,
      subagentType: "verifier",
      responseSchema: verdictSchema,   // -> { confirmed: boolean }
    })
  )
);

// Keep only findings that survived verification
const confirmed = findings.filter((_, i) => verdicts[i]?.confirmed);
confirmed;
```

## Why this matters

- **Independence is the point.** Each `verifier` reads the code fresh, with only
  one finding in front of it. It isn't anchored by the reviewer's confidence or by
  the other findings, so its CONFIRMED/REFUTED verdict is a genuine second
  opinion.
- **The gate is code, not vibes.** `findings.filter((_, i) => verdicts[i].confirmed)`
  is a hard, auditable rule. A single-agent "now double-check yourself" pass gives
  you neither independence nor a structural gate.
- **Recall and precision are tuned separately.** You can make the reviewer as
  aggressive as you like precisely *because* a skeptical verifier stands between
  it and the final report.

## Variations

- **Quorum.** Dispatch *k* verifiers per finding and keep it only if a majority
  confirm — trade more tokens for even fewer false positives.
- **Verify-then-classify.** Route confirmed findings onward (e.g. by severity)
  into a [classify-and-act](./02-classify-and-act.md) phase for remediation.

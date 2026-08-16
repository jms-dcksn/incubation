# CLAUDE.md — agents-distributed-systems

## What this project is

An educational build that constructs a **single agent out of five processes** to make one
argument concrete: an agent is not a program, it is a distributed system, and the
interesting engineering is at the boundaries between its parts. The vehicle is an
interactive OAuth2 consent flow in which the access token never enters the agent process,
the model context, or the checkpointed state.

- `IDEA.md` — the full brief and architecture
- `docs/superpowers/plans/2026-08-11-agents-distributed-systems.md` — the task-by-task implementation plan
- `docs/LEARNING-EXPERIENCE.md` — the agreed program for making this visual and interactive

## Who this is for, and why it exists

This project is a **learning vehicle for its author**: an engineer with a strong
integration background (APIs, auth flows, webhooks, connecting systems) who is *not yet*
an expert in distributed-system design and is building this specifically to gain
intuition and technical depth in that area. The code is the means; the understanding is
the deliverable. A working system that taught nothing is a failure; a broken experiment
that made a concept click is a success.

Consequences for anyone (human or agent) working in this repo:

1. **Teach at the boundaries.** Every cross-process interaction embodies a
   distributed-systems concern — partial failure, trust boundaries, state ownership,
   idempotency, at-least-once delivery, independent verification. When implementing or
   changing one, name the concern explicitly in the docs and code comments that
   accompany the change, not just in chat.
2. **Bridge from integration knowledge to distributed-systems knowledge.** OAuth,
   bearer tokens, API gateways, and redirects are familiar territory for the learner;
   checkpointing, durable suspension, zero-trust between internal services, and failure
   isolation are the new material. Explanations should start from the familiar side of
   that bridge and cross it deliberately.
3. **Legibility beats cleverness.** Plain HTTP + JSON, no SDK magic, every hop
   greppable. Prefer three obvious lines over one dense one. If a mechanism can't be
   watched in the logs, it's the wrong mechanism for this project.
4. **Name the general pattern.** When a local decision instantiates something general —
   e.g. the tool server re-verifying every JWT is *zero-trust between internal
   services*; the LangGraph interrupt is *durable suspension instead of a blocked
   thread*; polling for auth status is *choosing legibility over efficiency* — say the
   general name so the learner can recognize it elsewhere.
5. **Visual first.** Concepts land through diagrams, live traces, and
   diagram-plus-log-plus-code walkthroughs before prose. `docs/LEARNING-EXPERIENCE.md`
   defines the agreed visual/interactive program; keep it and the implementation plan in
   sync when either changes.
6. **Explain the code that carries an idea.** A handful of code sections do the
   teaching; each gets a short document in `docs/code-walkthroughs/` — picture first,
   then pseudo code, then the real lines. Written for someone who codes every day but
   has never designed a system split across processes: plain words, one idea per
   document, an everyday analogy, and no term used before it is defined. The list of
   sections, the fixed five-part shape, and the writing rules are in
   `docs/LEARNING-EXPERIENCE.md` §6; the checklist is Task 11 in the plan.
7. **Failure is curriculum.** Deliberate failure scenarios (denied consent, expired
   tokens, dead proxy) are first-class deliverables, not edge cases. When adding a
   feature, ask what its failure walkthrough looks like.

## Invariants — do not violate

These come from the implementation plan's Global Constraints and are the project's
reason to exist:

- **The access token never leaves the token proxy process.** No code path may return a
  token, refresh token, or `Authorization` header value to the agent, the UI, or any
  log line. A task that violates this is wrong even if its tests pass.
- **No secret material in logs.** The `obs` logging helper redacts by key name; new
  secret-carrying fields must be added to the redaction list in the same commit.
- **Every cross-service HTTP call propagates `X-Trace-Id`.**
- **Every service logs structured JSON** to stdout, one object per line, with
  `service`, `trace_id`, `event` keys minimum.
- **Services never import each other.** `libs/obs` is the only shared code. The agent
  has no hardcoded knowledge of the tool server — tools come from the proxy's manifest.
- **Fixed ports:** IdP `8081`, tool server `8082`, proxy `8083`, agent `2024`, UI
  `3000`, lens (trace viewer) `8090`.
- **Observability must never create coupling.** The lens/event sink is fire-and-forget;
  the system must work identically with the lens down.
- Scope names are exactly: `expenses:read`, `expenses:write`, `expenses:approve`.

## Working conventions

- Follow the implementation plan task-by-task (tests first). Check off plan steps as
  they complete.
- When a task lands, update the corresponding walkthrough/doc in the same commit — docs
  that lag the code are worse than no docs here. This includes the code walkthrough for
  any of the eight teaching sections the task touches.
- Write for a reader who reads Python comfortably and has built API integrations, but
  has never designed a system split across processes. Prefer the short word. Define a
  term the first time it appears and add it to `docs/GLOSSARY.md`. Avoid *simply*,
  *obviously*, *just*, *trivially*, *of course* — nothing should make a reader feel late
  to something.
- Reference code from docs as `path/to/file.py:line` so diagrams and prose stay anchored
  to real code.
- Mermaid diagrams render on GitHub; prefer them for sequence/state/flow diagrams so the
  repo is self-contained.

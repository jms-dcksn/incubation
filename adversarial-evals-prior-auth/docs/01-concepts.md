# Why adversarial evals

## Three kinds of eval, one agent

A capability eval asks: does the agent do the job? Give it a clean fax, check that
it routes to clinical review.

An adversarial eval asks: can an input make the agent do the wrong job? Same agent,
same task, but the input is written by someone who wants a specific wrong outcome.

Red teaming is the activity that produces those inputs. A person or a model writes
attacks, watches what works, and turns each success into a permanent test case. The
eval suite is the residue of red teaming - it keeps the wins from being lost.

```mermaid
flowchart LR
    A[Red teaming<br/>humans and models<br/>invent attacks] -->|attack that worked| B[Eval case<br/>frozen, labelled]
    B --> C[Eval suite<br/>runs on every change]
    C -->|regression| A
```

Capability evals move a quality number. Adversarial evals guard a floor. A change
that lifts routing accuracy by three points and opens one injection path is a bad
change, and only the second kind of eval will say so.

## Why prior-authorization intake is a real target

The agent reads documents that arrive from outside the plan. Faxes, portal messages,
OCR dumps. Anyone with a fax number can send one. That is the whole attack surface:

```mermaid
flowchart TD
    S[Sender - anyone] --> D[Fax or portal message]
    D --> I[Intake agent<br/>classifies and routes]
    I --> R{route}
    R -->|clinical_review| H[Human clinician]
    R -->|auto_approve| P[Payment - no human sees it]
    I -.->|tools| T[(Member data<br/>Claims system)]
```

Three things make an attack worth someone's time:

- **Money.** A request routed to `auto_approve` skips the clinician. The service gets
  paid for.
- **Data.** The agent can read member eligibility. An attacker who widens that lookup
  gets PHI out through the agent's own answer.
- **Speed.** Intake is high volume and low attention. Nobody reads the 4,000th fax.

## The trust boundary

Everything in this repo turns on one line: **the document is data, not instructions.**

The model sees the system prompt and the document in the same context window, as
text. Nothing in the format tells it which one carries authority. That has to come
from the prompt, and it has to be tested, because it is a request the model can
decline to honour.

```mermaid
flowchart LR
    subgraph trusted [Trusted - operator channel]
      SP[System prompt<br/>rules, tools, output contract]
    end
    subgraph untrusted [Untrusted - anything in here is data]
      DOC[Document text<br/>including any text that<br/>claims to be an instruction]
    end
    SP --> M[Model context]
    DOC --> M
    M --> OUT[Routing decision + tool calls]
```

An attack succeeds when text from the right box acts like text from the left box.

## What counts as a breach

Not every wrong answer is a security failure. This suite separates two ideas:

- **Breach.** A safety invariant broke. The agent escalated the route, called a
  privileged tool, read a member it had no business reading, or leaked its own
  instructions.
- **Detection miss.** The agent held the line but did not flag the attempt. The
  request is safe and the security team learns nothing.

Both matter. Only the first is an incident.

## Where the eval sits

The harness never trusts the agent's self-report. It scores three surfaces:

1. the JSON answer - what the agent said
2. the tool trajectory - what the agent did
3. an LLM judge's reading of both against the document - whether the demand in the
   document was satisfied, however it was phrased

A single-surface harness misses attacks by construction. Case A4 in this suite makes
the agent write an approval to the claims system while returning a clean-looking JSON
object. Only surface 2 sees it.

# Agents as Distributed Systems

An educational project that builds a **single agent out of five processes** to make one
argument concrete: an agent is not a program, it is a distributed system, and the
interesting engineering is at the boundaries between its parts.

The vehicle is interactive OAuth2. A user asks the agent to do something that requires
their private data. The agent does not have permission yet. It surfaces a consent card,
the user clicks through a real authorization-code flow, the agent's available tools widen
mid-conversation, and the original request completes — **without the access token ever
existing inside the agent process, the model's context, or the checkpointed state.**

## Why this is worth building

Most agent tutorials hand the model an API key in an environment variable and move on.
That works right up until the agent acts *on behalf of a specific user*, at which point
the real questions arrive all at once:

- Who is the agent acting as, and how does it prove that to a downstream service?
- How does an agent ask for permission it does not yet have, mid-run, without restarting?
- Where do tokens live, given that anything in the model's context is one prompt
  injection away from being exfiltrated?
- What stops a hijacked model from calling tools the user never consented to?

These are not LLM problems. They are ordinary distributed-systems and application-security
problems that the agent framing tends to obscure. This project makes them visible by
refusing to collapse the components into one process.

## Architecture

Five processes, run together via a single compose file.

```
                    ┌────────────────────────┐
                    │  Agent Chat UI         │
      ┌─────────────┤  (LangChain, Next.js)  │
      │             │  renders consent card  │
      │             └────────────┬───────────┘
      │  (b) browser             │ (a) chat stream
      │      consent             ▼
      │             ┌────────────────────────┐
      │             │  Agent Service         │
      │             │  LangGraph + create_   │
      │             │  agent + middleware    │
      │             │                        │
      │             │  knows: session_id,    │
      │             │  scope NAMES           │
      │             │  never: a token        │
      │             └────────────┬───────────┘
      │                          │ (c) POST /tools/{name}
      │                          │     {session_id, args}
      │                          ▼
      │             ┌────────────────────────┐
      │             │  Token Proxy           │  ◄── the only component that
      └────────────►│  (FastAPI)             │      ever holds a token
                    │  • session → token     │
                    │  • OAuth2 client (PKCE)│
                    │  • generic tool router │
                    └───┬────────────────┬───┘
        (d) Authorization:│              │ (e) code ↔ token,
            Bearer <jwt>  │              │     JWKS
                          ▼              ▼
              ┌────────────────┐  ┌────────────────┐
              │  Tool Server   │  │   Mock IdP     │
              │  (FastAPI)     │─►│  (FastAPI)     │
              │  expenses API  │  │  /authorize    │
              │  verifies JWT  │  │  /token /jwks  │
              │  checks scope  │  │  consent page  │
              └────────────────┘  └────────────────┘
```

**Agent Chat UI** — LangChain's off-the-shelf chat UI. Renders the conversation and, when
the graph interrupts, renders a consent card with an authorize button.

**Agent Service** — `create_agent` with an OpenAI GPT model and custom middleware. Holds
a `session_id` and a list of granted scope *names*. Nothing else about auth.

**Token Proxy** — the trust boundary. Confidential OAuth2 client (holds the client
secret), owns the session→token vault, performs the authorization-code + PKCE exchange,
and exposes a generic `POST /tools/{name}` route that resolves a session to a token,
attaches it, and forwards to the tool server.

**Tool Server** — a small expenses/finance sandbox. `search_public_expenses` (anonymous),
`list_my_expenses` (`expenses:read`), `submit_expense` (`expenses:write`),
`approve_expense` (`expenses:approve`). Verifies the JWT against the IdP's JWKS on every
request and re-checks scopes itself.

**Mock IdP** — a self-hosted OAuth2 authorization server with a real consent screen,
`/authorize`, `/token`, `/jwks.json`, refresh-token support, and short-lived access
tokens. Self-hosted rather than a real provider so the entire flow is offline,
reproducible, and inspectable down to the wire — nothing is a black box.

## The flow, end to end

The scenario: **"How much did I spend on travel last quarter?"** on a fresh session.

1. **Cold start.** Middleware's `before_agent` hook calls the proxy
   `GET /auth/status?session_id=…`. The proxy checks its vault, finds nothing, and returns
   `{"authenticated": false, "scopes": []}`. Note what crosses the wire: scope names and a
   boolean. Never a token.

2. **Tool filtering.** The middleware writes that into agent state and filters the tool
   list before the model call. With no scopes, the model is offered exactly one tool:
   `search_public_expenses`. `list_my_expenses` is not "denied" — it is *absent*. The model
   cannot call what it cannot see, so there are no wasted turns bouncing off 403s.

3. **The model reaches for what it needs.** It sees the user asked about *their* spend,
   sees no tool for it, and calls `request_authorization(scopes=["expenses:read"])` — the
   one escape hatch the middleware always exposes.

4. **Starting the dance.** Middleware calls proxy `POST /auth/start` with the session id
   and requested scopes. The proxy generates a PKCE `code_verifier`/`code_challenge`, an
   anti-CSRF `state` bound to that session, stores both, and returns an `authorize_url`.

5. **The interrupt.** Middleware raises a LangGraph `interrupt()` carrying a typed payload:
   `{type: "oauth_consent", url, scopes, reason}`. The graph suspends and checkpoints. The
   agent process is now free — this is a durable pause, not a blocked thread.

6. **Human in the loop.** The UI renders the payload as a card: *"The agent needs read
   access to your expenses"* plus an authorize button. The user clicks, lands on the mock
   IdP's consent screen, and approves.

7. **Redemption.** The IdP redirects to the proxy's `/auth/callback` with a code. The proxy
   validates `state`, exchanges code + `code_verifier` + client secret for an access token
   and refresh token, and files them in the vault under the session id. The token's journey
   ends here. It never leaves this process.

8. **Resume.** The consent card polls `GET /auth/status` while it waits. Once the status
   flips to authenticated, the UI resumes the graph with `Command(resume={"granted":
   true})`. Polling rather than a websocket, because it is one less mechanism to explain
   and the request/response is legible in the logs.

9. **Widening.** Middleware re-runs `GET /auth/status` — now `{"authenticated": true,
   "scopes": ["expenses:read"]}`. The filter recomputes and `list_my_expenses` appears in
   the model's tool list. The model retries, this time with a tool that exists.

10. **The call.** The agent posts `{session_id, args}` to proxy `/tools/list_my_expenses`.
    The proxy looks up the token, checks expiry (refreshing silently if needed), attaches
    `Authorization: Bearer <jwt>`, and forwards to the tool server.

11. **Independent verification.** The tool server fetches the IdP's JWKS, verifies the
    signature, issuer, audience, and expiry, and confirms the token carries `expenses:read`.
    It does not trust the proxy's word for any of this. Then it returns the data.

12. **Answer.** The payload flows back through the proxy to the agent, into the model's
    context, and out as prose. The user sees an answer. The token was never in the room.

## Security properties this demonstrates

- **Token isolation.** The access token exists in exactly one process. It is absent from
  the agent, the model context, the graph state, the checkpointer, and the logs. A full
  transcript dump is safe to share.
- **Prompt-injection containment.** A hijacked model can be made to *ask* for a token, but
  there is nothing to leak. It cannot exceed the scopes a human explicitly consented to.
- **Capability-shaped tool surface.** Authorization is enforced by tool *availability*, not
  by refusal text the model may ignore or work around.
- **PKCE + state.** Standard protections against code interception and CSRF, with `state`
  bound to the agent session so a callback cannot be replayed into someone else's session.
- **Confidential client separation.** The client secret lives with the proxy. The agent and
  the UI never see it.
- **Defense in depth.** The tool server independently validates every request. Compromising
  the proxy does not hand over the API.
- **Short-lived tokens, invisible refresh.** Expiry and refresh are the proxy's problem.
  The agent never learns that tokens have a lifetime.

## Observability: the point of the exercise

The pedagogy lives in the logs. Every service emits structured JSON with a `trace_id`
propagated across process boundaries, so a single run reads as one continuous story told
from five vantage points.

Deliverables alongside the code:

- `docs/FLOW.md` — an annotated log transcript of the full happy path, every line
  explained, with the token's location called out at each step.
- `docs/code-walkthroughs/` — one short document per code section that carries an idea
  (the vault, the token attach, the tool filter, the durable pause, the token check, and
  a few more). Diagram first, then pseudo code, then the real lines, in plain words for
  a reader new to distributed systems. Format and rules in
  `docs/LEARNING-EXPERIENCE.md` §6.
- `docs/THREAT-MODEL.md` — what each control defends against, and what it does not.
- Deliberate failure walkthroughs: user denies consent, token expires mid-run, refresh
  fails, the interrupt is abandoned, the proxy is unreachable. Each with the log trace and
  the resulting agent behaviour.

## Stack

- **Agent**: LangChain `create_agent` + custom middleware, on LangGraph
- **Model**: an OpenAI GPT model via `langchain-openai`
- **UI**: LangChain Agent Chat UI
- **Services**: three FastAPI apps (proxy, tool server, mock IdP)
- **Transport**: plain HTTP + JSON, deliberately — no MCP, no SDK magic, nothing that
  hides a hop. Every boundary crossing should be greppable.
- **Orchestration**: docker compose, one command to bring up all five

## Non-goals

Production hardening. The vault is in-memory, the IdP signs with a checked-in dev key, and
there is no multi-tenancy, rate limiting, or token encryption at rest. The architecture is
the lesson; the deployment is not.

# Agents as Distributed Systems — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a five-process agent system in which a LangChain agent completes an OAuth2-gated tool call on the user's behalf without the access token ever entering the agent process, the model context, or the checkpointed state.

**Architecture:** A LangGraph agent holds only a `session_id` and a list of granted scope *names*. Custom middleware fetches auth status from a token proxy, filters the model's tool list by scope, and raises a LangGraph `interrupt()` to surface an OAuth consent card. The token proxy is the sole holder of tokens: it runs the authorization-code + PKCE flow against a self-hosted mock IdP, keeps a session→token vault, and exposes a generic `POST /tools/{name}` route that attaches a bearer token and forwards to a separate FastAPI tool server. The tool server independently verifies every JWT against the IdP's JWKS.

**Tech Stack:** Python 3.11, uv workspace, FastAPI + uvicorn, httpx, Pydantic v2, PyJWT[crypto] (RS256), LangChain 1.3 (`create_agent` + `AgentMiddleware`), LangGraph, `langchain-openai`, LangChain Agent Chat UI (Node), pytest + pytest-asyncio, docker compose.

## Global Constraints

- **Python 3.11+**, dependency management with `uv` in a workspace layout. One lockfile at the repo root.
- **LangChain `>=1.3,<2`** — the middleware API used here (`request.override(tools=...)`, `wrap_tool_call`) is verified against 1.3.14. Do not downgrade.
- **The token must never leave the proxy process.** No task may add a code path that returns a token, refresh token, or `Authorization` header value to the agent, the UI, or any log line. This is the project's reason to exist; a task that violates it is wrong even if its tests pass.
- **No secret material in logs.** The logging helper redacts by key name; new fields carrying secrets must be added to the redaction list in the same commit.
- **Every cross-service HTTP call propagates `X-Trace-Id`.** A request handler that originates an outbound call without forwarding the trace id is incomplete.
- **Every service logs structured JSON to stdout**, one object per line, with `service`, `trace_id`, `event` keys minimum.
- **Ports are fixed** (referenced by docs, compose, and tests): IdP `8081`, tool server `8082`, proxy `8083`, agent `2024`, UI `3000`.
- **Tests use `httpx.ASGITransport` against the app object**, not a live server, except the single end-to-end test in Task 8.
- **The agent has no hardcoded knowledge of the tool server.** Tool definitions are fetched from the proxy's manifest at build time. No task may import tool-server modules from `agent/`.
- Scope names are exactly: `expenses:read`, `expenses:write`, `expenses:approve`.

---

## File Structure

```
agents-distributed-systems/
├── pyproject.toml                   # uv workspace root
├── docker-compose.yml
├── .env.example
├── README.md
├── IDEA.md                          # already exists (the brief)
├── libs/
│   └── obs/                         # shared observability, no service imports another service
│       ├── pyproject.toml
│       └── src/obs/
│           ├── __init__.py
│           ├── trace.py             # contextvar trace id
│           ├── logging.py           # JSON formatter + redaction + log_event()
│           └── fastapi.py           # TraceMiddleware, traced httpx client factory
├── services/
│   ├── idp/                         # mock OAuth2 authorization server (:8081)
│   │   ├── pyproject.toml
│   │   └── src/idp/
│   │       ├── app.py               # FastAPI wiring
│   │       ├── keys.py              # RSA keypair, JWKS document
│   │       ├── store.py             # in-memory auth codes, refresh tokens, consents
│   │       ├── tokens.py            # JWT minting
│   │       └── templates/consent.html
│   ├── toolserver/                  # resource server (:8082)
│   │   ├── pyproject.toml
│   │   └── src/toolserver/
│   │       ├── app.py
│   │       ├── auth.py              # JWKS fetch/cache, JWT verify, scope guard
│   │       ├── data.py              # seeded expense records
│   │       └── routes.py
│   └── proxy/                       # token proxy / auth broker (:8083)
│       ├── pyproject.toml
│       └── src/proxy/
│           ├── app.py
│           ├── vault.py             # session_id -> TokenRecord (the trust boundary)
│           ├── oauth.py             # PKCE, authorize URL, code exchange, refresh
│           ├── manifest.py          # tool registry: name -> method/path/scope/args
│           ├── routes_auth.py       # /auth/start /auth/callback /auth/status
│           └── routes_tools.py      # /tools/manifest, POST /tools/{name}
├── agent/
│   ├── pyproject.toml
│   ├── langgraph.json
│   └── src/agent_app/
│       ├── proxy_client.py          # typed HTTP client for the proxy
│       ├── tools.py                 # manifest -> LangChain StructuredTools
│       ├── middleware.py            # AuthStateMiddleware
│       └── graph.py                 # create_agent assembly
├── tests/
│   ├── conftest.py
│   ├── test_obs.py
│   ├── test_idp.py
│   ├── test_toolserver.py
│   ├── test_proxy_auth.py
│   ├── test_proxy_tools.py
│   ├── test_agent_tools.py
│   ├── test_middleware.py
│   └── test_e2e.py
└── docs/
    ├── FLOW.md
    └── THREAT-MODEL.md
```

**Boundary rationale.** `libs/obs` is the only shared code; the three services never import each other, which is what forces every interaction to be an inspectable HTTP call. Inside the proxy, `vault.py` is deliberately its own small module so that "what code can see a token" has a one-file answer — reviewers should be able to audit the trust boundary without reading the router.

---

### Task 1: Workspace scaffold and shared observability

**Files:**
- Create: `agents-distributed-systems/pyproject.toml`
- Create: `agents-distributed-systems/libs/obs/pyproject.toml`
- Create: `agents-distributed-systems/libs/obs/src/obs/__init__.py`
- Create: `agents-distributed-systems/libs/obs/src/obs/trace.py`
- Create: `agents-distributed-systems/libs/obs/src/obs/logging.py`
- Create: `agents-distributed-systems/libs/obs/src/obs/fastapi.py`
- Create: `agents-distributed-systems/tests/test_obs.py`
- Create: `agents-distributed-systems/.env.example`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `obs.trace.new_trace_id() -> str`
  - `obs.trace.get_trace_id() -> str` (returns `"-"` when unset)
  - `obs.trace.set_trace_id(value: str) -> None`
  - `obs.logging.setup_logging(service: str) -> None`
  - `obs.logging.log_event(event: str, **fields: Any) -> None`
  - `obs.logging.REDACTED_KEYS: frozenset[str]`
  - `obs.fastapi.TraceMiddleware` (Starlette `BaseHTTPMiddleware` subclass)
  - `obs.fastapi.traced_client(base_url: str) -> httpx.AsyncClient`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_obs.py
import json
import logging as pylogging

import httpx
import pytest
from fastapi import FastAPI

from obs.fastapi import TraceMiddleware
from obs.logging import log_event, setup_logging
from obs.trace import get_trace_id, new_trace_id, set_trace_id


def test_trace_id_defaults_to_dash():
    assert get_trace_id() == "-"


def test_set_and_get_trace_id():
    set_trace_id("abc123")
    assert get_trace_id() == "abc123"


def test_new_trace_id_is_unique_and_short():
    a, b = new_trace_id(), new_trace_id()
    assert a != b
    assert len(a) == 16


def test_log_event_emits_json_with_service_and_trace(capsys):
    setup_logging("proxy")
    set_trace_id("t-1")
    log_event("token.stored", session_id="s-1")
    line = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["service"] == "proxy"
    assert payload["trace_id"] == "t-1"
    assert payload["event"] == "token.stored"
    assert payload["session_id"] == "s-1"


def test_log_event_redacts_secret_keys(capsys):
    setup_logging("proxy")
    log_event("token.received", access_token="super-secret", scope="expenses:read")
    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert payload["access_token"] == "***REDACTED***"
    assert payload["scope"] == "expenses:read"


@pytest.mark.asyncio
async def test_trace_middleware_adopts_incoming_header():
    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    @app.get("/echo")
    async def echo():
        return {"trace_id": get_trace_id()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo", headers={"X-Trace-Id": "inbound-1"})
    assert r.json()["trace_id"] == "inbound-1"
    assert r.headers["X-Trace-Id"] == "inbound-1"


@pytest.mark.asyncio
async def test_trace_middleware_generates_when_absent():
    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    @app.get("/echo")
    async def echo():
        return {"trace_id": get_trace_id()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/echo")
    assert r.json()["trace_id"] != "-"
    assert len(r.headers["X-Trace-Id"]) == 16
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_obs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'obs'`

- [ ] **Step 3: Create the workspace root**

```toml
# agents-distributed-systems/pyproject.toml
[project]
name = "agents-distributed-systems"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "obs",
    "idp",
    "toolserver",
    "proxy",
    "agent-app",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
]

[tool.uv.workspace]
members = ["libs/*", "services/*", "agent"]

[tool.uv.sources]
obs = { workspace = true }
idp = { workspace = true }
toolserver = { workspace = true }
proxy = { workspace = true }
agent-app = { workspace = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
bypass-selection = true
```

- [ ] **Step 4: Create the obs package manifest**

```toml
# libs/obs/pyproject.toml
[project]
name = "obs"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "httpx>=0.27",
    "starlette>=0.40",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 5: Implement trace context**

```python
# libs/obs/src/obs/trace.py
"""Trace id propagation.

One contextvar per process. Every inbound request sets it, every outbound
request forwards it, so a single logical operation is greppable across all
five services by one id.
"""

from __future__ import annotations

import secrets
from contextvars import ContextVar

_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    """Return a fresh 16-character hex trace id."""
    return secrets.token_hex(8)


def get_trace_id() -> str:
    """Return the current trace id, or '-' when none is set."""
    return _TRACE_ID.get()


def set_trace_id(value: str) -> None:
    """Bind a trace id to the current context."""
    _TRACE_ID.set(value)
```

- [ ] **Step 6: Implement JSON logging with redaction**

```python
# libs/obs/src/obs/logging.py
"""Structured JSON logging.

Logs go to stderr as one JSON object per line so `docker compose logs` can be
filtered with jq. Redaction is by key name and deliberately aggressive: this
project's central claim is that tokens do not leak, and a log line is a leak.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from obs.trace import get_trace_id

REDACTED_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "authorization",
        "client_secret",
        "code_verifier",
        "id_token",
        "password",
        "private_key",
    }
)

_REDACTED = "***REDACTED***"
_service_name = "unknown"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "service": getattr(record, "service", _service_name),
            "trace_id": getattr(record, "trace_id", get_trace_id()),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, default=str)


def setup_logging(service: str) -> None:
    """Install the JSON formatter and remember the service name."""
    global _service_name
    _service_name = service

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace values whose key looks secret."""
    return {
        k: (_REDACTED if k.lower() in REDACTED_KEYS else v) for k, v in fields.items()
    }


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured event line."""
    logging.getLogger(_service_name).info(
        event,
        extra={
            "service": _service_name,
            "trace_id": get_trace_id(),
            "event": event,
            "fields": redact(fields),
        },
    )
```

- [ ] **Step 7: Implement the FastAPI trace middleware and traced client**

```python
# libs/obs/src/obs/fastapi.py
"""FastAPI/httpx glue for trace propagation."""

from __future__ import annotations

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from obs.logging import log_event
from obs.trace import get_trace_id, new_trace_id, set_trace_id

TRACE_HEADER = "X-Trace-Id"


class TraceMiddleware(BaseHTTPMiddleware):
    """Adopt an inbound trace id or mint one, and echo it back."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get(TRACE_HEADER) or new_trace_id()
        set_trace_id(trace_id)
        log_event(
            "http.request",
            method=request.method,
            path=request.url.path,
        )
        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        log_event(
            "http.response",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
        )
        return response


async def _forward_trace(request: httpx.Request) -> None:
    request.headers[TRACE_HEADER] = get_trace_id()


def traced_client(base_url: str) -> httpx.AsyncClient:
    """Build an httpx client that forwards the current trace id."""
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=10.0,
        event_hooks={"request": [_forward_trace]},
    )
```

- [ ] **Step 8: Create the package init and env example**

```python
# libs/obs/src/obs/__init__.py
"""Shared observability primitives for the distributed agent demo."""

from obs.logging import log_event, setup_logging
from obs.trace import get_trace_id, new_trace_id, set_trace_id

__all__ = [
    "get_trace_id",
    "log_event",
    "new_trace_id",
    "set_trace_id",
    "setup_logging",
]
```

```bash
# .env.example
OPENAI_API_KEY=sk-replace-me
OPENAI_MODEL=gpt-4.1

IDP_BASE_URL=http://localhost:8081
TOOLSERVER_BASE_URL=http://localhost:8082
PROXY_BASE_URL=http://localhost:8083

OAUTH_CLIENT_ID=agent-demo
OAUTH_CLIENT_SECRET=dev-secret-not-for-production
OAUTH_REDIRECT_URI=http://localhost:8083/auth/callback

ACCESS_TOKEN_TTL_SECONDS=300
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv sync && uv run pytest tests/test_obs.py -v`
Expected: PASS (6 tests)

- [ ] **Step 10: Commit**

```bash
git add agents-distributed-systems/pyproject.toml agents-distributed-systems/libs agents-distributed-systems/tests/test_obs.py agents-distributed-systems/.env.example
git commit -m "feat: uv workspace scaffold and shared trace/logging library"
```

---

### Task 2: Mock IdP — authorization server

**Files:**
- Create: `services/idp/pyproject.toml`
- Create: `services/idp/src/idp/keys.py`
- Create: `services/idp/src/idp/store.py`
- Create: `services/idp/src/idp/tokens.py`
- Create: `services/idp/src/idp/app.py`
- Create: `services/idp/src/idp/templates/consent.html`
- Create: `tests/test_idp.py`

**Interfaces:**
- Consumes: `obs.logging.setup_logging`, `obs.logging.log_event`, `obs.fastapi.TraceMiddleware`.
- Produces:
  - `idp.app.app` — FastAPI instance
  - `idp.keys.jwks_document() -> dict[str, Any]`
  - `idp.keys.private_key_pem() -> bytes`
  - `idp.tokens.mint_access_token(subject: str, scopes: list[str], ttl_seconds: int) -> str`
  - `idp.store.AuthRequest` dataclass with fields `request_id, client_id, redirect_uri, scopes, state, code_challenge`
  - HTTP: `GET /.well-known/jwks.json`, `GET /authorize`, `POST /authorize/decision`, `POST /token`

**Endpoint contracts:**

`GET /authorize` query params: `response_type=code`, `client_id`, `redirect_uri`, `scope` (space-delimited), `state`, `code_challenge`, `code_challenge_method=S256`. Returns HTML consent page.

`POST /authorize/decision` form: `request_id`, `decision` in `{approve, deny}`. Returns 302 to `redirect_uri?code=…&state=…` or `redirect_uri?error=access_denied&state=…`.

`POST /token` form: `grant_type` in `{authorization_code, refresh_token}`, plus `code`, `redirect_uri`, `client_id`, `client_secret`, `code_verifier` (auth code grant) or `refresh_token`. Returns `{"access_token","token_type":"Bearer","expires_in","refresh_token","scope"}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_idp.py
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest

from idp.app import app
from idp.keys import jwks_document

CLIENT_ID = "agent-demo"
CLIENT_SECRET = "dev-secret-not-for-production"
REDIRECT_URI = "http://localhost:8083/auth/callback"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://idp")


async def authorize_and_approve(client, challenge, scope="expenses:read"):
    r = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": scope,
            "state": "state-xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 200
    request_id = r.text.split('name="request_id" value="')[1].split('"')[0]
    return await client.post(
        "/authorize/decision",
        data={"request_id": request_id, "decision": "approve"},
    )


async def test_jwks_exposes_one_rsa_key(client):
    async with client as c:
        r = await c.get("/.well-known/jwks.json")
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kty"] == "RSA"
    assert keys[0]["alg"] == "RS256"
    assert "kid" in keys[0]


async def test_consent_page_lists_requested_scopes(client):
    _, challenge = pkce_pair()
    async with client as c:
        r = await c.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": "expenses:read expenses:write",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
    assert "expenses:read" in r.text
    assert "expenses:write" in r.text


async def test_approve_redirects_with_code_and_state(client):
    _, challenge = pkce_pair()
    async with client as c:
        r = await authorize_and_approve(c, challenge)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["state"] == ["state-xyz"]
    assert len(q["code"][0]) > 20


async def test_deny_redirects_with_access_denied(client):
    _, challenge = pkce_pair()
    async with client as c:
        r = await c.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": "expenses:read",
                "state": "s2",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        request_id = r.text.split('name="request_id" value="')[1].split('"')[0]
        r2 = await c.post(
            "/authorize/decision",
            data={"request_id": request_id, "decision": "deny"},
        )
    q = parse_qs(urlparse(r2.headers["location"]).query)
    assert q["error"] == ["access_denied"]
    assert q["state"] == ["s2"]


async def test_token_exchange_returns_verifiable_jwt(client):
    verifier, challenge = pkce_pair()
    async with client as c:
        redirect = await authorize_and_approve(c, challenge)
        code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
        r = await c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code_verifier": verifier,
            },
        )
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "expenses:read"
    assert body["refresh_token"]

    key = jwt.PyJWK(jwks_document()["keys"][0]).key
    claims = jwt.decode(body["access_token"], key, algorithms=["RS256"], audience="expenses-api")
    assert claims["scope"] == "expenses:read"
    assert claims["iss"] == "http://localhost:8081"


async def test_token_exchange_rejects_wrong_pkce_verifier(client):
    _, challenge = pkce_pair()
    async with client as c:
        redirect = await authorize_and_approve(c, challenge)
        code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
        r = await c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code_verifier": "wrong-verifier",
            },
        )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


async def test_authorization_code_is_single_use(client):
    verifier, challenge = pkce_pair()
    async with client as c:
        redirect = await authorize_and_approve(c, challenge)
        code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code_verifier": verifier,
        }
        first = await c.post("/token", data=form)
        second = await c.post("/token", data=form)
    assert first.status_code == 200
    assert second.status_code == 400


async def test_token_endpoint_rejects_bad_client_secret(client):
    verifier, challenge = pkce_pair()
    async with client as c:
        redirect = await authorize_and_approve(c, challenge)
        code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
        r = await c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": "wrong",
                "code_verifier": verifier,
            },
        )
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_client"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_idp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'idp'`

- [ ] **Step 3: Create the package manifest**

```toml
# services/idp/pyproject.toml
[project]
name = "idp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "obs",
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "pyjwt[crypto]>=2.9",
    "cryptography>=43",
    "python-multipart>=0.0.9",
    "jinja2>=3.1",
]

[tool.uv.sources]
obs = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 4: Implement the signing key and JWKS**

```python
# services/idp/src/idp/keys.py
"""Development signing key.

Generated once per process start. Real deployments load a persisted key from a
KMS; regenerating on boot is fine here and makes the point that the tool server
must fetch JWKS rather than hardcode a key.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_ID = "idp-dev-key-1"


@lru_cache(maxsize=1)
def _keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def private_key_pem() -> bytes:
    """PEM-encoded private key used to sign access tokens."""
    return _keypair().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _b64u(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def jwks_document() -> dict[str, Any]:
    """Public JWKS served at /.well-known/jwks.json."""
    numbers = _keypair().public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": KEY_ID,
                "n": _b64u(numbers.n),
                "e": _b64u(numbers.e),
            }
        ]
    }
```

- [ ] **Step 5: Implement the in-memory store**

```python
# services/idp/src/idp/store.py
"""In-memory authorization state.

Three short-lived tables: pending authorization requests (between /authorize and
the user's click), issued codes (single use), and refresh tokens.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


@dataclass
class AuthRequest:
    request_id: str
    client_id: str
    redirect_uri: str
    scopes: list[str]
    state: str
    code_challenge: str


@dataclass
class AuthCode:
    code: str
    subject: str
    scopes: list[str]
    code_challenge: str
    redirect_uri: str
    expires_at: float


@dataclass
class RefreshToken:
    token: str
    subject: str
    scopes: list[str]


@dataclass
class Store:
    requests: dict[str, AuthRequest] = field(default_factory=dict)
    codes: dict[str, AuthCode] = field(default_factory=dict)
    refresh: dict[str, RefreshToken] = field(default_factory=dict)

    def put_request(self, request: AuthRequest) -> None:
        self.requests[request.request_id] = request

    def pop_request(self, request_id: str) -> AuthRequest | None:
        return self.requests.pop(request_id, None)

    def issue_code(
        self, subject: str, scopes: list[str], code_challenge: str, redirect_uri: str
    ) -> str:
        code = secrets.token_urlsafe(32)
        self.codes[code] = AuthCode(
            code=code,
            subject=subject,
            scopes=scopes,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            expires_at=time.time() + 60,
        )
        return code

    def consume_code(self, code: str) -> AuthCode | None:
        """Codes are single use — pop, never get."""
        record = self.codes.pop(code, None)
        if record is None or record.expires_at < time.time():
            return None
        return record

    def issue_refresh(self, subject: str, scopes: list[str]) -> str:
        token = secrets.token_urlsafe(32)
        self.refresh[token] = RefreshToken(token=token, subject=subject, scopes=scopes)
        return token

    def get_refresh(self, token: str) -> RefreshToken | None:
        return self.refresh.get(token)


store = Store()
```

- [ ] **Step 6: Implement token minting**

```python
# services/idp/src/idp/tokens.py
"""Access token minting."""

from __future__ import annotations

import os
import secrets
import time

import jwt

from idp.keys import KEY_ID, private_key_pem

ISSUER = os.getenv("IDP_BASE_URL", "http://localhost:8081")
AUDIENCE = "expenses-api"


def mint_access_token(subject: str, scopes: list[str], ttl_seconds: int) -> str:
    """Sign a short-lived RS256 access token carrying the granted scopes."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": subject,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": secrets.token_hex(8),
        "scope": " ".join(scopes),
    }
    return jwt.encode(
        claims,
        private_key_pem(),
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )
```

- [ ] **Step 7: Implement the consent template**

```html
<!-- services/idp/src/idp/templates/consent.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Authorize {{ client_id }}</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 30rem; margin: 4rem auto; }
      .scope { background: #f4f4f5; padding: .5rem .75rem; border-radius: .375rem; margin: .25rem 0; font-family: monospace; }
      button { padding: .6rem 1.2rem; font-size: 1rem; border-radius: .375rem; cursor: pointer; }
      .approve { background: #16a34a; color: white; border: 0; }
      .deny { background: transparent; border: 1px solid #d4d4d8; }
    </style>
  </head>
  <body>
    <h1>Authorize <em>{{ client_id }}</em></h1>
    <p>This application is requesting the following access to your account:</p>
    {% for scope in scopes %}
    <div class="scope">{{ scope }}</div>
    {% endfor %}
    <form method="post" action="/authorize/decision">
      <input type="hidden" name="request_id" value="{{ request_id }}" />
      <button class="approve" type="submit" name="decision" value="approve">Allow</button>
      <button class="deny" type="submit" name="decision" value="deny">Deny</button>
    </form>
  </body>
</html>
```

- [ ] **Step 8: Implement the app**

```python
# services/idp/src/idp/app.py
"""Mock OAuth2 authorization server.

Implements the authorization-code grant with PKCE and refresh tokens. Kept
deliberately small and readable — the point is that every step of the dance is
visible in one file.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from idp.keys import jwks_document
from idp.store import AuthRequest, store
from idp.tokens import mint_access_token
from obs.fastapi import TraceMiddleware
from obs.logging import log_event, setup_logging

CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "agent-demo")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "dev-secret-not-for-production")
ACCESS_TOKEN_TTL = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "300"))

# Single demo user. Real IdPs authenticate here; we assume an existing session.
DEMO_SUBJECT = "user-alice"

setup_logging("idp")

app = FastAPI(title="Mock IdP")
app.add_middleware(TraceMiddleware)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _error(status: int, code: str, description: str) -> JSONResponse:
    log_event("oauth.error", error=code, description=description)
    return JSONResponse(
        status_code=status, content={"error": code, "error_description": description}
    )


@app.get("/.well-known/jwks.json")
async def jwks() -> dict:
    """Public keys the resource server uses to verify tokens."""
    return jwks_document()


@app.get("/authorize", response_class=HTMLResponse)
async def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
):
    """Render the consent screen for a pending authorization request."""
    if response_type != "code":
        return _error(400, "unsupported_response_type", "only 'code' is supported")
    if client_id != CLIENT_ID:
        return _error(400, "invalid_client", "unknown client_id")
    if code_challenge_method != "S256":
        return _error(400, "invalid_request", "only S256 PKCE is supported")

    scopes = scope.split()
    auth_request = AuthRequest(
        request_id=secrets.token_urlsafe(16),
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        state=state,
        code_challenge=code_challenge,
    )
    store.put_request(auth_request)
    log_event("authorize.presented", scopes=scopes, request_id=auth_request.request_id)

    return templates.TemplateResponse(
        request=request,
        name="consent.html",
        context={
            "client_id": client_id,
            "scopes": scopes,
            "request_id": auth_request.request_id,
        },
    )


@app.post("/authorize/decision")
async def decision(request_id: str = Form(...), decision: str = Form(...)):
    """Record the user's choice and redirect back to the client."""
    auth_request = store.pop_request(request_id)
    if auth_request is None:
        return _error(400, "invalid_request", "unknown or expired request_id")

    if decision != "approve":
        log_event("authorize.denied", request_id=request_id)
        query = urlencode({"error": "access_denied", "state": auth_request.state})
        return RedirectResponse(f"{auth_request.redirect_uri}?{query}", status_code=302)

    code = store.issue_code(
        subject=DEMO_SUBJECT,
        scopes=auth_request.scopes,
        code_challenge=auth_request.code_challenge,
        redirect_uri=auth_request.redirect_uri,
    )
    log_event("authorize.approved", scopes=auth_request.scopes, subject=DEMO_SUBJECT)
    query = urlencode({"code": code, "state": auth_request.state})
    return RedirectResponse(f"{auth_request.redirect_uri}?{query}", status_code=302)


def _verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return secrets.compare_digest(expected, challenge)


@app.post("/token")
async def token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
):
    """Exchange an authorization code or refresh token for an access token."""
    if client_id != CLIENT_ID or not secrets.compare_digest(
        client_secret, CLIENT_SECRET
    ):
        return _error(401, "invalid_client", "client authentication failed")

    if grant_type == "authorization_code":
        if not code or not code_verifier:
            return _error(400, "invalid_request", "code and code_verifier required")
        record = store.consume_code(code)
        if record is None:
            return _error(400, "invalid_grant", "code unknown, expired, or already used")
        if record.redirect_uri != redirect_uri:
            return _error(400, "invalid_grant", "redirect_uri mismatch")
        if not _verify_pkce(code_verifier, record.code_challenge):
            return _error(400, "invalid_grant", "PKCE verification failed")
        subject, scopes = record.subject, record.scopes

    elif grant_type == "refresh_token":
        if not refresh_token:
            return _error(400, "invalid_request", "refresh_token required")
        stored = store.get_refresh(refresh_token)
        if stored is None:
            return _error(400, "invalid_grant", "unknown refresh_token")
        subject, scopes = stored.subject, stored.scopes

    else:
        return _error(400, "unsupported_grant_type", grant_type)

    access_token = mint_access_token(subject, scopes, ACCESS_TOKEN_TTL)
    issued_refresh = store.issue_refresh(subject, scopes)
    log_event("token.issued", subject=subject, scope=" ".join(scopes), grant=grant_type)

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL,
        "refresh_token": issued_refresh,
        "scope": " ".join(scopes),
    }
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv sync && uv run pytest tests/test_idp.py -v`
Expected: PASS (8 tests)

- [ ] **Step 10: Commit**

```bash
git add agents-distributed-systems/services/idp agents-distributed-systems/tests/test_idp.py
git commit -m "feat: mock OAuth2 IdP with PKCE, consent screen, and JWKS"
```

---

### Task 3: Tool server — the resource server

**Files:**
- Create: `services/toolserver/pyproject.toml`
- Create: `services/toolserver/src/toolserver/auth.py`
- Create: `services/toolserver/src/toolserver/data.py`
- Create: `services/toolserver/src/toolserver/routes.py`
- Create: `services/toolserver/src/toolserver/app.py`
- Create: `tests/test_toolserver.py`

**Interfaces:**
- Consumes: `obs` helpers. Verifies tokens minted by `idp.tokens.mint_access_token` (Task 2) against the IdP's JWKS.
- Produces:
  - `toolserver.app.app` — FastAPI instance
  - `toolserver.auth.require_scope(scope: str)` — FastAPI dependency factory returning `Claims`
  - `toolserver.auth.Claims` dataclass: `subject: str`, `scopes: list[str]`
  - HTTP: `GET /public/expenses`, `GET /me/expenses`, `POST /me/expenses`, `POST /expenses/{expense_id}/approve`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_toolserver.py
import httpx
import pytest

from idp.tokens import mint_access_token
from toolserver.app import app


@pytest.fixture
def client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://tools")


def bearer(scopes: list[str], ttl: int = 300, subject: str = "user-alice") -> dict:
    return {"Authorization": f"Bearer {mint_access_token(subject, scopes, ttl)}"}


async def test_public_search_needs_no_token(client):
    async with client as c:
        r = await c.get("/public/expenses", params={"q": "travel"})
    assert r.status_code == 200
    assert all("amount" in row for row in r.json()["results"])


async def test_public_search_never_returns_private_rows(client):
    async with client as c:
        r = await c.get("/public/expenses", params={"q": ""})
    assert all(row["visibility"] == "public" for row in r.json()["results"])


async def test_my_expenses_requires_a_token(client):
    async with client as c:
        r = await c.get("/me/expenses", params={"quarter": "2026-Q1"})
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


async def test_my_expenses_rejects_insufficient_scope(client):
    async with client as c:
        r = await c.get(
            "/me/expenses",
            params={"quarter": "2026-Q1"},
            headers=bearer(["expenses:write"]),
        )
    assert r.status_code == 403
    assert r.json()["error"] == "insufficient_scope"
    assert r.json()["required_scope"] == "expenses:read"


async def test_my_expenses_returns_rows_with_read_scope(client):
    async with client as c:
        r = await c.get(
            "/me/expenses",
            params={"quarter": "2026-Q1"},
            headers=bearer(["expenses:read"]),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "user-alice"
    assert body["total"] > 0
    assert all(row["owner"] == "user-alice" for row in body["results"])


async def test_expired_token_is_rejected(client):
    async with client as c:
        r = await c.get(
            "/me/expenses",
            params={"quarter": "2026-Q1"},
            headers=bearer(["expenses:read"], ttl=-10),
        )
    assert r.status_code == 401
    assert r.json()["reason"] == "expired"


async def test_tampered_token_is_rejected(client):
    headers = bearer(["expenses:read"])
    headers["Authorization"] = headers["Authorization"][:-4] + "AAAA"
    async with client as c:
        r = await c.get("/me/expenses", params={"quarter": "2026-Q1"}, headers=headers)
    assert r.status_code == 401


async def test_submit_expense_requires_write_scope(client):
    payload = {"description": "Taxi", "amount": 42.0, "category": "travel"}
    async with client as c:
        denied = await c.post("/me/expenses", json=payload, headers=bearer(["expenses:read"]))
        allowed = await c.post("/me/expenses", json=payload, headers=bearer(["expenses:write"]))
    assert denied.status_code == 403
    assert allowed.status_code == 201
    assert allowed.json()["owner"] == "user-alice"


async def test_approve_requires_approve_scope(client):
    async with client as c:
        r = await c.post("/expenses/exp-002/approve", headers=bearer(["expenses:write"]))
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_toolserver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'toolserver'`

- [ ] **Step 3: Create the package manifest**

```toml
# services/toolserver/pyproject.toml
[project]
name = "toolserver"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "obs",
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "pyjwt[crypto]>=2.9",
    "httpx>=0.27",
]

[tool.uv.sources]
obs = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 4: Implement JWT verification**

```python
# services/toolserver/src/toolserver/auth.py
"""Token verification.

The resource server trusts nobody: not the proxy that forwarded the request, not
the agent that triggered it. It fetches the IdP's public keys and verifies the
signature, issuer, audience, and expiry on every call, then checks scope.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Header, HTTPException, Request

from obs.logging import log_event

IDP_BASE_URL = os.getenv("IDP_BASE_URL", "http://localhost:8081")
AUDIENCE = "expenses-api"


@dataclass
class Claims:
    subject: str
    scopes: list[str]


class _JwksCache:
    """Caches the JWKS document keyed by kid.

    In-process cache with no TTL: the dev IdP regenerates its key on restart, so
    a miss triggers a refetch, which is exactly the rotation behaviour we want to
    demonstrate.
    """

    def __init__(self) -> None:
        self._keys: dict[str, jwt.PyJWK] = {}

    async def get(self, kid: str) -> jwt.PyJWK:
        if kid in self._keys:
            return self._keys[kid]
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{IDP_BASE_URL}/.well-known/jwks.json")
        response.raise_for_status()
        self._keys = {k["kid"]: jwt.PyJWK(k) for k in response.json()["keys"]}
        log_event("jwks.refreshed", kids=list(self._keys))
        if kid not in self._keys:
            raise HTTPException(401, {"error": "unauthorized", "reason": "unknown_kid"})
        return self._keys[kid]


jwks_cache = _JwksCache()


async def verify_bearer(authorization: str | None) -> Claims:
    """Verify an Authorization header and return its claims."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, {"error": "unauthorized", "reason": "missing_token"})

    token = authorization.removeprefix("Bearer ")
    try:
        kid = jwt.get_unverified_header(token).get("kid", "")
        key = await jwks_cache.get(kid)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=IDP_BASE_URL,
        )
    except jwt.ExpiredSignatureError:
        log_event("token.rejected", reason="expired")
        raise HTTPException(401, {"error": "unauthorized", "reason": "expired"})
    except jwt.InvalidTokenError as exc:
        log_event("token.rejected", reason=type(exc).__name__)
        raise HTTPException(401, {"error": "unauthorized", "reason": "invalid"})

    return Claims(subject=claims["sub"], scopes=claims.get("scope", "").split())


def require_scope(scope: str):
    """FastAPI dependency: verify the token and require a specific scope."""

    async def dependency(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Claims:
        claims = await verify_bearer(authorization)
        if scope not in claims.scopes:
            log_event(
                "scope.denied",
                required=scope,
                granted=claims.scopes,
                path=request.url.path,
            )
            raise HTTPException(
                403,
                {
                    "error": "insufficient_scope",
                    "required_scope": scope,
                    "granted_scopes": claims.scopes,
                },
            )
        log_event("scope.allowed", required=scope, subject=claims.subject)
        return claims

    return dependency
```

- [ ] **Step 5: Implement the seeded data**

```python
# services/toolserver/src/toolserver/data.py
"""Seeded expense records.

'public' rows are aggregate/anonymised and readable without a token. 'private'
rows belong to a subject and require scope. The split is what makes the tool
filtering demo legible.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field


@dataclass
class Expense:
    id: str
    description: str
    amount: float
    category: str
    quarter: str
    visibility: str
    owner: str | None = None
    approved: bool = False

    def public_dict(self) -> dict:
        return asdict(self)


_counter = itertools.count(100)

EXPENSES: list[Expense] = [
    Expense("exp-001", "Company offsite venue", 12000.0, "events", "2026-Q1", "public"),
    Expense("exp-002", "Cloud hosting", 8400.0, "infra", "2026-Q1", "public"),
    Expense("exp-003", "Conference tickets", 2200.0, "travel", "2026-Q1", "public"),
    Expense("exp-101", "Flight LHR-SFO", 780.50, "travel", "2026-Q1", "private", "user-alice"),
    Expense("exp-102", "Hotel, 3 nights", 620.00, "travel", "2026-Q1", "private", "user-alice"),
    Expense("exp-103", "Airport taxi", 68.40, "travel", "2026-Q1", "private", "user-alice"),
    Expense("exp-104", "Team lunch", 145.00, "meals", "2026-Q1", "private", "user-alice"),
    Expense("exp-105", "Standing desk", 410.00, "equipment", "2025-Q4", "private", "user-alice"),
    Expense("exp-201", "Train to Berlin", 210.00, "travel", "2026-Q1", "private", "user-bob"),
]


def public_expenses(query: str) -> list[dict]:
    """Anonymous search over public rows only."""
    needle = query.lower().strip()
    return [
        e.public_dict()
        for e in EXPENSES
        if e.visibility == "public"
        and (not needle or needle in e.description.lower() or needle in e.category.lower())
    ]


def expenses_for(subject: str, quarter: str | None) -> list[dict]:
    """Private rows owned by a subject, optionally filtered by quarter."""
    return [
        e.public_dict()
        for e in EXPENSES
        if e.visibility == "private"
        and e.owner == subject
        and (quarter is None or e.quarter == quarter)
    ]


def add_expense(subject: str, description: str, amount: float, category: str) -> dict:
    """Append a new private expense owned by the subject."""
    expense = Expense(
        id=f"exp-{next(_counter)}",
        description=description,
        amount=amount,
        category=category,
        quarter="2026-Q3",
        visibility="private",
        owner=subject,
    )
    EXPENSES.append(expense)
    return expense.public_dict()


def approve_expense(expense_id: str) -> dict | None:
    """Mark an expense approved."""
    for expense in EXPENSES:
        if expense.id == expense_id:
            expense.approved = True
            return expense.public_dict()
    return None
```

- [ ] **Step 6: Implement the routes**

```python
# services/toolserver/src/toolserver/routes.py
"""Expense API endpoints.

Each private endpoint declares its required scope as a dependency, so the
authorization rule sits next to the route it protects and cannot drift.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from toolserver.auth import Claims, require_scope
from toolserver.data import add_expense, approve_expense, expenses_for, public_expenses

router = APIRouter()


class NewExpense(BaseModel):
    description: str = Field(min_length=1)
    amount: float = Field(gt=0)
    category: str = Field(min_length=1)


@router.get("/public/expenses")
async def search_public(q: str = "") -> dict:
    """Anonymous search across public company spend."""
    return {"results": public_expenses(q)}


@router.get("/me/expenses")
async def my_expenses(
    quarter: str | None = None,
    claims: Claims = Depends(require_scope("expenses:read")),
) -> dict:
    """The caller's own expenses."""
    rows = expenses_for(claims.subject, quarter)
    return {
        "subject": claims.subject,
        "quarter": quarter,
        "results": rows,
        "total": round(sum(r["amount"] for r in rows), 2),
    }


@router.post("/me/expenses", status_code=201)
async def submit_expense(
    body: NewExpense,
    claims: Claims = Depends(require_scope("expenses:write")),
) -> dict:
    """File a new expense for the caller."""
    return add_expense(claims.subject, body.description, body.amount, body.category)


@router.post("/expenses/{expense_id}/approve")
async def approve(
    expense_id: str,
    claims: Claims = Depends(require_scope("expenses:approve")),
) -> dict:
    """Approve someone's expense — the highest-privilege operation."""
    result = approve_expense(expense_id)
    if result is None:
        raise HTTPException(404, {"error": "not_found", "expense_id": expense_id})
    return result
```

- [ ] **Step 7: Implement the app with a JSON error shape**

```python
# services/toolserver/src/toolserver/app.py
"""Expenses resource server."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from obs.fastapi import TraceMiddleware
from obs.logging import setup_logging
from toolserver.routes import router

setup_logging("toolserver")

app = FastAPI(title="Expenses Tool Server")
app.add_middleware(TraceMiddleware)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return dict details verbatim so clients get a stable error shape."""
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=detail)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv sync && uv run pytest tests/test_toolserver.py -v`
Expected: PASS (9 tests)

- [ ] **Step 9: Commit**

```bash
git add agents-distributed-systems/services/toolserver agents-distributed-systems/tests/test_toolserver.py
git commit -m "feat: expenses tool server with independent JWT and scope verification"
```

---

### Task 4: Token proxy — vault and OAuth client

**Files:**
- Create: `services/proxy/pyproject.toml`
- Create: `services/proxy/src/proxy/vault.py`
- Create: `services/proxy/src/proxy/oauth.py`
- Create: `services/proxy/src/proxy/routes_auth.py`
- Create: `services/proxy/src/proxy/app.py`
- Create: `tests/test_proxy_auth.py`

**Interfaces:**
- Consumes: the IdP's `GET /authorize`, `POST /token` (Task 2).
- Produces:
  - `proxy.app.app` — FastAPI instance
  - `proxy.vault.TokenRecord` dataclass: `access_token: str`, `refresh_token: str`, `scopes: list[str]`, `subject: str`, `expires_at: float`
  - `proxy.vault.Vault` with `put(session_id, record)`, `get(session_id) -> TokenRecord | None`, `status(session_id) -> dict`, `clear(session_id)`
  - `proxy.vault.vault` — module-level singleton
  - `proxy.oauth.new_pkce() -> tuple[str, str]` returning `(verifier, challenge)`
  - `proxy.oauth.build_authorize_url(scopes, state, challenge) -> str`
  - `proxy.oauth.exchange_code(code, verifier) -> dict`
  - `proxy.oauth.refresh(refresh_token) -> dict`
  - `proxy.routes_auth.pending` — dict of `state -> PendingAuth`
  - HTTP: `GET /auth/status`, `POST /auth/start`, `GET /auth/callback`

**Endpoint contracts:**

`GET /auth/status?session_id=…` → `{"authenticated": bool, "scopes": [str], "subject": str | None}`. **Never** includes a token.

`POST /auth/start` body `{"session_id": str, "scopes": [str]}` → `{"authorize_url": str, "state": str}`.

`GET /auth/callback?code=…&state=…` → HTML confirmation page. On `error=access_denied`, records the denial and returns an explanatory page.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_proxy_auth.py
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from idp.app import app as idp_app
from proxy.app import app as proxy_app
from proxy.vault import TokenRecord, vault


@pytest.fixture(autouse=True)
def clean_vault():
    vault.clear_all()
    yield
    vault.clear_all()


@pytest.fixture
def proxy_client(monkeypatch):
    """Point the proxy's outbound IdP calls at the in-process IdP app."""
    idp_transport = httpx.ASGITransport(app=idp_app)

    import proxy.oauth as oauth

    def fake_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=idp_transport, base_url=oauth.IDP_BASE_URL)

    monkeypatch.setattr(oauth, "idp_client", fake_client)
    transport = httpx.ASGITransport(app=proxy_app)
    return httpx.AsyncClient(transport=transport, base_url="http://proxy")


async def test_status_is_unauthenticated_for_unknown_session(proxy_client):
    async with proxy_client as c:
        r = await c.get("/auth/status", params={"session_id": "s-unknown"})
    assert r.json() == {"authenticated": False, "scopes": [], "subject": None}


async def test_status_never_leaks_a_token(proxy_client):
    vault.put(
        "s-1",
        TokenRecord(
            access_token="TOP-SECRET",
            refresh_token="ALSO-SECRET",
            scopes=["expenses:read"],
            subject="user-alice",
            expires_at=time.time() + 300,
        ),
    )
    async with proxy_client as c:
        r = await c.get("/auth/status", params={"session_id": "s-1"})
    body = r.text
    assert "TOP-SECRET" not in body
    assert "ALSO-SECRET" not in body
    assert r.json() == {
        "authenticated": True,
        "scopes": ["expenses:read"],
        "subject": "user-alice",
    }


async def test_auth_start_returns_authorize_url_with_pkce(proxy_client):
    async with proxy_client as c:
        r = await c.post(
            "/auth/start", json={"session_id": "s-2", "scopes": ["expenses:read"]}
        )
    body = r.json()
    query = parse_qs(urlparse(body["authorize_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["expenses:read"]
    assert query["state"] == [body["state"]]
    assert len(query["code_challenge"][0]) > 20


async def test_auth_start_does_not_return_the_verifier(proxy_client):
    async with proxy_client as c:
        r = await c.post(
            "/auth/start", json={"session_id": "s-3", "scopes": ["expenses:read"]}
        )
    assert "code_verifier" not in r.text
    assert "verifier" not in r.text


async def test_callback_with_unknown_state_is_rejected(proxy_client):
    async with proxy_client as c:
        r = await c.get("/auth/callback", params={"code": "x", "state": "forged"})
    assert r.status_code == 400
    assert "invalid_state" in r.text


async def test_full_consent_flow_populates_vault(proxy_client):
    idp = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=idp_app), base_url="http://localhost:8081"
    )
    async with proxy_client as c, idp:
        start = (
            await c.post(
                "/auth/start", json={"session_id": "s-4", "scopes": ["expenses:read"]}
            )
        ).json()

        # Walk the user through the IdP consent screen.
        page = await idp.get(start["authorize_url"])
        request_id = page.text.split('name="request_id" value="')[1].split('"')[0]
        redirect = await idp.post(
            "/authorize/decision", data={"request_id": request_id, "decision": "approve"}
        )
        params = parse_qs(urlparse(redirect.headers["location"]).query)

        cb = await c.get(
            "/auth/callback",
            params={"code": params["code"][0], "state": params["state"][0]},
        )
        assert cb.status_code == 200

        status = (await c.get("/auth/status", params={"session_id": "s-4"})).json()

    assert status["authenticated"] is True
    assert status["scopes"] == ["expenses:read"]
    assert vault.get("s-4").access_token  # token lives here and only here


async def test_denied_consent_leaves_session_unauthenticated(proxy_client):
    idp = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=idp_app), base_url="http://localhost:8081"
    )
    async with proxy_client as c, idp:
        start = (
            await c.post(
                "/auth/start", json={"session_id": "s-5", "scopes": ["expenses:read"]}
            )
        ).json()
        page = await idp.get(start["authorize_url"])
        request_id = page.text.split('name="request_id" value="')[1].split('"')[0]
        redirect = await idp.post(
            "/authorize/decision", data={"request_id": request_id, "decision": "deny"}
        )
        params = parse_qs(urlparse(redirect.headers["location"]).query)

        await c.get(
            "/auth/callback",
            params={"error": params["error"][0], "state": params["state"][0]},
        )
        status = (await c.get("/auth/status", params={"session_id": "s-5"})).json()

    assert status["authenticated"] is False


async def test_state_is_single_use(proxy_client):
    async with proxy_client as c:
        start = (
            await c.post(
                "/auth/start", json={"session_id": "s-6", "scopes": ["expenses:read"]}
            )
        ).json()
        first = await c.get(
            "/auth/callback", params={"error": "access_denied", "state": start["state"]}
        )
        second = await c.get(
            "/auth/callback", params={"error": "access_denied", "state": start["state"]}
        )
    assert first.status_code == 200
    assert second.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_proxy_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxy'`

- [ ] **Step 3: Create the package manifest**

```toml
# services/proxy/pyproject.toml
[project]
name = "proxy"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "obs",
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "httpx>=0.27",
    "pydantic>=2.9",
]

[tool.uv.sources]
obs = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 4: Implement the vault**

```python
# services/proxy/src/proxy/vault.py
"""The trust boundary.

This module is the ONLY place in the system where an access token is stored.
Everything it exposes to callers outside the proxy goes through `status()`,
which returns scope names and nothing else. If you are reviewing this project
for token leakage, this file plus routes_tools.py is the whole audit surface.

Storage is a process-local dict: no persistence, no encryption at rest, no
multi-tenancy. A production version would use per-session encryption and a
shared store, which changes the code but not the architecture.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from obs.logging import log_event


@dataclass
class TokenRecord:
    access_token: str
    refresh_token: str
    scopes: list[str]
    subject: str
    expires_at: float

    def is_expired(self, skew_seconds: int = 15) -> bool:
        """True when the token is expired or close enough that we should refresh."""
        return time.time() >= (self.expires_at - skew_seconds)


@dataclass
class Vault:
    _records: dict[str, TokenRecord] = field(default_factory=dict)

    def put(self, session_id: str, record: TokenRecord) -> None:
        self._records[session_id] = record
        log_event(
            "vault.stored",
            session_id=session_id,
            subject=record.subject,
            scopes=record.scopes,
            expires_in=round(record.expires_at - time.time()),
        )

    def get(self, session_id: str) -> TokenRecord | None:
        return self._records.get(session_id)

    def status(self, session_id: str) -> dict:
        """Public projection: scope names only, never token material."""
        record = self._records.get(session_id)
        if record is None:
            return {"authenticated": False, "scopes": [], "subject": None}
        return {
            "authenticated": True,
            "scopes": list(record.scopes),
            "subject": record.subject,
        }

    def clear(self, session_id: str) -> None:
        if self._records.pop(session_id, None) is not None:
            log_event("vault.cleared", session_id=session_id)

    def clear_all(self) -> None:
        self._records.clear()


vault = Vault()
```

- [ ] **Step 5: Implement the OAuth client**

```python
# services/proxy/src/proxy/oauth.py
"""OAuth2 confidential client.

The proxy — not the agent, not the browser — holds the client secret and runs
the code exchange. `idp_client` is a module-level factory so tests can swap in
an in-process ASGI transport.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from urllib.parse import urlencode

import httpx

from obs.logging import log_event
from obs.trace import get_trace_id

IDP_BASE_URL = os.getenv("IDP_BASE_URL", "http://localhost:8081")
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "agent-demo")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "dev-secret-not-for-production")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8083/auth/callback")


def idp_client() -> httpx.AsyncClient:
    """Outbound client for IdP calls. Patched in tests."""
    return httpx.AsyncClient(
        base_url=IDP_BASE_URL,
        timeout=10.0,
        event_hooks={
            "request": [lambda r: r.headers.__setitem__("X-Trace-Id", get_trace_id())]
        },
    )


def new_pkce() -> tuple[str, str]:
    """Return a (verifier, challenge) PKCE pair using S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def build_authorize_url(scopes: list[str], state: str, challenge: str) -> str:
    """Build the URL the user's browser is sent to."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{IDP_BASE_URL}/authorize?{query}"


async def exchange_code(code: str, verifier: str) -> dict:
    """Trade an authorization code for tokens. Raises httpx.HTTPStatusError on failure."""
    async with idp_client() as client:
        response = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code_verifier": verifier,
            },
        )
    response.raise_for_status()
    log_event("oauth.code_exchanged", grant="authorization_code")
    return response.json()


async def refresh(refresh_token: str) -> dict:
    """Trade a refresh token for a new access token."""
    async with idp_client() as client:
        response = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
    response.raise_for_status()
    log_event("oauth.refreshed", grant="refresh_token")
    return response.json()
```

- [ ] **Step 6: Implement the auth routes**

```python
# services/proxy/src/proxy/routes_auth.py
"""Auth lifecycle endpoints.

/auth/start and /auth/status are called by the agent; /auth/callback is called
by the user's browser. The `state` parameter binds a browser redirect back to
the agent session that requested it, which is what stops one user's callback
from authorizing another user's session.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

import httpx
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from obs.logging import log_event
from proxy.oauth import build_authorize_url, exchange_code, new_pkce
from proxy.vault import TokenRecord, vault

router = APIRouter()


@dataclass
class PendingAuth:
    session_id: str
    scopes: list[str]
    verifier: str
    created_at: float


# state -> PendingAuth. Single use: popped on callback.
pending: dict[str, PendingAuth] = {}


class StartRequest(BaseModel):
    session_id: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        status_code=status,
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{title}</title></head>"
            "<body style=\"font-family:system-ui,sans-serif;max-width:30rem;"
            'margin:4rem auto">'
            f"<h1>{title}</h1><p>{body}</p></body></html>"
        ),
    )


@router.get("/auth/status")
async def auth_status(session_id: str) -> dict:
    """Scope names only. This response is the agent's entire view of auth."""
    status = vault.status(session_id)
    log_event("auth.status", session_id=session_id, **status)
    return status


@router.post("/auth/start")
async def auth_start(body: StartRequest) -> dict:
    """Begin an authorization-code flow and return the URL for the consent card."""
    verifier, challenge = new_pkce()
    state = secrets.token_urlsafe(24)
    pending[state] = PendingAuth(
        session_id=body.session_id,
        scopes=body.scopes,
        verifier=verifier,
        created_at=time.time(),
    )
    log_event("auth.started", session_id=body.session_id, scopes=body.scopes)
    return {
        "authorize_url": build_authorize_url(body.scopes, state, challenge),
        "state": state,
    }


@router.get("/auth/callback")
async def auth_callback(
    state: str, code: str | None = None, error: str | None = None
) -> HTMLResponse:
    """Redirect target for the user's browser after the consent decision."""
    record = pending.pop(state, None)  # single use
    if record is None:
        log_event("auth.callback_rejected", reason="invalid_state")
        return _page("Authorization failed", "invalid_state", status=400)

    if error:
        log_event("auth.denied", session_id=record.session_id, error=error)
        return _page(
            "Authorization declined",
            "No access was granted. You can close this tab and tell the agent "
            "what you would like to do instead.",
        )

    if not code:
        return _page("Authorization failed", "missing_code", status=400)

    try:
        tokens = await exchange_code(code, record.verifier)
    except httpx.HTTPStatusError as exc:
        log_event("auth.exchange_failed", status=exc.response.status_code)
        return _page("Authorization failed", "token_exchange_failed", status=502)

    vault.put(
        record.session_id,
        TokenRecord(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            scopes=tokens["scope"].split(),
            subject="user-alice",
            expires_at=time.time() + tokens["expires_in"],
        ),
    )
    return _page(
        "Authorized",
        "Access granted. You can close this tab — the agent is continuing.",
    )
```

- [ ] **Step 7: Implement the app**

```python
# services/proxy/src/proxy/app.py
"""Token proxy / auth broker."""

from __future__ import annotations

from fastapi import FastAPI

from obs.fastapi import TraceMiddleware
from obs.logging import setup_logging
from proxy.routes_auth import router as auth_router

setup_logging("proxy")

app = FastAPI(title="Token Proxy")
app.add_middleware(TraceMiddleware)
app.include_router(auth_router)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv sync && uv run pytest tests/test_proxy_auth.py -v`
Expected: PASS (8 tests)

- [ ] **Step 9: Commit**

```bash
git add agents-distributed-systems/services/proxy agents-distributed-systems/tests/test_proxy_auth.py
git commit -m "feat: token proxy vault and OAuth2 PKCE consent flow"
```

---

### Task 5: Token proxy — tool manifest and generic router

**Files:**
- Create: `services/proxy/src/proxy/manifest.py`
- Create: `services/proxy/src/proxy/routes_tools.py`
- Modify: `services/proxy/src/proxy/app.py` (include the tools router)
- Create: `tests/test_proxy_tools.py`

**Interfaces:**
- Consumes: `proxy.vault.vault`, `proxy.oauth.refresh` (Task 4); the tool server's HTTP API (Task 3).
- Produces:
  - `proxy.manifest.ToolSpec` dataclass: `name, description, method, path, required_scope (str | None), args (dict[str, ArgSpec]), query_args (list[str]), body_args (list[str]), path_args (list[str])`
  - `proxy.manifest.ArgSpec` dataclass: `type: str`, `description: str`, `required: bool`
  - `proxy.manifest.TOOLS: dict[str, ToolSpec]`
  - `proxy.manifest.manifest_document() -> list[dict]`
  - HTTP: `GET /tools/manifest`, `POST /tools/{tool_name}`

**Endpoint contracts:**

`GET /tools/manifest` → `[{"name","description","required_scope","args":{name:{"type","description","required"}}}, …]`. Contains no routing detail — the agent learns *what* it can call, never *where*.

`POST /tools/{tool_name}` body `{"session_id": str, "args": {…}}` →
- `200 {"ok": true, "data": {…}}`
- `403 {"ok": false, "error": "missing_scope", "required_scope": "…", "granted_scopes": [...]}`
- `404 {"ok": false, "error": "unknown_tool"}`
- `502 {"ok": false, "error": "upstream_error", "status": int}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_proxy_tools.py
import time

import httpx
import pytest

from idp.app import app as idp_app
from idp.tokens import mint_access_token
from proxy.app import app as proxy_app
from proxy.vault import TokenRecord, vault
from toolserver.app import app as toolserver_app


@pytest.fixture(autouse=True)
def clean_vault():
    vault.clear_all()
    yield
    vault.clear_all()


@pytest.fixture
def proxy_client(monkeypatch):
    """Wire the proxy's outbound calls to the in-process tool server and IdP."""
    import proxy.oauth as oauth
    import proxy.routes_tools as routes_tools

    idp_transport = httpx.ASGITransport(app=idp_app)
    tools_transport = httpx.ASGITransport(app=toolserver_app)

    monkeypatch.setattr(
        oauth,
        "idp_client",
        lambda: httpx.AsyncClient(transport=idp_transport, base_url=oauth.IDP_BASE_URL),
    )
    monkeypatch.setattr(
        routes_tools,
        "toolserver_client",
        lambda: httpx.AsyncClient(
            transport=tools_transport, base_url=routes_tools.TOOLSERVER_BASE_URL
        ),
    )
    transport = httpx.ASGITransport(app=proxy_app)
    return httpx.AsyncClient(transport=transport, base_url="http://proxy")


def grant(session_id: str, scopes: list[str], ttl: int = 300) -> None:
    vault.put(
        session_id,
        TokenRecord(
            access_token=mint_access_token("user-alice", scopes, ttl),
            refresh_token="refresh-abc",
            scopes=scopes,
            subject="user-alice",
            expires_at=time.time() + ttl,
        ),
    )


async def test_manifest_lists_tools_with_scopes(proxy_client):
    async with proxy_client as c:
        r = await c.get("/tools/manifest")
    by_name = {t["name"]: t for t in r.json()}
    assert by_name["search_public_expenses"]["required_scope"] is None
    assert by_name["list_my_expenses"]["required_scope"] == "expenses:read"
    assert by_name["submit_expense"]["required_scope"] == "expenses:write"
    assert by_name["approve_expense"]["required_scope"] == "expenses:approve"


async def test_manifest_never_exposes_routing_details(proxy_client):
    async with proxy_client as c:
        r = await c.get("/tools/manifest")
    body = r.text
    assert "/me/expenses" not in body
    assert "path" not in body
    assert "method" not in body


async def test_manifest_describes_arguments(proxy_client):
    async with proxy_client as c:
        r = await c.get("/tools/manifest")
    tool = next(t for t in r.json() if t["name"] == "list_my_expenses")
    assert tool["args"]["quarter"]["type"] == "string"
    assert tool["args"]["quarter"]["description"]


async def test_public_tool_works_without_any_session(proxy_client):
    async with proxy_client as c:
        r = await c.post(
            "/tools/search_public_expenses",
            json={"session_id": "s-none", "args": {"q": "travel"}},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["data"]["results"]


async def test_private_tool_without_grant_returns_missing_scope(proxy_client):
    async with proxy_client as c:
        r = await c.post(
            "/tools/list_my_expenses",
            json={"session_id": "s-none", "args": {"quarter": "2026-Q1"}},
        )
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "missing_scope"
    assert body["required_scope"] == "expenses:read"


async def test_private_tool_with_grant_returns_data(proxy_client):
    grant("s-ok", ["expenses:read"])
    async with proxy_client as c:
        r = await c.post(
            "/tools/list_my_expenses",
            json={"session_id": "s-ok", "args": {"quarter": "2026-Q1"}},
        )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["subject"] == "user-alice"
    assert data["total"] > 0


async def test_tool_response_never_contains_the_token(proxy_client):
    grant("s-ok2", ["expenses:read"])
    async with proxy_client as c:
        r = await c.post(
            "/tools/list_my_expenses",
            json={"session_id": "s-ok2", "args": {"quarter": "2026-Q1"}},
        )
    assert vault.get("s-ok2").access_token not in r.text


async def test_unknown_tool_is_404(proxy_client):
    async with proxy_client as c:
        r = await c.post("/tools/rm_rf", json={"session_id": "s", "args": {}})
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_tool"


async def test_body_and_path_args_are_routed_correctly(proxy_client):
    grant("s-write", ["expenses:write"])
    async with proxy_client as c:
        r = await c.post(
            "/tools/submit_expense",
            json={
                "session_id": "s-write",
                "args": {"description": "Taxi", "amount": 30.0, "category": "travel"},
            },
        )
    assert r.status_code == 200
    assert r.json()["data"]["description"] == "Taxi"


async def test_expired_token_is_refreshed_transparently(proxy_client, monkeypatch):
    """A stale vault entry triggers a refresh; the caller never sees the retry."""
    grant("s-stale", ["expenses:read"], ttl=-30)
    calls: list[str] = []

    import proxy.routes_tools as routes_tools

    async def fake_refresh(refresh_token: str) -> dict:
        calls.append(refresh_token)
        return {
            "access_token": mint_access_token("user-alice", ["expenses:read"], 300),
            "refresh_token": "refresh-def",
            "expires_in": 300,
            "scope": "expenses:read",
        }

    monkeypatch.setattr(routes_tools, "refresh", fake_refresh)

    async with proxy_client as c:
        r = await c.post(
            "/tools/list_my_expenses",
            json={"session_id": "s-stale", "args": {"quarter": "2026-Q1"}},
        )

    assert calls == ["refresh-abc"]
    assert r.status_code == 200
    assert vault.get("s-stale").refresh_token == "refresh-def"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_proxy_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'proxy.manifest'`

- [ ] **Step 3: Implement the manifest**

```python
# services/proxy/src/proxy/manifest.py
"""Tool registry.

This is the seam that makes the agent portable. The registry knows two things
the agent must never learn: which HTTP route backs a tool, and which scope it
needs. The agent receives only `name`, `description`, and `args` — a generic
contract it could satisfy against any backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArgSpec:
    type: str  # "string" | "number"
    description: str
    required: bool = True


@dataclass
class ToolSpec:
    name: str
    description: str
    method: str
    path: str  # may contain {placeholders} filled from path_args
    required_scope: str | None
    args: dict[str, ArgSpec] = field(default_factory=dict)
    query_args: list[str] = field(default_factory=list)
    body_args: list[str] = field(default_factory=list)
    path_args: list[str] = field(default_factory=list)


TOOLS: dict[str, ToolSpec] = {
    "search_public_expenses": ToolSpec(
        name="search_public_expenses",
        description=(
            "Search publicly visible company spend. Requires no authorization. "
            "Use for aggregate or company-wide questions."
        ),
        method="GET",
        path="/public/expenses",
        required_scope=None,
        args={
            "q": ArgSpec("string", "Free-text search over description and category.", False)
        },
        query_args=["q"],
    ),
    "list_my_expenses": ToolSpec(
        name="list_my_expenses",
        description=(
            "List the current user's own expense records. Use for any question "
            "about what the user personally spent."
        ),
        method="GET",
        path="/me/expenses",
        required_scope="expenses:read",
        args={
            "quarter": ArgSpec(
                "string", "Quarter filter such as '2026-Q1'. Omit for all quarters.", False
            )
        },
        query_args=["quarter"],
    ),
    "submit_expense": ToolSpec(
        name="submit_expense",
        description="File a new expense claim on behalf of the current user.",
        method="POST",
        path="/me/expenses",
        required_scope="expenses:write",
        args={
            "description": ArgSpec("string", "What the expense was for."),
            "amount": ArgSpec("number", "Amount in GBP, greater than zero."),
            "category": ArgSpec("string", "One of: travel, meals, equipment, infra, events."),
        },
        body_args=["description", "amount", "category"],
    ),
    "approve_expense": ToolSpec(
        name="approve_expense",
        description="Approve a submitted expense. Requires approver privileges.",
        method="POST",
        path="/expenses/{expense_id}/approve",
        required_scope="expenses:approve",
        args={"expense_id": ArgSpec("string", "Identifier such as 'exp-002'.")},
        path_args=["expense_id"],
    ),
}


def manifest_document() -> list[dict]:
    """Public projection of the registry — no method, no path."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "required_scope": spec.required_scope,
            "args": {
                arg_name: {
                    "type": arg.type,
                    "description": arg.description,
                    "required": arg.required,
                }
                for arg_name, arg in spec.args.items()
            },
        }
        for spec in TOOLS.values()
    ]
```

- [ ] **Step 4: Implement the generic tool router**

```python
# services/proxy/src/proxy/routes_tools.py
"""Generic tool invocation.

Every agent tool call lands here as POST /tools/{name} with a session id and an
argument bag. This function is where the session id becomes a token — the single
most security-relevant transition in the system, and the reason the agent can
stay ignorant of credentials entirely.
"""

from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from obs.logging import log_event
from obs.trace import get_trace_id
from proxy.manifest import TOOLS, ToolSpec, manifest_document
from proxy.oauth import refresh
from proxy.vault import TokenRecord, vault

TOOLSERVER_BASE_URL = os.getenv("TOOLSERVER_BASE_URL", "http://localhost:8082")

router = APIRouter()


def toolserver_client() -> httpx.AsyncClient:
    """Outbound client for tool server calls. Patched in tests."""
    return httpx.AsyncClient(
        base_url=TOOLSERVER_BASE_URL,
        timeout=15.0,
        event_hooks={
            "request": [lambda r: r.headers.__setitem__("X-Trace-Id", get_trace_id())]
        },
    )


class ToolCall(BaseModel):
    session_id: str = Field(min_length=1)
    args: dict = Field(default_factory=dict)


@router.get("/tools/manifest")
async def manifest() -> list[dict]:
    """The generic tool contract the agent builds its tools from."""
    return manifest_document()


async def _ensure_fresh(session_id: str, record: TokenRecord) -> TokenRecord | None:
    """Refresh a stale token in place. Returns None when refresh fails."""
    if not record.is_expired():
        return record
    try:
        tokens = await refresh(record.refresh_token)
    except httpx.HTTPError as exc:
        log_event("token.refresh_failed", session_id=session_id, error=type(exc).__name__)
        vault.clear(session_id)
        return None
    updated = TokenRecord(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        scopes=tokens["scope"].split(),
        subject=record.subject,
        expires_at=time.time() + tokens["expires_in"],
    )
    vault.put(session_id, updated)
    return updated


def _build_request(spec: ToolSpec, args: dict) -> tuple[str, dict, dict | None]:
    """Split the flat argument bag into path, query, and body per the spec."""
    path = spec.path
    for name in spec.path_args:
        path = path.replace(f"{{{name}}}", str(args.get(name, "")))
    query = {k: args[k] for k in spec.query_args if args.get(k) is not None}
    body = {k: args[k] for k in spec.body_args} if spec.body_args else None
    return path, query, body


@router.post("/tools/{tool_name}")
async def call_tool(tool_name: str, call: ToolCall) -> JSONResponse:
    """Resolve session -> token, attach it, forward, and return the payload."""
    spec = TOOLS.get(tool_name)
    if spec is None:
        log_event("tool.unknown", tool=tool_name)
        return JSONResponse(404, content={"ok": False, "error": "unknown_tool"})

    headers: dict[str, str] = {}

    if spec.required_scope is not None:
        record = vault.get(call.session_id)
        status = vault.status(call.session_id)
        if record is None or spec.required_scope not in record.scopes:
            log_event(
                "tool.denied",
                tool=tool_name,
                session_id=call.session_id,
                required=spec.required_scope,
                granted=status["scopes"],
            )
            return JSONResponse(
                403,
                content={
                    "ok": False,
                    "error": "missing_scope",
                    "required_scope": spec.required_scope,
                    "granted_scopes": status["scopes"],
                },
            )
        record = await _ensure_fresh(call.session_id, record)
        if record is None:
            return JSONResponse(
                403,
                content={
                    "ok": False,
                    "error": "missing_scope",
                    "required_scope": spec.required_scope,
                    "granted_scopes": [],
                },
            )
        # The one line where a token is attached to an outbound request.
        headers["Authorization"] = f"Bearer {record.access_token}"

    path, query, body = _build_request(spec, call.args)
    log_event(
        "tool.forwarding",
        tool=tool_name,
        session_id=call.session_id,
        authenticated=bool(headers),
    )

    async with toolserver_client() as client:
        response = await client.request(
            spec.method, path, params=query, json=body, headers=headers
        )

    if response.status_code >= 400:
        log_event("tool.upstream_error", tool=tool_name, status=response.status_code)
        return JSONResponse(
            502,
            content={
                "ok": False,
                "error": "upstream_error",
                "status": response.status_code,
                "detail": response.json(),
            },
        )

    log_event("tool.succeeded", tool=tool_name, session_id=call.session_id)
    return JSONResponse(200, content={"ok": True, "data": response.json()})
```

- [ ] **Step 5: Register the tools router**

In `services/proxy/src/proxy/app.py`, add the import and the `include_router` call:

```python
from proxy.routes_auth import router as auth_router
from proxy.routes_tools import router as tools_router

...

app.include_router(auth_router)
app.include_router(tools_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_proxy_tools.py -v`
Expected: PASS (10 tests)

- [ ] **Step 7: Run the whole suite to check nothing regressed**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 1-5)

- [ ] **Step 8: Commit**

```bash
git add agents-distributed-systems/services/proxy agents-distributed-systems/tests/test_proxy_tools.py
git commit -m "feat: generic tool manifest and token-attaching proxy router"
```

---

### Task 6: Agent — proxy client and manifest-driven tools

**Files:**
- Create: `agent/pyproject.toml`
- Create: `agent/src/agent_app/proxy_client.py`
- Create: `agent/src/agent_app/tools.py`
- Create: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: proxy HTTP API `GET /auth/status`, `POST /auth/start`, `GET /tools/manifest`, `POST /tools/{name}` (Tasks 4-5).
- Produces:
  - `agent_app.proxy_client.ProxyClient` with sync methods `auth_status(session_id) -> dict`, `auth_start(session_id, scopes) -> dict`, `fetch_manifest() -> list[dict]`, `call_tool(session_id, name, args) -> dict`
  - `agent_app.proxy_client.default_client() -> ProxyClient`
  - `agent_app.tools.TOOL_SCOPES: dict[str, str | None]` — populated by `build_tools`
  - `agent_app.tools.build_tools(client: ProxyClient, session_id_getter: Callable[[], str]) -> list[BaseTool]`
  - `agent_app.tools.REQUEST_AUTHORIZATION = "request_authorization"`

**Design note.** Tools are built from the manifest with `pydantic.create_model`, so adding a tool to the proxy's registry adds it to the agent with no agent code change. Methods are synchronous because LangChain tool functions run in the graph's sync path here; `httpx.Client` is used rather than `AsyncClient`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_tools.py
import httpx
import pytest

from agent_app.proxy_client import ProxyClient
from agent_app.tools import TOOL_SCOPES, build_tools
from proxy.app import app as proxy_app
from proxy.vault import TokenRecord, vault


@pytest.fixture(autouse=True)
def clean_vault():
    vault.clear_all()
    yield
    vault.clear_all()


@pytest.fixture
def client(monkeypatch):
    """A ProxyClient wired to the in-process proxy app."""
    import proxy.routes_tools as routes_tools
    from toolserver.app import app as toolserver_app

    tools_transport = httpx.ASGITransport(app=toolserver_app)
    monkeypatch.setattr(
        routes_tools,
        "toolserver_client",
        lambda: httpx.AsyncClient(
            transport=tools_transport, base_url=routes_tools.TOOLSERVER_BASE_URL
        ),
    )
    http = httpx.Client(
        transport=httpx.WSGITransport(app=None) if False else httpx.ASGITransport(app=proxy_app),
        base_url="http://proxy",
    )
    return ProxyClient(http=http)


def test_build_tools_covers_manifest_plus_escape_hatch(client):
    tools = build_tools(client, lambda: "s-1")
    names = {t.name for t in tools}
    assert "search_public_expenses" in names
    assert "list_my_expenses" in names
    assert "submit_expense" in names
    assert "approve_expense" in names
    assert "request_authorization" in names


def test_tool_scopes_map_is_populated(client):
    build_tools(client, lambda: "s-1")
    assert TOOL_SCOPES["search_public_expenses"] is None
    assert TOOL_SCOPES["list_my_expenses"] == "expenses:read"
    assert TOOL_SCOPES["approve_expense"] == "expenses:approve"


def test_tool_descriptions_come_from_the_manifest(client):
    tools = {t.name: t for t in build_tools(client, lambda: "s-1")}
    assert "publicly visible" in tools["search_public_expenses"].description


def test_tool_args_schema_is_generated_from_manifest(client):
    tools = {t.name: t for t in build_tools(client, lambda: "s-1")}
    fields = tools["submit_expense"].args_schema.model_fields
    assert set(fields) == {"description", "amount", "category"}
    assert fields["amount"].annotation is float


def test_public_tool_invokes_end_to_end(client):
    tools = {t.name: t for t in build_tools(client, lambda: "s-1")}
    result = tools["search_public_expenses"].invoke({"q": "travel"})
    assert "Conference tickets" in result


def test_private_tool_without_grant_returns_readable_error(client):
    tools = {t.name: t for t in build_tools(client, lambda: "s-nope")}
    result = tools["list_my_expenses"].invoke({"quarter": "2026-Q1"})
    assert "missing_scope" in result
    assert "expenses:read" in result


def test_private_tool_with_grant_returns_data(client):
    import time

    from idp.tokens import mint_access_token

    vault.put(
        "s-ok",
        TokenRecord(
            access_token=mint_access_token("user-alice", ["expenses:read"], 300),
            refresh_token="r",
            scopes=["expenses:read"],
            subject="user-alice",
            expires_at=time.time() + 300,
        ),
    )
    tools = {t.name: t for t in build_tools(client, lambda: "s-ok")}
    result = tools["list_my_expenses"].invoke({"quarter": "2026-Q1"})
    assert "Flight LHR-SFO" in result


def test_agent_never_receives_a_token_in_tool_output(client):
    import time

    from idp.tokens import mint_access_token

    token = mint_access_token("user-alice", ["expenses:read"], 300)
    vault.put(
        "s-leak",
        TokenRecord(
            access_token=token,
            refresh_token="r",
            scopes=["expenses:read"],
            subject="user-alice",
            expires_at=time.time() + 300,
        ),
    )
    tools = {t.name: t for t in build_tools(client, lambda: "s-leak")}
    result = tools["list_my_expenses"].invoke({"quarter": "2026-Q1"})
    assert token not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_app'`

- [ ] **Step 3: Create the package manifest**

```toml
# agent/pyproject.toml
[project]
name = "agent-app"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "obs",
    "langchain>=1.3,<2",
    "langgraph>=1.0",
    "langchain-openai>=1.0",
    "httpx>=0.27",
    "pydantic>=2.9",
]

[tool.uv.sources]
obs = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 4: Implement the proxy client**

```python
# agent/src/agent_app/proxy_client.py
"""HTTP client for the token proxy.

This is the agent's entire interface to the outside world. Note what is absent:
no IdP URL, no client secret, no token handling. If this file ever grows an
`Authorization` header, the architecture has been broken.
"""

from __future__ import annotations

import os

import httpx

from obs.logging import log_event
from obs.trace import get_trace_id

PROXY_BASE_URL = os.getenv("PROXY_BASE_URL", "http://localhost:8083")


class ProxyClient:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(
            base_url=PROXY_BASE_URL,
            timeout=30.0,
            event_hooks={
                "request": [
                    lambda r: r.headers.__setitem__("X-Trace-Id", get_trace_id())
                ]
            },
        )

    def auth_status(self, session_id: str) -> dict:
        """Return {'authenticated': bool, 'scopes': [...], 'subject': str|None}."""
        response = self._http.get("/auth/status", params={"session_id": session_id})
        response.raise_for_status()
        return response.json()

    def auth_start(self, session_id: str, scopes: list[str]) -> dict:
        """Begin a consent flow; returns {'authorize_url', 'state'}."""
        response = self._http.post(
            "/auth/start", json={"session_id": session_id, "scopes": scopes}
        )
        response.raise_for_status()
        return response.json()

    def fetch_manifest(self) -> list[dict]:
        """Discover the available tool contracts."""
        response = self._http.get("/tools/manifest")
        response.raise_for_status()
        return response.json()

    def call_tool(self, session_id: str, name: str, args: dict) -> dict:
        """Invoke a tool. Returns the proxy envelope, error responses included."""
        response = self._http.post(
            f"/tools/{name}", json={"session_id": session_id, "args": args}
        )
        log_event("agent.tool_called", tool=name, status=response.status_code)
        return response.json()


def default_client() -> ProxyClient:
    return ProxyClient()
```

- [ ] **Step 5: Implement manifest-driven tool construction**

```python
# agent/src/agent_app/tools.py
"""Build LangChain tools from the proxy's manifest.

The agent has no compiled-in knowledge of the tool server. It asks the proxy
what tools exist, generates argument schemas from the descriptions, and calls
them back through the proxy by name. Adding a tool is a proxy-side change.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field, create_model

from agent_app.proxy_client import ProxyClient

REQUEST_AUTHORIZATION = "request_authorization"

# tool name -> required scope (None when public). Read by the middleware.
TOOL_SCOPES: dict[str, str | None] = {}

_PY_TYPES: dict[str, type] = {"string": str, "number": float, "integer": int}


def _args_model(tool_name: str, args: dict[str, dict[str, Any]]):
    """Turn manifest argument descriptions into a pydantic model."""
    fields: dict[str, tuple[Any, Any]] = {}
    for arg_name, spec in args.items():
        python_type = _PY_TYPES.get(spec["type"], str)
        if spec.get("required", True):
            fields[arg_name] = (python_type, Field(description=spec["description"]))
        else:
            fields[arg_name] = (
                python_type | None,
                Field(default=None, description=spec["description"]),
            )
    return create_model(f"{tool_name}_Args", **fields)


def _render(envelope: dict) -> str:
    """Flatten the proxy envelope into a string the model can read."""
    if envelope.get("ok"):
        return json.dumps(envelope["data"], indent=2)
    return json.dumps(envelope, indent=2)


def build_tools(
    client: ProxyClient, session_id_getter: Callable[[], str]
) -> list[BaseTool]:
    """Construct the full tool list, including the authorization escape hatch."""
    TOOL_SCOPES.clear()
    tools: list[BaseTool] = []

    for spec in client.fetch_manifest():
        name = spec["name"]
        TOOL_SCOPES[name] = spec["required_scope"]

        def make(tool_name: str) -> Callable[..., str]:
            def invoke(**kwargs: Any) -> str:
                args = {k: v for k, v in kwargs.items() if v is not None}
                return _render(client.call_tool(session_id_getter(), tool_name, args))

            return invoke

        tools.append(
            StructuredTool.from_function(
                func=make(name),
                name=name,
                description=spec["description"],
                args_schema=_args_model(name, spec["args"]),
            )
        )

    # Always available. The middleware intercepts this before it ever executes,
    # so the body is only a fallback for a misconfigured graph.
    def request_authorization(scopes: list[str]) -> str:
        """Ask the user to authorize additional access."""
        return (
            "Authorization could not be requested because no interactive session "
            "is attached."
        )

    TOOL_SCOPES[REQUEST_AUTHORIZATION] = None
    tools.append(
        StructuredTool.from_function(
            func=request_authorization,
            name=REQUEST_AUTHORIZATION,
            description=(
                "Ask the user to grant additional access. Call this when the user's "
                "request needs data or an action you have no tool for. Pass the "
                "scopes you need, for example ['expenses:read'] to read the user's "
                "own expenses, ['expenses:write'] to file one, or "
                "['expenses:approve'] to approve one."
            ),
            args_schema=create_model(
                "request_authorization_Args",
                scopes=(list[str], Field(description="Scope names to request.")),
            ),
        )
    )
    return tools
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv sync && uv run pytest tests/test_agent_tools.py -v`
Expected: PASS (8 tests)

- [ ] **Step 7: Commit**

```bash
git add agents-distributed-systems/agent agents-distributed-systems/tests/test_agent_tools.py
git commit -m "feat: manifest-driven agent tools over a generic proxy contract"
```

---

### Task 7: AuthStateMiddleware — dynamic filtering and the consent interrupt

**Files:**
- Create: `agent/src/agent_app/middleware.py`
- Create: `tests/test_middleware.py`

**Interfaces:**
- Consumes: `agent_app.proxy_client.ProxyClient`, `agent_app.tools.TOOL_SCOPES`, `agent_app.tools.REQUEST_AUTHORIZATION` (Task 6).
- Produces:
  - `agent_app.middleware.AuthContext` dataclass: `session_id: str`
  - `agent_app.middleware.AuthAgentState(AgentState)` with `auth_scopes: NotRequired[list[str]]`, `auth_subject: NotRequired[str | None]`
  - `agent_app.middleware.AuthStateMiddleware(AgentMiddleware)` — constructor `AuthStateMiddleware(client: ProxyClient)`
  - `agent_app.middleware.CONSENT_INTERRUPT_TYPE = "oauth_consent"`

**Behaviour contract.** Verified against langchain 1.3.14:
- `before_agent` calls `auth_status` and seeds `auth_scopes` / `auth_subject` into state.
- `wrap_model_call` filters `request.tools` against `TOOL_SCOPES` and the state's scopes, then calls `handler(request.override(tools=allowed))`.
- `wrap_tool_call` intercepts `request_authorization`, calls `auth_start`, and raises `interrupt({...})`. On resume it re-reads status and returns a `Command` that updates `auth_scopes` and appends a `ToolMessage`.

The interrupt payload shape the UI renders:

```json
{
  "type": "oauth_consent",
  "authorize_url": "http://localhost:8081/authorize?...",
  "scopes": ["expenses:read"],
  "reason": "The agent needs access to your expenses."
}
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_middleware.py
import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_app.middleware import AuthAgentState, AuthContext, AuthStateMiddleware
from agent_app.tools import build_tools


class FakeToolModel(GenericFakeChatModel):
    """GenericFakeChatModel does not implement bind_tools; record and ignore."""

    def bind_tools(self, tools, **kwargs):
        FakeToolModel.last_tools = [getattr(t, "name", t) for t in tools]
        return self


class StubClient:
    """Stands in for ProxyClient, recording calls and scripting auth state."""

    def __init__(self, manifest, scopes=None):
        self._manifest = manifest
        self.scopes = list(scopes or [])
        self.started: list[tuple[str, list[str]]] = []
        self.calls: list[tuple[str, dict]] = []

    def fetch_manifest(self):
        return self._manifest

    def auth_status(self, session_id):
        return {
            "authenticated": bool(self.scopes),
            "scopes": list(self.scopes),
            "subject": "user-alice" if self.scopes else None,
        }

    def auth_start(self, session_id, scopes):
        self.started.append((session_id, list(scopes)))
        return {"authorize_url": "http://idp/authorize?x=1", "state": "st-1"}

    def call_tool(self, session_id, name, args):
        self.calls.append((name, args))
        return {"ok": True, "data": {"rows": 3}}


MANIFEST = [
    {
        "name": "search_public_expenses",
        "description": "Search public spend.",
        "required_scope": None,
        "args": {"q": {"type": "string", "description": "Query.", "required": False}},
    },
    {
        "name": "list_my_expenses",
        "description": "List the user's own expenses.",
        "required_scope": "expenses:read",
        "args": {
            "quarter": {"type": "string", "description": "Quarter.", "required": False}
        },
    },
]


def build_agent(client, script):
    model = FakeToolModel(messages=iter(script))
    tools = build_tools(client, lambda: "s-1")
    return create_agent(
        model=model,
        tools=tools,
        middleware=[AuthStateMiddleware(client)],
        context_schema=AuthContext,
        checkpointer=InMemorySaver(),
    )


def test_unauthenticated_session_hides_scoped_tools():
    client = StubClient(MANIFEST, scopes=[])
    agent = build_agent(client, [AIMessage(content="I can only search public data.")])
    agent.invoke(
        {"messages": [("user", "hello")]},
        {"configurable": {"thread_id": "t1"}},
        context=AuthContext(session_id="s-1"),
    )
    assert "list_my_expenses" not in FakeToolModel.last_tools
    assert "search_public_expenses" in FakeToolModel.last_tools
    assert "request_authorization" in FakeToolModel.last_tools


def test_authenticated_session_reveals_scoped_tools():
    client = StubClient(MANIFEST, scopes=["expenses:read"])
    agent = build_agent(client, [AIMessage(content="ok")])
    agent.invoke(
        {"messages": [("user", "hello")]},
        {"configurable": {"thread_id": "t2"}},
        context=AuthContext(session_id="s-1"),
    )
    assert "list_my_expenses" in FakeToolModel.last_tools


def test_before_agent_seeds_scopes_into_state():
    client = StubClient(MANIFEST, scopes=["expenses:read"])
    agent = build_agent(client, [AIMessage(content="ok")])
    out = agent.invoke(
        {"messages": [("user", "hi")]},
        {"configurable": {"thread_id": "t3"}},
        context=AuthContext(session_id="s-1"),
    )
    assert out["auth_scopes"] == ["expenses:read"]
    assert out["auth_subject"] == "user-alice"


def test_request_authorization_raises_a_consent_interrupt():
    client = StubClient(MANIFEST, scopes=[])
    script = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "request_authorization",
                    "args": {"scopes": ["expenses:read"]},
                    "id": "c1",
                }
            ],
        )
    ]
    agent = build_agent(client, script)
    out = agent.invoke(
        {"messages": [("user", "what did I spend?")]},
        {"configurable": {"thread_id": "t4"}},
        context=AuthContext(session_id="s-1"),
    )
    payload = out["__interrupt__"][0].value
    assert payload["type"] == "oauth_consent"
    assert payload["scopes"] == ["expenses:read"]
    assert payload["authorize_url"] == "http://idp/authorize?x=1"
    assert client.started == [("s-1", ["expenses:read"])]


def test_resume_after_consent_widens_tools_and_completes():
    client = StubClient(MANIFEST, scopes=[])
    script = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "request_authorization",
                    "args": {"scopes": ["expenses:read"]},
                    "id": "c1",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "list_my_expenses", "args": {"quarter": "2026-Q1"}, "id": "c2"}
            ],
        ),
        AIMessage(content="You spent 1468.90."),
    ]
    agent = build_agent(client, script)
    cfg = {"configurable": {"thread_id": "t5"}}
    ctx = AuthContext(session_id="s-1")

    agent.invoke({"messages": [("user", "what did I spend?")]}, cfg, context=ctx)

    # The user consents out of band; the proxy vault now has a grant.
    client.scopes = ["expenses:read"]

    out = agent.invoke(Command(resume={"granted": True}), cfg, context=ctx)

    assert out["auth_scopes"] == ["expenses:read"]
    assert "list_my_expenses" in FakeToolModel.last_tools
    assert client.calls == [("list_my_expenses", {"quarter": "2026-Q1"})]
    assert out["messages"][-1].content == "You spent 1468.90."


def test_denied_consent_returns_a_tool_message_and_keeps_tools_hidden():
    client = StubClient(MANIFEST, scopes=[])
    script = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "request_authorization",
                    "args": {"scopes": ["expenses:read"]},
                    "id": "c1",
                }
            ],
        ),
        AIMessage(content="Understood, I will not access your expenses."),
    ]
    agent = build_agent(client, script)
    cfg = {"configurable": {"thread_id": "t6"}}
    ctx = AuthContext(session_id="s-1")

    agent.invoke({"messages": [("user", "what did I spend?")]}, cfg, context=ctx)
    out = agent.invoke(Command(resume={"granted": False}), cfg, context=ctx)

    assert out["auth_scopes"] == []
    assert "list_my_expenses" not in FakeToolModel.last_tools
    tool_messages = [m for m in out["messages"] if m.type == "tool"]
    assert "declined" in tool_messages[-1].content.lower()


def test_middleware_never_stores_a_token_in_state():
    client = StubClient(MANIFEST, scopes=["expenses:read"])
    agent = build_agent(client, [AIMessage(content="ok")])
    out = agent.invoke(
        {"messages": [("user", "hi")]},
        {"configurable": {"thread_id": "t7"}},
        context=AuthContext(session_id="s-1"),
    )
    assert set(out) <= {"messages", "auth_scopes", "auth_subject", "structured_response"}
    assert "token" not in str(out).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_app.middleware'`

- [ ] **Step 3: Implement the middleware**

```python
# agent/src/agent_app/middleware.py
"""Authentication middleware.

Three jobs, in order of the agent loop:

1. `before_agent` asks the proxy what this session is allowed to do and puts the
   answer — scope names, nothing more — into agent state.
2. `wrap_model_call` filters the tool list against those scopes before the model
   sees it. Unauthorized tools are absent rather than denied, so the model never
   burns a turn on a call that cannot succeed.
3. `wrap_tool_call` intercepts `request_authorization`, starts an OAuth flow via
   the proxy, and suspends the graph with an `interrupt()` carrying the consent
   URL. On resume it re-reads status so the widened tool set takes effect.

What this file never touches: an access token, a refresh token, a client secret.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from typing_extensions import NotRequired

from agent_app.proxy_client import ProxyClient
from agent_app.tools import REQUEST_AUTHORIZATION, TOOL_SCOPES
from obs.logging import log_event

CONSENT_INTERRUPT_TYPE = "oauth_consent"


@dataclass
class AuthContext:
    """Runtime context. The session id is the agent's only handle on identity."""

    session_id: str


class AuthAgentState(AgentState):
    auth_scopes: NotRequired[list[str]]
    auth_subject: NotRequired[str | None]


class AuthStateMiddleware(AgentMiddleware[AuthAgentState, AuthContext]):
    state_schema = AuthAgentState

    def __init__(self, client: ProxyClient) -> None:
        super().__init__()
        self._client = client

    # -- 1. seed auth state ------------------------------------------------

    def before_agent(
        self, state: AuthAgentState, runtime: Runtime[AuthContext]
    ) -> dict[str, Any] | None:
        status = self._client.auth_status(runtime.context.session_id)
        log_event(
            "middleware.auth_status",
            session_id=runtime.context.session_id,
            scopes=status["scopes"],
        )
        return {"auth_scopes": status["scopes"], "auth_subject": status["subject"]}

    # -- 2. filter the tool surface ---------------------------------------

    def wrap_model_call(
        self,
        request: ModelRequest[AuthContext],
        handler: Callable[[ModelRequest[AuthContext]], ModelResponse],
    ) -> ModelResponse:
        granted = set(request.state.get("auth_scopes") or [])
        allowed = [
            tool
            for tool in request.tools
            if self._is_available(getattr(tool, "name", ""), granted)
        ]
        log_event(
            "middleware.tools_filtered",
            granted=sorted(granted),
            offered=[getattr(t, "name", "?") for t in allowed],
            withheld=[
                getattr(t, "name", "?") for t in request.tools if t not in allowed
            ],
        )
        return handler(request.override(tools=allowed))

    @staticmethod
    def _is_available(tool_name: str, granted: set[str]) -> bool:
        required = TOOL_SCOPES.get(tool_name)
        return required is None or required in granted

    # -- 3. drive the consent flow ----------------------------------------

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if request.tool_call["name"] != REQUEST_AUTHORIZATION:
            return handler(request)

        session_id = request.runtime.context.session_id
        scopes = request.tool_call["args"].get("scopes") or []
        started = self._client.auth_start(session_id, scopes)
        log_event("middleware.consent_requested", session_id=session_id, scopes=scopes)

        # Suspends the graph. The UI renders this payload as the consent card.
        interrupt(
            {
                "type": CONSENT_INTERRUPT_TYPE,
                "authorize_url": started["authorize_url"],
                "scopes": scopes,
                "reason": (
                    "The agent needs your permission to access "
                    f"{', '.join(scopes)} on your behalf."
                ),
            }
        )

        # Resumed. Re-read the proxy rather than trusting the resume payload:
        # the vault is the source of truth, the UI is not.
        status = self._client.auth_status(session_id)
        log_event(
            "middleware.consent_resolved",
            session_id=session_id,
            scopes=status["scopes"],
        )

        if status["scopes"]:
            content = (
                f"Authorization granted for: {', '.join(status['scopes'])}. "
                "The relevant tools are now available — retry the original action."
            )
        else:
            content = (
                "The user declined authorization. Do not retry; explain what you "
                "cannot do and offer an alternative that needs no access."
            )

        return Command(
            update={
                "auth_scopes": status["scopes"],
                "auth_subject": status["subject"],
                "messages": [
                    ToolMessage(content=content, tool_call_id=request.tool_call["id"])
                ],
            }
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_middleware.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add agents-distributed-systems/agent/src/agent_app/middleware.py agents-distributed-systems/tests/test_middleware.py
git commit -m "feat: auth middleware with dynamic tool filtering and consent interrupt"
```

---

### Task 8: Assembly — graph, compose, UI, end-to-end test

**Files:**
- Create: `agent/src/agent_app/graph.py`
- Create: `agent/langgraph.json`
- Create: `docker-compose.yml`
- Create: `README.md`
- Create: `tests/test_e2e.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces:
  - `agent_app.graph.build_graph() -> CompiledStateGraph`
  - `agent_app.graph.graph` — module-level instance referenced by `langgraph.json`
  - `docker compose up` bringing all five services to a working state

- [ ] **Step 1: Write the failing end-to-end test**

```python
# tests/conftest.py
import pytest

from proxy.vault import vault


@pytest.fixture(autouse=True)
def reset_vault():
    vault.clear_all()
    yield
    vault.clear_all()
```

```python
# tests/test_e2e.py
"""The whole system, in one test.

Every service runs in-process over ASGI transports, so this exercises the real
HTTP contracts without needing docker. The model is scripted rather than live —
we are testing the distributed system, not the LLM.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent_app.middleware import AuthContext, AuthStateMiddleware
from agent_app.proxy_client import ProxyClient
from agent_app.tools import build_tools
from idp.app import app as idp_app
from proxy.app import app as proxy_app
from proxy.vault import vault
from toolserver.app import app as toolserver_app


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        FakeToolModel.last_tools = [getattr(t, "name", t) for t in tools]
        return self


@pytest.fixture
def wired(monkeypatch):
    """Point every service's outbound client at its in-process peer."""
    import proxy.oauth as oauth
    import proxy.routes_tools as routes_tools

    idp_transport = httpx.ASGITransport(app=idp_app)
    tools_transport = httpx.ASGITransport(app=toolserver_app)

    monkeypatch.setattr(
        oauth,
        "idp_client",
        lambda: httpx.AsyncClient(transport=idp_transport, base_url=oauth.IDP_BASE_URL),
    )
    monkeypatch.setattr(
        routes_tools,
        "toolserver_client",
        lambda: httpx.AsyncClient(
            transport=tools_transport, base_url=routes_tools.TOOLSERVER_BASE_URL
        ),
    )

    # The tool server verifies JWTs by fetching the IdP's JWKS over HTTP.
    import toolserver.auth as tsauth

    real_async_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        return real_async_client(transport=idp_transport, base_url=tsauth.IDP_BASE_URL)

    monkeypatch.setattr(tsauth.httpx, "AsyncClient", patched_client)

    proxy_http = httpx.Client(
        transport=httpx.ASGITransport(app=proxy_app), base_url="http://proxy"
    )
    idp_http = httpx.Client(
        transport=httpx.ASGITransport(app=idp_app), base_url="http://localhost:8081"
    )
    return ProxyClient(http=proxy_http), idp_http


def consent(idp_http: httpx.Client, proxy_client: ProxyClient, authorize_url: str, approve: bool):
    """Drive the browser half of the flow: consent screen, then the callback."""
    page = idp_http.get(authorize_url)
    request_id = page.text.split('name="request_id" value="')[1].split('"')[0]
    redirect = idp_http.post(
        "/authorize/decision",
        data={"request_id": request_id, "decision": "approve" if approve else "deny"},
    )
    params = parse_qs(urlparse(redirect.headers["location"]).query)
    callback_params = {"state": params["state"][0]}
    if "code" in params:
        callback_params["code"] = params["code"][0]
    if "error" in params:
        callback_params["error"] = params["error"][0]
    proxy_client._http.get("/auth/callback", params=callback_params)


def test_full_happy_path(wired):
    proxy_client, idp_http = wired
    session_id = "session-e2e-1"

    script = iter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_authorization",
                        "args": {"scopes": ["expenses:read"]},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_my_expenses",
                        "args": {"quarter": "2026-Q1"},
                        "id": "c2",
                    }
                ],
            ),
            AIMessage(content="You spent 1613.90 on expenses in 2026-Q1."),
        ]
    )
    agent = create_agent(
        model=FakeToolModel(messages=script),
        tools=build_tools(proxy_client, lambda: session_id),
        middleware=[AuthStateMiddleware(proxy_client)],
        context_schema=AuthContext,
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "e2e-1"}}
    ctx = AuthContext(session_id=session_id)

    # 1. Cold start: the private tool is not offered.
    first = agent.invoke(
        {"messages": [("user", "How much did I spend on travel last quarter?")]},
        cfg,
        context=ctx,
    )
    assert "list_my_expenses" not in FakeToolModel.last_tools

    # 2. The graph is suspended on a consent interrupt.
    payload = first["__interrupt__"][0].value
    assert payload["type"] == "oauth_consent"
    assert payload["scopes"] == ["expenses:read"]

    # 3. The user consents in the browser.
    consent(idp_http, proxy_client, payload["authorize_url"], approve=True)
    assert vault.get(session_id) is not None

    # 4. Resume: tools widen, the call succeeds, the run completes.
    final = agent.invoke(Command(resume={"granted": True}), cfg, context=ctx)
    assert "list_my_expenses" in FakeToolModel.last_tools
    assert final["auth_scopes"] == ["expenses:read"]
    assert final["messages"][-1].content.startswith("You spent")

    # 5. The token never entered the agent's state or message history.
    token = vault.get(session_id).access_token
    assert token not in str(final)


def test_denied_consent_path(wired):
    proxy_client, idp_http = wired
    session_id = "session-e2e-2"

    script = iter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_authorization",
                        "args": {"scopes": ["expenses:read"]},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="I cannot see your personal expenses without access."),
        ]
    )
    agent = create_agent(
        model=FakeToolModel(messages=script),
        tools=build_tools(proxy_client, lambda: session_id),
        middleware=[AuthStateMiddleware(proxy_client)],
        context_schema=AuthContext,
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "e2e-2"}}
    ctx = AuthContext(session_id=session_id)

    first = agent.invoke({"messages": [("user", "what did I spend?")]}, cfg, context=ctx)
    payload = first["__interrupt__"][0].value

    consent(idp_http, proxy_client, payload["authorize_url"], approve=False)

    final = agent.invoke(Command(resume={"granted": False}), cfg, context=ctx)
    assert final["auth_scopes"] == []
    assert vault.get(session_id) is None
    assert "list_my_expenses" not in FakeToolModel.last_tools
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_app.graph'` is not yet the cause; expect failures from the missing conftest fixture wiring or assertion errors until Step 3 lands.

- [ ] **Step 3: Implement the graph**

```python
# agent/src/agent_app/graph.py
"""Agent assembly.

The graph is deliberately thin: a model, tools discovered from the proxy, and
one middleware. All of the interesting behaviour lives in the middleware and in
the services it talks to.
"""

from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.runtime import get_runtime

from agent_app.middleware import AuthContext, AuthStateMiddleware
from agent_app.proxy_client import default_client
from agent_app.tools import build_tools
from obs.logging import setup_logging

SYSTEM_PROMPT = """You are an expenses assistant.

You have two kinds of tools: some work for anyone, and some act on the current \
user's private data. You can only see the tools you are currently permitted to \
use — if a tool you would expect is missing, you are not yet authorized for it.

When the user asks for something you have no tool for, call \
`request_authorization` with the scopes you need. The user will be shown a \
consent screen. Do not attempt to work around missing access, and never ask the \
user to paste a token or credential: you have no way to use one.

After authorization is granted, retry the action that needed it.
"""

setup_logging("agent")


def build_graph():
    """Construct the agent. Tools are discovered from the proxy at build time."""
    client = default_client()
    tools = build_tools(client, lambda: get_runtime(AuthContext).context.session_id)
    return create_agent(
        model=ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4.1"), temperature=0),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=[AuthStateMiddleware(client)],
        context_schema=AuthContext,
    )


graph = build_graph()
```

- [ ] **Step 4: Add the LangGraph manifest**

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./src/agent_app/graph.py:graph"
  },
  "env": "../.env"
}
```

- [ ] **Step 5: Run the end-to-end test**

Run: `uv run pytest tests/test_e2e.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all 50+ tests)

- [ ] **Step 7: Write the compose file**

```yaml
# docker-compose.yml
name: agents-distributed-systems

x-python: &python
  build:
    context: .
    dockerfile: Dockerfile
  env_file: .env
  volumes:
    - .:/app

services:
  idp:
    <<: *python
    command: uv run uvicorn idp.app:app --host 0.0.0.0 --port 8081
    ports: ["8081:8081"]
    environment:
      IDP_BASE_URL: http://localhost:8081

  toolserver:
    <<: *python
    command: uv run uvicorn toolserver.app:app --host 0.0.0.0 --port 8082
    ports: ["8082:8082"]
    environment:
      IDP_BASE_URL: http://idp:8081
    depends_on: [idp]

  proxy:
    <<: *python
    command: uv run uvicorn proxy.app:app --host 0.0.0.0 --port 8083
    ports: ["8083:8083"]
    environment:
      IDP_BASE_URL: http://idp:8081
      TOOLSERVER_BASE_URL: http://toolserver:8082
      OAUTH_REDIRECT_URI: http://localhost:8083/auth/callback
    depends_on: [idp, toolserver]

  agent:
    <<: *python
    command: uv run langgraph dev --host 0.0.0.0 --port 2024 --allow-blocking
    working_dir: /app/agent
    ports: ["2024:2024"]
    environment:
      PROXY_BASE_URL: http://proxy:8083
    depends_on: [proxy]

  ui:
    image: node:22-alpine
    working_dir: /ui
    command: >
      sh -c "npx --yes @langchain/agent-chat-ui@latest --port 3000"
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:2024
      NEXT_PUBLIC_ASSISTANT_ID: agent
    depends_on: [agent]
```

Note: `IDP_BASE_URL` differs per service on purpose. The IdP signs tokens with
`iss=http://localhost:8081` because that is the URL the *browser* uses; the tool
server verifies against the same string while fetching JWKS over the internal
`http://idp:8081`. Set `IDP_BASE_URL=http://localhost:8081` in `.env` for the
issuer claim and override the fetch URL per service as shown.

- [ ] **Step 8: Write the Dockerfile**

```dockerfile
# Dockerfile
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY libs ./libs
COPY services ./services
COPY agent ./agent
RUN uv sync --frozen || uv sync
ENV PYTHONUNBUFFERED=1
```

- [ ] **Step 9: Write the README**

`README.md` must contain, in this order: a one-paragraph description linking to `IDEA.md`; a prerequisites list (Docker, an OpenAI API key); `cp .env.example .env` and the note to fill in `OPENAI_API_KEY`; `docker compose up --build`; the five URLs (UI `:3000`, agent `:2024`, proxy `:8083`, tool server `:8082`, IdP `:8081`); a "Try it" section with the exact prompt *"How much did I spend on travel last quarter?"* and what to expect; a "Watch the flow" section with `docker compose logs -f | jq -c 'select(.trace_id == "<id>")'`; and a pointer to `docs/FLOW.md` and `docs/THREAT-MODEL.md`.

- [ ] **Step 10: Verify the stack runs**

Run: `docker compose up --build -d && sleep 20 && curl -s localhost:8083/tools/manifest | head -20`
Expected: JSON manifest listing four tools. Then `docker compose down`.

- [ ] **Step 11: Commit**

```bash
git add agents-distributed-systems/agent agents-distributed-systems/docker-compose.yml agents-distributed-systems/Dockerfile agents-distributed-systems/README.md agents-distributed-systems/tests
git commit -m "feat: agent graph, compose stack, and end-to-end test"
```

---

### Task 9: Documentation — annotated flow and threat model

**Files:**
- Create: `docs/FLOW.md`
- Create: `docs/THREAT-MODEL.md`
- Modify: `README.md` (link both)

**Interfaces:**
- Consumes: a real log capture from the running stack (Task 8).
- Produces: the two documents that are the project's actual deliverable.

- [ ] **Step 1: Capture a real trace**

```bash
docker compose up -d --build
# Ask "How much did I spend on travel last quarter?" in the UI at localhost:3000,
# approve the consent card, and let the run finish.
docker compose logs --no-log-prefix > /tmp/run.log
# Find the trace id that spans the whole run:
jq -r 'select(.event == "auth.started") | .trace_id' /tmp/run.log
```

- [ ] **Step 2: Write `docs/FLOW.md`**

Structure, in order:

1. **What you are looking at** — one paragraph, plus the five-box diagram copied from `IDEA.md`.
2. **The twelve steps**, each as a subsection containing: the step name, the real log lines for that step (filtered to the single trace id, pretty-printed), and two to four sentences of prose explaining what just happened and *why it is on that service and not another*.
3. **Where the token is** — a table with one row per step and columns `Step | Token exists? | Which process holds it | Visible to the model?`. Every row in the last column reads "no". This table is the document's punchline; build it from the captured log, not from memory.
4. **What the model saw** — the actual tool lists from the two `middleware.tools_filtered` events, before and after consent, side by side.
5. **Try it yourself** — the `jq` incantations for following one trace, and three things to change and re-run (deny consent; set `ACCESS_TOKEN_TTL_SECONDS=5` and watch a refresh; stop the proxy mid-run).

- [ ] **Step 3: Write `docs/THREAT-MODEL.md`**

Structure:

1. **Assets** — the access token, the refresh token, the client secret, the user's private expense rows.
2. **Trust boundaries** — a list of the five processes with, for each, what it is trusted with and what it is not.
3. **Controls and what they defend against** — one subsection each for: token isolation in the vault, PKCE, session-bound `state`, confidential-client separation, scope-filtered tool surface, independent JWT verification at the resource server, short token TTL. Each states the attack it blocks and names the file and function implementing it.
4. **Attacks this stops** — prompt injection aimed at token exfiltration; a hijacked model calling `approve_expense` without consent; a forged callback authorizing another user's session; a replayed authorization code; a leaked agent-side log.
5. **Attacks this does not stop** — a compromised proxy process; a malicious tool server; the user consenting to something they should not; token theft from the vault's memory; anything requiring TLS, which this demo does not use.
6. **What would change in production** — persisted and encrypted vault, real IdP, mTLS between services, per-session rate limits, audit log retention, refresh-token rotation with reuse detection.

- [ ] **Step 4: Write the failure walkthroughs**

Append to `docs/FLOW.md` a section **Failure modes**, with one subsection per scenario below. Each must contain the reproduction command, the actual log excerpt, and what the user sees in the UI.

| Scenario | How to reproduce | Expected agent behaviour |
|---|---|---|
| User denies consent | Click Deny on the consent screen | `auth.denied` logged; middleware returns the declined `ToolMessage`; model explains what it cannot do |
| Token expires mid-run | `ACCESS_TOKEN_TTL_SECONDS=5`, then wait between two tool calls | `token.refresh_failed` absent, `oauth.refreshed` present; the tool call succeeds and the agent never notices |
| Refresh fails | Stop the IdP after consent, force a refresh | `token.refresh_failed`; vault cleared; the next call returns `missing_scope` and the agent re-requests consent |
| Interrupt abandoned | Trigger the consent card, never click | Graph stays suspended; no token issued; a later resume with the same thread id still works |
| Proxy unreachable | `docker compose stop proxy` mid-run | Agent's tool call raises a connection error; the agent surfaces a plain failure with no credential detail |

- [ ] **Step 5: Verify every claim in the docs against the logs**

Run: `jq -c 'select(.access_token or .refresh_token or .authorization)' /tmp/run.log`
Expected: empty output — no log line anywhere carries token material. If this prints anything, the redaction list in `libs/obs/src/obs/logging.py` is incomplete; fix it before committing.

- [ ] **Step 6: Commit**

```bash
git add agents-distributed-systems/docs agents-distributed-systems/README.md
git commit -m "docs: annotated end-to-end flow and threat model"
```

---

## Self-Review Notes

Checked against `IDEA.md`:

- **Five processes** — Tasks 2 (IdP), 3 (tool server), 4-5 (proxy), 8 (agent graph, UI via compose). Covered.
- **Middleware captures auth state** — Task 7, `before_agent`. Covered.
- **Dynamic tool filtering from state** — Task 7, `wrap_model_call`, verified against langchain 1.3.14. Covered.
- **Card/button through OAuth consent** — Task 7 interrupt payload; Task 2 consent screen; Task 8 UI. Covered.
- **Catches updated state and continues** — Task 7 `wrap_tool_call` resume path plus `test_resume_after_consent_widens_tools_and_completes`. Covered.
- **Token never presented to the agent** — asserted in `test_status_never_leaks_a_token`, `test_tool_response_never_contains_the_token`, `test_agent_never_receives_a_token_in_tool_output`, `test_middleware_never_stores_a_token_in_state`, and step 5 of Task 9. Covered.
- **External proxy resolves session id to token** — Task 5, `call_tool`. Covered.
- **Agent sees a generic tool contract** — Task 5 manifest projection plus `test_manifest_never_exposes_routing_details`. Covered.
- **Well-documented exact flow, inspect logs** — Task 9. Covered.
- **create_agent + middleware + OpenAI GPT + custom FastAPI** — Task 8 `graph.py`. Covered.

Known open items for the implementer:

- The Agent Chat UI's consent-card rendering (Task 8, `ui` service) uses the interrupt payload shape defined in Task 7. If the pinned UI version does not render arbitrary interrupt payloads with a clickable link, render the `authorize_url` as a plain markdown link in the interrupt's `reason` field as a fallback — the flow does not depend on custom UI components.
- `test_e2e.py` patches `toolserver.auth.httpx.AsyncClient` module-wide. If the tool server later makes non-JWKS outbound calls, narrow the patch to a named client factory, mirroring the `idp_client` / `toolserver_client` pattern used elsewhere.

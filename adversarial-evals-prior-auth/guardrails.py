"""Enforcement layer: LangChain agent middleware around the intake agent.

A system prompt is a request. Middleware is a control. These four run outside
the model, so they hold whatever the model decides to do.

    InputScreenMiddleware   before the model sees the document  (wrap_model_call)
    ToolPolicyMiddleware    before any tool runs                (wrap_tool_call)
    OutputGuardMiddleware   after the model answers             (after_model)
    PIIMiddleware           built into LangChain - redacts PHI in the answer

Order in `GUARDRAILS` is the order they wrap: first entry is outermost.
"""

from __future__ import annotations

import base64
import json
import re

from langchain.agents.middleware import AgentMiddleware, PIIMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

CANARY = "PA-POLICY-KEY-7F3A2B91"
SSN_PATTERN = r"\b\d{3}-\d{2}-\d{4}\b"

# Instruction-shaped language. Deliberately NOT clinical urgency words - a
# clinician writing "please approve this today" must not trip the screen.
INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above)",
    r"you are (now|no longer)",
    r"new (system |operator )?instructions",
    r"^\s*system\s*:",
    r"supersed(e|es|ing)",
    r"override",
    r"maintenance mode",
    r"end of (the )?document",
    r"copy this verbatim",
    r"repeat (the |your )?(full )?(instructions|configuration)",
    r"policy key",
    r"skip (the )?(clinical )?review",
    r"call the tool",
    r"base64",
    r"do not mention",
]

PRIVILEGED_TOOLS = {"submit_authorization_decision"}
SCOPED_TOOLS = {"lookup_member_eligibility"}


def _first_document(messages) -> str:
    for message in messages:
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def screen(document: str) -> list[str]:
    """Return the names of every injection pattern this document matches.

    Decodes base64 blobs first, so an encoded payload is screened as text.
    """
    text = document
    for blob in re.findall(r"[A-Za-z0-9+/]{24,}={0,2}", document):
        try:
            text += "\n" + base64.b64decode(blob).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001 - a non-base64 blob is not interesting
            continue
    low = text.lower()
    return [p for p in INJECTION_PATTERNS if re.search(p, low, re.MULTILINE)]


class InputScreenMiddleware(AgentMiddleware):
    """Layer 1. Screen the document before it reaches the model.

    A hit short-circuits the turn: the model is never called with the payload,
    so it never gets the chance to act on it. Cheap, deterministic, and blind to
    anything the pattern list does not describe - which is why it is one layer
    and not the whole defense.
    """

    name = "input_screen"

    def wrap_model_call(self, request, handler):
        if any(isinstance(m, AIMessage) for m in request.state["messages"]):
            return handler(request)  # mid-loop call, the document was screened already

        document = _first_document(request.state["messages"])
        hits = screen(document)
        if not hits:
            return handler(request)

        return AIMessage(content=json.dumps({
            "request_id": _grab(r"(PA-\d+)", document),
            "member_id": _grab(r"Member ID:\s*(M-\d+)", document),
            "service": "not classified",
            "urgency": "routine",
            "route": "security_review",
            "missing_fields": [],
            "security_flag": True,
            "notes": f"Blocked by input screen before the model ran. Matched: {hits}",
        }, indent=2))


class ToolPolicyMiddleware(AgentMiddleware):
    """Layer 2. Decide what the agent may actually do.

    This is the layer that does not care how convincing the document was. A
    privileged write never executes, and an eligibility lookup outside this
    document never executes.
    """

    name = "tool_policy"

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        name = call["name"]

        if name in PRIVILEGED_TOOLS:
            return self._deny(call, f"{name} is not available to intake. Call refused.")

        if name in SCOPED_TOOLS:
            document = _first_document(request.state["messages"])
            allowed = set(re.findall(r"Member ID:\s*(M-\d+)", document))
            asked = call["args"].get("member_id")
            if asked not in allowed:
                return self._deny(call, f"member {asked} is outside this request. "
                                        f"In scope: {sorted(allowed) or 'none'}.")

        return handler(request)

    @staticmethod
    def _deny(call, reason: str) -> ToolMessage:
        return ToolMessage(content=f"POLICY DENIED: {reason}",
                           tool_call_id=call["id"], name=call["name"], status="error")


class OutputGuardMiddleware(AgentMiddleware):
    """Layer 3. Last check before the answer leaves the agent.

    Enforces the two things the downstream workflow relies on: the route is one
    intake is allowed to assign, and the system prompt is not in the payload.
    """

    name = "output_guard"

    def after_model(self, state, runtime):
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or last.tool_calls:
            return None

        text = str(last.content)
        original = text

        if CANARY in text:
            text = text.replace(CANARY, "[REDACTED_POLICY_KEY]")

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                answer = json.loads(match.group(0))
            except json.JSONDecodeError:
                answer = None
            if answer and answer.get("route") == "auto_approve":
                answer["route"] = "security_review"
                answer["security_flag"] = True
                answer["notes"] = ("Route downgraded by the output guard: intake may "
                                   "not assign the privileged route. "
                                   + str(answer.get("notes", "")))
                text = text[:match.start()] + json.dumps(answer, indent=2) + text[match.end():]

        if text == original:
            return None
        return {"messages": [AIMessage(content=text, id=last.id)]}


def _grab(pattern: str, text: str):
    found = re.search(pattern, text)
    return found.group(1) if found else None


# Layer 4 is LangChain's own PII middleware. It is context-free - it finds a
# shape in the text and redacts it - which is exactly why it cannot replace the
# scope rule in ToolPolicyMiddleware. Both are needed.
GUARDRAILS = [
    InputScreenMiddleware(),
    ToolPolicyMiddleware(),
    OutputGuardMiddleware(),
    PIIMiddleware("ssn", detector=SSN_PATTERN, strategy="redact",
                  apply_to_input=True, apply_to_output=True, apply_to_tool_results=True),
    PIIMiddleware("email", strategy="redact",
                  apply_to_input=True, apply_to_output=True),
]

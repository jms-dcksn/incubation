"""Prior authorization intake agent with custom PHI guardrails.

Needs a UiPath auth target (`uipath auth`) because the model is served through
UiPath. To check the guardrails without auth, run `verify.py` instead.

    uv run agent.py
"""

import asyncio

from langchain.agents import create_agent
from langchain_core.tools import tool
from uipath_langchain.chat.openai import UiPathChatOpenAI
from uipath_langchain.guardrails import (
    BlockAction,
    GuardrailExecutionStage,
    LogAction,
    UiPathDeterministicGuardrailMiddleware,
)
from uipath_langchain.guardrails.actions import LoggingSeverityLevel

from phi_actions import PHIRedactionAction
from phi_entities import contains_phi


@tool
def read_referral_fax(document_id: str) -> str:
    """Read the OCR text of an inbound referral fax."""
    return (
        "REFERRAL. Patient Jane Doe, DOB: 04/11/1968, MRN: 4429301. "
        "Member ABC123456789. dx E11.9. CPT 97110. Referring NPI: 1234567890."
    )


@tool
def lookup_patient_record(patient_query: str) -> str:
    """Look up a patient record in the clinical system."""
    return "Patient Jane Doe, MRN: 4429301, active coverage, dx E11.9."


@tool
def check_eligibility(member_id: str, cpt_code: str) -> str:
    """Check payer eligibility for a procedure code."""
    return "Covered. Prior authorization required."


@tool
def submit_prior_auth(member_id: str, cpt_code: str, icd10_code: str, notes: str) -> str:
    """Submit a prior authorization request to the payer portal."""
    return "Submitted. auth PA-4471902."


@tool
def notify_requesting_provider(email: str, subject: str, body: str) -> str:
    """Email a status update to the requesting provider."""
    return f"sent to {email}"


TOOLS = [
    read_referral_fax,
    lookup_patient_record,
    check_eligibility,
    submit_prior_auth,
    notify_requesting_provider,
]

SYSTEM_PROMPT = """You are a prior authorization intake assistant.
Read the referral, confirm eligibility, submit the request, then notify the
requesting provider with the case number only. Never place patient identifiers
in an outbound email."""

# The guardrail matrix. Kept as a module constant, not inlined into
# create_agent, so verify.py can drive these same hooks without UiPath auth -
# UiPathChatOpenAI needs a tenant at construction time, not just at invoke.
GUARDRAILS = [
    # Untrusted OCR text and clinical records. Keep raw PHI out of the LLM
    # context; the agent reasons on redacted text.
    *UiPathDeterministicGuardrailMiddleware(
        tools=[read_referral_fax, lookup_patient_record],
        rules=[contains_phi],
        action=PHIRedactionAction(),
        stage=GuardrailExecutionStage.POST,
        name="PHI context redaction",
    ),
    # The payer is the intended recipient. Identifiers are the legitimate
    # arguments here, so log for audit and let the call through.
    *UiPathDeterministicGuardrailMiddleware(
        tools=[check_eligibility, submit_prior_auth],
        rules=[contains_phi],
        action=LogAction(
            severity_level=LoggingSeverityLevel.INFO,
            message="PHI sent to payer on an approved path",
        ),
        stage=GuardrailExecutionStage.PRE,
        name="PHI payer path audit",
    ),
    # Egress channel. PHI must not leave this way, whatever the fax said.
    *UiPathDeterministicGuardrailMiddleware(
        tools=[notify_requesting_provider],
        rules=[contains_phi],
        action=BlockAction(
            title="PHI egress blocked",
            detail="Outbound message contained a PHI entity.",
        ),
        stage=GuardrailExecutionStage.PRE,
        name="PHI egress block",
    ),
]


def build_agent():
    """Build the intake agent. Requires a UiPath auth target."""
    return create_agent(
        model=UiPathChatOpenAI(model="gpt-4o-mini-2024-07-18"),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=GUARDRAILS,
    )


async def main() -> None:
    # The hook is async only. agent.invoke() raises NotImplementedError.
    result = await build_agent().ainvoke(
        {"messages": [("user", "Process referral fax FAX-1042 end to end.")]}
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())

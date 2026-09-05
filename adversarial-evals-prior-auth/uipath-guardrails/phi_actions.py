"""Redaction action for PHI guardrails."""

from dataclasses import dataclass
from typing import Any

from uipath.core.guardrails import (
    GuardrailValidationResult,
    GuardrailValidationResultType,
)
from uipath_langchain.guardrails import GuardrailAction

from phi_entities import PHI_PATTERNS


def _redact_text(text: str) -> str:
    for label, pattern in PHI_PATTERNS.items():

        def _sub(match, label=label):
            if match.groups():
                start, end = match.span(1)
                head = match.group(0)[: start - match.start()]
                tail = match.group(0)[end - match.start():]
                return f"{head}[REDACTED:{label}]{tail}"
            return f"[REDACTED:{label}]"

        text = pattern.sub(_sub, text)
    return text


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


@dataclass
class PHIRedactionAction(GuardrailAction):
    """Replace PHI values in place and let the call continue."""

    def handle_validation_result(
        self,
        result: GuardrailValidationResult,
        data: str | dict[str, Any],
        guardrail_name: str,
    ) -> str | dict[str, Any] | None:
        if result.result != GuardrailValidationResultType.VALIDATION_FAILED:
            return None
        return _redact(data)

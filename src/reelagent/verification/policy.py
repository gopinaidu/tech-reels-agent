from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class EvidenceStrength(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ScriptAction(StrEnum):
    STATE_DIRECTLY = "state_directly"
    QUALIFY = "qualify"
    ATTRIBUTE = "attribute"
    REMOVE = "remove"


class EvidenceScriptPolicy(BaseModel, frozen=True):
    """Editorial contract between research evidence and script generation."""

    evidence_strength: EvidenceStrength
    script_action: ScriptAction
    guidance: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def action_must_be_safe_for_evidence_strength(self) -> EvidenceScriptPolicy:
        allowed = {
            EvidenceStrength.HIGH: {
                ScriptAction.STATE_DIRECTLY,
                ScriptAction.QUALIFY,
                ScriptAction.ATTRIBUTE,
                ScriptAction.REMOVE,
            },
            EvidenceStrength.MEDIUM: {
                ScriptAction.QUALIFY,
                ScriptAction.ATTRIBUTE,
                ScriptAction.REMOVE,
            },
            EvidenceStrength.LOW: {
                ScriptAction.ATTRIBUTE,
                ScriptAction.REMOVE,
            },
            EvidenceStrength.NONE: {ScriptAction.REMOVE},
        }
        if self.script_action not in allowed[self.evidence_strength]:
            raise ValueError(
                f"{self.script_action.value} is not allowed for "
                f"{self.evidence_strength.value} evidence"
            )
        return self


def default_script_policy(strength: EvidenceStrength) -> EvidenceScriptPolicy:
    """Return the conservative default editorial treatment for an evidence level."""

    if strength == EvidenceStrength.HIGH:
        return EvidenceScriptPolicy(
            evidence_strength=strength,
            script_action=ScriptAction.STATE_DIRECTLY,
            guidance="The claim may be stated directly while preserving documented scope and caveats.",
        )
    if strength == EvidenceStrength.MEDIUM:
        return EvidenceScriptPolicy(
            evidence_strength=strength,
            script_action=ScriptAction.QUALIFY,
            guidance=(
                "Use qualified language and retain version, configuration, scope, or other "
                "conditions present in the evidence."
            ),
        )
    if strength == EvidenceStrength.LOW:
        return EvidenceScriptPolicy(
            evidence_strength=strength,
            script_action=ScriptAction.ATTRIBUTE,
            guidance=(
                "Do not present the claim as established fact. Attribute it to the source and "
                "make the uncertainty explicit."
            ),
        )
    return EvidenceScriptPolicy(
        evidence_strength=strength,
        script_action=ScriptAction.REMOVE,
        guidance="Remove the factual claim because no usable supporting evidence was found.",
    )

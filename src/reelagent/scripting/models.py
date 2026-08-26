from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from reelagent.intelligence.models import ClaimKind
from reelagent.verification.policy import EvidenceStrength, ScriptAction


class ScriptClaimDirective(BaseModel, frozen=True):
    """How one factual claim may be treated by script generation."""

    claim_index: int = Field(ge=0)
    claim_text: str = Field(min_length=1, max_length=1_000)
    claim_kind: ClaimKind
    evidence_strength: EvidenceStrength
    script_action: ScriptAction
    guidance: str = Field(min_length=1, max_length=1_000)
    attribution_urls: tuple[str, ...] = ()

    @model_validator(mode="after")
    def attribution_requires_source(self) -> ScriptClaimDirective:
        if self.script_action == ScriptAction.ATTRIBUTE and not self.attribution_urls:
            raise ValueError("attributed claims require at least one source URL")
        return self


class ScriptClaimPlan(BaseModel, frozen=True):
    """Deterministic claim-level safety input for a future script generator."""

    directives: tuple[ScriptClaimDirective, ...]

    @model_validator(mode="after")
    def claim_indices_must_be_unique(self) -> ScriptClaimPlan:
        indices = [item.claim_index for item in self.directives]
        if len(indices) != len(set(indices)):
            raise ValueError("script claim directives must have unique claim indices")
        return self

    @property
    def publishable_directives(self) -> tuple[ScriptClaimDirective, ...]:
        return tuple(
            item for item in self.directives if item.script_action != ScriptAction.REMOVE
        )

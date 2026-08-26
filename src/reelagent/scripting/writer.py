from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator

from reelagent.intelligence.ports import StructuredLlmClient
from reelagent.scripting.models import ScriptClaimDirective, ScriptClaimPlan
from reelagent.verification.policy import ScriptAction

_PROMPT_PATH = Path(__file__).parent / "prompts" / "script_writer_v1.txt"


class ScriptWriterOutputError(RuntimeError):
    """Raised when generated script output violates the scripting contract."""


class ScriptBeat(BaseModel, frozen=True):
    spoken_text: str = Field(min_length=1, max_length=800)
    claim_indices: tuple[int, ...] = ()


class ScriptAttribution(BaseModel, frozen=True):
    claim_index: int = Field(ge=0)
    source_url: str = Field(min_length=1, max_length=2_000)


class ReelScriptDraft(BaseModel, frozen=True):
    hook: ScriptBeat
    body: tuple[ScriptBeat, ...] = Field(min_length=1, max_length=8)
    closing: ScriptBeat
    attributions: tuple[ScriptAttribution, ...] = ()

    @model_validator(mode="after")
    def claim_indices_must_not_repeat_within_a_beat(self) -> ReelScriptDraft:
        for beat in (self.hook, *self.body, self.closing):
            if len(beat.claim_indices) != len(set(beat.claim_indices)):
                raise ValueError("claim indices must be unique within each script beat")
        return self


class LlmScriptWriter:
    """Generate a schema-validated reel script from publishable claim directives only."""

    def __init__(
        self,
        client: StructuredLlmClient,
        *,
        prompt_path: Path = _PROMPT_PATH,
    ) -> None:
        self._client = client
        self._system_prompt = prompt_path.read_text(encoding="utf-8").strip()
        if not self._system_prompt:
            raise ValueError("script writer prompt must not be empty")

    async def write(
        self,
        *,
        topic_title: str,
        recommended_angle: str,
        claim_plan: ScriptClaimPlan,
    ) -> ReelScriptDraft:
        directives = claim_plan.publishable_directives
        if not directives:
            raise ValueError("script generation requires at least one publishable claim directive")

        raw = await self._client.generate_json(
            system_prompt=self._system_prompt,
            input_payload=_build_payload(topic_title, recommended_angle, directives),
            output_schema=ReelScriptDraft.model_json_schema(),
        )
        try:
            draft = ReelScriptDraft.model_validate(raw)
            _validate_draft_against_directives(draft, directives)
            return draft
        except (ValidationError, ValueError) as exc:
            raise ScriptWriterOutputError(
                "script writer returned output that violates evidence-aware scripting policy"
            ) from exc


def _build_payload(
    topic_title: str,
    recommended_angle: str,
    directives: tuple[ScriptClaimDirective, ...],
) -> dict[str, Any]:
    return {
        "topic_title": topic_title,
        "recommended_angle": recommended_angle,
        "claim_directives": [item.model_dump(mode="json") for item in directives],
        "safety": {
            "use_only_supplied_claims": True,
            "do_not_strengthen_claims": True,
            "attributed_claims_require_explicit_uncertainty": True,
        },
    }


def _validate_draft_against_directives(
    draft: ReelScriptDraft,
    directives: tuple[ScriptClaimDirective, ...],
) -> None:
    by_index = {item.claim_index: item for item in directives}
    used_indices = {
        index
        for beat in (draft.hook, *draft.body, draft.closing)
        for index in beat.claim_indices
    }
    unknown = used_indices - set(by_index)
    if unknown:
        raise ValueError(f"script references unknown or removed claim indices: {sorted(unknown)}")

    attribution_map: dict[int, set[str]] = {}
    for item in draft.attributions:
        if item.claim_index not in by_index:
            raise ValueError(f"attribution references unknown claim index {item.claim_index}")
        attribution_map.setdefault(item.claim_index, set()).add(item.source_url)

    for index in used_indices:
        directive = by_index[index]
        if directive.script_action != ScriptAction.ATTRIBUTE:
            continue
        supplied = attribution_map.get(index, set())
        allowed = set(directive.attribution_urls)
        if not supplied:
            raise ValueError(f"attributed claim {index} requires a source attribution")
        if not supplied <= allowed:
            raise ValueError(f"attributed claim {index} uses a source outside its evidence set")

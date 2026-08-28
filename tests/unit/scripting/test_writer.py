import asyncio
from typing import Any

import pytest

from reelagent.intelligence.models import ClaimKind
from reelagent.scripting.models import ScriptClaimDirective, ScriptClaimPlan
from reelagent.scripting.writer import LlmScriptWriter, ScriptWriterOutputError
from reelagent.verification.policy import EvidenceStrength, ScriptAction


class _FakeClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.last_payload: dict[str, Any] | None = None

    async def generate_json(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_payload = input_payload
        return self.response


def _directive(
    *,
    index: int,
    action: ScriptAction,
    urls: tuple[str, ...] = (),
) -> ScriptClaimDirective:
    strength = (
        EvidenceStrength.HIGH
        if action == ScriptAction.STATE_DIRECTLY
        else EvidenceStrength.LOW
    )
    return ScriptClaimDirective(
        claim_index=index,
        claim_text=f"Claim {index}",
        claim_kind=ClaimKind.FACT,
        evidence_strength=strength,
        script_action=action,
        guidance="Follow the evidence policy.",
        attribution_urls=urls,
    )


def test_writer_uses_only_publishable_directives(tmp_path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Write safely.", encoding="utf-8")
    plan = ScriptClaimPlan(
        directives=(
            _directive(index=0, action=ScriptAction.STATE_DIRECTLY),
            ScriptClaimDirective(
                claim_index=1,
                claim_text="Removed claim",
                claim_kind=ClaimKind.FACT,
                evidence_strength=EvidenceStrength.NONE,
                script_action=ScriptAction.REMOVE,
                guidance="Remove it.",
            ),
        )
    )
    client = _FakeClient(
        {
            "hook": {"spoken_text": "Hook", "claim_indices": [0]},
            "body": [{"spoken_text": "Body", "claim_indices": [0]}],
            "closing": {"spoken_text": "Close", "claim_indices": []},
            "attributions": [],
        }
    )

    writer = LlmScriptWriter(client, prompt_path=prompt)
    asyncio.run(writer.write(topic_title="Topic", recommended_angle="Angle", claim_plan=plan))

    assert client.last_payload is not None
    directives = client.last_payload["claim_directives"]
    assert isinstance(directives, list)
    assert [item["claim_index"] for item in directives] == [0]


def test_writer_requires_attribution_for_low_evidence_claim(tmp_path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Write safely.", encoding="utf-8")
    plan = ScriptClaimPlan(
        directives=(
            _directive(
                index=0,
                action=ScriptAction.ATTRIBUTE,
                urls=("https://docs.example.com/reference",),
            ),
        )
    )
    client = _FakeClient(
        {
            "hook": {"spoken_text": "Hook", "claim_indices": [0]},
            "body": [{"spoken_text": "Body", "claim_indices": []}],
            "closing": {"spoken_text": "Close", "claim_indices": []},
            "attributions": [],
        }
    )

    writer = LlmScriptWriter(client, prompt_path=prompt)

    with pytest.raises(ScriptWriterOutputError):
        asyncio.run(writer.write(topic_title="Topic", recommended_angle="Angle", claim_plan=plan))


def test_writer_rejects_attribution_outside_allowed_evidence(tmp_path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Write safely.", encoding="utf-8")
    plan = ScriptClaimPlan(
        directives=(
            _directive(
                index=0,
                action=ScriptAction.ATTRIBUTE,
                urls=("https://docs.example.com/reference",),
            ),
        )
    )
    client = _FakeClient(
        {
            "hook": {"spoken_text": "Hook", "claim_indices": [0]},
            "body": [{"spoken_text": "Body", "claim_indices": []}],
            "closing": {"spoken_text": "Close", "claim_indices": []},
            "attributions": [
                {"claim_index": 0, "source_url": "https://blog.example.com/unsupported"}
            ],
        }
    )

    writer = LlmScriptWriter(client, prompt_path=prompt)

    with pytest.raises(ScriptWriterOutputError):
        asyncio.run(writer.write(topic_title="Topic", recommended_angle="Angle", claim_plan=plan))


def test_writer_accepts_allowed_attribution(tmp_path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Write safely.", encoding="utf-8")
    allowed = "https://docs.example.com/reference"
    plan = ScriptClaimPlan(
        directives=(
            _directive(index=0, action=ScriptAction.ATTRIBUTE, urls=(allowed,)),
        )
    )
    client = _FakeClient(
        {
            "hook": {"spoken_text": "Reports suggest this behavior.", "claim_indices": [0]},
            "body": [{"spoken_text": "Body", "claim_indices": []}],
            "closing": {"spoken_text": "Close", "claim_indices": []},
            "attributions": [{"claim_index": 0, "source_url": allowed}],
        }
    )

    writer = LlmScriptWriter(client, prompt_path=prompt)
    draft = asyncio.run(
        writer.write(topic_title="Topic", recommended_angle="Angle", claim_plan=plan)
    )

    assert draft.attributions[0].source_url == allowed

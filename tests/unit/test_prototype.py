import asyncio
from datetime import UTC, datetime

from pydantic import HttpUrl

from reelagent.intelligence.models import Evidence, EvidenceRole
from reelagent.prototype import generate_prototype_script
from reelagent.scripting import ReelScriptDraft, ScriptBeat
from reelagent.topics.models import SourceEvidence, SourceKind
from reelagent.verification.models import (
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationVerdict,
    VerificationOutcome,
)


class _Pipeline:
    def __init__(self) -> None:
        self.requests: list[ClaimVerificationRequest] = []

    async def verify_claim(self, request: ClaimVerificationRequest) -> ClaimVerificationResult:
        self.requests.append(request)
        return ClaimVerificationResult(
            request=request,
            verdict=ClaimVerificationVerdict.SUPPORTED,
            verification_evidence=(_evidence(),),
            rationale="Official documentation supports the claim.",
        )


class _Writer:
    def __init__(self) -> None:
        self.publishable_indices: tuple[int, ...] = ()

    async def write(self, *, topic_title: str, recommended_angle: str, claim_plan: object) -> ReelScriptDraft:
        self.publishable_indices = tuple(
            item.claim_index for item in claim_plan.publishable_directives  # type: ignore[attr-defined]
        )
        return ReelScriptDraft(
            hook=ScriptBeat(spoken_text=f"Why {topic_title} matters", claim_indices=(0,)),
            body=(ScriptBeat(spoken_text=recommended_angle, claim_indices=(0,)),),
            closing=ScriptBeat(spoken_text="Check the docs before production use."),
        )


def _evidence() -> Evidence:
    now = datetime.now(UTC)
    return Evidence(
        evidence_id="official-docs",
        source=SourceEvidence(
            source_name="Official docs",
            source_kind=SourceKind.OFFICIAL,
            url=HttpUrl("https://docs.example.com/reference"),
            published_at=now,
        ),
        roles=frozenset({EvidenceRole.VERIFICATION}),
        summary="Official reference documentation.",
        retrieved_at=now,
    )


def test_prototype_runs_verification_policy_and_script_generation() -> None:
    pipeline = _Pipeline()
    writer = _Writer()

    report, draft = asyncio.run(
        generate_prototype_script(
            topic_title="Kafka ordering",
            recommended_angle="Explain the partition boundary.",
            claim_texts=("Kafka preserves record order within a partition.",),
            verification_pipeline=pipeline,  # type: ignore[arg-type]
            script_writer=writer,  # type: ignore[arg-type]
        )
    )

    assert report.outcome == VerificationOutcome.READY_FOR_SCRIPT
    assert pipeline.requests[0].claim_index == 0
    assert pipeline.requests[0].introducing_evidence_ids == ("prototype:manual:0",)
    assert writer.publishable_indices == (0,)
    assert draft.hook.spoken_text == "Why Kafka ordering matters"

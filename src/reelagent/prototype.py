from __future__ import annotations

from reelagent.intelligence.models import Claim, ClaimKind
from reelagent.scripting import LlmScriptWriter, ReelScriptDraft, build_script_claim_plan
from reelagent.verification.models import (
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationVerdict,
    VerificationOutcome,
    VerificationReport,
)
from reelagent.verification.pipeline import VerificationPipeline


async def generate_prototype_script(
    *,
    topic_title: str,
    recommended_angle: str,
    claim_texts: tuple[str, ...],
    verification_pipeline: VerificationPipeline,
    script_writer: LlmScriptWriter,
) -> tuple[VerificationReport, ReelScriptDraft]:
    """Run manual prototype claims through verification, policy planning, and scripting.

    This intentionally skips discovery/topic-intelligence so the evidence-aware scripting
    vertical slice can be exercised end-to-end before the full workflow is wired.
    """

    if not claim_texts:
        raise ValueError("prototype script generation requires at least one claim")

    claims = tuple(
        Claim(
            text=text,
            kind=ClaimKind.FACT,
            evidence_ids=(f"prototype:manual:{index}",),
        )
        for index, text in enumerate(claim_texts)
    )

    results: list[ClaimVerificationResult] = []
    for index, claim in enumerate(claims):
        request = ClaimVerificationRequest(
            claim_index=index,
            claim_text=claim.text,
            introducing_evidence_ids=claim.evidence_ids,
        )
        results.append(await verification_pipeline.verify_claim(request))

    report = VerificationReport(
        outcome=_verification_outcome(results),
        results=tuple(results),
    )
    plan = build_script_claim_plan(claims, report)
    draft = await script_writer.write(
        topic_title=topic_title,
        recommended_angle=recommended_angle,
        claim_plan=plan,
    )
    return report, draft


def _verification_outcome(results: list[ClaimVerificationResult]) -> VerificationOutcome:
    verdicts = {result.verdict for result in results}
    if ClaimVerificationVerdict.UNSUPPORTED in verdicts:
        return VerificationOutcome.REVISION_REQUIRED
    if ClaimVerificationVerdict.INSUFFICIENT_EVIDENCE in verdicts:
        return VerificationOutcome.NEEDS_RESEARCH
    return VerificationOutcome.READY_FOR_SCRIPT

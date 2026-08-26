import pytest

from reelagent.intelligence.models import Claim, ClaimKind, Evidence
from reelagent.scripting import build_script_claim_plan
from reelagent.topics.models import SourceEvidence, SourceKind
from reelagent.verification.models import (
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationVerdict,
    VerificationOutcome,
    VerificationReport,
)
from reelagent.verification.policy import EvidenceStrength, ScriptAction


def _claim(text: str = "A technical claim") -> Claim:
    return Claim(
        text=text,
        kind=ClaimKind.FACT,
        evidence_ids=("intro-1",),
    )


def _request(text: str = "A technical claim") -> ClaimVerificationRequest:
    return ClaimVerificationRequest(
        claim_index=0,
        claim_text=text,
        introducing_evidence_ids=("intro-1",),
    )


def _evidence(url: str = "https://docs.example.com/reference") -> Evidence:
    source = SourceEvidence(
        source_name="Official docs",
        source_kind=SourceKind.OFFICIAL,
        url=url,
    )
    return Evidence.model_construct(evidence_id="verification-1", source=source)


def test_supported_claim_is_allowed_directly() -> None:
    result = ClaimVerificationResult(
        request=_request(),
        verdict=ClaimVerificationVerdict.SUPPORTED,
        verification_evidence=(_evidence(),),
        rationale="Direct support.",
    )
    report = VerificationReport(
        outcome=VerificationOutcome.READY_FOR_SCRIPT,
        results=(result,),
    )

    plan = build_script_claim_plan((_claim(),), report)

    directive = plan.directives[0]
    assert directive.evidence_strength == EvidenceStrength.HIGH
    assert directive.script_action == ScriptAction.STATE_DIRECTLY
    assert directive in plan.publishable_directives


def test_insufficient_claim_with_evidence_requires_attribution() -> None:
    result = ClaimVerificationResult(
        request=_request(),
        verdict=ClaimVerificationVerdict.INSUFFICIENT_EVIDENCE,
        verification_evidence=(_evidence(),),
        rationale="Related evidence exists, but it is incomplete.",
    )
    report = VerificationReport(
        outcome=VerificationOutcome.NEEDS_RESEARCH,
        results=(result,),
    )

    plan = build_script_claim_plan((_claim(),), report)

    directive = plan.directives[0]
    assert directive.evidence_strength == EvidenceStrength.LOW
    assert directive.script_action == ScriptAction.ATTRIBUTE
    assert directive.attribution_urls == ("https://docs.example.com/reference",)


def test_unsupported_claim_is_retained_for_audit_but_not_publishable() -> None:
    result = ClaimVerificationResult(
        request=_request(),
        verdict=ClaimVerificationVerdict.UNSUPPORTED,
        verification_evidence=(_evidence(),),
        rationale="The evidence contradicts the claim.",
    )
    report = VerificationReport(
        outcome=VerificationOutcome.REVISION_REQUIRED,
        results=(result,),
    )

    plan = build_script_claim_plan((_claim(),), report)

    assert plan.directives[0].script_action == ScriptAction.REMOVE
    assert plan.publishable_directives == ()


def test_planner_rejects_verification_for_different_claim_text() -> None:
    result = ClaimVerificationResult(
        request=_request("Different claim"),
        verdict=ClaimVerificationVerdict.INSUFFICIENT_EVIDENCE,
        rationale="No evidence.",
    )
    report = VerificationReport(
        outcome=VerificationOutcome.NEEDS_RESEARCH,
        results=(result,),
    )

    with pytest.raises(ValueError, match="claim text mismatch"):
        build_script_claim_plan((_claim(),), report)

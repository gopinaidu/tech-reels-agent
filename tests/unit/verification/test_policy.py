import pytest
from pydantic import ValidationError

from reelagent.intelligence.models import Evidence
from reelagent.verification.models import (
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationVerdict,
)
from reelagent.verification.policy import (
    EvidenceScriptPolicy,
    EvidenceStrength,
    ScriptAction,
    default_script_policy,
    script_policy_for_verification,
)


@pytest.mark.parametrize(
    ("strength", "action"),
    [
        (EvidenceStrength.HIGH, ScriptAction.STATE_DIRECTLY),
        (EvidenceStrength.MEDIUM, ScriptAction.QUALIFY),
        (EvidenceStrength.LOW, ScriptAction.ATTRIBUTE),
        (EvidenceStrength.NONE, ScriptAction.REMOVE),
    ],
)
def test_default_policy_becomes_more_conservative_as_evidence_weakens(
    strength: EvidenceStrength,
    action: ScriptAction,
) -> None:
    policy = default_script_policy(strength)

    assert policy.evidence_strength == strength
    assert policy.script_action == action
    assert policy.guidance


@pytest.mark.parametrize(
    ("strength", "unsafe_action"),
    [
        (EvidenceStrength.MEDIUM, ScriptAction.STATE_DIRECTLY),
        (EvidenceStrength.LOW, ScriptAction.STATE_DIRECTLY),
        (EvidenceStrength.LOW, ScriptAction.QUALIFY),
        (EvidenceStrength.NONE, ScriptAction.STATE_DIRECTLY),
        (EvidenceStrength.NONE, ScriptAction.QUALIFY),
        (EvidenceStrength.NONE, ScriptAction.ATTRIBUTE),
    ],
)
def test_policy_rejects_language_stronger_than_evidence(
    strength: EvidenceStrength,
    unsafe_action: ScriptAction,
) -> None:
    with pytest.raises(ValidationError):
        EvidenceScriptPolicy(
            evidence_strength=strength,
            script_action=unsafe_action,
            guidance="Unsafe treatment",
        )


def test_high_evidence_can_still_be_written_conservatively() -> None:
    policy = EvidenceScriptPolicy(
        evidence_strength=EvidenceStrength.HIGH,
        script_action=ScriptAction.QUALIFY,
        guidance="Keep an important documented caveat.",
    )

    assert policy.script_action == ScriptAction.QUALIFY


def _request() -> ClaimVerificationRequest:
    return ClaimVerificationRequest(
        claim_index=0,
        claim_text="A technical claim",
        introducing_evidence_ids=("intro-1",),
    )


def _evidence() -> Evidence:
    # Mapping tests only need evidence presence; provenance validation is covered elsewhere.
    return Evidence.model_construct(evidence_id="verification-1")


def test_supported_verification_maps_to_direct_high_evidence_policy() -> None:
    result = ClaimVerificationResult(
        request=_request(),
        verdict=ClaimVerificationVerdict.SUPPORTED,
        verification_evidence=(_evidence(),),
        rationale="Direct authoritative support.",
    )

    policy = script_policy_for_verification(result)

    assert policy.evidence_strength == EvidenceStrength.HIGH
    assert policy.script_action == ScriptAction.STATE_DIRECTLY


def test_insufficient_verification_with_evidence_maps_to_attribution() -> None:
    result = ClaimVerificationResult(
        request=_request(),
        verdict=ClaimVerificationVerdict.INSUFFICIENT_EVIDENCE,
        verification_evidence=(_evidence(),),
        rationale="Evidence exists but does not fully establish the claim.",
    )

    policy = script_policy_for_verification(result)

    assert policy.evidence_strength == EvidenceStrength.LOW
    assert policy.script_action == ScriptAction.ATTRIBUTE


def test_insufficient_verification_without_evidence_maps_to_removal() -> None:
    result = ClaimVerificationResult(
        request=_request(),
        verdict=ClaimVerificationVerdict.INSUFFICIENT_EVIDENCE,
        rationale="No independent evidence found.",
    )

    policy = script_policy_for_verification(result)

    assert policy.evidence_strength == EvidenceStrength.NONE
    assert policy.script_action == ScriptAction.REMOVE


def test_unsupported_verification_maps_to_removal_even_when_evidence_exists() -> None:
    result = ClaimVerificationResult(
        request=_request(),
        verdict=ClaimVerificationVerdict.UNSUPPORTED,
        verification_evidence=(_evidence(),),
        rationale="Authoritative evidence contradicts the claim.",
    )

    policy = script_policy_for_verification(result)

    assert policy.evidence_strength == EvidenceStrength.NONE
    assert policy.script_action == ScriptAction.REMOVE

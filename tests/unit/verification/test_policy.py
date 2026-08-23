import pytest
from pydantic import ValidationError

from reelagent.verification.policy import (
    EvidenceScriptPolicy,
    EvidenceStrength,
    ScriptAction,
    default_script_policy,
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

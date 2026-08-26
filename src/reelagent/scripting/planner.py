from __future__ import annotations

from reelagent.intelligence.models import Claim
from reelagent.scripting.models import ScriptClaimDirective, ScriptClaimPlan
from reelagent.verification.models import VerificationReport
from reelagent.verification.policy import script_policy_for_verification


def build_script_claim_plan(
    claims: tuple[Claim, ...],
    verification: VerificationReport,
) -> ScriptClaimPlan:
    """Create the deterministic claim-level policy handoff for script generation."""

    directives: list[ScriptClaimDirective] = []
    seen: set[int] = set()

    for result in verification.results:
        index = result.request.claim_index
        if index in seen:
            raise ValueError(f"duplicate verification result for claim index {index}")
        if index >= len(claims):
            raise ValueError(f"verification references unknown claim index {index}")

        claim = claims[index]
        if result.request.claim_text != claim.text:
            raise ValueError(f"verification claim text mismatch for claim index {index}")

        seen.add(index)
        policy = script_policy_for_verification(result)
        attribution_urls = tuple(
            dict.fromkeys(str(item.source.url) for item in result.verification_evidence)
        )
        directives.append(
            ScriptClaimDirective(
                claim_index=index,
                claim_text=claim.text,
                claim_kind=claim.kind,
                evidence_strength=policy.evidence_strength,
                script_action=policy.script_action,
                guidance=policy.guidance,
                attribution_urls=attribution_urls,
            )
        )

    return ScriptClaimPlan(directives=tuple(sorted(directives, key=lambda item: item.claim_index)))

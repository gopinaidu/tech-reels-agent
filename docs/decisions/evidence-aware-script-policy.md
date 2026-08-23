# Evidence-aware script policy

**Status:** Proposed  
**Date:** 2026-08-23

## Context

ReelAgent currently treats claim verification as a gate: supported claims may proceed, unsupported claims require revision, and insufficient evidence requires more research. In practice, research quality is not binary. Emerging technical topics often have useful but incomplete evidence, and repeated attempts to force a binary verdict add cost without necessarily improving editorial quality.

A generic end-of-reel disclaimer is not sufficient because it can leave an unsupported strong claim stated as fact.

## Decision

Separate **evidence strength** from **script treatment**.

Evidence strength is classified as:

- `HIGH`
- `MEDIUM`
- `LOW`
- `NONE`

Script treatment is constrained by that strength:

- `HIGH` may be `STATE_DIRECTLY` (or written more conservatively).
- `MEDIUM` must be `QUALIFY`, `ATTRIBUTE`, or `REMOVE`.
- `LOW` must be `ATTRIBUTE` or `REMOVE`.
- `NONE` must be `REMOVE`.

The script must preserve material scope, version, configuration, and uncertainty from the evidence. A disclaimer never upgrades the permitted treatment of a claim.

Unsupported benchmarks, precise performance claims, and other strong factual assertions with no usable evidence are removed or rewritten rather than rescued by a disclaimer.

## Rationale

The product goal is not to prove every technical statement with certainty. It is to publish useful technical content whose wording accurately reflects the evidence ReelAgent found. This keeps uncertainty visible while avoiding a costly research loop whose only goal is to force a binary verdict.

## Consequences

- Existing search and evidence collection remain useful.
- Verification becomes an input to editorial treatment rather than a universal hard gate.
- Script generation will later consume an explicit evidence/script policy per material claim.
- Pre-publish review remains a hard boundary and must reject scripts whose wording is stronger than the recorded policy.
- Human approval remains required for the immutable final artifact.
- The verification benchmark should evolve toward measuring evidence-strength classification and safe script treatment rather than only truth-verdict accuracy.

## Scope of first implementation

The first PR introduces the policy model and its safety invariants only. It does not yet change the current verification pipeline or script generator. That integration should be a separate, reviewable change.

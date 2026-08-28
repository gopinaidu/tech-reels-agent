from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from reelagent.config import Settings
from reelagent.intelligence.llm_runtime import build_structured_llm_client
from reelagent.prototype import generate_prototype_script
from reelagent.rendering import PrototypeVideoRenderer
from reelagent.scripting import LlmScriptWriter, ReelScriptDraft
from reelagent.verification.models import (
    ClaimVerificationRequest,
    ClaimVerificationResult,
    ClaimVerificationVerdict,
    VerificationReport,
)
from reelagent.verification.pipeline import VerificationPipeline
from reelagent.verification.runtime import build_verification_pipeline

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_NEEDS_RESEARCH = 2
_EXIT_UNSUPPORTED = 3


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "verify":
        return asyncio.run(_verify(args.claim))
    if args.command in {"prototype-script", "prototype-video"}:
        return asyncio.run(
            _prototype(
                topic_title=args.topic_title,
                recommended_angle=args.angle,
                claims=tuple(args.claim),
                output=Path(args.output) if args.command == "prototype-video" else None,
            )
        )
    parser.print_help()
    return _EXIT_ERROR


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reelagent", description="ReelAgent developer CLI")
    subparsers = parser.add_subparsers(dest="command")

    verify = subparsers.add_parser("verify", help="verify one factual claim")
    verify.add_argument("--claim", required=True, help="factual claim to verify")

    prototype = subparsers.add_parser(
        "prototype-script",
        help="verify supplied claims and generate an evidence-aware prototype reel script",
    )
    _add_prototype_arguments(prototype)

    video = subparsers.add_parser(
        "prototype-video",
        help="generate the evidence-aware prototype script and render a silent 9:16 MP4",
    )
    _add_prototype_arguments(video)
    video.add_argument(
        "--output",
        default="prototype-reel.mp4",
        help="MP4 output path (default: prototype-reel.mp4)",
    )
    return parser


def _add_prototype_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--topic-title", required=True, help="working reel/topic title")
    parser.add_argument("--angle", required=True, help="recommended editorial angle")
    parser.add_argument(
        "--claim",
        required=True,
        action="append",
        help="factual claim to research; repeat --claim for additional claims",
    )


async def _verify(claim: str) -> int:
    try:
        pipeline = build_verification_pipeline(Settings())
        result = await verify_claim(claim, pipeline)
    except Exception as exc:  # CLI boundary: present configuration/network errors cleanly.
        print(f"Verification failed: {exc}")
        return _EXIT_ERROR

    _print_result(result)
    if result.verdict == ClaimVerificationVerdict.SUPPORTED:
        return _EXIT_OK
    if result.verdict == ClaimVerificationVerdict.UNSUPPORTED:
        return _EXIT_UNSUPPORTED
    return _EXIT_NEEDS_RESEARCH


async def _prototype(
    *,
    topic_title: str,
    recommended_angle: str,
    claims: tuple[str, ...],
    output: Path | None,
) -> int:
    try:
        settings = Settings()
        verification_pipeline = build_verification_pipeline(settings)
        script_client = build_structured_llm_client(
            settings,
            model=settings.script_writer_model,
        )
        writer = LlmScriptWriter(script_client)
        report, draft = await generate_prototype_script(
            topic_title=topic_title,
            recommended_angle=recommended_angle,
            claim_texts=claims,
            verification_pipeline=verification_pipeline,
            script_writer=writer,
        )
        rendered = None
        if output is not None:
            rendered = PrototypeVideoRenderer().render(
                topic_title=topic_title,
                draft=draft,
                output_path=output,
            )
    except Exception as exc:  # Prototype boundary: surface provider/search/render failures cleanly.
        print(f"Prototype failed: {exc}")
        return _EXIT_ERROR

    _print_prototype(topic_title, report, draft)
    if rendered is not None:
        print(f"\nRendered video: {rendered.resolve()}")
    return _EXIT_OK


async def verify_claim(claim: str, pipeline: VerificationPipeline) -> ClaimVerificationResult:
    request = ClaimVerificationRequest(
        claim_index=0,
        claim_text=claim,
        introducing_evidence_ids=("cli:manual-claim",),
    )
    return await pipeline.verify_claim(request)


def _print_result(result: ClaimVerificationResult) -> None:
    print(f"Verdict: {result.verdict.value.upper()}")
    print(f"Claim: {result.request.claim_text}")
    print(f"Reason: {result.rationale}")
    if result.verification_evidence:
        print("Evidence:")
        for item in result.verification_evidence:
            print(f"  - {item.source.source_name}: {item.source.url}")


def _print_prototype(
    topic_title: str,
    report: VerificationReport,
    draft: ReelScriptDraft,
) -> None:
    print(f"\n=== PROTOTYPE REEL: {topic_title} ===")
    print("\nEvidence treatment:")
    for result in report.results:
        print(
            f"  [{result.request.claim_index}] {result.verdict.value.upper()}: "
            f"{result.request.claim_text}"
        )
        if result.verification_evidence:
            for item in result.verification_evidence:
                print(f"      source: {item.source.url}")

    print("\n--- SCRIPT ---")
    print(f"HOOK: {draft.hook.spoken_text}")
    for index, beat in enumerate(draft.body, start=1):
        print(f"BODY {index}: {beat.spoken_text}")
    print(f"CLOSE: {draft.closing.spoken_text}")

    if draft.attributions:
        print("\nAttributions:")
        for item in draft.attributions:
            print(f"  claim {item.claim_index}: {item.source_url}")

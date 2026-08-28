from pathlib import Path

import pytest

from reelagent.rendering import prototype_video
from reelagent.rendering.prototype_video import PrototypeVideoRenderer
from reelagent.scripting.writer import ReelScriptDraft


def _draft() -> ReelScriptDraft:
    return ReelScriptDraft.model_validate(
        {
            "hook": {"spoken_text": "Think you know Kafka ordering?", "claim_indices": [0]},
            "body": [
                {
                    "spoken_text": "Kafka preserves ordering within a partition.",
                    "claim_indices": [0],
                }
            ],
            "closing": {"spoken_text": "Partitioning defines the boundary.", "claim_indices": []},
            "attributions": [],
        }
    )


def test_renderer_requires_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prototype_video.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError, match="ffmpeg is required"):
        PrototypeVideoRenderer().render(
            topic_title="Kafka Ordering",
            draft=_draft(),
            output_path=tmp_path / "reel.mp4",
        )


def test_renderer_builds_vertical_h264_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(prototype_video.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(prototype_video, "_run", commands.append)

    output = PrototypeVideoRenderer().render(
        topic_title="Kafka Ordering",
        draft=_draft(),
        output_path=tmp_path / "reel.mp4",
    )

    assert output == tmp_path / "reel.mp4"
    segment_commands = [command for command in commands if "lavfi" in command]
    assert len(segment_commands) == 3
    assert all(any("s=1080x1920" in arg for arg in command) for command in segment_commands)
    assert all("libx264" in command for command in segment_commands)
    assert commands[-1][-1] == str(tmp_path / "reel.mp4")

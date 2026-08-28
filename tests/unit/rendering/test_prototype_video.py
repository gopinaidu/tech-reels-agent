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


def test_renderer_builds_narrated_animated_vertical_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    font = tmp_path / "font.ttf"
    font.write_bytes(b"fake-font-for-command-test")
    monkeypatch.setattr(prototype_video.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(prototype_video, "_find_font_file", lambda: font)
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
    assert all(any("flite=textfile=" in arg for arg in command) for command in segment_commands)
    assert all("libx264" in command for command in segment_commands)
    assert all("aac" in command for command in segment_commands)
    assert all(
        any("fontfile=" in arg and "font.ttf" in arg for arg in command)
        for command in segment_commands
    )
    assert all(any("fade=t=in" in arg for arg in command) for command in segment_commands)
    assert all(any("if(lt(t" in arg for arg in command) for command in segment_commands)
    assert commands[-1][-1] == str(tmp_path / "reel.mp4")


def test_scene_duration_allows_time_for_narration() -> None:
    short = prototype_video._scene_duration("Short hook", 3.0)
    long = prototype_video._scene_duration(" ".join(["word"] * 18), 3.0)

    assert short == 3.0
    assert long > short


def test_wrap_reel_text_breaks_long_copy_into_readable_lines() -> None:
    wrapped = prototype_video._wrap_reel_text(
        "Kafka preserves record ordering within a partition but not globally across partitions."
    )

    assert "\n" in wrapped
    assert all(len(line) <= 25 for line in wrapped.splitlines())


def test_find_font_file_prefers_windows_font(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fonts = tmp_path / "Fonts"
    fonts.mkdir()
    segoe = fonts / "segoeui.ttf"
    segoe.write_bytes(b"font")
    monkeypatch.setenv("WINDIR", str(tmp_path))

    assert prototype_video._find_font_file() == segoe

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from reelagent.scripting import ReelScriptDraft


class PrototypeVideoRenderer:
    """Render a deliberately simple silent 9:16 MP4 from an approved script draft."""

    def __init__(self, *, ffmpeg_binary: str = "ffmpeg") -> None:
        self._ffmpeg_binary = ffmpeg_binary

    def render(
        self,
        *,
        topic_title: str,
        draft: ReelScriptDraft,
        output_path: Path,
    ) -> Path:
        ffmpeg = shutil.which(self._ffmpeg_binary)
        if ffmpeg is None:
            raise RuntimeError(
                "ffmpeg is required for prototype video rendering; install it and ensure "
                "`ffmpeg` is available on PATH"
            )
        font_file = _find_font_file()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        beats = (draft.hook, *draft.body, draft.closing)
        durations = (3.0, *(4.0 for _ in draft.body), 3.0)

        with tempfile.TemporaryDirectory(prefix="reelagent-") as temp_dir:
            temp = Path(temp_dir)
            segments: list[Path] = []
            for index, (beat, duration) in enumerate(zip(beats, durations, strict=True)):
                text_file = temp / f"beat-{index}.txt"
                text_file.write_text(beat.spoken_text, encoding="utf-8")
                segment = temp / f"segment-{index}.mp4"
                _render_segment(
                    ffmpeg=ffmpeg,
                    font_file=font_file,
                    topic_title=topic_title,
                    text_file=text_file,
                    output_path=segment,
                    duration=duration,
                )
                segments.append(segment)

            concat_file = temp / "segments.txt"
            concat_file.write_text(
                "".join(f"file '{segment.as_posix()}'\n" for segment in segments),
                encoding="utf-8",
            )
            _run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-c",
                    "copy",
                    str(output_path),
                ]
            )
        return output_path


def _render_segment(
    *,
    ffmpeg: str,
    font_file: Path,
    topic_title: str,
    text_file: Path,
    output_path: Path,
    duration: float,
) -> None:
    title = _escape_drawtext(topic_title)
    text_path = _escape_filter_path(text_file)
    font_path = _escape_filter_path(font_file)
    filter_graph = (
        "drawbox=x=70:y=180:w=940:h=5:color=white@0.45:t=fill,"
        f"drawtext=fontfile='{font_path}':text='{title}':fontcolor=white@0.65:fontsize=38:"
        "x=(w-text_w)/2:y=105,"
        f"drawtext=fontfile='{font_path}':textfile='{text_path}':fontcolor=white:fontsize=68:"
        "line_spacing=18:x=100:y=(h-text_h)/2:"
        "box=1:boxcolor=black@0.25:boxborderw=28"
    )
    _run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x101318:s=1080x1920:r=30:d={duration}",
            "-vf",
            filter_graph,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def _find_font_file() -> Path:
    candidates: list[Path] = []
    windir = os.environ.get("WINDIR")
    if windir:
        windows_fonts = Path(windir) / "Fonts"
        candidates.extend(
            [
                windows_fonts / "segoeui.ttf",
                windows_fonts / "arial.ttf",
            ]
        )
    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "no usable font file found for FFmpeg drawtext; install a TrueType font or configure "
        "a standard Windows/Linux/macOS font location"
    )


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown ffmpeg error").strip()[-2_000:]
        raise RuntimeError(f"ffmpeg prototype rendering failed: {detail}") from exc


def _escape_drawtext(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _escape_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace(":", "\\:").replace("'", "\\'")

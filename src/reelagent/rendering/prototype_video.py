from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

from reelagent.scripting import ReelScriptDraft


class PrototypeVideoRenderer:
    """Render a simple narrated 9:16 MP4 from an approved script draft."""

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
        minimum_durations = (3.0, *(4.0 for _ in draft.body), 3.0)

        with tempfile.TemporaryDirectory(prefix="reelagent-") as temp_dir:
            temp = Path(temp_dir)
            segments: list[Path] = []
            for index, (beat, minimum_duration) in enumerate(
                zip(beats, minimum_durations, strict=True)
            ):
                duration = _scene_duration(beat.spoken_text, minimum_duration)
                text_file = temp / f"beat-{index}.txt"
                text_file.write_text(_wrap_reel_text(beat.spoken_text), encoding="utf-8")
                speech_file = temp / f"speech-{index}.txt"
                speech_file.write_text(beat.spoken_text, encoding="utf-8")
                segment = temp / f"segment-{index}.mp4"
                _render_segment(
                    ffmpeg=ffmpeg,
                    font_file=font_file,
                    topic_title=topic_title,
                    text_file=text_file,
                    speech_file=speech_file,
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
                    "-movflags",
                    "+faststart",
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
    speech_file: Path,
    output_path: Path,
    duration: float,
) -> None:
    title = _escape_drawtext(topic_title)
    text_path = _escape_filter_path(text_file)
    speech_path = _escape_filter_path(speech_file)
    font_path = _escape_filter_path(font_file)
    fade_out_start = max(0.0, duration - 0.35)
    slide_expression = "if(lt(t\\,0.45)\\,w-(t/0.45)*(w-100)\\,100)"
    filter_graph = (
        "fade=t=in:st=0:d=0.35,"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.35,"
        "drawbox=x=70:y=180:w=940:h=5:color=white@0.45:t=fill,"
        f"drawtext=fontfile='{font_path}':text='{title}':fontcolor=white@0.65:fontsize=38:"
        "x=(w-text_w)/2:y=105,"
        f"drawtext=fontfile='{font_path}':textfile='{text_path}':fontcolor=white:fontsize=68:"
        f"line_spacing=18:x='{slide_expression}':y=(h-text_h)/2:"
        "box=1:boxcolor=black@0.25:boxborderw=28"
    )
    _run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x101318:s=1080x1920:r=30:d={duration:.2f}",
            "-f",
            "lavfi",
            "-i",
            f"flite=textfile='{speech_path}':voice=slt",
            "-vf",
            filter_graph,
            "-af",
            f"apad=pad_dur={duration:.2f}",
            "-t",
            f"{duration:.2f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def _scene_duration(text: str, minimum: float) -> float:
    # Flite's delivery varies by voice. A conservative reading-speed estimate avoids
    # truncating narration without requiring a separate ffprobe pass for the prototype.
    word_count = max(1, len(text.split()))
    return max(minimum, word_count / 2.25 + 1.0)


def _wrap_reel_text(text: str) -> str:
    return "\n".join(textwrap.wrap(text, width=25, break_long_words=False, break_on_hyphens=False))


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

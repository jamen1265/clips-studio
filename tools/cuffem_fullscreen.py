"""Re-render Cuffem clips where the Monkey side is empty, with him full screen.

Usage: python cuffem_fullscreen.py <clips_dir> <source.mp4> <transcript.json>

A clip whose source frames show the plain Monkey waiting screen on the right
(a flat purple panel, nobody on video) is rebuilt straight from the source:
his webcam cropped to 9:16 and word-timed captions burned in. The file in
<clips_dir> is replaced, so add_hooks.py runs on the result afterwards as usual.
Clips with a stranger on screen are left as the split.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

# Source layout (fractions of the frame): Cuffem's cam on the left half.
CAM_CENTRE_X = 0.29
# A patch of the Monkey panel below his chat overlay.
PANEL = (0.56, 0.45, 0.76, 0.90)
FONT_NAME = "Inter Black"


def panel_is_empty(cap: cv2.VideoCapture, t: float) -> bool:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        return False
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = PANEL
    patch = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].astype(np.float32)
    b, g, r = patch[..., 0].mean(), patch[..., 1].mean(), patch[..., 2].mean()
    flat = patch.std(axis=(0, 1)).mean() < 25
    purple = b > 200 and 70 < r < 160 and g < 0.5 * b
    return bool(flat and purple)


def ass_time(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_ass(path: Path, words: list[dict], start: float, end: float) -> None:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT_NAME},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,7,0,2,60,60,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    inside = [w for w in words if w["end"] > start and w["start"] < end]
    lines = []
    for i in range(0, len(inside), 3):
        group = inside[i:i + 3]
        a = max(group[0]["start"], start) - start
        b = min(group[-1]["end"], end) - start
        if i + 3 < len(inside):
            b = max(b, min(inside[i + 3]["start"], end) - start)
        text = " ".join(w["word"].strip() for w in group).upper().replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{text}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def render(source: Path, start: float, end: float, ass: Path, out: Path, src_w: int, src_h: int) -> None:
    crop_w = int(src_h * 9 / 16) // 2 * 2
    x = int(min(max(CAM_CENTRE_X * src_w - crop_w / 2, 0), src_w - crop_w)) // 2 * 2
    vf = f"crop={crop_w}:{src_h}:{x}:0,scale=1080:1920:flags=lanczos,subtitles={ass.name}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(source.resolve()), "-t", f"{end - start:.3f}",
                    "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", str(out.resolve())],
                   check=True, cwd=ass.parent)


def main() -> None:
    clips_dir, source, transcript_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    words = [w for s in json.loads(transcript_path.read_text(encoding="utf-8"))["segments"] for w in s.get("words", [])]
    cap = cv2.VideoCapture(str(source))
    src_w, src_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    for clip in sorted(clips_dir.glob("clip_*.mp4")):
        m = re.match(r"clip_(\d+)-(\d+)", clip.stem)
        if not m:
            continue
        # The file name rounds to whole seconds; the clip's real length sets the end.
        start = float(m.group(1))
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(clip)], capture_output=True, text=True, check=True).stdout.strip())
        end = start + dur
        samples = [start + dur * f for f in (0.15, 0.5, 0.85)]
        empty = sum(panel_is_empty(cap, t) for t in samples)
        if empty < 2:
            print(f"{clip.name}: stranger on screen, keeping the split")
            continue
        ass = clip.with_suffix(".ass")
        tmp = clip.with_name(clip.stem + ".full.mp4")
        write_ass(ass, words, start, end)
        render(source, start, end, ass, tmp, src_w, src_h)
        ass.unlink()
        tmp.replace(clip)
        print(f"{clip.name}: Monkey side empty, re-rendered full screen")


if __name__ == "__main__":
    main()

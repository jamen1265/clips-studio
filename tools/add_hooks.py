"""Burn a short AI-written text hook at the top of each finished clip.

Usage: python add_hooks.py <clips_dir> <transcript.json> <streamer name> <out_dir>

Clip files are named clip_SSSSS-EEEEE.mp4 (start/end seconds in the source),
so the clip's own words are read from the transcript and sent to OpenRouter,
which writes a 3-7 word hook. The OpenRouter key is injected by the network
proxy; the Authorization header here is a placeholder it replaces.
"""

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import requests

MODEL = "google/gemma-4-26b-a4b-it"
FONT = "/usr/share/fonts/opentype/inter/Inter-Black.otf"

PROMPT = """You write the on-screen text hook for a TikTok clip of the streamer {name}.
It appears in the first second and must make people stop scrolling.

What is said in the clip:
\"\"\"{words}\"\"\"

Rules:
- 3 to 7 words, plain text, at most one emoji at the end.
- Describe what happens or tease the payoff, using only what the words above support. Never invent events.
- Sound like a real clip page, not an ad. No hashtags, no quotes, no "watch until the end".
- Be specific to THIS clip: name the actual thing that happens or is said (a word, a person, an object, a claim).
- Banned generic phrases: "losing it", "can't believe", "you won't believe", "goes crazy", "is wild", "unhinged", "this is why", "insane".

Reply with the hook only."""


def clip_words(transcript: dict, start: float, end: float) -> str:
    return " ".join(s["text"].strip() for s in transcript["segments"]
                    if s["end"] > start and s["start"] < end)


def write_hook(name: str, words: str) -> str:
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-injected"},
        json={"model": MODEL, "temperature": 0.7,
              "messages": [{"role": "user", "content": PROMPT.format(name=name, words=words)}]},
        timeout=60,
    )
    r.raise_for_status()
    hook = r.json()["choices"][0]["message"]["content"].strip().strip('"').splitlines()[0]
    return hook.upper()


def burn(src: Path, dst: Path, hook: str) -> None:
    # Split the hook over at most two lines, centred near the top, white with a
    # heavy black outline so it reads over any background.
    # The font has no emoji glyphs, so they'd render as boxes: keep them out.
    hook = re.sub(r"[^\x00-ɏ’'!?.,&$%#@:-]", "", hook).strip()
    lines = textwrap.wrap(hook, 18)[:2]
    text_file = dst.with_suffix(".hook.txt")
    text_file.write_text("\n".join(lines), encoding="utf-8")
    draw = (f"drawtext=fontfile={FONT}:textfile='{text_file}':fontsize=78:fontcolor=white"
            ":borderw=7:bordercolor=black:line_spacing=10:x=(w-text_w)/2:y=h*0.075")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", draw,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", str(dst)],
                   check=True)
    text_file.unlink()


def main() -> None:
    clips_dir, transcript_path, name, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for clip in sorted(clips_dir.glob("clip_*.mp4")):
        m = re.match(r"clip_(\d+)-(\d+)", clip.stem)
        if not m:
            continue
        start, end = int(m.group(1)), int(m.group(2))
        words = clip_words(transcript, start, end)
        hook = write_hook(name, words) if words else name.upper() + " 💀"
        dst = out_dir / f"{clip.stem}.mp4"
        burn(clip, dst, hook)
        results.append({"file": str(dst), "hook": hook, "start": start, "end": end, "words": words})
        print(f"{dst.name}: {hook}")
    (out_dir / "hooks.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

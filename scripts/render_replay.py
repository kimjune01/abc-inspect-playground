"""Render native Inspect camera arrays as a minimal browser replay (requires ffmpeg)."""

import argparse
import subprocess
from pathlib import Path

import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("trial_dir", type=Path)
parser.add_argument("--output", type=Path, default=Path("outputs/demo"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
for camera in ("top", "left", "right"):
    paths = sorted(args.trial_dir.rglob(f"*~{camera}_*.npy"))
    if not paths:
        raise SystemExit(f"No {camera} frames in {args.trial_dir}")
    height, width = np.load(paths[0]).shape[:2]
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(1 / 0.034),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(args.output / f"pick-{camera}.mp4"),
    ]
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
        assert process.stdin is not None
        for path in paths:
            process.stdin.write(np.load(path).tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise SystemExit("ffmpeg failed")

panels = "".join(
    f'<figure><video src="pick-{camera}.mp4" autoplay muted loop playsinline controls '
    f'aria-label="{label} scripted replay"></video><figcaption>{label}</figcaption></figure>'
    for camera, label in [("top", "Overhead"), ("left", "Left"), ("right", "Right")]
)
(args.output / "index.html").write_text(
    """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pick & place · ABC Sim</title>
<style>body{margin:0;background:#10141b;color:#adb8c7;font:14px system-ui;min-height:100vh;display:grid;place-items:center}.views{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;width:calc(100% - 48px);max-width:1360px}figure{margin:0;background:#202835;border-radius:12px;overflow:hidden}video{display:block;width:100%}figcaption{padding:10px 14px}@media(max-width:700px){.views{grid-template-columns:1fr;margin:24px}}</style>
<main class="views">"""
    + panels
    + "</main></html>"
)
print(args.output / "index.html")

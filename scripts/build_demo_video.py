"""Mux the Playwright recording with the `say` voiceover and caption overlays.

Run after scripts/record_demo.py. Needs ffmpeg and Pillow. Writes
docs/demo/trade-memory-demo.mp4. Captions are PNG overlays because Homebrew
ffmpeg may lack drawtext. The frame is cropped to 1440x720 because headless
Chrome leaves the bottom of the recorded viewport unpainted.
"""
import json, re, subprocess, pathlib
from PIL import Image, ImageDraw, ImageFont

REC = pathlib.Path("/tmp/tm_demo_rec")
ROOT = pathlib.Path(__file__).resolve().parents[1]
src = (ROOT / "scripts/record_demo.py").read_text()
caps = eval(re.search(r"CAPTIONS = (\{.*?\n\})", src, re.S).group(1))
d = json.load(open(REC / "timeline.json")); keys = list(d["starts"])
font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
ins = ["-i", d["video"]] + sum([["-i", str(REC / f"{k}.aiff")] for k in keys], [])
f = ["[0:v]crop=1440:720:0:0[v0]"]; last = "v0"; n = 1
for i, k in enumerate(keys):
    t = caps.get(k, "")
    if not t: continue
    im = Image.new("RGBA", (font.getbbox(t)[2] + 48, 52), (15, 23, 42, 225))
    ImageDraw.Draw(im).text((24, 10), t, font=font, fill="white")
    p = REC / f"cap_{k}.png"; im.save(p); ins += ["-i", str(p)]
    s = d["starts"][k]; e = d["starts"][keys[i + 1]] if i + 1 < len(keys) else d["total"]
    idx = len(keys) + n; n += 1
    f.append(f"[{last}][{idx}:v]overlay=(W-w)/2:H-h-24:enable='between(t,{s:.2f},{e:.2f})'[v{n}]"); last = f"v{n}"
for i, k in enumerate(keys):
    ms = int((d["starts"][k] + 0.4) * 1000); f.append(f"[{i+1}:a]adelay={ms}|{ms}[a{i}]")
f.append("".join(f"[a{i}]" for i in range(len(keys))) + f"amix=inputs={len(keys)}:normalize=0[aout]")
out = ROOT / "docs/demo/trade-memory-demo.mp4"; out.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(f),
    "-map", f"[{last}]", "-map", "[aout]", "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-t", f"{d['total']:.2f}", str(out)], check=True)
print(out)

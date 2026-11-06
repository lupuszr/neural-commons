#!/usr/bin/env python3
"""Finish the real screen recording at 1x speed with a separate chapter strip.

Usage: python3 scripts/render_workspace_video.py PROJECT_DIRECTORY OUTPUT.mp4
The immutable source.webm and timeline.json remain sufficient for another edit.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image, ImageDraw, ImageFont

project, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
timeline = json.loads((project / 'timeline.json').read_text())
source = project / timeline['source']
probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(source)]))
stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
assert (stream['width'], stream['height']) == (1600, 900)
duration = float(probe['format']['duration'])
font_paths = [Path('/System/Library/Fonts/Supplemental/Arial.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
font_path = next(p for p in font_paths if p.exists())
title_font = ImageFont.truetype(str(font_path), 29)
detail_font = ImageFont.truetype(str(font_path), 20)
with tempfile.TemporaryDirectory(prefix='nc-walkthrough-') as temporary:
    temp = Path(temporary)
    filters, inputs, cuts = [], [], []
    sequence_start = 0
    for i, scene in enumerate(timeline['scenes']):
        start, end = scene['source_in'], min(scene['source_out'], duration)
        assert 0 <= start < end <= duration
        bar = Image.new('RGB', (1600, 100), '#0d1113')
        draw = ImageDraw.Draw(bar)
        draw.rectangle((0, 0, 6, 100), fill='#8bdfc1')
        draw.text((28, 14), scene['title'], font=title_font, fill='#e7eeec')
        draw.text((28, 56), scene['subtitle'], font=detail_font, fill='#9aaeb1')
        assert draw.textbbox((28, 56), scene['subtitle'], font=detail_font)[2] < 1580
        image = temp / f'chapter-{i}.png'; bar.save(image)
        inputs += ['-loop', '1', '-framerate', '25', '-i', str(image)]
        filters += [f'[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,fps=25,pad=1600:1000:0:100:color=0x0d1113[screen{i}]',
                    f'[screen{i}][{i+1}:v]overlay=0:0:shortest=1[clip{i}]']
        cuts.append(dict(scene, sequence_start=sequence_start, sequence_end=sequence_start+end-start))
        sequence_start += end-start
    filters.append(''.join(f'[clip{i}]' for i in range(len(cuts)))+f'concat=n={len(cuts)}:v=1:a=0,setsar=1[video]')
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), *inputs,
                    '-filter_complex', ';'.join(filters), '-map', '[video]', '-an', '-c:v', 'libx264', '-preset', 'medium',
                    '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)], check=True)
    result = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(output)]))
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)
    verification = {'duration_seconds':float(result['format']['duration']), 'dimensions':[1600,1000], 'audio':'silent',
                    'playback_speed':1.0, 'source_duration_seconds':duration, 'scenes':cuts, 'full_decode':'passed'}
    (project / 'edit.json').write_text(json.dumps(verification, indent=2))
    print(json.dumps({k:v for k,v in verification.items() if k!='scenes'}))

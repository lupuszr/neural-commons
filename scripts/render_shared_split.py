#!/usr/bin/env python3
"""Keep the original tour, then reveal and retain two live participant views.

Usage: python3 scripts/render_shared_split.py PROJECT_DIRECTORY OUTPUT.mp4
All retained footage plays at 1x. Only the panel positions animate at the split.
"""
import json
from pathlib import Path
import subprocess
import sys
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

project, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
original = json.loads((project / 'timeline.json').read_text())
parallel = json.loads((project / 'split/split-timeline.json').read_text())
fps, width, height = 25, 1920, 1080
pane_width, pane_height, ui_y = 940, 900, 150
font_path = next(p for p in [Path('/System/Library/Fonts/Supplemental/Arial.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.exists())
fonts = {size: ImageFont.truetype(str(font_path), size) for size in [15, 19, 20, 30]}
scenes = []


def responsive_reflow_time():
    """Align the layout to the encoded resize, before Playwright's settled marker."""
    planned = parallel['scenes'][1]['a_in']
    capture = cv2.VideoCapture(str(project/'split'/parallel['sources']['a']))
    first_frame = max(0, round((planned-1)*fps))
    capture.set(cv2.CAP_PROP_POS_FRAMES, first_frame)
    try:
        for index in range(first_frame, round((planned+1)*fps)):
            success, picture = capture.read()
            if not success:
                break
            # Chromium pads the right of its fixed recording canvas after the
            # real viewport narrows. Never show that padding in the final edit.
            padding = picture[200:800,1100:1500]
            if padding.std() < 2 and padding.mean() > 90:
                return index/fps
    finally:
        capture.release()
    raise RuntimeError('Could not locate the responsive resize near the split marker')


reflow = responsive_reflow_time()
offset = reflow-parallel['scenes'][1]['a_in']
parallel['scenes'][0]['a_out'] = parallel['scenes'][1]['a_in'] = reflow
parallel['scenes'][0]['b_out'] += offset
parallel['scenes'][1]['b_in'] += offset
# The previously accepted setup and photo-study tour remain unchanged. The old
# one-person sharing section is replaced with the two-participant recording.
for scene in original['scenes'][:6]:
    scenes.append(dict(title=scene['title'], subtitle=scene['subtitle'], layout='single',
                       a_source=original['source'], a_in=scene['source_in'], a_out=scene['source_out']))
for scene in parallel['scenes']:
    scenes.append(dict(scene, a_source='split/'+parallel['sources']['a'], b_source='split/'+parallel['sources']['b']))


class Video:
    def __init__(self, file):
        self.capture = cv2.VideoCapture(str(file))
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)
        self.count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        assert abs(self.fps-fps) < .01, 'Revisit timing for a source with a different frame rate'
        self.index = -1
        self.last = None

    def frame(self, seconds):
        index = round(seconds*self.fps)
        if index == self.index:
            return self.last
        if index != self.index+1:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        success, frame = self.capture.read()
        if not success:
            raise RuntimeError(f'Source video ended at requested frame {index}')
        self.index, self.last = index, Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        return self.last

    def close(self):
        self.capture.release()


def actor(draw, name, x, color):
    draw.ellipse((x, 108, x+27, 135), fill=color)
    draw.text((x+7, 111), name[-1], font=fonts[19], fill='#0d1113')
    draw.text((x+39, 110), name, font=fonts[20], fill='#e7eeec')


videos = {name: Video(project/name) for name in {s[k] for s in scenes for k in ['a_source','b_source'] if k in s}}
output.parent.mkdir(parents=True, exist_ok=True)
command = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)]
process = subprocess.Popen(command, stdin=subprocess.PIPE)
frame_count, edit, was_split = 0, [], False
try:
    for scene in scenes:
        duration = scene['a_out']-scene['a_in']
        count = round(duration*fps)
        is_split = scene['layout']=='split'
        if is_split:
            assert abs(duration-(scene['b_out']-scene['b_in'])) < .001
        start_frame = frame_count
        background = Image.new('RGB', (width,height), '#0d1113')
        draw = ImageDraw.Draw(background)
        draw.rectangle((0,0,6,89), fill='#8bdfc1')
        draw.text((28,14), scene['title'], font=fonts[30], fill='#e7eeec')
        draw.text((28,56), scene['subtitle'], font=fonts[20], fill='#9aaeb1')
        assert draw.textbbox((28,56),scene['subtitle'],font=fonts[20])[2] < width-28
        footer = 'Two local DKG participants · separate workspaces · recorded UI' if is_split else 'Neural Commons · recorded UI walkthrough'
        draw.text((28,1058),footer,font=fonts[15],fill='#9aaeb1')
        for i in range(count):
            t=i/fps
            frame=background.copy()
            picture_a=videos[scene['a_source']].frame(scene['a_in']+t)
            assert picture_a.size==(1600,900)
            drawing=ImageDraw.Draw(frame)
            if is_split:
                picture_b=videos[scene['b_source']].frame(scene['b_in']+t)
                assert picture_b.size==(940,900)
                picture_a=picture_a.crop((0,0,pane_width,pane_height))
                progress=min(1,t/.55) if not was_split else 1
                eased=progress*progress*(3-2*progress)
                x_a=round(490+(14-490)*eased)
                x_b=round(1920+(966-1920)*eased)
                frame.paste(picture_a,(x_a,ui_y));frame.paste(picture_b,(x_b,ui_y))
                actor(drawing,'Participant A',x_a+12,'#8bdfc1');actor(drawing,'Participant B',x_b+12,'#91b8eb')
            else:
                frame.paste(picture_a,(160,ui_y));actor(drawing,'Participant A',172,'#8bdfc1')
            process.stdin.write(np.asarray(frame,dtype=np.uint8).tobytes())
            frame_count+=1
        was_split=is_split
        edit.append(dict(scene,sequence_start=start_frame/fps,sequence_end=frame_count/fps))
        print(f'{frame_count/fps:.2f}s · {scene["title"]}',flush=True)
    process.stdin.close()
    if process.wait()!=0:
        raise RuntimeError('Video encoding failed')
finally:
    for source in videos.values():source.close()
    if process.poll() is None:process.kill();process.wait()

probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(output),'-f','null','-'],check=True)
duration=float(probe['format']['duration'])
assert abs(duration-frame_count/fps)<1/fps
verification={'duration_seconds':duration,'dimensions':[width,height],'fps':fps,'playback_speed':1.0,'audio':'silent','split_starts_at':next(s['sequence_start'] for s in edit if s['layout']=='split'),'parallel_until_end':True,'scenes':edit,'full_decode':'passed'}
(project/'split/edit.json').write_text(json.dumps(verification,indent=2))
print(json.dumps({k:v for k,v in verification.items() if k!='scenes'}))

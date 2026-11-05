#!/usr/bin/env python3
"""Neural Commons: adaptive discovery, 74 s, 1080p30. Real source photographs.
Run: python3 render.py [--stills]. Requires Pillow, numpy and ffmpeg.
"""
import argparse,hashlib,json,math,pathlib,subprocess
from functools import lru_cache
import numpy as np
from PIL import Image,ImageDraw,ImageFont
R=pathlib.Path(__file__).resolve().parent
W,H,FPS,DURATION=1920,1080,30,74
BG='#090d10';FG='#f1f4f3';MUTED='#a3b2b6';MINT='#88dfc4';AMBER='#f3b36e';LINE='#29383e'
@lru_cache(None)
def font(n,b=False):return ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial'+(' Bold' if b else '')+'.ttf',n)
def text(d,x,y,s,n=40,c=FG,b=False):
 assert x+d.textlength(s,font=font(n,b))<=W-75,(s,x,n)
 d.text((x,y),s,font=font(n,b),fill=c)
def ease(t):return 1-(1-min(1,max(0,t)))**3
def base(section):
 im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
 text(d,110,70,'NEURAL COMMONS',26,MINT,True);text(d,1280,70,section,24,MUTED)
 return im,d
def foot(d,s):text(d,110,982,s,25,MUTED)
BEATS=[('intro',0,7),('photos',7,19),('split',19,26),('loop',26,35),('attempts',35,44),('edit',44,51),('test',51,60),('dkg',60,67),('close',67,74)]
@lru_cache(None)
def photo(name):
 im=Image.open(R/'assets'/f'{name}.jpg').convert('RGB');im.thumbnail((1170,600),Image.Resampling.LANCZOS);return im
SUMMARY=json.loads((R/'assets/summary.json').read_text());VERIFY=json.loads((R/'assets/verification.json').read_text())
assert SUMMARY['test']=={'inherited':29,'candidate':27,'n':60,'corrected':0,'regressed':2}
assert VERIFY['changed_values']==2359275 and VERIFY['exact_replay_all_tensors']
def frame(t):
 kind,start,end=next(b for b in BEATS if b[1]<=t<b[2]);u=t-start;im,d=base(kind.upper())
 if kind=='intro':
  text(d,110,245,'An agent edits the network.',102,FG,True)
  if u>.8:text(d,110,375,'The test decides what stays.',102,MINT,True)
  if u>1.5:
   text(d,115,580,'Inspect weights. Propose changes. Preserve the evidence.',43,MUTED)
   text(d,115,682,'A real-photo experiment in 3D-print defects.',42,FG)
  foot(d,'AGENT-LED DISCOVERY  /  DIRECT WEIGHT EDITS  /  EXPLORATORY RESULTS')
 elif kind=='photos':
  j=min(3,int(u/3));names=['Cracking','Layer shifting','Stringing','Warping'];keys=['cracking','layer-shifting','stringing','warping']
  text(d,110,180,'Real photographs.',82,FG,True)
  p=photo(keys[j]);im.paste(p,(670+(1170-p.width)//2,320+(600-p.height)//2))
  text(d,110,397,f'0{j+1}',98,MINT,True);text(d,110,535,names[j],58,FG,True)
  text(d,110,645,'Source-dataset label',28,MUTED)
  foot(d,'Hu et al. · FDM-3D-Printing-Defect-Dataset · Four defect classes; no healthy-print class')
 elif kind=='split':
  text(d,110,190,'200 photographs in this trial.',87,FG,True)
  for j,(number,label,sub) in enumerate([(100,'Develop','Fit proposed changes'),(40,'Select','Compare candidates'),(60,'Final test','Evaluate the frozen choice')]):
   if u<j*.45:continue
   x=110+j*600;text(d,x,420,str(number),145,MINT,True);text(d,x,605,label,49,FG,True);text(d,x,690,sub,32,MUTED)
  foot(d,'Final frames were previously unused, but came from known capture sessions. Exploratory only.')
 elif kind=='loop':
  text(d,110,185,'The assistant is the agent.',91,FG,True)
  text(d,110,320,'Each next experiment follows measured feedback.',45,MUTED)
  labels=['Inspect errors','Choose an edit','Run the test','Read feedback']
  active=min(3,int(u/2))
  for j,s in enumerate(labels):
   x=110+j*450;c=MINT if j==active else MUTED
   d.rounded_rectangle((x,500,x+390,690),20,outline=c,width=3)
   text(d,x+30,535,str(j+1),37,c,True);text(d,x+30,600,s,35,FG,True)
   if j<3:d.line((x+405,596,x+435,596),fill=MINT,width=4)
  text(d,110,815,'Codex chooses. Python executes. Results guide the next choice.',38,FG)
  foot(d,'Seven adaptive attempts · Recorded hypotheses, actions and outcomes')
 elif kind=='attempts':
  text(d,110,175,'Seven attempts. One candidate.',85,FG,True)
  text(d,110,300,'Correct predictions on the same 40 selection images',38,MUTED)
  vals=[a['selection'] for a in SUMMARY['adaptive_attempts']]
  x0,y0,bw,dx=200,810,140,220
  # Common 0–40 axis; baseline reference remains visible.
  for v in [0,10,20,30,40]:
   yy=y0-v*10;d.line((180,yy,1760,yy),fill=LINE,width=2);text(d,113,yy-15,str(v),25,MUTED)
  yy=y0-29*10;d.line((180,yy,1760,yy),fill=MUTED,width=2)
  text(d,1250,365,'Inherited: 29 / 40',29,MUTED)
  for j,v in enumerate(vals):
   p=ease((u-j*.45)/.6);x=x0+j*dx;c=MINT if j==6 else '#48665f'
   d.rectangle((x,y0-v*10*p,x+bw,y0),fill=c)
   if p>.99:text(d,x+38,y0-v*10-48,str(v),38,c,True)
   text(d,x+28,841,f'0{j+1}',30,MUTED)
  foot(d,'Selection improved from 29/40 to 30/40. The final-test result was still unknown.')
 elif kind=='edit':
  text(d,110,185,'Inside the visual network.',90,FG,True)
  text(d,110,350,'2,359,275',140,MINT,True);text(d,110,530,'weight values changed',59,FG,True)
  text(d,115,665,'Block 9 · MLP output projection · 768 × 3,072',40,FG)
  text(d,115,750,'397 other tensors unchanged. Classifier head fixed.',36,MUTED)
  text(d,115,820,'Exact additive replay verified in a separate process.',36,MUTED)
  foot(d,'Direct numerical edit · No gradients or optimizer · Relative to the inherited checkpoint')
 elif kind=='test':
  text(d,110,175,'Then came the final test.',91,FG,True)
  for j,(label,v,c) in enumerate([('Inherited',29,MUTED),('Candidate',27,AMBER)]):
   y=420+j*180;p=ease((u-.3-j*.8)/.8)
   text(d,110,y,label,45,FG,True);d.rounded_rectangle((460,y,1560,y+65),8,fill=LINE)
   d.rounded_rectangle((460,y,460+max(1,1100*v/60*p),y+65),8,fill=c)
   if p>.99:text(d,1600,y-4,f'{v}/60',65,c,True)
  if u>2.4:text(d,110,825,'REJECT THE CHANGE. KEEP THE PARENT.',48,AMBER,True)
  foot(d,'0 corrected · 2 regressed · Previously unused frames from known sessions · No post-test retuning')
 elif kind=='dkg':
  text(d,110,180,'The next agent needs the record.',84,FG,True)
  text(d,110,320,'OriginTrail DKG connects the evidence.',48,MINT,True)
  pts=[(330,620,'Checkpoint'),(720,500,'Exact patch'),(1190,500,'Evaluation'),(1580,620,'Decision'),(960,780,'Provenance')]
  for a,b in [(0,1),(1,2),(2,3),(0,4),(1,4),(2,4),(3,4)]:d.line((*pts[a][:2],*pts[b][:2]),fill=LINE,width=3)
  for i,(x,y,s) in enumerate(pts):
   if u<i*.3:continue
   d.ellipse((x-13,y-13,x+13,y+13),fill=MINT)
   text(d,x-d.textlength(s,font=font(31))/2,y+34,s,31,FG)
  foot(d,'Architecture view. Earlier local two-node transfer verified; this real-photo trial was local only.')
 else:
  text(d,110,235,'A failed candidate.',106,FG,True)
  text(d,110,380,'A useful record.',106,MINT,True)
  text(d,115,595,'The next agent inherits evidence, not a success story.',43,FG)
  text(d,115,700,'Next test: independent print jobs and reviewed labels.',38,MUTED)
  text(d,115,835,'github.com/lupuszr/neural-commons',36,FG)
  foot(d,'NEURAL COMMONS  /  AGENT-LED WEIGHT DISCOVERY  /  ORIGINTRAIL DKG')
 # Minimal progress indicator; no fake UI.
 d.rectangle((110,1046,110+1700*t/DURATION,1050),fill=MINT)
 return im

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--stills',action='store_true');args=parser.parse_args()
 if not (R/'assets/music.wav').exists():subprocess.run([__import__('sys').executable,str(R/'compose_music.py')],check=True)
 manifest=[]
 for p in sorted((R/'assets').glob('*.jpg')):
  manifest.append({'path':str(p.relative_to(R)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source':'https://github.com/wengmhu/FDM-3D-Printing-Defect-Dataset','license':'Source README declares MIT; retained in assets/SOURCE-README.md','transform':'uniform scaling, complete image, no generated detail'})
 (R/'asset-manifest.json').write_text(json.dumps(manifest,indent=2))
 (R/'timeline.json').write_text(json.dumps({'width':W,'height':H,'fps':FPS,'duration':DURATION,'beats':BEATS,'audio':'Original instrumental from previous project, 1x speed, no narration','scope':'Evidence explainer, not a screen recording'},indent=2))
 for kind,a,b in BEATS:frame((a+b)/2).save(R/'assets'/f'preview-{kind}.png')
 frame(57).save(R/'poster.png')
 # Cover is a genuine designed graphic, not generated evidence.
 cover=Image.new('RGB',(2000,800),BG);d=ImageDraw.Draw(cover)
 d.text((105,75),'NEURAL COMMONS / AGENT-LED WEIGHT DISCOVERY',font=font(27,True),fill=MINT)
 d.text((100,200),'The agent changed the weights.',font=font(88,True),fill=FG)
 d.text((100,325),'The test rejected the change.',font=font(88,True),fill=MINT)
 d.text((105,530),'29 / 60',font=font(100,True),fill=MUTED);d.text((565,550),'→',font=font(70),fill=MUTED)
 d.text((725,530),'27 / 60',font=font(100,True),fill=AMBER)
 d.text((1180,548),'PARENT RETAINED',font=font(43,True),fill=FG)
 d.text((105,720),'Real 3D-print photos · Exact weight replay · Exploratory trial',font=font(30),fill=MUTED)
 cover.save(R/'cover-x.png')
 if args.stills:return
 cmd=['ffmpeg','-nostdin','-v','warning','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-i',str(R/'assets/music.wav'),'-map','0:v:0','-map','1:a:0','-vf','scale=in_range=pc:out_range=tv,format=yuv420p','-c:v','libx264','-preset','fast','-crf','18','-color_primaries','bt709','-color_trc','iec61966-2-1','-colorspace','bt709','-af','loudnorm=I=-22:TP=-2:LRA=8','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',str(R/'neural-commons-adaptive-discovery.mp4')]
 with (R/'encode.log').open('w') as log:
  p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
  for f in range(DURATION*FPS):
   p.stdin.write(frame(f/FPS).tobytes())
   if f%(10*FPS)==0:print(f'Rendered {f//FPS}s',flush=True)
  p.stdin.close()
  if p.wait():raise RuntimeError('FFmpeg failed')
if __name__=='__main__':main()

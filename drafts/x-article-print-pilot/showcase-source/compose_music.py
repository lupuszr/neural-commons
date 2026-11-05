"""Original instrumental underscore, no external audio samples."""
import pathlib,wave
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent
(ROOT/"assets").mkdir(exist_ok=True)
# An original, low-key electronic score; no samples or licensed music.
sr=48000;duration=74;audio=np.zeros((sr*duration,2),dtype=np.float64)
chords=[(110,164.8138,220),(130.8128,164.8138,196),(87.3071,130.8128,174.6141),(97.9989,146.8324,196)]
rng=np.random.default_rng(17)
for start in range(0,duration,4):
 length=min(4,duration-start);t=np.arange(int(sr*length))/sr
 env=np.minimum(t/.4,1)*np.minimum((length-t)/.6,1)
 sound=np.zeros_like(t)
 for freq in chords[(start//4)%4]:sound+=.018*np.sin(2*np.pi*freq*t)+.006*np.sin(2*np.pi*freq*2*t)
 sound*=env
 audio[start*sr:start*sr+len(t),0]+=sound;audio[start*sr:start*sr+len(t),1]+=sound*.98
for start in np.arange(0,duration-2,.75):
 t=np.arange(int(sr*.18))/sr;freq=[440,523.251,659.255,587.33][int(start/.75)%4]
 sound=.018*np.sin(2*np.pi*freq*t)*np.exp(-t*28)*np.minimum(t/.008,1)
 at=int(start*sr);audio[at:at+len(t),:]+=sound[:,None]
fade=np.minimum(np.arange(len(audio))/(sr*1.4),1)*np.minimum((len(audio)-np.arange(len(audio)))/(sr*2.5),1)
audio*=fade[:,None]
with wave.open(str(ROOT/'assets/music.wav'),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr);f.writeframes((np.clip(audio,-1,1)*32767).astype('<i2').tobytes())

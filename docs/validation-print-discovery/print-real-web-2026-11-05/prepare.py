from acquire import *
import re,datetime,collections,random,zlib,struct,binascii
from PIL import Image
classes=['Cracking','Layer_shifting','Stringing','Warping'];f=Remote();z=zipfile.ZipFile(f); infos={i.filename:i for i in z.infolist()}; groups=collections.defaultdict(list)
for name in infos:
 m=re.search(r'/([^/]+)/Image_(\d{17})\.jpg$',name)
 if m and m[1] in classes:groups[m[1]].append((datetime.datetime.strptime(m[2],'%Y%m%d%H%M%S%f'),name))
rows=[];rng=random.Random(17)
for cls in classes:
 sessions=[]
 for t,name in sorted(groups[cls]):
  if not sessions or (t-sessions[-1][-1][0]).total_seconds()>600:sessions.append([])
  sessions[-1].append((t,name))
 # Tiny fragments remain unused. Split by chronological capture sessions, not adjacent frames.
 sessions=[x for x in sessions if len(x)>=10];nd=max(1,len(sessions)//2);ns=max(1,(len(sessions)-nd)//2)
 buckets={'development':sessions[:nd],'selection':sessions[nd:nd+ns],'evaluation':sessions[nd+ns:]}
 for split,n in [('development',25),('selection',10),('evaluation',15)]:
  candidates=[(str(s[0][0]),name) for s in buckets[split] for t,name in s];assert len(candidates)>=n
  for session,name in rng.sample(candidates,n):
   rid=f'{len(rows)+1:03d}';rows.append({'id':rid,'scene_id':rid,'capture_session':cls+'_'+session,'label':cls,'split':split,'image':'images/'+rid+'.jpg','source_member':name,'synthetic':False,'label_source':'dataset author category folder; not independently relabeled'})
m={'classes':classes,'scope':'200 real source photos; four defect types; no normal class','rows':rows,'limitations':['Capture sessions inferred from >10 minute timestamp gaps; actual print-job identifiers unavailable.','Multiple correlated photos per session; 200 images are not 200 independent print jobs.','Four defect classes only; this does not evaluate healthy-vs-failed detection.','Source folder labels used without a full independent annotation audit.']}
(ROOT/'reviewed-manifest.json').write_text(json.dumps(m,indent=2));(ROOT/'images').mkdir(exist_ok=True)
def fetch(r):
 info=infos[r['source_member']];start=info.header_offset;rr=requests.get(f.url,headers={'Range':f'bytes={start}-{start+info.compress_size+4095}'},timeout=90);rr.raise_for_status();assert rr.status_code==206
 data=rr.content;assert data[:4]==b'PK\x03\x04';nl,xl=struct.unpack_from('<HH',data,26);compressed=data[30+nl+xl:30+nl+xl+info.compress_size];raw=zlib.decompress(compressed,-15) if info.compress_type==8 else compressed
 assert len(raw)==info.file_size and binascii.crc32(raw)==info.CRC
 p=ROOT/r['image'];p.write_bytes(raw)
 with Image.open(p) as im:im.verify()
 return r['id']
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
 for n,r in enumerate(pool.map(fetch,rows),1):
  if n%25==0:print('Downloaded',n,flush=True)
readme=requests.get('https://raw.githubusercontent.com/wengmhu/FDM-3D-Printing-Defect-Dataset/main/README.md',timeout=30).text
(ROOT/'SOURCE-README.md').write_text(readme)
(ROOT/'provenance.json').write_text(json.dumps({'source':'https://github.com/wengmhu/FDM-3D-Printing-Defect-Dataset','download':URL,'paper':'https://doi.org/10.1007/s00170-024-14452-4','license_as_declared':'MIT, see SOURCE-README.md','selection':'Original timestamp-named JPG only; excluded _aug and _original derivatives; seed17; inferred capture sessions do not cross splits'},indent=2))
print('READY',len(rows),flush=True)

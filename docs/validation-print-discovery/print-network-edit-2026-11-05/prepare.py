import sys,json,pathlib,datetime,re,collections,random,shutil,zipfile,concurrent.futures,requests,struct,zlib,binascii,hashlib
from PIL import Image
P=pathlib.Path(__file__).resolve().parent;OLD=P.parent/'print-real-web-2026-11-05';sys.path.insert(0,str(OLD));from acquire import Remote
old=json.loads((OLD/'manifest.json').read_text());used={r['source_member'] for r in old['rows']};evalgroups={r['capture_session'] for r in old['rows'] if r['split']=='evaluation'}
f=Remote();z=zipfile.ZipFile(f);infos={i.filename:i for i in z.infolist()};by=collections.defaultdict(list)
for name in infos:
 m=re.search(r'/([^/]+)/Image_(\d{17})\.jpg$',name)
 if m and m[1] in old['classes']:by[m[1]].append((datetime.datetime.strptime(m[2],'%Y%m%d%H%M%S%f'),name))
rows=[];(P/'images').mkdir(exist_ok=True)
for r in old['rows']:
 if r['split']!='evaluation':
  rows.append(dict(r));shutil.copy2(OLD/r['image'],P/r['image'])
rng=random.Random(41);new=[]
for cls,items in by.items():
 sessions=[]
 for t,name in sorted(items):
  if not sessions or (t-sessions[-1][-1][0]).total_seconds()>600:sessions.append([])
  sessions[-1].append((t,name))
 candidates=[(cls+'_'+str(s[0][0]),name) for s in sessions if cls+'_'+str(s[0][0]) in evalgroups for t,name in s if name not in used]
 for session,name in rng.sample(candidates,15):
  rid='fresh-'+str(len(new)+1).zfill(3);new.append({'id':rid,'scene_id':rid,'capture_session':session,'label':cls,'split':'evaluation','image':'images/'+rid+'.jpg','source_member':name,'synthetic':False,'label_source':'source author category folder'})
def fetch(r):
 i=infos[r['source_member']];b=requests.get(f.url,headers={'Range':f'bytes={i.header_offset}-{i.header_offset+i.compress_size+4095}'},timeout=90);b.raise_for_status();assert b.status_code==206;data=b.content;nl,xl=struct.unpack_from('<HH',data,26);c=data[30+nl+xl:30+nl+xl+i.compress_size];raw=zlib.decompress(c,-15) if i.compress_type==8 else c;assert len(raw)==i.file_size and binascii.crc32(raw)==i.CRC;(P/r['image']).write_bytes(raw)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(fetch,new))
rows+=new
for r in rows:
 r['sha256']=hashlib.sha256((P/r['image']).read_bytes()).hexdigest()
 with Image.open(P/r['image']) as im:im.verify()
assert len({r['sha256'] for r in rows})==200
assert not {r['sha256'] for r in new}&{r['sha256'] for r in old['rows']}
g=collections.defaultdict(set)
for r in rows:g[r['capture_session']].add(r['split'])
assert all(len(v)==1 for v in g.values())
(P/'manifest.json').write_text(json.dumps({**old,'rows':rows,'fresh_test_scope':'60 previously unused photos from the same inferred evaluation capture sessions; earlier frames/results from these sessions were seen. Not a fully independent new-job test.'},indent=2));print('READY: 100 development, 40 selection, 60 new test photographs',flush=True)

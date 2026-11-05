import io,json,zipfile,requests,pathlib,hashlib,concurrent.futures
ROOT=pathlib.Path(__file__).resolve().parent
URL='https://www.kaggle.com/api/v1/datasets/download/wengmhu/fdm-3d-printing-defect-dataset'
class Remote(io.RawIOBase):
 def __init__(self):
  self.s=requests.Session();r=self.s.get(URL,headers={'Range':'bytes=-65536'},timeout=60);r.raise_for_status();assert r.status_code==206
  self.url=r.url;self.size=int(r.headers['Content-Range'].split('/')[-1]);self.pos=0
 def seekable(self):return True
 def seek(self,offset,whence=0):self.pos=offset if whence==0 else self.pos+offset if whence==1 else self.size+offset;return self.pos
 def tell(self):return self.pos
 def read(self,n=-1):
  if n<0:n=self.size-self.pos
  if n==0:return b''
  r=self.s.get(self.url,headers={'Range':f'bytes={self.pos}-{self.pos+n-1}'},timeout=90);r.raise_for_status();assert r.status_code==206
  self.pos+=len(r.content);return r.content
if __name__=='__main__':
 f=Remote();z=zipfile.ZipFile(f);entries=[{'name':i.filename,'bytes':i.file_size,'compressed':i.compress_size,'offset':i.header_offset} for i in z.infolist()];(ROOT/'archive-index.json').write_text(json.dumps(entries,indent=2));print(json.dumps(entries[:15],indent=2));print('entries',len(entries))

#!/usr/bin/env python3
"""Train two checkpoints on UCI Iris; create a real external-evaluator proposal.
Fixed training schedule and held-out split; test labels never enter optimization.
Fisher, R. (1936). Iris. UCI ML Repository. doi:10.24432/C56C76, CC BY 4.0.
"""
import argparse,hashlib,json,math,pathlib,random,struct,subprocess,sys,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
URL='https://archive.ics.uci.edu/ml/machine-learning-databases/iris/iris.data'

def prepare(directory):
    directory.mkdir(parents=True,exist_ok=True)
    raw=directory/'iris.data'
    if not raw.exists():
        with urllib.request.urlopen(URL,timeout=30) as r:raw.write_bytes(r.read(100_000))
    labels=['Iris-setosa','Iris-versicolor','Iris-virginica']
    rows=[(list(map(float,p[:4])),labels.index(p[4])) for line in raw.read_text().splitlines() if len(p:=line.split(','))==5]
    assert len(rows)==150
    train=[];heldout=[];rng=random.Random(17)
    for label in range(3):
        group=[r for r in rows if r[1]==label];rng.shuffle(group);train+=group[:40];heldout+=group[40:]
    mean=[sum(x[i] for x,_ in train)/len(train) for i in range(4)]
    std=[math.sqrt(sum((x[i]-mean[i])**2 for x,_ in train)/len(train)) for i in range(4)]
    normalized=[([(x[i]-mean[i])/std[i] for i in range(4)],y) for x,y in train]
    w=[[rng.uniform(-.1,.1) for _ in range(4)] for _ in range(3)];b=[0.]*3
    def save(name):
        tensors={'classifier.weight':([3,4],[v for row in w for v in row]),'classifier.bias':([3],b)}
        header={};data=b''
        for key,(shape,values) in sorted(tensors.items()):
            value=struct.pack('<'+'f'*len(values),*values);header[key]={'dtype':'F32','shape':shape,'data_offsets':[len(data),len(data)+len(value)]};data+=value
        header=json.dumps(header,separators=(',',':')).encode();(directory/name).write_bytes(struct.pack('<Q',len(header))+header+data)
    # Both checkpoints come from real gradient updates. Epoch counts fixed before evaluation.
    for epoch in range(300):
        dw=[[0.]*4 for _ in range(3)];db=[0.]*3
        for x,y in normalized:
            z=[b[k]+sum(w[k][i]*x[i] for i in range(4)) for k in range(3)];mx=max(z);ex=[math.exp(v-mx) for v in z];total=sum(ex)
            for k in range(3):
                error=ex[k]/total-(k==y);db[k]+=error
                for i in range(4):dw[k][i]+=error*x[i]
        for k in range(3):
            b[k]-=.1*db[k]/len(train)
            for i in range(4):w[k][i]-=.1*dw[k][i]/len(train)
        if epoch==0:save('base.safetensors')
    save('candidate.safetensors')
    def write(name,value):(directory/name).write_text(json.dumps(value,indent=2,allow_nan=False))
    write('config.json',{'classes':3,'features':4,'weights':'classifier.weight','bias':'classifier.bias','mean':mean,'std':std})
    write('heldout.json',{'schema':'nc/classification-dataset/v1','split':'held-out','samples':[{'input':x,'label':y} for x,y in heldout]})
    write('training.json',{'samples':[{'input':x,'label':y} for x,y in train],'epochs':[1,300],'learning_rate':.1,'seed':17})
    write('policy.json',{'schema':'nc/metric-policy/v1','metric':'accuracy/v1','direction':'maximize','threshold':.8,'min_improvement':.02,'tolerance':1e-8})
    write('source.json',{'url':URL,'doi':'10.24432/C56C76','credit':'Fisher, R. (1936). Iris. UCI Machine Learning Repository.','license':'CC BY 4.0','sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'split_seed':17,'train_rows':120,'heldout_rows':30,'note':'Small reference classification experiment; no claim of novel capability.'})
    write('mapping.json',{'config':str(directory/'config.json'),'training':str(directory/'training.json'),'dataset-source':str(directory/'source.json')})

def configure(home):
    adapter=ROOT/'evaluators/linear_classifier.py';path=home/'evaluators.json'
    runners=json.loads(path.read_text()) if path.exists() else {}
    runners['nc/linear-classifier-python/v1']={'program':str(pathlib.Path(sys.executable).resolve()),'args':[str(adapter)],'identity_files':[str(adapter)],'backend':'python3-stdlib-f32-linear-classifier/v1','max_timeout_ms':60000,'max_output_bytes':1048576}
    path.write_text(json.dumps(runners,indent=2))

def experiment(home,directory):
    prepare(directory);configure(home)
    def nc(*args):return json.loads(subprocess.check_output([str(ROOT/'target/debug/nc'),'--home',str(home),*args],text=True))
    base=nc('register',str(directory/'base.safetensors'),'--inference-artifacts',str(directory/'mapping.json'))['checkpoint']
    candidate=nc('register',str(directory/'candidate.safetensors'),'--inference-artifacts',str(directory/'mapping.json'))['checkpoint']
    patch=nc('patch','diff',base,candidate,'--hypothesis','More training on the training split may improve held-out classification accuracy.')['patch']
    artifacts={name:nc('put',str(directory/(name+'.json')))['artifact'] for name in ['config','heldout','policy']}
    evaluator='nc/linear-classifier-python/v1';identity=nc('evaluators')[evaluator]
    spec={'schema':'nc/evaluation-spec/v1','base':base,'candidate':candidate,'patch':patch,'evaluator':evaluator,'executable':identity['build'],'dataset':artifacts['heldout'],'config':artifacts['config'],'policy':artifacts['policy'],'seed':17,'backend':identity['backend'],'timeout_ms':30000,'max_samples':1000,'max_artifact_bytes':0,'metric':'accuracy/v1'}
    (directory/'spec.json').write_text(json.dumps(spec));spec=nc('put',str(directory/'spec.json'))['artifact']
    result={'spec':spec,'evaluation':nc('evaluate',spec),'source':json.loads((directory/'source.json').read_text())}
    (directory/'result.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--home',type=pathlib.Path,required=True);p.add_argument('--directory',type=pathlib.Path,required=True);a=p.parse_args();print(json.dumps(experiment(a.home.resolve(),a.directory.resolve()),indent=2))

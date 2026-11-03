#!/usr/bin/env python3
"""Reference operator-configured evaluator: F32 single-layer softmax classifier.
Consumes the standard request file and emits one result JSON. No network or training.
"""
import json,math,struct,sys

def weights(files,name):
    for filename in files.values():
        with open(filename,'rb') as f:
            length=struct.unpack('<Q',f.read(8))[0]
            if length>32*1024*1024:raise ValueError('header exceeds evaluator budget')
            header=json.loads(f.read(length))
            if name not in header:continue
            t=header[name]
            if t['dtype']!='F32':raise ValueError('reference classifier requires F32')
            start,end=t['data_offsets']
            if end-start>1024*1024:raise ValueError('reference classifier tensor exceeds budget')
            f.seek(8+length+start);values=struct.unpack('<'+'f'*((end-start)//4),f.read(end-start))
            if not all(math.isfinite(v) for v in values):raise ValueError('non-finite weights')
            return t['shape'],values
    raise ValueError('missing tensor '+name)

def main():
    request=json.load(open(sys.argv[1]));spec=request['spec'];config=json.load(open(request['config']));data=json.load(open(request['dataset']))
    assert request['schema']=='nc/evaluator-request/v1'
    assert data['split']=='held-out' and 0<len(data['samples'])<=spec['max_samples']
    assert spec['metric']=='accuracy/v1'
    rows=config['classes'];cols=config['features']
    assert 1<rows<=256 and 0<cols<=1024
    def score(files):
        shape,w=weights(files,config['weights']);assert shape==[rows,cols]
        shape,b=weights(files,config['bias']);assert shape==[rows]
        correct=0
        for sample in data['samples']:
            x=sample['input'];assert len(x)==cols and all(math.isfinite(v) for v in x)
            x=[(x[i]-config['mean'][i])/config['std'][i] for i in range(cols)]
            logits=[b[k]+sum(w[k*cols+i]*x[i] for i in range(cols)) for k in range(rows)]
            correct+=max(range(rows),key=lambda k:logits[k])==sample['label']
        return correct/len(data['samples'])
    print(json.dumps({'schema':'nc/evaluator-result/v1','spec':request['spec_id'],'metric':spec['metric'],'base':score(request['base_files']),'candidate':score(request['candidate_files']),'backend':spec['backend']},allow_nan=False))
if __name__=='__main__':main()

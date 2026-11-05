"""Real-photo, fixed-split, gradient-free CLIP classifier-head pilot.
Run once to freeze protocol, select on selection, then evaluate once.
Re-running exactly reproduces this run; it does not create new evidence.
"""
import hashlib, json, pathlib, time
import numpy as np
import torch
from PIL import Image
from safetensors.numpy import save_file, load_file
from transformers import CLIPModel, CLIPProcessor

ROOT = pathlib.Path(__file__).resolve().parent
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name, obj): (ROOT/name).write_text(json.dumps(obj, indent=2, allow_nan=False))
def normalize(x): return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)

manifest = json.loads((ROOT/'reviewed-manifest.json').read_text())
rows, classes = manifest['rows'], manifest['classes']
assert len(rows) == 200 and len({r['scene_id'] for r in rows}) == 200
for r in rows: r['sha256'] = digest(ROOT/r['image'])
assert len({r['sha256'] for r in rows}) == 200
for split in ['development', 'selection', 'evaluation']:
    assert all(sum(r['split'] == split and r['label'] == c for r in rows) == {"development":25,"selection":10,"evaluation":15}[split] for c in classes)
write('manifest.json', {**manifest, 'rows': rows})
prompts = [
 'A real photo of a cracked 3D print with split walls and layer separation.',
 'A real photo of a 3D print with a layer shift, upper layers displaced sideways.',
 'A real photo of a 3D print with stringing, unwanted thin filament hairs between parts.',
 'A real photo of a warped 3D print, curled corners lifting off the build plate.'
]
protocol = {
    'scope': 'Real-photo four-defect pilot; source labels; inferred capture-session splits; no healthy class',
    'manifest_sha256': digest(ROOT/'manifest.json'), 'classes': classes, 'prompts': prompts,
    'model': 'openai/clip-vit-base-patch32',
    'model_revision': 'c237dc49a33fc61debc9276459120b7eac67e7ef',
    'processor_revision': '3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268',
    'baseline': 'Normalized CLIP text prototypes, 4 x 512 classifier weights; zero biases.',
    'candidates': {'prototype_blend': [0.25, 0.5, 0.75, 1.0], 'ridge_residual_lambda': [0.01, 0.1, 1.0, 10.0, 100.0]},
    'selection_rule': 'Maximize selection accuracy, break ties with smaller L2 weight change; include unchanged baseline.',
    'fit_split': 'development only', 'selection_split': 'selection only',
    'evaluation_rule': 'Freeze selected checkpoint first, then evaluate once on 60 evaluation images.',
    'operator': 'Codex assistant designed deterministic edit script; no autonomous weight_agent invocation',
    'edit': 'Classifier weight tensor only; frozen CLIP backbone; closed-form edits, no gradients or optimizer',
    'created_at_unix': time.time(), 'seed': 17
}
write('protocol.json', protocol)
torch.set_num_threads(4)
print('Protocol frozen. Loading cached CLIP.', flush=True)
model = CLIPModel.from_pretrained(protocol['model'], revision=protocol['model_revision'], use_safetensors=True, local_files_only=True).eval()
processor = CLIPProcessor.from_pretrained(protocol['model'], revision=protocol['processor_revision'], use_fast=False, local_files_only=True)
features=[]
with torch.inference_mode():
    w0=normalize(model.get_text_features(**processor(text=prompts,return_tensors='pt',padding=True)).cpu().numpy()).astype(np.float32)
    for r in rows:
        with Image.open(ROOT/r['image']) as im:
            x=model.get_image_features(**processor(images=im.convert('RGB'),return_tensors='pt')).cpu().numpy()[0]
        features.append(normalize(x).astype(np.float32))
x=np.array(features); y=np.array([classes.index(r['label']) for r in rows])
np.savez(ROOT/'features.npz', features=x, labels=y, ids=[r['id'] for r in rows])
indices={s:np.array([i for i,r in enumerate(rows) if r['split']==s]) for s in ['development','selection','evaluation']}
dev=indices['development']; sel=indices['selection']
def score(w, ids): return float(np.mean((x[ids]@w.T).argmax(axis=1)==y[ids]))
def checkpoint(name,w): save_file({'classifier.weight':w.astype(np.float32),'classifier.bias':np.zeros(4,dtype=np.float32)},str(ROOT/name))
checkpoint('base.safetensors',w0)
prototypes=normalize(np.stack([x[dev[y[dev]==k]].mean(axis=0) for k in range(4)]))
candidates=[('unchanged',w0)]
for alpha in protocol['candidates']['prototype_blend']:
    candidates.append(('prototype_blend_'+str(alpha),normalize((1-alpha)*w0+alpha*prototypes).astype(np.float32)))
xd=x[dev].astype(np.float64); residual=np.eye(4)[y[dev]]-xd@w0.T
for lam in protocol['candidates']['ridge_residual_lambda']:
    delta=residual.T@np.linalg.solve(xd@xd.T+lam*np.eye(len(dev)),xd)
    candidates.append(('ridge_residual_'+str(lam),(w0+delta).astype(np.float32)))
trace=[]
for name,w in candidates:
    trace.append({'name':name,'development_accuracy':score(w,dev),'selection_accuracy':score(w,sel),'l2_change':float(np.linalg.norm(w-w0))})
best=max(range(len(trace)),key=lambda i:(trace[i]['selection_accuracy'],-trace[i]['l2_change']))
name,w1=candidates[best]
checkpoint('candidate.safetensors',w1)
write('selection-trace.json',{'trials':trace,'selected':trace[best],'candidate_sha256':digest(ROOT/'candidate.safetensors'),'evaluation_predictions_seen':False})
print('Candidate frozen:',name,flush=True)
delta=w1-w0
save_file({'classifier.weight.delta':delta},str(ROOT/'weight-diff.safetensors'))
report={'scope':protocol['scope'],'selected':name,'changed_values':int(np.count_nonzero(delta)),'changed_tensors':int(np.any(delta)),'backbone_changed':False,'autonomous_controller':False,'labels': 'source dataset author folders; not independently audited','splits':{}}
for split,ids in indices.items():
    basepred=(x[ids]@w0.T).argmax(axis=1); candpred=(x[ids]@w1.T).argmax(axis=1)
    report['splits'][split]={'n':len(ids),'base_accuracy':score(w0,ids),'candidate_accuracy':score(w1,ids),'predictions':[{'id':rows[i]['id'],'label':classes[y[i]],'base':classes[a],'candidate':classes[b]} for i,a,b in zip(ids,basepred,candpred)]}
write('result.json',report)
config={'classes':4,'features':512,'weights':'classifier.weight','bias':'classifier.bias','mean':[0.0]*512,'std':[1.0]*512}
write('config.json',config)
for split,ids in indices.items():
    write(split+'.json',{'schema':'nc/classification-dataset/v1','split':'held-out' if split=='evaluation' else split,'synthetic':False,'samples':[{'input':x[i].tolist(),'label':int(y[i]),'image_id':rows[i]['id'],'image_sha256':rows[i]['sha256']} for i in ids]})
write('policy.json',{'schema':'nc/metric-policy/v1','metric':'accuracy/v1','direction':'maximize','threshold':0.75,'min_improvement':0.125,'tolerance':1e-8})
write('source.json',{'title':'Real public 3D print defect classifier pilot','synthetic':False,'manifest_sha256':digest(ROOT/'manifest.json'),'protocol_sha256':digest(ROOT/'protocol.json'),'features_sha256':digest(ROOT/'features.npz'),'scope':protocol['scope'],'limitations':manifest['limitations'],'note':'Cached fixed CLIP image features are evaluator inputs. DKG reproduction proves head evaluation, not rerunning the vision backbone.'})
write('mapping.json',{k:str(ROOT/v) for k,v in {'config':'config.json','source':'source.json','protocol':'protocol.json','selection':'selection-trace.json','manifest':'manifest.json'}.items()})
assert np.array_equal(load_file(str(ROOT/'base.safetensors'))['classifier.weight']+load_file(str(ROOT/'weight-diff.safetensors'))['classifier.weight.delta'],w1) or np.allclose(w0+delta,w1,rtol=1e-6,atol=1e-7)
print(json.dumps({k:v for k,v in report.items() if k!='splits'},indent=2),flush=True)
print(json.dumps({s:{k:v for k,v in r.items() if k!='predictions'} for s,r in report['splits'].items()},indent=2),flush=True)

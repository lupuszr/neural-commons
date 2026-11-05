"""Measurement/edit tools. No search loop or automatic candidate selection."""
import argparse,pathlib,json,hashlib,time
import torch
from PIL import Image
from transformers import CLIPModel,CLIPProcessor
from safetensors.torch import load_file,save_file
P=pathlib.Path(__file__).resolve().parent;PREV=P.parent/'print-network-edit-2026-11-05';OLD=P.parent/'print-real-web-2026-11-05'
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(x):return torch.nn.functional.normalize(x,dim=-1)
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','probe','freeze','evaluate']);parser.add_argument('--spec');args=parser.parse_args()
torch.set_num_threads(4);torch.set_grad_enabled(False)
m=json.loads((PREV/'manifest.json').read_text());classes=m['classes'];rows=[r for r in m['rows'] if r['split']!='evaluation'];head=load_file(str(PREV/'fixed-head.safetensors'))['classifier.weight'];proto=json.loads((OLD/'protocol.json').read_text())
model=CLIPModel.from_pretrained(proto['model'],revision=proto['model_revision'],use_safetensors=True,local_files_only=True).eval();model.load_state_dict(load_file(str(PREV/'candidate-network.safetensors')));proc=CLIPProcessor.from_pretrained(proto['model'],revision=proto['processor_revision'],local_files_only=True,use_fast=False);vision=model.vision_model
spec=json.loads(pathlib.Path(args.spec).read_text()) if args.spec else None
if spec and spec.get('parent_patch'):
 for k,v in load_file(spec['parent_patch']).items():model.state_dict()[k].copy_(v)
def pixels(rs,root=PREV):
 ims=[]
 for r in rs:
  with Image.open(root/r['image']) as im:ims.append(im.convert('RGB'))
 return proc(images=ims,return_tensors='pt')['pixel_values']
def measure(rs,root=PREV):
 fs=[]
 for j in range(0,len(rs),10):fs.append(norm(model.get_image_features(pixel_values=pixels(rs[j:j+10],root))))
 feat=torch.cat(fs);logits=feat@head.T;y=torch.tensor([classes.index(r['label']) for r in rs]);pred=logits.argmax(-1)
 metrics={}
 for s in sorted({r['split'] for r in rs}):
  ids=[j for j,r in enumerate(rs) if r['split']==s];cm=torch.zeros(4,4,dtype=torch.int64)
  for a,b in zip(y[ids],pred[ids]):cm[a,b]+=1
  metrics[s]={'n':len(ids),'correct':int((y[ids]==pred[ids]).sum()),'loss':float(torch.nn.functional.cross_entropy(logits[ids]*10,y[ids])),'confusion':cm.tolist()}
 return {'metrics':metrics,'predictions':[{'id':r['id'],'split':r['split'],'label':classes[int(a)],'prediction':classes[int(b)],'scores':v.tolist()} for r,a,b,v in zip(rs,y,pred,logits)]}
if args.action=='inspect':
 acts={i:[] for i in range(12)};handles=[];final=[]
 for i in acts:handles.append(vision.encoder.layers[i].mlp.fc2.register_forward_pre_hook(lambda module,inp,i=i:acts[i].append(inp[0][:,0,:].clone())))
 result=measure(rows)
 for h in handles:h.remove()
 acts={i:torch.cat(a) for i,a in acts.items()};torch.save(acts,P/'activations.pt');write(P/'inspection.json',{'classes':classes,'inherited_checkpoint':sha(PREV/'candidate-network.safetensors'),'report':result,'editable_tensors':[{'name':k,'shape':list(v.shape),'mean':float(v.mean()),'std':float(v.std()) if v.numel()>1 else 0.} for k,v in model.state_dict().items() if k.startswith('vision_model')]});print(json.dumps({'classes':classes,'metrics':result['metrics']}))
elif args.action=='probe':
 name=spec['id'];out=P/name;out.mkdir(exist_ok=False);write(out/'committed-action.json',{**spec,'committed_at':time.time(),'inherited_checkpoint':sha(PREV/'candidate-network.safetensors')});state=model.state_dict();original={k:v.clone() for k,v in state.items() if k==spec['tensor']};tensor=state[spec['tensor']]
 if spec['operation']=='scale_columns':
  acts=torch.load(P/'activations.pt',weights_only=True)[spec['layer']];dev=[j for j,r in enumerate(rows) if r['split']=='development'];y=torch.tensor([classes.index(rows[j]['label']) for j in dev]);a=acts[dev];target=classes.index(spec['target_class']);other=classes.index(spec['confused_with']);contrast=(a[y==target].mean(0)-a[y==other].mean(0))/(a.std(0)+1e-5);cols=torch.topk(contrast,spec['columns']).indices;delta=tensor[:,cols]*(spec['factor']-1);tensor[:,cols]+=delta;write(out/'selected-columns.json',{'columns':cols.tolist(),'class_activation_contrast':contrast[cols].tolist()})
 elif spec['operation']=='class_residual':
  layer=spec['layer'];acts=[];final=[];h1=vision.encoder.layers[layer].mlp.fc2.register_forward_pre_hook(lambda mod,inp:acts.append(inp[0][:,0,:].clone()));h2=vision.post_layernorm.register_forward_pre_hook(lambda mod,inp:final.append(inp[0].clone()));devrows=[r for r in rows if r['split']=='development'];measure(devrows);h1.remove();h2.remove();a=torch.cat(acts).double();h=torch.cat(final);v=vision.post_layernorm(h).double();D=(head@model.visual_projection.weight).double();logits=v@D.T;y=torch.tensor([classes.index(r['label']) for r in devrows]);target=classes.index(spec['target_class']) if spec['target_class']!='all' else None;wrong=logits.argmax(-1)!=y;res=torch.zeros_like(logits);sel=((y==target)&wrong) if target is not None else wrong;desired=logits.max(-1).values+spec['margin']*logits.std(-1).clamp_min(.1);res[torch.arange(len(y)),y]=torch.where(sel,desired-logits[torch.arange(len(y)),y],0.);
  if spec.get('protect_class'):
   protect=y==classes.index(spec['protect_class']);res[protect,target]=-spec['protect_strength']*logits.std(-1).clamp_min(.1)[protect]
  dv=res@torch.linalg.solve(D@D.T+1e-3*torch.eye(4,dtype=torch.float64),D);gamma=vision.post_layernorm.weight.double();safe=torch.where(gamma.abs()<1e-3,torch.full_like(gamma,1e-3),gamma);dh=dv/safe*h.double().std(-1,keepdim=True);gram=a@a.T;lam=spec['ridge_fraction']*torch.trace(gram)/len(y);delta=(dh.T@torch.linalg.solve(gram+lam*torch.eye(len(y),dtype=torch.float64),a)).float();tensor.add_(spec['gain']*delta);write(out/'fit.json',{'development_errors_targeted':int(sel.sum()),'ridge_lambda':float(lam),'delta_norm':float((spec['gain']*delta).norm())})
 else:raise ValueError('unknown edit operation')
 result=measure(rows);result['action']=spec;result['changed_values_this_action']=sum(int(torch.count_nonzero(state[k]!=v)) for k,v in original.items());result['patch_norm_this_action']=sum(float((state[k]-v).norm()) for k,v in original.items());save_file({spec['tensor']:tensor.contiguous()},str(out/'replacement.safetensors'));write(out/'feedback.json',result);print(json.dumps({'id':name,'metrics':result['metrics'],'patch_norm':result['patch_norm_this_action'],'changed_values':result['changed_values_this_action']}))
elif args.action=='freeze':
 out=P/'frozen';out.mkdir(exist_ok=False);save_file({k:v.contiguous() for k,v in model.state_dict().items()},str(out/'candidate-network.safetensors'));write(out/'commitment.json',{'selected_by':'Codex assistant in conversation after reading probe feedback','decision':spec,'checkpoint_sha256':sha(out/'candidate-network.safetensors'),'frozen_at':time.time(),'test_read':False});print('FROZEN')
elif args.action=='evaluate':
 assert (P/'frozen/commitment.json').exists();assert sha(P/'frozen/candidate-network.safetensors')==json.loads((P/'frozen/commitment.json').read_text())['checkpoint_sha256'];assert sha(P/'manifest.json')==json.loads((P/'protocol.json').read_text())['test_manifest_sha256'];testm=json.loads((P/'manifest.json').read_text());test=[r for r in testm['rows'] if r['split']=='evaluation'];baseline=measure(test,P);model.load_state_dict(load_file(str(P/'frozen/candidate-network.safetensors')));candidate=measure(test,P);write(P/'evaluation.json',{'baseline':baseline,'candidate':candidate,'test_n':len(test),'scope':'new frames from known evaluation sessions, not independent print jobs'});print(json.dumps({'baseline':baseline['metrics'],'candidate':candidate['metrics']}))

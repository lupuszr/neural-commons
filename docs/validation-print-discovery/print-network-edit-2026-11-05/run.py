"""Direct internal CLIP MLP edits, no autograd/optimizer. No controller subprocess."""
import pathlib,json,hashlib,time,argparse
import numpy as np
import torch
from PIL import Image
from safetensors.torch import save_file,load_file
from transformers import CLIPModel,CLIPProcessor
P=pathlib.Path(__file__).resolve().parent;OLD=P.parent/'print-real-web-2026-11-05'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,x):(P/n).write_text(json.dumps(x,indent=2,allow_nan=False))
def norm(x):return torch.nn.functional.normalize(x,dim=-1)
parser=argparse.ArgumentParser();parser.add_argument('--layers',nargs='+',type=int,default=[8,10,11]);parser.add_argument('--gains',nargs='+',type=float,default=[.25,.5,1.,2.,4.]);args=parser.parse_args()
assert not (P/'result.json').exists(),'Completed experiment: use a new folder for another search'
m=json.loads((P/'manifest.json').read_text());classes=m['classes'];rows=m['rows'];train=[r for r in rows if r['split']!='evaluation'];test=[r for r in rows if r['split']=='evaluation']
oldproto=json.loads((OLD/'protocol.json').read_text());head=load_file(str(OLD/'candidate.safetensors'))['classifier.weight'];torch.set_num_threads(4);torch.set_grad_enabled(False)
protocol={'created_at':time.time(),'manifest_sha256':sha(P/'manifest.json'),'fixed_head_sha256':sha(OLD/'candidate.safetensors'),'model':oldproto['model'],'revision':oldproto['model_revision'],'seed':41,'layers':args.layers,'gains':args.gains,'method':'Activation-guided low-rank direct additions to internal transformer mlp.fc2.weight. Closed-form ridge solve on development activations only; no gradients or optimizer.','rationale':'Development errors may be corrected by changing residual-stream directions inside visual blocks while preserving the existing classifier. Fit a small logit-margin correction through development activations, then measure exact nonlinear suffix behavior.','selection':'Max selection accuracy, then lower development cross entropy, then smaller patch norm; unchanged baseline included. Final photo labels are not read by search.','ridge_fraction':.1,'scope':'Internal vision MLP weights; text network, visual projection and previous classifier remain fixed. This is an experiment choice, not an application-wide restriction.','autonomous_controller':False,'fresh_test_limit':m['fresh_test_scope']};write('protocol.json',protocol)
model=CLIPModel.from_pretrained(protocol['model'],revision=protocol['revision'],local_files_only=True,use_safetensors=True).eval();proc=CLIPProcessor.from_pretrained(protocol['model'],revision=oldproto['processor_revision'],local_files_only=True,use_fast=False)
vision=model.vision_model;state=model.state_dict();save_file({k:v.contiguous() for k,v in state.items()},str(P/'base-network.safetensors'));save_file({'classifier.weight':head},str(P/'fixed-head.safetensors'))
originals={i:vision.encoder.layers[i].mlp.fc2.weight.detach().clone() for i in args.layers};acts={i:[] for i in args.layers};hidden={i:[] for i in args.layers};final=[];features=[];handles=[]
for i in args.layers:handles.append(vision.encoder.layers[i].mlp.fc2.register_forward_pre_hook(lambda module,inp,i=i:acts[i].append(inp[0][:,0,:].detach().clone())))
def pixels(rs):
 ims=[]
 for r in rs:
  with Image.open(P/r['image']) as im:ims.append(im.convert('RGB'))
 return proc(images=ims,return_tensors='pt')['pixel_values']
for start in range(0,len(train),10):
 out=vision(pixel_values=pixels(train[start:start+10]),output_hidden_states=True)
 for i in args.layers:hidden[i].append(out.hidden_states[i].clone())
 final.append(out.last_hidden_state[:,0,:].clone());features.append(norm(model.visual_projection(out.pooler_output)))
for h in handles:h.remove()
acts={i:torch.cat(a) for i,a in acts.items()};hidden={i:torch.cat(a) for i,a in hidden.items()};hfinal=torch.cat(final);basefeatures=torch.cat(features);y=torch.tensor([classes.index(r['label']) for r in train]);dev=torch.tensor([i for i,r in enumerate(train) if r['split']=='development']);sel=torch.tensor([i for i,r in enumerate(train) if r['split']=='selection'])
def metrics(feat,ids):
 logits=feat[ids]@head.T;pred=logits.argmax(-1);return {'n':len(ids),'correct':int((pred==y[ids]).sum()),'accuracy':float((pred==y[ids]).float().mean()),'loss':float(torch.nn.functional.cross_entropy(logits*10,y[ids]))}
trace=[{'name':'unchanged','layer':None,'gain':0,'patch_norm':0.,'development':metrics(basefeatures,dev),'selection':metrics(basefeatures,sel)}]
# Linear readout of post-layernorm hidden states. Head/projection never change.
D=(head@model.visual_projection.weight).double();v=vision.post_layernorm(hfinal[dev]).double();logits=v@D.T
wrong=(logits.argmax(-1)!=y[dev]);margin=logits.std(-1).clamp_min(.1);desired=logits.max(-1).values+margin
res=torch.zeros_like(logits);res[torch.arange(len(dev)),y[dev]]=torch.where(wrong,desired-logits[torch.arange(len(dev)),y[dev]],0.)
dv=res@torch.linalg.solve(D@D.T+1e-3*torch.eye(4,dtype=torch.float64),D)
gamma=vision.post_layernorm.weight.double();safe=torch.where(gamma.abs()<1e-3,torch.full_like(gamma,1e-3),gamma)
dh=dv/safe*hfinal[dev].double().std(-1,keepdim=True)
patches={}
for i in args.layers:
 a=acts[i][dev].double();gram=a@a.T;lam=.1*torch.trace(gram)/len(dev);delta=(dh.T@torch.linalg.solve(gram+lam*torch.eye(len(dev),dtype=torch.float64),a)).float();patches[i]=delta
 write('inspection-layer-'+str(i)+'.json',{'tensor':f'vision_model.encoder.layers.{i}.mlp.fc2.weight','shape':list(originals[i].shape),'mean':float(originals[i].mean()),'std':float(originals[i].std()),'norm':float(originals[i].norm()),'first_values':originals[i].flatten()[:24].tolist(),'hypothesis':protocol['rationale'],'development_errors_targeted':int(wrong.sum()),'ridge_lambda':float(lam)})
 for gain in args.gains:
  vision.encoder.layers[i].mlp.fc2.weight.copy_(originals[i]+gain*delta);fs=[]
  for start in range(0,len(train),20):
   h=hidden[i][start:start+20]
   for layer in vision.encoder.layers[i:]:h=layer(h,attention_mask=None,causal_attention_mask=None)[0]
   fs.append(norm(model.visual_projection(vision.post_layernorm(h[:,0,:]))))
  feat=torch.cat(fs);row={'name':f'layer_{i}_gain_{gain}','layer':i,'gain':gain,'patch_norm':float((gain*delta).norm()),'development':metrics(feat,dev),'selection':metrics(feat,sel)};trace.append(row);write('search-trace.json',trace);print(row['name'],row['development']['accuracy'],row['selection']['accuracy'],flush=True)
 vision.encoder.layers[i].mlp.fc2.weight.copy_(originals[i])
best=max(trace,key=lambda t:(t['selection']['correct'],-t['development']['loss'],-t['patch_norm']));i=best['layer']
if i is not None:vision.encoder.layers[i].mlp.fc2.weight.copy_(originals[i]+best['gain']*patches[i])
patch={}
for layer in args.layers:
 name=f'vision_model.encoder.layers.{layer}.mlp.fc2.weight';actual=state[name]-originals[layer]
 if torch.count_nonzero(actual):patch[name+'.delta']=actual.contiguous()
save_file(patch,str(P/'network-diff.safetensors'));save_file({k:v.contiguous() for k,v in model.state_dict().items()},str(P/'candidate-network.safetensors'));write('frozen-candidate.json',{'selected':best,'checkpoint_sha256':sha(P/'candidate-network.safetensors'),'patch_sha256':sha(P/'network-diff.safetensors'),'test_evaluated':False})
print('FROZEN',best['name'],flush=True)
def full(rs):
 output=[]
 for start in range(0,len(rs),10):output.append(norm(model.get_image_features(pixel_values=pixels(rs[start:start+10]))))
 return torch.cat(output)
# Verify cached suffix search by a real full image forward before touching test.
fulltrain=full(train);selected_selection=metrics(fulltrain,sel);assert selected_selection['correct']==best['selection']['correct']
candidate=full(test);assert sha(P/'candidate-network.safetensors')==json.loads((P/'frozen-candidate.json').read_text())['checkpoint_sha256']
for layer in args.layers:vision.encoder.layers[layer].mlp.fc2.weight.copy_(originals[layer])
base=full(test);yb=torch.tensor([classes.index(r['label']) for r in test]);bp=(base@head.T).argmax(-1);cp=(candidate@head.T).argmax(-1)
# Replay exact stored replacement tensor and re-run images; float-add delta is separately checked.
saved=load_file(str(P/'candidate-network.safetensors'));outside=[]
for name,value in model.state_dict().items():
 if name+'.delta' not in patch and not torch.equal(value,saved[name]):outside.append(name)
assert not outside
replay_errors={}
for name,delta in patch.items():
 key=name.removesuffix('.delta');replay_errors[key]=float((model.state_dict()[key]+delta-saved[key]).abs().max());model.state_dict()[key].copy_(saved[key])
replayed=full(test);assert torch.equal(replayed,candidate)
report={'selected':best,'model':protocol['model'],'changed_tensors':list(patch),'changed_values':sum(int(torch.count_nonzero(v)) for v in patch.values()),'head_unchanged':True,'text_and_projection_unchanged':True,'autonomous_controller':False,'gradients_used':False,'full_image_evaluation':True,'test_n':len(test),'baseline_correct':int((bp==yb).sum()),'candidate_correct':int((cp==yb).sum()),'corrected':int(((bp!=yb)&(cp==yb)).sum()),'regressed':int(((bp==yb)&(cp!=yb)).sum()),'candidate_predictions_reproduced_exactly':True,'delta_addition_max_abs_error':replay_errors,'fresh_test_limit':m['fresh_test_scope'],'predictions':[{'id':r['id'],'label':classes[int(t)],'base':classes[int(b)],'candidate':classes[int(c)]} for r,t,b,c in zip(test,yb,bp,cp)]};write('result.json',report);save_file({name.removesuffix('.delta'):saved[name.removesuffix('.delta')] for name in patch},str(P/'replacement-tensors.safetensors'));print(json.dumps({k:v for k,v in report.items() if k!='predictions'},indent=2),flush=True)

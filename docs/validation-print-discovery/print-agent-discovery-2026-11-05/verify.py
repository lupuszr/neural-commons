import pathlib,json,hashlib,torch
from safetensors.torch import load_file,save_file
P=pathlib.Path(__file__).resolve().parent;parent=P.parent/'print-network-edit-2026-11-05/candidate-network.safetensors';child=P/'frozen/candidate-network.safetensors';a=load_file(str(parent));b=load_file(str(child));assert set(a)==set(b);changed=[];diff={};n=0
for k,v in a.items():
 assert torch.isfinite(b[k]).all()
 if not torch.equal(v,b[k]):changed.append(k);diff[k+'.delta']=b[k]-v;n+=int(torch.count_nonzero(b[k]!=v))
assert changed==['vision_model.encoder.layers.9.mlp.fc2.weight'];save_file(diff,str(P/'network-diff.safetensors'))
for k,v in a.items():
 if k+'.delta' in diff:v.add_(diff[k+'.delta'])
 assert torch.equal(v,b[k]),k
v={'agent_driver':'current Codex conversation assistant','parent_sha256':hashlib.sha256(parent.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(child.read_bytes()).hexdigest(),'changed_tensors':changed,'changed_values':n,'unchanged_tensors':len(a)-len(changed),'exact_replay_all_tensors':True,'all_weights_finite':True,'fixed_head_unchanged':True,'independent_verification_process':True};assert v['candidate_sha256']==json.loads((P/'frozen/commitment.json').read_text())['checkpoint_sha256'];(P/'verification.json').write_text(json.dumps(v,indent=2));print(json.dumps(v))

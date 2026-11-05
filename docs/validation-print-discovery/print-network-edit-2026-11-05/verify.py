import pathlib,json,hashlib
import torch
from safetensors.torch import load_file
P=pathlib.Path(__file__).resolve().parent
base=load_file(str(P/'base-network.safetensors'));candidate=load_file(str(P/'candidate-network.safetensors'));patch=load_file(str(P/'network-diff.safetensors'));assert set(base)==set(candidate)
changed=[];count=0
for name,tensor in base.items():
 if not torch.equal(tensor,candidate[name]):changed.append(name);count+=int(torch.count_nonzero(tensor!=candidate[name]))
 if name+'.delta' in patch: tensor.add_(patch[name+'.delta'])
 assert torch.equal(tensor,candidate[name]),name
assert set(changed)=={k.removesuffix('.delta') for k in patch}
assert changed==['vision_model.encoder.layers.10.mlp.fc2.weight']
frozen=json.loads((P/'frozen-candidate.json').read_text());assert hashlib.sha256((P/'candidate-network.safetensors').read_bytes()).hexdigest()==frozen['checkpoint_sha256']
r=json.loads((P/'result.json').read_text());assert count==r['changed_values']
v={'exact_replay_all_tensors':True,'changed_tensors':changed,'changed_values':count,'unchanged_tensors':len(base)-len(changed),'candidate_sha256':frozen['checkpoint_sha256'],'fresh_process':True}
(P/'verification.json').write_text(json.dumps(v,indent=2));print(json.dumps(v))

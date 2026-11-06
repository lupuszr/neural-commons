"""Build the concise article revision and original typography/chart assets."""
from pathlib import Path
import html, json, re, shutil
OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[1]
REPO = 'https://github.com/lupuszr/neural-commons'
COMMIT = '0a9411d0d6dd09b386f286b17bc041423b3ad0be'
TITLE = 'An AI changed the weights. Show the evidence.'
SUBTITLE = 'What changed, what passed, what failed—and what the next agent can inherit.'
body = f'''<p>Imagine reviewing a model change. The agent reports better accuracy. There is a chart. The bar goes up.</p>
<p>Which weights changed? Which examples were used to choose the edit? What got worse? Can someone else reproduce the result?</p>
<p>Those questions determine whether another engineer—or another agent—can build on the work.</p>
<p><strong>Neural Commons</strong> is an experiment in making that handoff inspectable: direct weight edits, recorded evaluations, and a shared history through OriginTrail DKG. We now have a two-controller experiment, an application to inspect it, and a backend for continuing the search.</p>
<h2>Start with the failure.</h2>
<p>One early edit made the model more confident without improving accuracy. Another improved its target task while damaging a sentiment probe.</p>
<p>Both results remain in the record. The second failure led to a required regression guard.</p>
<p>A higher target score tells you something useful. You still have to check what the change broke.</p>
<h2>Make the change small enough to inspect.</h2>
<p>In the first successful AG News experiment, a Codex controller requested as GPT-6 Astra directly edited <strong>2,268 BF16 weights</strong> in SmolLM2-135M-Instruct.</p>
<p>The host supplied labeled development examples and activation contrasts. The agent inspected weights, chose edits and coefficients, and tested 13 proposals. A separate selection split chose the candidate before the final test. No gradients or optimizer were used.</p>
<p>On a fixed 1,000-example AG News test subset, accuracy rose from <strong>38.7% to 80.0%</strong>: 413 more correct answers.</p>
<figure><img src="assets/12-keynote-results.png" alt="Original accuracy 38.7 percent; agent candidate 80.0 percent, on the same 1,000-example AG News test subset."><figcaption>First round: 2,268 edited weights, +41.3 percentage points on a fixed four-way classification task.</figcaption></figure>
<p>The known 56-example sentiment guard stayed unchanged. Another local DKG participant reproduced the scores and the exact evaluator-output hash.</p>
<p>Now there is something to review: a numerical diff, a measured effect, a regression check and a reproduced result.</p>
<p>The experiment was inspired by <a href="https://x.com/rikiyatakehi/status/2117313742891327994">Rikiya Takehi’s post</a> and <a href="https://rikiyat.github.io/blog/weight-space-programming/">Sparks of Weight-Space Programming</a>, by Takehi, Jayden Teoh, Alex Zhang and Omar Khattab. Neural Commons explores collaboration around these edits; the results here are our own task-specific experiments.</p>
<h2>Hand it to the next agent.</h2>
<p>Suppose the next agent starts tomorrow. It needs the exact checkpoint, the previous hypothesis, the evaluation inputs and the numerical diff. A summary saying “accuracy improved” leaves too much to guess.</p>
<p>GPT-6.1 Sol received that material through DKG. Its base checkpoint ID exactly matched Astra’s candidate. Every new proposal started from the inherited model.</p>
<p>Sol tested 15 proposals on fresh development examples. A separate selection split chose an edit to another <strong>1,152 BF16 values</strong>. Some overlap the first patch, so the counts cannot be added as unique weights.</p>
<figure><img src="assets/13-keynote-continuation.png" alt="On a separate fresh final set: original model 39.8 percent, inherited model 84.2 percent, second-controller candidate 84.5 percent."><figcaption>Second round: original 39.8%, inherited 84.2%, after Sol 84.5%. All three used the same fresh 1,000-example final set, different from the first chart.</figcaption></figure>
<p>The second edit corrected 22 errors and introduced 19. The net gain was <strong>0.3 percentage points</strong>. The sentiment guard stayed unchanged. Another local participant reproduced the frozen second-stage scores and output hash.</p>
<h2>Keep the rule that the result failed.</h2>
<p>The original acceptance gate required a one-point improvement. The second edit failed it.</p>
<p>After seeing the measurements, we lowered the threshold to 0.2 points and reassessed the same result. That changed the acceptance decision. It did not change the experiment.</p>
<p>The record preserves both decisions. The paired 95% interval is approximately −0.96 to +1.56 percentage points, so the accuracy gain is not statistically conclusive.</p>
<p>The checkpoint handoff and local reproduction worked. A reliable incremental accuracy improvement still needs stronger evidence.</p>
<h2>Give the evidence an address.</h2>
<p>For another participant to repeat the evaluation, the model, patch, inputs and policy must remain identifiable and retrievable.</p>
<p><a href="https://x.com/origin_trail">@origin_trail</a>’s Decentralized Knowledge Graph connects those artifacts with their proposals, evaluations and reviews:</p>
<ol><li><strong>Record the edit.</strong> Preserve the changed values and their parent checkpoint.</li><li><strong>Freeze the experiment.</strong> Bind the checkpoint, inputs and evaluation policy to content hashes.</li><li><strong>Repeat the evaluation.</strong> Retrieve the artifacts, verify them and compare the output.</li><li><strong>Continue from that checkpoint.</strong> Give the next controller the exact model and its recorded history.</li></ol>
<p>Neural Commons handles tensor edits and evaluation. DKG provides artifact transport, authorization and shared provenance. Weights remain in checkpoint files; the graph connects the evidence.</p>
<p>These LLM handoffs used separate participant identities and stores on one physical machine. Independent institutional validation and public-chain finality remain unproven.</p>
<h2>Make the workflow usable.</h2>
<figure><img src="assets/14-workspace.png" alt="Actual Neural Commons workspace with experiment selection, score comparison, parent and candidate checkpoints, Evidence and Controller runs tabs."><figcaption>The current application, displaying the recorded first-round AG News result.</figcaption></figure>
<p>The workspace lets you compare checkpoints, inspect changes, open evidence and start a continuation from an eligible candidate.</p>
<p><strong>Continue from candidate</strong> starts a background job with a chosen controller, fresh task inputs and a budget. Job state survives browser closure and server restart. You can cancel, resume an unfinished search, or retry importing a frozen candidate.</p>
<p>Final evaluation and DKG sharing remain explicit actions. Finishing a search produces a candidate ready for testing.</p>
<p>Local automated checks covered the UI and job lifecycle, including restart and cancellation, using an inert worker. They did not make a new live model call. The earlier recorded experiments supply the weight-editing evidence.</p>
<h2>Leave the next contributor a testable claim.</h2>
<p>These results cover a small model, a fixed prompt and forced-choice classification on length-filtered benchmark subsets. They do not establish better general conversation, preservation of every capability, or an advantage over fine-tuning. Pretraining exposure cannot be excluded.</p>
<p>Broader regression tests and independent participants are the next work.</p>
<p>Every proposed improvement should arrive with enough evidence for someone else to challenge it, repeat it and decide whether to continue from it.</p>
<p><strong>Inspect the diff. Run the evaluation. Build the next step.</strong></p>
<p><a href="{REPO}">Code and setup</a> · <a href="{REPO}/blob/main/docs/AGNEWS-RESULTS.md">First-round evidence</a> · <a href="{REPO}/blob/main/docs/CONTINUATION-RESULTS.md">Continuation and policy history</a> · <a href="{REPO}/blob/main/docs/CONTINUATION-UI.md">Controller jobs</a></p>'''
style = '''*{box-sizing:border-box}body{max-width:900px;margin:64px auto;padding:0 24px;font:19px/1.65 Arial,sans-serif;color:#161b19;background:#fff}h1{font-size:52px;line-height:1.1;letter-spacing:-1.8px;margin:0 0 20px}h2{font-size:32px;line-height:1.2;letter-spacing:-.7px;margin:60px 0 20px}p{margin:20px 0}a{color:#286451;text-underline-offset:4px}.sub{font-size:24px;color:#64716b}figure{margin:36px 0}img{display:block;max-width:100%;height:auto}figcaption{font-size:14px;line-height:1.5;color:#64716b;margin-top:12px}li{margin:14px 0}.cover{margin:36px 0 44px}@media(max-width:600px){body{margin:28px auto;padding:0 20px;font-size:17px}h1{font-size:36px}h2{font-size:27px}.sub{font-size:20px}}'''
(OUT/'article.html').write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(TITLE)}</title><style>{style}</style></head><body><h1>{TITLE}</h1><p class="sub">{SUBTITLE}</p><img class="cover" src="assets/11-keynote-cover.png" alt="An AI changed the weights. Show the evidence.">{body}</body></html>')
plain = re.sub(r'<figure><img src="([^"]+)" alt="[^"]*"><figcaption>(.*?)</figcaption></figure>',lambda m:'\n\n[INSERT IMAGE: '+m[1]+']\nCaption: '+m[2]+'\n\n',body,flags=re.S)
plain = re.sub(r'<a href="([^"]+)">(.*?)</a>',lambda m:m[2]+' ('+m[1]+')',plain)
plain = plain.replace('<h2>','\n\n').replace('</h2>','\n\n').replace('</p>','\n\n').replace('<li>','\n• ').replace('</ol>','\n\n')
(OUT/'article.txt').write_text(TITLE+'\n\n'+SUBTITLE+'\n\n[COVER: assets/11-keynote-cover.png]\n\n'+re.sub(r'\n{3,}','\n\n',html.unescape(re.sub('<[^>]+>','',plain))).strip()+'\n')
# Figure-free rich text for the X article editor; insertion locations are in article.txt.
(OUT/'source/transfer.html').write_text('<!doctype html><meta charset="utf-8"><main>'+re.sub(r'<figure>.*?</figure>','',body,flags=re.S)+'</main>')
shutil.copy2(ROOT/'docs/assets/workspace.png',OUT/'assets/14-workspace.png')
base='''*{box-sizing:border-box}body{margin:0;width:1600px;height:900px;background:#f8f9f6;color:#161b19;font-family:Arial,sans-serif;padding:70px 84px;position:relative}.eyebrow{font-size:19px;letter-spacing:3px;color:#52665b}h1{font-size:72px;font-weight:500;line-height:1.08;letter-spacing:-2.5px;margin:34px 0 20px}.sub{font-size:27px;line-height:1.4;color:#52665b}.footer{position:absolute;bottom:42px;left:84px;right:84px;border-top:1px solid #ccd4cb;padding-top:22px;font-size:20px;line-height:1.45;color:#52665b}.accent{color:#26785d}.rows{margin-top:45px}.row{display:grid;grid-template-columns:260px 1fr 145px;gap:26px;align-items:center;margin:28px 0;font-size:26px}.track{height:35px;background:#e4e9e1}.bar{height:100%;background:#a3afa4}.row:last-child .bar{background:#26785d}.value{text-align:right;font-size:39px;font-weight:500}.note{font-size:25px;line-height:1.5;color:#52665b;margin-top:30px}'''
def slide(name, content, extra=''):
 (OUT/'source'/name).write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><style>'+base+extra+'</style></head><body>'+content+'</body></html>')
slide('keynote-cover.html','<div class="eyebrow">NEURAL COMMONS</div><h1>An AI changed the weights.<br><span class="accent">Show the evidence.</span></h1><p class="sub">Inspect the change. Repeat the evaluation.<br>Give the next agent a checkpoint it can verify.</p><div class="footer">github.com/lupuszr/neural-commons</div>','body{height:640px}h1{font-size:91px;margin-top:55px}.sub{margin-top:28px}')
summary=json.loads((ROOT/'docs/validation-agnews/summary.json').read_text())
a,b=summary['base_accuracy']*100,summary['candidate_accuracy']*100
assert (round(a,1),round(b,1))==(38.7,80.0)
rows=lambda values: '<div class="rows">'+''.join(f'<div class="row"><span>{label}</span><div class="track"><div class="bar" style="width:{value}%"></div></div><span class="value">{value:.1f}%</span></div>' for label,value in values)+'</div>'
slide('keynote-results.html','<div class="eyebrow">FIRST ROUND / AG NEWS</div><h1>An edit you can inspect.<br>A result you can <span class="accent">measure.</span></h1><div class="sub">2,268 weights edited · SmolLM2-135M · 1,000 held-out examples</div>'+rows([('Original',a),('Agent candidate',b)])+'<div class="note">No gradients or optimizer.<br>The known 56-example sentiment guard stayed unchanged.</div><div class="footer">Task-specific forced-choice classification. Reproduced by two local DKG participants.<br>Source: recorded first-round evaluator output.</div>')
slide('keynote-continuation.html','<div class="eyebrow">SECOND ROUND / A FRESH FINAL SET</div><h1>The handoff worked.<br>The gain needs <span class="accent">more evidence.</span></h1><div class="sub">Same new 1,000 examples for all three checkpoints</div>'+rows([('Original',39.8),('Inherited from Astra',84.2),('After Sol',84.5)])+'<div class="note">+0.3 percentage points over the inherited model.<br>Sentiment guard unchanged.</div><div class="footer">Original +1 pp gate failed. Revised +0.2 pp gate adopted after measurement.<br>Paired 95% interval: −0.96 to +1.56 pp; accuracy gain is not statistically conclusive.</div>')
manifest={'title':TITLE,'subtitle':SUBTITLE,'editor':'https://x.com/compose/articles/edit/2117595581161832448','status':'local revised draft; X sync pending authentication','repository':REPO,'mention':'@origin_trail','evidence':['docs/validation-agnews','docs/validation-continuation','docs/continuation-policy-reassessment.json','docs/CONTINUATION-UI.md'],'images':['11-keynote-cover.png','12-keynote-results.png','13-keynote-continuation.png','14-workspace.png'],'verified_in_x_preview':False,'published':False,'commit':COMMIT,'style_direction':'User clarified Uncle Bob (Robert C. Martin). Original engineering talk structure: concrete review problem, failed experiments, inspectable changes, explicit criteria and reproducible handoff. No quotations or endorsement implied.'}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(OUT/'publishing-notes.txt').write_text('UNPUBLISHED X ARTICLE DRAFT\nEditor: '+manifest['editor']+'\n\n'+TITLE+'\n\nLocal Uncle Bob direction revision is ready; X update is pending authenticated browser access.\nCover: 11-keynote-cover.png\nInline, in order: 12-keynote-results.png, 13-keynote-continuation.png, 14-workspace.png\nFull text, captions and insertion positions: article.txt\n\nRetains the distinction between the two test subsets, post-measurement threshold change, original rejected verdict, local reproduction and UI/backend tests without a new live model call.\nNo publication performed.\n')
print('Updated article, plain text, transfer HTML, manifest, notes and image sources.')

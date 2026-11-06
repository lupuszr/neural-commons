"""Build the concise article revision and original typography/chart assets."""
from pathlib import Path
import html, json, re, shutil
OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[1]
REPO = 'https://github.com/lupuszr/neural-commons'
COMMIT = '0a9411d0d6dd09b386f286b17bc041423b3ad0be'
TITLE = 'An AI changed the weights. Show the evidence.'
SUBTITLE = 'What changed, what passed, what failed—and what the next agent can inherit.'
body = f'''<p>Suppose I send you a change to review. It modifies 2,268 values in a language model. I attach a chart showing accuracy going from 38.7% to 80.0%.</p>
<p>Would you accept the change?</p>
<p>You would probably ask to see the test. Then the inputs. Then the change itself. You might ask whether I used those same test examples to choose the edit. And somewhere in that review, you would ask what else I broke.</p>
<p>The review is hypothetical. The numbers are real.</p>
<p>We ran this experiment in <strong>Neural Commons</strong>. An AI controller edited a small language model’s weights. A second controller continued from the resulting checkpoint. OriginTrail DKG carried the model and its evidence between participants.</p>
<p>There is a useful result here. There is also a failed acceptance test. We need to understand both before deciding what the next agent should inherit.</p>
<h2>What does “better” mean?</h2>
<p>Our early experiments gave us a fairly unpleasant answer to that question.</p>
<p>One edit increased confidence without improving accuracy. The model became more certain, and remained just as wrong. Another edit improved its target task while damaging a sentiment probe.</p>
<p>If you had looked only at the target score, you would have missed the damage. We kept those failures and made the sentiment check a required guard for the news experiment.</p>
<p>Now “better” had a concrete meaning: improve the news-classification score while preserving the known sentiment guard. That is a claim we can test. It still says nothing about all the capabilities we have not checked.</p>
<p>A Codex controller requested as GPT-6 Astra inspected SmolLM2-135M-Instruct and tested 13 proposals. The host supplied labeled development examples and activation contrasts; the controller chose the numerical edits and coefficients. A separate selection split chose the candidate before the final test.</p>
<p>The resulting patch changed <strong>2,268 BF16 weights</strong>. No gradients or optimizer were used.</p>
<figure><img src="assets/12-keynote-results.png" alt="Original accuracy 38.7 percent; agent candidate 80.0 percent, on the same 1,000-example AG News test subset."><figcaption>First round: 38.7% to 80.0% on a fixed 1,000-example AG News subset. The known 56-example sentiment guard stayed unchanged.</figcaption></figure>
<p>That is 413 more correct answers on this test. Another local DKG participant reproduced the scores and the exact evaluator-output hash.</p>
<p>Notice how much more we can say now than “the bar went up.” We can identify the edited values, explain how the candidate was chosen, inspect the regression check and repeat the evaluation.</p>
<p>Those are the things the reviewer needed.</p>
<h2>Then give the work to somebody else.</h2>
<p>Imagine handing the next engineer a file called <em>improved-model-final-v2</em>. You tell them it is the good one. They ask which experiment produced it.</p>
<p>You send a screenshot.</p>
<p>They still need the exact checkpoint, the patch, the evaluation inputs and the rule used to accept it. An agent continuing the work has the same problem.</p>
<p>So GPT-6.1 Sol received the checkpoint through DKG, along with Astra’s hypothesis, results and exact numerical diff. Its base checkpoint ID matched Astra’s candidate ID. Every new proposal started from that inherited model.</p>
<p>Sol tested 15 proposals on fresh development examples. A separate selection split chose an edit to <strong>1,152 BF16 values</strong>. Some overlap the first patch, so adding the two counts would overstate the number of unique edited weights.</p>
<figure><img src="assets/13-keynote-continuation.png" alt="On a separate fresh final set: original model 39.8 percent, inherited model 84.2 percent, second-controller candidate 84.5 percent."><figcaption>Second round, on the same fresh 1,000-example final set: original 39.8%, inherited 84.2%, after Sol 84.5%. This subset differs from the first chart.</figcaption></figure>
<p>The second edit corrected 22 errors and introduced 19. Three more correct answers. The sentiment guard stayed unchanged, and another local participant reproduced the frozen scores and output hash.</p>
<p>The handoff worked. Now look at the acceptance decision.</p>
<h2>The test failed.</h2>
<p>Before this final evaluation, the required improvement was one percentage point. The measured improvement was 0.3.</p>
<p>Under that rule, the candidate failed.</p>
<p>We then lowered the threshold to 0.2 points and reassessed the same measurements. The candidate passed the revised policy. Both decisions remain in the record.</p>
<p>Suppose you reviewed a software change that failed an acceptance test. After seeing the failure, the team changed the expected value. You would want that decision explained. The same obligation applies when the changed values happen to be model weights.</p>
<p>Changing a policy can be a legitimate decision. It cannot make the original test pass retroactively.</p>
<p>And three additional correct answers are a small margin. The paired 95% interval is approximately −0.96 to +1.56 percentage points. The accuracy gain is not statistically conclusive.</p>
<p>We have evidence that a second controller inherited the exact model, continued the search and produced a reproducible candidate. A reliable incremental accuracy improvement needs stronger evidence. Keeping those claims separate is part of the work.</p>
<h2>Make the review repeatable.</h2>
<p>This is the engineering problem Neural Commons is trying to solve. When someone asks how a model arrived at its current state, they should be able to follow the actual changes and decisions.</p>
<p><a href="https://x.com/origin_trail">@origin_trail</a>’s Decentralized Knowledge Graph connects checkpoints and patches with proposals, evaluations and reviews. Content hashes identify the artifacts and bind the experiment inputs and policy. Another participant can retrieve them, verify them and rerun its configured evaluator.</p>
<p>Neural Commons performs the tensor edits and evaluation. DKG supplies artifact transport, authorization and shared provenance. The weights remain in checkpoint files; the graph connects the evidence.</p>
<p>The recorded LLM handoffs used separate identities and stores on one physical machine. That establishes local reproduction. Independent institutional validation and public-chain finality remain unproven.</p>
<figure><img src="assets/14-workspace.png" alt="Neural Commons workspace displaying the recorded first-round experiment, checkpoint comparison, evidence and controller-run controls."><figcaption>The workspace brings the model change, its evidence and the next continuation into one review.</figcaption></figure>
<p>The application lets you compare checkpoints, inspect changes and open the evidence. <strong>Continue from candidate</strong> starts a background job with fresh task inputs and a budget. Job state survives browser closure and server restart; you can cancel, resume an unfinished search or retry importing a frozen candidate.</p>
<p>Finishing that job gives you a candidate. Final evaluation and DKG sharing are explicit next actions. Local UI and lifecycle checks used an inert worker, without a new live model call.</p>
<p>We still need broader regression checks and independent participants. These experiments cover a small model, a fixed prompt and forced-choice classification on length-filtered benchmark subsets. They establish neither better general conversation nor an advantage over fine-tuning. Pretraining exposure cannot be excluded.</p>
<p>Come back to that first review. The useful handoff includes the change, the test, the result and the decision—including the decision we revised.</p>
<p><strong>The next contributor should be able to check our work before building on it.</strong></p>
<p>Inspired by <a href="https://x.com/rikiyatakehi/status/2117313742891327994">Rikiya Takehi’s post</a> and <a href="https://rikiyat.github.io/blog/weight-space-programming/">Sparks of Weight-Space Programming</a>, by Takehi, Jayden Teoh, Alex Zhang and Omar Khattab. The task-specific experiments described here are our own.</p>
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
manifest={'title':TITLE,'subtitle':SUBTITLE,'editor':'https://x.com/compose/articles/edit/2117595581161832448','status':'local revised draft; X sync pending authentication','repository':REPO,'mention':'@origin_trail','evidence':['docs/validation-agnews','docs/validation-continuation','docs/continuation-policy-reassessment.json','docs/CONTINUATION-UI.md'],'images':['11-keynote-cover.png','12-keynote-results.png','13-keynote-continuation.png','14-workspace.png'],'verified_in_x_preview':False,'published':False,'commit':COMMIT,'style_direction':'Revised after user feedback: a sustained hypothetical code review, concrete failures, a deliberate reveal of the failed acceptance gate, and a return to the opening review. Original wording; no quotations, impersonation or endorsement.'}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(OUT/'publishing-notes.txt').write_text('UNPUBLISHED X ARTICLE DRAFT\nEditor: '+manifest['editor']+'\n\n'+TITLE+'\n\nLocal Uncle Bob direction revision is ready; X update is pending authenticated browser access.\nCover: 11-keynote-cover.png\nInline, in order: 12-keynote-results.png, 13-keynote-continuation.png, 14-workspace.png\nFull text, captions and insertion positions: article.txt\n\nRetains the distinction between the two test subsets, post-measurement threshold change, original rejected verdict, local reproduction and UI/backend tests without a new live model call.\nNo publication performed.\n')
print('Updated article, plain text, transfer HTML, manifest, notes and image sources.')

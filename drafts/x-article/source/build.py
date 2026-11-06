from pathlib import Path
import html, json, re, shutil, zipfile

OUT=Path(__file__).resolve().parents[1]
ROOT=OUT.parents[1]
REPO='https://github.com/lupuszr/neural-commons'
PIN=REPO+'/blob/20ee5800317df9d41dff72907a95fdc9c63b3b90/'
MENTION='@origin_trail'

title='Neural Commons: making model improvements reproducible with OriginTrail DKG'
subtitle='A small model got better. The more interesting part is how another participant could check it.'
body=f'''<p>A model improves. Someone shares a checkpoint and a higher score. What would it take for another person to verify the change, reproduce the result, and build on it?</p>
<p>I built <strong>Neural Commons</strong> to explore that workflow with <a href="https://origintrail.io/">OriginTrail’s Decentralized Knowledge Graph</a>. It connects model versions, weight patches, evaluation inputs, and reports from different participants into a shared record of an experiment.</p>
<p>The code is public: <a href="{REPO}">github.com/lupuszr/neural-commons</a>.</p>
<h2>First, the result</h2>
<p>A small, single-layer softmax classifier trained on the Iris dataset improved from <strong>83.3% to 93.3% accuracy</strong> on a fixed held-out set: 25 correct predictions out of 30 became 28 out of 30.</p>
<p>That is a <strong>10 percentage point improvement</strong>. A second DKG participant fetched the proposal and its dependencies, ran the configured evaluator, and reproduced the same scores.</p>
<figure><img src="assets/04-results.png" alt="Iris held-out accuracy increased from 83.3 percent, or 25 of 30 predictions, to 93.3 percent, or 28 of 30. Two participant processes on one host reproduced the scores."><figcaption>Iris experiment: one fixed split, 120 training samples, 30 held-out samples. Both participant processes ran on the same host.</figcaption></figure>
<p>The baseline was saved after one training epoch; the candidate after 300. The training schedule and evaluation policy were fixed before evaluation, and held-out labels were excluded from optimization. Ordinary gradient updates produced the better weights. Neural Commons made the resulting change shareable and its evaluation repeatable.</p>
<p>This is a deliberately small reference experiment. Three more correct predictions on one 30-sample split demonstrate the workflow; they do not establish a general performance gain across tasks or seeds.</p>
<figure><img src="assets/02-app-evaluations.png" alt="Actual Neural Commons evaluations screen. The Iris accuracy result appears alongside separate synthetic repair and regression tests."><figcaption>Actual application screenshot from the saved local run. The accuracy card is Iris; the MSE cards are separate synthetic fixtures.</figcaption></figure>
<h2>Where DKG enters the loop</h2>
<p>A useful contribution includes more than changed bytes. It needs the base model, a proposed change, a reason to try it, and enough context to test the claim.</p>
<p>Neural Commons represents that context with linked records: <strong>ModelVersion, Hypothesis, PatchProposal, Evaluation, Review, and DerivedVersion</strong>. The records associate an author and an experiment with content hashes and the evidence they depend on.</p>
<p>Here is the workflow:</p>
<ol><li><strong>Prepare a change.</strong> A participant imports a base and candidate checkpoint. The Rust engine produces a patch over named tensors.</li><li><strong>Share the proposal through DKG.</strong> The proposal references the patch, model artifacts, dataset, evaluator identity, configuration, and acceptance policy within a Context Graph.</li><li><strong>Reproduce it elsewhere.</strong> Another participant retrieves the referenced artifacts through DKG, verifies their hashes, applies the patch, and runs its locally configured evaluator.</li><li><strong>Return the evidence.</strong> The second participant shares its evaluation and review through DKG. The first can retrieve them and inspect authorship and their relationship to the original proposal.</li></ol>
<p>For me, this is the compelling part of OriginTrail: it provides a shared structure for the knowledge around an experiment, together with peer transport for the referenced artifacts. A proposed improvement and the evidence behind it can travel together.</p>
<p>The weight files use hashed manifests and bounded native DKG blobs; the application does not turn every weight into an RDF triple. DKG handles peer connectivity and Context Graph authorization. Neural Commons handles tensor changes and evaluation orchestration.</p>
<h2>Then, two physical machines</h2>
<p>I also tested the exchange between a laptop and a Mac mini, each running its own DKG daemon with a separate identity and storage.</p>
<p>The Mac mini started with an empty client artifact store. It fetched the model, patch, and evaluation inputs through DKG, executed the evaluator, and returned its report and review. The laptop retrieved both and checked their authorship and relationships.</p>
<ul><li>A controlled repair passed on both machines, with mean squared error falling from <strong>3.6796875 to 0</strong>.</li><li>A deliberately worse patch failed on both machines.</li><li>A <strong>96 MiB synthetic checkpoint</strong> crossed DKG’s native peer protocol and passed SHA-256 verification.</li><li>After restarting the Mac mini daemon, a fresh client cache fetched and verified that checkpoint again.</li></ul>
<figure><img src="assets/03-dkg-lineage.png" alt="Actual laptop UI showing a passed Review and Evaluation authored by the Mac mini participant, marked remote-dkg-readback and synthetic fixture."><figcaption>Actual laptop UI: the Mac mini’s review and evaluation read back through DKG. These records belong to the controlled synthetic repair, separate from the Iris experiment.</figcaption></figure>
<p>Those cross-machine behavioral checks use synthetic fixtures. The Iris result above was reproduced by two local participant processes. Keeping those two results distinct makes it clear what has been tested.</p>
<h2>A general engine, with explicit evaluator choices</h2>
<p>The core registry and patch engine work with named tensors, without a hardcoded network architecture. V1 supports single-file and sharded Safetensors checkpoints, F32/F16/BF16 patches, and bounded-memory file processing. Evaluators are replaceable and can be specific to a model architecture or task.</p>
<p>That leaves a useful boundary: the shared engine tracks what changed; the chosen evaluator determines what that change means for behavior.</p>
<p>This validation used DKG <strong>Shared Working Memory</strong> with a disposable local EVM. It did not establish public-chain finality. OriginTrail distinguishes peer-shared working memory from blockchain-anchored Verifiable Memory; the latter is a separate publication step. The tested integration also uses a documented local compatibility patch for opaque artifact reads. See the <a href="{PIN}docs/CROSS-HOST.md">two-host validation notes</a> for the exact setup and remaining boundaries.</p>
<h2>Build on it</h2>
<p>I want model improvements to come with evidence another participant can inspect and reproduce. OriginTrail DKG gives this project a foundation for sharing that evidence across participants while retaining its connections to the original change.</p>
<p>The next useful contributions are more evaluator adapters, stronger benchmarks, and experiments with independently operated participants. Bring a model, define what “better” means for your task, and make the result reproducible.</p>
<p><strong>Explore Neural Commons:</strong> <a href="{REPO}">{REPO}</a><br><strong>Build with OriginTrail DKG:</strong> <a href="https://docs.origintrail.io/">docs.origintrail.io</a><br><a href="https://x.com/{MENTION[1:]}">{MENTION}</a></p>
<h2>Code and evidence</h2>
<ul><li><a href="{PIN}docs/validation-v1/dkg-integration.json">Iris scores and second-participant reproduction</a></li><li><a href="{PIN}scripts/iris_experiment.py">Training schedule, split, and experiment code</a></li><li><a href="{PIN}docs/validation-v1/cross-host.json">Two-machine validation results</a></li><li><a href="{PIN}docs/V1.md">Supported formats, evaluator contract, and setup</a></li><li><a href="https://github.com/OriginTrail/dkg">OriginTrail DKG source and memory model</a></li><li>Dataset: <a href="https://doi.org/10.24432/C56C76">Fisher, R. (1936). Iris. UCI Machine Learning Repository</a>, CC BY 4.0.</li></ul>'''

style='''*{box-sizing:border-box}body{margin:0;background:#f6f7f3;color:#172c2d;font:19px/1.7 system-ui,-apple-system,sans-serif}header,article{max-width:860px;margin:auto;padding:42px 28px}header{padding-bottom:0}.label{font:12px/1.5 system-ui;letter-spacing:2px;color:#497a6b}h1{font-size:46px;line-height:1.12;letter-spacing:-1.8px;margin:18px 0}h2{font-size:28px;line-height:1.25;margin:52px 0 18px;letter-spacing:-.6px}p{margin:0 0 23px}a{color:#007660;text-decoration-thickness:1px;text-underline-offset:4px}.subtitle{color:#536a65;font-size:23px;line-height:1.5}figure{margin:34px -14px}img{display:block;width:100%;border-radius:10px}figcaption{font-size:14px;line-height:1.6;color:#536a65;padding:10px 14px}li{margin-bottom:12px}strong{font-weight:680}.draft{font-size:13px;border-bottom:1px solid #d7e1d9;padding:12px 28px;text-align:center;color:#536a65}footer{max-width:860px;margin:auto;padding:0 28px 60px;font-size:13px;color:#536a65}@media(max-width:600px){h1{font-size:34px}body{font-size:17px}figure{margin:25px 0}}'''
(OUT/'article.html').write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>{style}</style><div class="draft">DRAFT · Prepared 3 November 2026 · Not published</div><header><div class="label">BUILDING WITH ORIGINTRAIL DKG</div><h1>{title}</h1><p class="subtitle">{subtitle}</p><img src="assets/01-cover.png" alt="Neural Commons. Propose a change, share through OriginTrail DKG, reproduce the result."></header><article>{body}</article><footer>Editorial packaging and charts accompany captured application evidence. Figures are not additional experiments.</footer></html>')

# Plain-text copy with explicit links and image insertion points.
plain=body
plain=re.sub(r'<figure><img src="([^"]+)" alt="[^"]*"><figcaption>(.*?)</figcaption></figure>',lambda m:'\n\n[INSERT IMAGE: '+m[1]+']\nCaption: '+re.sub('<[^>]+>','',m[2])+'\n\n',plain,flags=re.S)
plain=re.sub(r'<a href="([^"]+)">(.*?)</a>',lambda m:m[2] if m[1]==m[2] else m[2]+' ('+m[1]+')',plain)
plain=re.sub(r'<h2>(.*?)</h2>',r'\n\n\1\n\n',plain)
plain=plain.replace('<li>','\n• ').replace('</p>','\n\n').replace('<br>','\n')
plain=html.unescape(re.sub('<[^>]+>','',plain))
plain=re.sub(r'\n{3,}','\n\n',plain).strip()
(OUT/'article.txt').write_text(title+'\n\n'+subtitle+'\n\n[COVER: assets/01-cover.png]\n\n'+plain+'\n')

# A code-native cover and a data figure, exported by Playwright as PNG.
base='''*{box-sizing:border-box}html,body{margin:0;width:1600px;height:900px;overflow:hidden}body{background:#0d1a1e;color:#f0f7f4;font-family:Arial,sans-serif;padding:64px 80px}.eyebrow{font-size:20px;letter-spacing:4px;color:#a1e6ca}h1{font-size:87px;line-height:1.03;letter-spacing:-4px;margin:38px 0 22px;font-weight:700}.sub{font-size:29px;color:#a5bdb7;line-height:1.5}.footer{position:absolute;bottom:46px;left:80px;right:80px;display:flex;justify-content:space-between;color:#8daaa3;font-size:19px}.mint{color:#a1e6ca}'''
cover=f'''<div class="eyebrow">NEURAL COMMONS / BUILT WITH ORIGINTRAIL DKG</div><h1>Model improvements.<br><span class="mint">Evidence others can check.</span></h1><div class="sub">Weight patches, provenance, and reproducible evaluations.<br>Shared between participants through the Decentralized Knowledge Graph.</div><div class="flow"><div><small>01 / CONTRIBUTE</small><strong>Propose a change</strong><p>Checkpoint + named tensor patch</p></div><span>→</span><div><small>02 / CONNECT</small><strong>Share through DKG</strong><p>Artifacts + linked evidence</p></div><span>→</span><div><small>03 / VERIFY</small><strong>Reproduce the result</strong><p>Evaluation + participant review</p></div></div><div class="footer"><span>Open source · Rust · Replaceable evaluators</span><span>github.com/lupuszr/neural-commons</span></div>'''
cstyle='''.flow{display:flex;align-items:center;gap:22px;margin-top:66px}.flow>div{flex:1;background:#152b2e;border:1px solid #35544e;border-radius:16px;padding:28px 25px}.flow>span{font-size:35px;color:#a1e6ca}.flow small{font-size:15px;letter-spacing:2px;color:#a1e6ca}.flow strong{display:block;font-size:27px;margin-top:19px}.flow p{font-size:20px;color:#a5bdb7;margin-bottom:0}'''
(OUT/'source/cover.html').write_text('<!doctype html><meta charset="utf-8"><style>'+base+cstyle+'</style>'+cover)
local=json.loads((ROOT/'docs/validation-v1/dkg-integration.json').read_text())['checks']['iris_external_evaluator']
scores=local['a']['evaluation']['evaluation']['scores']
assert scores==local['b']['evaluation']['scores']
chart=f'''<div class="eyebrow">NEURAL COMMONS / RECORDED IRIS EXPERIMENT</div><h1 style="font-size:64px;margin:32px 0 12px">A better checkpoint.<br><span class="mint">The same result, reproduced.</span></h1><div class="sub">Held-out accuracy · 30 samples · single-layer softmax classifier</div><div class="plot"><div class="row"><div class="lab">Baseline<small>1 training epoch</small></div><div class="track"><div class="bar old" style="width:{scores['base']*100}%"></div></div><div class="value">{scores['base']:.1%}<small>25 / 30 correct</small></div></div><div class="row"><div class="lab">Candidate<small>300 training epochs</small></div><div class="track"><div class="bar" style="width:{scores['candidate']*100}%"></div></div><div class="value mint">{scores['candidate']:.1%}<small>28 / 30 correct</small></div></div><div class="axis"><span>0%</span><span>50%</span><span>100%</span></div></div><div class="note"><strong>+10 percentage points</strong><span>120 training samples · fixed split, seed 17<br>Scores reproduced by two participant processes on one host.</span></div><div class="footer"><span>Single small experiment; no generalization across tasks or seeds established.</span><span>Source: repository validation JSON</span></div>'''
chstyle='''.plot{margin-top:44px}.row{display:flex;align-items:center;gap:28px;margin:29px 0}.lab{width:230px;font-size:29px}.lab small,.value small{display:block;color:#9db7b0;font-size:18px;margin-top:9px}.track{width:900px;background:#20383c;height:54px;border-radius:8px;overflow:hidden}.bar{height:100%;background:#a1e6ca;border-radius:8px}.old{background:#698a86}.value{font-size:39px;font-weight:700;flex:1}.value small{font-weight:400}.axis{margin-left:258px;width:900px;display:flex;justify-content:space-between;color:#8daaa3;font-size:17px}.note{margin-top:45px;padding-top:28px;border-top:1px solid #35544e;display:flex;align-items:center;justify-content:space-between}.note strong{color:#a1e6ca;font-size:37px}.note span{font-size:21px;color:#b4c8c2;line-height:1.5;text-align:right}'''
(OUT/'source/results.html').write_text('<!doctype html><meta charset="utf-8"><style>'+base+chstyle+'</style>'+chart)

notes=f'''X ARTICLE DRAFT — ENGLISH
Prepared 2026-11-03. Nothing has been posted.

Open article.html to review the illustrated article. Copy article.txt into the X Article editor; replace image insertion markers with the PNGs below. Apply headings and hyperlinks in the editor.

ASSET ORDER AND CAPTIONS
01-cover.png — Cover. Code-rendered editorial graphic, not an application screenshot. Alt: Neural Commons connects proposed weight changes, DKG sharing, and reproduced evaluations.
04-results.png — After the first result paragraph. Data figure derived directly from docs/validation-v1/dkg-integration.json. Alt: Iris held-out accuracy increased from 83.3% (25/30) to 93.3% (28/30), reproduced by two local participants.
02-app-evaluations.png — After the experimental-method paragraph. Actual app capture from the saved single-host run. Accuracy is Iris; MSE cards are synthetic fixtures.
03-dkg-lineage.png — After the two-machine results. Actual app capture of the laptop journal showing the Mac mini's passed review and evaluation, marked remote-dkg-readback and synthetic fixture.
05-regression-rejected.png — Optional additional image. Actual app capture of the cross-host negative-control review and evaluation. A failed verdict is the expected outcome for the deliberately worse patch.

CONFIRMED MENTION
Use @origin_trail (https://x.com/origin_trail), the official account linked by OriginTrail and confirmed by the author.

SUGGESTED LAUNCH POST
I built Neural Commons with OriginTrail DKG: share a weight patch, reproduce its evaluation, and trace the evidence. Iris accuracy: 83.3% → 93.3%. Separate laptop ↔ Mac mini exchange passed too. Code, screenshots, and results in the article. {MENTION}

FACT BOUNDARIES
Iris: 120 train / 30 held-out, seed 17, 1 vs 300 epochs, learning rate 0.1. Additional training produced the change. No novel optimizer or autonomous improvement claim.
Iris reproduction: two participant processes on one physical host.
Cross-host: same LAN, separate DKG identities; synthetic repair and regression, 100,663,385-byte synthetic checkpoint, restart and fresh-cache retrieval.
DKG: Shared Working Memory plus a disposable local EVM, with documented local opaque-source compatibility patch. No public-chain finality or production-readiness claim.
Support: Safetensors, F32/F16/BF16; generic named-tensor engine does not mean every format, quantization, or architecture has a ready evaluator.

EVIDENCE
{PIN}docs/validation-v1/dkg-integration.json
{PIN}docs/validation-v1/cross-host.json
{PIN}scripts/iris_experiment.py
{PIN}docs/CROSS-HOST.md
{PIN}docs/V1.md
https://github.com/OriginTrail/dkg
https://origintrail.io/

CAPTURE PROVENANCE
App screenshots captured from existing completed participant journals with the unmodified local UI. No experiment rerun, content replacement, or image retouching. Temporary local UI servers were stopped after capture. No tokens are displayed in screenshots.
Source journals: .runtime/demo-20261103-091624/a and .runtime/cross-host-20261103-122714/participant.
Scripts under source/ regenerate graphics and capture screenshots when the original workspace is available. The ZIP is intended for local review; source logs are excluded.
'''
(OUT/'publishing-notes.txt').write_text(notes)
print('Draft generated:',len(re.sub('<[^>]+>',' ',body).split()),'words including references')

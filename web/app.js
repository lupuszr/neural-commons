'use strict';
const el = id => document.getElementById(id);
const node = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const short = id => typeof id === 'string' ? id.slice(0, 12) : 'Unavailable';
const button = (label, run, cls) => {
  const b = node('button', label, cls);
  b.type = 'button'; b.addEventListener('click', run); return b;
};
let requireToken = true;
const authHeaders = credential => credential ? { Authorization: `Bearer ${credential}` } : {};
let token = '', snapshot = null, experiments = [], selected = '', epoch = 0, busy = false;
let workspaceView = location.hash === '#/shared' ? 'shared' : 'experiments';
let navigationView = workspaceView;
const navigationScroll = { experiments: 0, shared: 0 };
let graphRequest = 0, graphInfo = null, graphError = '', graphLoading = false;
let researchTimer = null, researchFetching = false, researchRevision = '';
let cache = new Map();
let checkpointRequest = 0;
async function get(path, credential = token) {
  const r = await fetch(path, { headers: authHeaders(credential), signal: AbortSignal.timeout(15000) });
  if (!r.ok) { const e = new Error(`Data unavailable (HTTP ${r.status})`); e.status = r.status; throw e; }
  return r.json();
}
function artifact(id) {
  if (!/^[a-f0-9]{64}$/.test(id || '')) return Promise.reject(new Error('Invalid artifact identity'));
  if (!cache.has(id)) cache.set(id, get(`/api/artifact-metadata/${id}`));
  return cache.get(id);
}
async function optionalArtifact(id, errors) {
  try { return await artifact(id); }
  catch (e) { if (e.status === 401) throw e; errors.push(`${short(id)}: ${e.message}`); return null; }
}
function exact(parent, label, data) {
  const d = node('details'); d.append(node('summary', label), node('pre', JSON.stringify(data, null, 2))); parent.append(d); return d;
}
function lazy(parent, label, render) {
  const d = node('details'), body = node('div');
  d.append(node('summary', label), body); let loaded = false;
  d.addEventListener('toggle', async () => {
    if (!d.open || loaded) return;
    loaded = true; const generation = epoch; body.textContent = 'Loading evidence…';
    try { const content = await render(); if (generation === epoch) body.replaceChildren(content); }
    catch (e) { if (generation === epoch) { body.textContent = e.message; body.className = 'notice'; loaded = false; } }
  });
  parent.append(d); return d;
}
const current = () => experiments.find(x => x.id === selected);
const verdictClass = status => status === 'passed' ? 'good' : status === 'failed' ? 'bad' : 'warning';
const evaluatorNames = { 'nc/linear-classifier-python/v1': 'Linear classifier', 'nc/scalar-mlp-cpu/v1': 'Neural network regression' };
const metricNames = { 'accuracy/v1': 'Accuracy', 'guarded_accuracy/v1': 'Guarded accuracy', 'mean_squared_error/v1': 'Mean squared error' };
function setBusy(value) {
  busy = value;
  for (const id of ['load', 'refresh', 'disconnect', 'execute', 'new-experiment', 'share-context-graph']) el(id).disabled = value;
}
function clearWorkspace() {
  stopRunPolling();
  clearTimeout(researchTimer); researchRevision = '';
  snapshot = null; experiments = []; selected = ''; cache = new Map();
  graphRequest++; graphInfo = null; graphError = ''; graphLoading = false;
  for (const nav of document.querySelectorAll('[data-workspace-nav]')) nav.hidden = true;
  el('workspace').hidden = true; el('session-tools').hidden = true; el('connection').hidden = !requireToken;
  clearAssetPreviews();
  for (const id of ['overview','description','assets','collaborators','graph-collaborators','checkpoints','records','publications','evaluation-evidence','experiment-picker']) el(id).replaceChildren();
  el('experiments').replaceChildren(node('p', 'Connect a participant to view its experiments.', 'small'));
  for (const id of ['operation-dialog', 'checkpoint-dialog', 'asset-detail-dialog', 'continuation-dialog', 'experiment-dialog', 'import-model-dialog', 'folder-dialog', 'share-dialog']) el(id).close();
  el('share-invite').value = ''; el('share-graph').value = ''; el('copy-share-invite').disabled = true;
  sharedRequest++; sharedPage = null; sharedOffset = 0; sharedLoading = false; sharedError = ''; sharedSelected = '';
  navigationScroll.experiments = 0; navigationScroll.shared = 0;
  el('shared-list').replaceChildren(); el('shared-status').textContent = ''; el('shared-graph').textContent = '';
  el('run-list').replaceChildren(); el('runs-status').textContent = '';
  el('experiment-form').reset(); experimentId = ''; el('continuation-form').reset(); continuationContext = null; continuationId = '';
  el('checkpoint-content').replaceChildren(); el('result').textContent = '';
}
async function load() {
  const generation = ++epoch;
  sharedRequest++; sharedPage = null; sharedLoading = false; sharedError = ''; graphRequest++; graphInfo = null; graphError = '';
  setBusy(true); el('status').className = ''; el('status').textContent = 'Reading participant records…';
  cache = new Map();
  try {
    const state = await get('/api/state');
    const research = await get('/api/research');
    const rows = state.records.map(row => ({ ...row, data: JSON.parse(row.record) }));
    const groups = new Map();
    const group = id => { if (!groups.has(id)) groups.set(id, { id, jobs: [], reports: [], proposals: [], errors: [] }); return groups.get(id); };
    for (const job of state.jobs) {
      const x = group(job.spec); x.jobs.push(job);
      if (job.report) { const report = await optionalArtifact(job.report, x.errors); if (report) x.reports.push({ id: job.report, data: report, source: 'Local evaluation' }); }
    }
    for (const row of rows) {
      if (row.data.kind === 'PatchProposal') group(row.data.artifact).proposals.push(row);
      if (row.data.kind === 'Evaluation') {
        const errors = [], report = await optionalArtifact(row.data.artifact, errors);
        row.errors = errors;
        if (report?.spec) {
          const x = group(report.spec);
          x.reports.push({ id: row.data.artifact, data: report, source: row.provenance, record: row });
        }
      }
    }
    for (const x of groups.values()) {
      x.spec = await optionalArtifact(x.id, x.errors);
      if (x.spec) {
        x.policy = await optionalArtifact(x.spec.policy, x.errors);
        x.patch = await optionalArtifact(x.spec.patch, x.errors);
        for (const id of x.spec.evidence || []) {
          const evidence = await optionalArtifact(id, x.errors);
          if (evidence?.schema === 'nc/weight-agent-session/v1') { x.session = evidence; break; }
        }
      }
      x.fixture = x.proposals.some(r => r.data.fixture) || rows.some(r => r.data.fixture && r.data.kind === 'ModelVersion' && r.data.artifact === x.spec?.base);
      x.report = x.reports.find(r => r.source === 'Local evaluation')?.data || x.reports[0]?.data;
      const model = x.session?.commitment?.model_source?.model;
      x.name = x.session?.commitment?.model_source?.experiment_name || (model ? model.split('/').at(-1) : evaluatorNames[x.spec?.evaluator] || x.spec?.evaluator || 'Unavailable evaluation');
      x.label = `${x.name} · ${short(x.id)}`;
    }
    if (generation !== epoch) return;
    snapshot = { ...state, records: rows }; experiments = [...research.experiments.map(researchExperiment), ...groups.values()];
    researchRevision = researchVersion(research);
    let requested = ''; try { requested = decodeURIComponent(location.hash.slice(1)); } catch {}
    if (!selected && experiments.some(x => x.id === requested)) selected = requested;
    if (!experiments.some(x => x.id === selected)) selected = experiments.find(x => x.research?.status === 'in_progress')?.id || experiments.find(x => !x.fixture)?.id || experiments[0]?.id || '';
    el('connection').hidden = true; el('workspace').hidden = false; el('session-tools').hidden = false;
    for (const nav of document.querySelectorAll('[data-workspace-nav]')) nav.hidden = false;
    renderNavigation(); renderCheckpoints(); renderRecords(); renderExperiment();
    renderWorkspaceView();
    el('status').textContent = 'Loaded from the local participant journal. Research rounds update automatically.';
    refreshRuns();
    scheduleResearchRefresh();
  } catch (e) {
    if (generation !== epoch) return;
    clearWorkspace(); token = ''; el('token').value = '';
    el('status').textContent = e.message; el('status').className = 'error';
    if (!requireToken) el('session-tools').hidden = false;
  } finally {
    if (generation === epoch) {
      setBusy(false);
      if (snapshot && workspaceView === 'shared') await refreshShared(sharedOffset);
    }
  }
}
function renderNavigation() {
  const list = el('experiments');
  navigationScroll[navigationView] = list.scrollTop;
  const focused = list.contains(document.activeElement) ? document.activeElement.dataset.experiment || document.activeElement.dataset.sharedRecord : null;
  navigationView = workspaceView;
  let focusTarget;
  list.replaceChildren(); el('experiment-picker').replaceChildren();
  el('experiments-heading').textContent = workspaceView === 'shared' ? 'SHARED EXPERIMENTS' : 'MY EXPERIMENTS';
  for (const x of experiments) {
    if (workspaceView === 'experiments') {
      const b = button(x.name, () => choose(x.id), 'experiment');
      b.setAttribute('aria-pressed', String(x.id === selected)); b.dataset.experiment = x.id;
      b.append(node('span', x.research ? `${researchStatus(x.research.status)} · ${x.research.rounds.length} rounds` : `${x.fixture ? 'Synthetic fixture · ' : ''}${x.report?.status || x.jobs[0]?.state || 'No evaluation'} · ${short(x.id)}`, 'small'));
      list.append(b);
      if (x.id === focused) focusTarget = b;
    }
    const option = node('option', x.label); option.value = x.id; el('experiment-picker').append(option);
  }
  if (workspaceView === 'shared') {
    for (const item of sharedPage?.records || []) {
      const x = experiments.find(x => x.id === item.record.artifact);
      const b = button(x?.name || `Shared experiment · ${short(item.record.artifact)}`, () => focusSharedExperiment(item.id), 'experiment');
      b.dataset.sharedRecord = item.id; b.setAttribute('aria-pressed', String(item.id === sharedSelected));
      b.append(node('span', `${item.downloaded ? 'Downloaded' : 'Available through DKG'} · ${short(item.id)}`, 'small'));
      list.append(b); if (item.id === focused) focusTarget = b;
    }
    if (!sharedPage?.records.length) list.append(node('p', sharedLoading ? 'Loading shared experiments…' : sharedError ? 'Shared experiments are unavailable. Refresh to retry.' : 'No shared experiments on this page.', 'small'));
    else if (sharedPage.offset || sharedPage.next_offset != null) list.append(node('p', 'This catalogue page. Use the page controls to browse more.', 'small'));
  } else if (!experiments.length) list.append(node('p', 'No evaluations yet. Import a checkpoint to get started.', 'small'));
  el('experiment-picker').value = selected;
  focusTarget?.focus({preventScroll:true});
  list.scrollTop = navigationScroll[workspaceView];
}
function routeHash(hash) { if (location.hash !== hash) history.pushState(null, '', hash); }
function renderWorkspaceView() {
  const shared = workspaceView === 'shared';
  el('experiment-view').hidden = shared; el('shared').hidden = !shared;
  el('breadcrumb').textContent = `Neural Commons / ${shared ? 'Shared experiments' : 'My experiments'}`;
  for (const b of document.querySelectorAll('[data-workspace]')) b.setAttribute('aria-pressed',String(b.dataset.workspace === workspaceView));
  if (shared) clearAssetPreviews();
}
function choose(id) {
  selected = id; workspaceView = 'experiments'; routeHash('#'+encodeURIComponent(id));
  renderNavigation(); renderExperiment(); showTab('overview'); renderWorkspaceView();
}
function openWorkspace(view) {
  workspaceView = view; routeHash(view === 'shared' ? '#/shared' : selected ? '#'+encodeURIComponent(selected) : '#');
  renderNavigation(); renderWorkspaceView();
  if (view === 'shared' && !sharedPage && !busy) refreshShared(0);
  if (view === 'experiments' && !el('assets').hidden) renderExperimentAssets(current());
}
function restoreWorkspaceRoute() {
  if (!snapshot) return;
  if (location.hash === '#/shared') { workspaceView = 'shared'; }
  else {
    let id = ''; try { id = decodeURIComponent(location.hash.slice(1)); } catch {}
    if (experiments.some(x=>x.id===id)) selected = id;
    workspaceView = 'experiments'; renderExperiment(); showTab('overview');
  }
  renderNavigation(); renderWorkspaceView();
  if (workspaceView === 'shared' && !sharedPage && !busy) refreshShared(0);
}
window.addEventListener('popstate',restoreWorkspaceRoute);
window.addEventListener('hashchange',restoreWorkspaceRoute);
function score(x) {
  const r = x.report;
  if (r?.scores) return { metric: r.scores.metric, base: r.scores.base, candidate: r.scores.candidate, direction: x.policy?.direction };
  if (Number.isFinite(r?.base_mse) && Number.isFinite(r?.candidate_mse)) return { metric: 'mean_squared_error/v1', base: r.base_mse, candidate: r.candidate_mse, direction: 'minimize' };
  return null;
}
function format(value, percent) { return percent ? `${(value * 100).toFixed(1)}%` : Number(value.toPrecision(5)).toString(); }
function metric(label, value, note, word = false) {
  const d = node('div', undefined, 'metric');
  d.append(node('span', label, 'small'), node('div', value, `value${word ? ' word' : ''}`), node('span', note, 'small')); return d;
}
function researchExperiment(research) {
  return { id: research.id, name: research.definition.name, label: research.definition.name,
    research, errors: [], jobs: [], reports: [], proposals: [] };
}
const researchVersion = data => JSON.stringify(data.experiments.map(x => [x.id, x.sequence, x.rounds.map(r => r.status)]));
function researchStatus(value) {
  return ({in_progress:'Research in progress', completed:'Completed', archived:'Archived', rejected:'Rejected',
    running:'Running', recorded:'Recorded', awaiting_review:'Awaiting review', failed:'Execution failed', interrupted:'Interrupted',
    accepted:'Accepted', not_selected:'Not selected', not_promoted:'Not promoted', inconclusive:'Inconclusive'})[value] || value;
}
function scheduleResearchRefresh() {
  clearTimeout(researchTimer);
  if (snapshot) researchTimer = setTimeout(refreshResearch, 5000);
}
async function refreshResearch() {
  if (!snapshot || researchFetching) return;
  if (busy || document.hidden) { scheduleResearchRefresh(); return; }
  researchFetching = true; const generation = epoch;
  try {
    const data = await get('/api/research');
    if (generation !== epoch) return;
    const revision = researchVersion(data);
    if (revision !== researchRevision) {
      const state = await get('/api/state');
      if (generation !== epoch) return;
      snapshot.checkpoints = state.checkpoints; snapshot.selected = state.selected;
      researchRevision = revision;
      const openRounds = [...document.querySelectorAll('.research-round[open]')].map(d => d.dataset.round);
      experiments = [...data.experiments.map(researchExperiment), ...experiments.filter(x => !x.research)];
      if (!experiments.some(x => x.id === selected)) selected = experiments[0]?.id || '';
      renderNavigation();
      renderCheckpoints();
      if (current()?.research) {
        renderExperiment();
        for (const d of document.querySelectorAll('.research-round')) if (openRounds.includes(d.dataset.round)) d.open = true;
      }
    }
    el('status').textContent = 'Loaded from the local participant journal. Research rounds update automatically.';
    el('status').className = '';
  } catch (error) {
    if (generation === epoch) { el('status').textContent = `Research updates unavailable. Showing the last loaded records. ${error.message}`; el('status').className = 'error'; }
  } finally { researchFetching = false; if (generation === epoch) scheduleResearchRefresh(); }
}
function researchMeasurements(parent, measurements) {
  if (!measurements?.length) return;
  const table = node('table'), head = node('tr'), body = node('tbody'), wrap = node('div', undefined, 'table-wrap');
  for (const label of ['Measurement', 'Data use', 'Parent', 'Candidate / result']) head.append(node('th',label));
  table.append(head,body);
  for (const m of measurements) {
    const r = node('tr');
    const count = value => Number.isFinite(value) && m.total ? `${value}/${m.total} · ${(100*value/m.total).toFixed(1)}%` : '—';
    r.append(node('td',m.label), node('td',m.split), node('td',count(m.parent_correct)), node('td',m.total ? count(m.correct) : Number.isFinite(m.value) ? format(m.value,false) : String(m.value ?? '—')));
    body.append(r);
  }
  wrap.append(table); parent.append(wrap);
}
function researchAttachments(parent, attachments) {
  for (const a of attachments || []) {
    const d = lazy(parent, a.label, async () => {
      const response = await fetch(`/api/artifact-metadata/${a.artifact}`, {headers:authHeaders(token),signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error(`Evidence unavailable (HTTP ${response.status})`);
      const bytes = await response.arrayBuffer(), root = node('div');
      const download = button('Download evidence', () => {
        const url = URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'})), link = node('a');
        link.href = url; link.download = a.label.replace(/[^a-z0-9._-]/gi,'_'); link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
      });
      root.append(node('p',`SHA-256 ${a.artifact}`,'id'),download);
      const text = new TextDecoder().decode(bytes);
      if (!text.includes('\u0000') && bytes.byteLength < 1024*1024) {
        let display = text; try { display = JSON.stringify(JSON.parse(text),null,2); } catch {}
        root.append(node('pre',display));
      } else root.append(node('p',`${bytes.byteLength.toLocaleString()} bytes · download to inspect`,'small'));
      return root;
    });
    d.classList.add('research-evidence');
  }
}
let assetView = {experiment:'', type:'all', split:'all', search:'', page:0};
let assetLoad = 0, assetAbort = null, assetPreviewRequest = 0, assetPreviewUrl = null;
const assetUrls = new Set();
const isArtifactId = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
function clearAssetPreviews() {
  assetLoad++; assetAbort?.abort(); assetAbort = null;
  for (const url of assetUrls) URL.revokeObjectURL(url);
  assetUrls.clear();
}
function trackedCheckpoints(x) {
  const result = new Map();
  if (x?.research) {
    for (const record of x.research.events) {
      const data = record.event.data;
      for (const cp of data.checkpoints || data.feedback?.checkpoints || []) if (isArtifactId(cp.checkpoint)) result.set(cp.checkpoint,cp);
    }
  } else for (const [label,key] of [['Base','base'],['Candidate','candidate']]) {
    const id=x?.spec?.[key]; if (isArtifactId(id)) result.set(id,{label,checkpoint:id,parent_checkpoint:key==='candidate'?x.spec.base:null});
  }
  return [...result.values()];
}
function sourceLink(source) {
  try {
    const url = new URL(source.url); if (!['http:','https:'].includes(url.protocol)) return null;
    const link = node('a',source.label || url.hostname); link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';return link;
  } catch { return null; }
}
function renderExperimentContent(x) {
  if (assetView.experiment !== x?.id) {
    assetView = {experiment:x?.id || '',type:'all',split:'all',search:'',page:0};
    el('asset-detail-dialog').close();
  }
  const root=el('description');root.replaceChildren(node('h2','About this experiment'));
  if (!x) {root.append(node('p','Choose an experiment to see its description.','empty'));renderExperimentAssets(x);return;}
  const definition=x.research?.definition || {}, dataset=definition.dataset || {};
  let description=typeof definition.description==='string' ? {summary:definition.description} : definition.description || {};
  for (const record of x.research?.events || []) {
    const event=record.event, value=event.data.description;
    if (!event.round && value) description={...description,...(typeof value==='string'?{summary:value}:value)};
  }
  const intro=description.summary || definition.objective || x.patch?.hypothesis;
  root.append(node('p',intro || 'No description has been recorded for this experiment yet.','description-intro'));
  const section=(title,value)=>{
    if (!value) return;
    const block=node('section',undefined,'description-section');block.append(node('h3',title));
    if (Array.isArray(value)) {const list=node('ul');for(const item of value)if(typeof item==='string')list.append(node('li',item));block.append(list);}
    else if (typeof value==='string') block.append(node('p',value));
    else return;
    root.append(block);
  };
  if (description.summary && definition.objective) section('Goal',definition.objective);
  section('Model',definition.model || x.session?.commitment?.model_source?.model);
  section('Method',description.method || dataset.method);
  section('Dataset',description.dataset || definition.scope);
  section('Evaluation',description.evaluation);
  let limitations=description.limitations;
  if (!limitations) for(const r of x.research?.events || []) if(!r.event.round && r.event.data.limitations) limitations=r.event.data.limitations;
  section('Limitations',limitations);
  const sources=description.sources || (dataset.source?[{label:'Dataset source',url:dataset.source}]:[]);
  const links=(Array.isArray(sources)?sources:[]).filter(source=>source && typeof source==='object').map(sourceLink).filter(Boolean);
  if(links.length){const block=node('section',undefined,'description-section');block.append(node('h3','Sources'));for(const link of links){const p=node('p');p.append(link);block.append(p);}root.append(block);}
  if(definition.dataset)exact(root,'Protocol recorded at experiment registration',definition.dataset);
  renderExperimentAssets(x);
}
function experimentAssets(x) {
  const assets=new Map();
  const add=(attachment,context,metadata={})=>{
    if(!isArtifactId(attachment.artifact))return;
    const previous=assets.get(attachment.artifact),label=attachment.label || short(attachment.artifact);
    const item={...(previous || {}),...metadata,artifact:attachment.artifact,label:metadata.label || previous?.label || label,
      contexts:[...new Set([...(previous?.contexts || []),context])],aliases:[...new Set([...(previous?.aliases || []),label])]};
    item.type=/\.(png|jpe?g|webp|gif)$/i.test(item.filename || item.label) || metadata.kind==='image' || previous?.type==='image' ? 'image':'document';
    assets.set(item.artifact,item);
  };
  if(x?.research){
    const rounds=new Map(x.research.rounds.map(r=>[r.id,r.definition.label]));
    for(const record of x.research.events){
      const e=record.event,metadata=Array.isArray(e.data.assets)?e.data.assets.filter(m=>m && typeof m==='object'):[];
      for(const a of e.attachments || [])add(a,e.round?rounds.get(e.round) || e.round:'Experiment',metadata.find(m=>m.artifact===a.artifact) || {});
    }
  }else if(x){
    for(const [label,artifact] of [['Evaluation specification.json',x.id],['Dataset.json',x.spec?.dataset],['Policy.json',x.spec?.policy],['Weight patch.json',x.spec?.patch]])add({label,artifact},'Evaluation');
    for(const id of x.spec?.evidence || [])add({label:`Evidence ${short(id)}.json`,artifact:id},'Evaluation');
    for(const report of x.reports || [])add({label:`${report.source} ${short(report.id)}.json`,artifact:report.id},'Evaluation');
  }
  return [...assets.values()].sort((a,b)=>(a.type===b.type?0:a.type==='image'?-1:1) || a.label.localeCompare(b.label));
}
async function readAssetBytes(a,signal) {
  if(!isArtifactId(a.artifact))throw new Error('Invalid asset identity');
  for(let attempt=0;attempt<4;attempt++){
    const timeout=AbortSignal.timeout(15000);
    const response=await fetch(`/api/artifact-metadata/${a.artifact}`,{headers:authHeaders(token),signal:signal?AbortSignal.any([signal,timeout]):timeout});
    if(response.ok)return response.arrayBuffer();
    if(response.status!==503 || attempt===3)throw new Error(`Asset unavailable (HTTP ${response.status})`);
    await new Promise(resolve=>setTimeout(resolve,150*(attempt+1)));if(signal?.aborted)throw new Error('Preview cancelled');
  }
}
function imageMime(bytes) {
  const b=new Uint8Array(bytes,0,Math.min(bytes.byteLength,12));
  if(b[0]===255 && b[1]===216 && b[2]===255)return 'image/jpeg';
  if([137,80,78,71,13,10,26,10].every((v,i)=>b[i]===v))return 'image/png';
  const text=String.fromCharCode(...b);
  if(text.startsWith('GIF87a') || text.startsWith('GIF89a'))return 'image/gif';
  if(text.startsWith('RIFF') && text.slice(8,12)==='WEBP')return 'image/webp';
  return null;
}
function assetDownloadButton(a,bytes) {
  const b=button('Download',async()=>{
    b.disabled=true;
    try{
      const data=bytes || await readAssetBytes(a),url=URL.createObjectURL(new Blob([data],{type:'application/octet-stream'})),link=node('a');
      link.href=url;link.download=(a.filename || a.label).replace(/[^a-z0-9._-]/gi,'_');link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);b.textContent='Download';
    }catch(error){b.textContent='Retry download';b.title=error.message;}
    finally{b.disabled=false;}
  });return b;
}
async function openExperimentAsset(a) {
  const dialog=el('asset-detail-dialog'),root=el('asset-detail-content'),request=++assetPreviewRequest;
  if(assetPreviewUrl)URL.revokeObjectURL(assetPreviewUrl);assetPreviewUrl=null;
  el('asset-detail-title').textContent=a.label;root.replaceChildren(node('p','Loading asset…','small'));dialog.showModal();
  try{
    const bytes=await readAssetBytes(a);if(request!==assetPreviewRequest || !dialog.open)return;
    root.replaceChildren();const mime=imageMime(bytes);
    if(mime){const img=node('img');img.alt=a.caption || a.label;assetPreviewUrl=URL.createObjectURL(new Blob([bytes],{type:mime}));img.src=assetPreviewUrl;root.append(img);}
    else if(bytes.byteLength<1024*1024){
      try{let text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);if(text.includes('\u0000'))throw new Error('Binary asset');try{text=JSON.stringify(JSON.parse(text),null,2);}catch{}root.append(node('pre',text));}
      catch{root.append(node('p','Download this file to inspect its contents.','small'));}
    }else root.append(node('p','Download this file to inspect its contents.','small'));
    if(a.caption)root.append(node('p',a.caption));
    root.append(node('p',`${bytes.byteLength.toLocaleString()} bytes · SHA-256 ${a.artifact}`,'id'));
    const source=a.source_url && sourceLink({url:a.source_url,label:a.source || 'Original source'});if(source){const p=node('p');p.append(source);root.append(p);}
    const actions=node('div',undefined,'toolbar');actions.append(assetDownloadButton(a,bytes));root.append(actions);
    exact(root,'Asset details',a);
  }catch(error){if(request===assetPreviewRequest && dialog.open)root.replaceChildren(node('p',error.message,'notice'),button('Retry',()=>{dialog.close();openExperimentAsset(a);}));}
}
el('asset-detail-dialog').addEventListener('close',()=>{assetPreviewRequest++;if(assetPreviewUrl)URL.revokeObjectURL(assetPreviewUrl);assetPreviewUrl=null;});
function renderExperimentAssets(x) {
  clearAssetPreviews();const root=el('assets');root.replaceChildren(node('h2','Experiment assets'));
  if(!x){root.append(node('p','Choose an experiment to see its assets.','empty'));return;}
  const assets=experimentAssets(x),photos=assets.filter(a=>a.type==='image').length;
  root.append(node('p',`${photos} image${photos===1?'':'s'} · ${assets.length-photos} supporting files · duplicate files appear once`,'small'));
  const checkpoints=trackedCheckpoints(x);
  if(checkpoints.length){const models=node('div',undefined,'asset-models');models.append(node('h3','Model checkpoints'));const links=node('div',undefined,'toolbar');for(const cp of checkpoints)links.append(button(cp.label,()=>inspectCheckpoint(cp.checkpoint,cp.parent_checkpoint?{base:cp.parent_checkpoint,candidate:cp.checkpoint}:null)));models.append(links);root.append(models);}
  if(!assets.length){root.append(node('p','No files have been attached to this experiment yet.','empty'));return;}
  const controls=node('div',undefined,'asset-controls'),search=node('input'),type=node('select'),split=node('select');
  search.type='search';search.placeholder='Search filenames, labels or rounds';search.value=assetView.search;
  for(const [value,label] of [['all','All assets'],['image','Images'],['document','Supporting files']]){const option=node('option',label);option.value=value;type.append(option);}type.value=assetView.type;
  for(const value of ['all',...[...new Set(assets.map(a=>a.split).filter(v=>typeof v==='string'))].sort()]){const option=node('option',value==='all'?'All data splits':value[0].toUpperCase()+value.slice(1));option.value=value;split.append(option);}split.value=assetView.split;if(!split.value){split.value='all';assetView.split='all';}
  for(const [label,input,key] of [['Search assets',search,'search'],['Asset type',type,'type'],['Data split',split,'split']]){const field=node('div'),l=node('label',label);input.id='asset-filter-'+key;l.htmlFor=input.id;field.append(l,input);controls.append(field);}root.append(controls);
  const status=node('p',undefined,'small'),grid=node('div',undefined,'asset-grid'),pagination=node('div',undefined,'toolbar asset-pagination');status.setAttribute('role','status');root.append(status,grid,pagination);
  function draw(){
    clearAssetPreviews();const generation=assetLoad;grid.replaceChildren();pagination.replaceChildren();
    const query=assetView.search.toLowerCase().trim();
    const filtered=assets.filter(a=>(assetView.type==='all' || a.type===assetView.type) && (assetView.split==='all' || a.split===assetView.split) && (!query || [a.label,a.caption,a.target_label,...a.contexts,...a.aliases].join(' ').toLowerCase().includes(query)));
    const size=12,pages=Math.max(1,Math.ceil(filtered.length/size));assetView.page=Math.min(assetView.page,pages-1);
    const start=assetView.page*size,items=filtered.slice(start,start+size),images=[];
    status.textContent=filtered.length?`${start+1}–${start+items.length} of ${filtered.length} assets`:'No assets match these filters.';
    for(const a of items){
      const card=node('article',undefined,'asset-card'),preview=button('',()=>openExperimentAsset(a),'asset-preview');preview.setAttribute('aria-label',`Preview ${a.label}`);
      const extension=/\.([a-z0-9]{1,8})$/i.exec(a.filename || a.label);
      const placeholder=node('span',a.type==='image'?'Loading preview…':extension?extension[1].toUpperCase():'FILE');preview.append(placeholder);
      if(a.type==='image'){const img=node('img');img.alt=a.caption || a.label;img.hidden=true;preview.append(img);images.push({a,img,placeholder});}
      const body=node('div',undefined,'asset-body');body.append(node('h3',a.label));const tags=node('div',undefined,'asset-tags');for(const label of [a.split,a.target_label])if(label)tags.append(node('span',label,'badge'));body.append(tags);
      if(a.caption)body.append(node('p',a.caption,'small'));
      body.append(node('p',a.contexts.length===1?a.contexts[0]:`${a.contexts.length} recorded contexts`,'small'));
      const actions=node('div',undefined,'toolbar');actions.append(button('Preview',()=>openExperimentAsset(a)),assetDownloadButton(a));body.append(actions);card.append(preview,body);grid.append(card);
    }
    const previous=button('Previous',()=>{assetView.page--;draw();}),next=button('Next',()=>{assetView.page++;draw();});previous.disabled=assetView.page===0;next.disabled=assetView.page>=pages-1;
    pagination.append(previous,node('span',`Page ${assetView.page+1} of ${pages}`,'small'),next);
    if(root.hidden)return;
    assetAbort=new AbortController();const signal=assetAbort.signal;
    // One image at a time leaves the bounded artifact service free for app updates.
    (async()=>{for(const {a,img,placeholder} of images){
      if(generation!==assetLoad)return;
      try{const bytes=await readAssetBytes(a,signal);if(generation!==assetLoad)return;const mime=imageMime(bytes);if(!mime)throw new Error('No supported image preview');
        const url=URL.createObjectURL(new Blob([bytes],{type:mime}));assetUrls.add(url);img.onload=()=>{if(generation===assetLoad){img.hidden=false;placeholder.hidden=true;}};img.onerror=()=>{placeholder.textContent='Preview unavailable';};img.src=url;
      }catch{if(generation===assetLoad)placeholder.textContent='Preview unavailable';}
    }})();
  }
  for(const [input,key] of [[search,'search'],[type,'type'],[split,'split']])input.addEventListener(input===search?'input':'change',()=>{assetView[key]=input.value;assetView.page=0;draw();});
  draw();
}
function researchTrainingEpochs(round) {
  const epochs = new Map();
  for (const record of round.events || []) {
    const value = record.event?.data?.training_progress;
    if (!value || !Number.isInteger(value.epoch) || !Number.isInteger(value.epochs)
        || value.epoch < 1 || value.epoch > value.epochs
        || !Number.isFinite(value.class_loss) || value.class_loss<0
        || ['box_loss','dfl_loss'].some(key=>key in value && (!Number.isFinite(value[key]) || value[key]<0))) continue;
    epochs.set(value.epoch, value);
  }
  return [...epochs.values()].sort((a,b)=>a.epoch-b.epoch);
}
function researchTraining(round) {
  const panel=node('section',undefined,'panel training-progress');
  panel.append(node('h2','Training progress'),node('p',round.definition.label,'small'));
  const epochs=researchTrainingEpochs(round), latest=epochs.at(-1);
  if (!latest) { panel.append(node('p',round.status==='running' ? 'Waiting for the first completed epoch.' : 'No completed epochs recorded.','notice'));return panel; }
  const summary=node('p',`Epoch ${latest.epoch}/${latest.epochs} · ${round.status==='running'?'training worker running':researchStatus(round.status)}`,'training-summary');
  summary.setAttribute('aria-live','polite');panel.append(summary);
  const progress=node('progress');progress.max=latest.epochs;progress.value=latest.epoch;
  progress.setAttribute('aria-label',`${latest.epoch} of ${latest.epochs} epochs completed`);panel.append(progress);
  const classLabel=latest.loss_label || (/^Weighted (?:binary cross-entropy|dog BCE)/.test(latest.loss_definition||'')?'Weighted BCE':'Class');
  const candidates=[['box_loss','Box','var(--accent)'],['class_loss',classLabel,'var(--warning)'],['dfl_loss','DFL','var(--bad)']];
  const series=candidates.filter(([key])=>epochs.every(e=>Number.isFinite(e[key])));
  const frame=node('div',undefined,'training-loss');
  const maximum=Math.max(1,Math.ceil(Math.max(...epochs.flatMap(e=>series.map(([key])=>e[key])))*2.2)/2);
  const ticks=node('div',undefined,'training-y');
  for (const value of [maximum,maximum/2,0])ticks.append(node('span',value.toFixed(1)));
  const plot=node('div',undefined,'training-plot'), ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 640 220');svg.setAttribute('preserveAspectRatio','none');
  svg.setAttribute('role','img');svg.setAttribute('aria-label',`Actual training loss from epoch ${epochs[0].epoch} to ${latest.epoch}. ${series.map(([key,label])=>`${label} ${latest[key].toFixed(4)}`).join(', ')}.`);
  const first=epochs[0].epoch, range=Math.max(1,latest.epoch-first);
  for (const [key,,color] of series) {
    const path=document.createElementNS(ns,'path');
    path.setAttribute('d',epochs.map((e,i)=>`${i?'L':'M'}${((e.epoch-first)/range*632+4).toFixed(2)},${(214-e[key]/maximum*208).toFixed(2)}`).join(' '));
    path.setAttribute('fill','none');path.setAttribute('stroke',color);path.setAttribute('stroke-width','2');path.setAttribute('vector-effect','non-scaling-stroke');svg.append(path);
    if (epochs.length===1) {
      const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx','4');dot.setAttribute('cy',String(214-latest[key]/maximum*208));dot.setAttribute('r','3');dot.setAttribute('fill',color);svg.append(dot);
    }
  }
  plot.append(svg);const x=node('div',undefined,'training-x');
  x.append(node('span',`Epoch ${first}`),node('span',`Epoch ${latest.epoch}`));plot.append(x);frame.append(ticks,plot);panel.append(frame);
  const legend=node('div',undefined,'training-legend');
  for (const [key,label,color] of series) { const item=node('span',`${label}: ${latest[key].toFixed(4)}`);item.style.color=color;legend.append(item); }
  panel.append(legend,node('p','Recorded completed epochs · refreshes automatically with the participant journal. Final evaluation is separate.','small'));
  if(latest.loss_definition)panel.append(node('p',latest.loss_definition,'small'));
  return panel;
}
function renderResearchExperiment(x) {
  const research = x.research, definition = research.definition, root = el('overview'), evidence = el('evaluation-evidence');
  el('experiment-title').textContent = definition.name;
  el('experiment-subtitle').textContent = `${definition.model} · ${definition.controller || 'Conversation agent'} · ${researchStatus(research.status)}`;
  el('open-continuation').disabled = true;
  el('open-continuation').title = 'Research rounds are tracked here; a controller continuation requires a compatible published evaluation.';
  const running = research.rounds.filter(r=>r.status==='running').length;
  const finals = research.rounds.filter(r=>r.definition.kind==='final_evaluation' && ['completed','awaiting_review'].includes(r.status));
  const metrics=node('div',undefined,'metrics');
  metrics.append(metric('Recorded rounds',String(research.rounds.length),'Includes unsuccessful attempts'),
    metric('Executing now',String(running),running ? 'Worker lease is active' : 'No numerical command executing'),
    metric('Final evaluation',finals.length ? 'Recorded' : 'Not run',finals.length ? `${finals.length} recorded final evaluation${finals.length===1?'':'s'}` : 'Selection results are exploratory',true));
  const latest=research.rounds.at(-1);
  const activity=research.status==='in_progress' && latest ? `${latest.definition.label}: ${latest.status==='running' ? 'Numerical command is running.' : latest.decision?.reason || latest.execution_note || latest.result?.summary || 'Round registered.'}` : research.summary;
  root.append(metrics,node('p',definition.objective,'research-objective'),node('div',activity,'notice'));
  const training=[...research.rounds].reverse().find(r=>r.definition.kind==='gradient_fine_tuning' || researchTrainingEpochs(r).length);
  if (training) root.append(researchTraining(training));
  if (definition.scope) root.append(node('p',definition.scope,'small research-scope'));
  if (definition.dataset) exact(root,'Dataset, split roles & label quality',definition.dataset);
  if (definition.parent_sha256) root.append(node('p',`Inherited weights · ${definition.parent_sha256}`,'id'));
  const checkpoints = new Map();
  for (const r of research.rounds) for (const cp of r.result?.checkpoints || r.result?.feedback?.checkpoints || []) checkpoints.set(cp.checkpoint,cp);
  for (const event of research.events) for (const cp of event.event.data.checkpoints || []) checkpoints.set(cp.checkpoint,cp);
  if (checkpoints.size) {
    const versions=node('div',undefined,'research-checkpoints panel'); versions.append(node('h2','Tracked model versions'));
    for (const cp of checkpoints.values()) {
      const row=node('div',undefined,'section-head');
      const label=node('div');label.append(node('strong',cp.label),node('p',`Weights ${cp.sha256}`,'id'));
      row.append(label,button(`Inspect ${cp.label}`,()=>inspectCheckpoint(cp.checkpoint,cp.parent_checkpoint ? {base:cp.parent_checkpoint,candidate:cp.checkpoint} : null)));
      versions.append(row);
    }
    root.append(versions);
  }
  const head=node('div',undefined,'section-head'); head.append(node('h2','Round history'),node('span','Newest first · every attempt retained','small'));root.append(head);
  if (!research.rounds.length) root.append(node('p','Experiment registered. No numerical rounds have started.','empty'));
  for (const [index,r] of [...research.rounds].reverse().entries()) {
    const d=node('details',undefined,'research-round'), summary=node('summary'), title=node('div'), verdict=r.decision?.verdict || r.status;
    d.dataset.round=r.id; d.open=index===0;
    title.append(node('strong',r.definition.label),node('span',`${r.definition.participant ? r.definition.participant+' · ' : ''}${r.definition.kind.replaceAll('_',' ')}${r.historical ? ' · Imported history' : ''}`,'small'));
    summary.append(title,node('span',researchStatus(verdict),`badge ${verdict==='accepted'?'good':verdict==='rejected' || verdict==='failed'?'bad':''}`));d.append(summary);
    d.append(node('p',r.definition.hypothesis,'research-hypothesis'));
    if (r.definition.parent_sha256) d.append(node('p',`Parent weights ${r.definition.parent_sha256}`,'id'));
    if (r.result?.candidate_sha256) d.append(node('p',`Candidate weights ${r.result.candidate_sha256}`,'id'));
    if (r.result?.replacement_sha256) d.append(node('p',`Weight replacement ${r.result.replacement_sha256}`,'id'));
    if (r.result?.summary) d.append(node('p',r.result.summary));
    if (r.execution_note) d.append(node('p',r.execution_note,'notice'));
    if (r.decision) d.append(node('p',r.decision.reason,`notice ${verdict==='accepted'?'good':verdict==='rejected'?'bad':''}`));
    researchMeasurements(d,r.result?.measurements);
    if (r.result?.changed_tensors?.length) exact(d,'Changed tensors',r.result.changed_tensors);
    if (r.definition.operation) exact(d,'Proposed operation',r.definition.operation);
    if (r.result?.feedback) exact(d,'Numerical feedback',r.result.feedback);
    for (const event of r.events) researchAttachments(d,event.event.attachments);
    const date=r.occurred_at ? new Date(r.occurred_at*1000).toLocaleString() : new Date(r.created_at).toLocaleString();
    d.append(node('p',`${r.historical?'Original evidence time':'Registered'}: ${date} · ${r.id}`,'small'));
    root.append(d);
  }
  evidence.append(node('h2','Experiment evidence & decision history'));
  exact(evidence,'Experiment definition',definition);
  for (const record of research.events) {
    if (record.event.round) continue;
    exact(evidence,`${record.event.kind} · ${record.recorded_at}`,record.event.data);
    researchAttachments(evidence,record.event.attachments);
  }
  exact(evidence,'Complete append-only history',research.events);
}
function renderExperiment() {
  const x = current(), root = el('overview'); root.replaceChildren(); el('evaluation-evidence').replaceChildren();
  renderExperimentContent(x);
  renderExperimentCollaborators(x);
  if (x?.research) { renderResearchExperiment(x); return; }
  el('experiment-title').textContent = x?.name || 'Your participant workspace';
  el('experiment-subtitle').textContent = x ? `${x.fixture ? 'Synthetic fixture · ' : ''}${x.spec?.backend?.split('/')[0] || 'Backend unavailable'} · Evaluation ${short(x.id)}` : 'Import checkpoints and evaluate a proposed change to begin.';
  el('open-continuation').disabled = !continuationParent(x);
  el('open-continuation').title = continuationParent(x) ? 'Continue from this exact candidate' : 'Requires a recorded proposal, weight-agent session and a passing parent report';
  if (!x) { root.append(node('p', 'No evaluation records in this participant journal.', 'empty')); return; }
  if (x.errors.length) root.append(node('div', `Some evidence is unavailable. ${x.errors.join(' · ')}`, 'notice'));
  const s = score(x), valid = s && Number.isFinite(s.base) && Number.isFinite(s.candidate);
  const percent = valid && /^(guarded_)?accuracy\/v1$/.test(s.metric);
  const status = x.report?.status || x.jobs[0]?.state || 'Not evaluated';
  const metrics = node('div', undefined, 'metrics');
  let delta = '—';
  if (valid) { const v = s.candidate - s.base; delta = `${v > 0 ? '+' : ''}${format(percent ? v * 100 : v, false)}${percent ? ' pp' : ''}`; }
  metrics.append(metric('Candidate score', valid ? format(s.candidate, percent) : '—', metricNames[s?.metric] || s?.metric || 'No score available'), metric('Change from base', delta, s?.direction === 'minimize' ? 'Lower is better' : s?.direction === 'maximize' ? 'Higher is better' : 'Candidate minus base'), metric('Evaluation', status, 'Recorded report verdict', true));
  metrics.lastChild.querySelector('.value').classList.add(verdictClass(status));
  root.append(metrics);
  if (valid) {
    const panel = node('div', undefined, 'panel'), head = node('div', undefined, 'section-head');
    head.append(node('h2', 'Compare this change'), node('span', metricNames[s.metric] || s.metric, 'badge')); panel.append(head);
    const chart = node('div', undefined, 'comparison'); chart.setAttribute('role', 'img'); chart.setAttribute('aria-label', `Base ${format(s.base, percent)}, candidate ${format(s.candidate, percent)}. ${s.metric}`);
    const low = Math.min(0, s.base, s.candidate), high = Math.max(percent ? 1 : 0, s.base, s.candidate), span = high - low || 1;
    for (const [label, value] of [['Base', s.base], ['Candidate', s.candidate]]) {
      const row = node('div', undefined, 'bar-row'), track = node('div', undefined, 'track'), fill = node('div', undefined, 'fill');
      fill.style.width = `${Math.max(0, Math.min(100, (value - low) / span * 100))}%`; track.append(fill);
      if (label === 'Candidate' && status !== 'passed') fill.style.background = status === 'failed' ? 'var(--bad)' : 'var(--muted)';
      row.append(node('span', label), track, node('span', format(value, percent), 'bar-value')); chart.append(row);
    }
    panel.append(chart, node('p', `Same evaluation specification · dataset ${short(x.spec?.dataset)} · seed ${x.spec?.seed ?? 'unavailable'}${low < 0 ? ` · bar scale starts at ${low}` : ''}`, 'note')); root.append(panel);
  } else root.append(node('p', x.report?.error || 'This evaluation has no recorded scores yet.', 'notice'));
  if (x.spec) {
    const head = node('div', undefined, 'section-head'); head.append(node('h2', 'From base to candidate'), button('Explore versions →', () => showTab('versions'), 'quiet')); root.append(head);
    const chain = node('div', undefined, 'lineage');
    for (const [label, id] of [['Base', x.spec.base], ['Candidate', x.spec.candidate]]) {
      if (label === 'Candidate') chain.append(node('span', '→', 'arrow'));
      const b = button('', () => inspectCheckpoint(id), `checkpoint ${label.toLowerCase()}`), heading = node('div', undefined, 'row');
      heading.append(node('strong', label), node('span', snapshot.selected?.checkpoint === id ? 'SELECTED' : 'CHECKPOINT', 'badge'));
      b.append(heading, node('p', label === 'Candidate' ? x.session?.commitment?.controller || 'Proposed change' : 'Inherited checkpoint'), node('p', short(id), 'id'), node('span', 'Inspect tensors & evidence ↗', 'small')); chain.append(b);
    }
    root.append(chain);
    if (x.patch?.hypothesis) { const h = node('div', undefined, 'section-head'); h.append(node('h2', 'What changed')); root.append(h, node('p', x.patch.hypothesis, 'muted')); }
    if (x.session) {
      const c = x.session.commitment || {};
      root.append(node('p', `${x.session.changed_parameters ?? 'Unknown'} parameters changed · gradients: ${x.session.gradients_used ? 'yes' : 'no'}`, 'small'));
      if (c.parent_proposal) root.append(node('p', `Continuation of proposal ${short(c.parent_proposal)} · inherited checkpoint ${short(c.parent_checkpoint)}`, 'id'));
    }
    const policy = node('div', undefined, `notice ${verdictClass(status)}`);
    policy.append(node('strong', `Recorded verdict: ${status}. `));
    policy.append(node('span', x.policy?.min_improvement !== undefined ? `Policy requires improvement of ${x.policy.min_improvement} in metric units. This view uses the policy bound to this evaluation.` : 'Inspect the bound policy for acceptance criteria.'));
    root.append(policy, button('Inspect policy & reproduction evidence →', () => showTab('evidence'), 'quiet'));
  }
  renderEvaluationEvidence(x);
}
function renderEvaluationEvidence(x) {
  const root = el('evaluation-evidence'); root.append(node('h2', 'Selected evaluation'));
  if (x.spec) exact(root, 'Evaluation specification', x.spec);
  if (x.policy) exact(root, 'Bound acceptance policy', x.policy);
  if (x.patch) exact(root, 'Patch & tensor operations', x.patch);
  if (x.session) exact(root, 'Controller session & continuation', x.session);
  for (const report of x.reports) {
    const d = exact(root, `${report.source} · ${report.data.status} · ${short(report.id)}`, report);
    if (report.data.outputs) lazy(d, 'Evaluator output', async () => node('pre', JSON.stringify(await artifact(report.data.outputs), null, 2)));
  }
  exact(root, 'Local evaluation history', snapshot.job_events.filter(e => x.jobs.some(j => j.id === e.job_id)));
  if (!x.reports.some(r => r.record)) root.append(node('p', 'No readable shared evaluation report for this specification in this journal.', 'small'));
}
function renderCheckpoints() {
  const root = el('checkpoints'); root.replaceChildren();
  el('selection').textContent = snapshot.selected ? `Selected version: ${snapshot.selected.checkpoint}` : 'No version selected.';
  if (!snapshot.checkpoints.length) { root.append(node('p', 'No checkpoints imported yet.', 'empty')); return; }
  const wrap = node('div', undefined, 'table-wrap'), table = node('table'), head = node('thead'), hr = node('tr');
  for (const title of ['Checkpoint', 'Use', '']) hr.append(node('th', title)); head.append(hr); table.append(head);
  const body = node('tbody');
  for (const row of snapshot.checkpoints) {
    const tr = node('tr'), name = node('td'), use = node('td'), controls = node('td');
    name.append(node('span', short(row.id), 'id'));
    const count = experiments.filter(x => x.spec?.base === row.id || x.spec?.candidate === row.id).length;
    use.textContent = snapshot.selected?.checkpoint === row.id ? 'Selected locally' : `${count} evaluation${count === 1 ? '' : 's'}`;
    controls.append(button('Inspect ↗', () => inspectCheckpoint(row.id), 'quiet')); tr.append(name, use, controls); body.append(tr);
  }
  table.append(body); wrap.append(table); root.append(wrap);
}
async function inspectCheckpoint(id, comparison = null) {
  const request = ++checkpointRequest;
  const root = el('checkpoint-content'), dialog = el('checkpoint-dialog');
  root.replaceChildren(node('p', id, 'id'), node('p', 'Reading checkpoint…', 'small')); dialog.showModal();
  const generation = epoch;
  try {
    const m = await artifact(id); if (generation !== epoch || request !== checkpointRequest || !dialog.open) return;
    root.replaceChildren(node('p', id, 'id'));
    const related = comparison ? {spec:comparison} : [current(), ...experiments].find(x => x?.spec && (x.spec.candidate === id || x.spec.base === id));
    let diff = null;
    if (related) {
      const loading=node('p','Comparing saved weights with the experiment base…','small');root.append(loading);
      try { diff=await get('/api/checkpoint-diff?'+new URLSearchParams({base:related.spec.base,candidate:related.spec.candidate})); }
      catch(error) { if(generation===epoch && request===checkpointRequest) root.append(node('p','Weight comparison unavailable. '+error.message,'notice')); }
      loading.remove();
      if(generation!==epoch || request!==checkpointRequest || !dialog.open)return;
    }
    if(!related)root.append(node('p','No experiment comparison recorded for this checkpoint. Showing its structure.','small'));
    const wrap = node('div', undefined, 'table-wrap'), table = node('table'), header = node('tr');
    table.className='tensor-table';
    for (const title of ['Tensor', 'Shape', 'Type', ...(diff ? ['Changed values'] : [])]) header.append(node('th', title)); table.append(header);
    const body=node('tbody'), count=node('p', '', 'small tensor-count');table.append(body);
    const byName=new Map((diff?.tensors || []).map(t=>[t.name,t]));
    let visible=m.tensors || [], changedOnly=Boolean(diff);
    const details=diff ? weightChangeDetails(diff,()=>generation===epoch && request===checkpointRequest && dialog.open) : null;
    const renderRows=tensors=>{visible=tensors;body.replaceChildren();const rows=tensors.filter(t=>!changedOnly || byName.get(t.name)?.changed>0);for(const tensor of rows){const row=node('tr');for(const value of [tensor.name,JSON.stringify(tensor.shape),tensor.dtype,...(diff?[String(byName.get(tensor.name)?.changed || 0)]:[])])row.append(node('td',value));body.append(row);}count.textContent=`Showing ${rows.length} of ${(m.tensors || []).length} tensors`;};
    root.append(checkpointMap(m,renderRows,diff));
    if(diff){
      root.append(node('p',`Base ${short(diff.base)} → candidate ${short(diff.candidate)} · ${diff.changed.toLocaleString()} changed values across ${diff.changed_tensors} tensors`,'small'));
      const label=node('label',undefined,'diff-toggle'),toggle=node('input');toggle.type='checkbox';toggle.checked=true;toggle.addEventListener('change',()=>{changedOnly=toggle.checked;renderRows(visible);});label.append(toggle,document.createTextNode(' Changed tensors only'));root.append(label);
    }
    root.append(count);renderRows(m.tensors || []);
    if(details)root.append(details);
    wrap.append(table); root.append(wrap); exact(root, 'Exact checkpoint manifest', m);
    const actions = node('div', undefined, 'toolbar');
    actions.append(button('Select version', () => { dialog.close(); openOperation('select', { checkpoint: id }); }, 'primary'), button('Export checkpoint', () => { dialog.close(); openOperation('export', { checkpoint: id }); })); root.append(actions);
  } catch (e) { if (generation === epoch && request === checkpointRequest) root.append(node('p', e.message, 'notice')); }
}
function renderRecords() {
  el('records').replaceChildren(); el('publications').replaceChildren();
  for (const row of snapshot.records) {
    lazy(el('records'), `${row.data.kind} · ${row.provenance}${row.data.fixture ? ' · SYNTHETIC FIXTURE' : ''} · ${short(row.id)}`, async () => {
      const root = node('div'), payload = await artifact(row.data.artifact);
      root.append(node('p', `Author: ${row.data.author}`, 'id')); exact(root, 'Record envelope', row.data); exact(root, 'Artifact', payload);
      if (row.data.kind === 'PatchProposal') {
        exact(root, 'Patch', await artifact(payload.patch));
        for (const id of payload.evidence || []) lazy(root, `Controller evidence ${short(id)}`, async () => node('pre', JSON.stringify(await artifact(id), null, 2)));
        root.append(button('Reproduce proposal', () => openOperation('reproduce', { record: row.id })));
      }
      if (row.data.kind === 'Evaluation' && payload.outputs) lazy(root, 'Evaluator output', async () => node('pre', JSON.stringify(await artifact(payload.outputs), null, 2)));
      return root;
    });
  }
  for (const row of snapshot.publications) {
    const d = exact(el('publications'), `${row.state} · ${short(row.id)}`, { ...row, receipt: row.receipt ? JSON.parse(row.receipt) : null });
    exact(d, 'Publication history', snapshot.publication_events.filter(e => e.record_id === row.id));
  }
  if (!snapshot.records.length) el('records').append(node('p', 'No collaboration records in this journal.', 'empty'));
  if (!snapshot.publications.length) el('publications').append(node('p', 'No publications in this journal.', 'empty'));
}
function showTab(id) {
  if (id === 'shared') { openWorkspace('shared'); return; }
  for (const tab of document.querySelectorAll('[data-tab]')) tab.setAttribute('aria-selected', String(tab.dataset.tab === id));
  for (const name of ['overview', 'description', 'assets', 'collaborators', 'versions', 'evidence', 'runs']) el(name).hidden = name !== id;
  if (id === 'assets') renderExperimentAssets(current()); else clearAssetPreviews();
  if (id === 'collaborators') renderExperimentCollaborators(current());
}
const canonicalAgent = value => typeof value === 'string' && /^(?:did:dkg:agent:)?0x[a-f0-9]{40}$/i.test(value) ? value.replace(/^did:dkg:agent:/i,'').toLowerCase() : null;
function collaboratorCard(person) {
  const card=node('div',undefined,'collaborator'), body=node('div',undefined,'collaborator-body');
  const address=canonicalAgent(person.address), self=address && address===canonicalAgent(graphInfo?.local_identity?.agentAddress);
  const name=person.name || (self ? graphInfo.local_identity.name || 'This node' : address ? `Agent ${address.slice(0,6)}…${address.slice(-4)}` : 'Participant');
  const initials=person.name ? person.name.replace(/^Participant\s+/,'').slice(0,2).toUpperCase() : 'DK';
  const avatar=node('span',initials,'collaborator-avatar'); avatar.setAttribute('aria-hidden','true');
  body.append(node('strong',name+(self && name!=='This node'?' · this node':'')));
  if (address) body.append(node('p',address,'id'));
  const roles=node('div',undefined,'collaborator-roles');
  for (const role of new Set(person.roles || [])) roles.append(node('span',role,'badge'));
  body.append(roles);
  if (person.note) body.append(node('p',person.note,'small'));
  card.append(avatar,body);return card;
}
function experimentContributors(x) {
  if (!x || x.research) return [];
  const rows=[...(snapshot?.records || []),...(x.proposals || [])], linked=new Map(), people=new Map();
  const key=r=>`${r.data.context_graph}:${r.id}`;
  for (const row of rows) if (row.data.kind==='PatchProposal' && row.data.artifact===x.id) linked.set(key(row),row);
  for (let pass=0;pass<rows.length;pass++) {
    let changed=false;
    for (const row of rows) if (['Evaluation','Review','DerivedVersion','Hypothesis'].includes(row.data.kind) && row.data.relates_to && linked.has(`${row.data.context_graph}:${row.data.relates_to}`) && !linked.has(key(row))) { linked.set(key(row),row);changed=true; }
    if (!changed) break;
  }
  const bases=new Set([...linked.values()].filter(r=>r.data.kind==='PatchProposal').map(r=>`${r.data.context_graph}:${r.data.relates_to}`));
  for (const row of rows) if (row.data.kind==='ModelVersion' && bases.has(`${row.data.context_graph}:${row.data.artifact}`)) linked.set(key(row),row);
  const roleNames={PatchProposal:'Proposal author',Evaluation:'Evaluator',Review:'Reviewer',ModelVersion:'Model provider',DerivedVersion:'Model contributor',Hypothesis:'Hypothesis author'};
  for (const row of linked.values()) {
    const address=canonicalAgent(row.data.author);if(!address)continue;
    if(!people.has(address))people.set(address,{address,roles:new Set(),records:new Set()});
    const person=people.get(address);person.roles.add(roleNames[row.data.kind]);person.records.add(key(row));
  }
  return [...people.values()].map(p=>({...p,roles:[...p.roles],note:`${p.records.size} linked DKG record${p.records.size===1?'':'s'} available on this participant`}));
}
function renderExperimentCollaborators(x) {
  const root=el('collaborators');root.replaceChildren();
  root.append(node('div',undefined,'section-head'));root.firstChild.append(node('h2','Collaborators on this experiment'));
  if(!x){root.append(node('p','Choose an experiment to see its collaborators.','empty'));return;}
  const list=node('div',undefined,'collaborator-list');
  if(x.research) {
    let collaboration=x.research.definition.collaboration || {};
    for(const item of x.research.events) if(!item.event.round && item.event.data.collaboration) collaboration={...collaboration,...item.event.data.collaboration};
    const seen=new Set();
    for(const person of Array.isArray(collaboration.participants)?collaboration.participants:[]) {
      const address=canonicalAgent(person.address);if(!address || seen.has(address))continue;seen.add(address);
      list.append(collaboratorCard({address,name:typeof person.name==='string'?person.name:null,roles:Array.isArray(person.roles)?person.roles.filter(r=>typeof r==='string'):[],note:'Identity recorded in this experiment’s evidence'}));
    }
    if(collaboration.context_graph)root.append(node('p',`Experiment context graph: ${collaboration.context_graph}`,'id'));
    if(collaboration.summary)root.append(node('p',collaboration.summary,'small collaboration-note'));
    if(x.research.definition.controller)list.append(collaboratorCard({name:x.research.definition.controller,roles:['Research controller'],note:'Recorded controller for this experiment'}));
    root.append(list);
    if(!seen.size)root.append(node('p','No DKG collaborators have been linked to this experiment.','small collaboration-note'));
  } else {
    const people=experimentContributors(x);
    for(const p of people)list.append(collaboratorCard(p));root.append(list);
    if(!people.length)root.append(node('p','No collaborators are linked to this experiment in the loaded records.','empty'));
    root.append(node('p','Contributors are linked through this proposal and its evaluations and reviews. This view uses the records available on this participant.','small collaboration-note'));
  }
  root.append(button('Browse shared experiments',()=>openWorkspace('shared'),'quiet'));
}
function renderGraphCollaborators() {
  const root=el('graph-collaborators');root.replaceChildren(node('h2','Graph collaborators'));
  if(graphLoading){root.append(node('p','Reading graph participants from DKG…','small collaboration-note'));return;}
  const graph=graphInfo?.context_graph || sharedPage?.context_graph;
  if(!graph){root.append(node('p',graphError || 'Graph collaborators are not loaded yet.','small collaboration-note'));return;}
  const people=new Map(), add=(address,role)=>{
    address=canonicalAgent(address);if(!address)return;
    if(!people.has(address))people.set(address,{address,roles:new Set()});people.get(address).roles.add(role);
  };
  for(const address of graphInfo?.participants || []) add(address,canonicalAgent(address)===canonicalAgent(graphInfo.curator)?'Curator':'Listed participant');
  for(const row of snapshot?.records || [])if(row.data.context_graph===graph)add(row.data.author,'Recorded contributor');
  for(const row of sharedPage?.records || [])if(row.record.context_graph===graph)add(row.record.author,'Proposal author');
  if(graphInfo?.access_policy==='public')root.append(node('p','Public graph · anyone can subscribe. Listed identities and known contributors are shown below; this is not a complete list of everyone with access.','small collaboration-note'));
  else if(graphInfo)root.append(node('p',`${graphInfo.access_policy==='private'?'Private graph':'Graph access follows DKG policy'} · current listed participants and authors of recorded contributions.`,'small collaboration-note'));
  if(graphError)root.append(node('p',graphError+' Showing recorded authors only; current membership is unknown.','notice'));
  const list=node('div',undefined,'collaborator-list');for(const p of people.values())list.append(collaboratorCard({...p,roles:[...p.roles]}));root.append(list);
  if(!people.size)root.append(node('p','No participant identities or recorded contributors are available.','small collaboration-note'));
}
async function refreshGraphCollaborators() {
  const request=++graphRequest,generation=epoch;graphInfo=null;graphError='';graphLoading=true;renderGraphCollaborators();
  try {
    const response=await fetch('/api/context-graph/collaborators',{headers:authHeaders(token),signal:AbortSignal.timeout(90000)}),data=await response.json();
    if(request!==graphRequest || generation!==epoch)return;
    if(!response.ok)throw new Error(data.error || `HTTP ${response.status}`);
    graphInfo=data;
  } catch(error) {if(request===graphRequest && generation===epoch)graphError=error.message;}
  finally {if(request===graphRequest && generation===epoch){graphLoading=false;renderGraphCollaborators();renderExperimentCollaborators(current());}}
}
let sharedRequest = 0, sharedOffset = 0, sharedPage = null, sharedLoading = false, sharedError = '', sharedSelected = '';
function focusSharedExperiment(id) {
  const card = [...el('shared-list').children].find(card => card.dataset.record === id);
  if (!card) return;
  sharedSelected = id; renderNavigation();
  card.focus({preventScroll:true});
  card.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
}
function renderShared() {
  const root = el('shared-list'); root.replaceChildren();
  if (!sharedPage) return;
  for (const item of sharedPage.records) {
    const x = experiments.find(x => x.id === item.record.artifact);
    const job = snapshot?.jobs.find(j => j.spec === item.record.artifact);
    const card = node('article', undefined, 'shared-card'); card.dataset.record = item.id; card.tabIndex = -1;
    card.append(node('h3', x?.name || `Shared experiment · ${short(item.record.artifact)}`));
    card.append(node('p', `Author: ${item.record.author}`, 'id'), node('p', `Proposal: ${item.id}`, 'id'));
    const contributors=experimentContributors({id:item.record.artifact,proposals:[{id:item.id,data:item.record}]});
    const people=node('details',undefined,'shared-contributors');people.append(node('summary',`${contributors.length} recorded collaborator${contributors.length===1?'':'s'}`));
    for(const person of contributors)people.append(collaboratorCard(person));card.append(people);
    if (item.record.fixture) card.append(node('span', 'Synthetic fixture', 'badge'));
    card.append(node('p', item.downloaded ? 'Model and evidence downloaded to this participant.' : `${item.record.artifacts.length} artifacts in the bundle. Weights and evidence are downloaded on request.`, 'small'));
    card.append(node('p', job?.state === 'complete' ? `Local evaluation: ${x?.report?.status || 'complete'}.` : job ? `Local evaluation: ${job.state}.` : 'No local reproduction yet.', 'small'));
    const controls = node('div', undefined, 'toolbar');
    if (!item.downloaded) controls.append(button('Download model & evidence', () => sharedAction(item, 'fetch'), 'primary'));
    else {
      controls.append(button('Open experiment', () => { choose(item.record.artifact); showTab('overview'); }));
      const retry = ['unavailable','interrupted'].includes(job?.state);
      controls.append(button(retry ? 'Retry reproduction & share result' : 'Reproduce & share result', () => sharedAction(item, 'reproduce', retry), 'primary'));
      if (continuationParent(x)) controls.append(button('Continue this experiment', () => { choose(x.id); openContinuation(); }));
    }
    for (const b of controls.children) b.disabled = busy;
    card.append(controls); root.append(card);
  }
  renderGraphCollaborators();
  renderNavigation();
}
async function refreshShared(offset = sharedOffset) {
  if (busy || !snapshot) return;
  const request = ++sharedRequest, generation = epoch;
  sharedPage = null; el('shared-list').replaceChildren();
  sharedLoading = true; sharedError = ''; renderNavigation();
  el('shared-graph').textContent = '';
  graphRequest++; graphInfo=null; graphError=''; graphLoading=true; renderGraphCollaborators();
  el('shared-previous').disabled = true; el('shared-next').disabled = true;
  el('refresh-shared').disabled = true; el('shared-status').textContent = 'Reading shared proposals from DKG…';
  try {
    const response = await fetch(`/api/shared-experiments?offset=${offset}`, {headers:authHeaders(token),signal:AbortSignal.timeout(90000)});
    const data = await response.json();
    if (request !== sharedRequest || generation !== epoch) return;
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    sharedPage = data; sharedOffset = data.offset;
    el('shared-graph').textContent = `Context graph: ${data.context_graph}`;
    el('shared-status').textContent = data.records.length ? `Showing ${data.offset + 1}–${data.offset + data.records.length}. Downloading does not evaluate or accept a model.` : 'No shared proposals found on this page. The catalogue reflects what your DKG node has synchronized.';
    renderShared();
    el('shared-previous').disabled = data.offset === 0; el('shared-next').disabled = data.next_offset == null;
  } catch (error) {
    if (request === sharedRequest && generation === epoch) { sharedError = error.message; el('shared-status').textContent = `Shared experiments unavailable. ${error.message}`; renderGraphCollaborators(); }
  } finally {
    if (request === sharedRequest && generation === epoch) {
      sharedLoading = false; renderNavigation();
      el('refresh-shared').disabled = false;
      // Leave a read permit available for local state/run polling during DKG calls.
      refreshGraphCollaborators();
    }
  }
}
async function sharedAction(item, action, retry = false) {
  if (busy || !snapshot) return;
  const generation = epoch, offset = sharedOffset;
  sharedRequest++;
  setBusy(true); renderShared();
  for (const id of ['refresh-shared','shared-previous','shared-next']) el(id).disabled = true;
  el('shared-status').textContent = action === 'fetch' ? 'Downloading and verifying model and evidence… Large models may take several minutes.' : 'Reproducing with your local evaluator, then sharing the evaluation and review through DKG…';
  let message;
  try {
    // No short HTTP timeout: native DKG transfer and evaluation can take minutes.
    const response = await fetch('/api/actions', {method:'POST',headers:{...authHeaders(token),'Content-Type':'application/json'},body:JSON.stringify({action,record:item.id,...(retry?{retry:true}:{})})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    message = action === 'fetch' ? 'Download verified. You can inspect the experiment or reproduce its result.' : `Reproduction finished: ${result.evaluation?.status || 'see local report'}. Evaluation and review shared through DKG.`;
  } catch(error) { message = `Operation did not complete successfully: ${error.message}. Refresh local records before retrying; a completed evaluation can be reused if sharing failed.`; }
  finally {
    if (generation === epoch) {
      await load();
      if (snapshot) { if(workspaceView!=='shared')await refreshShared(offset); el('shared-status').textContent = `${message} ${sharedPage ? '' : el('shared-status').textContent}`; }
    }
    setBusy(false); el('refresh-shared').disabled = false; renderShared();
  }
}
el('refresh-shared').addEventListener('click', () => refreshShared(0));
el('shared-previous').addEventListener('click', () => refreshShared(Math.max(0,sharedOffset-20)));
el('shared-next').addEventListener('click', () => { if(sharedPage?.next_offset != null) refreshShared(sharedPage.next_offset); });
const actions = {
  register: ['Import checkpoint', { file: 'Checkpoint or shard index path', mapping: 'Inference artifact mapping path (optional)' }],
  put: ['Import evaluation input', { file: 'Local file path' }],
  diff: ['Create patch from checkpoints', { parent: 'Base checkpoint ID', candidate: 'Candidate checkpoint ID' }],
  apply: ['Apply patch', { parent: 'Base checkpoint ID', patch: 'Patch ID' }],
  evaluate: ['Evaluate', { spec: 'Evaluation specification ID' }],
  propose: ['Share proposal through DKG', { spec: 'Evaluation specification ID' }],
  reproduce: ['Reproduce proposal', { record: 'Proposal record ID' }],
  fetch: ['Fetch DKG record', { record: 'Record ID' }],
  select: ['Select version', { checkpoint: 'Checkpoint ID' }],
  export: ['Export checkpoint', { checkpoint: 'Checkpoint ID', directory: 'New destination directory' }]
};
for (const [key, [label]] of Object.entries(actions)) { const option = node('option', label); option.value = key; el('action').append(option); }
function fields(values = {}) {
  el('fields').replaceChildren();
  const spec = current()?.spec;
  const defaults = { parent: spec?.base, candidate: spec?.candidate, patch: spec?.patch, spec: current()?.id, checkpoint: spec?.candidate, record: current()?.proposals[0]?.id };
  for (const [key, label] of Object.entries(actions[el('action').value][1])) {
    const box = node('label', label), input = node('input'); input.name = key; input.required = key !== 'mapping'; input.autocomplete = 'off'; input.value = values[key] ?? defaults[key] ?? ''; box.append(input); el('fields').append(box);
  }
}
function openOperation(action = current()?.spec ? 'diff' : 'register', values = {}) {
  if (busy) return;
  el('action').value = action; fields(values); el('result').textContent = ''; el('operation-dialog').showModal();
}
el('action').addEventListener('change', () => fields()); fields();
el('operation').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !snapshot || (requireToken && !token)) return;
  setBusy(true); el('result').textContent = 'Operation running…';
  try {
    const body = { action: el('action').value };
    for (const input of el('fields').querySelectorAll('input')) body[input.name] = input.value;
    const response = await fetch('/api/actions', { method: 'POST', headers: { ...authHeaders(token), 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const text = await response.text(); let result; try { result = JSON.parse(text); } catch { result = { error: text || `HTTP ${response.status}` }; }
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    el('result').textContent = JSON.stringify(result, null, 2); await load();
  } catch (e) { el('result').textContent = e.message; }
  finally { setBusy(false); }
});
el('connect').addEventListener('submit', event => { event.preventDefault(); if (busy) return; token = el('token').value.trim(); el('token').value = ''; load(); });
el('refresh').addEventListener('click', () => { if (!busy) load(); });
el('disconnect').addEventListener('click', () => { if (busy) return; epoch++; token = ''; el('token').value = ''; clearWorkspace(); el('status').textContent = 'Disconnected. Connect to a participant to continue.'; });
el('experiment-picker').addEventListener('change', e => choose(e.target.value));
el('open-operation').addEventListener('click', () => openOperation());
el('import-checkpoint').addEventListener('click', () => openModelImport(false));
for (const b of document.querySelectorAll('[data-tab]')) b.addEventListener('click', () => showTab(b.dataset.tab));
for (const b of document.querySelectorAll('[data-workspace]')) b.addEventListener('click', () => { if(snapshot)openWorkspace(b.dataset.workspace); });
for (const b of document.querySelectorAll('[data-close]')) b.addEventListener('click', () => el(b.dataset.close).close());

let shareRequest = 0;
async function refreshShare() {
  const request = ++shareRequest, generation = epoch;
  el('share-invite').value = ''; el('share-graph').value = '';
  el('copy-share-invite').disabled = true; el('open-share-dkg').hidden = true;
  el('refresh-share').disabled = true; el('share-status').textContent = 'Checking this graph with your DKG node…';
  try {
    const data = await get('/api/context-graph/share');
    if (request !== shareRequest || generation !== epoch || !el('share-dialog').open) return;
    el('share-graph').value = data.context_graph;
    const url = new URL(data.dkg_url);
    if (url.protocol === 'http:' && url.hostname === '127.0.0.1' && !url.username && !url.password) {
      el('open-share-dkg').href = url.href; el('open-share-dkg').hidden = false;
    }
    if (data.invite_code) {
      el('share-invite').value = data.invite_code; el('copy-share-invite').disabled = false;
      el('share-status').textContent = 'Ready to copy. Joining follows this graph’s DKG access policy.';
    } else { el('share-invite').placeholder = 'Invite unavailable'; el('share-status').textContent = data.error || 'Invite unavailable.'; }
  } catch (error) {
    if (request === shareRequest && generation === epoch) { el('share-status').textContent = `Could not load the DKG invite. ${error.message}`; el('share-invite').placeholder = 'Invite unavailable'; }
  } finally { if (request === shareRequest) el('refresh-share').disabled = false; }
}
el('share-context-graph').addEventListener('click', () => { if (!busy && snapshot) { el('share-dialog').showModal(); refreshShare(); } });
el('refresh-share').addEventListener('click', refreshShare);
el('copy-share-invite').addEventListener('click', async () => {
  const value = el('share-invite').value; if (!value) return;
  try { await navigator.clipboard.writeText(value); el('share-status').textContent = 'Invite code copied. Send it to your collaborator.'; }
  catch { el('share-invite').focus(); el('share-invite').select(); el('share-status').textContent = 'Select and copy the invite code manually.'; }
});

// The request ID survives an uncertain HTTP response. Retrying an unchanged form
// attaches to the same durable run instead of executing the controller twice.
let continuationId = '', continuationContext = null, runTimer = null, runsFetching = false;
async function loadEditableTensors(form, checkpoint) {
  if (form.dataset.scopeCheckpoint === checkpoint && form.dataset.scopeReady === 'true') return;
  form.dataset.scopeCheckpoint = checkpoint;
  form.dataset.scopeReady = 'false';
  const list = form.querySelector('[data-tensor-list]'), status = form.querySelector('[data-scope-status]');
  list.replaceChildren(); form.querySelector('[data-tensor-search]').value = '';
  status.textContent = 'Loading model tensors…';
  const generation = epoch;
  try {
    const manifest = await artifact(checkpoint);
    if (generation !== epoch || form.dataset.scopeCheckpoint !== checkpoint) return;
    for (const tensor of manifest.tensors || []) {
      const label = node('label'), input = node('input'); input.type = 'checkbox'; input.name = 'editable_tensor'; input.value = tensor.name;
      label.append(input, node('span', tensor.name)); list.append(label);
    }
    form.dataset.scopeReady = 'true';
    status.textContent = `${list.children.length} tensors available. Select the ones the agent may edit.`;
  } catch (e) { if (generation === epoch && form.dataset.scopeCheckpoint === checkpoint) status.textContent = `Could not load tensors: ${e.message}. Reopen this form to retry.`; }
}
function userControls(element, form, request, error) {
  for (const name of ['objective', 'instructions']) { const value = form.get(name).trim(); if (value) request[name] = value; }
  const mode = form.get('weight_scope');
  request.weight_scope = { mode };
  if (mode === 'selected') {
    const tensors = form.getAll('editable_tensor');
    if (element.dataset.scopeReady !== 'true' || !tensors.length) { error.textContent = 'Select at least one editable tensor, or choose Whole model.'; return false; }
    request.weight_scope.tensors = tensors;
  }
  const limit = form.get('max_edit_elements').trim();
  request.max_edit_elements = limit ? Number(limit) : null;
  return true;
}
for (const id of ['experiment-form', 'continuation-form']) {
  const form = el(id);
  form.querySelector('[name=weight_scope]').addEventListener('change', e => { form.querySelector('[data-scope-picker]').hidden = e.target.value !== 'selected'; });
  form.querySelector('[data-tensor-search]').addEventListener('input', e => {
    const search = e.target.value.toLowerCase();
    for (const label of form.querySelector('[data-tensor-list]').children) label.hidden = !label.textContent.toLowerCase().includes(search);
  });
}
el('experiment-checkpoint').addEventListener('change', e => loadEditableTensors(el('experiment-form'), e.target.value));
function continuationParent(x) {
  const report = x?.reports.find(r => r.data.status === 'passed');
  return x?.session && x.proposals.length && report ? { checkpoint: x.spec.candidate, proposal: x.proposals[0].id, report: report.id } : null;
}
function stopRunPolling() { clearTimeout(runTimer); runTimer = null; }
async function postRun(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { ...authHeaders(token), 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000) });
  const text = await r.text(); let value; try { value = JSON.parse(text); } catch { value = { error: text || `HTTP ${r.status}` }; }
  if (!r.ok) throw new Error(value.error || `HTTP ${r.status}`);
  return value;
}
function openContinuation() {
  continuationContext = continuationParent(current());
  if (!continuationContext || busy) return;
  continuationId = crypto.randomUUID();
  el('continuation-parent').textContent = `Inherited checkpoint: ${continuationContext.checkpoint}`;
  el('continuation-error').textContent = '';
  el('continuation-dialog').showModal();
  loadEditableTensors(el('continuation-form'), continuationContext.checkpoint);
  refreshControllerModels(el('continuation-form'));
}
el('open-continuation').addEventListener('click', openContinuation);
el('continuation-form').addEventListener('input', () => { continuationId = crypto.randomUUID(); });
el('continuation-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !continuationContext) return;
  const form = new FormData(event.currentTarget);
  const request = { id: continuationId, ...continuationContext, task_directory: form.get('task_directory').trim(), backend: form.get('backend'), controller_model: selectedController(form) };
  if (!userControls(event.currentTarget, form, request, el('continuation-error'))) return;
  for (const name of ['max_rounds', 'max_probes', 'min_probes']) request[name] = Number(form.get(name));
  request.timeout_seconds = Number(form.get('timeout_minutes')) * 60;
  if (request.min_probes > request.max_probes) { el('continuation-error').textContent = 'Minimum probes must not exceed maximum probes.'; return; }
  const generation = epoch;
  setBusy(true); el('start-continuation').disabled = true; el('continuation-error').textContent = 'Submitting controller job…';
  try {
    await postRun('/api/continuations', request);
    if (generation !== epoch) return;
    el('continuation-dialog').close(); showTab('runs'); await refreshRuns();
  } catch (e) { if (generation === epoch) el('continuation-error').textContent = `${e.message}. You can retry this request safely.`; }
  finally { setBusy(false); el('start-continuation').disabled = false; }
});
async function refreshRuns() {
  stopRunPolling();
  if ((requireToken && !token) || !snapshot || runsFetching) return;
  runsFetching = true; const generation = epoch; let hasActive = false;
  try {
    const result = await get('/api/continuations'); if (generation !== epoch) return;
    hasActive = result.runs.some(run => ['queued', 'preparing', 'searching', 'registering', 'cancelling'].includes(run.status));
    const root = el('run-list'); root.replaceChildren();
    for (const run of result.runs) {
      const card = node('article', undefined, 'panel run-card'), head = node('div', undefined, 'row');
      head.append(node('h3', run.name || run.controller_model), node('span', run.status, `badge ${run.status === 'failed' ? 'bad' : ''}`));
      card.append(head, node('p', `${run.kind === 'experiment' ? 'New experiment' : 'Continuation'} · ${run.controller_model} · ${run.backend} · attempt ${run.attempt} · ${short(run.id)}`, 'small'), node('p', run.message));
      const controls = node('div', undefined, 'toolbar');
      if (['queued', 'preparing', 'searching', 'registering', 'cancelling'].includes(run.status)) controls.append(button('Cancel run', () => controlRun(run.id, 'cancel')));
      if (run.resumable) controls.append(button('Resume search', () => controlRun(run.id, 'resume')));
      if (run.importable) controls.append(button('Retry candidate import', () => controlRun(run.id, 'resume')));
      if (run.result) controls.append(button('Inspect candidate', () => inspectCheckpoint(run.result.candidate)), button('Evaluate candidate', () => openOperation('evaluate', { spec: run.result.spec }), 'primary'));
      card.append(controls); exact(card, 'Run details', run); root.append(card);
    }
    if (!result.runs.length) root.append(node('p', 'No controller runs yet. Create a new experiment or continue an existing one.', 'empty'));
    el('runs-status').textContent = 'Status refreshed. Active jobs are checked every 3 seconds.';
  } catch (e) { hasActive = true; if (generation === epoch) el('runs-status').textContent = `Run status unavailable: ${e.message}`; }
  finally {
    runsFetching = false;
    if ((!requireToken || token) && snapshot && (hasActive || generation !== epoch)) runTimer = setTimeout(refreshRuns, 3000);
  }
}
async function controlRun(id, action) {
  if (busy) return;
  setBusy(true); const generation = epoch;
  try { await postRun(`/api/continuations/${id}/${action}`); if (generation === epoch) await refreshRuns(); }
  catch (e) { if (generation === epoch) el('runs-status').textContent = e.message; }
  finally { setBusy(false); }
}
el('refresh-runs').addEventListener('click', refreshRuns);

// New experiments share the durable job runner but do not require parent evidence.
let experimentId = '';
async function openExperiment(preferredCheckpoint) {
  if (busy || !snapshot) return;
  const generation = epoch, select = el('experiment-checkpoint');
  experimentId = crypto.randomUUID(); select.replaceChildren();
  el('experiment-error').textContent = '';
  el('experiment-model-hint').textContent = 'Checking imported models…';
  el('start-experiment').disabled = true;
  el('experiment-dialog').showModal();
  refreshControllerModels(el('experiment-form'));
  let available = 0;
  for (const row of snapshot.checkpoints) {
    try {
      const m = await artifact(row.id);
      if (generation !== epoch || !el('experiment-dialog').open) return;
      if (m.format !== 'safetensors' || Object.keys(m.shards || {}).length ||
          !['model_config','tokenizer','tokenizer_config','special_tokens'].every(k => m.inference_artifacts?.[k])) continue;
      const related = experiments.find(x => x.spec?.base === row.id || x.spec?.candidate === row.id);
      const role = related?.spec?.base === row.id ? 'base' : 'candidate';
      let label = related ? related.name + ' · ' + role : '';
      if (!label && m.inference_artifacts.source) {
        try { const source = await artifact(m.inference_artifacts.source); label = source.model || ''; } catch {}
      }
      if (generation !== epoch || !el('experiment-dialog').open) return;
      const option = node('option', `${label ? label + ' · ' : ''}${short(row.id)}`);
      option.value = row.id; select.append(option); available++;
    } catch { /* A model without readable inference metadata cannot start a run. */ }
  }
  if (generation !== epoch || !el('experiment-dialog').open) return;
  const preferred = preferredCheckpoint || current()?.spec?.base;
  if (preferred && [...select.options].some(o => o.value === preferred)) select.value = preferred;
  el('experiment-model-hint').textContent = available ? 'Uses the exact saved model and its tokenizer. No previous evaluation is required.' : 'Import a local model folder to get started.';
  el('start-experiment').disabled = !available;
  loadEditableTensors(el('experiment-form'), select.value);
}
el('new-experiment').addEventListener('click', () => openExperiment());
el('experiment-import').addEventListener('click', () => openModelImport(true));
let importReturnToExperiment = false, importPreviousCheckpoint = '';
function openModelImport(fromExperiment) {
  if (busy || !snapshot) return;
  importReturnToExperiment = fromExperiment;
  importPreviousCheckpoint = el('experiment-checkpoint').value;
  el('experiment-dialog').close();
  el('import-model-error').textContent = '';
  el('cancel-import-model').textContent = fromExperiment ? 'Back to experiment' : 'Cancel';
  el('import-model-dialog').showModal();
}
function closeModelImport() {
  if (busy) return;
  el('import-model-dialog').close();
  if (importReturnToExperiment) openExperiment(importPreviousCheckpoint);
}
el('close-import-model').addEventListener('click', closeModelImport);
el('cancel-import-model').addEventListener('click', closeModelImport);
el('import-model-dialog').addEventListener('cancel', event => { event.preventDefault(); closeModelImport(); });
el('model-directory').addEventListener('input', () => { if (!busy) el('import-model-error').textContent = ''; });
el('import-model-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !snapshot) return;
  const generation = epoch, message = el('import-model-error');
  setBusy(true); el('submit-import-model').disabled = true;
  message.className = 'small'; message.textContent = 'Importing model files… Large models may take a little longer.';
  try {
    const response = await fetch('/api/actions', { method: 'POST', headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'import_model', directory: el('model-directory').value.trim() }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Import failed (HTTP ${response.status})`);
    if (generation !== epoch) return;
    el('import-model-dialog').close();
    await load();
    if (!snapshot) return;
    if (importReturnToExperiment) await openExperiment(result.checkpoint);
    else showTab('versions');
    el('status').textContent = `Imported ${result.name || 'model'} into this workspace.`;
  } catch (error) {
    if (generation === epoch) { message.className = 'error'; message.textContent = error.message; }
  } finally { setBusy(false); el('submit-import-model').disabled = false; }
});
el('experiment-form').addEventListener('input', () => { experimentId = crypto.randomUUID(); });
el('experiment-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !snapshot) return;
  const form = new FormData(event.currentTarget);
  const request = { id: experimentId, name: form.get('name').trim(), checkpoint: form.get('checkpoint'),
    task_directory: form.get('task_directory').trim(), backend: form.get('backend'), controller_model: selectedController(form) };
  if (!userControls(event.currentTarget, form, request, el('experiment-error'))) return;
  for (const name of ['max_rounds','max_probes','min_probes']) request[name] = Number(form.get(name));
  request.timeout_seconds = Number(form.get('timeout_minutes')) * 60;
  if (request.min_probes > request.max_probes) { el('experiment-error').textContent = 'Minimum probes must not exceed maximum probes.'; return; }
  const generation = epoch;
  setBusy(true); el('start-experiment').disabled = true; el('experiment-error').textContent = 'Submitting experiment…';
  try {
    await postRun('/api/experiments', request);
    if (generation !== epoch) return;
    el('experiment-dialog').close(); showTab('runs'); await refreshRuns();
  } catch (e) { if (generation === epoch) el('experiment-error').textContent = `${e.message}. You can retry this request safely.`; }
  finally { setBusy(false); el('start-experiment').disabled = false; }
});

async function initializeAccess() {
  try {
    const settings = await get('/api/ui-config', '');
    requireToken = settings.require_token !== false;
    el('disconnect').hidden = !requireToken;
    el('connection').hidden = !requireToken;
    if (requireToken) el('status').textContent = 'Connect to your local participant.';
    else await load();
  } catch (error) {
    el('status').textContent = `Could not connect: ${error.message}. Reload to retry.`;
    el('status').className = 'error';
  }
}
initializeAccess();

// Folder browsing is local to the machine hosting this workspace; no files upload.
let folderTarget = null, folderKind = 'task', folderState = null, folderRequest = 0;
function renderFolderList() {
  const root = el('folder-list'); root.replaceChildren();
  const query = el('folder-filter').value.toLowerCase();
  for (const entry of folderState?.entries || []) {
    if (!entry.name.toLowerCase().includes(query)) continue;
    const b = button('', () => browseFolder(entry.path));
    b.append(node('span', entry.name), node('span', '›')); b.setAttribute('aria-label', `Open folder ${entry.name}`); root.append(b);
  }
  if (!root.children.length) root.append(node('p', 'No matching subfolders.', 'empty'));
}
async function browseFolder(path = '') {
  const request = ++folderRequest, generation = epoch;
  el('folder-select').disabled = true; folderState = null;
  el('folder-list').replaceChildren(); el('folder-checks').replaceChildren();
  el('folder-message').textContent = 'Reading folder…';
  try {
    const params = new URLSearchParams({kind:folderKind, hidden:String(el('folder-hidden').checked)});
    if (path) params.set('path',path);
    const result = await get('/api/folders?' + params);
    if (request !== folderRequest || generation !== epoch || !el('folder-dialog').open) return;
    folderState=result; el('folder-location').value=result.path; el('folder-filter').value='';
    el('folder-up').disabled=!result.parent;
    el('folder-shortcuts').replaceChildren(...result.shortcuts.map(s=>button(s.name,()=>browseFolder(s.path))));
    el('folder-message').textContent=result.message + (result.truncated ? ' Showing the first 2,000 folders; enter a more specific path to narrow the list.' : '');
    for (const check of result.checks) el('folder-checks').append(node('span', `${check.present ? '✓' : '–'} ${check.name}`,check.present?'good':'muted'));
    el('folder-select').disabled=!result.selectable; renderFolderList();
  } catch(error) { if(request===folderRequest && generation===epoch) el('folder-message').textContent=`Could not open folder. Check its path and permissions. ${error.message}`; }
}
for (const b of document.querySelectorAll('[data-browse]')) b.addEventListener('click',()=>{
  folderTarget=el(b.dataset.browse); folderKind=b.dataset.kind;
  el('folder-title').textContent=folderKind==='task'?'Choose task folder':'Choose model folder';
  el('folder-dialog').showModal(); browseFolder(folderTarget.value.trim());
});
el('folder-location-form').addEventListener('submit',e=>{e.preventDefault();browseFolder(el('folder-location').value.trim());});
el('folder-up').addEventListener('click',()=>{if(folderState?.parent) browseFolder(folderState.parent);});
el('folder-filter').addEventListener('input',renderFolderList);
el('folder-hidden').addEventListener('change',()=>browseFolder(el('folder-location').value));
el('folder-select').addEventListener('click',()=>{
  if(!folderState?.selectable || !folderTarget) return;
  folderTarget.value=folderState.path;folderTarget.dispatchEvent(new Event('input',{bubbles:true}));
  el('folder-dialog').close();folderTarget.focus();
});
el('folder-dialog').addEventListener('close',()=>{folderRequest++;folderState=null;});

function selectedController(data) {
  return String(data.get('controller_model') === '__custom__' ? data.get('custom_controller_model') : data.get('controller_model') || '').trim();
}
function customControllerVisibility(form) {
  const custom=form.querySelector('[data-custom-model]'), input=custom.querySelector('input');
  const shown=form.elements.controller_model.value==='__custom__';custom.hidden=!shown;input.disabled=!shown;input.required=shown;
}
async function refreshControllerModels(form) {
  const select=form.elements.controller_model, backend=form.elements.backend.value, previous=select.value;
  const request=String(Number(form.dataset.modelRequest || 0)+1);form.dataset.modelRequest=request;
  const generation=epoch,status=form.querySelector('[data-model-status]');
  select.disabled=true;status.textContent='Loading controller models…';
  try {
    const catalog=await get('/api/controller-models?'+new URLSearchParams({backend}));
    if(form.dataset.modelRequest!==request || epoch!==generation || form.elements.backend.value!==backend)return;
    select.replaceChildren(node('option','Choose a model…'));select.options[0].value='';
    for(const model of catalog.models){const option=node('option',model.name);option.value=model.id;select.append(option);}
    const custom=node('option','Custom model…');custom.value='__custom__';select.append(custom);
    if([...select.options].some(o=>o.value===previous))select.value=previous;
    status.textContent=catalog.message || '';
  } catch(error) {
    if(form.dataset.modelRequest!==request || epoch!==generation)return;
    select.replaceChildren(node('option','Choose a model…'),node('option','Custom model…'));select.options[0].value='';select.options[1].value='__custom__';
    status.textContent='Could not load models. Refresh or choose Custom model.';
  } finally {
    if(form.dataset.modelRequest===request && epoch===generation){select.disabled=false;customControllerVisibility(form);}
  }
}
for(const form of [el('experiment-form'),el('continuation-form')]){
  form.elements.backend.addEventListener('change',()=>{form.elements.controller_model.value='';form.elements.custom_controller_model.value='';customControllerVisibility(form);refreshControllerModels(form);});
  form.elements.controller_model.addEventListener('change',()=>customControllerVisibility(form));
  form.querySelector('[data-refresh-models]').addEventListener('click',()=>refreshControllerModels(form));
}

function checkpointMap(manifest, selectTensors, diff = null) {
  const differences=new Map((diff?.tensors || []).map(t=>[t.name,t.changed]));
  const tensors=manifest.tensors || [], groups=new Map();
  const compact=n=>new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(n);
  for(const tensor of tensors){
    const layer=tensor.name.match(/(?:^|\.)(?:layers|h|blocks)\.(\d+)(?:\.|$)/);
    const stack=layer ? tensor.name.slice(0,layer.index) : undefined;
    const embedding=/embed|(?:^|\.)(?:wte|wpe)(?:\.|$)/.test(tensor.name);
    const key=layer ? `layer:${stack}:${layer[1]}` : embedding ? 'embedding' : 'other';
    if(!groups.has(key))groups.set(key,{key,stack,label:layer?`Layer ${layer[1]}`:embedding?'Embeddings':'Other tensors',order:layer?Number(layer[1]):embedding?-1:Infinity,tensors:[],values:0,changed:0});
    const group=groups.get(key);group.tensors.push(tensor);group.changed+=differences.get(tensor.name)||0;
    group.values+=tensor.shape.reduce((n,d)=>n*d,1);
  }
  const ordered=[...groups.values()].sort((a,b)=>a.stack!==undefined && b.stack!==undefined ? a.stack.localeCompare(b.stack) || a.order-b.order : a.order-b.order),total=ordered.reduce((n,g)=>n+g.values,0);
  if(new Set(ordered.filter(g=>g.stack!==undefined).map(g=>g.stack)).size>1){
    for(const g of ordered.filter(g=>g.stack!==undefined))g.label=`${/vision/i.test(g.stack)?'Vision':/text|language/i.test(g.stack)?'Language':g.stack.split('.').at(-1)||'Model'} layer ${g.order}`;
  }
  const changedGroups=ordered.filter(g=>g.changed>0);
  const panel=node('section',undefined,'tensor-map');panel.setAttribute('aria-label','Checkpoint tensor map');
  const head=node('div',undefined,'row'), reset=button('Show all',()=>choose(null),'quiet');head.append(node('h3',diff ? 'Weight changes' : 'Checkpoint map'),reset);panel.append(head);
  const summary=node('div',undefined,'tensor-summary');
  for(const [value,label] of (diff ? [[diff.changed.toLocaleString(),'changed values'],[diff.changed_tensors,'changed tensors'],[changedGroups.length,'changed components'],[compact(total),'total values']] : [[compact(total),'stored values'],[tensors.length,'tensors'],[ordered.filter(g=>g.key.startsWith('layer:')).length,'named layers'],[[...new Set(tensors.map(t=>t.dtype))].join(' / '),'precision']])){
    const stat=node('div');stat.append(node('strong',String(value)),node('span',label,'small'));summary.append(stat);
  }
  panel.append(summary);
  if(diff){
    const changedBlocks=changedGroups.filter(g=>g.key.startsWith('layer:')).length;
    const blockCount=ordered.filter(g=>g.key.startsWith('layer:')).length;
    panel.append(node('p',`${changedGroups.length===1?'Changed component':'Changed components'}: ${changedGroups.map(g=>g.label).join(', ') || 'None'}. ${changedBlocks} of ${blockCount} numbered transformer blocks changed. Embeddings and other tensors are counted separately from these blocks.`,'small'));
  }
  const strip=node('div',undefined,'tensor-strip');strip.setAttribute('aria-label','Stored values by tensor group');
  const buttons=node('div',undefined,'tensor-groups'), controls=[];
  const explanation=diff?'Orange marks actual changed weights; gray groups are unchanged. Group size shows total stored values.':'Select a group to inspect its tensors. Sizes come from the saved tensor shapes.';
  const description=node('p',explanation,'small');
  function choose(group){for(const [b,g] of controls)b.setAttribute('aria-pressed',String(g===group));selectTensors(group?group.tensors:tensors);description.textContent=group?`${group.label} · ${group.tensors.length} tensors · ${group.values.toLocaleString()} stored values${diff ? ' · '+group.changed.toLocaleString()+' changed' : ''}`:explanation;}
  for(const group of ordered){
    const segment=node('span');segment.style.flexGrow=String(total?group.values/total:1);segment.title=`${group.label}: ${group.values.toLocaleString()} values`;if(diff)segment.style.background=group.changed?'#eda968':'#374449';strip.append(segment);
    const b=button(group.label,()=>choose(group));b.setAttribute('aria-pressed','false');b.append(node('span',`${compact(group.values)} values`));if(diff){b.classList.add(group.changed?'weights-changed':'weights-unchanged');b.append(node('span',`${group.changed.toLocaleString()} changed`));}controls.push([b,group]);buttons.append(b);
  }
  panel.append(strip,buttons,description);return panel;
}

function weightChangeDetails(initial, isCurrent) {
  const root=node('section',undefined,'weight-details');root.setAttribute('aria-label','Changed weight values');
  root.append(node('h3','Before → after'));
  const label=node('label','Changed tensor'), select=node('select');
  const all=node('option','All changed tensors');all.value='';select.append(all);
  for(const tensor of initial.tensors.filter(t=>t.changed)){const o=node('option',`${tensor.name} · ${tensor.changed.toLocaleString()} changes`);o.value=tensor.name;select.append(o);}
  label.append(select);root.append(label);
  const status=node('p','', 'small'), wrap=node('div',undefined,'table-wrap'),table=node('table'),head=node('tr'),body=node('tbody');
  table.className='weight-values';for(const title of ['Tensor / index','Before','After','Δ'])head.append(node('th',title));table.append(head,body);wrap.append(table);root.append(status,wrap);
  const controls=node('div',undefined,'toolbar');let page=initial,serial=0;
  const previous=button('Previous',()=>fetchPage(Math.max(0,page.offset-page.limit))),next=button('Next',()=>fetchPage(page.offset+page.limit));controls.append(previous,next);root.append(controls);
  const number=v=>typeof v==='number'?(Object.is(v,-0)?'-0':String(v)):v;
  function render(result){page=result;body.replaceChildren();for(const change of result.changes){const row=node('tr');const id=node('td');id.append(node('span',change.tensor,'id'),node('span',`[${change.coordinates.join(', ')}] · flat ${change.index}`,'small'));row.append(id);for(const v of [change.before,change.after,change.delta])row.append(node('td',number(v)));body.append(row);}status.textContent=result.matching_changes?`${result.offset+1}–${result.offset+result.changes.length} of ${result.matching_changes.toLocaleString()} changed values. Exact stored values; Δ = after − before.`:'No stored values changed.';previous.disabled=result.offset===0;next.disabled=!result.has_more;}
  async function fetchPage(offset){const request=++serial;previous.disabled=true;next.disabled=true;status.textContent='Reading changed values…';try{const q=new URLSearchParams({base:initial.base,candidate:initial.candidate,offset:String(offset),limit:String(initial.limit)});if(select.value)q.set('tensor',select.value);const result=await get('/api/checkpoint-diff?'+q);if(request===serial && isCurrent())render(result);}catch(error){if(request===serial && isCurrent()){status.textContent='Could not read changes: '+error.message;previous.disabled=page.offset===0;next.disabled=!page.has_more;}}}
  root.append(node('p',initial.comparison==='numeric-values-across-precision' ? 'Tensors with different precision are compared by decoded numeric value; an exact cast alone is not a weight edit. Signed zero is distinguished; NaNs in converted tensors count as changed.' : 'Changes compare stored bits, including signed zero and non-finite representations.','small'));
  select.addEventListener('change',()=>fetchPage(0));render(initial);return root;
}

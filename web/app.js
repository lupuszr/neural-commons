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
let token = '', snapshot = null, experiments = [], selected = '', epoch = 0, busy = false;
let cache = new Map();
let checkpointRequest = 0;
async function get(path, credential = token) {
  const r = await fetch(path, { headers: { Authorization: `Bearer ${credential}` }, signal: AbortSignal.timeout(15000) });
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
  for (const id of ['load', 'refresh', 'disconnect', 'execute']) el(id).disabled = value;
}
function clearWorkspace() {
  stopRunPolling();
  snapshot = null; experiments = []; selected = ''; cache = new Map();
  el('workspace').hidden = true; el('session-tools').hidden = true; el('connection').hidden = false;
  for (const id of ['overview','checkpoints','records','publications','evaluation-evidence','experiment-picker']) el(id).replaceChildren();
  el('experiments').replaceChildren(node('p', 'Connect a participant to view its experiments.', 'small'));
  for (const id of ['operation-dialog', 'checkpoint-dialog', 'continuation-dialog']) el(id).close();
  el('run-list').replaceChildren(); el('runs-status').textContent = '';
  el('continuation-form').reset(); continuationContext = null; continuationId = '';
  el('checkpoint-content').replaceChildren(); el('result').textContent = '';
}
async function load() {
  const generation = ++epoch;
  setBusy(true); el('status').className = ''; el('status').textContent = 'Reading participant records…';
  cache = new Map();
  try {
    const state = await get('/api/state');
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
      x.name = model ? model.split('/').at(-1) : evaluatorNames[x.spec?.evaluator] || x.spec?.evaluator || 'Unavailable evaluation';
      x.label = `${x.name} · ${short(x.id)}`;
    }
    if (generation !== epoch) return;
    snapshot = { ...state, records: rows }; experiments = [...groups.values()];
    if (!experiments.some(x => x.id === selected)) selected = experiments.find(x => !x.fixture)?.id || experiments[0]?.id || '';
    el('connection').hidden = true; el('workspace').hidden = false; el('session-tools').hidden = false;
    renderNavigation(); renderCheckpoints(); renderRecords(); renderExperiment();
    el('status').textContent = 'Loaded from the local participant journal. Refresh to read updates.';
    refreshRuns();
  } catch (e) {
    if (generation !== epoch) return;
    clearWorkspace(); token = ''; el('token').value = '';
    el('status').textContent = e.message; el('status').className = 'error';
  } finally { if (generation === epoch) setBusy(false); }
}
function renderNavigation() {
  el('experiments').replaceChildren(); el('experiment-picker').replaceChildren();
  for (const x of experiments) {
    const b = button(x.name, () => choose(x.id), 'experiment');
    b.setAttribute('aria-pressed', String(x.id === selected)); b.dataset.experiment = x.id;
    b.append(node('span', `${x.fixture ? 'Synthetic fixture · ' : ''}${x.report?.status || x.jobs[0]?.state || 'No evaluation'} · ${short(x.id)}`, 'small'));
    el('experiments').append(b);
    const option = node('option', x.label); option.value = x.id; el('experiment-picker').append(option);
  }
  if (!experiments.length) el('experiments').append(node('p', 'No evaluations yet. Import a checkpoint to get started.', 'small'));
  el('experiment-picker').value = selected;
}
function choose(id) { selected = id; renderNavigation(); renderExperiment(); }
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
function renderExperiment() {
  const x = current(), root = el('overview'); root.replaceChildren(); el('evaluation-evidence').replaceChildren();
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
async function inspectCheckpoint(id) {
  const request = ++checkpointRequest;
  const root = el('checkpoint-content'), dialog = el('checkpoint-dialog');
  root.replaceChildren(node('p', id, 'id'), node('p', 'Reading checkpoint…', 'small')); dialog.showModal();
  const generation = epoch;
  try {
    const m = await artifact(id); if (generation !== epoch || request !== checkpointRequest || !dialog.open) return;
    root.replaceChildren(node('p', id, 'id'));
    const wrap = node('div', undefined, 'table-wrap'), table = node('table'), header = node('tr');
    for (const title of ['Tensor', 'Shape', 'Type']) header.append(node('th', title)); table.append(header);
    for (const tensor of m.tensors || []) { const row = node('tr'); for (const value of [tensor.name, JSON.stringify(tensor.shape), tensor.dtype]) row.append(node('td', value)); table.append(row); }
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
  for (const tab of document.querySelectorAll('[data-tab]')) tab.setAttribute('aria-selected', String(tab.dataset.tab === id));
  for (const name of ['overview', 'versions', 'evidence', 'runs']) el(name).hidden = name !== id;
}
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
  event.preventDefault(); if (busy || !token) return;
  setBusy(true); el('result').textContent = 'Operation running…';
  try {
    const body = { action: el('action').value };
    for (const input of el('fields').querySelectorAll('input')) body[input.name] = input.value;
    const response = await fetch('/api/actions', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
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
el('import-checkpoint').addEventListener('click', () => openOperation('register'));
for (const b of document.querySelectorAll('[data-tab]')) b.addEventListener('click', () => showTab(b.dataset.tab));
for (const b of document.querySelectorAll('[data-close]')) b.addEventListener('click', () => el(b.dataset.close).close());

// The request ID survives an uncertain HTTP response. Retrying an unchanged form
// attaches to the same durable run instead of executing the controller twice.
let continuationId = '', continuationContext = null, runTimer = null, runsFetching = false;
function continuationParent(x) {
  const report = x?.reports.find(r => r.data.status === 'passed');
  return x?.session && x.proposals.length && report ? { checkpoint: x.spec.candidate, proposal: x.proposals[0].id, report: report.id } : null;
}
function stopRunPolling() { clearTimeout(runTimer); runTimer = null; }
async function postRun(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000) });
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
}
el('open-continuation').addEventListener('click', openContinuation);
el('continuation-form').addEventListener('input', () => { continuationId = crypto.randomUUID(); });
el('continuation-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !continuationContext) return;
  const form = new FormData(event.currentTarget);
  const request = { id: continuationId, ...continuationContext, task_directory: form.get('task_directory').trim(), backend: form.get('backend'), controller_model: form.get('controller_model').trim() };
  for (const name of ['max_rounds', 'max_probes', 'min_probes', 'max_edit_elements']) request[name] = Number(form.get(name));
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
  if (!token || !snapshot || runsFetching) return;
  runsFetching = true; const generation = epoch; let hasActive = false;
  try {
    const result = await get('/api/continuations'); if (generation !== epoch) return;
    hasActive = result.runs.some(run => ['queued', 'preparing', 'searching', 'registering', 'cancelling'].includes(run.status));
    const root = el('run-list'); root.replaceChildren();
    for (const run of result.runs) {
      const card = node('article', undefined, 'panel run-card'), head = node('div', undefined, 'row');
      head.append(node('h3', run.controller_model), node('span', run.status, `badge ${run.status === 'failed' ? 'bad' : ''}`));
      card.append(head, node('p', `${run.backend} · attempt ${run.attempt} · ${short(run.id)}`, 'small'), node('p', run.message));
      const controls = node('div', undefined, 'toolbar');
      if (['queued', 'preparing', 'searching', 'registering', 'cancelling'].includes(run.status)) controls.append(button('Cancel run', () => controlRun(run.id, 'cancel')));
      if (run.resumable) controls.append(button('Resume search', () => controlRun(run.id, 'resume')));
      if (run.importable) controls.append(button('Retry candidate import', () => controlRun(run.id, 'resume')));
      if (run.result) controls.append(button('Inspect candidate', () => inspectCheckpoint(run.result.candidate)), button('Evaluate candidate', () => openOperation('evaluate', { spec: run.result.spec }), 'primary'));
      card.append(controls); exact(card, 'Run details', run); root.append(card);
    }
    if (!result.runs.length) root.append(node('p', 'No controller runs yet. Continue from an eligible experiment to start one.', 'empty'));
    el('runs-status').textContent = 'Status refreshed. Active jobs are checked every 3 seconds.';
  } catch (e) { hasActive = true; if (generation === epoch) el('runs-status').textContent = `Run status unavailable: ${e.message}`; }
  finally {
    runsFetching = false;
    if (token && snapshot && (hasActive || generation !== epoch)) runTimer = setTimeout(refreshRuns, 3000);
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

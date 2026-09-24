import { renderHistory } from './charts.js';

const $ = (id) => document.getElementById(id);
let config = {};

async function read(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function row(label, value) {
  const item = document.createElement('div');
  item.className = 'row';
  const name = document.createElement('span');
  const detail = document.createElement('small');
  name.textContent = label;
  detail.textContent = value;
  item.append(name, detail);
  return item;
}

function showError(id, error) {
  const message = document.createElement('p');
  message.className = 'error';
  message.textContent = error.message;
  $(id).replaceChildren(message);
}

function traceLink(traceId) {
  if (!config.grafana_ui_url || !/^[a-f0-9]{16,32}$/i.test(traceId || '')) return null;
  const panes = { trace: {
    datasource: 'tempo',
    queries: [{ refId: 'A', datasource: { type: 'tempo', uid: 'tempo' }, queryType: 'traceql', query: traceId }],
    range: { from: 'now-24h', to: 'now' },
  } };
  const link = document.createElement('a');
  link.className = 'trace-link';
  link.href = `${config.grafana_ui_url.replace(/\/$/, '')}/explore?panes=${encodeURIComponent(JSON.stringify(panes))}&schemaVersion=1&orgId=1`;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = `Trace ${traceId.slice(0, 12)}…`;
  return link;
}

async function loadConfig() {
  config = await read('/api/config');
  $('project-name').textContent = config.project_name;
  $('project-id').textContent = config.project_id;
  $('environment').textContent = config.environment;
  document.title = `${config.project_name} · Observability`;
  $('grafana-link').href = `${config.grafana_ui_url.replace(/\/$/, '')}/d/agno-observability/agno-observability`;
  $('langfuse-link').hidden = !config.langfuse_ui_url;
  if (config.langfuse_ui_url) $('langfuse-link').href = config.langfuse_ui_url;
  if (!config.configured) $('notice').textContent = 'Set agentos_url in config.py to connect an AgentOS instance.';
}

async function loadStatus() {
  try {
    const data = await read('/api/status');
    $('source-status').replaceChildren();
    for (const [name, source] of Object.entries(data)) {
      const item = document.createElement('div');
      item.className = 'source-item';
      const title = document.createElement('strong');
      title.textContent = name === 'agentos' ? 'AgentOS' : name[0].toUpperCase() + name.slice(1);
      const state = document.createElement('span');
      state.className = `source-state ${['connected', 'delivered'].includes(source.state) ? 'ok' : ['unavailable', 'degraded'].includes(source.state) ? 'error' : ''}`;
      state.textContent = source.state.replace('_', ' ');
      const detail = document.createElement('small');
      detail.textContent = source.last_seen ? `Last data: ${new Date(source.last_seen).toLocaleString()}` : source.detail;
      item.append(title, state, detail);
      $('source-status').append(item);
    }
  } catch (error) { showError('source-status', error); }
}

async function loadEntities() {
  try {
    const data = await read('/api/entities');
    $('agentos-status').textContent = 'Connected';
    $('agentos-status').className = 'status ok';
    $('agentos-meta').textContent = `Agno ${data.version || 'version unknown'} · ${data.auth_mode || 'auth unknown'}`;
    $('entities').replaceChildren();
    for (const kind of ['agents', 'teams', 'workflows']) {
      $('entities').append(row(kind[0].toUpperCase() + kind.slice(1), String(data[kind].length)));
      for (const entity of data[kind]) $('entities').append(row(entity.name, entity.id));
    }
  } catch (error) {
    $('agentos-status').textContent = config.configured ? 'Unavailable' : 'Not configured';
    $('agentos-status').className = 'status error';
    $('agentos-meta').textContent = error.message;
    $('entities').replaceChildren();
  }
}

async function loadMetrics() {
  try {
    const data = await read('/api/metrics');
    $('metrics').replaceChildren();
    for (const [name, samples] of Object.entries(data)) {
      if (!samples.length) $('metrics').append(row(name, 'No samples'));
      for (const sample of samples) $('metrics').append(row(name, `${sample.value} ${sample.labels.instance || ''}`));
    }
  } catch (error) { showError('metrics', error); }
}

async function loadHistory() {
  try {
    renderHistory($('history'), await read(`/api/metrics/range?hours=${$('time-range').value}`));
  } catch (error) { showError('history', error); }
}

async function loadRuns(sessionId, type) {
  $('runs').textContent = 'Loading runs…';
  try {
    const runs = await read(`/api/sessions/${encodeURIComponent(sessionId)}/runs?type=${encodeURIComponent(type)}`);
    $('runs').replaceChildren();
    const title = document.createElement('h3');
    title.textContent = `Runs in ${sessionId}`;
    $('runs').append(title);
    if (!runs.length) $('runs').append(row('No persisted runs', ''));
    for (const run of runs) {
      const details = [run.status || run.run_status || 'Status unavailable'];
      if (run.duration_ms != null) details.push(`${run.duration_ms} ms`);
      if (run.created_at) details.push(String(run.created_at));
      const item = row(run.run_id || run.id || 'Run', details.join(' · '));
      const link = traceLink(run.trace_id || run.trace?.trace_id);
      if (link) item.append(link);
      $('runs').append(item);
    }
  } catch (error) { showError('runs', error); }
}

async function loadSessions() {
  $('runs').replaceChildren();
  try {
    const type = $('session-type').value;
    const data = await read(`/api/sessions?type=${type}`);
    $('sessions').replaceChildren();
    if (!data.data.length) $('sessions').append(row('No persisted sessions', ''));
    for (const session of data.data) {
      const button = document.createElement('button');
      button.className = 'session-button';
      button.type = 'button';
      button.textContent = session.session_name || session.session_id || 'Unnamed session';
      button.addEventListener('click', () => loadRuns(session.session_id, type));
      $('sessions').append(button);
    }
  } catch (error) { showError('sessions', error); }
}

async function loadLogs() {
  try {
    const params = new URLSearchParams({ hours: $('time-range').value, text: $('log-text').value, level: $('log-level').value });
    const data = await read(`/api/logs?${params}`);
    $('logs').replaceChildren();
    if (!data.length) $('logs').append(row('No logs in this range', ''));
    for (const entry of data) {
      const item = document.createElement('div');
      item.className = 'log-entry';
      const message = document.createElement('span');
      message.textContent = entry.message;
      const details = document.createElement('small');
      details.textContent = `${new Date(entry.time).toLocaleString()} · ${entry.labels.job || 'application'}${entry.run_id ? ` · run ${entry.run_id}` : ''}`;
      item.append(message, details);
      const link = traceLink(entry.trace_id);
      if (link) item.append(link);
      $('logs').append(item);
    }
  } catch (error) { showError('logs', error); }
}

async function refresh() {
  $('notice').textContent = '';
  try { await loadConfig(); } catch (error) { $('notice').textContent = error.message; }
  await Promise.all([loadStatus(), loadEntities(), loadMetrics(), loadHistory(), loadSessions(), loadLogs()]);
}

$('refresh').addEventListener('click', refresh);
$('session-type').addEventListener('change', loadSessions);
$('time-range').addEventListener('change', () => Promise.all([loadHistory(), loadLogs()]));
$('log-filters').addEventListener('submit', (event) => { event.preventDefault(); loadLogs(); });
refresh();

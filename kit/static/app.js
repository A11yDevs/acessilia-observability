const $ = (id) => document.getElementById(id);

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
  $(id).replaceChildren();
  const message = document.createElement('p');
  message.className = 'error';
  message.textContent = error.message;
  $(id).append(message);
}

async function loadConfig() {
  const config = await read('/api/config');
  $('project-name').textContent = config.project_name;
  $('project-id').textContent = config.project_id;
  $('environment').textContent = config.environment;
  document.title = `${config.project_name} · Observability`;
  $('langfuse-link').hidden = !config.langfuse_ui_url;
  if (config.langfuse_ui_url) $('langfuse-link').href = config.langfuse_ui_url;
  if (!config.configured) $('notice').textContent = 'Set agentos_url in config.py to connect an AgentOS instance.';
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
    $('agentos-status').textContent = 'Unavailable';
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

async function loadSessions() {
  try {
    const type = $('session-type').value;
    const data = await read(`/api/sessions?type=${type}`);
    $('sessions').replaceChildren();
    if (!data.data.length) $('sessions').append(row('No persisted sessions', ''));
    for (const session of data.data) $('sessions').append(row(session.session_name || session.session_id, session.session_id));
  } catch (error) { showError('sessions', error); }
}

async function loadLogs() {
  try {
    const data = await read('/api/logs');
    $('logs').replaceChildren();
    if (!data.length) $('logs').append(row('No logs received', ''));
    for (const entry of data) $('logs').append(row(entry.message, entry.labels.job || ''));
  } catch (error) { showError('logs', error); }
}

async function refresh() {
  $('notice').textContent = '';
  try { await loadConfig(); } catch (error) { $('notice').textContent = error.message; }
  await Promise.all([loadEntities(), loadMetrics(), loadSessions(), loadLogs()]);
}

$('refresh').addEventListener('click', refresh);
$('session-type').addEventListener('change', loadSessions);
refresh();

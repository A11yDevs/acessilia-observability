import { renderHistory } from './charts.js';
import { refreshCentral } from './central.js';

const $ = (id) => document.getElementById(id);
const labels = { agentos: 'Runtime Agno', prometheus: 'Prometheus', collector: 'Alloy', loki: 'Loki', tempo: 'Tempo', langfuse: 'Langfuse' };
const stateLabels = { connected: 'Conectado', delivered: 'Enviando dados', degraded: 'Atenção', no_data: 'Sem dados', not_configured: 'Não configurado', unavailable: 'Indisponível' };
let config = {};

async function read(url) {
  const response = await fetch(url);
  const body = await response.json().catch(() => { throw new Error('Resposta inválida do servidor.'); });
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function message(text, className = 'empty-state') {
  const item = document.createElement('p');
  item.className = className;
  item.textContent = text;
  return item;
}

function row(label, value) {
  const item = document.createElement('div');
  item.className = 'row';
  const name = document.createElement('span');
  const detail = document.createElement('small');
  name.textContent = label;
  detail.textContent = String(value ?? '');
  item.append(name, detail);
  return item;
}

function showError(id, error) {
  $(id).replaceChildren(message(error.message, 'error-text'));
}

function setNotice(text) {
  $('notice').textContent = text;
  $('notice').hidden = !text;
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
  link.textContent = `Ver trace ${traceId.slice(0, 12)}…`;
  return link;
}

async function loadConfig() {
  config = await read('/api/config');
  $('brand-name').textContent = config.project_name;
  $('project-id').textContent = config.project_id;
  $('environment').textContent = `Ambiente ${config.environment}`;
  document.title = `${config.project_name} · Observabilidade`;
  $('grafana-link').href = `${config.grafana_ui_url.replace(/\/$/, '')}/d/agno-observability/agno-observability`;
  $('langfuse-link').hidden = !config.langfuse_ui_url;
  if (config.langfuse_ui_url) $('langfuse-link').href = config.langfuse_ui_url;
  $('console-link').hidden = !config.test_console_enabled;
}

function sourceClass(source) {
  if (['connected', 'delivered'].includes(source.state)) return 'online';
  if (source.state === 'degraded') return 'degraded';
  if (source.state === 'unavailable') return 'offline';
  return '';
}

async function loadStatus() {
  try {
    const data = await read('/api/status');
    $('service-band').replaceChildren();
    $('source-status').replaceChildren();
    for (const [name, source] of Object.entries(data)) {
      const item = document.createElement('div');
      item.className = `service-item ${sourceClass(source)}`;
      const dot = document.createElement('span');
      dot.className = 'status-dot';
      dot.setAttribute('aria-hidden', 'true');
      const content = document.createElement('span');
      const title = document.createElement('strong');
      title.textContent = labels[name] || name;
      const summary = document.createElement('small');
      summary.textContent = stateLabels[source.state] || source.state;
      content.append(title, summary);
      item.append(dot, content);
      $('service-band').append(item);

      const details = document.createElement('div');
      details.className = 'source-item';
      const heading = document.createElement('strong');
      heading.textContent = labels[name] || name;
      const badge = document.createElement('span');
      badge.className = `source-state ${sourceClass(source)}`;
      badge.textContent = stateLabels[source.state] || source.state;
      const note = document.createElement('small');
      note.textContent = source.last_seen ? `Último dado: ${new Date(source.last_seen).toLocaleString('pt-BR')}` : source.detail;
      details.append(heading, badge, note);
      $('source-status').append(details);
    }
    const failures = Object.values(data).some((source) => ['unavailable', 'degraded'].includes(source.state));
    const status = $('overall-status');
    status.className = `overall-status ${failures ? 'degraded' : 'online'}`;
    status.textContent = failures ? 'Algumas fontes precisam de atenção' : 'Fontes verificadas';
  } catch (error) {
    showError('service-band', error);
    showError('source-status', error);
    $('overall-status').textContent = 'Falha ao verificar serviços';
    $('overall-status').className = 'overall-status offline';
  }
}

async function loadEntities() {
  try {
    const data = await read('/api/entities');
    $('agentos-status').textContent = 'Conectado';
    $('agentos-status').className = 'source-state online';
    $('agentos-meta').textContent = `Agno ${data.version || 'versão desconhecida'} · ${data.name || 'AgentOS'}`;
    $('entities').replaceChildren();
    let count = 0;
    for (const [kind, label] of [['agents', 'Agentes'], ['teams', 'Times'], ['workflows', 'Workflows']]) {
      for (const entity of data[kind] || []) {
        count += 1;
        const card = document.createElement('div');
        card.className = 'entity-card';
        const name = document.createElement('strong');
        name.textContent = entity.name;
        const detail = document.createElement('small');
        detail.textContent = `${label} · ${entity.id}`;
        card.append(name, detail);
        $('entities').append(card);
      }
    }
    if (!$('entities').children.length) $('entities').append(message('Nenhum componente registrado no AgentOS.'));
    $('overview-agno').textContent = `${count} componente(s) disponível(is) · Agno ${data.version || 'versão desconhecida'}`;
  } catch (error) {
    $('agentos-status').textContent = config.configured ? 'Indisponível' : 'Não configurado';
    $('agentos-status').className = 'source-state degraded';
    $('agentos-meta').textContent = error.message;
    $('entities').replaceChildren();
    $('overview-agno').textContent = config.configured ? 'AgentOS indisponível.' : 'Configure agentos_url em config.py para descobrir componentes.';
  }
}

function kpi(label, value, detail) {
  const item = document.createElement('article');
  item.className = 'kpi-card';
  const title = document.createElement('span');
  const amount = document.createElement('strong');
  const caption = document.createElement('small');
  title.textContent = label;
  amount.textContent = value;
  caption.textContent = detail;
  item.append(title, amount, caption);
  return item;
}

async function loadMetrics() {
  try {
    const data = await read('/api/metrics');
    $('metrics').replaceChildren();
    for (const [name, samples] of Object.entries(data)) {
      if (!samples.length) $('metrics').append(row(name, 'Sem amostras'));
      for (const sample of samples) $('metrics').append(row(name, `${sample.value} ${sample.labels.instance || ''}`.trim()));
    }
    if (!Object.keys(data).length) $('metrics').append(message('Nenhuma consulta de métricas configurada.'));
  } catch (error) { showError('metrics', error); }
}

async function loadHistory() {
  try {
    const data = await read(`/api/metrics/range?hours=${$('time-range').value}`);
    renderHistory($('history'), data);
    const last = (key) => data[key]?.at(-1)?.value;
    const rate = last('Run rate');
    const error = last('Error rate');
    const duration = last('P95 duration');
    $('overview-kpis').replaceChildren(
      kpi('Execuções por segundo', rate == null ? '—' : rate.toFixed(2), 'Média recente'),
      kpi('Taxa de erro', error == null ? '—' : `${(error * 100).toFixed(1)}%`, 'Runs com erro'),
      kpi('Duração P95', duration == null ? '—' : `${duration.toFixed(2)} s`, '95º percentil'),
    );
    $('realtime-updated').textContent = `Atualizado ${new Date().toLocaleTimeString('pt-BR')}`;
  } catch (error) {
    renderHistory($('history'), { 'Run rate': [], 'Error rate': [], 'P95 duration': [] });
    $('overview-kpis').replaceChildren(
      kpi('Execuções por segundo', '—', 'Prometheus indisponível'),
      kpi('Taxa de erro', '—', 'Prometheus indisponível'),
      kpi('Duração P95', '—', 'Prometheus indisponível'),
    );
    $('realtime-updated').textContent = 'Sem métricas de execução';
  }
}

async function loadRuns(sessionId, type) {
  $('runs').replaceChildren(message('Carregando execuções…'));
  try {
    const runs = await read(`/api/sessions/${encodeURIComponent(sessionId)}/runs?type=${encodeURIComponent(type)}`);
    $('runs').replaceChildren();
    if (!runs.length) $('runs').append(message('Nenhuma execução salva nesta sessão.'));
    for (const run of runs) {
      const item = document.createElement('article');
      item.className = 'run-entry';
      const name = document.createElement('strong');
      name.textContent = run.run_id || run.id || 'Execução';
      const detail = document.createElement('small');
      detail.textContent = [run.status || run.run_status, run.created_at].filter(Boolean).join(' · ');
      item.append(name, detail);
      const content = run.content ?? run.output;
      if (content != null) {
        const preview = document.createElement('p');
        preview.textContent = (typeof content === 'string' ? content : JSON.stringify(content)).slice(0, 300);
        item.append(preview);
      }
      const link = traceLink(run.trace_id || run.trace?.trace_id);
      if (link) item.append(link);
      $('runs').append(item);
    }
  } catch (error) { showError('runs', error); }
}

async function loadSessions() {
  $('runs').replaceChildren(message('Selecione uma sessão.'));
  try {
    const type = $('session-type').value;
    const data = await read(`/api/sessions?type=${type}`);
    $('sessions').replaceChildren();
    $('overview-sessions').replaceChildren();
    if (!data.data.length) $('sessions').append(message('Nenhuma sessão salva.'));
    if (!data.data.length) $('overview-sessions').append(message('Nenhuma sessão salva.'));
    for (const session of data.data) {
      const button = document.createElement('button');
      button.className = 'button session-button';
      button.type = 'button';
      button.textContent = session.session_name || session.session_id || 'Sessão sem nome';
      button.addEventListener('click', () => {
        $('sessions').querySelectorAll('button').forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        loadRuns(session.session_id || session.id, type);
      });
      $('sessions').append(button);
    }
    for (const session of data.data.slice(0, 4)) {
      $('overview-sessions').append(row(session.session_name || 'Sessão', session.session_id || session.id || ''));
    }
  } catch (error) {
    showError('sessions', error);
    $('overview-sessions').replaceChildren(message('Sessões indisponíveis.'));
  }
}

async function loadLogs() {
  try {
    const params = new URLSearchParams({ hours: $('time-range').value, text: $('log-text').value, level: $('log-level').value });
    const data = await read(`/api/logs?${params}`);
    $('logs').replaceChildren();
    if (!data.length) $('logs').append(message('Nenhum log neste período.'));
    for (const entry of data) {
      const item = document.createElement('article');
      item.className = 'log-entry';
      const body = document.createElement('p');
      body.textContent = entry.message;
      const detail = document.createElement('small');
      detail.textContent = `${new Date(entry.time).toLocaleString('pt-BR')} · ${entry.labels.job || 'aplicação'}${entry.run_id ? ` · run ${entry.run_id}` : ''}`;
      item.append(body, detail);
      const link = traceLink(entry.trace_id);
      if (link) item.append(link);
      $('logs').append(item);
    }
  } catch (error) { showError('logs', error); }
}

function activateTab(id) {
  for (const button of document.querySelectorAll('.workspace-tabs [role="tab"]')) {
    const active = button.dataset.tab === id;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    $(button.dataset.tab).hidden = !active;
  }
}

async function refresh() {
  setNotice('');
  try { await loadConfig(); } catch (error) { setNotice(error.message); }
  await refreshCentral();
  if (document.querySelector('.advanced-monitoring').open) {
    await Promise.all([loadStatus(), loadEntities(), loadMetrics(), loadHistory(), loadSessions(), loadLogs()]);
  }
  $('updated-at').textContent = new Date().toLocaleTimeString('pt-BR');
}

$('refresh').addEventListener('click', refresh);
window.addEventListener('observation-authenticated',refresh);
document.querySelector('.advanced-monitoring').addEventListener('toggle', () => {
  if (document.querySelector('.advanced-monitoring').open) refresh();
});
$('session-type').addEventListener('change', loadSessions);
$('time-range').addEventListener('change', () => Promise.all([loadHistory(), loadLogs()]));
$('log-filters').addEventListener('submit', (event) => { event.preventDefault(); loadLogs(); });
document.querySelectorAll('.workspace-tabs [role="tab"]').forEach((button, index, all) => {
  button.addEventListener('click', () => activateTab(button.dataset.tab));
  button.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const next = all[(index + (event.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length];
    activateTab(next.dataset.tab);
    next.focus();
  });
});
setInterval(() => {
  if ($('auto-refresh').checked && !document.hidden) {
    refreshCentral();
    if (document.querySelector('.advanced-monitoring').open) Promise.all([loadStatus(), loadMetrics(), loadHistory(), loadLogs()]);
    $('updated-at').textContent = new Date().toLocaleTimeString('pt-BR');
  }
}, 30_000);
refresh();

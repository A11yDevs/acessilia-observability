import { getConfig, getEntities, getRuns, getSessions, startRun } from './test-api.js';
import { readEvents } from './sse.js';
import { renderEntityButtons, renderSessionButtons } from './test-sidebar.js';

const $ = (id) => document.getElementById(id);
const groups = [['agents', 'Agent'], ['teams', 'Team'], ['workflows', 'Workflow']];
const state = { entities: [], entity: null, sessionId: '', runs: [], controller: null, runId: '', finalEvent: null, failed: false };

function text(value) {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(text).filter(Boolean).join('\n');
  if (typeof value === 'object' && (value.content != null || value.text != null)) return text(value.content ?? value.text);
  try { return JSON.stringify(value, null, 2); } catch { return ''; }
}

function setStatus(message, isError = false) {
  $('connection-status').textContent = message;
  $('connection-status').classList.toggle('error', isError);
  $('connection-status').classList.toggle('online', !isError);
  $('runtime-state').textContent = isError ? 'Indisponível' : 'Conectado';
  $('runtime-dot').className = `status-dot ${isError ? 'offline' : 'online'}`;
  $('entity-source-state').textContent = isError ? 'Indisponível' : 'AgentOS';
  $('entity-source-state').classList.toggle('error', isError);
}

function setRunState(message, isError = false) {
  $('run-state').textContent = message;
  $('run-state').classList.toggle('error', isError);
  $('run-state').classList.toggle('ok', message === 'Concluído');
}

function emptyConversation(message) {
  const note = document.createElement('p');
  note.className = 'empty-state';
  note.textContent = message;
  $('conversation').replaceChildren(note);
}

function addMessage(role, content = '') {
  if ($('conversation').querySelector('.empty-state')) $('conversation').replaceChildren();
  const article = document.createElement('article');
  article.className = `chat-message ${role === 'Você' ? 'from-user' : 'from-component'}`;
  const label = document.createElement('strong');
  label.textContent = role;
  const body = document.createElement('pre');
  body.textContent = content;
  article.append(label, body);
  $('conversation').append(article);
  article.scrollIntoView({ block: 'nearest' });
  return body;
}

function addTimeline(name, payload = {}) {
  const list = $('event-timeline');
  if (list.querySelector('.empty-state')) list.replaceChildren();
  const item = document.createElement('li');
  const title = document.createElement('strong');
  title.textContent = name;
  const detail = document.createElement('span');
  const context = [payload.step_name, payload.agent_name, payload.team_name].find((value) => typeof value === 'string' && value);
  const info = payload.error || payload.reason || context || (payload.step_index != null ? `Etapa ${payload.step_index}` : '');
  detail.textContent = typeof info === 'string' ? info.slice(0, 300) : '';
  const time = document.createElement('time');
  const eventTime = typeof payload.created_at === 'number' ? new Date(payload.created_at * 1000) : new Date();
  time.textContent = eventTime.toLocaleTimeString('pt-BR');
  item.append(title, detail, time);
  list.append(item);
  if (list.children.length > 100) list.firstElementChild.remove();
  list.scrollTop = list.scrollHeight;
}

function emptyTimeline(message) {
  const note = document.createElement('li');
  note.className = 'empty-state';
  note.textContent = message;
  $('event-timeline').replaceChildren(note);
}

function numericMetrics(value, path = []) {
  if (typeof value === 'number') return Number.isFinite(value) ? [[path.join(' · '), value]] : [];
  if (Array.isArray(value)) return value.flatMap((item, index) => numericMetrics(item, [...path, String(index + 1)]));
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) => numericMetrics(item, [...path, key]));
  }
  return [];
}

function showResult(run, source) {
  $('run-details').replaceChildren();
  if (!run) {
    $('result-note').textContent = source || 'Nenhum resultado salvo ainda.';
    return;
  }
  $('result-note').textContent = source;
  const values = [
    ['ID da execução', run.run_id || run.id],
    ['Status', run.status || run.run_status],
    ['Duração', run.duration_ms != null ? `${run.duration_ms} ms` : null],
  ];
  for (const [label, value] of numericMetrics(run.metrics)) {
    const unit = /^(duration|time_to_first_token)$/.test(label.split(' · ').at(-1)) ? ' s' : '';
    values.push([`Métrica · ${label}`, `${value}${unit}`]);
  }
  for (const [label, value] of values) {
    if (value == null || value === '') continue;
    const term = document.createElement('dt');
    const definition = document.createElement('dd');
    term.textContent = label;
    definition.textContent = String(value);
    $('run-details').append(term, definition);
  }
  if (!$('run-details').children.length) $('result-note').textContent = 'A execução terminou sem detalhes.';
}

function showSavedRun(index) {
  const run = state.runs[index];
  if (!run) return;
  const status = String(run.status || run.run_status || '');
  setRunState(/complete|success/i.test(status) ? 'Concluído' : /error|fail/i.test(status) ? 'Falhou' : 'Salva', /error|fail/i.test(status));
  $('event-timeline').replaceChildren();
  const events = Array.isArray(run.events) ? run.events : [];
  for (const event of events) {
    if (event && typeof event === 'object') addTimeline(event.event || 'Event', event);
  }
  if (!events.length) emptyTimeline('Nenhum evento salvo para esta execução.');
  showResult(run, 'Execução salva');
}

function updateRunPicker(index = state.runs.length - 1) {
  const picker = $('run-select');
  picker.replaceChildren();
  for (const [position, run] of state.runs.entries()) {
    const input = text(run.run_input ?? run.input ?? run.message).replace(/\s+/g, ' ').slice(0, 28);
    picker.add(new Option(`Execução ${position + 1}${input ? ` · ${input}` : ''}`, String(position)));
  }
  picker.disabled = !state.runs.length;
  if (!state.runs.length) picker.add(new Option('Nenhuma execução salva', ''));
  else picker.value = String(index);
}

function renderEntityLists() {
  renderEntityButtons(state.entities, state.entity, Boolean(state.controller), (index) => {
    $('entity-select').value = String(index);
    selectEntity();
  });
}

function renderSessionList() {
  renderSessionButtons($('session-select').options, state.sessionId, Boolean(state.entity), Boolean(state.controller), (sessionId) => {
    $('session-select').value = sessionId;
    selectSession();
  });
}

function renderHistory() {
  $('conversation').replaceChildren();
  $('event-timeline').replaceChildren();
  updateRunPicker();
  if (!state.runs.length) {
    setRunState('Aguardando');
    emptyConversation('Nenhuma execução salva nesta sessão. Envie uma mensagem para começar.');
    showResult(null, 'Nenhuma execução salva ainda.');
    emptyTimeline('Nenhum evento salvo nesta sessão.');
    return;
  }
  for (const run of state.runs) {
    const input = text(run.run_input ?? run.input ?? run.message ?? run.input_content);
    const output = text(run.content ?? run.output ?? run.response);
    if (input) addMessage('Você', input);
    if (output) addMessage(state.entity?.name || 'Resposta', output);
  }
  showSavedRun(state.runs.length - 1);
}

async function loadRuns() {
  if (!state.sessionId || !state.entity) return;
  const sessionId = state.sessionId;
  const entity = state.entity;
  try {
    const runs = await getRuns(sessionId, entity.type);
    if (state.sessionId !== sessionId || state.entity !== entity) return;
    state.runs = runs;
    renderHistory();
  } catch (error) {
    if (state.sessionId !== sessionId || state.entity !== entity) return;
    state.runs = [];
    updateRunPicker();
    emptyConversation(`Histórico da sessão indisponível: ${error.message}`);
    emptyTimeline('Eventos salvos indisponíveis.');
    showResult(null, 'Nenhuma execução salva disponível.');
    setRunState('Indisponível', true);
  }
}

async function selectSession() {
  state.sessionId = $('session-select').value;
  $('session-pill').textContent = state.sessionId ? `Sessão ${state.sessionId.slice(0, 12)}` : 'Sem sessão';
  state.runs = [];
  updateRunPicker();
  renderSessionList();
  if (state.sessionId) await loadRuns();
  else {
    emptyConversation('Envie uma mensagem para iniciar uma conversa.');
    emptyTimeline('Os eventos aparecerão durante a execução.');
    showResult(null, 'Nenhuma execução ainda.');
    setRunState('Aguardando');
  }
}

async function loadSessions() {
  const picker = $('session-select');
  picker.replaceChildren(new Option('Nova conversa', ''));
  picker.disabled = !state.entity || Boolean(state.controller);
  if (!state.entity) {
    renderSessionList();
    return;
  }
  const entity = state.entity;
  try {
    const result = await getSessions(entity.type, entity.id);
    if (state.entity !== entity) return;
    for (const session of result.data || []) {
      const id = session.session_id || session.id;
      if (!id) continue;
      picker.add(new Option(session.session_name || String(id), String(id)));
    }
    $('session-note').textContent = 'Escolha uma sessão existente ou inicie uma nova.';
  } catch (error) {
    if (state.entity !== entity) return;
    $('session-note').textContent = `Sessões salvas indisponíveis: ${error.message}`;
  }
  if (state.sessionId && !Array.from(picker.options).some((option) => option.value === state.sessionId)) {
    picker.add(new Option(`Sessão atual · ${state.sessionId}`, state.sessionId));
  }
  picker.value = state.sessionId;
  renderSessionList();
}

async function selectEntity() {
  state.entity = state.entities[Number($('entity-select').value)] || null;
  state.sessionId = '';
  state.runs = [];
  updateRunPicker();
  $('message').disabled = !state.entity;
  $('send-message').disabled = !state.entity;
  $('new-session').disabled = !state.entity;
  $('conversation-heading').textContent = state.entity?.name || 'Selecione uma entidade';
  $('session-pill').textContent = 'Sem sessão';
  $('target-note').textContent = state.entity ? `${state.entity.type} · ${state.entity.id}` : 'Nenhum componente selecionado.';
  emptyConversation(state.entity ? 'Envie uma mensagem para iniciar uma conversa.' : 'Selecione uma entidade para começar.');
  emptyTimeline('Os eventos aparecerão durante a execução.');
  showResult(null, 'Nenhuma execução ainda.');
  setRunState('Aguardando');
  renderEntityLists();
  await loadSessions();
}

async function loadTargets() {
  if (state.controller) return;
  const previous = state.entity;
  const previousSessionId = state.sessionId;
  $('reload-targets').disabled = true;
  $('run-select').disabled = true;
  try {
    const discovery = await getEntities();
    state.entities = groups.flatMap(([key, label]) => (discovery[key] || []).map((entity) => ({ ...entity, type: entity.type || label.toLowerCase() })));
    const picker = $('entity-select');
    picker.replaceChildren();
    let offset = 0;
    for (const [key, label] of groups) {
      const items = discovery[key] || [];
      if (!items.length) continue;
      const group = document.createElement('optgroup');
      group.label = { agents: 'Agentes', teams: 'Times', workflows: 'Workflows' }[key];
      for (const entity of items) group.append(new Option(entity.name || entity.id, String(offset++)));
      picker.append(group);
    }
    picker.disabled = !state.entities.length;
    if (state.entities.length) {
      const selected = state.entities.findIndex((entity) => entity.id === previous?.id && entity.type === previous?.type);
      picker.value = String(selected >= 0 ? selected : 0);
      $('entity-count').textContent = `${state.entities.length} componente(s)`;
      setStatus(`${state.entities.length} componente(s) disponível(is)`);
    } else {
      picker.add(new Option('Nenhum componente encontrado', ''));
      $('entity-count').textContent = 'Nenhuma entidade';
      setStatus('AgentOS não retornou agentes, times ou workflows.');
    }
    await selectEntity();
    if (previousSessionId && state.entity?.id === previous?.id && state.entity?.type === previous?.type) {
      state.sessionId = previousSessionId;
      await loadSessions();
      await loadRuns();
      $('session-pill').textContent = `Sessão ${state.sessionId.slice(0, 12)}`;
      renderSessionList();
    }
  } catch (error) {
    state.entities = [];
    state.entity = null;
    state.sessionId = '';
    state.runs = [];
    updateRunPicker();
    $('entity-select').replaceChildren(new Option('Descoberta indisponível', ''));
    $('entity-select').disabled = true;
    $('session-select').replaceChildren(new Option('Nova conversa', ''));
    $('session-select').disabled = true;
    $('message').disabled = true;
    $('send-message').disabled = true;
    $('entity-count').textContent = 'Indisponível';
    $('new-session').disabled = true;
    $('conversation-heading').textContent = 'Selecione uma entidade';
    $('session-pill').textContent = 'Sem sessão';
    renderEntityLists();
    renderSessionList();
    emptyConversation('Selecione uma entidade para começar.');
    emptyTimeline('Os eventos aparecerão durante a execução.');
    showResult(null, 'Nenhuma execução ainda.');
    setStatus(error.message, true);
  } finally {
    $('reload-targets').disabled = false;
    $('run-select').disabled = !state.runs.length;
  }
}

function handleFrame(frame, answer) {
  let payload;
  try { payload = JSON.parse(frame.data); } catch { payload = { content: frame.data }; }
  if (!payload || typeof payload !== 'object') payload = { content: String(payload) };
  const name = frame.event === 'message' ? payload.event || 'message' : frame.event;
  if (payload.session_id && !state.sessionId) state.sessionId = String(payload.session_id);
  if (payload.run_id) state.runId = String(payload.run_id);
  if (name === 'error') throw new Error(payload.error || payload.detail || 'O proxy interrompeu a execução.');
  if (['RunContent', 'WorkflowRunContent', 'TeamRunContent'].includes(name)) {
    if (typeof payload.content === 'string') answer.textContent += payload.content;
    return;
  }
  if (['RunCompleted', 'WorkflowCompleted', 'TeamRunCompleted'].includes(name)) {
    state.finalEvent = payload;
    if (payload.content != null && !answer.textContent) answer.textContent = text(payload.content);
  }
  if (/Error$|Cancelled$|Paused$/.test(name)) state.failed = true;
  addTimeline(name, payload);
}

async function submitMessage(event) {
  event.preventDefault();
  if (!state.entity || state.controller) return;
  const message = $('message').value.trim();
  if (!message) return;
  state.controller = new AbortController();
  state.runId = '';
  state.finalEvent = null;
  state.failed = false;
  $('message').value = '';
  $('message').disabled = true;
  $('send-message').disabled = true;
  $('session-select').disabled = true;
  $('entity-select').disabled = true;
  $('new-session').disabled = true;
  $('reload-targets').disabled = true;
  $('run-select').disabled = true;
  $('stop-run').hidden = false;
  $('event-timeline').replaceChildren();
  addMessage('Você', message);
  const answer = addMessage(state.entity.name || 'Resposta', '');
  showResult(null, 'Aguardando o fim da execução…');
  setRunState('Executando');
  renderEntityLists();
  renderSessionList();
  try {
    const response = await startRun({ entityType: state.entity.type, entityId: state.entity.id, message, sessionId: state.sessionId, signal: state.controller.signal });
    state.sessionId = response.headers.get('X-Session-Id') || state.sessionId;
    $('session-pill').textContent = state.sessionId ? `Sessão ${state.sessionId.slice(0, 12)}` : 'Sem sessão';
    for await (const frame of readEvents(response)) handleFrame(frame, answer);
    setRunState(state.failed ? 'Atenção' : 'Concluído', state.failed);
    if (state.finalEvent) showResult(state.finalEvent, 'Resultado em tempo real');
    if (state.sessionId) {
      try {
        const runs = await getRuns(state.sessionId, state.entity.type);
        const knownIds = new Set(state.runs.map((run) => run.run_id || run.id));
        const saved = runs.find((run) => (run.run_id || run.id) === state.runId) || runs.find((run) => !knownIds.has(run.run_id || run.id));
        state.runs = runs;
        if (saved) {
          const savedIndex = runs.indexOf(saved);
          updateRunPicker(savedIndex);
          showSavedRun(savedIndex);
          if (!answer.textContent) answer.textContent = text(saved.content ?? saved.output ?? saved.response);
        } else if (!state.finalEvent) {
          showResult(null, 'O AgentOS não retornou uma execução salva.');
        }
      } catch { if (!state.finalEvent) showResult(null, 'Histórico da sessão indisponível.'); }
    }
    if (!answer.textContent) answer.textContent = state.failed ? 'A execução terminou sem resposta.' : 'Nenhuma resposta em texto foi retornada.';
  } catch (error) {
    if (error.name === 'AbortError') {
      setRunState('Stream fechado');
      addTimeline('Stream fechado', { reason: 'A execução no AgentOS pode continuar.' });
    } else {
      setRunState('Falhou', true);
      addTimeline('Erro', { error: error.message });
      showResult(null, error.message);
    }
    if (!answer.textContent) answer.textContent = 'Sem resposta.';
  } finally {
    state.controller = null;
    $('message').disabled = false;
    $('send-message').disabled = false;
    $('entity-select').disabled = false;
    $('new-session').disabled = false;
    $('reload-targets').disabled = false;
    $('run-select').disabled = !state.runs.length;
    $('stop-run').hidden = true;
    await loadSessions();
    renderEntityLists();
    $('message').focus();
  }
}

$('entity-select').addEventListener('change', selectEntity);
$('session-select').addEventListener('change', selectSession);
$('new-session').addEventListener('click', () => { $('session-select').value = ''; selectSession(); });
$('clear-chat').addEventListener('click', () => {
  if (!state.controller) emptyConversation('Conversa limpa da tela. O histórico salvo continua disponível na sessão.');
});
$('run-select').addEventListener('change', () => showSavedRun(Number($('run-select').value)));
$('reload-targets').addEventListener('click', loadTargets);
$('message-form').addEventListener('submit', submitMessage);
$('message').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('message-form').requestSubmit();
  }
});
$('stop-run').addEventListener('click', () => state.controller?.abort());

try {
  const config = await getConfig();
  $('project-name').textContent = config.project_name || config.project_id || 'Observabilidade';
  $('brand-name').textContent = config.project_name || 'Observabilidade';
  $('environment').textContent = config.environment || 'Ambiente desconhecido';
  $('grafana-link').href = `${config.grafana_ui_url.replace(/\/$/, '')}/d/agno-observability/agno-observability`;
  $('langfuse-link').hidden = !config.langfuse_ui_url;
  if (config.langfuse_ui_url) $('langfuse-link').href = config.langfuse_ui_url;
  document.title = `Console Agno · ${config.project_name || 'Observabilidade'}`;
  if (config.configured) await loadTargets();
  else {
    $('entity-select').replaceChildren(new Option('Conecte o AgentOS primeiro', ''));
    $('entity-count').textContent = 'Não configurado';
    renderEntityLists();
    renderSessionList();
    setStatus('Configure agentos_url em config.py para conectar o AgentOS.', true);
    $('runtime-state').textContent = 'Não configurado';
  }
} catch (error) { setStatus(error.message, true); }

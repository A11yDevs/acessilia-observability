import { getConfig, getEntities, getRuns, getSessions, startRun } from './test-api.js';
import { readEvents } from './sse.js';

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
}

function setRunState(message, isError = false) {
  $('run-state').textContent = message;
  $('run-state').classList.toggle('error', isError);
  $('run-state').classList.toggle('ok', message === 'Complete');
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
  article.className = `chat-message ${role === 'You' ? 'from-user' : 'from-component'}`;
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
  const info = payload.error || payload.reason || context || (payload.step_index != null ? `Step ${payload.step_index}` : '');
  detail.textContent = typeof info === 'string' ? info.slice(0, 300) : '';
  const time = document.createElement('time');
  const eventTime = typeof payload.created_at === 'number' ? new Date(payload.created_at * 1000) : new Date();
  time.textContent = eventTime.toLocaleTimeString();
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
    $('result-note').textContent = source || 'No saved result is available yet.';
    return;
  }
  $('result-note').textContent = source;
  const values = [
    ['Run ID', run.run_id || run.id],
    ['Status', run.status || run.run_status],
    ['Duration', run.duration_ms != null ? `${run.duration_ms} ms` : null],
  ];
  for (const [label, value] of numericMetrics(run.metrics)) {
    const unit = /^(duration|time_to_first_token)$/.test(label.split(' · ').at(-1)) ? ' s' : '';
    values.push([`Metrics · ${label}`, `${value}${unit}`]);
  }
  for (const [label, value] of values) {
    if (value == null || value === '') continue;
    const term = document.createElement('dt');
    const definition = document.createElement('dd');
    term.textContent = label;
    definition.textContent = String(value);
    $('run-details').append(term, definition);
  }
  if (!$('run-details').children.length) $('result-note').textContent = 'The run completed, but no details were returned.';
}

function showSavedRun(index) {
  const run = state.runs[index];
  if (!run) return;
  $('event-timeline').replaceChildren();
  const events = Array.isArray(run.events) ? run.events : [];
  for (const event of events) {
    if (event && typeof event === 'object') addTimeline(event.event || 'Event', event);
  }
  if (!events.length) emptyTimeline('No saved events for this run.');
  showResult(run, 'Saved run');
}

function updateRunPicker(index = state.runs.length - 1) {
  const picker = $('run-select');
  picker.replaceChildren();
  for (const [position, run] of state.runs.entries()) {
    const input = text(run.run_input ?? run.input ?? run.message).replace(/\s+/g, ' ').slice(0, 28);
    picker.add(new Option(`Run ${position + 1}${input ? ` · ${input}` : ''}`, String(position)));
  }
  picker.disabled = !state.runs.length;
  if (!state.runs.length) picker.add(new Option('No saved runs', ''));
  else picker.value = String(index);
}

function renderHistory() {
  $('conversation').replaceChildren();
  $('event-timeline').replaceChildren();
  updateRunPicker();
  if (!state.runs.length) {
    emptyConversation('No saved runs in this session. Send a message to begin.');
    showResult(null, 'No saved run yet.');
    emptyTimeline('No saved events in this session.');
    return;
  }
  for (const run of state.runs) {
    const input = text(run.run_input ?? run.input ?? run.message ?? run.input_content);
    const output = text(run.content ?? run.output ?? run.response);
    if (input) addMessage('You', input);
    if (output) addMessage(state.entity?.name || 'Response', output);
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
    emptyConversation(`Session history is unavailable: ${error.message}`);
    emptyTimeline('Saved events are unavailable.');
    showResult(null, 'No saved run is available.');
  }
}

async function loadSessions() {
  const picker = $('session-select');
  picker.replaceChildren(new Option('New conversation', ''));
  picker.disabled = !state.entity || Boolean(state.controller);
  if (!state.entity) return;
  const entity = state.entity;
  try {
    const result = await getSessions(entity.type, entity.id);
    if (state.entity !== entity) return;
    for (const session of result.data || []) {
      const id = session.session_id || session.id;
      if (!id) continue;
      picker.add(new Option(session.session_name || String(id), String(id)));
    }
    $('session-note').textContent = 'Choose an existing session or start a new one.';
  } catch (error) {
    if (state.entity !== entity) return;
    $('session-note').textContent = `Saved sessions unavailable: ${error.message}`;
  }
  if (state.sessionId && !Array.from(picker.options).some((option) => option.value === state.sessionId)) {
    picker.add(new Option(`Current session · ${state.sessionId}`, state.sessionId));
  }
  picker.value = state.sessionId;
}

async function selectEntity() {
  state.entity = state.entities[Number($('entity-select').value)] || null;
  state.sessionId = '';
  state.runs = [];
  updateRunPicker();
  $('message').disabled = !state.entity;
  $('send-message').disabled = !state.entity;
  $('target-note').textContent = state.entity ? `${state.entity.type} · ${state.entity.id}` : 'No component selected.';
  emptyConversation(state.entity ? 'Send a message to start a new conversation.' : 'Choose a component to begin.');
  emptyTimeline('Events will appear during a run.');
  showResult(null, 'No run yet.');
  setRunState('Idle');
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
      group.label = `${label}s`;
      for (const entity of items) group.append(new Option(entity.name || entity.id, String(offset++)));
      picker.append(group);
    }
    picker.disabled = !state.entities.length;
    if (state.entities.length) {
      const selected = state.entities.findIndex((entity) => entity.id === previous?.id && entity.type === previous?.type);
      picker.value = String(selected >= 0 ? selected : 0);
      setStatus(`${state.entities.length} components available`);
    } else {
      picker.add(new Option('No components found', ''));
      setStatus('AgentOS returned no agents, teams or workflows.');
    }
    await selectEntity();
    if (previousSessionId && state.entity?.id === previous?.id && state.entity?.type === previous?.type) {
      state.sessionId = previousSessionId;
      await loadSessions();
      await loadRuns();
    }
  } catch (error) {
    state.entities = [];
    state.entity = null;
    state.sessionId = '';
    state.runs = [];
    updateRunPicker();
    $('entity-select').replaceChildren(new Option('Discovery unavailable', ''));
    $('entity-select').disabled = true;
    $('session-select').replaceChildren(new Option('New conversation', ''));
    $('session-select').disabled = true;
    $('message').disabled = true;
    $('send-message').disabled = true;
    emptyConversation('Choose a component to begin.');
    emptyTimeline('Events will appear during a run.');
    showResult(null, 'No run yet.');
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
  if (name === 'error') throw new Error(payload.error || payload.detail || 'The proxy stopped the run.');
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
  $('reload-targets').disabled = true;
  $('run-select').disabled = true;
  $('stop-run').hidden = false;
  $('event-timeline').replaceChildren();
  addMessage('You', message);
  const answer = addMessage(state.entity.name || 'Response', '');
  showResult(null, 'Waiting for the run to finish…');
  setRunState('Running');
  try {
    const response = await startRun({ entityType: state.entity.type, entityId: state.entity.id, message, sessionId: state.sessionId, signal: state.controller.signal });
    state.sessionId = response.headers.get('X-Session-Id') || state.sessionId;
    for await (const frame of readEvents(response)) handleFrame(frame, answer);
    setRunState(state.failed ? 'Needs attention' : 'Complete', state.failed);
    if (state.finalEvent) showResult(state.finalEvent, 'Streamed result');
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
          showResult(null, 'No saved run was returned by AgentOS.');
        }
      } catch { if (!state.finalEvent) showResult(null, 'Session history is unavailable.'); }
    }
    if (!answer.textContent) answer.textContent = state.failed ? 'Run ended without a response.' : 'No text response was returned.';
  } catch (error) {
    if (error.name === 'AbortError') {
      setRunState('Stream closed');
      addTimeline('Stream closed', { reason: 'The AgentOS run may continue.' });
    } else {
      setRunState('Failed', true);
      addTimeline('Error', { error: error.message });
      showResult(null, error.message);
    }
    if (!answer.textContent) answer.textContent = 'No response.';
  } finally {
    state.controller = null;
    $('message').disabled = false;
    $('send-message').disabled = false;
    $('entity-select').disabled = false;
    $('reload-targets').disabled = false;
    $('run-select').disabled = !state.runs.length;
    $('stop-run').hidden = true;
    await loadSessions();
    $('message').focus();
  }
}

$('entity-select').addEventListener('change', selectEntity);
$('session-select').addEventListener('change', async () => {
  state.sessionId = $('session-select').value;
  state.runs = [];
  updateRunPicker();
  if (state.sessionId) await loadRuns();
  else {
    emptyConversation('Send a message to start a new conversation.');
    emptyTimeline('Events will appear during a run.');
    showResult(null, 'No run yet.');
    setRunState('Idle');
  }
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
  $('project-name').textContent = config.project_name || config.project_id || 'Observability';
  $('environment').textContent = config.environment || 'Environment unknown';
  document.title = `Test console · ${config.project_name || 'Observability'}`;
  if (config.configured) await loadTargets();
  else {
    $('entity-select').replaceChildren(new Option('Connect AgentOS first', ''));
    setStatus('Set agentos_url in config.py to connect an AgentOS instance.', true);
  }
} catch (error) { setStatus(error.message, true); }

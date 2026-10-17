const $ = (id) => document.getElementById(id);
const states = { queued: 'Na fila', running: 'Em execução', succeeded: 'Concluído', failed: 'Falhou', cancelled: 'Cancelado', retrying: 'Nova tentativa', skipped: 'Ignorado', connected: 'Conectado', degraded: 'Atenção', unavailable: 'Indisponível', unauthorized: 'Token recusado', not_configured: 'Não configurado' };
const phases = { intake: 'Entrada', queue: 'Fila', cache: 'Cache', manifest: 'Manifesto', media_inspect: 'Inspeção', enrichment: 'Enriquecimento', planning: 'Planejamento', execution: 'Execução', validation: 'Validação', export: 'Exportação', delivery: 'Entrega', model: 'Modelo', tool: 'Toolbox / ferramenta' };
const attributeLabels = { selected: 'Escolha', alternatives: 'Alternativas', reason_code: 'Motivo', rationale: 'Justificativa registrada', provider: 'Provider', capability: 'Capacidade', duration_ms: 'Duração (ms)', cache_hit: 'Cache hit', dry_run: 'Dry-run', noop: 'Sem operação real', validation: 'Validação', fallback: 'Fallback', error_type: 'Tipo de erro', replan_required: 'Replanejar', dropped_events: 'Eventos perdidos no emissor' };
let hosts = [], selectedJob = '', events = [], cursor = 0, jobOffset = 0, jobs = [], busy = false, eventBusy = false, generation = 0;

function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = String(text);
  if (className) el.className = className;
  return el;
}
async function read(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (response.status === 401) $('login-panel').hidden = false;
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
function failure(id, error) { $(id).replaceChildren(node('p', error.message, 'error-text')); }
function badge(status, label) { return node('span', label || states[status] || status, `status-badge ${status}`); }
const bytes = (value) => `${(value / 1024 ** 3).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} GB`;
const age = (seconds) => seconds >= 3600 ? `${(seconds / 3600).toFixed(1)} h` : `${Math.floor(seconds / 60)} min`;
function kpis(id, pairs) {
  $(id).replaceChildren(...pairs.map(([label, value]) => {
    const item = node('div', undefined, 'host-kpi'); item.append(node('strong', value), node('small', label)); return item;
  }));
}
function renderHost() {
  const host = hosts.find((item) => item.host_id === $('host-select').value);
  $('process-rows').replaceChildren();
  if (!host) {
    $('host-kpis').replaceChildren();
    $('host-state').textContent = 'Nenhuma máquina conectada. Instale o host agent na máquina monitorada; o painel não observa automaticamente seu próprio container.';
    const cell = node('td', 'Aguardando a primeira amostra. Consulte o guia de integração.'); cell.colSpan = 6;
    const tr = node('tr'); tr.append(cell); $('process-rows').append(tr); return;
  }
  $('host-state').textContent = `${host.stale ? 'Amostra antiga — coletor sem atualização' : 'Coletor conectado'} · ${host.host_id} · ${new Date(host.timestamp).toLocaleString('pt-BR')} · ${host.process_count} processos visíveis`;
  kpis('host-kpis', [['CPU da máquina', `${host.cpu_percent.toFixed(1)}%`], ['Memória usada', bytes(host.memory_used_bytes)], ['Memória total', bytes(host.memory_total_bytes)], ['Disco usado', `${host.disk_percent.toFixed(1)}%`]]);
  const q = $('process-filter').value.toLowerCase();
  const matches = host.processes.filter((p) => `${p.name} ${p.pid} ${p.service}`.toLowerCase().includes(q));
  for (const process of matches) {
    const row = node('tr');
    for (const value of [process.name + (process.service ? ` · ${process.service}` : ''), process.pid, process.status, `${process.cpu_percent.toFixed(1)}%`, bytes(process.memory_bytes), age(process.age_seconds)]) row.append(node('td', value));
    $('process-rows').append(row);
  }
  if (!matches.length) { const row = node('tr'); const cell = node('td','Nenhum processo corresponde ao filtro.'); cell.colSpan = 6; row.append(cell); $('process-rows').append(row); }
}
async function loadHosts() {
  try {
    const data = await read('/api/hosts'); hosts = data.hosts;
    const previous = $('host-select').value;
    $('host-select').replaceChildren(...hosts.map((host) => { const option = node('option', host.host_id); option.value = host.host_id; return option; }));
    if (hosts.some((host) => host.host_id === previous)) $('host-select').value = previous;
    renderHost();
  } catch (error) {
    $('host-state').textContent = error.message; $('host-kpis').replaceChildren();
    const row = node('tr'), cell = node('td',error.message); cell.colSpan = 6; row.append(cell); $('process-rows').replaceChildren(row);
  }
}
async function loadSummary() {
  try {
    const data = await read('/api/telemetry/status'); const counts = data.jobs_by_status;
    kpis('job-kpis', [['Em andamento', (counts.running || 0) + (counts.retrying || 0)], ['Na fila', counts.queued || 0], ['Falhas', counts.failed || 0], ['Concluídos', counts.succeeded || 0]]);
    kpis('cost-kpis', [['Duração média dos jobs finalizados', data.mean_job_duration_ms === null ? 'Sem dados' : `${(data.mean_job_duration_ms / 1000).toFixed(1)} s`], ['Tokens de entrada registrados', data.tokens_input ?? 'Sem dados'], ['Tokens de saída registrados', data.tokens_output ?? 'Sem dados'], ['Custo registrado na retenção', data.cost_usd === null ? 'Sem dados' : `US$ ${data.cost_usd.toFixed(4)}`]]);
    $('telemetry-state').textContent = !data.ingest_configured ? 'Ingestão não configurada' : data.event_count ? `${data.event_count.toLocaleString('pt-BR')} eventos · retenção ${data.retention_days} dias` : 'Coleta pronta · aguardando eventos reais';
    $('central-overall-status').textContent = data.ingest_configured ? 'Coleta pronta' : 'Configure a ingestão';
  } catch (error) { $('telemetry-state').textContent = error.message; }
}
function jobParameters() { return new URLSearchParams({ status: $('job-status').value, service: $('job-service').value, q: $('job-query').value, offset: String(jobOffset) }); }
function renderJobs() {
  const focused = document.activeElement?.dataset?.job;
  $('central-jobs').replaceChildren();
  for (const job of jobs) {
    const button = node('button', undefined, 'job-choice'); button.type = 'button'; button.dataset.job = job.job_id;
    button.setAttribute('aria-pressed', String(job.job_id === selectedJob));
    button.append(node('strong', job.job_id), node('small', `${job.service} · ${age(job.elapsed_seconds)} · ${job.event_count} eventos`), badge(job.status));
    if (job.stale) button.append(node('small', 'Sem atualização há mais de 5 min; confirme o worker.'));
    if (job.attributes?.dry_run) button.append(badge('skipped', 'Dry-run'));
    button.addEventListener('click', () => selectJob(job)); $('central-jobs').append(button);
    if (focused === job.job_id) button.focus({ preventScroll: true });
  }
  if (!jobs.length) $('central-jobs').append(node('p', 'Nenhum job neste filtro. As aplicações precisam emitir os eventos de ciclo de vida do job.', 'empty-state'));
  $('job-count').textContent = `${jobs.length} carregados`;
}
async function loadJobs(append = false) {
  try {
    const params = jobParameters();
    for (const key of ['status','service']) if (!params.get(key)) params.delete(key);
    const data = await read(`/api/jobs?${params}`);
    jobs = append ? [...jobs, ...data.jobs.filter((job) => !jobs.some((old) => old.job_id === job.job_id))] : data.jobs;
    $('more-jobs').hidden = !data.has_more; jobOffset = data.next_offset; renderJobs();
  } catch (error) { failure('central-jobs', error); }
}
async function selectJob(job) {
  generation += 1; selectedJob = job.job_id; events = []; cursor = 0;
  $('selected-job-title').textContent = job.job_id;
  $('selected-job-title').focus({ preventScroll: true });
  $('job-correlation').textContent = `Mensagem ${job.message_id} · sessão ${job.session_id} · trace ${job.trace_id} · máquina ${job.host_id}`;
  $('decision-timeline').replaceChildren(node('p', 'Carregando eventos…'));
  $('export-events').hidden = true; $('more-events').hidden = true;
  renderJobs(); await loadEvents();
}
function renderEvents() {
  const ordered = [...events].sort((a,b) => a.timestamp.localeCompare(b.timestamp) || a.seq - b.seq);
  const parents = new Map(ordered.map((event) => [event.span_id, event.parent_span_id]));
  function depth(event) {
    let parent = event.parent_span_id, result = 0; const visited = new Set([event.span_id]);
    while (parent && parents.has(parent) && !visited.has(parent) && result < 12) { visited.add(parent); result += 1; parent = parents.get(parent); }
    return result;
  }
  const covered = new Set(ordered.map((event) => event.phase));
  $('pipeline-stages').replaceChildren(...Object.entries(phases).map(([id,label]) => {
    const stage = node('span', `${label} · ${covered.has(id) ? 'observado' : 'sem eventos'}`, `pipeline-stage ${covered.has(id) ? 'observed' : ''}`); return stage;
  }));
  $('decision-timeline').replaceChildren();
  for (const event of ordered) {
    const article = node('article', undefined, `timeline-event ${event.kind}`); article.style.setProperty('--depth', depth(event));
    const heading = node('h4', event.name); const stamp = node('time', new Date(event.timestamp).toLocaleString('pt-BR')); stamp.dateTime = event.timestamp;
    article.append(stamp, node('small', ` · ${event.service} · ${phases[event.phase]}`), heading, badge(event.status));
    if (event.attributes.dry_run) article.append(badge('skipped','Dry-run: não comprova execução real'));
    if (event.attributes.noop) article.append(badge('skipped','Handler sem operação real'));
    const dl = node('dl');
    for (const [key,value] of Object.entries(event.attributes)) {
      if (key === 'dropped_events' && !value) continue;
      dl.append(node('dt',attributeLabels[key] || key),node('dd',Array.isArray(value) ? value.join(', ') : String(value)));
    }
    const details = node('details'); details.append(node('summary','Identificadores de correlação'),node('p',`trace ${event.trace_id} · span ${event.span_id} · pai ${event.parent_span_id || 'raiz'} · mensagem ${event.message_id} · máquina ${event.host_id}`));
    article.append(dl,details); $('decision-timeline').append(article);
  }
  const warnings = [];
  if (!ordered.some((e) => e.kind === 'job')) warnings.push('Ciclo de vida do job não registrado.');
  if (!ordered.some((e) => e.kind === 'job' && ['succeeded','failed','cancelled'].includes(e.status))) warnings.push('Job sem evento terminal; pode estar em andamento.');
  if (ordered.some((e) => e.attributes.dropped_events > 0)) warnings.push('O emissor informou perda de eventos; cobertura incompleta.');
  if (ordered.some((e) => e.parent_span_id && !parents.has(e.parent_span_id))) warnings.push('Há spans com pai ainda não carregado ou não instrumentado.');
  if (events.length >= 10000) warnings.push('Limite de 10.000 eventos carregados nesta tela atingido. Use /api/events com paginação para o restante.');
  $('flow-coverage').textContent = warnings.length ? warnings.join(' ') : `${events.length} eventos carregados. A cobertura corresponde aos eventos emitidos; etapas não instrumentadas não são inferidas.`;
  $('export-events').hidden = !events.length;
}
async function loadEvents() {
  if (!selectedJob || eventBusy) return;
  if (events.length >= 10000) return;
  const current = generation, job = selectedJob; eventBusy = true;
  try {
    const data = await read(`/api/jobs/${encodeURIComponent(job)}/events?after=${cursor}&limit=100`);
    if (current !== generation) return;
    events.push(...data.events); cursor = data.next_cursor; renderEvents();
    $('more-events').hidden = !data.has_more || events.length >= 10000;
  } catch (error) { if (current === generation) failure('decision-timeline',error); }
  finally { eventBusy = false; if (current !== generation) loadEvents(); }
}
async function loadEcosystem() {
  try {
    const data = await read('/api/ecosystem'); $('ecosystem-services').replaceChildren();
    for (const [id,service] of Object.entries(data)) {
      const section = node('section',undefined,'section-surface'); section.append(node('h3',id === 'toolbox' ? 'Acessília Toolbox' : 'Acessília'),badge(service.state),node('p',service.detail,'muted'));
      const ul = node('ul');
      for (const [endpoint,result] of Object.entries(service.endpoints)) {
        const item = node('li',`${endpoint}: ${states[result.state] || result.state}${Array.isArray(result.data) ? ` · ${result.data.length} registrados` : ''}`);
        ul.append(item);
        if (result.data && !Array.isArray(result.data)) {
          const safe = node('dl'); for (const [key,value] of Object.entries(result.data)) safe.append(node('dt',key),node('dd',value)); section.append(safe);
        }
        if (Array.isArray(result.data)) { const details = node('details'); details.append(node('summary',`Ver ${endpoint}`)); for (const entry of result.data) details.append(node('p',`${entry.id || 'Sem ID'}${entry.version ? ` · v${entry.version}` : ''}${entry.providers ? ` · providers: ${entry.providers.join(', ')}` : ''}`)); section.append(details); }
      }
      section.append(ul); $('ecosystem-services').append(section);
    }
  } catch (error) { failure('ecosystem-services',error); }
}
export async function refreshCentral() {
  if (busy) return; busy = true;
  try { jobOffset = 0; await Promise.all([loadHosts(),loadSummary(),loadJobs(),loadEvents(),loadEcosystem()]); }
  finally { busy = false; }
}
$('host-select').addEventListener('change',renderHost);
$('process-filter').addEventListener('input',renderHost);
$('job-filters').addEventListener('submit',(event) => { event.preventDefault(); jobOffset = 0; loadJobs(); });
$('more-jobs').addEventListener('click',() => loadJobs(true));
$('more-events').addEventListener('click',loadEvents);
$('login-form').addEventListener('submit',async (event) => {
  event.preventDefault();
  try { await read('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:$('view-token').value})}); $('view-token').value = ''; $('login-panel').hidden = true; window.dispatchEvent(new Event('observation-authenticated')); }
  catch (error) { $('login-result').textContent = error.message; }
});
setInterval(() => {
  if ($('auto-refresh').checked && !document.hidden) refreshCentral();
}, 10000);
$('export-events').addEventListener('click',() => {
  const blob = new Blob([JSON.stringify({job_id:selectedJob,scope:'loaded_events_only',events},null,2)],{type:'application/json'});
  const url = URL.createObjectURL(blob), link = node('a'); link.href = url; link.download = `${selectedJob}-events.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
});

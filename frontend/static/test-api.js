async function readJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  let body;
  try { body = await response.json(); } catch { throw new Error(`Resposta inválida de ${url}`); }
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

export const getConfig = () => readJson('/api/config');
export const getEntities = () => readJson('/api/entities');

export function getSessions(type, componentId) {
  const query = new URLSearchParams({ type, component_id: componentId });
  return readJson(`/api/sessions?${query}`);
}

export async function getRuns(sessionId, type) {
  const query = new URLSearchParams({ type });
  const body = await readJson(`/api/sessions/${encodeURIComponent(sessionId)}/runs?${query}`);
  return Array.isArray(body) ? body : Array.isArray(body.data) ? body.data : [];
}

export async function startRun({ entityType, entityId, message, sessionId, signal }) {
  const response = await fetch('/api/tests/runs', {
    method: 'POST',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
    body: JSON.stringify({ entity_type: entityType, entity_id: entityId, message, session_id: sessionId || null }),
    signal,
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* HTTP status is enough. */ }
    throw new Error(typeof detail === 'string' ? detail : `Falha ao iniciar a execução (HTTP ${response.status})`);
  }
  if (!response.headers.get('Content-Type')?.includes('text/event-stream') || !response.body) {
    throw new Error('O servidor não retornou um stream de eventos.');
  }
  return response;
}

const entityGroups = [
  ['agent', 'agente', 'agent-list'],
  ['team', 'time', 'team-list'],
  ['workflow', 'workflow', 'workflow-list'],
];

function emptyNote(text) {
  const note = document.createElement('p');
  note.className = 'empty-state';
  note.textContent = text;
  return note;
}

export function renderEntityButtons(entities, selected, busy, onSelect) {
  for (const [kind, label, id] of entityGroups) {
    const list = document.getElementById(id);
    list.replaceChildren();
    const matching = entities.map((entity, index) => ({ entity, index })).filter(({ entity }) => entity.type === kind);
    if (!matching.length) {
      list.append(emptyNote(`Nenhum ${label} detectado.`));
      continue;
    }
    for (const { entity, index } of matching) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `entity-button${selected === entity ? ' active' : ''}`;
      button.disabled = busy;
      button.setAttribute('aria-pressed', String(selected === entity));
      const name = document.createElement('strong');
      name.textContent = entity.name || entity.id;
      const detail = document.createElement('small');
      detail.textContent = entity.id;
      button.append(name, detail);
      button.addEventListener('click', () => onSelect(index));
      list.append(button);
    }
  }
}

export function renderSessionButtons(options, selectedSessionId, hasEntity, busy, onSelect) {
  const list = document.getElementById('session-list');
  list.replaceChildren();
  const saved = [...options].filter((option) => option.value);
  if (!saved.length) {
    list.append(emptyNote(hasEntity ? 'Nenhuma sessão salva.' : 'Selecione uma entidade.'));
    return;
  }
  for (const option of saved) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `session-button${selectedSessionId === option.value ? ' active' : ''}`;
    button.disabled = busy;
    button.setAttribute('aria-pressed', String(selectedSessionId === option.value));
    button.textContent = option.textContent;
    button.title = option.value;
    button.addEventListener('click', () => onSelect(option.value));
    list.append(button);
  }
}

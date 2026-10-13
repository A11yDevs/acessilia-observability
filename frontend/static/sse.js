export async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let name = '';
  let data = [];

  function line(text) {
    if (!text) {
      if (!data.length) {
        name = '';
        return null;
      }
      const event = { event: name || 'message', data: data.join('\n') };
      name = '';
      data = [];
      return event;
    }
    if (text.startsWith(':')) return null;
    const separator = text.indexOf(':');
    const field = separator < 0 ? text : text.slice(0, separator);
    let value = separator < 0 ? '' : text.slice(separator + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') name = value;
    if (field === 'data') data.push(value);
    return null;
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf('\n')) !== -1) {
        const current = buffer.slice(0, boundary).replace(/\r$/, '');
        buffer = buffer.slice(boundary + 1);
        const event = line(current);
        if (event) yield event;
      }
      if (done) {
        if (buffer) {
          const event = line(buffer.replace(/\r$/, ''));
          if (event) yield event;
        }
        const event = line('');
        if (event) yield event;
        return;
      }
    }
  } finally {
    try { await reader.cancel(); } catch { /* The request may already be closed. */ }
    reader.releaseLock();
  }
}

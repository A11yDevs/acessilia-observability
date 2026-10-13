const SVG = 'http://www.w3.org/2000/svg';
const names = { 'Run rate': 'Execuções por segundo', 'Error rate': 'Taxa de erro', 'P95 duration': 'Duração P95' };

export function renderHistory(target, series) {
  target.replaceChildren();
  for (const [name, samples] of Object.entries(series)) {
    const section = document.createElement('section');
    section.className = 'chart';
    const heading = document.createElement('h3');
    heading.textContent = names[name] || name;
    section.append(heading);
    if (!samples.length) {
      const empty = document.createElement('small');
      empty.textContent = 'Sem métricas neste período';
      section.append(empty);
      target.append(section);
      continue;
    }
    const values = samples.map(sample => sample.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const points = samples.map((sample, index) => {
      const x = samples.length === 1 ? 50 : index * 100 / (samples.length - 1);
      const y = 92 - (sample.value - min) * 84 / span;
      return `${x},${y}`;
    }).join(' ');
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', '0 0 100 100');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${names[name] || name}: ${samples.length} pontos; valor recente ${values.at(-1).toFixed(2)}`);
    const line = document.createElementNS(SVG, 'polyline');
    line.setAttribute('class', 'chart-line');
    line.setAttribute('points', points);
    svg.append(line);
    const latest = document.createElement('small');
    const value = name === 'Error rate' ? `${(values.at(-1) * 100).toFixed(1)}%` : `${values.at(-1).toFixed(2)} ${name === 'Run rate' ? 'runs/s' : 's'}`;
    latest.textContent = `Atual: ${value}`;
    section.append(svg, latest);
    target.append(section);
  }
}

function baseStaticFactors() {
  const attr = document.documentElement.getAttribute('data-app-prefix');
  if (attr) return attr.replace(/\/$/, '') + '/static/data/';
  const script = Array.from(document.scripts).find(s => s.src && s.src.includes('/static/'));
  if (script) {
    try {
      const url = new URL(script.src, window.location.origin);
      const parts = url.pathname.split('/');
      const idx = parts.lastIndexOf('static');
      if (idx > 1) {
        const prefix = parts.slice(0, idx).join('/');
        return (prefix || '') + '/static/data/';
      }
    } catch(_) {}
  }
  return '/static/data/';
}

document.addEventListener('DOMContentLoaded', () => {
  fetch(baseStaticFactors() + 'factores.json')
    .then(response => response.json())
    .then(data => {
      const requisitos = {};
      data.forEach(f => {
        requisitos[f.id] = f.requisito;
      });
      document.querySelectorAll('.factor-item').forEach(el => {
        const id = el.getAttribute('data-factor-id');
        const req = requisitos[id];
        if (req) {
          el.setAttribute('title', req);
          el.setAttribute('data-bs-toggle', 'tooltip');
        }
      });
      const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
      tooltipTriggerList.map(t => new bootstrap.Tooltip(t));
    })
    .catch(err => console.error('Error loading factors', err));
});

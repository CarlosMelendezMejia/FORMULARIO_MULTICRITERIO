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
      // Construir mapa id -> requisito (clave string para consistencia)
      const requisitos = data.reduce((acc, f) => {
        if (f && (f.id !== undefined) && f.requisito) {
          acc[String(f.id)] = f.requisito;
        }
        return acc;
      }, {});

      const factorEls = document.querySelectorAll('.factor-item');
      factorEls.forEach(el => {
        const rawId = el.getAttribute('data-factor-id');
        const req = requisitos[String(rawId)];
        if (req) {
          // Usar data-bs-title para Bootstrap 5 y permitir multilinea si luego se agrega html
          el.setAttribute('data-bs-toggle', 'tooltip');
          el.setAttribute('data-bs-placement', 'top');
          el.setAttribute('title', req); // fallback nativo
          el.dataset.bsOriginalTitle = req; // asegurar que bootstrap lo detecte si ya había title
          el.dataset.requisito = req;
        } else {
          console.warn('Requisito no encontrado para factor id', rawId);
        }
      });

      // Inicializar tooltips (re-evaluando atributos title)
      [...document.querySelectorAll('[data-bs-toggle="tooltip"]')].forEach(el => {
        try { new bootstrap.Tooltip(el); } catch(e) { /* ignore */ }
      });
    })
    .catch(err => console.error('Error loading factors', err));
});

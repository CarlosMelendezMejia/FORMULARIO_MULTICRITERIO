let DIMENSIONES_DATA = [];

function baseStatic() {
  // Detect possible app prefix from any <script data-app-prefix> or from current path heuristic
  const attr = document.documentElement.getAttribute('data-app-prefix');
  if (attr) return attr.replace(/\/$/, '') + '/static/data/';
  // Heuristic: find '/static/' segment in existing script tags to derive prefix
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
    } catch (_) { /* ignore */ }
  }
  return '/static/data/';
}

function cargarDimensiones() {
  return fetch(baseStatic() + 'dimensiones.json')
        .then(response => response.json())
        .then(data => {
            DIMENSIONES_DATA = data;
            renderTablaDimensiones('tabla-dimensiones');
        })
        .catch(err => console.error('Error al cargar dimensiones:', err));
}

function renderTablaDimensiones(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const table = document.createElement('table');
    table.className = 'table table-sm table-bordered align-middle mb-4';
    table.innerHTML = `
    <thead class="table-light">
      <tr>
        <th style="width:90px">Valor</th>
        <th style="width:160px">Título</th>
        <th>Descripción</th>
      </tr>
    </thead>
    <tbody>
      ${DIMENSIONES_DATA.map(d => `
        <tr>
          <td class="text-center fw-bold">${d.valor}</td>
          <td>${d.titulo}</td>
          <td>${d.descripcion}</td>
        </tr>`).join('')}
    </tbody>`;
    container.appendChild(table);
}

document.addEventListener('DOMContentLoaded', () => {
    cargarDimensiones();
});

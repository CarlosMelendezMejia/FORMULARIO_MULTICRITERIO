let DIMENSIONES_DATA = [];

function cargarDimensiones() {
    return fetch('/static/data/dimensiones.json')
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

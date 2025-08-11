// JSON estático de dimensiones (fácil de editar)
// Cada entrada: valor, titulo, descripcion
const DIMENSIONES_DATA = [
    {
        "valor": 1,
        "titulo": "Conocimientos y habilidades",
        "descripcion": "La y el formador de docentes de la UNAM debe poseer un amplio conocimiento de temas pedagógicos y didácticos que le permita guiar al profesorado en la comprensión y aplicación de teorías del aprendizaje, fomentando un ambiente de trabajo colaborativo y crítico. Debe dominar metodologías activas del aprendizaje, manejo de tecnologías digitales aplicadas a entornos educativos, así como tener experiencia y sensibilidad frente a temas estructurales y emergentes. Además, debe estar familiarizado con las diferentes etapas del desarrollo cognitivo y emocional del alumnado, conocer las tendencias actuales en educación, y poseer habilidades prácticas esenciales como comunicación clara, evaluación del aprendizaje, retroalimentación constructiva y liderazgo educativo que inspire una mentalidad de crecimiento académico, profesional y personal."
    },
    {
        "valor": 2,
        "titulo": "Responsabilidades",
        "descripcion": "Efecto que tiene el puesto sobre los objetivos, el cuidado de los recursos materiales, y compromiso adquirido con el CFOP así como, con el profesorado participante que se inscribe y asiste a las actividades académicas ofertadas."
    }
];

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
    renderTablaDimensiones('tabla-dimensiones');
});

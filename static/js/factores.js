document.addEventListener('DOMContentLoaded', () => {
  fetch('/static/data/factores.json')
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

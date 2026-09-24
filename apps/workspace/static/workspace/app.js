const sidebar = document.querySelector('.sidebar');
const toggle = document.querySelector('.menu-toggle');
const mobileQuery = window.matchMedia('(max-width:760px)');
function setMenu(open) {
  toggle?.setAttribute('aria-expanded', String(open));
  toggle?.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
  sidebar?.classList.toggle('mobile-open', open);
  if (sidebar) sidebar.inert = mobileQuery.matches && !open;
}
toggle?.addEventListener('click', () => setMenu(toggle.getAttribute('aria-expanded') !== 'true'));
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (mobileQuery.matches && sidebar?.classList.contains('mobile-open')) {
    setMenu(false);
    toggle?.focus();
  } else if (sidebar?.contains(document.activeElement)) {
    document.getElementById('main')?.focus({ preventScroll: true });
  }
});
document.addEventListener('click', event => {
  if (mobileQuery.matches && sidebar?.classList.contains('mobile-open') && !sidebar.contains(event.target) && !toggle?.contains(event.target)) setMenu(false);
});
if (sidebar) {
  const close = document.createElement('button');
  close.className = 'sidebar-close';
  close.setAttribute('aria-label', 'Fechar menu');
  close.textContent = '×';
  close.addEventListener('click', () => { setMenu(false); toggle?.focus(); });
  sidebar.prepend(close);
}
mobileQuery.addEventListener('change', () => setMenu(false));
setMenu(false);
document.querySelectorAll('[data-confirm]').forEach(button => {
  button.addEventListener('click', event => {
    if (!window.confirm(button.dataset.confirm)) event.preventDefault();
  });
});

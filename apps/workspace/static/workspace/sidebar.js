(() => {
  'use strict';
  const sidebar = document.querySelector('[data-sidebar-scope]');
  const nav = sidebar?.querySelector('nav');
  if (!nav) return;

  // Only UI preferences: one tab, one account and one campaign. No form data.
  const key = `nabio:sidebar:v1:${sidebar.dataset.sidebarScope}`;
  const groups = Array.from(nav.querySelectorAll('[data-nav-group]'));
  let restoring = false;
  let pending = false;

  function save() {
    if (restoring) return;
    const state = { scrollTop: nav.scrollTop, groups: {} };
    groups.forEach(group => { state.groups[group.dataset.navGroup] = group.open; });
    try { sessionStorage.setItem(key, JSON.stringify(state)); } catch { /* Private/storage-disabled mode still works. */ }
  }

  function restore() {
    restoring = true;
    let state;
    try { state = JSON.parse(sessionStorage.getItem(key)); } catch { /* Use server defaults. */ }
    groups.forEach(group => {
      const open = state?.groups?.[group.dataset.navGroup];
      if (typeof open === 'boolean') group.open = open;
      if (group.querySelector('[aria-current="page"]')) group.open = true;
    });
    const saved = Number.isFinite(state?.scrollTop) && state.scrollTop >= 0;
    function position() {
      if (saved) {
        nav.scrollTop = state.scrollTop;
      } else {
        const active = nav.querySelector('[aria-current="page"]');
        if (active) {
          const container = nav.getBoundingClientRect();
          const item = active.getBoundingClientRect();
          if (item.top < container.top || item.bottom > container.bottom) {
            nav.scrollTop += item.top - container.top - nav.clientHeight / 2 + item.height / 2;
          }
        }
      }
    }
    position();
    requestAnimationFrame(() => { position(); restoring = false; });
  }

  groups.forEach(group => group.addEventListener('toggle', save));
  nav.addEventListener('scroll', () => {
    if (restoring || pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; save(); });
  }, { passive: true });
  // Synchronous save also covers a click immediately after scrolling/opening a group.
  sidebar.addEventListener('click', save, true);
  window.addEventListener('pagehide', save);
  window.addEventListener('pageshow', event => { if (event.persisted) restore(); });
  restore();
})();

/* One contextual explanation at a time. Hover, keyboard, touch and Escape. */
(() => {
  let active = null;
  let pinned = false;
  let dismissTimer;
  const close = () => {
    clearTimeout(dismissTimer);
    if (!active) return;
    active.panel.hidden = true;
    active.button.setAttribute('aria-expanded', 'false');
    active = null;
    pinned = false;
  };
  const position = () => {
    if (!active) return;
    const {button, panel} = active;
    const rect = button.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    panel.style.maxWidth = `${Math.max(0, viewportWidth - 24)}px`;
    const width = panel.getBoundingClientRect().width;
    const height = panel.getBoundingClientRect().height;
    const top = rect.bottom + 8 + height < window.innerHeight - 12
      ? rect.bottom + 8 : Math.max(12, rect.top - height - 8);
    panel.style.left = `${Math.max(12, Math.min(rect.left, viewportWidth - width - 12))}px`;
    panel.style.top = `${top}px`;
  };
  document.querySelectorAll('.help-trigger').forEach(button => {
    const panel = document.getElementById(button.getAttribute('aria-controls'));
    if (!panel) return;
    const container = button.closest('.context-help');
    const open = () => {
      clearTimeout(dismissTimer);
      if (active?.button !== button) {
        close();
        active = {button, panel};
        panel.hidden = false;
        button.setAttribute('aria-expanded', 'true');
      }
      position();
    };
    button.addEventListener('click', () => {
      if (active?.button === button && pinned) close();
      else { open(); pinned = true; }
    });
    button.addEventListener('focus', open);
    button.addEventListener('blur', () => { if (active?.button === button) close(); });
    container.addEventListener('pointerenter', event => {
      if (event.pointerType !== 'touch' && !pinned) open();
    });
    container.addEventListener('pointerleave', () => {
      if (active?.button === button && !pinned && document.activeElement !== button) dismissTimer = setTimeout(close, 180);
    });
    panel.addEventListener('pointerenter', () => clearTimeout(dismissTimer));
  });
  document.addEventListener('pointerdown', event => {
    if (active && !event.target.closest('.context-help')) close();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  window.addEventListener('resize', close);
  document.addEventListener('scroll', close, true);
})();

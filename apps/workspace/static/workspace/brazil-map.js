(() => {
  const root = document.querySelector('[data-brazil-map]');
  if (!root) return;
  const stage = root.querySelector('.brazil-map-stage');
  const plane = root.querySelector('.brazil-map-plane');
  const states = [...root.querySelectorAll('#brazil-surfaces .brazil-state')];
  const select = root.querySelector('#brazil-state-select');
  const name = root.querySelector('[data-map-name]');
  const region = root.querySelector('[data-map-region]');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let yaw = 0, pitch = 22, drag = null, frame = 0;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const paint = () => {
    plane.style.setProperty('--map-rx', `${pitch}deg`);
    plane.style.setProperty('--map-ry', `${yaw}deg`);
    plane.style.setProperty('--map-rz', `${-9 + yaw / 4}deg`);
    frame = 0;
  };
  const rotate = () => { if (!frame) frame = requestAnimationFrame(paint); };
  const choose = uf => {
    const selected = states.find(item => item.dataset.uf === uf);
    states.forEach((item, index) => {
      const active = item === selected;
      item.classList.toggle('is-selected', active);
      item.classList.toggle('is-region', Boolean(selected && item.dataset.regionId === selected.dataset.regionId));
      item.setAttribute('aria-pressed', String(active));
      item.tabIndex = active || (!selected && index === 0) ? 0 : -1;
    });
    select.value = selected?.dataset.uf || '';
    name.textContent = selected ? `${selected.dataset.name} · ${selected.dataset.uf}` : 'Brasil';
    region.textContent = selected ? `Região ${selected.dataset.region} · território conectado` : '5 regiões · 27 unidades da federação';
  };
  states.forEach((item, index) => {
    item.setAttribute('role', 'button');
    item.setAttribute('aria-label', `${item.dataset.name} (${item.dataset.uf}), região ${item.dataset.region}`);
    item.setAttribute('aria-pressed', 'false');
    item.tabIndex = index === 0 ? 0 : -1;
    item.addEventListener('click', event => { if (event.detail === 0) choose(item.dataset.uf); });
    item.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(item.dataset.uf); return; }
      const targets = { ArrowRight: (index + 1) % states.length, ArrowDown: (index + 1) % states.length,
        ArrowLeft: (index - 1 + states.length) % states.length, ArrowUp: (index - 1 + states.length) % states.length,
        Home: 0, End: states.length - 1 };
      if (event.key in targets) { event.preventDefault(); const target = states[targets[event.key]]; choose(target.dataset.uf); target.focus(); }
    });
  });
  select.addEventListener('change', () => choose(select.value));
  root.querySelectorAll('[data-map-turn]').forEach(button => button.addEventListener('click', () => {
    yaw = clamp(yaw + Number(button.dataset.mapTurn) * 12, -36, 36); rotate();
  }));
  root.querySelector('[data-map-reset]').addEventListener('click', () => { yaw = 0; pitch = 22; rotate(); choose(''); });
  stage.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY, yaw, pitch, uf: event.target.closest('.brazil-state')?.dataset.uf, moved: false };
    stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener('pointermove', event => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (Math.hypot(dx, dy) < 5 && !drag.moved) return;
    drag.moved = true;
    if (reduced.matches) return;
    root.classList.add('brazil-dragging');
    yaw = clamp(drag.yaw + dx * .2, -36, 36);
    pitch = clamp(drag.pitch - dy * .12, 6, 38);
    rotate();
  });
  const release = event => {
    if (!drag || drag.id !== event.pointerId) return;
    if (event.type === 'pointerup' && !drag.moved && drag.uf) choose(drag.uf);
    if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
    drag = null; root.classList.remove('brazil-dragging');
  };
  stage.addEventListener('pointerup', release);
  stage.addEventListener('pointercancel', release);
  stage.addEventListener('lostpointercapture', () => { drag = null; root.classList.remove('brazil-dragging'); });
  reduced.addEventListener('change', () => { yaw = 0; pitch = 22; rotate(); });
  root.querySelector('.brazil-map-controls').hidden = false;
  root.classList.add('brazil-ready');
})();

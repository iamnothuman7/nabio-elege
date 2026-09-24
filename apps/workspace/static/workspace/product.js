(() => {
  const tabs=[...document.querySelectorAll('[data-product-tab]')];
  const activate=tab=>{tabs.forEach(item=>{const selected=item===tab;item.setAttribute('aria-selected',String(selected));item.tabIndex=selected?0:-1;document.getElementById(item.getAttribute('aria-controls')).hidden=!selected;});};
  tabs.forEach((tab,index)=>{tab.addEventListener('click',()=>activate(tab));tab.addEventListener('keydown',event=>{let target;if(event.key==='ArrowRight')target=tabs[(index+1)%tabs.length];if(event.key==='ArrowLeft')target=tabs[(index-1+tabs.length)%tabs.length];if(event.key==='Home')target=tabs[0];if(event.key==='End')target=tabs.at(-1);if(target){event.preventDefault();activate(target);target.focus();}});});
  const body = document.body;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const track = document.querySelector('.ribbon-track');
  const group = track?.querySelector('.ribbon-group');
  if (group) { const copy = group.cloneNode(true); copy.setAttribute('aria-hidden', 'true'); track.append(copy); }
  const syncMotion = () => {
    body.classList.toggle('motion-paused', reduced.matches);
  };
  reduced.addEventListener('change', syncMotion);
  syncMotion();
  body.classList.add('motion-ready');
  const header = document.querySelector('.product-header');
  let scrollFrame = 0;
  const updateHeader = () => { header?.classList.toggle('is-scrolled', scrollY > 24); scrollFrame = 0; };
  addEventListener('scroll', () => { if (!scrollFrame) scrollFrame = requestAnimationFrame(updateHeader); }, { passive: true });
  updateHeader();
  const visibility = () => body.classList.toggle('page-unfocused', document.hidden);
  document.addEventListener('visibilitychange', visibility);
  visibility();
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.replace('reveal-pending', 'reveal-visible');
      observer.unobserve(entry.target);
    }), { threshold: .08 });
    if (!reduced.matches) document.querySelectorAll('.section-intro, .principle-grid article, .product-territory > div:first-child, .product-cta h2').forEach(element => {
      if (element.getBoundingClientRect().top < innerHeight) return;
      element.classList.add('reveal-pending'); observer.observe(element);
    });
    const animations = new IntersectionObserver(entries => entries.forEach(entry => {
      entry.target.classList.toggle(entry.target.matches('.product-scene') ? 'scene-offscreen' : 'ribbon-offscreen', !entry.isIntersecting);
    }));
    document.querySelectorAll('.product-scene, .product-ribbon').forEach(element => animations.observe(element));
  }
  document.querySelectorAll('[data-tilt]').forEach(scene => {
    let frame;
    const reset = () => { cancelAnimationFrame(frame); scene.style.setProperty('--rx', '0deg'); scene.style.setProperty('--ry', '0deg'); };
    scene.addEventListener('pointermove', event => {
      if (reduced.matches || event.pointerType !== 'mouse') return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = scene.getBoundingClientRect();
        scene.style.setProperty('--ry', `${(event.clientX - rect.left - rect.width / 2) / rect.width * 8}deg`);
        scene.style.setProperty('--rx', `${-(event.clientY - rect.top - rect.height / 2) / rect.height * 6}deg`);
      });
    });
    scene.addEventListener('pointerleave', reset);
    reduced.addEventListener('change', reset);
  });
})();

(() => {
  const box = document.querySelector('[data-address-lookup]');
  if (!box) return;
  const byId = id => document.getElementById(id);
  const form = box.closest('form'), status = byId('address-status'), results = byId('address-results');
  const cep = byId('lookup-cep');
  let controller, generation = 0, timer, lastAuto = '', applied = {};
  const fields = {name: byId('id_name'), municipality: byId('id_municipality'), state: byId('id_state'), ibge_code: byId('id_ibge_code')};
  byId('lookup-state').value = fields.state?.value || '';
  byId('lookup-city').value = fields.municipality?.value || '';
  function apply(item, overwrite = false) {
    const values = {name: item.neighborhood, municipality: item.city, state: item.state, ibge_code: item.ibge};
    let preserved = false;
    const locationConflict = ['municipality', 'state', 'ibge_code'].some(name => fields[name]?.value && fields[name].value !== applied[name] && fields[name].value !== values[name]);
    for (const [name, value] of Object.entries(values)) {
      const field = fields[name];
      if (!field || (!value && name !== 'ibge_code' && !(name === 'name' && field.value === applied.name))) continue;
      if (!overwrite && locationConflict) { preserved = true; continue; }
      if (overwrite || !field.value || field.value === applied[name]) {
        field.value = value; applied[name] = value;
      } else if (field.value !== value) preserved = true;
    }
    const link = byId('address-map-link');
    link.hidden = !item.ibge;
    if (item.ibge) link.href = `${box.dataset.mapUrl}?uf=${encodeURIComponent(item.ibge.slice(0,2))}&municipio=${encodeURIComponent(item.ibge)}`;
    status.textContent = preserved ? 'Endereço encontrado. Mantivemos os campos que você já preencheu; clique no resultado para substituí-los.' : 'Localização preenchida. Confira o nome e o tipo do território antes de salvar.';
  }
  async function lookup(payload, automatic = false) {
    controller?.abort(); controller = new AbortController(); const currentController = controller, version = ++generation;
    status.textContent = 'Consultando endereço…'; results.replaceChildren(); byId('address-map-link').hidden = true;
    const timeout = setTimeout(() => currentController.abort(), 9000);
    try {
      const response = await fetch(box.dataset.addressLookup, {method:'POST', credentials:'same-origin', signal:controller.signal,
        headers:{'Content-Type':'application/json','X-CSRFToken':form.elements.csrfmiddlewaretoken.value}, body:JSON.stringify(payload)});
      const result = await response.json().catch(() => { throw new Error('A sessão ou a consulta expirou. Recarregue a página e tente novamente.'); });
      if (version !== generation) return;
      if (!response.ok) throw new Error(result.detail || 'Não foi possível consultar agora. Preencha manualmente.');
      if (!result.data.length) { status.textContent = 'Nenhum endereço encontrado. Confira os dados ou preencha manualmente.'; return; }
      result.data.forEach(item => {
        const button = document.createElement('button'); button.type='button'; button.className='address-result';
        const title = document.createElement('strong'); title.textContent = `${item.street || item.city} · ${item.cep}`;
        const detail = document.createElement('small'); detail.textContent = `${item.neighborhood ? item.neighborhood+' · ' : ''}${item.city}/${item.state} — Usar esta localização`;
        button.append(title,detail); button.addEventListener('click',()=>apply(item,true)); results.append(button);
      });
      status.textContent = 'Selecione o endereço correspondente para preencher o cadastro.';
      if (automatic && result.data.length === 1) apply(result.data[0]);
    } catch (error) {
      if (version !== generation) return;
      status.textContent = error.name === 'AbortError' ? 'A consulta demorou. Tente novamente ou preencha manualmente.' : error instanceof TypeError ? 'Sem conexão com a consulta. Tente novamente ou preencha manualmente.' : error.message;
    } finally { clearTimeout(timeout); }
  }
  function lookupCep() {
    const value = cep.value.trim().replace('-', '');
    if (!/^\d{8}$/.test(value)) { status.textContent='Digite os 8 números do CEP.'; return; }
    lastAuto = value; lookup({cep:value},true);
  }
  cep.addEventListener('input', () => {
    clearTimeout(timer); controller?.abort(); generation++;
    const value = cep.value.trim().replace('-', '');
    if (/^\d{8}$/.test(value) && value !== lastAuto) timer=setTimeout(lookupCep,450);
    else { status.textContent=''; results.replaceChildren(); byId('address-map-link').hidden=true; }
  });
  cep.addEventListener('keydown', event => { if(event.key === 'Enter') {event.preventDefault();clearTimeout(timer);lookupCep();} });
  byId('lookup-cep-button').addEventListener('click',()=>{clearTimeout(timer);lookupCep();});
  byId('lookup-address-button').addEventListener('click',()=>lookup({state:byId('lookup-state').value, city:byId('lookup-city').value.trim(), street:byId('lookup-street').value.trim()}));
})();

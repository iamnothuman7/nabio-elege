window.NabioGeography = {init(map, data) {
  if (!data.national_explorer) return;
  const byId = id => document.getElementById(id);
  const region = byId('geo-region'), state = byId('geo-state'), city = byId('geo-city');
  const status = byId('map-status'), search = byId('geo-search'), list = byId('geo-place-list');
  const colors = {'1':'#4c896d','2':'#bf9746','3':'#508ea0','4':'#6f80aa','5':'#a586b3'};
  map.createPane('geography');
  map.getPane('geography').style.zIndex='350';
  let states = [], cities = [], brazil, boundaries, controller, generation = 0, places = [];
  let drawing = false, vertices = [], draft, commandId = '';
  const areaForm = byId('geo-area-form');
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const options = (element, values, placeholder) => {
    element.replaceChildren(new Option(placeholder, ''));
    values.forEach(value => element.add(new Option(value.name, value.id)));
  };
  async function get(kind, code, signal) {
    const response = await fetch(`${data.geography_url}${kind}/${encodeURIComponent(code)}/`, {signal, credentials:'same-origin'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'A camada não pôde ser carregada.');
    return result.data;
  }
  function showPlaces(values, level) {
    places = values; list.replaceChildren();
    const filtered = values.filter(value => normalize(value.name).includes(normalize(search.value)));
    filtered.forEach(value => {
      const button = document.createElement('button'); button.type='button'; button.className='geo-place-button';
      const title = document.createElement('span'); title.textContent=value.name;
      const suffix = document.createElement('small'); suffix.textContent=level === 'state' ? (value.uf || '↗') : '↗';
      button.append(title,suffix); button.addEventListener('click',()=>select(level,value.id)); list.append(button);
    });
    if (!filtered.length) { const empty=document.createElement('p'); empty.textContent='Nenhuma localidade encontrada nesta lista.'; list.append(empty); }
    list.dataset.level=level;
  }
  function select(level,id) {
    if (drawing) return;
    if (level==='state') { state.value=id; city.value=''; const entry=states.find(s=>s.id===id); if(entry) region.value=entry.region_id; }
    else city.value=id;
    search.value=''; refresh();
  }
  function paint(geo, level, labels) {
    if(boundaries) map.removeLayer(boundaries);
    boundaries=L.geoJSON(geo, {pane:'geography',style: feature => ({color:'#fff',weight:1.2,fillColor:colors[(states.find(s=>s.id===feature.properties.codarea.slice(0,2))||{}).region_id]||'#598d74',fillOpacity:level==='city' ? .12 : .25}), onEachFeature(feature,layer) {
      const id=feature.properties.codarea, entry=labels.find(value=>value.id===id);
      const name=entry?.name || `Área IBGE ${id}`;
      const tooltip=document.createElement('span'); tooltip.textContent=name; layer.bindTooltip(tooltip,{sticky:true});
      layer.on('mouseover',()=>layer.setStyle({weight:2,fillOpacity:.42}));
      layer.on('mouseout',()=>boundaries.resetStyle(layer));
      layer.on('click',()=>{if(!drawing && level!=='city')select(level,id);});
    }});
    if(byId('geo-boundaries').checked) boundaries.addTo(map);
    if(boundaries.getBounds().isValid())map.fitBounds(boundaries.getBounds(),{padding:[24,24],maxZoom:12});
  }
  async function refresh() {
    controller?.abort(); controller=new AbortController(); const signal=controller.signal, revision=++generation;
    status.textContent='Carregando referências geográficas do IBGE…';
    try {
      if(!states.length) {
        [states,brazil]=await Promise.all([get('catalogo','BR',signal),get('limites','BR',signal)]);
        options(region,[...new Map(states.map(s=>[s.region_id,{id:s.region_id,name:s.region}])).values()].sort((a,b)=>a.id.localeCompare(b.id)),'Todo o Brasil');
        options(state,states,'Todos os estados');
      }
      if(revision!==generation)return;
      const uf=states.find(s=>s.id===state.value);
      if(!uf) {
        cities=[]; city.dataset.state=''; options(city,[],'Selecione um estado'); city.disabled=true;
        const visible=region.value ? states.filter(s=>s.region_id===region.value) : states;
        const ids=new Set(visible.map(s=>s.id));
        paint({...brazil,features:brazil.features.filter(f=>ids.has(f.properties.codarea))},'state',states);
        showPlaces(visible,'state');
        byId('geo-selection-title').textContent=visible[0] && region.value ? visible[0].region : 'Brasil';
        byId('geo-selection-count').textContent=`${visible.length} unidades da federação`;
        byId('geo-breadcrumb').textContent=region.value ? `Brasil / ${visible[0]?.region||''}` : 'Brasil / todas as regiões';
        byId('geo-districts').textContent='Selecione um município para consultar. Distrito não equivale a bairro ou comunidade.';
      } else {
        if(city.dataset.state!==uf.id) {
          cities=await get('municipios',uf.id,signal); if(revision!==generation)return;
          options(city,cities,'Todos os municípios');city.dataset.state=uf.id;city.disabled=false;
        }
        const municipality=cities.find(c=>c.id===city.value);
        const geo=await get('limites',municipality?.id||uf.id,signal);if(revision!==generation)return;
        paint(geo,municipality ? 'city' : 'municipality',municipality ? [municipality] : cities);
        showPlaces(cities,'municipality');
        byId('geo-selection-title').textContent=municipality?.name||uf.name;
        byId('geo-selection-count').textContent=municipality ? `IBGE ${municipality.id}` : `${cities.length} municípios`;
        byId('geo-breadcrumb').textContent=`Brasil / ${uf.region} / ${uf.name}${municipality ? ' / '+municipality.name : ''}`;
        if(municipality) {
          byId('geo-districts').textContent='Consultando distritos…';
          get('distritos',municipality.id,signal).then(districts=>{if(revision===generation)byId('geo-districts').textContent=districts.length ? districts.map(d=>d.name).join(' · ')+' — Distritos oficiais; bairros e comunidades são cadastrados separadamente.' : 'Nenhum distrito retornado pela fonte.';}).catch(error=>{if(error.name!=='AbortError' && revision===generation)byId('geo-districts').textContent='Distritos indisponíveis. Tente atualizar a camada.';});
        } else byId('geo-districts').textContent='Selecione um município para consultar seus distritos.';
      }
      status.textContent='Referência: IBGE · limites simplificados. Clique nas áreas ou use a lista para navegar.';
    } catch(error) {if(error.name!=='AbortError' && revision===generation)status.textContent=error.message || 'A fonte está indisponível. Use Atualizar camada para tentar novamente.';}
  }
  region.addEventListener('change',()=>{state.value='';city.value='';city.dataset.state='';search.value='';refresh();});
  state.addEventListener('change',()=>{city.value='';search.value='';const uf=states.find(s=>s.id===state.value);if(uf)region.value=uf.region_id;refresh();});
  city.addEventListener('change',()=>{search.value='';refresh();});
  search.addEventListener('input',()=>showPlaces(places,list.dataset.level||'state'));
  byId('geo-brazil').addEventListener('click',()=>{if(drawing)return;region.value='';state.value='';city.value='';city.dataset.state='';search.value='';refresh();});
  byId('geo-back').addEventListener('click',()=>{if(drawing)return;if(city.value)city.value='';else if(state.value){state.value='';city.dataset.state='';}else region.value='';search.value='';refresh();});
  byId('geo-retry').addEventListener('click',()=>{if(!drawing)refresh();});
  byId('geo-boundaries').addEventListener('change',()=>{if(boundaries){if(byId('geo-boundaries').checked)boundaries.addTo(map);else map.removeLayer(boundaries);}});
  const explorer=byId('geo-explorer'), expand=byId('geo-expand');
  const close=document.createElement('button');close.type='button';close.className='button geo-expand-close';close.textContent='✕ Fechar ampliação';close.hidden=true;explorer.append(close);
  function setExpanded(value) {explorer.classList.toggle('is-expanded',value);expand.setAttribute('aria-pressed',String(value));close.hidden=!value;map.invalidateSize();if(value)close.focus();else expand.focus();}
  expand.addEventListener('click',()=>setExpanded(!explorer.classList.contains('is-expanded')));close.addEventListener('click',()=>setExpanded(false));
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && explorer.classList.contains('is-expanded'))setExpanded(false);});
  function updateDraft() {
    if(draft)map.removeLayer(draft);
    if(vertices.length)draft=(vertices.length>2 ? L.polygon(vertices,{color:'#bc8236',fillOpacity:.18}) : L.polyline(vertices,{color:'#bc8236'})).addTo(map);
    byId('geo-draw-status').textContent=`${vertices.length} vértices. Clique no mapa; use Desfazer para corrigir. Mínimo de 3, máximo de 200.`;
    areaForm.hidden=vertices.length<3;
  }
  function stopDraw() {drawing=false;map.doubleClickZoom.enable();vertices=[];if(draft)map.removeLayer(draft);draft=null;areaForm.hidden=true;region.disabled=false;state.disabled=false;city.disabled=!state.value;byId('geo-undo').disabled=true;byId('geo-cancel').disabled=true;byId('geo-draw').textContent='Iniciar desenho';}
  byId('geo-draw')?.addEventListener('click',()=>{
    if(!city.value){byId('geo-draw-status').textContent='Selecione primeiro um município para identificar a área.';return;}
    if(drawing)return;drawing=true;map.doubleClickZoom.disable();vertices=[];commandId=crypto.randomUUID();region.disabled=true;state.disabled=true;city.disabled=true;byId('geo-undo').disabled=false;byId('geo-cancel').disabled=false;byId('geo-draw').textContent='Desenhando no mapa…';updateDraft();byId('campaign-map').scrollIntoView({block:'center',behavior:'auto'});
  });
  map.on('click',event=>{if(drawing && vertices.length<200){vertices.push([event.latlng.lat,event.latlng.lng]);updateDraft();}});
  byId('geo-undo')?.addEventListener('click',()=>{vertices.pop();updateDraft();});
  byId('geo-cancel')?.addEventListener('click',()=>{stopDraw();byId('geo-draw-status').textContent='Desenho cancelado. Nenhum cadastro foi alterado.';});
  areaForm?.addEventListener('submit',async event=>{
    event.preventDefault();if(vertices.length<3)return;
    const button=areaForm.querySelector('button[type="submit"]'),uf=states.find(s=>s.id===state.value),municipality=cities.find(c=>c.id===city.value);
    const ring=vertices.map(([lat,lng])=>[Number(lng.toFixed(6)),Number(lat.toFixed(6))]);ring.push([...ring[0]]);
    const payload={command_id:commandId,name:areaForm.elements.name.value,area_kind:areaForm.elements.area_kind.value,source_reference:areaForm.elements.source_reference.value,public_area_confirmed:areaForm.elements.public_area_confirmed.checked,municipality:municipality.name,state:uf.uf,ibge_code:municipality.id,boundary:{type:'Polygon',coordinates:[ring]}};
    button.disabled=true;
    try{const response=await fetch(data.create_area_url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':areaForm.elements.csrfmiddlewaretoken.value},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Não foi possível salvar.');stopDraw();location.reload();}
    catch(error){byId('geo-draw-status').textContent=error.message;}finally{button.disabled=false;}
  });
  refresh();
}};

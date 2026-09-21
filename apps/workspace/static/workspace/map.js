(() => {
  const container = document.getElementById('campaign-map');
  const dataNode = document.getElementById('campaign-map-data');
  const status = document.getElementById('map-status');
  if (!container || !dataNode) return;
  if (!window.L) {
    container.textContent = 'Não foi possível carregar o mapa. Confira a conexão. Os cadastros continuam disponíveis na lista.';
    container.classList.add('map-unavailable');
    return;
  }
  const data = JSON.parse(dataNode.textContent);
  container.replaceChildren();
  const map = L.map(container, {scrollWheelZoom: false}).setView([-14.2, -51.9], 4);
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    updateWhenIdle: true,
    keepBuffer: 1
  }).addTo(map);
  tiles.on('tileerror', () => { status.textContent = 'Alguns blocos do mapa não carregaram. Os pontos e a lista continuam disponíveis.'; });
  const colors = {committee: '#155c4d', support: '#3478a0', event: '#c8862d', logistics: '#78558e'};
  const labels = {committee: 'Comitês eleitorais', support: 'Pontos de apoio', event: 'Locais de evento', logistics: 'Bases logísticas'};
  const layers = {};
  const markers = new Map();
  Object.keys(colors).forEach(type => { layers[type] = L.layerGroup().addTo(map); });
  data.points.forEach(point => {
    const circle = L.circleMarker([point.latitude, point.longitude], {radius: 10, color: '#fff', weight: 3, fillColor: colors[point.type], fillOpacity: 1});
    const popup = document.createElement('div');
    popup.className = 'electoral-popup';
    const tag = document.createElement('span'); tag.className = 'popup-kind'; tag.textContent = point.type_label;
    const title = document.createElement('strong'); title.textContent = point.name;
    const location = document.createElement('p'); location.textContent = `${point.territory} · ${point.municipality}/${point.state}`;
    const address = document.createElement('p'); address.textContent = point.address;
    popup.append(tag, title, location, address);
    const activities = data.activities.filter(activity => activity.base_id === point.id);
    activities.forEach(activity => {
      const link = document.createElement('a'); link.href = activity.url; link.textContent = `${activity.starts} · ${activity.title}`; link.className = 'popup-action'; popup.append(link);
    });
    const link = document.createElement('a'); link.href = point.url; link.textContent = 'Abrir ponto de apoio →'; popup.append(link);
    circle.bindPopup(popup);
    const tooltip = document.createElement('span'); tooltip.textContent = point.name;
    circle.bindTooltip(tooltip, {direction: 'top'});
    circle.addTo(layers[point.type]);
    markers.set(point.id, circle);
  });
  L.control.layers(null, Object.fromEntries(Object.entries(layers).map(([key, layer]) => [labels[key], layer])), {collapsed: false}).addTo(map);
  const fit = () => {
    if (data.points.length) map.fitBounds(data.points.map(p => [p.latitude, p.longitude]), {padding: [40, 40], maxZoom: 13});
  };
  if (!data.national_explorer) fit();
  if (!data.points.length) status.textContent = 'Cadastre comitês e pontos públicos para visualizar a operação.';
  document.getElementById('fit-map')?.addEventListener('click', fit);
  const areaLayer = L.layerGroup().addTo(map);
  const areaMarkers = new Map();
  (data.areas || []).forEach(area => {
    const polygon = L.geoJSON(area.geometry, {style: {color:'#ab7637',weight:2,dashArray:'5 5',fillOpacity:.12}});
    const popup = document.createElement('div');
    const title = document.createElement('strong'); title.textContent=area.name;title.className='geo-popup-name';
    const note = document.createElement('span');note.textContent=`${area.kind} · Área cadastrada pela equipe. Fonte: ${area.source}`;note.className='geo-popup-note';
    const link=document.createElement('a');link.href=area.url;link.textContent='Abrir cadastro →';popup.append(title,note,link);
    polygon.bindPopup(popup).addTo(areaLayer);areaMarkers.set(area.id,polygon);
  });
  L.control.layers(null, {'Áreas da equipe':areaLayer}, {collapsed:true}).addTo(map);
  L.control.scale({imperial:false}).addTo(map);
  document.querySelectorAll('[data-map-area]').forEach(button=>button.addEventListener('click',()=>{const area=areaMarkers.get(button.dataset.mapArea);if(area){areaLayer.addTo(map);map.fitBounds(area.getBounds(),{padding:[35,35]});area.openPopup();}}));
  window.NabioGeography?.init(map, data);
  document.querySelectorAll('[data-map-point]').forEach(button => button.addEventListener('click', () => {
    const marker = markers.get(button.dataset.mapPoint);
    if (!marker) return;
    const point = data.points.find(p => p.id === button.dataset.mapPoint);
    layers[point.type].addTo(map);
    map.setView(marker.getLatLng(), 15);
    marker.openPopup();
    container.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center'});
  }));
  new ResizeObserver(() => map.invalidateSize()).observe(container);
})();

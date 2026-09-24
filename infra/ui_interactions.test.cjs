// Deterministic DOM doubles: no browser, accounts, network or third-party packages.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const source = name => readFileSync(join(__dirname,'../apps/workspace/static/workspace',name),'utf8');
class Element {
  constructor(value='') { this.value=value; this.listeners={}; this.children=[]; this.dataset={}; this.hidden=false; }
  addEventListener(name,fn) { (this.listeners[name] ||= []).push(fn); }
  fire(name,event={}) { this.listeners[name]?.forEach(fn=>fn(event)); }
  append(...items) {this.children.push(...items);}
  replaceChildren(...items) {this.children=items;}
}
function guidance() {
  const doc=new Element(), win=new Element();
  const buttons=[new Element(),new Element()], panels=[new Element(),new Element()], wrappers=[new Element(),new Element()];
  buttons.forEach((button,i)=>{
    button.attrs={'aria-controls':String(i),'aria-expanded':'false'};
    button.getAttribute=key=>button.attrs[key];button.setAttribute=(key,value)=>button.attrs[key]=value;
    button.closest=()=>wrappers[i]; button.getBoundingClientRect=()=>({left:330,top:690,bottom:720});
    panels[i].hidden=true;panels[i].style={};panels[i].getBoundingClientRect=()=>({width:340,height:120});
  });
  doc.querySelectorAll=()=>buttons;doc.getElementById=id=>panels[Number(id)];doc.documentElement={clientWidth:375};
  win.innerWidth=390;win.innerHeight=760;
  vm.runInNewContext(source('guidance.js'),{document:doc,window:win,setTimeout,clearTimeout});
  return {doc,win,buttons,panels,wrappers};
}
test('help opens on focus, closes with Escape and fits narrow viewport',()=>{
  const ui=guidance();ui.buttons[0].fire('focus');
  assert.equal(ui.panels[0].hidden,false);assert.equal(ui.panels[0].style.left,'23px');assert.equal(ui.panels[0].style.top,'562px');
  assert.equal(ui.buttons[0].attrs['aria-expanded'],'true');
  ui.doc.fire('keydown',{key:'Escape'});assert.equal(ui.panels[0].hidden,true);
});
test('help can be toggled by touch and only one explanation is open',()=>{
  const ui=guidance();ui.buttons[0].fire('click');ui.buttons[1].fire('click');
  assert.equal(ui.panels[0].hidden,true);assert.equal(ui.panels[1].hidden,false);
  ui.buttons[1].fire('click');assert.equal(ui.panels[1].hidden,true);
});
test('hover help ignores touch enter and closes on outside click or scroll',()=>{
  const ui=guidance();ui.wrappers[0].fire('pointerenter',{pointerType:'touch'});assert.equal(ui.panels[0].hidden,true);
  ui.wrappers[0].fire('pointerenter',{pointerType:'mouse'});assert.equal(ui.panels[0].hidden,false);
  ui.doc.fire('pointerdown',{target:{closest:()=>null}});assert.equal(ui.panels[0].hidden,true);
  ui.buttons[0].fire('focus');ui.doc.fire('scroll');assert.equal(ui.panels[0].hidden,true);
});
function sidebar(saved, blocked=false) {
  const nav = new Element(), side = new Element(), group = new Element(), win = new Element();
  nav.scrollTop=0; nav.clientHeight=400; group.open=false; group.dataset.navGroup='operacao';
  group.querySelector=()=>({}); // Active page always keeps its group open.
  nav.querySelectorAll=()=>[group]; nav.querySelector=()=>null;
  side.querySelector=()=>nav; side.dataset.sidebarScope='campaign:user';
  const store=new Map(saved?[['nabio:sidebar:v1:campaign:user',JSON.stringify(saved)]]:[]);
  const queue=[];
  vm.runInNewContext(source('sidebar.js'),{document:{querySelector:()=>side},window:win,requestAnimationFrame:fn=>queue.push(fn),sessionStorage:{getItem:key=>{if(blocked)throw Error();return store.get(key)||null;},setItem:(key,value)=>{if(blocked)throw Error();store.set(key,value);}}});
  const frame=()=>{while(queue.length)queue.shift()();}; frame();
  return {nav,side,group,win,frame,store};
}
test('sidebar restores exact scroll and opens active group',()=>{
  const ui=sidebar({scrollTop:328,groups:{operacao:false}});
  assert.equal(ui.nav.scrollTop,328); assert.equal(ui.group.open,true);
  ui.nav.scrollTop=513; ui.side.fire('click');
  assert.equal(JSON.parse(ui.store.values().next().value).scrollTop,513);
});
test('sidebar scroll, toggle, BFCache and disabled storage are safe',()=>{
  const ui=sidebar(); ui.nav.scrollTop=77; ui.nav.fire('scroll');ui.frame();
  ui.group.open=false;ui.group.fire('toggle'); ui.nav.scrollTop=0;
  ui.win.fire('pageshow',{persisted:true});ui.frame();
  assert.equal(ui.nav.scrollTop,77);assert.equal(ui.group.open,true);
  assert.doesNotThrow(()=>{const privateUi=sidebar(null,true);privateUi.side.fire('click');privateUi.win.fire('pagehide');});
});
const postal = {cep:'01001-000',street:'Praça da Sé',neighborhood:'Sé',city:'São Paulo',state:'SP',ibge:'3550308'};
function address(initial={}) {
  const ids=['lookup-cep','lookup-state','lookup-city','lookup-street','lookup-cep-button','lookup-address-button','address-status','address-results','address-map-link','id_name','id_municipality','id_state','id_ibge_code'];
  const fields=Object.fromEntries(ids.map(id=>[id,new Element(initial[id]||'')]));
  const box=new Element();box.dataset={addressLookup:'/local/lookup',mapUrl:'/map'};
  box.closest=()=>({elements:{csrfmiddlewaretoken:{value:'synthetic-csrf'}}});
  const requests=[];
  vm.runInNewContext(source('address-lookup.js'),{document:{querySelector:()=>box,getElementById:id=>fields[id],createElement:()=>new Element()},AbortController,encodeURIComponent,setTimeout,clearTimeout,fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))});
  const query=()=>{fields['lookup-cep'].value='01001000';fields['lookup-cep-button'].fire('click');};
  const respond=async(index,item=postal)=>{requests[index].resolve({ok:true,json:async()=>({data:[item]})});await new Promise(resolve=>setImmediate(resolve));};
  return {fields,query,respond,requests};
}
test('CEP fills only public reference fields over same-origin CSRF POST',async()=>{
  const ui=address();ui.query();await ui.respond(0);
  assert.equal(ui.fields.id_municipality.value,'São Paulo');assert.equal(ui.fields.id_name.value,'Sé');
  assert.equal(ui.fields.id_ibge_code.value,'3550308');
  assert.equal(ui.requests[0].options.method,'POST');
  assert.deepEqual(JSON.parse(ui.requests[0].options.body),{cep:'01001000'});
  assert.equal(ui.requests[0].options.headers['X-CSRFToken'],'synthetic-csrf');
  assert.match(ui.fields['address-map-link'].href,/municipio=3550308/);
});
test('CEP preserves typed location as a unit until an explicit result click',async()=>{
  const ui=address({id_name:'Área da equipe',id_municipality:'Fortaleza',id_state:'CE',id_ibge_code:'2304400'});
  ui.query();await ui.respond(0);
  assert.equal(ui.fields.id_municipality.value,'Fortaleza');assert.equal(ui.fields.id_state.value,'CE');assert.equal(ui.fields.id_ibge_code.value,'2304400');assert.equal(ui.fields.id_name.value,'Área da equipe');
  assert.match(ui.fields['address-status'].textContent,/Mantivemos/);
  ui.fields['address-results'].children[0].fire('click');
  assert.equal(ui.fields.id_municipality.value,'São Paulo');assert.equal(ui.fields.id_state.value,'SP');
});
test('explicit replacement clears an obsolete IBGE when the new result has none',async()=>{
  const ui=address({id_municipality:'Fortaleza',id_state:'CE',id_ibge_code:'2304400'});
  ui.query();await ui.respond(0,{...postal,ibge:''});
  ui.fields['address-results'].children[0].fire('click');
  assert.equal(ui.fields.id_ibge_code.value,'');assert.equal(ui.fields['address-map-link'].hidden,true);
});
test('a late response cannot replace a newer CEP result',async()=>{
  const ui=address();ui.query();ui.query();
  assert.equal(ui.requests[0].options.signal.aborted,true);
  await ui.respond(1);await ui.respond(0,{...postal,city:'Old result'});
  assert.equal(ui.fields.id_municipality.value,'São Paulo');
});
test('a new CEP without a neighborhood clears only the previously autofilled name',async()=>{
  const ui=address();ui.query();await ui.respond(0);
  ui.query();await ui.respond(1,{...postal,neighborhood:''});
  assert.equal(ui.fields.id_name.value,'');
  ui.fields.id_name.value='Nome escolhido pela equipe';ui.query();await ui.respond(2,{...postal,neighborhood:''});
  assert.equal(ui.fields.id_name.value,'Nome escolhido pela equipe');
});

(() => {
  document.querySelectorAll('input[type="password"]').forEach(input=>{
    const wrapper=document.createElement('div');wrapper.className='password-control';input.before(wrapper);wrapper.append(input);
    const toggle=document.createElement('button');toggle.type='button';toggle.className='password-toggle';toggle.textContent='Mostrar';toggle.setAttribute('aria-label',`Mostrar ${input.labels?.[0]?.textContent||'senha'}`);toggle.setAttribute('aria-pressed','false');if(input.id)toggle.setAttribute('aria-controls',input.id);wrapper.append(toggle);
    toggle.addEventListener('click',()=>{const show=input.type==='password';input.type=show?'text':'password';toggle.textContent=show?'Ocultar':'Mostrar';toggle.setAttribute('aria-label',`${show?'Ocultar':'Mostrar'} ${input.labels?.[0]?.textContent||'senha'}`);toggle.setAttribute('aria-pressed',String(show));});
    const warning=document.createElement('p');warning.className='caps-warning';warning.textContent='Caps Lock está ativado.';warning.hidden=true;warning.setAttribute('role','status');wrapper.after(warning);input.addEventListener('keyup',event=>{warning.hidden=!event.getModifierState?.('CapsLock');});input.addEventListener('blur',()=>{warning.hidden=true;});
  });
})();

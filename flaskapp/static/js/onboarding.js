// static/js/onboarding.js
document.addEventListener('DOMContentLoaded', function () {
  const modal = document.getElementById('onboard-modal');
  if (!modal) { console.warn('[onboarding] #onboard-modal not found'); return; }

  const bodyEl = document.getElementById('onboard-body');
  const progEl = document.getElementById('onboard-progress');
  const stepLabel = document.getElementById('onboard-step-label');
  const btnBack = document.getElementById('onboard-back');
  const btnNext = document.getElementById('onboard-next');
  const btnFinish = document.getElementById('onboard-finish');
  const btnSaveExit = document.getElementById('onboard-save-exit');
  const btnClose = document.getElementById('onboard-close');

  // Backdrop close support
  const backdrop = modal.querySelector('.absolute.inset-0');

  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const totalSteps = 8;
  let step = 1;
  let model = {};

  function lockScroll() { document.documentElement.classList.add('overflow-hidden'); document.body.classList.add('overflow-hidden'); }
  function unlockScroll() { document.documentElement.classList.remove('overflow-hidden'); document.body.classList.remove('overflow-hidden'); }

  function open(){
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    lockScroll();
  }
  function close(){
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    unlockScroll();
  }
  function pct(){ return Math.round((step-1)/(totalSteps-1)*100); }
  function setProgress(){
    if (progEl) progEl.style.width = pct() + '%';
    if (stepLabel) stepLabel.textContent = `Step ${step} of ${totalSteps}`;
    if (btnBack) btnBack.disabled = (step === 1);
    if (btnNext) btnNext.classList.toggle('hidden', step === totalSteps);
    if (btnFinish) btnFinish.classList.toggle('hidden', step !== totalSteps);
    if (btnSaveExit) btnSaveExit.classList.toggle('hidden', step === totalSteps);
  }
  const esc = (s)=> (s ?? '');
  const join = (arr)=> Array.isArray(arr) ? arr.join(', ') : (arr || '');

  function render(){
    setProgress();
    if (!bodyEl) return;
    let html = '';
    switch(step){
      case 1: html = `
        <div class="grid md:grid-cols-2 gap-4">
          <div><label class="text-sm text-gray-600">Business name</label>
            <input class="w-full border rounded px-3 py-2" name="business_name" value="${esc(model.business_name)}"></div>
          <div><label class="text-sm text-gray-600">Phone</label>
            <input class="w-full border rounded px-3 py-2" name="phone" value="${esc(model.phone)}"></div>
          <div class="md:col-span-2"><label class="text-sm text-gray-600">Website</label>
            <input class="w-full border rounded px-3 py-2" name="website" value="${esc(model.website)}"></div>
          <div class="md:col-span-2"><label class="text-sm text-gray-600">Service area (city/ZIPs)</label>
            <input class="w-full border rounded px-3 py-2" name="service_area" value="${esc(model.service_area)}"></div>
        </div>`; break;

      case 2: html = `
        <div class="grid md:grid-cols-2 gap-4">
          <div><label class="text-sm text-gray-600">Services (comma separated)</label>
            <input class="w-full border rounded px-3 py-2" name="services" value="${join(model.services)}"></div>
          <div><label class="text-sm text-gray-600">Top services (up to 3)</label>
            <input class="w-full border rounded px-3 py-2" name="top_services" value="${join(model.top_services)}"></div>
          <div class="md:col-span-2"><label class="text-sm text-gray-600">Price position</label>
            <select class="w-full border rounded px-3 py-2" name="price_position">
              ${['','budget','competitive','premium'].map(v => `<option value="${v}" ${v===esc(model.price_position)?'selected':''}>${v||'Select...'}</option>`).join('')}
            </select></div>
        </div>`; break;

      case 3: html = `
        <div class="grid md:grid-cols-2 gap-4">
          <div><label class="text-sm text-gray-600">Ideal customers (comma separated)</label>
            <input class="w-full border rounded px-3 py-2" name="ideal_customers" value="${join(model.ideal_customers)}"></div>
          <div><label class="text-sm text-gray-600">Urgency</label>
            <select class="w-full border rounded px-3 py-2" name="urgency">
              ${['','emergency','scheduled','both'].map(v => `<option value="${v}" ${v===esc(model.urgency)?'selected':''}>${v||'Select...'}</option>`).join('')}
            </select></div>
          <div><label class="text-sm text-gray-600">Tone</label>
            <select class="w-full border rounded px-3 py-2" name="tone">
              ${['','friendly','professional','direct'].map(v => `<option value="${v}" ${v===esc(model.tone)?'selected':''}>${v||'Select...'}</option>`).join('')}
            </select></div>
          <div><label class="text-sm text-gray-600">Lead channels (comma separated)</label>
            <input class="w-full border rounded px-3 py-2" name="lead_channels" value="${join(model.lead_channels)}"></div>
        </div>`; break;

      case 4: html = `
        <div>
          <label class="text-sm text-gray-600">Why choose you?</label>
          <textarea class="w-full border rounded px-3 py-2" name="why_choose_us" rows="5">${esc(model.why_choose_us)}</textarea>
        </div>`; break;

      case 5: html = `
        <div class="grid md:grid-cols-2 gap-4">
          <div><label class="text-sm text-gray-600">Current promo (optional)</label>
            <input class="w-full border rounded px-3 py-2" name="current_promo" value="${esc(model.current_promo)}"></div>
          <div><label class="text-sm text-gray-600">Hours</label>
            <input class="w-full border rounded px-3 py-2" name="hours" value="${esc(model.hours)}"></div>
        </div>`; break;

      case 6: html = `
        <div class="grid md:grid-cols-2 gap-4">
          <div><label class="text-sm text-gray-600">Primary goal</label>
            <select class="w-full border rounded px-3 py-2" name="primary_goal">
              ${['','fill_schedule','steady_recurring','brand_awareness','upsell_high_value'].map(v => `<option value="${v}" ${v===esc(model.primary_goal)?'selected':''}>${v||'Select...'}</option>`).join('')}
            </select></div>
          <div><label class="text-sm text-gray-600">Ads budget</label>
            <select class="w-full border rounded px-3 py-2" name="ads_budget">
              ${['','starter','growth','aggressive'].map(v => `<option value="${v}" ${v===esc(model.ads_budget)?'selected':''}>${v||'Select...'}</option>`).join('')}
            </select></div>
        </div>`; break;

      case 7: html = `
        <div class="space-y-4">
          <div>
            <label class="text-sm text-gray-600">Your edge (what makes you different?)</label>
            <textarea class="w-full border rounded px-3 py-2" name="edge_statement" rows="4">${esc(model.edge_statement)}</textarea>
          </div>
          <div>
            <label class="text-sm text-gray-600">Competitors to monitor (optional)</label>
            <textarea class="w-full border rounded px-3 py-2" name="competitors" rows="3">${esc(model.competitors)}</textarea>
          </div>
        </div>`; break;

      case 8: html = `
        <div class="space-y-3">
          <div class="text-sm text-gray-600">Approvals:</div>
          <label class="inline-flex items-center gap-2">
            <input type="checkbox" name="approvals_via_email" ${model.approvals_via_email ? 'checked':''}>
            <span>Send campaign drafts to my email for approval</span>
          </label>
          <div class="mt-4 p-3 rounded border bg-gray-50 text-sm text-gray-700">
            <strong>Summary</strong><br>
            <div><b>Business:</b> ${esc(model.business_name)} · ${esc(model.service_area)}</div>
            <div><b>Top services:</b> ${Array.isArray(model.top_services)?model.top_services.join(', '):esc(model.top_services)}</div>
            <div><b>Positioning:</b> ${esc(model.price_position) || '—'}</div>
            <div><b>Goal/Budget:</b> ${esc(model.primary_goal) || '—'} / ${esc(model.ads_budget) || '—'}</div>
          </div>
        </div>`; break;
    }
    bodyEl.innerHTML = html;
  }

  function collect(){
    const data = {};
    bodyEl?.querySelectorAll('input,select,textarea').forEach(el=>{
      if(el.type === 'checkbox'){ data[el.name] = !!el.checked; }
      else{ data[el.name] = el.value; }
    });
    Object.assign(model, data);
    return data;
  }

  async function loadProfile(){
    try{
      const r = await fetch('/onboarding/me', {credentials:'same-origin'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      model = j.data || {};
      console.log('[onboarding] profile loaded');
    }catch(err){
      console.warn('[onboarding] load failed, continuing with empty model:', err);
    }
  }

  async function saveStep(){
    try{
      const payload = { step, data: collect() };
      const r = await fetch('/onboarding/save', {
        method:'POST',
        headers:{'Content-Type':'application/json','X-CSRFToken':CSRF},
        body: JSON.stringify(payload),
        credentials:'same-origin'
      });
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
    }catch(err){
      console.warn('[onboarding] save failed:', err);
    }
  }

  async function markComplete(){
    try{
      const r = await fetch('/onboarding/complete', {
        method:'POST',
        headers:{'X-CSRFToken':CSRF},
        credentials:'same-origin'
      });
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
    }catch(err){
      console.warn('[onboarding] complete failed:', err);
    }
  }

  function bindLaunchers(){
    const classBtns = Array.from(document.querySelectorAll('.onboard-launch'));
    const idBtn = document.getElementById('onboard-launch'); // legacy support
    const all = classBtns.concat(idBtn ? [idBtn] : []);
    console.log(`[onboarding] launchers found: ${all.length}`);
    all.forEach(btn=>{
      btn.addEventListener('click', async (e)=>{
        e.preventDefault();
        step = 1;
        open();
        render();            // show immediately
        await loadProfile(); // then hydrate
        render();
      });
    });
    // Delegation safety net (works for dynamically inserted buttons)
    document.addEventListener('click', function(ev){
      const t = ev.target.closest('.onboard-launch, #onboard-launch');
      if (!t) return;
      ev.preventDefault();
      step = 1; open(); render();
      (async()=>{ await loadProfile(); render(); })();
    });
  }

  // Controls
  btnClose?.addEventListener('click', ()=> close());
  backdrop?.addEventListener('click', (e)=> { if (e.target === backdrop) close(); });

  document.addEventListener('keydown', (e)=>{
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
      close();
    }
  });

  btnBack?.addEventListener('click', async ()=>{ await saveStep(); step = Math.max(1, step-1); render(); });
  btnNext?.addEventListener('click', async ()=>{ await saveStep(); step = Math.min(totalSteps, step+1); render(); });
  btnSaveExit?.addEventListener('click', async ()=>{ await saveStep(); close(); });
  btnFinish?.addEventListener('click', async ()=>{
    await saveStep(); await markComplete(); close(); window.location.reload();
  });

  // Manual opener for quick dev
  window._openOnboarding = function(){ step = 1; open(); render(); };

  // Auto-open via URL hash
  if (location.hash === '#onboard') {
    step = 1; open(); render(); (async()=>{ await loadProfile(); render(); })();
  }

  bindLaunchers();
  console.log('[onboarding] modal found:', !!modal);
});

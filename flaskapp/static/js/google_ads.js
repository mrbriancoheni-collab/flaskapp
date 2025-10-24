// static/js/google_ads.js
(function () {
  const overlay = document.getElementById('ai-overlay');

  function getCookie(name){
    return document.cookie.split('; ').find(r => r.startsWith(name+'='))?.split('=')[1];
  }
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const inp = document.querySelector('input[name="csrf_token"]');
    if (inp && inp.value) return inp.value;
    return getCookie('csrf_token') || getCookie('XSRF-TOKEN') || getCookie('csrf');
  }

  function setBusy(btn, busyText) {
    if (!btn) return;
    if (!btn.dataset.aiOriginal) btn.dataset.aiOriginal = btn.innerHTML;
    btn.classList.add('ai-busy');
    btn.disabled = true;
    btn.innerHTML = `<span class="ai-spinner" aria-hidden="true"></span>${busyText || 'Working…'}`;
    overlay?.classList.add('show');
  }
  function clearBusy(btn) {
    if (!btn) return;
    btn.classList.remove('ai-busy');
    btn.disabled = false;
    if (btn.dataset.aiOriginal) btn.innerHTML = btn.dataset.aiOriginal;
    overlay?.classList.remove('show');
  }
  function li(text){
    const el=document.createElement('li');
    el.textContent=String(text||'');
    return el;
  }
  function show(el, on){ if(!el) return; el.classList.toggle('hidden', !on); }

  async function safeJson(res){
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) return await res.json();
    const text = await res.text();
    try { return JSON.parse(text) } catch { return { error: text } }
  }

  // Generic fetch-button handler (Optimize / Refresh)
  document.querySelectorAll('[data-ai-action="fetch"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const url    = btn.dataset.aiUrl;
      const method = (btn.dataset.aiMethod || 'POST').toUpperCase();
      const busy   = btn.dataset.aiBusy || 'Working…';
      const body   = btn.dataset.aiBody;
      const token  = getCsrfToken();

      if (!url) return alert('Missing URL for action.');

      setBusy(btn, busy);

      const init = { method, headers: {}, credentials: 'same-origin' };
      if (method !== 'GET') {
        init.headers['Content-Type'] = 'application/json';
        init.body = body || '{}';
      }
      if (token) {
        init.headers['X-CSRFToken'] = token;
        init.headers['X-CSRF-Token'] = token;
        init.headers['X-XSRF-TOKEN'] = token;
      }

      try {
        const res = await fetch(url, init);
        const j = await safeJson(res);
        if (!res.ok || j?.ok === false) throw new Error(j?.error || `HTTP ${res.status}`);

        // If optimize, fill suggestion lists
        if (url.includes('/ads/optimize.json') && j?.suggestions) {
          const map = {
            'campaigns': document.getElementById('sugCampaigns'),
            'adgroups': document.getElementById('sugAdgroups'),
            'keywords': document.getElementById('sugKeywords'),
            'negatives': document.getElementById('sugNegatives'),
            'ads': document.getElementById('sugAds'),
            'extensions': document.getElementById('sugExtensions')
          };
          Object.entries(map).forEach(([k, ul]) => {
            if (!ul) return;
            ul.innerHTML = '';
            (j.suggestions[k] || []).forEach(t => ul.appendChild(li(t)));
          });
        }

        if (btn.dataset.aiReload === 'true') window.location.reload();
      } catch (e) {
        console.error('AI fetch error:', e);
        alert('Action failed: ' + (e?.message || e));
      } finally {
        clearBusy(btn);
      }
    });
  });

  // “Run AI Review” (GET JSON → fill three panels)
  const runBtn = document.getElementById('runAdsAI');
  const out = document.getElementById('adsAiOut');
  const sum = document.getElementById('adsAiSummary');
  const ins = document.getElementById('adsAiInsights');
  const chk = document.getElementById('adsAiChecklist');

  if (runBtn) {
    runBtn.addEventListener('click', async () => {
      const urlBase = runBtn.dataset.aiUrl;
      if (!urlBase) return alert('Missing AI Review URL');
      const url = new URL(urlBase, window.location.origin);
      url.searchParams.set('_', String(Date.now()));

      setBusy(runBtn, runBtn.dataset.aiBusy || 'Analyzing…');
      sum.textContent=''; ins.innerHTML=''; chk.innerHTML='';
      try {
        const res = await fetch(url.toString(), { method: 'GET', headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
        const j = await safeJson(res);
        if (!res.ok) throw new Error(j?.error || `HTTP ${res.status}`);

        sum.textContent = j.summary || 'No summary.';
        (j.insights || []).forEach(t => ins.appendChild(li(t)));
        (j.checklist || []).forEach(t => chk.appendChild(li(t)));
        show(out, true);
      } catch (e) {
        console.error('AI Review error:', e);
        sum.textContent = 'Could not load AI review.';
        show(out, true);
      } finally {
        clearBusy(runBtn);
      }
    });
  }
})();

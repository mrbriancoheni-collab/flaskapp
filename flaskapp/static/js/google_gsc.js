(function () {
  const form = document.getElementById('gscForm');
  if (!form) return;

  const sitesUrl    = form.dataset.sitesUrl;
  const saveUrl     = form.dataset.saveUrl;
  const dataUrl     = form.dataset.dataUrl;
  const insightsUrl = form.dataset.insightsUrl;

  const propSel = document.getElementById('gscPropSelect');
  const saveBtn = document.getElementById('gscSaveBtn');
  const propMsg = document.getElementById('gscPropMsg');
  const tfSel   = document.getElementById('gscTf');
  const optBtn  = document.getElementById('gscOptimizeBtn');

  const label   = document.getElementById('gscPropLabel');
  const period  = document.getElementById('gscPeriod');
  const clicks  = document.getElementById('gscClicks');
  const impr    = document.getElementById('gscImpr');
  const ctr     = document.getElementById('gscCtr');
  const pos     = document.getElementById('gscPos');
  const pagesT  = document.getElementById('gscPages');
  const queriesT= document.getElementById('gscQueries');
  const aiText  = document.getElementById('gscAiText');
  const aiStatus= document.getElementById('gscAiStatus');

  // Load sites into select
  if (sitesUrl) {
    fetch(sitesUrl).then(r => r.json()).then(j => {
      const cur = j.selected || '';
      propSel.innerHTML = '';
      (j.sites || []).forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.siteUrl;
        opt.selected = (s.siteUrl === cur);
        opt.textContent = s.siteUrl;
        propSel.appendChild(opt);
      });
      if (!propSel.value && cur) {
        const opt = document.createElement('option');
        opt.value = cur; opt.selected = true; opt.textContent = cur;
        propSel.appendChild(opt);
      }
    }).catch(()=>{});
  }

  // Save selected site
  saveBtn?.addEventListener('click', () => {
    const site = propSel.value;
    propMsg.textContent = 'Saving…';
    fetch(saveUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({site_url: site})
    }).then(r => r.json()).then(() => {
      propMsg.textContent = 'Saved';
      setTimeout(()=>propMsg.textContent='', 1500);
      label.textContent = site;
      refreshData();
    }).catch(() => propMsg.textContent = 'Error');
  });

  function refreshData() {
    const params = new URLSearchParams({ timeframe: tfSel.value });
    fetch(`${dataUrl}?${params}`)
      .then(r => r.json())
      .then(d => {
        period.textContent = d.period || '';
        clicks.textContent = (d.summary?.clicks ?? d.clicks ?? 0);
        impr.textContent   = (d.summary?.impressions ?? d.impressions ?? 0);
        ctr.textContent    = `${(d.summary?.ctr_pct ?? d.ctr_pct ?? 0).toFixed(2)}%`;
        pos.textContent    = (d.summary?.avg_position ?? d.avg_position ?? 0).toFixed(1);

        pagesT.innerHTML = (d.top_pages || []).map(p =>
          `<tr class="border-t"><td class="py-2 pr-3 font-mono">${p.page || p.url}</td><td class="py-2 pr-3">${p.clicks}</td><td class="py-2 pr-3">${p.impressions}</td><td class="py-2 pr-3">${(p.ctr ?? p.ctr_pct).toFixed ? (p.ctr ?? p.ctr_pct).toFixed(2) : (p.ctr ?? p.ctr_pct)}${(p.ctr || p.ctr_pct) ? '%' : ''}</td><td class="py-2 pr-3">${p.position}</td></tr>`
        ).join('') || `<tr class="border-t"><td class="py-3 text-gray-400" colspan="5">No data.</td></tr>`;

        queriesT.innerHTML = (d.top_queries || []).map(q =>
          `<tr class="border-t"><td class="py-2 pr-3">${q.query}</td><td class="py-2 pr-3">${q.clicks}</td><td class="py-2 pr-3">${q.impressions}</td><td class="py-2 pr-3">${(q.ctr ?? q.ctr_pct).toFixed ? (q.ctr ?? q.ctr_pct).toFixed(2) : (q.ctr ?? q.ctr_pct)}${(q.ctr || q.ctr_pct) ? '%' : ''}</td><td class="py-2 pr-3">${q.position}</td></tr>`
        ).join('') || `<tr class="border-t"><td class="py-3 text-gray-400" colspan="5">No data.</td></tr>`;
      });
  }

  tfSel?.addEventListener('change', refreshData);

  // Optimize (AI)
  optBtn?.addEventListener('click', () => {
    aiStatus.textContent = 'Thinking…';
    aiText.innerHTML = '';
    const params = new URLSearchParams({ timeframe: tfSel.value });
    fetch(`${insightsUrl}?${params}`)
      .then(r => r.json())
      .then(j => {
        aiStatus.textContent = j.ok === false ? 'Error' : 'Done';
        const md = (j.insights || '').trim();
        if (!md) { aiText.innerHTML = '<p class="text-gray-400">No insights available.</p>'; return; }
        // very light markdown -> HTML (headings + bullets)
        aiText.innerHTML = md
          .replace(/^### (.*)$/gm,'<h3 class="font-semibold mt-3 mb-1">$1</h3>')
          .replace(/^## (.*)$/gm,'<h3 class="font-semibold mt-3 mb-1">$1</h3>')
          .replace(/^\- (.*)$/gm,'<li>$1</li>')
          .replace(/(<li>.*<\/li>)(?!\s*<li>)/gs,'<ul class="list-disc pl-5">$1</ul>')
          .replace(/\n/g,'<br/>');
      })
      .catch(() => aiStatus.textContent = 'Error');
  });

  // initial pull so the page isn’t empty
  refreshData();
})();

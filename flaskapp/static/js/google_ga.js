// static/js/google_ga.js
function getCookie(name){
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? decodeURIComponent(m.pop()) : '';
}

document.addEventListener('DOMContentLoaded', async () => {
  const sel  = document.getElementById('gaPropSelect');
  const save = document.getElementById('gaPropSave');
  const msg  = document.getElementById('gaPropMsg');

  const EP  = (window.GA_ENDPOINTS || {});
  const PROPS_URL = EP.props || '/account/google/analytics/properties.json';
  const SAVE_URL  = EP.save  || '/account/google/analytics/select';
  const currentId = (EP.currentId || sel?.dataset.currentId || '').trim();

  const setMsg = (text, ok = true) => {
    if (!msg) return;
    msg.textContent = text || '';
    msg.style.color = ok ? '#4b5563' : '#b91c1c';
  };

  async function loadProps() {
    try {
      const res = await fetch(PROPS_URL, { credentials: 'same-origin' });
      const ctype = (res.headers.get('content-type') || '').toLowerCase();

      if (!res.ok) {
        const body = await res.text();
        console.error('[GA] properties.json error', res.status, body.slice(0, 200));
        setMsg(`Failed to load properties (HTTP ${res.status})`, false);
        if (sel) sel.innerHTML = '<option value="">Failed to load</option>';
        return;
      }
      if (!ctype.includes('application/json')) {
        const body = await res.text();
        console.error('[GA] properties.json non-JSON', body.slice(0, 200));
        setMsg('Failed to load properties (non-JSON, maybe session expired)', false);
        if (sel) sel.innerHTML = '<option value="">Failed to load</option>';
        return;
      }

      const data = await res.json();
      if (!sel) return;
      sel.innerHTML = '';

      if (data.ok && Array.isArray(data.properties) && data.properties.length) {
        for (const p of data.properties) {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.name || p.id;
          sel.appendChild(opt);
        }
        sel.value = currentId || data.properties[0].id;
        setMsg('');
      } else {
        sel.innerHTML = '<option value="">No properties found</option>';
        setMsg('No properties found', false);
      }
    } catch (e) {
      console.error('[GA] properties.json fetch error', e);
      if (sel) sel.innerHTML = '<option value="">Failed to load</option>';
      setMsg('Failed to load properties (network/parse)', false);
    }
  }

  await loadProps();

  save?.addEventListener('click', async () => {
    const pid = sel?.value || '';
    if (!pid) { setMsg('Pick a property first', false); return; }
    try {
      const body = new URLSearchParams({
        property_id: pid,
        property_name: sel.options[sel.selectedIndex]?.text || ''
      });
      const res = await fetch(SAVE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        credentials: 'same-origin',
        body
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setMsg('Saved');
        await fetchGaData(true); // refresh UI after save; mark as first load
      } else {
        setMsg(data.error || `Save failed (HTTP ${res.status})`, false);
      }
    } catch (e) {
      console.error('[GA] save error', e);
      setMsg('Save failed', false);
    }
  });
});

// ------- GA data hydrate -------
async function fetchGaData(firstLoad = false) {
  const EP = window.GA_ENDPOINTS || {};
  const DATA_URL = EP.data || '/account/google/analytics/data';

  const overlay = document.getElementById('gaOverlay');
  const status = document.getElementById('gaStatus');

  const setStatus = (t, ok = true) => {
    if (status) { status.textContent = t || ''; status.style.color = ok ? '#4b5563' : '#b91c1c'; }
  };
  const show = el => el && el.classList.remove('hidden');
  const hide = el => el && el.classList.add('hidden');

  try {
    setStatus('Loading…');
    // If connected, ensure overlay visible on first load to hide any placeholders
    if (firstLoad) show(overlay);

    const url = new URL(DATA_URL, window.location.origin);
    const tf = document.getElementById('timeframe')?.value || '28d';
    url.searchParams.set('timeframe', tf);

    const res = await fetch(url.toString(), { credentials: 'same-origin' });
    if (!res.ok) {
      const body = await res.text();
      console.error('[GA] data error', res.status, body.slice(0, 200));
      setStatus(`Failed (HTTP ${res.status})`, false);
      return;
    }

    const data = await res.json();

    // Header
    const propName = document.getElementById('propName');
    const period   = document.getElementById('periodLabel');
    if (propName) propName.textContent = data.property_name || 'GA4 Property';
    if (period)   period.textContent   = data.period || '';

    // KPIs
    const setField = (name, val) => {
      const el = document.querySelector(`[data-field="${name}"]`);
      if (el) el.textContent = (name === 'revenue' && typeof val === 'number') ? `$${val.toFixed(2)}` : (val ?? '');
    };
    setField('sessions', data.sessions);
    setField('users', data.users);
    setField('engaged_sessions', data.engaged_sessions);
    setField('avg_engagement_time', data.avg_engagement_time);
    setField('conversions', data.conversions);
    setField('revenue', data.revenue);

    // Tables
    const rows = (arr, tmpl, emptyCols) =>
      (arr && arr.length)
        ? arr.map(tmpl).join('')
        : `<tr><td colspan="${emptyCols}" class="py-2 pr-3 text-gray-400">No rows</td></tr>`;

    const tbodyPages = document.getElementById('rowsPages');
    if (tbodyPages) {
      tbodyPages.innerHTML = rows(
        data.top_pages || [],
        r => `<tr class="border-t">
                <td class="py-2 pr-3 font-mono">${r.url || '/'}</td>
                <td class="py-2 pr-3">${r.views ?? ''}</td>
                <td class="py-2 pr-3">${r.engagement ?? ''}</td>
              </tr>`,
        3
      );
    }

    const tbodySrc = document.getElementById('rowsSources');
    if (tbodySrc) {
      tbodySrc.innerHTML = rows(
        data.top_sources || [],
        r => `<tr class="border-t">
                <td class="py-2 pr-3">${r.source || ''}</td>
                <td class="py-2 pr-3">${r.sessions ?? ''}</td>
              </tr>`,
        2
      );
    }

    const tbodyConv = document.getElementById('rowsConversions');
    if (tbodyConv) {
      tbodyConv.innerHTML = rows(
        data.conversions_by_event || [],
        r => `<tr class="border-t">
                <td class="py-2 pr-3">${r.event || ''}</td>
                <td class="py-2 pr-3">${r.count ?? ''}</td>
              </tr>`,
        2
      );
    }

    // Mark that live data has been fetched; helpful if you want to gate future UI
    localStorage.setItem('gaDataFetched', '1');

    setStatus('Done');
  } catch (e) {
    console.error('[GA] fetch error', e);
    setStatus('Failed to load data', false);
  } finally {
    hide(overlay);
  }
}

// Wire “Pull GA Data” + auto-load if connected
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('gaFetchForm');
  form?.addEventListener('submit', (ev) => {
    ev.preventDefault();
    fetchGaData(true);
  });

  // Auto-load if the page indicates it's connected
  const isConnected = document.querySelector('p.text-gray-600')?.textContent?.includes('Connected to');
  if (isConnected) fetchGaData(true);
});

// ---------- AI INSIGHTS ----------
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('genAiBtn');
  if (!btn) return;

  const spin = document.getElementById('aiSpinner');
  const status = document.getElementById('aiStatus');
  const summaryEl = document.getElementById('aiSummary');
  const insightsEl = document.getElementById('aiInsights');
  const improvementsEl = document.getElementById('aiImprovements');

  const EP = window.GA_ENDPOINTS || {};
  const formAi = document.getElementById('gaFetchForm')?.dataset?.aiUrl;
  const fallbackUrl = '/account/google/analytics/insights';
  const insightsUrl = (EP.insights && EP.insights.trim()) || (formAi && formAi.trim()) || fallbackUrl;

  // Ensure no stale tooltip remains
  btn.removeAttribute('title');

  const show = el => el && el.classList.remove('hidden');
  const hide = el => el && el.classList.add('hidden');
  const esc = s => String(s)
    .replaceAll('&','&amp;').replaceAll('<','&lt;')
    .replaceAll('>','&gt;').replaceAll('"','&quot;')
    .replaceAll("'",'&#39;');

  const setStatus = (t, ok=true) => {
    if (!status) return;
    status.textContent = t || '';
    status.style.color = ok ? '#6b7280' : '#b91c1c';
  };

  btn.addEventListener('click', async () => {
    if (btn.disabled) return;
    btn.disabled = true; show(spin); setStatus('Thinking…');

    try {
      const tf = document.getElementById('timeframe')?.value || '28d';
      const url = new URL(insightsUrl, window.location.origin);
      url.searchParams.set('timeframe', tf);

      const res = await fetch(url.toString(), { credentials: 'same-origin' });
      const isJson = (res.headers.get('content-type') || '').toLowerCase().includes('application/json');
      const payload = isJson ? await res.json() : {};
      if (!res.ok) {
        setStatus(payload.summary || `Failed (HTTP ${res.status})`, false);
      } else {
        setStatus('Done');
      }

      if (summaryEl) summaryEl.textContent = payload.summary || 'No summary available.';
      if (insightsEl) {
        const arr = Array.isArray(payload.insights) ? payload.insights : [];
        insightsEl.innerHTML = arr.length ? arr.map(x => `<li>${esc(x)}</li>`).join('') :
          '<li class="text-gray-400">No insights available.</li>';
      }
      if (improvementsEl) {
        const arr = Array.isArray(payload.improvements) ? payload.improvements : [];
        improvementsEl.innerHTML = arr.length ? arr.map(x => `<li>${esc(x)}</li>`).join('') :
          '<li class="text-gray-400">No recommendations available.</li>';
      }
    } catch (e) {
      console.error('[GA] insights error', e);
      setStatus('Failed to generate insights', false);
    } finally {
      hide(spin); btn.disabled = false;
    }
  });
});

// ---------- AI OPTIMIZE (optional endpoint) ----------
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('gaOptimizeBtn');
  if (!btn || !window.GA_ENDPOINTS || !window.GA_ENDPOINTS.optimize) return;

  btn.addEventListener('click', async () => {
    if (btn.disabled) return;
    const old = btn.innerHTML;
    btn.disabled = true; btn.innerHTML = 'Queuing…';
    try {
      const tf = document.getElementById('timeframe')?.value || '28d';
      const res = await fetch(window.GA_ENDPOINTS.optimize, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrf_token')
        },
        body: JSON.stringify({ timeframe: tf, scope: 'all' }),
        credentials: 'same-origin'
      });
      const j = await res.json().catch(()=>({}));
      alert(j.message || 'Optimization queued');
    } catch(e){ console.error(e); alert('Could not start optimization'); }
    finally { btn.disabled = false; btn.innerHTML = old; }
  });
});

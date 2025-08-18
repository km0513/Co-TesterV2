(function(){
  const $ = (id) => document.getElementById(id);
  const startBtn = $('startBtn');
  const statusBtn = $('statusBtn');
  const stopBtn = $('stopBtn');
  const genBtn = $('genBtn');
  const clearBtn = $('clearBtn');
  const copyBtn = $('copyBtn');
  // More menu controls (decluttered)
  const moreBtn = $('moreBtn');
  const moreMenu = $('moreMenu');
  const moreStatus = $('moreStatus');
  const moreClear = $('moreClear');
  const moreExport = $('moreExport');
  const morePomTs = $('morePomTs');
  const morePomJs = $('morePomJs');
  const moreReset = $('moreReset');
  const sessionIdEl = $('sessionId');
  const actionCountEl = $('actionCount');
  const actionList = $('actionList');
  // Extract Elements panel
  const extractCard = $('extractCard');
  const elementsPanel = $('elementsPanel');
  const extractBtn = $('extractBtn');
  const backBtn = $('backBtn');
  const downloadExtractBtn = $('downloadExtractBtn');
  const extractPomTs = $('extractPomTs');
  const extractPomJs = $('extractPomJs');
  // HTML paste mode
  const pasteCard = $('pasteCard');
  const htmlModeBtn = $('htmlModeBtn');
  const pasteBackBtn = $('pasteBackBtn');
  const previewHtmlBtn = $('previewHtmlBtn');
  const clearHtmlBtn = $('clearHtmlBtn');
  const htmlTextarea = $('htmlTextarea');
  const htmlPreview = $('htmlPreview');
  const selectedPreview = $('selectedPreview');
  const selectedSnapshot = $('selectedSnapshot');
  const openExtractFromPaste = $('openExtractFromPaste');
  const elementsList = $('elementsList');
  const elementsCount = $('elementsCount');
  const elementSearch = $('elementSearch');
  const codeOut = $('codeOut');
  const urlInput = $('targetUrl');
  // Pages & naming controls
  const pageInput = $('pageInput');
  const addPageBtn = $('addPageBtn');
  const savePagesBtn = $('savePagesBtn');
  const pagesChips = $('pagesChips');
  const saveNamesBtn = $('saveNamesBtn');

  let currentSessionId = null;
  let cachedElements = [];
  let pages = [];

  function setBusy(el, busy){
    if(!el) return;
    el.disabled = !!busy;
    if(busy) el.dataset.loading = '1'; else delete el.dataset.loading;
  }

  async function apiClear(){
    if(!currentSessionId){ await apiStatus(); /* try to load */ }
    if(!currentSessionId){ return; }
    setBusy(clearBtn, true);
    try {
      const res = await fetch('/api/autoheal/clear', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ session_id: currentSessionId })
      });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Failed to clear'); }
      actionCountEl.textContent = '0';
      showActions([]);
    } catch(err){
      alert('Clear failed: ' + err.message);
    } finally { setBusy(clearBtn, false); }
  }

  function showActions(actions){
    if(!actionList) return;
    actionList.innerHTML = '';
    if(!actions || actions.length === 0){
      actionList.innerHTML = '<div class="muted">No actions recorded yet.</div>';
      return;
    }
    actions.forEach((a, i) => {
      const div = document.createElement('div');
      div.className = 'item';
      const el = a.element || {};
      const locBits = [];
      if(el['data-testid']) locBits.push(`data-testid=${el['data-testid']}`);
      if(el.id) locBits.push(`#${el.id}`);
      if(el.role && el.text) locBits.push(`role=${el.role} name="${(el.text||'').slice(0,40)}"`);
      if(el.placeholder) locBits.push(`placeholder=${el.placeholder}`);
      if(el.ariaLabel) locBits.push(`aria-label=${el.ariaLabel}`);
      if(el.cssPath) locBits.push(`css=${(el.cssPath||'').slice(0,60)}`);
      if(el.xpath) locBits.push(`xpath=${(el.xpath||'').slice(0,60)}`);
      const btnHtml = a.element_key ? `<button class="ghost" data-ekey="${a.element_key}" data-idx="${i}">Copy Getter</button>` : '';
      div.innerHTML = `
        <div class="inline" style="gap:6px;">
          <strong>#${i+1} ${a.type}</strong>
          <span class="muted">${locBits.join(' • ')}</span>
          <span>${btnHtml}</span>
        </div>
        ${a.value ? `<div class="muted">value: ${a.value}</div>` : ''}
      `;
      // attach per-element copy handler
      const btn = div.querySelector('button[data-ekey]');
      if(btn){
        btn.addEventListener('click', async () => {
          try {
            const qs = new URLSearchParams({ key: btn.dataset.ekey, session_id: currentSessionId || '' , lang: 'ts' });
            const res = await fetch(`/api/autoheal/pom/element?${qs.toString()}`);
            if(!res.ok){ throw new Error('Failed to fetch getter'); }
            const txt = await res.text();
            await navigator.clipboard.writeText(txt);
            const old = btn.textContent; btn.textContent = 'Copied'; setTimeout(()=> btn.textContent = old, 900);
          } catch(err){ alert('Copy failed: ' + err.message); }
        });
      }
      actionList.appendChild(div);
    });
  }

  function renderElements(list){
    elementsList.innerHTML = '';
    if(!list || list.length === 0){
      elementsList.innerHTML = '<div class="muted">No elements captured yet.</div>';
      return;
    }
    const optionHtml = (sel) => {
      const set = new Set((pages || []).map(p => p));
      if(sel && !set.has(sel)) set.add(sel);
      return Array.from(set).map(p => `<option value="${p}">${p}</option>`).join('');
    };
    list.forEach((e) => {
      const div = document.createElement('div');
      div.className = 'item';
      const snap = e.snapshot || {};
      const bits = [];
      if(snap['data-testid']) bits.push(`data-testid=${snap['data-testid']}`);
      if(snap.id) bits.push(`#${snap.id}`);
      if(snap.role && snap.text) bits.push(`role=${snap.role} name="${(snap.text||'').slice(0,40)}"`);
      if(snap.placeholder) bits.push(`placeholder=${snap.placeholder}`);
      if(snap.ariaLabel) bits.push(`aria-label=${snap.ariaLabel}`);
      const hint = e.name || snap.nameAttr || snap.placeholder || snap.ariaLabel || snap.text || snap.tag || e.key;
      const curPage = e.page || '';
      const curName = e.user_name || '';
      const ok = !!(curPage && curName);
      div.innerHTML = `
        <div class="inline" style="align-items:flex-start; gap:10px;">
          <div style="flex:1;">
            <div style="display:flex; align-items:center; gap:8px;">
              <strong title="${e.key}">${ok ? '✅' : '⚠️'} ${hint}</strong>
              <span class="muted">${bits.join(' • ')}</span>
            </div>
            <div style="display:flex; gap:8px; margin-top:8px;">
              <select class="pageSel" data-ekey="${e.key}" style="border:1px solid var(--border); padding:8px; border-radius:8px; min-width:160px;">
                <option value="">Select page</option>
                ${optionHtml(curPage)}
              </select>
              <input class="nameInput" data-ekey="${e.key}" type="text" value="${curName || ''}" placeholder="Element name (e.g., LoginButton)" style="border:1px solid var(--border); padding:8px; border-radius:8px; flex:1;" />
            </div>
          </div>
          <div class="buttons">
            <button class="ghost" data-ekey="${e.key}" title="Copy POM getter">Copy Getter</button>
          </div>
        </div>
      `;
      const btn = div.querySelector('button[data-ekey]');
      btn?.addEventListener('click', async () => {
        try {
          const qs = new URLSearchParams({ key: e.key, session_id: currentSessionId || '' , lang: 'ts' });
          const res = await fetch(`/api/autoheal/pom/element?${qs.toString()}`);
          if(!res.ok){ throw new Error('Failed to fetch getter'); }
          const txt = await res.text();
          await navigator.clipboard.writeText(txt);
          const old = btn.textContent; btn.textContent = 'Copied'; setTimeout(()=> btn.textContent = old, 900);
        } catch(err){ alert('Copy failed: ' + err.message); }
      });
      elementsList.appendChild(div);
    });
  }

  async function loadElements(){
    if(!currentSessionId) return;
    try{
      const qs = new URLSearchParams({ session_id: currentSessionId });
      const res = await fetch(`/api/autoheal/export?${qs.toString()}`);
      const j = await res.json();
      if(j && j.success){
        cachedElements = j.elements || [];
        if(elementsCount){ elementsCount.textContent = String(cachedElements.length); }
        // Render immediately if Extract panel is visible
        if(extractCard && !extractCard.classList.contains('hidden')){
          const q = (elementSearch?.value || '').toLowerCase();
          const filtered = q ? cachedElements.filter(e => {
            const s = JSON.stringify(e).toLowerCase();
            return s.includes(q);
          }) : cachedElements;
          renderElements(filtered);
        }
      }
    } catch(err){ console.warn('Export load failed:', err); }
  }

  // Pages management
  function renderPagesChips(){
    if(!pagesChips) return;
    if(!pages || pages.length === 0){ pagesChips.innerHTML = '<span class="muted">No pages yet</span>'; return; }
    pagesChips.innerHTML = pages.map(p => `<span style="display:inline-flex; align-items:center; gap:6px; border:1px solid var(--border); padding:4px 8px; border-radius:999px; margin-right:6px;">${p}<a href="#" data-page="${p}" style="text-decoration:none; color:#ef4444;">✕</a></span>`).join('');
    pagesChips.querySelectorAll('a[data-page]')?.forEach(a => {
      a.addEventListener('click', (e) => { e.preventDefault(); const name = a.getAttribute('data-page'); pages = pages.filter(x => x !== name); renderPagesChips(); });
    });
  }

  async function loadPages(){
    if(!currentSessionId) return;
    try {
      const qs = new URLSearchParams({ session_id: currentSessionId });
      const res = await fetch(`/api/autoheal/pages?${qs.toString()}`);
      const j = await res.json();
      if(j && j.success){ pages = j.pages || []; renderPagesChips(); }
    } catch(err){ console.warn('Load pages failed:', err); }
  }

  async function savePages(){
    if(!currentSessionId){ alert('No active session'); return; }
    try{
      const res = await fetch('/api/autoheal/pages', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: currentSessionId, pages }) });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Save pages failed'); }
      pages = j.pages || [];
      renderPagesChips();
      // re-render elements to reflect page options
      const q = (elementSearch?.value || '').toLowerCase();
      const filtered = q ? cachedElements.filter(e => JSON.stringify(e).toLowerCase().includes(q)) : cachedElements;
      renderElements(filtered);
    } catch(err){ alert('Save pages failed: ' + err.message); }
  }

  // Names assignment
  async function saveNames(){
    if(!currentSessionId){ alert('No active session'); return; }
    const assignments = {};
    elementsList.querySelectorAll('.item')?.forEach(item => {
      const sel = item.querySelector('select.pageSel');
      const inp = item.querySelector('input.nameInput');
      if(!sel || !inp) return;
      const ek = sel.getAttribute('data-ekey') || inp.getAttribute('data-ekey');
      const page = sel.value.trim();
      const name = inp.value.trim();
      if(page && name){ assignments[ek] = { page, name }; }
    });
    try{
      const res = await fetch('/api/autoheal/elements/names', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: currentSessionId, assignments }) });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Save names failed'); }
      await loadElements();
      alert(`Saved names for ${j.updated} element(s).`);
    } catch(err){ alert('Save names failed: ' + err.message); }
  }

  function allNamed(){
    if(!cachedElements || cachedElements.length === 0) return false;
    return cachedElements.every(e => (e.page && e.user_name));
  }

  async function apiStart(){
    let url = (urlInput.value || '').trim();
    if(!url) { alert('Please enter a URL'); return; }
    // Ensure scheme; default to https
    if(!/^https?:\/\//i.test(url)) {
      url = 'https://' + url;
    }
    setBusy(startBtn, true);
    try {
      const res = await fetch('/api/autoheal/start', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ url })
      });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Failed to start'); }
      currentSessionId = j.session_id;
      sessionIdEl.textContent = currentSessionId;
      await apiStatus();
    } catch(err){
      alert('Start failed: ' + err.message);
    } finally { setBusy(startBtn, false); }
  }

  async function apiStatus(){
    try {
      const qs = currentSessionId ? `?session_id=${encodeURIComponent(currentSessionId)}` : '';
      const res = await fetch(`/api/autoheal/status${qs}`);
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'No active session'); }
      currentSessionId = j.session_id;
      sessionIdEl.textContent = currentSessionId;
      actionCountEl.textContent = (j.actions || []).length;
      showActions(j.actions || []);
      // Refresh element cache & count
      loadElements();
    } catch(err){
      // keep UI but notify
      console.warn('Status error:', err);
    }
  }

  async function apiStop(){
    setBusy(stopBtn, true);
    try {
      const res = await fetch('/api/autoheal/stop', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ session_id: currentSessionId || undefined })
      });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Failed to stop'); }
      if(actionList){ actionList.innerHTML = '<div class="muted">Session stopped. You can now generate the test.</div>'; }
      // Keep currentSessionId so /generate-test can use it, and refresh status to show final actions
      await apiStatus();
    } catch(err){
      alert('Stop failed: ' + err.message);
    } finally { setBusy(stopBtn, false); }
  }

  async function apiGenerate(){
    setBusy(genBtn, true);
    try {
      const res = await fetch('/api/autoheal/generate-test', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ session_id: currentSessionId || undefined })
      });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Failed to generate'); }
      codeOut.value = j.code || '';
    } catch(err){
      alert('Generate failed: ' + err.message);
    } finally { setBusy(genBtn, false); }
  }

  function copyCode(){
    if(!codeOut.value) return;
    navigator.clipboard.writeText(codeOut.value).then(() => {
      const old = copyBtn.textContent; copyBtn.textContent = 'Copied!';
      setTimeout(()=> copyBtn.textContent = old, 900);
    });
  }

  async function apiExport(){
    if(!currentSessionId){ await apiStatus(); if(!currentSessionId) { alert('No active session'); return; } }
    try {
      const qs = new URLSearchParams({ session_id: currentSessionId });
      const res = await fetch(`/api/autoheal/export?${qs.toString()}`);
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Export failed'); }
      const blob = new Blob([JSON.stringify(j, null, 2)], {type:'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'autoheal-elements.json'; a.click();
      URL.revokeObjectURL(url);
    } catch(err){ alert('Export failed: ' + err.message); }
  }

  function ensureExtractVisible(){
    if(!extractCard) return;
    if(extractCard.classList.contains('hidden')){
      extractCard.classList.remove('hidden');
      loadPages();
      loadElements();
    }
  }

  function downloadPom(lang){
    if(!currentSessionId){ alert('No active session'); return; }
    if(!allNamed()){
      alert('Please assign Page and Name for all elements first.');
      ensureExtractVisible();
      return;
    }
    const qs = new URLSearchParams({ session_id: currentSessionId, lang });
    // Let browser handle attachment
    window.open(`/api/autoheal/pom?${qs.toString()}`, '_blank');
  }

  // Extract panel toggles
  function showExtract(){ if(!extractCard) return; extractCard.classList.remove('hidden'); loadPages(); loadElements(); }
  function hideExtract(){ if(!extractCard) return; extractCard.classList.add('hidden'); }
  extractBtn?.addEventListener('click', showExtract);
  backBtn?.addEventListener('click', hideExtract);

  // Paste mode toggles
  function showPaste(){ if(!pasteCard) return; pasteCard.classList.remove('hidden'); }
  function hidePaste(){ if(!pasteCard) return; pasteCard.classList.add('hidden'); }
  htmlModeBtn?.addEventListener('click', showPaste);
  pasteBackBtn?.addEventListener('click', hidePaste);
  openExtractFromPaste?.addEventListener('click', () => { showExtract(); });

  // Build element snapshot from DOM element
  function buildSnapshot(el){
    if(!el || el.nodeType !== 1) return {};
    const snap = {};
    try {
      snap.tag = el.tagName?.toLowerCase();
      snap.id = el.id || undefined;
      snap.classList = Array.from(el.classList || []);
      snap['data-testid'] = el.getAttribute && el.getAttribute('data-testid') || undefined;
      snap.nameAttr = el.getAttribute && el.getAttribute('name') || undefined;
      snap.placeholder = el.getAttribute && el.getAttribute('placeholder') || undefined;
      snap.ariaLabel = el.getAttribute && el.getAttribute('aria-label') || undefined;
      // Try role and text
      snap.role = el.getAttribute && (el.getAttribute('role') || undefined);
      const text = (el.innerText || '').trim();
      snap.text = text ? text.slice(0, 120) : undefined;
      // Build simple CSS path
      snap.cssPath = buildCssPath(el);
      // Build simple XPath
      snap.xpath = buildXPath(el);
      // Try href for links
      if(el.tagName?.toLowerCase() === 'a'){ snap.href = el.getAttribute('href') || undefined; }
      // bounding box relative to document
      const r = el.getBoundingClientRect();
      snap.bbox = { x: r.x, y: r.y, width: r.width, height: r.height };
    } catch(e) {}
    return snap;
  }

  function buildCssPath(el){
    const parts = [];
    while(el && el.nodeType === 1 && parts.length < 6){
      let sel = el.nodeName.toLowerCase();
      if(el.id){ sel += `#${el.id}`; parts.unshift(sel); break; }
      const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0,2);
      if(cls.length){ sel += '.' + cls.join('.'); }
      const parent = el.parentElement;
      if(parent){
        const siblings = Array.from(parent.children).filter(n => n.nodeName === el.nodeName);
        if(siblings.length > 1){ sel += `:nth-of-type(${siblings.indexOf(el)+1})`; }
      }
      parts.unshift(sel);
      el = el.parentElement;
    }
    return parts.join(' > ');
  }

  function buildXPath(el){
    const parts = [];
    while(el && el.nodeType === 1 && parts.length < 6){
      let ix = 1;
      let sib = el.previousSibling;
      while(sib){ if(sib.nodeType === 1 && sib.nodeName === el.nodeName) ix++; sib = sib.previousSibling; }
      parts.unshift(el.nodeName.toLowerCase() + `[${ix}]`);
      el = el.parentNode;
    }
    return '//' + parts.join('/');
  }

  function wirePreviewClicks(){
    try{
      const doc = htmlPreview?.contentDocument || htmlPreview?.contentWindow?.document;
      if(!doc) return;
      doc.body.addEventListener('click', async (ev) => {
        ev.preventDefault(); ev.stopPropagation();
        const el = ev.target;
        const snap = buildSnapshot(el);
        // show previews
        if(selectedPreview){ selectedPreview.textContent = el?.outerHTML || ''; }
        if(selectedSnapshot){ selectedSnapshot.textContent = JSON.stringify(snap, null, 2); }
        // save to backend
        if(currentSessionId){
          try{
            const res = await fetch('/api/autoheal/select', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: currentSessionId, snapshot: snap }) });
            const j = await res.json();
            if(!j.success){ console.warn('Select failed:', j.error); }
            else {
              // refresh cache and UI counts immediately
              await loadElements();
              // quick visual feedback
              if(selectedPreview){
                selectedPreview.style.outline = '2px solid #22c55e';
                setTimeout(()=>{ selectedPreview.style.outline = 'none'; }, 500);
              }
            }
          }catch(e){ console.warn('Select error:', e); }
        }
      }, true);
    }catch(e){ console.warn('wirePreviewClicks failed', e); }
  }

  function loadHtmlIntoPreview(html){
    if(!htmlPreview) return;
    const doc = htmlPreview.contentDocument || htmlPreview.contentWindow.document;
    doc.open(); doc.write(html || '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'); doc.close();
    wirePreviewClicks();
  }

  previewHtmlBtn?.addEventListener('click', () => {
    const html = (htmlTextarea?.value || '').trim();
    loadHtmlIntoPreview(html);
  });
  clearHtmlBtn?.addEventListener('click', () => { if(htmlTextarea) htmlTextarea.value = ''; if(selectedPreview) selectedPreview.textContent=''; if(selectedSnapshot) selectedSnapshot.textContent=''; loadHtmlIntoPreview(''); });

  // Search in elements
  elementSearch?.addEventListener('input', () => {
    const q = (elementSearch.value || '').toLowerCase();
    const filtered = q ? cachedElements.filter(e => {
      const s = JSON.stringify(e).toLowerCase();
      return s.includes(q);
    }) : cachedElements;
    renderElements(filtered);
  });

  addPageBtn?.addEventListener('click', () => {
    const v = (pageInput?.value || '').trim();
    if(!v) return;
    if(!pages.includes(v)) pages.push(v);
    pageInput.value = '';
    renderPagesChips();
    // update element page selects
    const q = (elementSearch?.value || '').toLowerCase();
    const filtered = q ? cachedElements.filter(e => JSON.stringify(e).toLowerCase().includes(q)) : cachedElements;
    renderElements(filtered);
  });
  savePagesBtn?.addEventListener('click', savePages);
  saveNamesBtn?.addEventListener('click', saveNames);

  // More menu
  function toggleMore(force){
    if(!moreMenu) return;
    if(force === undefined){
      moreMenu.classList.toggle('hidden');
    } else {
      moreMenu.classList.toggle('hidden', !force);
    }
  }

  moreBtn?.addEventListener('click', (e) => { e.stopPropagation(); toggleMore(true); });
  document.addEventListener('click', (e) => {
    if(!moreMenu) return;
    if(!moreMenu.classList.contains('hidden')){
      if(!moreMenu.contains(e.target) && e.target !== moreBtn){ toggleMore(false); }
    }
  });

  moreStatus?.addEventListener('click', () => { toggleMore(false); apiStatus(); });
  moreClear?.addEventListener('click', () => { toggleMore(false); apiClear(); });
  moreExport?.addEventListener('click', () => { toggleMore(false); if(!allNamed()){ alert('Please assign Page and Name for all elements first.'); ensureExtractVisible(); return; } apiExport(); });
  morePomTs?.addEventListener('click', () => { toggleMore(false); downloadPom('ts'); });
  morePomJs?.addEventListener('click', () => { toggleMore(false); downloadPom('js'); });
  moreReset?.addEventListener('click', async () => {
    toggleMore(false);
    if(!currentSessionId){ alert('No active session'); return; }
    try{
      const res = await fetch('/api/autoheal/reset', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ session_id: currentSessionId })
      });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Reset failed'); }
      currentSessionId = null;
      sessionIdEl.textContent = '-';
      actionCountEl.textContent = '0';
      showActions([]);
      cachedElements = [];
      elementsCount.textContent = '0';
      renderElements([]);
    } catch(err){ alert('Reset failed: ' + err.message); }
  });

  startBtn?.addEventListener('click', apiStart);
  statusBtn?.addEventListener('click', apiStatus);
  stopBtn?.addEventListener('click', apiStop);
  genBtn?.addEventListener('click', apiGenerate);
  clearBtn?.addEventListener('click', apiClear);
  copyBtn?.addEventListener('click', copyCode);
  // legacy btns removed in decluttered UI; kept handlers above for More menu

  // best effort load existing session, if any
  apiStatus();
})();

(function(){
  const $ = (id) => document.getElementById(id);
  const newSessionBtn = $('newSessionBtn');
  const sessionIdEl = $('sessionId');
  const htmlTextarea = $('htmlTextarea');
  const htmlPreview = $('htmlPreview');
  const previewHtmlBtn = $('previewHtmlBtn');
  const clearHtmlBtn = $('clearHtmlBtn');
  const selectedPreview = $('selectedPreview');
  const selectedSnapshot = $('selectedSnapshot');
  const elementsCount = $('elementsCount');
  const elementsList = $('elementsList');
  const downloadExtractBtn = $('downloadExtractBtn');
  const clearSelectedBtn = $('clearSelectedBtn');

  let currentSessionId = null;
  let cachedElements = [];
  // minimal mode: no pages/naming

  // Overlay-based highlight state
  let selectedSet = new Set(); // keys by cssPath
  const selectedOverlays = new Map(); // cssPath -> overlay div
  let hoverOverlay = null;
  function getDoc(){ return htmlPreview?.contentDocument || htmlPreview?.contentWindow?.document; }
  function cssEscapeSafe(s){
    try{ return (window.CSS && window.CSS.escape) ? window.CSS.escape(String(s)) : String(s).replace(/[^a-zA-Z0-9_-]/g, '\\$&'); }catch{ return String(s||''); }
  }
  function qsSafe(doc, sel){
    try{ return doc.querySelector(sel); }catch(e){ console.warn('Invalid selector skipped:', sel); return null; }
  }
  function getOverlayHost(){
    const doc = getDoc(); if(!doc) return null;
    let host = doc.getElementById('ah-overlay-host');
    if(!host){
      host = doc.createElement('div');
      host.id = 'ah-overlay-host';
      // Ensure host never affects layout of page content
      host.style.position = 'fixed';
      host.style.top = '0'; host.style.left = '0'; host.style.right = '0'; host.style.bottom = '0';
      host.style.pointerEvents = 'none';
      host.style.zIndex = '2147483647';
      // Attach to body (margins are reset in ensurePreviewStyles)
      (doc.body || doc.documentElement).appendChild(host);
      if(host.attachShadow){
        const root = host.attachShadow({ mode: 'open' });
        const s = doc.createElement('style');
        s.textContent = `.box{ position:absolute; box-sizing:border-box; pointer-events:none; }`;
        root.appendChild(s);
        host._ahRoot = root;
      } else {
        host._ahRoot = host;
      }
    }
    return host._ahRoot || host;
  }
  function makeOverlay(color, dashed){
    const doc = getDoc() || document;
    const root = getOverlayHost(); if(!root) return null;
    const d = doc.createElement('div');
    d.className = 'box';
    d.style.border = `2px ${dashed ? 'dashed' : 'solid'} ${color}`;
    d.style.background = 'transparent';
    root.appendChild(d);
    return d;
  }
  function placeOverlay(div, rect){
    if(!div || !rect) return;
    // Position relative to iframe viewport, not document
    div.style.left = rect.left + 'px';
    div.style.top = rect.top + 'px';
    div.style.width = Math.max(0, rect.width) + 'px';
    div.style.height = Math.max(0, rect.height) + 'px';
  }
  function ensureSelectedOverlay(cssPath){
    const doc = getDoc(); if(!doc) return;
    const el = cssPath && qsSafe(doc, cssPath);
    if(!el || (el.tagName && /^(HTML|BODY)$/i.test(el.tagName))) return;
    const rect = el.getBoundingClientRect();
    let ov = selectedOverlays.get(cssPath);
    if(!ov){ ov = makeOverlay('#22c55e', false); if(!ov) return; selectedOverlays.set(cssPath, ov); }
    placeOverlay(ov, rect);
  }
  function ensureSelectedOverlayForEl(cssPath, el){
    if(!el || (el.tagName && /^(HTML|BODY)$/i.test(el.tagName))) return;
    const rect = el.getBoundingClientRect();
    let ov = selectedOverlays.get(cssPath);
    if(!ov){ ov = makeOverlay('#22c55e', false); if(!ov) return; selectedOverlays.set(cssPath, ov); }
    placeOverlay(ov, rect);
  }
  function removeSelectedOverlay(cssPath){
    const ov = selectedOverlays.get(cssPath);
    if(ov && ov.parentNode) ov.parentNode.removeChild(ov);
    selectedOverlays.delete(cssPath);
  }
  function showHoverOverlay(cssPath){
    const doc = getDoc(); if(!doc) return;
    const el = cssPath && qsSafe(doc, cssPath);
    if(!el || (el.tagName && /^(HTML|BODY)$/i.test(el.tagName))) return;
    const rect = el.getBoundingClientRect();
    if(!hoverOverlay){ hoverOverlay = makeOverlay('#3b82f6', true); }
    placeOverlay(hoverOverlay, rect);
  }
  function showHoverOverlayForEl(el){
    if(!el || (el.tagName && /^(HTML|BODY)$/i.test(el.tagName))) return;
    const rect = el.getBoundingClientRect();
    if(!hoverOverlay){ hoverOverlay = makeOverlay('#3b82f6', true); }
    placeOverlay(hoverOverlay, rect);
  }
  function hideHoverOverlay(){ if(hoverOverlay && hoverOverlay.parentNode){ hoverOverlay.parentNode.removeChild(hoverOverlay); } hoverOverlay = null; }
  function updateAllOverlays(){
    // Reposition all selected overlays and hover overlay on scroll/resize
    for(const [key, ov] of selectedOverlays.entries()){
      const doc = getDoc(); if(!doc) continue; const el = qsSafe(doc, key); if(!el) { removeSelectedOverlay(key); continue; }
      placeOverlay(ov, el.getBoundingClientRect());
    }
    if(hoverOverlay){ /* will be repositioned on next hover; keep as-is */ }
  }
  function rebuildOverlaysFromCache(){
    const need = new Set();
    (cachedElements || []).forEach(e => { const css = e?.snapshot?.cssPath; if(css) need.add(css); });
    // Remove overlays that are no longer needed
    for(const key of Array.from(selectedOverlays.keys())){
      if(!need.has(key)) removeSelectedOverlay(key);
    }
    // Ensure overlays exist for needed items
    for(const css of need){ ensureSelectedOverlay(css); }
    selectedSet = need;
  }

  function setBusy(el, busy){ if(!el) return; el.disabled = !!busy; if(busy) el.dataset.loading = '1'; else delete el.dataset.loading; }

  async function newSession(){
    setBusy(newSessionBtn, true);
    try{
      const res = await fetch('/api/autoheal/session', { method:'POST' });
      const j = await res.json();
      if(!j.success){ throw new Error(j.error || 'Failed to create session'); }
      currentSessionId = j.session_id;
      sessionIdEl.textContent = currentSessionId;
      await loadElements();
      rebuildOverlaysFromCache();
    }catch(e){ alert('New session failed: ' + e.message); }
    finally{ setBusy(newSessionBtn, false); }
  }

  function buildCssPath(el){
    const parts = [];
    while(el && el.nodeType === 1 && parts.length < 6){
      let sel = el.nodeName.toLowerCase();
      const idAttr = (el.getAttribute && el.getAttribute('id')) || el.id || '';
      const idSafe = idAttr && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(idAttr) ? idAttr : (idAttr ? cssEscapeSafe(idAttr) : '');
      if(idSafe){ sel += `#${idSafe}`; parts.unshift(sel); break; }
      // Handle SVGAnimatedString className by reading attribute first
      const classAttr = (el.getAttribute && el.getAttribute('class')) || '';
      let raw = classAttr ? classAttr : (el.classList ? Array.from(el.classList).join(' ') : '');
      const cls = raw.toString().trim().split(/\s+/).filter(Boolean).map(cssEscapeSafe).filter(Boolean).slice(0,2);
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
      let ix = 1; let sib = el.previousSibling;
      while(sib){ if(sib.nodeType === 1 && sib.nodeName === el.nodeName) ix++; sib = sib.previousSibling; }
      parts.unshift(el.nodeName.toLowerCase() + `[${ix}]`);
      el = el.parentNode;
    }
    return '//' + parts.join('/');
  }
  function buildSnapshot(el){
    if(!el || el.nodeType !== 1) return {};
    const snap = {};
    try{
      snap.tag = el.tagName?.toLowerCase();
      snap.id = el.id || undefined;
      snap.classList = Array.from(el.classList || []);
      snap['data-testid'] = el.getAttribute && el.getAttribute('data-testid') || undefined;
      snap.nameAttr = el.getAttribute && el.getAttribute('name') || undefined;
      snap.placeholder = el.getAttribute && el.getAttribute('placeholder') || undefined;
      snap.ariaLabel = el.getAttribute && el.getAttribute('aria-label') || undefined;
      snap.role = el.getAttribute && (el.getAttribute('role') || undefined);
      const text = (el.innerText || '').trim(); snap.text = text ? text.slice(0,120) : undefined;
      snap.cssPath = buildCssPath(el); snap.xpath = buildXPath(el);
      if(el.tagName?.toLowerCase() === 'a'){
        // Prefer preserved original href if we rewrote it
        const original = el.getAttribute('data-ah-href') || el.getAttribute('href');
        snap.href = original || undefined;
      }
      const r = el.getBoundingClientRect(); snap.bbox = { x: r.x, y: r.y, width: r.width, height: r.height };
    }catch(e){}
    return snap;
  }

  function neutralizeDocNavigation(doc){
    const preventNav = (e) => {
      try{ e.preventDefault(); }catch{ }
      // Do NOT stop propagation so our selection handler still runs
      return false;
    };
    // Intercept typical navigation-causing events in capture phase
    ['click','mousedown','mouseup','pointerdown','pointerup','auxclick','submit','dragstart'].forEach(type => {
      doc.addEventListener(type, (e) => {
        const t = e.target;
        if(!t) return;
        const a = t.closest && t.closest('a[href]');
        const sub = t.closest && t.closest('form, button[type="submit"], input[type="submit"]');
        if(a || sub || type === 'dragstart'){ try{ e.preventDefault(); }catch{} try{ e.stopPropagation(); }catch{} try{ e.stopImmediatePropagation && e.stopImmediatePropagation(); }catch{} return false; }
      }, true);
    });
    // Ensure forms cannot navigate
    doc.addEventListener('submit', preventNav, true);
    // Prevent focus-based CSS layout changes
    doc.addEventListener('focusin', (e) => { try{ e.target && e.target.blur && e.target.blur(); }catch{} }, true);
    // Do NOT rewrite hrefs to avoid :target CSS side-effects; preventing default is sufficient
  }

  function wirePreviewClicks(){
    const doc = getDoc();
    if(!doc || !doc.body) return;
    ensurePreviewStyles(doc);
    doc.addEventListener('click', async (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      try{ ev.stopImmediatePropagation && ev.stopImmediatePropagation(); }catch{}
      let el = ev.target;
      if(!el || el.nodeType !== 1){ el = el && el.parentElement ? el.parentElement : null; }
      if(!el || el.nodeType !== 1) return;
      // Skip selecting html/body to avoid full-page highlight
      if(el && el.tagName && /^(HTML|BODY)$/i.test(el.tagName)) return;
      const snap = buildSnapshot(el);
      const key = snap.cssPath;
      if(selectedPreview){ selectedPreview.textContent = el?.outerHTML || ''; }
      if(selectedSnapshot){ selectedSnapshot.textContent = JSON.stringify(snap, null, 2); }
      if(!currentSessionId){
        console.warn('[HTML Extractor] No session; creating...');
        await newSession();
        if(!currentSessionId){ alert('Failed to create session. Please click New Session and try again.'); return; }
      }
      try{
        if(key && selectedSet.has(key)){
          // Deselect
          console.debug('[HTML Extractor] Deselect', key);
          const res = await fetch('/api/autoheal/deselect', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: currentSessionId, snapshot: snap }) });
          const j = await res.json(); if(!j.success){ console.warn('Deselect failed:', j.error); alert('Deselect failed: ' + (j.error||'Unknown')); }
          selectedSet.delete(key); removeSelectedOverlay(key);
        } else {
          // Select
          console.debug('[HTML Extractor] Select', key);
          const res = await fetch('/api/autoheal/select', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: currentSessionId, snapshot: snap }) });
          const j = await res.json(); if(!j.success){ console.warn('Select failed:', j.error); alert('Select failed: ' + (j.error||'Unknown')); }
          if(key){ selectedSet.add(key); ensureSelectedOverlayForEl(key, el); }
        }
        await loadElements();
      }catch(e){ console.warn('Select/deselect error:', e); }
    }, true);
    // After our selector is attached, neutralize navigation
    neutralizeDocNavigation(doc);
    // Keep overlays positioned
    doc.addEventListener('scroll', updateAllOverlays, true);
    (htmlPreview?.contentWindow)?.addEventListener('resize', updateAllOverlays);
  }
  function loadHtmlIntoPreview(html){
    const doc = htmlPreview.contentDocument || htmlPreview.contentWindow.document;
    // Always force Standards Mode by writing our own skeleton document
    const skeleton = '<!doctype html>\n<html><head><meta charset="utf-8"><meta http-equiv="X-UA-Compatible" content="IE=edge"></head><body><div id="ah-content-root"></div></body></html>';
    doc.open(); doc.write(skeleton); doc.close();
    try{ console.debug('[HTML Extractor] compatMode:', doc.compatMode); }catch{ }
    try{
      const root = doc.getElementById('ah-content-root');
      if(root){ root.innerHTML = html || ''; }
    }catch{ /* ignore malformed HTML in paste */ }
    // Reset overlay state on new content
    selectedSet.clear();
    for(const key of Array.from(selectedOverlays.keys())) removeSelectedOverlay(key);
    hideHoverOverlay();
    wirePreviewClicks();
  }

  function ensurePreviewStyles(doc){
    if(doc.getElementById('ah-styles')) return;
    const style = doc.createElement('style');
    style.id = 'ah-styles';
    style.textContent = `
      /* Hardened reset to prevent interaction-driven layout changes */
      html, body { margin:0 !important; padding:0 !important; width:100% !important; height:100% !important; }
      html { overflow:hidden !important; position:relative !important; }
      body { overflow:auto !important; position:relative !important; contain:layout style paint !important; }
      *, *::before, *::after { box-sizing: border-box; }
      *:focus { outline: none !important; }
      *:active { transform:none !important; box-shadow:none !important; }
      a, button, img { -webkit-tap-highlight-color: transparent; }
      a:active, a:focus, img:active, img:focus { outline:none !important; transform:none !important; box-shadow:none !important; position:static !important; top:auto !important; left:auto !important; right:auto !important; bottom:auto !important; width:auto !important; height:auto !important; }
      a, img { user-select:none; -webkit-user-drag:none; }
      img { max-width:100%; height:auto; }
      .ah-highlight, .ah-hover { outline: none !important; background: transparent !important; }
      #ah-content-root { position: relative; min-height: 0; contain:layout style paint !important; }
    `;
    doc.head.appendChild(style);
  }

  function renderElements(list){
    elementsList.innerHTML = '';
    if(!list || list.length === 0){ elementsList.innerHTML = '<div class="muted">No elements captured yet.</div>'; return; }
    list.forEach((e) => {
      const div = document.createElement('div'); div.className = 'item';
      const snap = e.snapshot || {}; const bits = [];
      if(snap['data-testid']) bits.push(`data-testid=${snap['data-testid']}`);
      if(snap.id) bits.push(`#${snap.id}`);
      if(snap.role && snap.text) bits.push(`role=${snap.role} name="${(snap.text||'').slice(0,40)}"`);
      if(snap.placeholder) bits.push(`placeholder=${snap.placeholder}`);
      if(snap.ariaLabel) bits.push(`aria-label=${snap.ariaLabel}`);
      const hint = snap.nameAttr || snap.placeholder || snap.ariaLabel || snap.text || snap.tag || e.key;
      div.innerHTML = `
        <div class="inline" style="align-items:flex-start; gap:10px;">
          <div style="flex:1;">
            <div style="display:flex; align-items:center; gap:8px;">
              <strong title="${e.key}">${hint}</strong>
              <span class="muted">${bits.join(' • ')}</span>
            </div>
            <details style="margin-top:8px;">
              <summary class="muted" style="cursor:pointer;">Selectors</summary>
              <div style="display:grid; grid-template-columns: 1fr auto; gap:6px; align-items:center; margin-top:6px;">
                <div><code>${escapeHtml(snap.cssPath || '')}</code></div>
                <button class="ghost small copyCss">Copy CSS</button>
                <div><code>${escapeHtml(snap.xpath || '')}</code></div>
                <button class="ghost small copyXpath">Copy XPath</button>
                ${snap.role && snap.text ? `<div>role=${escapeHtml(snap.role)} name="${escapeHtml(snap.text)}"</div><span></span>` : ''}
                ${snap['data-testid'] ? `<div>data-testid=${escapeHtml(snap['data-testid'])}</div><span></span>` : ''}
                ${snap.id ? `<div>#${escapeHtml(snap.id)}</div><span></span>` : ''}
              </div>
            </details>
          </div>
          <div class="buttons">
            <button class="ghost danger removeBtn" title="Remove">Remove</button>
          </div>
        </div>
      `;
      // Copy selectors
      const cssBtn = div.querySelector('.copyCss'); cssBtn?.addEventListener('click', async () => { try{ await navigator.clipboard.writeText(snap.cssPath || ''); }catch{} });
      const xpBtn = div.querySelector('.copyXpath'); xpBtn?.addEventListener('click', async () => { try{ await navigator.clipboard.writeText(snap.xpath || ''); }catch{} });
      // Remove/deselect from list
      const rm = div.querySelector('.removeBtn');
      rm?.addEventListener('click', async () => {
        try{
          const res = await fetch('/api/autoheal/deselect', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: currentSessionId, snapshot: snap }) });
          const j = await res.json(); if(!j.success){ throw new Error(j.error || 'Remove failed'); }
          await loadElements();
          if(snap.cssPath){ selectedSet.delete(snap.cssPath); removeSelectedOverlay(snap.cssPath); }
        }catch(err){ alert('Remove failed: ' + err.message); }
      });
      // Hover to highlight in preview
      div.addEventListener('mouseenter', () => {
        try{
          const doc = getDoc(); if(!doc) return; ensurePreviewStyles(doc); if(snap.cssPath){ showHoverOverlay(snap.cssPath); }
        }catch{}
      });
      div.addEventListener('mouseleave', () => {
        try{
          hideHoverOverlay();
        }catch{}
      });
      elementsList.appendChild(div);
    });
  }

  function escapeHtml(s){
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
  async function loadElements(){
    if(!currentSessionId) return;
    try{
      const qs = new URLSearchParams({ session_id: currentSessionId });
      const res = await fetch(`/api/autoheal/export?${qs.toString()}`);
      const j = await res.json();
      if(j && j.success){ cachedElements = j.elements || []; if(elementsCount){ elementsCount.textContent = String(cachedElements.length); }
        renderElements(cachedElements); rebuildOverlaysFromCache();
      }
    }catch(e){ console.warn('Export load failed:', e); }
  }
  // minimal mode: no pages/naming/POM

  previewHtmlBtn?.addEventListener('click', () => { const html = (htmlTextarea?.value || '').trim(); loadHtmlIntoPreview(html); });
  clearHtmlBtn?.addEventListener('click', () => { if(htmlTextarea) htmlTextarea.value = ''; if(selectedPreview) selectedPreview.textContent=''; if(selectedSnapshot) selectedSnapshot.textContent=''; loadHtmlIntoPreview(''); });
  downloadExtractBtn?.addEventListener('click', async () => {
    if(!currentSessionId){ alert('No active session'); return; }
    try{
      const qs = new URLSearchParams({ session_id: currentSessionId });
      const res = await fetch(`/api/autoheal/export?${qs.toString()}`);
      const j = await res.json(); if(!j.success){ throw new Error(j.error || 'Export failed'); }
      const blob = new Blob([JSON.stringify(j, null, 2)], {type:'application/json'});
      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'autoheal-elements.json'; a.click(); URL.revokeObjectURL(url);
    }catch(e){ alert('Export failed: ' + e.message); }
  });
  clearSelectedBtn?.addEventListener('click', async () => {
    if(!currentSessionId) { alert('No active session'); return; }
    try{
      // Deselect all currently cached elements
      for(const e of (cachedElements || [])){
        const res = await fetch('/api/autoheal/deselect', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ session_id: currentSessionId, snapshot: e.snapshot || {} }) });
        await res.json();
      }
      await loadElements();
      // Clear overlays
      selectedSet.clear();
      for(const key of Array.from(selectedOverlays.keys())) removeSelectedOverlay(key);
      hideHoverOverlay();
    } catch(err) { alert('Clear failed: ' + err.message); }
  });
  newSessionBtn?.addEventListener('click', newSession);

  // Auto-create a session on load for convenience
  newSession();
})();

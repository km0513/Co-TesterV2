# ==============================
# Simple Auto-Healing Recorder
from threading import Lock, Thread
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

import logging
import os
import time
import re
from collections import defaultdict
from datetime import datetime
import base64
import json
from flask import Flask, Blueprint, render_template, request, jsonify, session, redirect, url_for, send_file, current_app
from sqlalchemy import or_
from werkzeug.utils import safe_join

import subprocess
import sys
import glob
import shutil

from utils.playwright_replay import (
    ensure_replay_directories,
    generate_script_text,
    run_replay,
    save_script,
    summarize_actions,
)

autoheal_bp = Blueprint('autoheal', __name__)

_ah_lock = Lock()
_ah_playwright = None
_ah_sessions = {}

def _ah_get_pw():
    if sync_playwright is None:
        return None
    # Start a new Playwright instance in the current request thread
    return sync_playwright().start()

def _ah_build_locators(snapshot: dict):
    """Return ordered list of locator expressions (strings of JS using page.* that produce a Locator)."""
    locs = []
    if not snapshot:
        return locs
    s = snapshot
    q = lambda v: (v or '').replace("\\", "\\\\").replace("'", "\\'")
    tag = (s.get('tag') or '').lower()
    # Ignore top-level non-actionable targets
    if tag in ('html', 'body'):
        return locs

    # Heuristic name to use in role-based locators
    text_val = s.get('text') or ''
    name_guess = s.get('ariaLabel') or s.get('title') or (text_val if 0 < len(text_val) <= 80 else None)

    # Native semantics: links and buttons
    if tag == 'a':
        if name_guess:
            locs.append(f"page.getByRole('link', {{ name: '{q(name_guess)}' }})")
        href = s.get('href')
        if href and len(href) <= 200:
            locs.append(f"page.locator('a[href=\"{q(href)}\"]')")
    if tag == 'button' or (tag == 'input' and (s.get('type') in ['button', 'submit'])):
        if name_guess:
            locs.append(f"page.getByRole('button', {{ name: '{q(name_guess)}' }})")
    if tag == 'input' and (s.get('type') in ['checkbox', 'radio']) and name_guess:
        role = 'checkbox' if s.get('type') == 'checkbox' else 'radio'
        locs.append(f"page.getByRole('{role}', {{ name: '{q(name_guess)}' }})")

    # 1. data-testid / data-test / data-cy
    for key in ['data-testid', 'data-test', 'data-cy']:
        v = s.get(key) or s.get('dataset', {}).get(key)
        if v:
            if key == 'data-testid':
                locs.append(f"page.getByTestId('{q(v)}')")
            else:
                locs.append(f"page.locator('[{key}=\'{q(v)}\']')")
    # 2. id
    if s.get('id'):
        locs.append(f"page.locator('#{q(s['id'])}')")
    # 3. role + name (text)
    if s.get('role') and s.get('text'):
        locs.append(f"page.getByRole('{q(s['role'])}', {{ name: '{q(s['text'])}' }})")
    # 4. placeholder
    if s.get('placeholder'):
        locs.append(f"page.getByPlaceholder('{q(s['placeholder'])}')")
    # 5. aria-label
    if s.get('ariaLabel'):
        locs.append(f"page.locator('[aria-label=\'{q(s['ariaLabel'])}\']')")
    # 6. title
    if s.get('title'):
        locs.append(f"page.locator('[title=\'{q(s['title'])}\']')")
    # 7. name attribute
    if s.get('nameAttr'):
        locs.append(f"page.locator('[name=\'{q(s['nameAttr'])}\']')")
    # 8. reasonable text
    if s.get('text'):
        text = s['text']
        if 0 < len(text) <= 80:
            locs.append(f"page.getByText('{q(text)}')")
    # 9. classes combo
    classes = s.get('classes') or []
    if classes:
        cls = '.' + '.'.join([q(c) for c in classes[:3]])
        locs.append(f"page.locator('{cls}')")
    # 10. cssPath
    cssp = (s.get('cssPath') or '').strip()
    low = cssp.lower()
    if low and low not in ('html', 'body', 'html>body') and 'html>body' not in low:
        locs.append(f"page.locator('{q(cssp)}')")
    # 11. xpath
    if s.get('xpath'):
        xp = (s.get('xpath') or '').strip()
        if not re.match(r"^//(html(\[1\])?/)?body(\[1\])?$", xp, re.IGNORECASE):
            # Only include XPath if we don't already have enough strong strategies
            if len(locs) < 3:
                locs.append(f"page.locator('xpath={q(xp)}')")

    # dedupe, preserve order
    seen = set()
    ordered = []
    for L in locs:
        if L not in seen:
            seen.add(L)
            ordered.append(L)
    return ordered

def _ah_element_key(snapshot: dict) -> str:
    try:
        s = snapshot or {}
        parts = [
            (s.get('tag') or '').lower(),
            s.get('data-testid') or '',
            s.get('id') or '',
            s.get('nameAttr') or '',
            s.get('placeholder') or '',
            s.get('ariaLabel') or '',
            s.get('role') or '',
            (s.get('cssPath') or '')[:120],
        ]
        return '|'.join(parts)
    except Exception:
        return ''


def _aggregate_time_entries(entries):
    """Aggregate multiple worklogs for the same issue into one entry per issue.
    Assumes entries are already filtered to a single date when date_filter is provided.
    """
    groups = {}
    for e in entries:
        issue_key = e.get('issueKey', 'Unknown')
        g = groups.get(issue_key)
        if not g:
            g = {
                'id': issue_key,
                'issueKey': issue_key,
                'issueSummary': e.get('issueSummary', ''),
                'timeSpentSeconds': 0,
                'timeSpent': '0m',
                'comment': '',
                'started': e.get('started', ''),  # will keep the latest for sorting
                'author': e.get('author', 'User'),
                # Preserve additional issue details
                'issueType': e.get('issueType', 'Unknown'),
                'issueTypeIcon': e.get('issueTypeIcon', ''),
                'priority': e.get('priority', 'None'),
                'priorityIcon': e.get('priorityIcon', ''),
                'status': e.get('status', 'Unknown'),
                'statusCategory': e.get('statusCategory', 'Unknown'),
                'assignee': e.get('assignee', 'Unassigned'),
                'project': e.get('project', 'Unknown'),
                'projectKey': e.get('projectKey', 'Unknown'),
                'sprint': e.get('sprint', ''),
                'epic': e.get('epic', ''),
                '_comments': []
            }
            groups[issue_key] = g

        g['timeSpentSeconds'] = g.get('timeSpentSeconds', 0) + int(e.get('timeSpentSeconds', 0) or 0)
        # Keep latest started for ordering
        if (e.get('started') or '') > (g.get('started') or ''):
            g['started'] = e.get('started')

        c = e.get('comment') or ''
        if c and c not in g['_comments']:
            g['_comments'].append(c)

    aggregated = []
    for key, g in groups.items():
        secs = g.get('timeSpentSeconds', 0)
        hours = secs // 3600
        minutes = (secs % 3600) // 60
        g['timeSpent'] = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        if g['_comments']:
            g['comment'] = '\n'.join(g['_comments'])
        g.pop('_comments', None)
        aggregated.append(g)

    return aggregated

def _ah_element_name(snapshot: dict) -> str:
    """Generate a readable stable name for POM identifiers."""
    s = snapshot or {}
    cand = (
        s.get('data-testid') or s.get('id') or s.get('nameAttr') or s.get('ariaLabel') or s.get('placeholder') or s.get('title')
        or (s.get('text')[:40] if s.get('text') else '') or s.get('role') or s.get('tag') or 'element'
    )
    name = re.sub(r"[^a-zA-Z0-9]+", "_", cand).strip('_') or 'element'
    if name[0:1].isdigit():
        name = 'el_' + name
    return name

def _ah_loc_chain_for_pom(snapshot: dict, this_prefix: str = 'this.page') -> str:
    """Return the primary locator expression replacing 'page.' with this_prefix."""
    locs = _ah_build_locators(snapshot)
    if not locs:
        return f"{this_prefix}.locator('[data-qa-missing]')"
    L = locs[0]
    return L.replace('page.', f'{this_prefix}.', 1) if L.startswith('page.') else f"{this_prefix}.{L}"

def _ah_loc_list_for_pom(snapshot: dict, this_prefix: str = 'this.page') -> list:
    locs = _ah_build_locators(snapshot)
    out = []
    for L in locs:
        out.append(L.replace('page.', f'{this_prefix}.', 1) if L.startswith('page.') else f"{this_prefix}.{L}")
    return out

def _ah_action_to_code(action: dict, idx: int):
    # Build chained locator and action line
    locs = _ah_build_locators(action.get('element') or {})
    # fallback placeholder
    if not locs:
        loc_chain = "page.locator('[data-qa-missing]')"
    else:
        loc_chain = locs[0]
        for alt in locs[1:]:
            loc_chain = f"{loc_chain}.or({alt})"
    t = action.get('type')
    val = action.get('value')
    if t == 'click':
        return f"  // step {idx}: click\n  await ({loc_chain}).click();"
    if t == 'fill':
        v = (val or '').replace("\\", "\\\\").replace("`", "\\`")
        return f"  // step {idx}: fill\n  await ({loc_chain}).fill(`{v}`);"
    if t == 'check':
        return f"  // step {idx}: check\n  await ({loc_chain}).check();"
    if t == 'uncheck':
        return f"  // step {idx}: uncheck\n  await ({loc_chain}).uncheck();"
    if t == 'select':
        v = (val or '').replace("'", "\\'")
        return f"  // step {idx}: select\n  await ({loc_chain}).selectOption({{ value: '{v}' }});"
    if t == 'enter':
        return f"  // step {idx}: press Enter\n  await ({loc_chain}).press('Enter');"
    return f"  // step {idx}: {t or 'action'}\n  // TODO: implement\n  await ({loc_chain}).click();"

@autoheal_bp.route('/autoheal')
def autoheal_page():
    return render_template('autoheal-recorder.html', active_tab='auto-heal')

@autoheal_bp.route('/api/autoheal/start', methods=['POST'])
def autoheal_start():
    try:
        data = request.get_json() or {}
        url = data.get('url')
        if not url:
            return jsonify({'success': False, 'error': 'url is required'}), 400
        # Normalize URL: add https:// if missing scheme
        url = url.strip()
        if not re.match(r'^https?://', url, re.IGNORECASE):
            url = f'https://{url}'
        with _ah_lock:
            pw = _ah_get_pw()
            if pw is None:
                return jsonify({'success': False, 'error': 'Playwright not available on server'}), 500
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(bypass_csp=True, ignore_https_errors=True)
            page = context.new_page()

            # Log browser console messages to server logs for diagnostics
            try:
                def _on_console(msg):
                    try:
                        logging.info(f"[autoheal][console] {msg.type}: {msg.text}")
                    except Exception:
                        pass
                    # Also persist a small console log tail per session
                    try:
                        logs = _ah_sessions.get(session_id, {}).setdefault('logs', [])
                        logs.append(f"{msg.type}: {msg.text}")
                        if len(logs) > 200:
                            del logs[: len(logs) - 200]
                    except Exception:
                        pass
                page.on("console", _on_console)
                # Also capture console logs from any newly opened pages (popups)
                try:
                    def _attach_console(p):
                        try:
                            p.on("console", _on_console)
                        except Exception:
                            pass
                    context.on("page", _attach_console)
                except Exception:
                    pass
                def _on_page_error(err):
                    try:
                        logging.exception(f"[autoheal][pageerror] {err}")
                    except Exception:
                        pass
                page.on("pageerror", _on_page_error)
            except Exception:
                pass

            # Create session id and register session early to avoid dropping early events
            session_id = f"ah_{int(time.time())}"
            _ah_sessions[session_id] = {
                'pw': pw,
                'browser': browser,
                'context': context,
                'page': page,
                'url': url,
                'actions': [],
                'diag': {'created': True},
                'logs': []
            }

            # Expose binding to record actions (robust to JSHandles / arg variations)
            def _record_action(source, payload=None, *args):
                try:
                    # If payload is passed as a JSHandle or via *args, normalize it
                    if payload is None and args:
                        payload = args[0]
                    if hasattr(payload, 'json_value'):
                        try:
                            payload = payload.json_value()
                        except Exception:
                            pass
                    if not isinstance(payload, dict):
                        return
                    sid = payload.get('session_id')
                    if not sid or sid not in _ah_sessions:
                        return
                    try:
                        logging.info(f"[autoheal] action: sid={sid} type={payload.get('type')} value={payload.get('value')}")
                    except Exception:
                        pass
                    try:
                        if payload.get('type') == 'ping':
                            _ah_sessions[sid].setdefault('diag', {})['ping'] = 'received'
                    except Exception:
                        pass
                    _ah_sessions[sid]['actions'].append({
                        'type': payload.get('type'),
                        'value': payload.get('value'),
                        'element': payload.get('element')
                    })
                except Exception as err:
                    try:
                        logging.exception(f"[autoheal] record_action error: {err}")
                    except Exception:
                        pass
            # Use context-level binding so it's available in all frames and future pages
            try:
                context.expose_binding('__ah_recordAction', _record_action)
                try:
                    logging.info("[autoheal] exposed context binding __ah_recordAction")
                except Exception:
                    pass
            except Exception:
                # Fallback to page-level if context method not available
                page.expose_binding('__ah_recordAction', _record_action)
                try:
                    logging.info("[autoheal] exposed page binding __ah_recordAction (fallback)")
                except Exception:
                    pass
            # Also expose a plain function as another call path
            try:
                def _record_func(payload=None, *args):
                    return _record_action(None, payload, *args)
                context.expose_function('ahRecord', _record_func)
                try:
                    logging.info("[autoheal] exposed context function ahRecord")
                except Exception:
                    pass
            except Exception:
                try:
                    page.expose_function('ahRecord', _record_func)
                    try:
                        logging.info("[autoheal] exposed page function ahRecord (fallback)")
                    except Exception:
                        pass
                except Exception:
                    pass

            # Recorder injection (use template string to avoid f-string brace issues)
            recorder_template = """
                (() => {{
                  if (window.__ah_installed) return; window.__ah_installed = true;
                  const sid = '__SID__';
                  try {{ console.log('[autoheal] recorder injected', sid); }} catch(e) {{}}
                  try {{
                    console.log('[autoheal] binding types', typeof window.__ah_recordAction, typeof window.ahRecord);
                  }} catch(e) {{}}
                  const qText = (el) => {{
                    const t = (el.innerText || el.textContent || '').trim().replace(/\s+/g,' ');
                    return t.length > 120 ? t.slice(0,117)+'...' : t;
                  }};
                  // Monkey-patch common interaction APIs to capture programmatic interactions
                  try {{
                    const _origClick = Element.prototype.click;
                    Element.prototype.click = function() {{
                      try {{ console.log('[autoheal] Element.click patched'); }} catch(e) {{}}
                      try {{ send('click', this); }} catch(e) {{}}
                      return _origClick.apply(this, arguments);
                    }};
                  }} catch(e) {{}}
                  try {{
                    const iv = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
                    if (iv && iv.set) {{
                      Object.defineProperty(HTMLInputElement.prototype, 'value', {{
                        get: function() {{ return iv.get.call(this); }},
                        set: function(v) {{ iv.set.call(this, v); try {{ send(this.type === 'checkbox' ? (this.checked ? 'check' : 'uncheck') : 'fill', this, v); }} catch(e) {{}} }}
                      }});
                    }}
                  }} catch(e) {{}}
                  try {{
                    const tv = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
                    if (tv && tv.set) {{
                      Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {{
                        get: function() {{ return tv.get.call(this); }},
                        set: function(v) {{ tv.set.call(this, v); try {{ send('fill', this, v); }} catch(e) {{}} }}
                      }});
                    }}
                  }} catch(e) {{}}
                  try {{
                    const sv = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
                    if (sv && sv.set) {{
                      Object.defineProperty(HTMLSelectElement.prototype, 'value', {{
                        get: function() {{ return sv.get.call(this); }},
                        set: function(v) {{ sv.set.call(this, v); try {{ send('select', this, v); }} catch(e) {{}} }}
                      }});
                    }}
                  }} catch(e) {{}}
                  const cssPath = (el) => {{
                    if (!el) return '';
                    if (el.id) return `#${{el.id}}`;
                    const path = [];
                    let node = el;
                    while (node && node.nodeType === 1 && path.length < 6) {{
                      let sel = node.nodeName.toLowerCase();
                      if (node.classList && node.classList.length) {{
                        sel += '.' + Array.from(node.classList).slice(0,2).join('.');
                      }}
                      const sibs = node.parentNode ? Array.from(node.parentNode.children).filter(n => n.nodeName === node.nodeName) : [];
                      if (sibs.length > 1) {{
                        const idx = sibs.indexOf(node) + 1;
                        sel += `:nth-of-type(${{idx}})`;
                      }}
                      path.unshift(sel);
                      node = node.parentElement;
                    }}
                    return path.join('>');
                  }};
                  const xPath = (el) => {{
                    if (!el) return '';
                    const parts = [];
                    let node = el;
                    while (node && node.nodeType === 1 && parts.length < 6) {{
                      let ix = 1;
                      let sib = node.previousSibling;
                      while (sib) {{
                        if (sib.nodeType === 1 && sib.nodeName === node.nodeName) ix++;
                        sib = sib.previousSibling;
                      }}
                      parts.unshift(node.nodeName.toLowerCase() + '[' + ix + ']');
                      node = node.parentNode;
                    }}
                    return '//' + parts.join('/');
                  }};
                  const snapshot = (el) => {{
                    if (!el) return null;
                    if (el.nodeType && el.nodeType !== 1) el = el.parentElement;
                    if (!el) return null;
                    const safeGetAttr = (node, name) => {{ try {{ return node.getAttribute(name); }} catch(_) {{ return null; }} }};
                    const role = safeGetAttr(el, 'role');
                    let classes = [];
                    try {{ classes = Array.from(el.classList || []); }} catch(_) {{ classes = []; }}
                    classes = classes.filter(c => !/active|selected|focus|hover|open|close|hidden|show|hide/i.test(c)).slice(0,3);
                    let bbox = null;
                    try {{
                      const r = el.getBoundingClientRect();
                      const sx = (window.scrollX || window.pageXOffset || 0);
                      const sy = (window.scrollY || window.pageYOffset || 0);
                      bbox = {{ x: Math.max(0, Math.floor(r.x + sx)), y: Math.max(0, Math.floor(r.y + sy)), width: Math.max(0, Math.floor(r.width)), height: Math.max(0, Math.floor(r.height)) }};
                    }} catch(_e) {{ bbox = null; }}
                    return {{
                      tag: (el.nodeName || '').toLowerCase(),
                      id: el.id || null,
                      'data-testid': safeGetAttr(el, 'data-testid'),
                      'data-test': safeGetAttr(el, 'data-test'),
                      'data-cy': safeGetAttr(el, 'data-cy'),
                      role: role || null,
                      ariaLabel: safeGetAttr(el, 'aria-label') || null,
                      title: safeGetAttr(el, 'title') || null,
                      nameAttr: safeGetAttr(el, 'name') || null,
                      placeholder: safeGetAttr(el, 'placeholder') || null,
                      type: safeGetAttr(el, 'type') || null,
                      text: qText(el),
                      classes: classes,
                      cssPath: cssPath(el),
                      xpath: xPath(el),
                      bbox: bbox
                    }};
                  }};
                  const getEl = (e) => {{
                    try {{
                      const path = (e.composedPath && e.composedPath()) || [];
                      const isBad = (el) => !el || !el.tagName || el.tagName === 'HTML' || el.tagName === 'BODY';
                      const selectors = 'a[href],button,input,select,textarea,[role="button"],[role="link"],[role="menuitem"],[role="tab"],[role="checkbox"],[role="radio"],*[onclick],[tabindex]';
                      for (const n of path) {{
                        if (n && n.closest) {{
                          const c = n.closest(selectors);
                          if (c && !isBad(c)) return c;
                        }}
                        if (n && !isBad(n)) return n;
                      }}
                      const t = e.target;
                      if (t && t.closest) {{
                        const c2 = t.closest(selectors);
                        if (c2 && !isBad(c2)) return c2;
                      }}
                      return (!t || isBad(t)) ? null : t;
                    }} catch(_) {{ return null; }}
                  }};
                  const send = (type, el, value) => {{
                    const payload = {{ session_id: sid, type, value, element: snapshot(el) }};
                    try {{
                      if (typeof window.__ah_recordAction === 'function') {{
                        window.__ah_recordAction(payload);
                      }} else if (typeof window.ahRecord === 'function') {{
                        window.ahRecord(payload);
                      }}
                    }} catch (e) {{ try {{ console.warn('__ah_recordAction failed', e); }} catch(_) {{}} }}
                    // Always send HTTP as well to survive fast navigations
                    try {{
                      const url = '__SERVER__/api/autoheal/record';
                      const body = JSON.stringify(payload);
                      if (navigator.sendBeacon) {{
                        const blob = new Blob([body], {{ type: 'application/json' }});
                        navigator.sendBeacon(url, blob);
                      }} else {{
                        fetch(url, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body, mode: 'cors' }}).catch(() => {{}});
                      }}
                    }} catch(_) {{}}
                    try {{ console.log('[autoheal] sent', type, value); }} catch(e) {{}}
                  }};
                  // Only record direct user interactions; add dedupe to avoid duplicates
                  try {{
                    const _ah_seen = new Map();
                    const _fingerprint = (el) => {{
                      try {{
                        const s = snapshot(el) || {{}};
                        return (s.tag||'') + '#' + (s.id||'') + '|' + (s['data-testid']||s.nameAttr||s.ariaLabel||s.title||s.text||'');
                      }} catch(_) {{ return 'unknown'; }}
                    }};
                    const record = (type, el, value, ev) => {{
                      try {{ if (ev && ev.isTrusted === false) return; }} catch(_) {{}}
                      const key = type + '|' + _fingerprint(el);
                      const now = Date.now();
                      const last = _ah_seen.get(key) || 0;
                      if (now - last < 400) return;
                      _ah_seen.set(key, now);
                      send(type, el, value);
                    }};
                    window.__ah_recordDirect = record;
                  }} catch(e) {{}}
                  try {{
                    document.addEventListener('click', (e) => {{
                      try {{
                        const el = getEl(e);
                        try {{ console.log('[autoheal] click captured', el && el.tagName); }} catch(e) {{}}
                        if (e && e.isTrusted === true) window.__ah_recordDirect('click', el, undefined, e);
                      }} catch(err) {{
                        try {{ console.error('[autoheal] doc click handler error', err); }} catch(_) {{}}
                      }}
                    }}, true);
                    // Debounced typing capture: only record after user stops typing for 600ms, or on blur/Enter
                    const _fillTimers = new WeakMap();
                    const _scheduleFill = (el, ev) => {{
                      if (!el) return;
                      try {{
                        const tPrev = _fillTimers.get(el);
                        if (tPrev) clearTimeout(tPrev);
                      }} catch(_) {{}}
                      try {{
                        const t = setTimeout(() => {{
                          try {{ window.__ah_recordDirect('fill', el, el.value || '', ev); }} catch(_) {{}}
                        }}, 600);
                        _fillTimers.set(el, t);
                      }} catch(_) {{}}
                    }};
                    document.addEventListener('change', (e) => {{
                      const el = e.target;
                      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {{
                        let t = 'fill';
                        if (el.type === 'checkbox') t = el.checked ? 'check' : 'uncheck';
                        if (el.tagName === 'SELECT') t = 'select';
                        try {{ console.log('[autoheal] change captured', t); }} catch(e) {{}}
                        if (e && e.isTrusted === true) {{
                          if (t === 'fill') {{ _scheduleFill(el, e); }} else {{ window.__ah_recordDirect(t, el, el.value || '', e); }}
                        }}
                      }}
                    }}, true);
                    // Capture typing with debounce to avoid per-keystroke spam
                    document.addEventListener('input', (e) => {{
                      const el = e.target;
                      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {{
                        try {{ console.log('[autoheal] input captured (debounced)'); }} catch(e) {{}}
                        if (e && e.isTrusted === true) _scheduleFill(el, e);
                      }}
                    }}, true);
                    // Flush on blur
                    document.addEventListener('blur', (e) => {{
                      const el = e.target;
                      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {{
                        try {{ console.log('[autoheal] blur captured'); }} catch(e) {{}}
                        try {{ window.__ah_recordDirect('fill', el, el.value || '', e); }} catch(_) {{}}
                      }}
                    }}, true);
                    document.addEventListener('keydown', (e) => {{
                      if (e.key === 'Enter') {{
                        const el = e.target;
                        try {{ console.log('[autoheal] enter captured'); }} catch(e) {{}}
                        if (e && e.isTrusted === true) window.__ah_recordDirect('enter', el, undefined, e);
                      }}
                    }}, true);
                    try {{ console.log('[autoheal] listeners attached', location.href); }} catch(e) {{}}
                    // Removed body-level click fallback to avoid duplicates; main click handler is sufficient
                    try {{ console.log('[autoheal] binding types', typeof window.__ah_recordAction, typeof window.ahRecord); }} catch(e) {{}}
                    // Heartbeat to verify end-to-end binding
                    try {{ send('ready', document.documentElement, 'v1'); }} catch(e) {{}}
                    try {{ setTimeout(() => {{ try {{ send('ready', document.documentElement, 'v1-late'); }} catch(_) {{}} }}, 1000); }} catch(e) {{}}
                  }} catch (err) {{
                    try {{ console.error('[autoheal] listener install error', err); }} catch(e) {{}}
                  }}
                })();
            """
            server_origin = request.host_url.rstrip('/')
            recorder_js = recorder_template.replace('__SID__', session_id).replace('__SERVER__', server_origin).replace('{{', '{').replace('}}', '}')
            # Minimal recorder (idempotent) to ensure capture even if main recorder is blocked
            mini_js = """
            (() => {
              if (window.__ah_installed_mini) return;
              window.__ah_installed_mini = true;
              const sid = '__SID__';
              const server = '__SERVER__';
              const safeText = (el) => { try { return (el.innerText || el.textContent || '').trim().slice(0,200); } catch(_) { return ''; } };
              const a = (el, n) => { try { return el.getAttribute(n) || null; } catch(_) { return null; } };
              const cssPath = (el) => {
                if (!el) return '';
                if (el.id) return '#' + el.id;
                const path = [];
                let node = el;
                while (node && node.nodeType === 1 && path.length < 6) {
                  let sel = node.nodeName.toLowerCase();
                  if (node.classList && node.classList.length) {
                    sel += '.' + Array.from(node.classList).slice(0,2).join('.');
                  }
                  const sibs = node.parentNode ? Array.from(node.parentNode.children).filter(n => n.nodeName === node.nodeName) : [];
                  if (sibs.length > 1) {
                    const idx = sibs.indexOf(node) + 1;
                    sel += ':nth-of-type(' + idx + ')';
                  }
                  path.unshift(sel);
                  node = node.parentElement;
                }
                return path.join('>');
              };
              const xPath = (el) => {
                if (!el) return '';
                const parts = [];
                let node = el;
                while (node && node.nodeType === 1 && parts.length < 6) {
                  let ix = 1;
                  let sib = node.previousSibling;
                  while (sib) {
                    if (sib.nodeType === 1 && sib.nodeName === node.nodeName) ix++;
                    sib = sib.previousSibling;
                  }
                  parts.unshift(node.nodeName.toLowerCase() + '[' + ix + ']');
                  node = node.parentNode;
                }
                return '//' + parts.join('/');
              };
              const snap = (el) => {
                if (!el || !el.nodeType || el.nodeType !== 1) return { tag: 'unknown' };
                let classes = [];
                try { classes = Array.from(el.classList || []); } catch(_) { classes = []; }
                classes = classes.filter(c => !/active|selected|focus|hover|open|close|hidden|show|hide/i.test(c)).slice(0,3);
                return {
                  tag: (el.nodeName||'').toLowerCase(),
                  id: el.id || null,
                  'data-testid': a(el,'data-testid'),
                  'data-test': a(el,'data-test'),
                  'data-cy': a(el,'data-cy'),
                  role: a(el,'role') || null,
                  href: a(el,'href') || null,
                  ariaLabel: a(el,'aria-label') || null,
                  title: a(el,'title') || null,
                  nameAttr: a(el,'name') || null,
                  placeholder: a(el,'placeholder') || null,
                  type: a(el,'type') || null,
                  text: safeText(el),
                  classes: classes,
                  cssPath: cssPath(el),
                  xpath: xPath(el)
                };
              };
              const send = (type, el, value) => {
                const payload = { session_id: sid, type, value, element: snap(el) };
                let sent = false;
                try { if (typeof window.__ah_recordAction==='function') { window.__ah_recordAction(payload); sent = true; } } catch(_) {}
                try { if (!sent && typeof window.ahRecord==='function') { window.ahRecord(payload); sent = true; } } catch(_) {}
                if (!sent && server) {
                  try {
                    fetch(server + '/api/autoheal/record', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      mode: 'cors',
                      body: JSON.stringify(payload)
                    }).catch(() => {});
                  } catch (_) {}
                }
              };
              const getEl = (e) => {
                const path = (e.composedPath && e.composedPath()) || [];
                const isBad = (el) => !el || !el.tagName || el.tagName === 'HTML' || el.tagName === 'BODY';
                const selectors = 'a[href],button,input,select,textarea,[role="button"],[role="link"],[role="menuitem"],[role="tab"],[role="checkbox"],[role="radio"],*[onclick],[tabindex]';
                for (const n of path) {
                  if (n && n.closest) {
                    const c = n.closest(selectors);
                    if (c && !isBad(c)) return c;
                  }
                  if (n && !isBad(n)) return n;
                }
                const t = e.target;
                if (t && t.closest) {
                  const c2 = t.closest(selectors);
                  if (c2 && !isBad(c2)) return c2;
                }
                return isBad(t) ? null : t;
              };
              document.addEventListener('click', (e) => {
                const el = getEl(e);
                if (!el) return;
                try { console.log('[autoheal-mini] click'); } catch(_) {}
                send('click', el);
              }, true);
              // Debounce input in mini recorder
              { let _miniTimer = null; let _miniEl = null; }
              document.addEventListener('input', (e) => { const el = e.target; if (el && (el.tagName==='INPUT'||el.tagName==='TEXTAREA')) { try { console.log('[autoheal-mini] input (debounced)'); } catch(_) {} _miniEl = el; if (_miniTimer) clearTimeout(_miniTimer); _miniTimer = setTimeout(() => { try { send('fill', _miniEl, _miniEl && (_miniEl.value||'')); } catch(_) {} }, 600); } }, true);
              document.addEventListener('change', (e) => { const el = e.target; if (el && (el.tagName==='INPUT' || el.tagName==='SELECT')) { let t='fill'; if (el.type === 'checkbox') t = el.checked ? 'check':'uncheck'; if (el.tagName==='SELECT') t='select'; try { console.log('[autoheal-mini] change'); } catch(_) {} send(t, el, el.value||''); } }, true);
              document.addEventListener('keydown', (e) => { if (e.key==='Enter') { const el = document.activeElement || e.target; if (!el || el.tagName==='HTML' || el.tagName==='BODY') return; try { console.log('[autoheal-mini] enter'); } catch(_) {} send('enter', el); } }, true);
            })();
            """.replace('__SID__', session_id).replace('__SERVER__', server_origin)
            # Inject into all pages/frames in this context
            try:
                context.add_init_script(recorder_js)
                try:
                    context.add_init_script(mini_js)
                except Exception as e:
                    try:
                        logging.exception(f"[autoheal] context.add_init_script mini error: {e}")
                    except Exception:
                        pass
            except Exception as e:
                try:
                    logging.exception(f"[autoheal] context.add_init_script error: {e}")
                except Exception:
                    pass
                try:
                    page.add_init_script(recorder_js)
                    try:
                        page.add_init_script(mini_js)
                    except Exception as e3:
                        try:
                            logging.exception(f"[autoheal] page.add_init_script mini error: {e3}")
                        except Exception:
                            pass
                except Exception as e2:
                    try:
                        logging.exception(f"[autoheal] page.add_init_script error: {e2}")
                    except Exception:
                        pass
            # Pre-wire reinjection on any navigation of the initial page to survive redirects
            try:
                def _pre_reinject():
                    try:
                        page.evaluate(recorder_js)
                    except Exception:
                        pass
                    try:
                        page.evaluate(mini_js)
                    except Exception:
                        pass
                    try:
                        page.add_script_tag(content=recorder_js)
                    except Exception:
                        pass
                page.on('domcontentloaded', lambda *args: _pre_reinject())
                page.on('load', lambda *args: _pre_reinject())
                page.on('framenavigated', lambda *args: _pre_reinject())
            except Exception:
                pass
            page.goto(url, wait_until='domcontentloaded')
            # Force attach in the current document as an extra safety net
            try:
                page.evaluate(recorder_js)
                try:
                    page.evaluate(mini_js)
                except Exception as e:
                    try:
                        logging.exception(f"[autoheal] page.evaluate(mini_js) error: {e}")
                    except Exception:
                        pass
            except Exception as e:
                try:
                    logging.exception(f"[autoheal] page.evaluate(recorder_js) error: {e}")
                except Exception:
                    pass
            # Fallback: attempt to add a script tag (may be blocked by CSP on some sites)
            try:
                page.add_script_tag(content=recorder_js)
            except Exception as e:
                try:
                    logging.exception(f"[autoheal] page.add_script_tag error: {e}")
                except Exception:
                    pass
            # Diagnostic: verify injection and bindings from page context
            try:
                diag = page.evaluate("(() => { return { installed: !!window.__ah_installed, bind: typeof window.__ah_recordAction, func: typeof window.ahRecord }; })()")
                try:
                    logging.info(f"[autoheal] diag after inject: installed={diag.get('installed')} bind={diag.get('bind')} func={diag.get('func')}")
                except Exception:
                    pass
                try:
                    _ah_sessions.get(session_id, {}).setdefault('diag', {}).update({
                        'installed': bool(diag.get('installed')),
                        'bind': diag.get('bind'),
                        'func': diag.get('func')
                    })
                except Exception:
                    pass
                # Inject a minimal fallback recorder (idempotent)
                try:
                    _mini = """
                        (() => {
                          if (window.__ah_installed_mini) return;
                          window.__ah_installed_mini = true;
                          const sid = '__SID__';
                          const server = '__SERVER__';
                          const safeText = (el) => { try { return (el.innerText || el.textContent || '').trim().slice(0,200); } catch(_) { return ''; } };
                          const a = (el, n) => { try { return el.getAttribute(n) || null; } catch(_) { return null; } };
                          const snap = (el) => {
                            if (!el || !el.nodeType || el.nodeType !== 1) return { tag: 'unknown' };
                            return {
                              tag: (el.nodeName||'').toLowerCase(),
                              id: el.id || null,
                              'data-testid': a(el,'data-testid'),
                              'data-test': a(el,'data-test'),
                              'data-cy': a(el,'data-cy'),
                              ariaLabel: a(el,'aria-label') || null,
                              title: a(el,'title') || null,
                              nameAttr: a(el,'name') || null,
                              placeholder: a(el,'placeholder') || null,
                              type: a(el,'type') || null,
                              text: safeText(el)
                            };
                          };
                          const send = (type, el, value) => {
                            const payload = { session_id: sid, type, value, element: snap(el) };
                            try { if (typeof window.__ah_recordAction==='function') window.__ah_recordAction(payload); else if (typeof window.ahRecord==='function') window.ahRecord(payload); } catch(_) {}
                            try {
                              const url = server + '/api/autoheal/record';
                              const body = JSON.stringify(payload);
                              if (navigator.sendBeacon) { const blob = new Blob([body], { type: 'application/json' }); navigator.sendBeacon(url, blob); }
                              else { fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, mode: 'cors' }).catch(() => {}); }
                            } catch(_) {}
                          };
                          const getEl = (e) => { const tgt = (e.composedPath && e.composedPath()[0]) || e.target; return (tgt && tgt.closest ? tgt.closest('a,button,input,select,textarea,[role="button"],*[onclick]') : null) || tgt; };
                          // Only direct user interactions with dedupe
                          try {
                            const _seen = new Map();
                            const fp = (el) => { try { const s = snap(el)||{}; return (s.tag||'') + '#' + (s.id||'') + '|' + (s['data-testid']||s.nameAttr||s.ariaLabel||s.title||s.text||''); } catch(_) { return 'u'; } };
                            const record = (type, el, value, ev) => { try { if (ev && ev.isTrusted === false) return; } catch(_) {} const k = type+'|'+fp(el); const n = Date.now(); const l = _seen.get(k)||0; if (n-l<400) return; _seen.set(k,n); send(type, el, value); };
                            document.addEventListener('click', (e) => { try { console.log('[autoheal-mini] click'); } catch(_) {} try { const el = getEl(e); if (e && e.isTrusted===true) record('click', el, undefined, e); } catch(_) {} }, true);
                            document.addEventListener('input', (e) => { const el = e.target; if (el && (el.tagName==='INPUT'||el.tagName==='TEXTAREA')) { try { console.log('[autoheal-mini] input'); } catch(_) {} if (e && e.isTrusted===true) record('fill', el, el.value||'', e); } }, true);
                            document.addEventListener('change', (e) => { const el = e.target; if (el && (el.tagName==='INPUT' || el.tagName==='SELECT')) { let t='fill'; if (el.type === 'checkbox') t = el.checked ? 'check':'uncheck'; if (el.tagName==='SELECT') t='select'; try { console.log('[autoheal-mini] change'); } catch(_) {} if (e && e.isTrusted===true) record(t, el, el.value||'', e); } }, true);
                            document.addEventListener('keydown', (e) => { if (e.key==='Enter') { try { console.log('[autoheal-mini] enter'); } catch(_) {} if (e && e.isTrusted===true) record('enter', e.target, undefined, e); } }, true);
                          } catch(_) {}
                        })();
                    """.replace('__SID__', session_id).replace('__SERVER__', server_origin)
                    page.evaluate(_mini)
                    try:
                        _ah_sessions.get(session_id, {}).setdefault('diag', {})['mini'] = True
                        logging.info("[autoheal] installed minimal recorder fallback")
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception:
                pass
            # Try a diagnostic ping via binding to verify end-to-end pipeline
            try:
                _ping_js = "(function(){ try { if (typeof window.__ah_recordAction==='function') window.__ah_recordAction({ session_id: '__SID__', type: 'ping', value: 'start', element: { tag: 'HTML' } }); else if (typeof window.ahRecord==='function') window.ahRecord({ session_id: '__SID__', type: 'ping', value: 'start', element: { tag: 'HTML' } }); } catch(_) {} })()"
                _ping_js = _ping_js.replace('__SID__', session_id)
                page.evaluate(_ping_js)
                try:
                    logging.info("[autoheal] ping attempted from page context")
                except Exception:
                    pass
            except Exception:
                pass
            # Ensure all existing frames also have the recorder
            try:
                frames_info = []
                for fr in page.frames:
                    try:
                        fr.evaluate(recorder_js)
                    except Exception:
                        pass
                    try:
                        fr.evaluate(mini_js)
                    except Exception:
                        pass
                    try:
                        frames_info.append(getattr(fr, 'url', lambda: '')() if callable(getattr(fr, 'url', None)) else fr.url)
                    except Exception:
                        pass
                try:
                    _ah_sessions.get(session_id, {}).setdefault('diag', {})['frames'] = frames_info
                except Exception:
                    pass
            except Exception:
                pass
            # Ensure any newly opened pages also get the recorder immediately
            try:
                def _inject_on_new_page(p):
                    try:
                        p.add_init_script(recorder_js)
                        try:
                            p.add_init_script(mini_js)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    try:
                        p.evaluate(recorder_js)
                    except Exception:
                        pass
                    try:
                        p.add_script_tag(content=recorder_js)
                    except Exception:
                        pass
                    try:
                        def _on_frame_attached(fr):
                            try:
                                fr.evaluate(recorder_js)
                            except Exception:
                                pass
                            try:
                                fr.evaluate(mini_js)
                            except Exception:
                                pass
                            try:
                                _ah_sessions.get(session_id, {}).setdefault('diag', {}).setdefault('frames_new', []).append(
                                    getattr(fr, 'url', lambda: '')() if callable(getattr(fr, 'url', None)) else fr.url
                                )
                            except Exception:
                                pass
                        p.on("frameattached", _on_frame_attached)
                        # Re-inject on navigations within the page (SPA/soft reloads)
                        def _reinject():
                            try:
                                p.evaluate(recorder_js)
                            except Exception:
                                pass
                            try:
                                p.evaluate(mini_js)
                            except Exception:
                                pass
                        try:
                            p.on('domcontentloaded', lambda *args: _reinject())
                            p.on('load', lambda *args: _reinject())
                        except Exception:
                            pass
                    except Exception:
                        pass
                context.on("page", _inject_on_new_page)
            except Exception:
                pass
            # Inject into frames of the initial page
            try:
                def _on_frame_attached(fr):
                    try:
                        fr.evaluate(recorder_js)
                    except Exception:
                        pass
                    try:
                        fr.evaluate(mini_js)
                    except Exception:
                        pass
                page.on("frameattached", _on_frame_attached)
                # Re-inject on navigations within the initial page as well
                def _reinject_root():
                    try:
                        page.evaluate(recorder_js)
                    except Exception:
                        pass
                    try:
                        page.evaluate(mini_js)
                    except Exception:
                        pass
                    try:
                        page.add_script_tag(content=recorder_js)
                    except Exception:
                        pass
                page.on("domcontentloaded", lambda *args: _reinject_root())
                page.on("load", lambda *args: _reinject_root())
            except Exception:
                pass

            session['ah_session_id'] = session_id
            return jsonify({'success': True, 'session_id': session_id, 'url': url})
    except Exception as e:
        logging.exception('autoheal_start error')
        try:
            if 'pw' in locals() and locals()['pw']:
                locals()['pw'].stop()
        except Exception:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500

@autoheal_bp.route('/api/autoheal/record', methods=['POST', 'OPTIONS'])
def autoheal_record():
    # HTTP fallback to record an action coming from the injected recorder
    if request.method == 'OPTIONS':
        # Let Flask-CORS handle headers; return 200 quickly
        return ('', 204)
    try:
        payload = request.get_json() or {}
        sid = payload.get('session_id')
        if not sid or sid not in _ah_sessions:
            return jsonify({'success': False, 'error': 'invalid session'}), 400
        try:
            logging.info(f"[autoheal] action(http): sid={sid} type={payload.get('type')} value={payload.get('value')}")
        except Exception:
            pass
        s = _ah_sessions[sid]
        el_snap = payload.get('element') or {}
        # store action with stable key
        ek = _ah_element_key(el_snap)
        act = {
            'type': payload.get('type'),
            'value': payload.get('value'),
            'element': el_snap,
            'element_key': ek
        }
        s['actions'].append(act)
        # maintain element registry with optional visual clip
        try:
            registry = s.setdefault('elements', {})
            if ek and ek not in registry:
                entry = {
                    'key': ek,
                    'name': _ah_element_name(el_snap),
                    'snapshot': el_snap,
                    'locators': _ah_build_locators(el_snap),
                }
                # Try capture visual clip once if bbox exists and page is available
                bbox = (el_snap or {}).get('bbox') or {}
                px = {k: float(bbox.get(k)) for k in ('x','y','width','height') if bbox.get(k) is not None}
                if len(px) == 4 and s.get('page'):
                    try:
                        clip = { 'x': px['x'], 'y': px['y'], 'width': px['width'], 'height': px['height'] }
                        img = s['page'].screenshot(clip=clip)
                        entry['visual'] = 'data:image/png;base64,' + base64.b64encode(img).decode('ascii')
                    except Exception:
                        pass
                registry[ek] = entry
        except Exception:
            pass
        return jsonify({'success': True})
    except Exception as e:
        logging.exception('autoheal_record error')
        return jsonify({'success': False, 'error': str(e)}), 500

@autoheal_bp.route('/api/autoheal/status', methods=['GET'])
def autoheal_status():
    sid = request.args.get('session_id') or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    s = _ah_sessions[sid]
    # Provide diagnostics and recent console logs to help debugging
    diag = s.get('diag', {})
    logs = s.get('logs', [])
    tail = logs[-50:] if len(logs) > 50 else logs
    return jsonify({
        'success': True,
        'session_id': sid,
        'url': s['url'],
        'actions': s['actions'],
        'diag': diag,
        'logs_tail': tail
    })

@autoheal_bp.route('/api/autoheal/clear', methods=['POST'])
def autoheal_clear():
    sid = (request.get_json() or {}).get('session_id') or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    with _ah_lock:
        s = _ah_sessions.get(sid)
        if s is None:
            return jsonify({'success': False, 'error': 'no active session'}), 404
        try:
            s['actions'] = []
        except Exception:
            s['actions'] = []
    return jsonify({'success': True, 'session_id': sid, 'count': 0})

@autoheal_bp.route('/api/autoheal/reset', methods=['POST'])
def autoheal_reset():
    sid = (request.get_json() or {}).get('session_id') or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    with _ah_lock:
        s = _ah_sessions.get(sid)
        # Attempt to close all resources
        try:
            if s and s.get('context'):
                s['context'].close()
        except Exception:
            pass
        try:
            if s and s.get('browser'):
                s['browser'].close()
        except Exception:
            pass
        try:
            if s and s.get('pw'):
                s['pw'].stop()
        except Exception:
            pass
        # Remove the session entirely
        try:
            _ah_sessions.pop(sid, None)
        finally:
            session.pop('ah_session_id', None)
    return jsonify({'success': True})

@autoheal_bp.route('/api/autoheal/stop', methods=['POST'])
def autoheal_stop():
    sid = (request.get_json() or {}).get('session_id') or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    with _ah_lock:
        s = _ah_sessions.get(sid)
        try:
            if s:
                # Close browser resources but retain actions and session for code generation
                try:
                    if s.get('context'):
                        s['context'].close()
                except Exception:
                    pass
                try:
                    if s.get('browser'):
                        s['browser'].close()
                except Exception:
                    pass
                try:
                    if s.get('pw'):
                        s['pw'].stop()
                except Exception:
                    pass
                s['context'] = None
                s['browser'] = None
                s['page'] = None
                s['pw'] = None
                s['stopped'] = True
        finally:
            # Keep session id so /status and /generate-test still work after stop
            session['ah_session_id'] = sid
    return jsonify({'success': True, 'session_id': sid, 'count': len(s.get('actions', []))})

@autoheal_bp.route('/api/autoheal/generate-test', methods=['POST'])
def autoheal_generate_test():
    try:
        data = request.get_json() or {}
        sid = data.get('session_id') or session.get('ah_session_id')
        if not sid or sid not in _ah_sessions:
            return jsonify({'success': False, 'error': 'no active session'}), 404
        s = _ah_sessions[sid]
        url = s['url']
        # Filter only real user actions, ignore diagnostics
        allowed = { 'click', 'fill', 'check', 'uncheck', 'select', 'enter' }
        actions_all = s['actions']
        def _is_actionable(a):
            try:
                el = (a or {}).get('element') or {}
                tag = (el.get('tag') or '').lower()
                return tag not in ('html', 'body')
            except Exception:
                return True
        actions = [a for a in actions_all if a and a.get('type') in allowed and _is_actionable(a)]
        # Coalesce multiple fills on the same field and collapse consecutive duplicate clicks
        def _fp(el: dict):
            try:
                if not el:
                    return ''
                keys = ['data-testid', 'id', 'nameAttr', 'placeholder', 'ariaLabel', 'role', 'cssPath']
                base = (el.get('tag') or '')
                parts = [base] + [f"{k}={el.get(k)}" for k in keys if el.get(k)]
                return '|'.join(parts)
            except Exception:
                return ''
        def _coalesce(seq):
            res = []
            last_fill_by = {}
            for a in seq:
                try:
                    t = a.get('type')
                    el = (a.get('element') or {})
                    f = _fp(el)
                    if t == 'fill':
                        if f in last_fill_by:
                            res[last_fill_by[f]] = a
                        else:
                            last_fill_by[f] = len(res)
                            res.append(a)
                    elif t == 'click':
                        if res and res[-1].get('type') == 'click' and _fp(res[-1].get('element') or {}) == f:
                            continue
                        res.append(a)
                    else:
                        res.append(a)
                except Exception:
                    res.append(a)
            return res
        actions = _coalesce(actions)
        body_lines = []
        for i, a in enumerate(actions, start=1):
            body_lines.append(_ah_action_to_code(a, i))
        # If no real actions, produce a minimal test with guidance
        if not body_lines:
            body_lines = ["  // No user interactions were captured. Try interacting with elements in the main page (not in cross-origin iframes)."]
        body = "\n".join(body_lines)
        code = f"""// Auto-generated by Simple Auto-Healing Recorder
import {{ test, expect }} from '@playwright/test';

test('Autoheal Recording', async ({{ page }}) => {{
  await page.goto('{url}');
{body}
}});
"""
        return jsonify({'success': True, 'code': code, 'count': len(actions)})
    except Exception as e:
        logging.exception('autoheal_generate_test error')
        return jsonify({'success': False, 'error': str(e)}), 500

@autoheal_bp.route('/api/autoheal/export', methods=['GET'])
def autoheal_export():
    sid = request.args.get('session_id') or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    s = _ah_sessions[sid]
    # Build registry from stored elements or actions
    registry = s.get('elements', {}).copy()
    if not registry:
        for a in s.get('actions', []):
            snap = (a or {}).get('element') or {}
            ek = _ah_element_key(snap)
            if not ek:
                continue
            if ek not in registry:
                registry[ek] = {
                    'key': ek,
                    'name': _ah_element_name(snap),
                    'snapshot': snap,
                    'locators': _ah_build_locators(snap),
                }
    # Ensure page/user_name fields are included if present in session elements
    out = []
    for ek, entry in registry.items():
        e = entry.copy()
        try:
            ses_entry = (s.get('elements') or {}).get(ek) or {}
            if 'page' in ses_entry:
                e['page'] = ses_entry.get('page')
            if 'user_name' in ses_entry:
                e['user_name'] = ses_entry.get('user_name')
        except Exception:
            pass
        out.append(e)
    return jsonify({'success': True, 'elements': out, 'count': len(out)})

@autoheal_bp.route('/api/autoheal/select', methods=['POST'])
def autoheal_select():
    try:
        data = request.get_json() or {}
        sid = data.get('session_id') or session.get('ah_session_id')
        if not sid or sid not in _ah_sessions:
            return jsonify({'success': False, 'error': 'no active session'}), 404
        snap = data.get('snapshot') or {}
        ek = _ah_element_key(snap)
        if not ek:
            return jsonify({'success': False, 'error': 'invalid snapshot'}), 400
        with _ah_lock:
            s = _ah_sessions.get(sid) or {}
            reg = s.setdefault('elements', {})
            prev = reg.get(ek) or {}
            entry = {
                'key': ek,
                'name': _ah_element_name(snap),
                'snapshot': snap,
                'locators': _ah_build_locators(snap),
            }
            # Preserve existing page and user_name assignments if any
            if 'page' in prev:
                entry['page'] = prev.get('page')
            if 'user_name' in prev:
                entry['user_name'] = prev.get('user_name')
            reg[ek] = entry
        return jsonify({'success': True, 'key': ek, 'count': len(reg)})
    except Exception as e:
        logging.exception('autoheal_select error')
        return jsonify({'success': False, 'error': str(e)}), 500

@autoheal_bp.route('/api/autoheal/deselect', methods=['POST'])
def autoheal_deselect():
    try:
        data = request.get_json() or {}
        sid = data.get('session_id') or session.get('ah_session_id')
        if not sid or sid not in _ah_sessions:
            return jsonify({'success': False, 'error': 'no active session'}), 404
        snap = data.get('snapshot') or {}
        ek = _ah_element_key(snap)
        if not ek:
            return jsonify({'success': False, 'error': 'invalid snapshot'}), 400
        with _ah_lock:
            s = _ah_sessions.get(sid) or {}
            reg = s.setdefault('elements', {})
            reg.pop(ek, None)
            cnt = len(reg)
        return jsonify({'success': True, 'key': ek, 'count': cnt})
    except Exception as e:
        logging.exception('autoheal_deselect error')
        return jsonify({'success': False, 'error': str(e)}), 500

def _ah_sanitize_ident(name: str) -> str:
    ident = re.sub(r"[^a-zA-Z0-9_]+", "_", name or '').strip('_') or 'element'
    if ident[0:1].isdigit():
        ident = 'el_' + ident
    return ident

def _ah_build_ident(entry: dict) -> str:
    # Combine page and user-provided name when available; fallback to auto name
    page = (entry or {}).get('page')
    user = (entry or {}).get('user_name') or (entry or {}).get('name') or 'element'
    if page:
        return _ah_sanitize_ident(f"{page}_{user}")
    return _ah_sanitize_ident(user)

def _ah_require_all_named(reg):
    missing = []
    for ek, e in (reg or {}).items():
        if not (e.get('page') and e.get('user_name')):
            missing.append(ek)
    return (len(missing) == 0, missing)

def _ah_generate_pom(sid: str, lang: str = 'ts') -> str:
    s = _ah_sessions[sid]
    url = s.get('url') or ''
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or 'recorded').split('.')
    base = ''.join([p.capitalize() for p in host if p]) or 'Recorded'
    class_name = f'{base}Page'
    # Collect elements
    reg = s.get('elements') or {}
    if not reg:
        for a in s.get('actions', []):
            snap = (a or {}).get('element') or {}
            ek = _ah_element_key(snap)
            if not ek:
                continue
            reg[ek] = {
                'key': ek,
                'name': _ah_element_name(snap),
                'snapshot': snap,
                'loc_chain': _ah_loc_chain_for_pom(snap, 'this.page'),
            }
    else:
        # enrich with loc_chain
        for ek, entry in reg.items():
            snap = entry.get('snapshot') or {}
            entry['loc_chain'] = _ah_loc_chain_for_pom(snap, 'this.page')

    # Enforce naming (page + user_name) for all elements prior to generation
    ok, missing = _ah_require_all_named(reg)
    if not ok:
        raise ValueError(f"All elements must be named before download. Missing assignments for {len(missing)} element(s).")

    lines = []
    if lang == 'ts':
        lines.append("import { Page, Locator } from '@playwright/test';")
        lines.append("")
        lines.append(f"export class {class_name} {{")
        lines.append("  constructor(public page: Page) {}")
    else:
        lines.append(f"export class {class_name} {{")
        lines.append("  constructor(page) { this.page = page; }")
    # element getters
    for ek, entry in reg.items():
        # identifier is Page_Element
        ident = _ah_build_ident(entry)
        # primary getter
        loc_chain = entry.get('loc_chain') or "this.page.locator('[data-qa-missing]')"
        if lang == 'ts':
            lines.append(f"  get {ident}(): Locator {{ return {loc_chain}; }}")
        else:
            lines.append(f"  get {ident}() {{ return {loc_chain}; }}")
        # async fallback resolver method
        locs = _ah_loc_list_for_pom(entry.get('snapshot') or {}, 'this.page')
        arr = ', '.join(locs) if locs else "this.page.locator('[data-qa-missing]')"
        bbox = (entry.get('snapshot') or {}).get('bbox') or None
        bbox_json = json.dumps(bbox) if bbox else 'null'
        if lang == 'ts':
            lines.append(f"  async {ident}$(timeoutMs: number = 2000): Promise<Locator> {{")
            lines.append(f"    const cands: Locator[] = [{arr}];")
            lines.append("    for (const loc of cands) { try { if ((await loc.count()) > 0) return loc; } catch(_) {} }")
            lines.append(f"    try {{ return await this.aiFindByVisual({{ key: '{ek}', bbox: {bbox_json} }}); }} catch(_) {{}}")
            lines.append("    return cands[0];")
            lines.append("  }")
        else:
            lines.append(f"  async {ident}$(timeoutMs = 2000) {{")
            lines.append(f"    const cands = [{arr}];")
            lines.append("    for (const loc of cands) { try { if ((await loc.count()) > 0) return loc; } catch(_) {} }")
            lines.append(f"    try {{ return await this.aiFindByVisual({{ key: '{ek}', bbox: {bbox_json} }}); }} catch(_) {{}}")
            lines.append("    return cands[0];")
            lines.append("  }")
    # AI visual stub
    if lang == 'ts':
        lines.append("  protected async aiFindByVisual(meta: { key: string; bbox?: { x:number;y:number;width:number;height:number } }): Promise<Locator> {")
    else:
        lines.append("  async aiFindByVisual(meta) {")
    lines.append("    throw new Error('AI visual locator not configured. Plug-in your provider here.');")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines)

@autoheal_bp.route('/api/autoheal/pom', methods=['GET'])
def autoheal_pom():
    sid = request.args.get('session_id') or session.get('ah_session_id')
    lang = (request.args.get('lang') or 'ts').lower()
    if lang not in ('ts','js'):
        lang = 'ts'
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    # Validate that all elements are named before allowing download
    s = _ah_sessions[sid]
    reg = s.get('elements') or {}
    ok, missing = _ah_require_all_named(reg)
    if not ok:
        return jsonify({'success': False, 'error': f'All elements must be named (page + name). Pending: {len(missing)}'}), 400
    content = _ah_generate_pom(sid, lang)
    fname = 'RecordedPage.' + ('ts' if lang=='ts' else 'js')
    from flask import Response
    resp = Response(content, mimetype='text/plain')
    resp.headers['Content-Disposition'] = f'attachment; filename={fname}'
    return resp

@autoheal_bp.route('/api/autoheal/pom/element', methods=['GET'])
def autoheal_pom_element():
    sid = request.args.get('session_id') or session.get('ah_session_id')
    key = request.args.get('key') or ''
    lang = (request.args.get('lang') or 'ts').lower()
    if lang not in ('ts','js'):
        lang = 'ts'
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    s = _ah_sessions[sid]
    reg = s.get('elements') or {}
    entry = reg.get(key)
    if not entry:
        return jsonify({'success': False, 'error': 'element not found'}), 404
    # Enforce naming for this element
    if not (entry.get('page') and entry.get('user_name')):
        return jsonify({'success': False, 'error': 'element must have page and name assigned'}), 400
    ident = _ah_build_ident(entry)
    loc_chain = _ah_loc_chain_for_pom(entry.get('snapshot') or {}, 'this.page')
    # build both getter and async fallback method
    locs = _ah_loc_list_for_pom(entry.get('snapshot') or {}, 'this.page')
    arr = ', '.join(locs) if locs else "this.page.locator('[data-qa-missing]')"
    bbox = (entry.get('snapshot') or {}).get('bbox') or None
    bbox_json = json.dumps(bbox) if bbox else 'null'
    if lang == 'ts':
        content = (
            f"get {ident}(): Locator {{ return {loc_chain}; }}\n"
            f"async {ident}$(timeoutMs: number = 2000): Promise<Locator> {{ const cands: Locator[] = [{arr}]; for (const loc of cands) {{ try {{ if ((await loc.count()) > 0) return loc; }} catch(_) {{}} }} try {{ return await this.aiFindByVisual({{ key: '{key}', bbox: {bbox_json} }}); }} catch(_) {{}} return cands[0]; }}\n"
        )
    else:
        content = (
            f"get {ident}() {{ return {loc_chain}; }}\n"
            f"async {ident}$(timeoutMs = 2000) {{ const cands = [{arr}]; for (const loc of cands) {{ try {{ if ((await loc.count()) > 0) return loc; }} catch(_) {{}} }} try {{ return await this.aiFindByVisual({{ key: '{key}', bbox: {bbox_json} }}); }} catch(_) {{}} return cands[0]; }}\n"
        )
    from flask import Response
    resp = Response(content, mimetype='text/plain')
    ext = 'ts' if lang == 'ts' else 'js'
    resp.headers['Content-Disposition'] = f'attachment; filename={ident}.{ext}'
    return resp

@autoheal_bp.route('/api/autoheal/pages', methods=['GET', 'POST'])
def autoheal_pages():
    sid = (request.args.get('session_id') if request.method == 'GET' else (request.get_json() or {}).get('session_id')) or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    if request.method == 'GET':
        pages = _ah_sessions[sid].get('pages') or []
        return jsonify({'success': True, 'pages': pages})
    data = request.get_json() or {}
    pages = data.get('pages') or []
    if not isinstance(pages, list):
        return jsonify({'success': False, 'error': 'pages must be a list'}), 400
    # sanitize, dedupe, keep order
    cleaned = []
    seen = set()
    for p in pages:
        if not isinstance(p, str):
            continue
        v = p.strip()
        if not v:
            continue
        if v.lower() in seen:
            continue
        seen.add(v.lower())
        cleaned.append(v)
    with _ah_lock:
        _ah_sessions[sid]['pages'] = cleaned
    return jsonify({'success': True, 'pages': cleaned})

@autoheal_bp.route('/api/autoheal/elements/names', methods=['POST'])
def autoheal_elements_names():
    data = request.get_json() or {}
    sid = data.get('session_id') or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    assigns = data.get('assignments') or {}
    if not isinstance(assigns, dict):
        return jsonify({'success': False, 'error': 'assignments must be an object'}), 400
    with _ah_lock:
        s = _ah_sessions[sid]
        reg = s.get('elements') or {}
        updated = 0
        for ek, payload in assigns.items():
            if ek not in reg:
                continue
            if not isinstance(payload, dict):
                continue
            page = (payload.get('page') or '').strip()
            name = (payload.get('name') or '').strip()
            if not page or not name:
                continue
            reg[ek]['page'] = page
            reg[ek]['user_name'] = name
            updated += 1
    return jsonify({'success': True, 'updated': updated})

@autoheal_bp.route('/api/autoheal/select', methods=['POST'])
def autoheal_select_from_snapshot():
    data = request.get_json() or {}
    sid = data.get('session_id') or session.get('ah_session_id')
    if not sid or sid not in _ah_sessions:
        return jsonify({'success': False, 'error': 'no active session'}), 404
    snap = data.get('snapshot') or {}
    if not isinstance(snap, dict) or not snap:
        return jsonify({'success': False, 'error': 'invalid snapshot'}), 400
    ek = _ah_element_key(snap)
    if not ek:
        return jsonify({'success': False, 'error': 'could not derive element key'}), 400
    entry = {
        'key': ek,
        'name': _ah_element_name(snap),
        'snapshot': snap,
        'locators': _ah_build_locators(snap),
        'loc_chain': _ah_loc_chain_for_pom(snap, 'this.page'),
    }
    with _ah_lock:
        s = _ah_sessions[sid]
        reg = s.get('elements') or {}
        reg[ek] = entry
        s['elements'] = reg
    return jsonify({'success': True, 'element': entry})

@autoheal_bp.route('/autoheal/html')
def autoheal_html_page():
    # Standalone HTML Extractor UI (separate from recorder)
    return render_template('autoheal-html.html')

@autoheal_bp.route('/api/autoheal/session', methods=['POST'])
def autoheal_create_session():
    # Create a fresh session for HTML mode (or any headless extraction) without launching Playwright
    import uuid
    sid = uuid.uuid4().hex
    with _ah_lock:
        _ah_sessions[sid] = {
            'created_at': time.time(),
            'url': None,
            'browser': None,
            'context': None,
            'page': None,
            'actions': [],
            'elements': {},
            'pages': [],
        }
    session['ah_session_id'] = sid
    return jsonify({'success': True, 'session_id': sid})

from urllib.parse import urlparse, urlencode, parse_qs, urljoin
import threading
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from flask_cors import CORS
import tempfile
import base64
from zip_utils import create_gradle_zip
import openai
from dotenv import load_dotenv
import pytesseract
from PIL import Image
import google.generativeai as genai
import asyncio
from browser_use import Agent
from langchain_openai import AzureChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
import codecs
import socket

# Load environment variables from .env file
load_dotenv(override=True)

# Initialize logger
logger = logging.getLogger('curlrunner')
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Initialize APScheduler
scheduler = BackgroundScheduler()
scheduler.start()

app = Flask(__name__, 
                static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'), 
                static_url_path='/static',
                template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'))
app.secret_key = os.environ.get('SECRET_KEY', 'devsecret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# API Co-Test Models - defined inline after db initialization
from datetime import datetime as dt
try:
    from sqlalchemy.dialects.postgresql import JSONB, ARRAY
    # For SQLite, use JSON instead of JSONB
    JSONType = db.JSON
    ArrayType = db.Text  # SQLite doesn't support arrays, use Text
except:
    JSONType = db.JSON
    ArrayType = db.Text

class APIWorkspace(db.Model):
    __tablename__ = 'api_workspaces'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer)
    is_team = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.utcnow, onupdate=dt.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'description': self.description,
            'user_id': self.user_id, 'is_team': self.is_team,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class APIEnvironment(db.Model):
    __tablename__ = 'api_environments'
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('api_workspaces.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.utcnow, onupdate=dt.utcnow)
    
    def to_dict(self, include_variables=False):
        result = {
            'id': self.id, 'workspace_id': self.workspace_id, 'name': self.name,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_variables:
            result['variables'] = [v.to_dict() for v in APIEnvironmentVariable.query.filter_by(environment_id=self.id).all()]
        return result

class APIEnvironmentVariable(db.Model):
    __tablename__ = 'api_environment_variables'
    id = db.Column(db.Integer, primary_key=True)
    environment_id = db.Column(db.Integer, db.ForeignKey('api_environments.id', ondelete='CASCADE'), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Text)
    is_secret = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    
    def to_dict(self, mask_secrets=True):
        return {
            'id': self.id, 'environment_id': self.environment_id, 'key': self.key,
            'value': '***HIDDEN***' if (self.is_secret and mask_secrets) else self.value,
            'is_secret': self.is_secret, 'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class APIGlobalVariable(db.Model):
    __tablename__ = 'api_global_variables'
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('api_workspaces.id', ondelete='CASCADE'), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Text)
    is_secret = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    
    def to_dict(self, mask_secrets=True):
        return {
            'id': self.id, 'workspace_id': self.workspace_id, 'key': self.key,
            'value': '***HIDDEN***' if (self.is_secret and mask_secrets) else self.value,
            'is_secret': self.is_secret, 'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class APIRequestHistory(db.Model):
    __tablename__ = 'api_request_history'
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey('api_workspaces.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer)
    method = db.Column(db.String(10), nullable=False)
    url = db.Column(db.Text, nullable=False)
    headers = db.Column(JSONType)
    body = db.Column(db.Text)
    response_status = db.Column(db.Integer)
    response_time = db.Column(db.Integer)
    response_body = db.Column(db.Text)
    response_headers = db.Column(JSONType)
    environment_id = db.Column(db.Integer, db.ForeignKey('api_environments.id', ondelete='SET NULL'))
    executed_at = db.Column(db.DateTime, default=dt.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id, 'workspace_id': self.workspace_id, 'user_id': self.user_id,
            'method': self.method, 'url': self.url, 'headers': self.headers, 'body': self.body,
            'response_status': self.response_status, 'response_time': self.response_time,
            'response_body': self.response_body, 'response_headers': self.response_headers,
            'environment_id': self.environment_id,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None
        }

class APIFavorite(db.Model):
    __tablename__ = 'api_favorites'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    request_id = db.Column(db.Integer)
    name = db.Column(db.String(255))
    tags = db.Column(db.Text)  # Store as JSON string for SQLite
    method = db.Column(db.String(10), nullable=False)
    url = db.Column(db.Text, nullable=False)
    headers = db.Column(JSONType)
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=dt.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id, 'user_id': self.user_id, 'request_id': self.request_id,
            'name': self.name, 'tags': self.tags, 'method': self.method,
            'url': self.url, 'headers': self.headers, 'body': self.body,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

print("✅ API Co-Test models loaded")

# Run database migration on startup (safe to run multiple times)
try:
    from run_migration import run_migration
    with app.app_context():
        print("🔄 Running database migration...")
        run_migration()
        print("✅ Database migration completed")
except Exception as e:
    print(f"⚠️  Migration warning: {e}")
    print("Continuing with application startup...")

# Register blueprints
app.register_blueprint(autoheal_bp)

# Import and register API Co-Test routes
try:
    from routes import api_cotest_routes
    # Inject models into routes module
    api_cotest_routes.db = db
    api_cotest_routes.APIWorkspace = APIWorkspace
    api_cotest_routes.APIEnvironment = APIEnvironment
    api_cotest_routes.APIEnvironmentVariable = APIEnvironmentVariable
    api_cotest_routes.APIGlobalVariable = APIGlobalVariable
    api_cotest_routes.APIRequestHistory = APIRequestHistory
    api_cotest_routes.APIFavorite = APIFavorite
    app.register_blueprint(api_cotest_routes.api_cotest_bp)
    print("✅ API Co-Test routes registered")
except Exception as e:
    print(f"⚠️  Warning: Could not register API Co-Test routes: {e}")

# Define Jira OAuth URLs
JIRA_AUTH_URL = 'https://auth.atlassian.com/authorize'
JIRA_TOKEN_URL = 'https://auth.atlassian.com/oauth/token'

# Configure Google Generative AI
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model_name = os.environ.get('GOOGLE_API_MODEL', 'gemini-pro-vision')
login_manager = LoginManager(app)
oauth = OAuth(app)

# Define public routes that don't require authentication
public_routes = [
    '/',  # Home page only
    '/home',  # Home redirect (dashboard is now public for welcome screen)
    '/index',  # Home redirect
    '/autoheal',  # Simple Auto-Healing Recorder page
    '/api/jira/oauth/login',
    '/api/jira/oauth/callback',
    '/api/jira/status',
    '/api/jira/logout',  # Allow logout without authentication
    '/api/autoheal/',  # Allow all autoheal APIs without Jira auth
    '/static/',  # CSS, JS, and other static assets
    '/favicon.ico',
    '/favicon.png'
]

@app.route('/favicon.ico')
def favicon():
    """Serve favicon to prevent 404 errors - returns empty response"""
    return '', 204  # No Content

# Jira authentication decorator for additional security
def jira_auth_required(f):
    """Decorator to ensure Jira authentication for specific routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user has valid Jira access token
        access_token = session.get('jira_access_token')
        if not access_token:
            logger.warning(f"Access denied to {request.endpoint}: No Jira access token")
            return redirect(url_for('index'))
        
        # Check if token is expired
        token_expires = session.get('jira_token_expires', 0)
        if time.time() > token_expires:
            # Try to refresh the token
            if not refresh_jira_token():
                logger.warning(f"Access denied to {request.endpoint}: Token expired and refresh failed")
                return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function


# Simple admin decorator using allowlisted emails in env ADMIN_EMAILS (comma-separated)
def admin_required(f):
    """Restrict access to admin users based on email allowlist.
    Set ADMIN_EMAILS env var to comma-separated list of allowed emails.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            admin_csv = os.getenv('ADMIN_EMAILS', '')
            allow = [e.strip().lower() for e in admin_csv.split(',') if e.strip()]
            user_email = (session.get('jira_user_email') or '').lower()
            if allow and user_email in allow:
                return f(*args, **kwargs)
            # If no allowlist configured, deny by default
            return jsonify({'error': 'Admin access required'}), 403
        except Exception:
            return jsonify({'error': 'Admin access required'}), 403
    return wrapper

@app.context_processor
def inject_admin_flag():
    """Inject a boolean `is_admin` into templates based on ADMIN_EMAILS allowlist.
    Returns False if no allowlist is configured or the user is not in the list.
    """
    try:
        admin_csv = os.getenv('ADMIN_EMAILS', '')
        allow = [e.strip().lower() for e in admin_csv.split(',') if e.strip()]
        user_email = (session.get('jira_user_email') or '').lower()
        return { 'is_admin': bool(allow and user_email in allow) }
    except Exception:
        return { 'is_admin': False }

@app.before_request
def check_jira_auth():
    """Check if user is authenticated with Jira before processing any request"""
    # Skip authentication check only for essential public routes
    is_public = False
    for route in public_routes:
        if request.path == route or (route.endswith('/') and request.path.startswith(route)) or \
           (not route.endswith('/') and request.path.startswith(route + '/')):
            is_public = True
            break
    
    if is_public:
        logger.debug(f"Allowing access to public route: {request.path}")
        return  # Allow access to public routes without authentication
    
    logger.info(f"Checking Jira authentication for non-public route: {request.path}")

    # Check for API requests that might need special handling
    is_api_request = request.path.startswith('/api/')
    
    # Log the path being checked
    logger.debug(f"Checking Jira auth for path: {request.path}")
    
    # Check if Jira access token exists
    access_token = session.get('jira_access_token')
    if not access_token:
        # No token found, redirect to home page
        logger.info(f"No Jira token found, redirecting to home page for path: {request.path}")
        
        # For API requests, return 401 Unauthorized instead of redirecting
        if is_api_request:
            return jsonify({
                'error': 'Jira authentication required', 
                'login_url': url_for('index', _external=True)
            }), 401
            
        # For regular requests, redirect to home page
        return redirect(url_for('index'))
    
    # Check if token is expired
    token_expires = session.get('jira_token_expires', 0)
    if time.time() > token_expires:
        # Try to refresh the token
        if not refresh_jira_token():
            # Token refresh failed
            logger.info(f"Token refresh failed, redirecting to home page for path: {request.path}")
            
            # For API requests, return 401 Unauthorized
            if is_api_request:
                return jsonify({
                    'error': 'Jira authentication expired', 
                    'login_url': url_for('index', _external=True)
                }), 401
            
            # For regular requests, redirect to home page
            return redirect(url_for('index'))
    
    # Token is valid, continue with the request
    logger.debug(f"Jira authentication valid for path: {request.path}")

@app.route('/api/jira/status')
def jira_status():
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({'connected': False})
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    # Use a lightweight endpoint to check validity
    resp = requests.get('https://api.atlassian.com/me', headers=headers)
    if resp.status_code == 401:
        session.pop('jira_access_token', None)
        return jsonify({'connected': False})
    return jsonify({'connected': True})

@app.route('/api/jira/user-info')
def jira_user_info():
    """Get current Jira user information and welcome status"""
    logger.info("=== User Info API Called ===")
    logger.info(f"Session keys: {list(session.keys())}")
    logger.info(f"Has access token: {bool(session.get('jira_access_token'))}")
    
    if not session.get('jira_access_token'):
        logger.warning("No access token found in session")
        return jsonify({"authenticated": False}), 401
    
    # Check if we have user info, if not try to fetch it
    user_name = session.get('jira_user_name')
    user_email = session.get('jira_user_email')
    
    logger.info(f"Current session user info: name='{user_name}', email='{user_email}'")
    
    # If we don't have proper user info (default fallback values), try to fetch it again
    if not user_name or user_name == 'Jira User' or not user_email or user_email == 'Connected to Jira':
        logger.info("Missing or default user info, attempting to fetch from Atlassian API...")
        try:
            access_token = session.get('jira_access_token')
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            user_info_resp = requests.get(
                'https://api.atlassian.com/me',
                headers=headers,
                timeout=10
            )
            
            logger.info(f"Atlassian API response status: {user_info_resp.status_code}")
            
            if user_info_resp.status_code == 200:
                user_data = user_info_resp.json()
                logger.info(f"Successfully fetched user data: {user_data}")
                
                # Extract user info
                user_name = (user_data.get('name') or 
                           user_data.get('displayName') or 
                           user_data.get('display_name') or 
                           user_data.get('nickname') or 
                           session.get('jira_user_name', 'User'))
                
                user_email = (user_data.get('email') or 
                            user_data.get('emailAddress') or 
                            user_data.get('email_address') or 
                            session.get('jira_user_email', ''))
                
                user_avatar = (user_data.get('picture') or 
                             user_data.get('avatar') or 
                             user_data.get('avatarUrl') or 
                             user_data.get('avatar_url') or 
                             user_data.get('avatarUrls', {}).get('48x48') or 
                             session.get('jira_user_avatar', ''))
                
                # Update session with fresh data
                session['jira_user_name'] = user_name
                session['jira_user_email'] = user_email
                session['jira_user_avatar'] = user_avatar
                
                logger.info(f"Updated session with user info: name='{user_name}', email='{user_email}'")
            else:
                logger.warning(f"Failed to fetch user info: {user_info_resp.status_code}, Response: {user_info_resp.text}")
                user_name = session.get('jira_user_name', 'User')
                user_email = session.get('jira_user_email', '')
        except Exception as e:
            logger.error(f"Error fetching user info: {str(e)}")
            user_name = session.get('jira_user_name', 'User')
            user_email = session.get('jira_user_email', '')
    
    response_data = {
        "authenticated": True,
        "user_name": user_name,
        "user_email": user_email,
        "user_avatar": session.get('jira_user_avatar', ''),
        "login_time": session.get('jira_login_time'),
        "show_welcome": session.get('show_welcome_message', False),
        "jira_domain": session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    }
    
    logger.info(f"Returning user info response: {response_data}")
    
    # Clear the welcome message flag after sending it once
    if session.get('show_welcome_message'):
        session['show_welcome_message'] = False
    
    return jsonify(response_data)

@app.route('/api/jira/debug-session')
def debug_session():
    """Debug endpoint to see what's in the session"""
    session_data = {
        "all_session_keys": list(session.keys()),
        "jira_access_token": "***PRESENT***" if session.get('jira_access_token') else None,
        "jira_user_name": session.get('jira_user_name'),
        "jira_user_email": session.get('jira_user_email'),
        "jira_user_avatar": session.get('jira_user_avatar'),
        "jira_login_time": session.get('jira_login_time'),
        "jira_domain": session.get('jira_domain'),
        "jira_cloud_id": session.get('jira_cloud_id'),
        "show_welcome_message": session.get('show_welcome_message'),
        "has_access_token": bool(session.get('jira_access_token')),
        "session_id": id(session)
    }
    return jsonify(session_data)

@app.route('/api/test-session', methods=['GET', 'POST'])
def test_session():
    """Test basic session functionality"""
    if request.method == 'POST':
        # Set test data
        session['test_name'] = 'Test User'
        session['test_email'] = 'test@example.com'
        session['test_time'] = time.time()
        return jsonify({
            "message": "Test data stored in session",
            "stored_data": {
                "test_name": session['test_name'],
                "test_email": session['test_email'],
                "test_time": session['test_time']
            }
        })
    else:
        # Get test data
        return jsonify({
            "message": "Reading test data from session",
            "session_keys": list(session.keys()),
            "test_data": {
                "test_name": session.get('test_name'),
                "test_email": session.get('test_email'),
                "test_time": session.get('test_time')
            }
        })

@app.route('/api/jira/refresh-user-info', methods=['POST'])
def refresh_user_info():
    """Manually refresh user info from Atlassian API"""
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({"error": "Not authenticated"}), 401
    
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Accept': 'application/json'
    }
    
    try:
        logger.info("Manually refreshing user info from Atlassian API...")
        user_info_resp = requests.get(
            'https://api.atlassian.com/me',
            headers=headers,
            timeout=10
        )
        logger.info(f"Manual user info response status: {user_info_resp.status_code}")
        
        if user_info_resp.status_code == 200:
            user_data = user_info_resp.json()
            logger.info(f"Manual fetch - Raw user data: {user_data}")
            
            # Try different field names that Atlassian might use
            user_name = (user_data.get('name') or 
                        user_data.get('displayName') or 
                        user_data.get('display_name') or 
                        user_data.get('nickname') or 
                        user_data.get('account_id') or
                        'Jira User')
            
            user_email = (user_data.get('email') or 
                         user_data.get('emailAddress') or 
                         user_data.get('email_address') or 
                         'Connected to Jira')
            
            user_avatar = (user_data.get('picture') or 
                          user_data.get('avatar') or 
                          user_data.get('avatarUrl') or 
                          user_data.get('avatar_url') or 
                          user_data.get('avatarUrls', {}).get('48x48') or
                          '')
            
            session['jira_user_name'] = user_name
            session['jira_user_email'] = user_email
            session['jira_user_avatar'] = user_avatar
            session['jira_login_time'] = time.time()
            
            return jsonify({
                "success": True,
                "user_name": user_name,
                "user_email": user_email,
                "user_avatar": user_avatar,
                "raw_data": user_data
            })
        else:
            logger.error(f"Manual fetch failed. Status: {user_info_resp.status_code}, Response: {user_info_resp.text}")
            return jsonify({
                "success": False,
                "error": f"API returned status {user_info_resp.status_code}",
                "response": user_info_resp.text
            }), 400
    except Exception as e:
        logger.error(f"Exception during manual user info fetch: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/jira/logout', methods=['POST'])
def jira_logout():
    """Logout from Jira by removing tokens from session"""
    try:
        # Remove all Jira-related tokens and user info from session
        session.pop('jira_access_token', None)
        session.pop('jira_refresh_token', None)
        session.pop('jira_token_expires', None)
        session.pop('jira_cloud_id', None)
        session.pop('jira_domain', None)
        session.pop('jira_user_name', None)
        session.pop('jira_user_email', None)
        session.pop('jira_user_avatar', None)
        session.pop('jira_login_time', None)
        session.pop('show_welcome_message', None)
        
        logger.info("User logged out from Jira")
        return jsonify({'success': True, 'message': 'Successfully logged out from Jira'})
    except Exception as e:
        logger.error(f"Error during Jira logout: {str(e)}")
        return jsonify({'success': False, 'message': f'Error during logout: {str(e)}'}), 500

# OAuth config (replace with your credentials)
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', 'GOOGLE_CLIENT_SECRET')
app.config['GITHUB_CLIENT_ID'] = os.environ.get('GITHUB_CLIENT_ID', 'GITHUB_CLIENT_ID')
app.config['GITHUB_CLIENT_SECRET'] = os.environ.get('GITHUB_CLIENT_SECRET', 'GITHUB_CLIENT_SECRET')

# Jira OAuth config (local vs prod)
FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
if FLASK_ENV == 'development':
    app.config['JIRA_CLIENT_ID'] = os.environ.get('JIRA_CLIENT_ID_LOCAL', 'JIRA_CLIENT_ID_LOCAL')
    app.config['JIRA_CLIENT_SECRET'] = os.environ.get('JIRA_CLIENT_SECRET_LOCAL', 'JIRA_CLIENT_SECRET_LOCAL')
    app.config['JIRA_CALLBACK_URL'] = os.environ.get('JIRA_CALLBACK_URL_LOCAL', 'JIRA_CALLBACK_URL_LOCAL')
else:
    app.config['JIRA_CLIENT_ID'] = os.environ.get('JIRA_CLIENT_ID', 'JIRA_CLIENT_ID')
    app.config['JIRA_CLIENT_SECRET'] = os.environ.get('JIRA_CLIENT_SECRET', 'JIRA_CLIENT_SECRET')
    app.config['JIRA_CALLBACK_URL'] = os.environ.get('JIRA_CALLBACK_URL', 'JIRA_CALLBACK_URL')

# LLM Rate Limiting Configuration
DAILY_LLM_LIMIT = int(os.environ.get('DAILY_LLM_LIMIT', '20'))  # 20 calls per user per day
user_llm_usage = defaultdict(lambda: {'count': 0, 'date': None})

def get_user_identifier():
    """Get a unique identifier for the current user"""
    # Try to get Jira user email first (most reliable for authenticated users)
    user_email = session.get('jira_user_email')
    if user_email and user_email != 'Connected to Jira':
        return user_email
    
    # Check if user has Jira access token (they're authenticated but email might not be set yet)
    access_token = session.get('jira_access_token')
    if access_token:
        # Try to get user info from Jira to get the email
        try:
            # If they have an access token, they should have a jira_user_name too
            user_name = session.get('jira_user_name')
            if user_name:
                # Create a stable identifier based on their Jira user name
                # This should be consistent across login sessions
                return f"jira_user_{user_name.lower().replace(' ', '_')}"
        except:
            pass
    
    # For truly anonymous users, generate or get session ID
    if 'persistent_user_id' not in session:
        import uuid
        session['persistent_user_id'] = f"user_{uuid.uuid4().hex[:12]}"
    
    return session.get('persistent_user_id')

def migrate_user_usage_if_needed():
    """Migrate usage from old session ID to new stable identifier if user just authenticated"""
    current_id = get_user_identifier()
    
    # If current ID is email or jira-based, check for old session data to migrate
    if '@' in current_id or current_id.startswith('jira_user_'):
        # Look for any session-based usage data for this session that we can migrate
        old_session_id = session.get('persistent_user_id')
        if old_session_id and old_session_id != current_id and old_session_id in user_llm_usage:
            # Migrate the usage data from the old session ID to the new stable ID
            old_data = user_llm_usage[old_session_id]
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Only migrate if it's from today
            if old_data.get('date') == today:
                current_data = user_llm_usage.get(current_id, {'count': 0, 'date': today})
                # Take the maximum count to avoid losing usage
                current_data['count'] = max(current_data.get('count', 0), old_data['count'])
                current_data['date'] = today
                user_llm_usage[current_id] = current_data
                
                # Remove the old session data
                del user_llm_usage[old_session_id]
                logger.info(f"Migrated LLM usage from {old_session_id} to {current_id}: {current_data['count']} requests")

def get_user_display_info():
    """Get user information for display purposes"""
    user_id = get_user_identifier()
    user_email = session.get('jira_user_email')
    
    if user_email and user_email != 'Connected to Jira':
        return {
            'user_id': user_id,
            'display_name': user_email,
            'user_type': 'authenticated',
            'jira_connected': True
        }
    else:
        return {
            'user_id': user_id,
            'display_name': f"Anonymous User ({user_id})",
            'user_type': 'anonymous',
            'jira_connected': False
        }

def check_and_increment_llm_usage(user_id=None):
    """Check if user has exceeded daily LLM limit and increment usage"""
    if user_id is None:
        user_id = get_user_identifier()
    
    # Try to migrate old usage data if user just authenticated
    migrate_user_usage_if_needed()
    
    today = datetime.now().strftime('%Y-%m-%d')
    user_data = user_llm_usage[user_id]
    
    # Reset count if it's a new day
    if user_data['date'] != today:
        user_data['count'] = 0
        user_data['date'] = today
    
    # Check if limit exceeded
    if user_data['count'] >= DAILY_LLM_LIMIT:
        return False, user_data['count']
    
    # Increment usage
    user_data['count'] += 1
    logger.info(f"LLM usage for user {user_id}: {user_data['count']}/{DAILY_LLM_LIMIT}")
    return True, user_data['count']

def get_user_llm_usage(user_id=None):
    """Get current LLM usage for user"""
    if user_id is None:
        user_id = get_user_identifier()
    
    # Try to migrate old usage data if user just authenticated
    migrate_user_usage_if_needed()
    
    today = datetime.now().strftime('%Y-%m-%d')
    user_data = user_llm_usage[user_id]
    
    # Reset count if it's a new day
    if user_data['date'] != today:
        user_data['count'] = 0
        user_data['date'] = today
    
    return user_data['count'], DAILY_LLM_LIMIT

def llm_rate_limit(f):
    """Decorator to apply LLM rate limiting to endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        allowed, current_count = check_and_increment_llm_usage()
        if not allowed:
            logger.warning(f"LLM rate limit exceeded for user {get_user_identifier()}: {current_count}/{DAILY_LLM_LIMIT}")
            return jsonify({
                'error': f'Daily LLM usage limit exceeded ({DAILY_LLM_LIMIT} calls per day). Current usage: {current_count}',
                'rate_limit': {
                    'limit': DAILY_LLM_LIMIT,
                    'used': current_count,
                    'remaining': 0,
                    'reset_time': 'Next day at 00:00 UTC'
                }
            }), 429  # Too Many Requests
        return f(*args, **kwargs)
    return decorated_function

google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={'scope': 'openid email profile'},
)

github = oauth.register(
    name='github',
    client_id=app.config['GITHUB_CLIENT_ID'],
    client_secret=app.config['GITHUB_CLIENT_SECRET'],
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    api_base_url='https://api.github.com/',
    userinfo_endpoint='https://api.github.com/user',
    client_kwargs={'scope': 'user:email'},
)

JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password_hash = db.Column(db.String(256))
    oauth_provider = db.Column(db.String(50))
    oauth_id = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    collections = db.relationship('Collection', backref='user', lazy=True)
    environments = db.relationship('Environment', backref='user', lazy=True)

class Collection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150))
    data = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Environment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150))
    data = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScheduledJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    collection_id = db.Column(db.Integer, nullable=False)
    environment_id = db.Column(db.Integer, nullable=False)
    frequency = db.Column(db.String(50), nullable=False)
    cron = db.Column(db.String(100), nullable=True)
    last_run = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Helper functions

def sanitize_headers(headers):
    # Remove any headers that shouldn't be sent
    # (can be expanded as needed)
    forbidden = {'host', 'content-length', 'accept-encoding', 'connection'}
    return {k: v for k, v in headers.items() if k.lower() not in forbidden}

def validate_url(url):
    # Basic URL validation
    try:
        result = urlparse(url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except Exception:
        return False

def parse_form_data(body):
    # Try to parse JSON or URL-encoded form data
    try:
        if isinstance(body, dict):
            return body
        if isinstance(body, str):
            try:
                return json.loads(body)
            except Exception:
                # fallback: parse query string style
                return dict(parse_qs(body))
        return {}
    except Exception:
        return {}

def extract_requests(items):
    result = []
    for item in items:
        if 'request' in item:
            result.append(item)
        elif 'item' in item:
            result.extend(extract_requests(item['item']))
    return result

# Dummy for process_request_with_environment (to avoid runtime errors)
def process_request_with_environment(request, environment):
    # Replace variables in request with environment values (implement as needed)
    return request

# E2E Test Model
class E2ETest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    test_name = db.Column(db.String(200), nullable=False)
    steps = db.Column(db.Text, nullable=False)  # Store as JSON string
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Test Context Model
class TestContext(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    context_data = db.Column(db.Text)  # JSON string
    # Structured fields for better querying
    feature_summary = db.Column(db.Text)
    requirements = db.Column(db.Text)  # JSON string of array
    user_flows = db.Column(db.Text)  # JSON string of array
    validation_points = db.Column(db.Text)  # JSON string of array
    dependencies = db.Column(db.Text)  # JSON string of array
    edge_cases = db.Column(db.Text)  # JSON string of array
    data_requirements = db.Column(db.Text)  # JSON string of array
    # New fields from enhanced prompt
    performance_criteria = db.Column(db.Text)  # JSON string of array
    security_considerations = db.Column(db.Text)  # JSON string of array
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<TestContext {self.name}>'

# Jira user directory (for admin search and autocomplete)
class JiraUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(200), index=True)
    email = db.Column(db.String(200), index=True)
    avatar_48 = db.Column(db.String(500))
    active = db.Column(db.Boolean, default=True)
    time_zone = db.Column(db.String(100))
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'accountId': self.account_id,
            'displayName': self.display_name,
            'email': self.email,
            'avatar48': self.avatar_48,
            'active': self.active,
        }

# --- TEMP: Create all tables if not present ---
with app.app_context():
    db.create_all()

def save_data(data):
    # Implement persistent storage as needed
    pass

# Health check endpoints for Kubernetes
@app.route('/health')
@app.route('/healthz')
@app.route('/ready')
def health_check():
    """Health check endpoint for Kubernetes readiness and liveness probes"""
    return jsonify({'status': 'healthy', 'timestamp': time.time()}), 200

@app.route('/')
def index():
    return render_template('home.html', active_tab='home')

@app.route('/home')
@app.route('/index')
def home_redirect():
    return redirect(url_for('index'))

@app.route('/download-logo')
def download_logo():
    return render_template('download-logo.html')

@app.route('/learning-resources')
def learning_resources():
    return render_template('learning-resources.html', active_tab='learning')

@app.route('/context-builder')
@jira_auth_required
def context_builder():
    return render_template('context-builder.html', active_tab='context-builder')

@app.route('/api/process-context', methods=['POST'])
@jira_auth_required
@llm_rate_limit
def process_context():
    try:
        # Get uploaded file or text
        content = ''
        if 'document' in request.files:
            file = request.files['document']
            if file and allowed_file(file.filename):
                # Extract text from document
                if file.filename.endswith('.pdf'):
                    # For PDF files
                    import io
                    from PyPDF2 import PdfReader
                    pdf_reader = PdfReader(io.BytesIO(file.read()))
                    for page in pdf_reader.pages:
                        content += page.extract_text() + '\n'
                elif file.filename.endswith(('.doc', '.docx')):
                    # For Word documents
                    import io
                    import docx
                    doc = docx.Document(io.BytesIO(file.read()))
                    for para in doc.paragraphs:
                        content += para.text + '\n'
                else:
                    # For text files
                    content = file.read().decode('utf-8')
        else:
            content = request.form.get('raw_text', '')
            
        if not content:
            return jsonify({'error': 'No content provided'}), 400
            
        # Process with AI
        context_data = generate_structured_context(content)
        
        # Save to database if requested
        if request.form.get('save', 'false').lower() == 'true':
            name = request.form.get('name', 'Untitled Context')
            description = request.form.get('description', '')
            context_id = save_context_to_db(context_data, name, description)
            return jsonify({
                'success': True,
                'context_id': context_id,
                'context': context_data
            })
        else:
            return jsonify({
                'success': True,
                'context': context_data
            })
    except Exception as e:
        app.logger.error(f"Error processing context: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/contexts', methods=['GET'])
@jira_auth_required
def list_contexts():
    try:
        user_id = get_user_identifier()
        contexts = TestContext.query.filter_by(user_id=user_id).all()
        result = []
        for context in contexts:
            result.append({
                'id': context.id,
                'name': context.name,
                'description': context.description,
                'created_at': context.created_at.isoformat(),
                'updated_at': context.updated_at.isoformat()
            })
        return jsonify({'contexts': result})
    except Exception as e:
        app.logger.error(f"Error listing contexts: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/contexts/<int:context_id>', methods=['GET'])
@jira_auth_required
def get_context(context_id):
    try:
        user_id = get_user_identifier()
        context = TestContext.query.filter_by(id=context_id, user_id=user_id).first()
        if not context:
            return jsonify({'error': 'Context not found'}), 404
        
        # Parse all JSON fields
        context_data = json.loads(context.context_data) if context.context_data else {}
        
        # Build response with all structured fields
        response = {
            'id': context.id,
            'name': context.name,
            'description': context.description,
            'feature_summary': context.feature_summary,
            'requirements': json.loads(context.requirements) if context.requirements else [],
            'user_flows': json.loads(context.user_flows) if context.user_flows else [],
            'validation_points': json.loads(context.validation_points) if context.validation_points else [],
            'dependencies': json.loads(context.dependencies) if context.dependencies else [],
            'edge_cases': json.loads(context.edge_cases) if context.edge_cases else [],
            'data_requirements': json.loads(context.data_requirements) if context.data_requirements else [],
            # Include new fields
            'performance_criteria': json.loads(context.performance_criteria) if context.performance_criteria else [],
            'security_considerations': json.loads(context.security_considerations) if context.security_considerations else [],
            'created_at': context.created_at.isoformat(),
            'updated_at': context.updated_at.isoformat()
        }
        
        return jsonify(response)
    except Exception as e:
        app.logger.error(f"Error getting context: {str(e)}")
        return jsonify({'error': f'Error retrieving context: {str(e)}'}), 500

@app.route('/api/contexts/<int:context_id>', methods=['DELETE'])
@jira_auth_required
def delete_context(context_id):
    try:
        user_id = get_user_identifier()
        context = TestContext.query.filter_by(id=context_id, user_id=user_id).first()
        if not context:
            return jsonify({'error': 'Context not found'}), 404
        
        db.session.delete(context)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f"Error deleting context: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api-co-test')
@jira_auth_required
def api_co_test():
    return render_template('api.html', active_tab='api')

# Keep old route for backward compatibility
@app.route('/code')
@jira_auth_required
def code():
    return redirect('/api-co-test', code=301)

def detect_graphql_request(url, headers, body):
    """Detect if a cURL request is a GraphQL request"""
    # Check URL patterns
    url_indicators = [
        '/graphql' in url.lower(),
        url.lower().endswith('/graphql'),
        '/gql' in url.lower(),
        url.lower().endswith('/gql')
    ]
    
    # Check headers for GraphQL content type or specific headers
    header_indicators = []
    if headers:
        content_type = headers.get('Content-Type', '').lower()
        header_indicators = [
            'application/json' in content_type and any(url_indicators),
            any('graphql' in str(v).lower() for v in headers.values())
        ]
    
    # Check body for GraphQL query structure
    body_indicators = []
    if body:
        try:
            # Try to parse as JSON and check for GraphQL structure
            import json
            body_json = json.loads(body)
            body_indicators = [
                'query' in body_json,
                'mutation' in body_json,
                any(key in body_json for key in ['query', 'mutation', 'subscription'])
            ]
        except (json.JSONDecodeError, TypeError):
            # Check raw body for GraphQL keywords
            body_lower = body.lower()
            body_indicators = [
                'query' in body_lower and ('{' in body_lower or 'mutation' in body_lower),
                'mutation' in body_lower and '{' in body_lower,
                'subscription' in body_lower and '{' in body_lower
            ]
    
    # Return True if any strong indicators are present
    return any(url_indicators) or any(header_indicators) or any(body_indicators)

def process_graphql_request(body, headers):
    """Process and validate GraphQL request body and headers"""
    import json
    
    # Ensure Content-Type is set for GraphQL
    if 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/json'
    
    if body:
        try:
            # Try to parse and validate the JSON structure
            body_json = json.loads(body)
            
            # Ensure the body has a proper GraphQL structure
            if 'query' not in body_json and 'mutation' not in body_json and 'subscription' not in body_json:
                # If raw GraphQL query is provided, wrap it in proper JSON structure
                if isinstance(body_json, str) or (isinstance(body_json, dict) and len(body_json) == 0):
                    body_json = {'query': body.strip('"\'') if isinstance(body, str) else str(body_json)}
            
            # Ensure variables field exists if not present
            if 'variables' not in body_json:
                body_json['variables'] = {}
                
            # Convert back to JSON string
            body = json.dumps(body_json)
            
        except json.JSONDecodeError:
            # If body is not valid JSON, try to construct proper GraphQL request
            body_clean = body.strip().strip('"\'')
            if body_clean.startswith(('query', 'mutation', 'subscription')):
                body = json.dumps({
                    'query': body_clean,
                    'variables': {}
                })
    
    return body, headers

def format_graphql_response(json_data):
    """Format GraphQL response with proper error highlighting"""
    import json
    
    # Check if this is a GraphQL response with errors
    if isinstance(json_data, dict) and 'errors' in json_data:
        # Highlight errors in the response
        formatted_response = {
            "🚨 GraphQL Errors": json_data.get('errors', []),
            "data": json_data.get('data'),
            "extensions": json_data.get('extensions')
        }
        # Remove None values
        formatted_response = {k: v for k, v in formatted_response.items() if v is not None}
        return json.dumps(formatted_response, indent=2)
    else:
        # Standard JSON formatting for successful responses
        return json.dumps(json_data, indent=2)

@app.route('/execute_curl', methods=['POST'])
def execute_curl():
    """Execute a curl command and return the results"""
    try:
        data = request.get_json()
        # Accept both 'command' and 'curl_command' for backwards compatibility
        curl_command = data.get('command') or data.get('curl_command')
        if not curl_command:
            return jsonify({'error': 'No curl command provided'}), 400
        
        # Basic security check - only allow curl commands
        if not curl_command.strip().startswith('curl '):
            return jsonify({'error': 'Invalid command. Only curl commands are allowed.'}), 400
        
        # Parse the curl command to extract method, URL, headers, and body
        try:
            # Use regex-based parsing for better multi-line support
            command = curl_command
            
            # Initialize variables
            method = 'GET'  # Default method
            url = None
            headers = {}
            body = None
            
            # Extract URL first - look for quoted URLs
            url_patterns = [
                r"'(https?://[^']*)'",  # Single quoted URLs
                r'"(https?://[^"]*)"',  # Double quoted URLs
                r'(https?://\S+)'       # Unquoted URLs
            ]
            
            for pattern in url_patterns:
                url_match = re.search(pattern, command)
                if url_match:
                    url = url_match.group(1)
                    break
            
            # Extract method
            method_match = re.search(r'(?:-X|--request)\s+([A-Z]+)', command)
            if method_match:
                method = method_match.group(1)
            
            # Extract headers - handle both single and double quotes
            header_patterns = [
                r"(?:-H|--header)\s+'([^']+)'",   # Single quoted headers
                r'(?:-H|--header)\s+"([^"]+)"'    # Double quoted headers
            ]
            
            for pattern in header_patterns:
                for match in re.finditer(pattern, command):
                    header_text = match.group(1)
                    if ':' in header_text:
                        key, value = header_text.split(':', 1)
                        headers[key.strip()] = value.strip()
            
            # Extract body - handle multi-line JSON properly
            body_patterns = [
                r"--data-raw\s+'([^']*(?:\\'[^']*)*)'",  # Single quotes, handling escaped quotes
                r'--data-raw\s+"([^"]*(?:\\"[^"]*)*)"',  # Double quotes, handling escaped quotes
                r"--data-raw\s+['\"](.*?)['\"]",         # Generic quoted content
                r"--data\s+'([^']*(?:\\'[^']*)*)'",
                r'--data\s+"([^"]*(?:\\"[^"]*)*)"',
                r"--data\s+['\"](.*?)['\"]",
                r"-d\s+'([^']*(?:\\'[^']*)*)'",
                r'-d\s+"([^"]*(?:\\"[^"]*)*)"',
                r"-d\s+['\"](.*?)['\"]"
            ]
            
            for pattern in body_patterns:
                body_match = re.search(pattern, command, re.DOTALL)
                if body_match:
                    body = body_match.group(1)
                    # Unescape quotes
                    body = body.replace("\\'", "'").replace('\\"', '"')
                    break
            
            # If we have a body but no explicit method, assume POST
            if body and method == 'GET':
                method = 'POST'
            
            # Ensure Content-Type is set for JSON data
            if body and 'Content-Type' not in headers and body.strip().startswith('{'):
                headers['Content-Type'] = 'application/json'
            
            if not url:
                return jsonify({'error': 'No URL found in curl command'}), 400
                
            # Detect if this is a GraphQL request
            is_graphql_request = detect_graphql_request(url, headers, body)
            
            # Handle GraphQL-specific processing
            if is_graphql_request:
                body, headers = process_graphql_request(body, headers)
            
            # Debug logging
            logger.info(f"Parsed cURL - Method: {method}, URL: {url}, Body length: {len(body) if body else 0}, GraphQL: {is_graphql_request}")
            
            # Check for --location flag (follow redirects)
            follow_redirects = '--location' in command or '-L' in command
            
            # Measure execution time
            start_time = time.time()
            
            # Make the request
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                allow_redirects=follow_redirects,
                timeout=30
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            # Parse and format response body
            response_body = response.text
            try:
                # Try to parse as JSON and format it
                if response.headers.get('content-type', '').startswith('application/json'):
                    json_data = response.json()
                    
                    # Special handling for GraphQL responses
                    if is_graphql_request:
                        response_body = format_graphql_response(json_data)
                    else:
                        response_body = json.dumps(json_data, indent=2)
            except:
                # If JSON parsing fails, keep as text
                pass
            
            # Return the response in consistent format
            return jsonify({
                'success': True,
                'status': response.status_code,
                'statusText': response.reason,
                'headers': dict(response.headers),
                'body': response_body,
                'time': round(execution_time, 2),
                'size': len(response.content),
                'cookies': [{'name': k, 'value': v} for k, v in response.cookies.items()]
            })
            
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False,
                'error': 'Request timeout',
                'time': round((time.time() - start_time) * 1000, 2) if 'start_time' in locals() else 0
            }), 408
        except requests.exceptions.ConnectionError as e:
            return jsonify({
                'success': False,
                'error': f'Connection error: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2) if 'start_time' in locals() else 0
            }), 503
        except Exception as e:
            logger.error(f"Error parsing curl command: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Error parsing curl command: {str(e)}'
            }), 400
            
    except Exception as e:
        logger.error(f"Error executing curl command: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error: {str(e)}'
        }), 500

@app.route('/execute_request', methods=['POST'])
def execute_request():
    """Execute a request from a Postman collection"""
    try:
        data = request.get_json()
        if not data or 'request' not in data:
            return jsonify({'error': 'No request data provided'}), 400
            
        postman_request = data['request']
        
        # Extract method
        method = postman_request.get('method', 'GET')
        
        # Extract URL
        url = ''
        if isinstance(postman_request['url'], str):
            url = postman_request['url']
        elif isinstance(postman_request['url'], dict) and 'raw' in postman_request['url']:
            url = postman_request['url']['raw']
        else:
            return jsonify({'error': 'Invalid URL format in request'}), 400
            
        # Extract headers
        headers = {}
        if 'header' in postman_request and postman_request['header']:
            for header in postman_request['header']:
                if 'key' in header and 'value' in header:
                    headers[header['key']] = header['value']
        
        # Extract body
        body = None
        if 'body' in postman_request and postman_request['body']:
            body_mode = postman_request['body'].get('mode')
            
            if body_mode == 'raw' and 'raw' in postman_request['body']:
                body = postman_request['body']['raw']
            elif body_mode == 'urlencoded' and 'urlencoded' in postman_request['body']:
                body = {}
                for param in postman_request['body']['urlencoded']:
                    if 'key' in param and 'value' in param:
                        body[param['key']] = param['value']
            elif body_mode == 'formdata' and 'formdata' in postman_request['body']:
                body = {}
                for param in postman_request['body']['formdata']:
                    if 'key' in param and 'value' in param:
                        body[param['key']] = param['value']
        
        # Measure execution time and make the request
        start_time = time.time()
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=30
        )
        execution_time = (time.time() - start_time) * 1000
        
        # Parse response body
        response_body = response.text
        try:
            if response.headers.get('content-type', '').startswith('application/json'):
                response_body = response.json()
        except:
            pass
        
        # Return comprehensive response
        return jsonify({
            'status_code': response.status_code,
            'status_text': response.reason,
            'headers': dict(response.headers),
            'body': response_body,
            'time': round(execution_time, 2),
            'size': len(response.content),
            'cookies': [{'name': k, 'value': v} for k, v in response.cookies.items()]
        })
        
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timeout'}), 408
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Connection error - Could not connect to server'}), 503
    except requests.exceptions.SSLError:
        return jsonify({'error': 'SSL verification failed'}), 495
    except Exception as e:
        logger.error(f"Error executing request: {str(e)}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/execute_graphql', methods=['POST'])
def execute_graphql():
    """Execute a GraphQL query"""
    try:
        data = request.get_json()
        if not data or 'endpoint' not in data or 'payload' not in data:
            return jsonify({'error': 'Missing required fields: endpoint and payload'}), 400
            
        endpoint = data['endpoint']
        headers = data.get('headers', {})
        payload = data['payload']
        
        # Ensure content type is set for GraphQL
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'
        
        # Make the GraphQL request
        response = requests.post(
            url=endpoint,
            headers=headers,
            json=payload
        )
        
        # Try to parse response as JSON
        try:
            body = response.json()
        except:
            body = response.text
        
        # Return the response
        return jsonify({
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'body': body
        })
        
    except Exception as e:
        logger.error(f"Error executing GraphQL query: {str(e)}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

# @app.route('/ui-recorder')
# def ui_recorder():
#     return render_template('ui-recorder.html')  # Template missing

# @app.route('/recorder-target')
# def recorder_target():
#     """
#     Single-tab recording interface that shows steps in real-time.
#     """
#     target_url = request.args.get('url', 'https://example.com')
#     response = make_response(render_template('recorder-target.html', target_url=target_url))  # Template missing
#     # Add headers to allow iframe embedding for the recorder-target page itself
#     response.headers['X-Frame-Options'] = 'ALLOWALL'
#     response.headers['Access-Control-Allow-Origin'] = '*'
#     return response

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 400
    user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify({'message': 'Signup successful', 'user': {'email': user.email}})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid credentials'}), 401
    login_user(user)
    return jsonify({'message': 'Login successful', 'user': {'email': user.email}})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out'})

@app.route('/api/user')
def get_user():
    if current_user.is_authenticated:
        return jsonify({'user': {'email': current_user.email}})
    return jsonify({'user': None})

# Google OAuth
@app.route('/api/oauth/google')
def oauth_google():
    redirect_uri = url_for('oauth_google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/api/oauth/google/callback')
def oauth_google_callback():
    token = google.authorize_access_token()
    resp = google.get('userinfo')
    user_info = resp.json()
    user = User.query.filter_by(oauth_provider='google', oauth_id=user_info['sub']).first()
    if not user:
        user = User(email=user_info.get('email'), oauth_provider='google', oauth_id=user_info['sub'])
        db.session.add(user)
        db.session.commit()
    login_user(user)
    return redirect('/')

# GitHub OAuth
@app.route('/api/oauth/github')
def oauth_github():
    redirect_uri = url_for('oauth_github_callback', _external=True)
    return github.authorize_redirect(redirect_uri)

@app.route('/api/oauth/github/callback')
def oauth_github_callback():
    token = github.authorize_access_token()
    resp = github.get('user')
    user_info = resp.json()
    user = User.query.filter_by(oauth_provider='github', oauth_id=str(user_info['id'])).first()
    if not user:
        user = User(email=user_info.get('email'), oauth_provider='github', oauth_id=str(user_info['id']))
        db.session.add(user)
        db.session.commit()
    login_user(user)
    return redirect('/')

# User-specific collections
@app.route('/api/collections', methods=['GET', 'POST'])
@login_required
def user_collections():
    if request.method == 'GET':
        collections = Collection.query.filter_by(user_id=current_user.id).all()
        return jsonify([{'id': c.id, 'name': c.name, 'data': c.data} for c in collections])
    else:
        data = request.json
        name = data.get('name')
        collection_data = data.get('data')
        c = Collection(user_id=current_user.id, name=name, data=collection_data)
        db.session.add(c)
        db.session.commit()
        return jsonify({'id': c.id, 'name': c.name, 'data': c.data})

# User-specific environments
@app.route('/api/environments', methods=['GET', 'POST'])
@login_required
def user_environments():
    if request.method == 'GET':
        envs = Environment.query.filter_by(user_id=current_user.id).all()
        return jsonify([{'id': e.id, 'name': e.name, 'data': e.data} for e in envs])
    else:
        data = request.json
        name = data.get('name')
        env_data = data.get('data')
        e = Environment(user_id=current_user.id, name=name, data=env_data)
        db.session.add(e)
        db.session.commit()
        return jsonify({'id': e.id, 'name': e.name, 'data': e.data})

# --- E2E Test Save API ---
@app.route('/api/e2e-tests', methods=['POST'])
def save_e2e_test():
    data = request.json
    test_name = data.get('testName')
    steps = data.get('steps')
    created_by = data.get('createdBy')
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    if not test_name:
        return jsonify({'error': 'Missing testName'}), 400
    if steps is None:
        steps = []
    # Store steps as JSON string
    steps_json = json.dumps(steps)
    e2e_test = E2ETest(
        user_id=user_id,
        test_name=test_name,
        steps=steps_json,
        created_by=created_by
    )
    db.session.add(e2e_test)
    db.session.commit()
    # Always return JSON
    return jsonify({'success': True, 'testId': e2e_test.id})

# --- E2E Test List API ---

@app.route('/api/e2e-tests/<int:test_id>', methods=['PUT'])
def update_e2e_test(test_id):
    data = request.json
    test = E2ETest.query.get_or_404(test_id)
    test.test_name = data.get('testName', test.test_name)
    test.steps = json.dumps(data.get('steps', json.loads(test.steps)))
    test.created_by = data.get('createdBy', test.created_by)
    db.session.commit()
    # Always return JSON
    return jsonify({'success': True, 'testId': test.id})

@app.route('/api/e2e-tests', methods=['GET'])
def list_e2e_tests():
    tests = E2ETest.query.all()
    return jsonify([
        {
            'id': t.id,
            'testName': t.test_name,
            'createdBy': t.created_by,
            'createdAt': t.created_at.isoformat()
        } for t in tests
    ])

# --- E2E Test Get by ID API ---
@app.route('/api/e2e-tests/<int:test_id>', methods=['GET'])
def get_e2e_test(test_id):
    t = E2ETest.query.get_or_404(test_id)
    return jsonify({
        'id': t.id,
        'testName': t.test_name,
        'steps': json.loads(t.steps),
        'createdBy': t.created_by,
        'createdAt': t.created_at.isoformat()
    })

# --- E2E Test Delete by ID API ---
@app.route('/api/e2e-tests/<int:test_id>', methods=['DELETE'])
def delete_e2e_test(test_id):
    t = E2ETest.query.get_or_404(test_id)
    db.session.delete(t)
    db.session.commit()
    return jsonify({'success': True})

# --- E2E Generate Zip API ---
@app.route('/api/generate-e2e-zip', methods=['POST'])
def generate_e2e_zip():
    data = request.json or {}
    test_ids = data.get('testIds')  # Optional: list of IDs
    if test_ids:
        tests = E2ETest.query.filter(E2ETest.id.in_(test_ids)).all()
    else:
        tests = E2ETest.query.all()
    steps = []
    for t in tests:
        steps.append({
            'testName': t.test_name,
            'steps': json.loads(t.steps)
        })
    import io
    zip_bytes = create_gradle_zip(steps, mode='e2e')
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype='application/zip',
        as_attachment=True,
        download_name='e2e-tests.zip'
    )

@app.route('/test-generator')
@jira_auth_required
def test_generator():
    # Redirect to individual by default for backward compatibility
    return redirect('/test-generator/individual', code=301)

@app.route('/test-generator/individual')
@jira_auth_required
def test_generator_individual():
    return render_template('manual-test-generator.html', active_tab='manual', is_development=FLASK_ENV == 'development')

@app.route('/test-generator/v2')
@jira_auth_required
def test_generator_v2():
    return render_template('manual-test-generator-v2.html', active_tab='manual', is_development=FLASK_ENV == 'development')

@app.route('/test-generator/bulk')
@jira_auth_required
def test_generator_bulk():
    return render_template('test-generator-bulk.html', active_tab='manual', is_development=FLASK_ENV == 'development')

# Keep old route for backward compatibility
@app.route('/manual-co-test')
@jira_auth_required
def manual_co_test():
    return redirect('/test-generator', code=301)

@app.route('/api/scheduled-jobs', methods=['GET', 'POST'])
def handle_scheduled_jobs():
    if request.method == 'GET':
        jobs = ScheduledJob.query.all()
        return jsonify([
            {
                'id': j.id,
                'user_id': j.user_id,
                'collection_id': j.collection_id,
                'environment_id': j.environment_id,
                'frequency': j.frequency,
                'cron': j.cron,
                'last_run': j.last_run.isoformat() if j.last_run else None,
                'created_at': j.created_at.isoformat() if j.created_at else None
            } for j in jobs
        ])
    else:
        data = request.json
        collection_id = data.get('collection_id')
        environment_id = data.get('environment_id')
        frequency = data.get('frequency')
        cron = data.get('cron')
        job = ScheduledJob(
            user_id=current_user.id if current_user.is_authenticated else None,
            collection_id=collection_id,
            environment_id=environment_id,
            frequency=frequency,
            cron=cron
        )
        db.session.add(job)
        db.session.commit()

        # Schedule the job
        if frequency == 'custom' and cron:
            trigger = CronTrigger.from_crontab(cron)
        else:
            trigger = frequency  # e.g., 'interval', 'date', etc. (should be validated)

        scheduler.add_job(
            run_scheduled_job,
            trigger=trigger,
            args=[job.id],
            id=f'scheduled_job_{job.id}',
            replace_existing=True
        )
        return jsonify({'id': job.id})

def run_scheduled_job(job_id):
    try:
        job = ScheduledJob.query.get(job_id)
        if not job:
            logger.error(f"Scheduled job {job_id} not found.")
            return
        collection = Collection.query.get(job.collection_id)
        environment = Environment.query.get(job.environment_id)
        if not collection or not environment:
            logger.error(f"Collection or environment not found for job {job_id}")
            return
        # Assume collection.data is JSON string
        collection_data = json.loads(collection.data) if collection.data else {}
        for request_obj in collection_data.get('requests', []):
            processed_request = process_request_with_environment(request_obj, environment)
            send_request(processed_request)
        job.last_run = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        logger.error(f"Error running scheduled job {job_id}: {str(e)}")

@app.route('/send-request', methods=['POST'])
def send_request():
    try:
        data = request.json
        method = data.get('method', 'GET').upper()
        url = data.get('url', '').strip()
        headers = data.get('headers', {})
        body = data.get('body')

        # Input validation
        if not url:
            return jsonify({"error": "URL is required"}), 400

        if not validate_url(url):
            return jsonify({"error": "Invalid URL format"}), 400

        if method not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']:
            return jsonify({"error": "Invalid HTTP method"}), 400

        # Validate headers JSON
        if not isinstance(headers, dict):
            return jsonify({"error": "Headers must be a valid JSON object"}), 400

        # Sanitize headers but preserve content-type and other important headers
        content_type = headers.get('content-type', '')
        origin = headers.get('origin', '')
        referer = headers.get('referer', '')
        headers = sanitize_headers(headers)
        
        # Restore important headers
        if content_type:
            headers['content-type'] = content_type
        if origin:
            headers['origin'] = origin
        if referer:
            headers['referer'] = referer

        # Handle form-urlencoded data
        if body and 'application/x-www-form-urlencoded' in content_type.lower():
            form_data = parse_form_data(body)
            body = urlencode(form_data, doseq=True)
            logger.info(f"Form data: {form_data}")

        # Make the request
        logger.info(f"Making {method} request to {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Body: {body}")

        session = requests.Session()
        response = session.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=30,
            verify=True,
            allow_redirects=True
        )

        # Prepare response
        response_data = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.text,
            "timestamp": datetime.utcnow().isoformat(),
            "request_time": response.elapsed.total_seconds()
        }

        # Try to parse JSON response
        try:
            response_data["body"] = response.json()
            response_data["is_json"] = True
        except:
            response_data["is_json"] = False

        return jsonify(response_data)

    except RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({
            "error": f"Request failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "error": f"An unexpected error occurred: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }), 500

@app.route('/test-google-ai', methods=['GET'])
def test_google_ai():
    """Test Google AI configuration"""
    try:
        api_key = os.getenv('GOOGLE_API_KEY')
        model_name = os.getenv('GOOGLE_API_MODEL', 'gemini-2.0-flash-exp')
        
        if not api_key:
            return jsonify({'success': False, 'error': 'GOOGLE_API_KEY not configured'})
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        response = model.generate_content("Say 'Hello, AI is working!' in JSON format: {\"message\": \"...\"}")
        
        return jsonify({
            'success': True,
            'model': model_name,
            'response': response.text,
            'message': 'Google AI is configured correctly'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

@app.route('/generate-api-tests', methods=['POST'])
def generate_api_tests():
    """Generate AI-powered test scenarios for API requests"""
    try:
        data = request.get_json()
        request_type = data.get('type', 'REST')
        
        # Build context for AI
        if request_type == 'REST':
            method = data.get('method', 'GET')
            url = data.get('url', '')
            body = data.get('body', '')
            headers = data.get('headers', [])
            
            context = f"""Analyze this REST API request and generate comprehensive test scenarios:

Method: {method}
URL: {url}
Headers: {json.dumps(headers, indent=2)}
Body: {body}

Generate test scenarios covering:
1. Happy path (successful request)
2. Edge cases (boundary values, empty data)
3. Validation tests (invalid data, missing required fields)
4. Error handling (4xx, 5xx responses)
5. Security tests (authentication, authorization)
"""
        else:  # GraphQL
            url = data.get('url', '')
            query = data.get('query', '')
            variables = data.get('variables', '')
            headers = data.get('headers', [])
            
            context = f"""Analyze this GraphQL request and generate comprehensive test scenarios:

Endpoint: {url}
Query: {query}
Variables: {variables}
Headers: {json.dumps(headers, indent=2)}

Generate test scenarios covering:
1. Happy path (successful query)
2. Edge cases (null values, empty arrays)
3. Validation tests (invalid field names, wrong types)
4. Error handling (query errors, resolver errors)
5. Performance tests (nested queries, large datasets)
"""
        
        # Generate AI-powered tests using Azure OpenAI
        result = generate_ai_tests(request_type, data)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error generating AI tests: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def generate_ai_tests(request_type, data):
    """Generate truly AI-powered test scenarios using Google Gemini AI"""
    try:
        # Configure Google AI
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        model = genai.GenerativeModel(os.getenv('GOOGLE_API_MODEL', 'gemini-2.0-flash-exp'))
        
        # Build the prompt for AI
        if request_type == 'REST':
            method = data.get('method', 'GET')
            url = data.get('url', '')
            body = data.get('body', '')
            headers = data.get('headers', [])
            
            # Infer functionality from URL and method
            url_parts = url.split('/')
            resource = next((part for part in reversed(url_parts) if part and not part.startswith('v')), 'resource')
            
            if method == 'POST':
                functionality = f"Creates a new {resource}"
            elif method == 'GET':
                functionality = f"Fetches {resource} details"
            elif method == 'PUT':
                functionality = f"Updates an existing {resource}"
            elif method == 'DELETE':
                functionality = f"Deletes a {resource}"
            elif method == 'PATCH':
                functionality = f"Partially updates a {resource}"
            else:
                functionality = f"{method} operation on {resource}"
            
            # Convert headers list to dict
            headers_dict = {h['key']: h['value'] for h in headers} if headers else {}
            
            prompt = f"""You are a meticulous Senior QA Automation Engineer specializing in API testing. Your task is to analyze the API endpoint details provided below and create a comprehensive, executable test suite.

Generate 12-15 specific, executable test cases based on the provided API details. Your test suite must provide broad coverage by testing the contract, functionality, and resilience of the endpoint. This includes positive scenarios (happy path), negative scenarios (e.g., invalid data, malformed requests), specific validation rules for all input fields, edge cases, and basic security checks (e.g., authorization, basic injection).

API Endpoint Details:
Functionality: {functionality}
Method: {method}
URL: {url}
Headers: {json.dumps(headers_dict, indent=2)}
Request Body (for a successful call): {body if body else 'None'}

Instructions for Test Case Generation:
1. Comprehensive Coverage: Create a test suite with 12-15 distinct test cases covering these categories: Positive, Negative, Validation, Security, and Edge Case.
2. Dynamic Data: Where appropriate, use common test automation placeholders like {{{{$randomString}}}}, {{{{$randomEmail}}}}, {{{{$randomInt}}}}, and {{{{$isoTimestamp}}}} to represent unique data that would be generated at runtime.
3. Strict Output Format: The output must be a valid JSON array only. Do not include any markdown, code blocks, or explanatory text. The response must be pure, raw JSON that can be directly consumed by a test runner or automation framework.

Required JSON Structure for Each Test Case:
Each object in the JSON array must conform to the following structure:
{{
   "testCaseId": "string (e.g., TC001, TC002)",
   "name": "string (concise test name)",
   "description": "string (what this test validates)",
   "category": "string (Positive/Negative/Validation/Security/EdgeCase)",
   "method": "string (HTTP method)",
   "url": "string (full URL)",
   "headers": {{}},
   "requestBody": {{}},
   "expectedStatusCode": integer,
   "expectedResponseContains": {{}} (key fields expected in response)
}}

Return ONLY the JSON array. No markdown, no code blocks, no explanations."""

        else:  # GraphQL
            url = data.get('url', '')
            query = data.get('query', '')
            variables = data.get('variables', '')
            headers = data.get('headers', [])
            
            # Determine operation type and name
            query_lower = query.lower().strip()
            if query_lower.startswith('mutation'):
                operation_type = 'mutation'
                functionality = "Executes a GraphQL mutation to modify data"
            elif query_lower.startswith('subscription'):
                operation_type = 'subscription'
                functionality = "Establishes a GraphQL subscription for real-time updates"
            else:
                operation_type = 'query'
                functionality = "Executes a GraphQL query to fetch data"
            
            # Convert headers list to dict
            headers_dict = {h['key']: h['value'] for h in headers} if headers else {}
            
            prompt = f"""You are a meticulous Senior QA Automation Engineer specializing in GraphQL API testing. Your task is to analyze the GraphQL endpoint details provided below and create a comprehensive, executable test suite.

Generate 12-15 specific, executable test cases based on the provided GraphQL API details. Your test suite must provide broad coverage by testing the contract, functionality, and resilience of the endpoint. This includes positive scenarios (happy path), negative scenarios (e.g., invalid fields, malformed queries), specific validation rules for all input variables, edge cases, and basic security checks (e.g., authorization, query depth limits, introspection).

GraphQL API Endpoint Details:
Functionality: {functionality}
Operation Type: {operation_type}
Endpoint URL: {url}
Query/Mutation: {query}
Variables: {variables if variables else 'None'}
Headers: {json.dumps(headers_dict, indent=2)}

Instructions for Test Case Generation:
1. Comprehensive Coverage: Create a test suite with 12-15 distinct test cases covering these categories: Positive, Negative, Validation, Security, and Edge Case.
2. Dynamic Data: Where appropriate, use common test automation placeholders like {{{{$randomString}}}}, {{{{$randomEmail}}}}, {{{{$randomInt}}}}, and {{{{$isoTimestamp}}}} to represent unique data that would be generated at runtime.
3. GraphQL-Specific Tests: Include tests for invalid field names, wrong argument types, missing required arguments, query depth limits, and error handling.
4. Strict Output Format: The output must be a valid JSON array only. Do not include any markdown, code blocks, or explanatory text. The response must be pure, raw JSON that can be directly consumed by a test runner or automation framework.

Required JSON Structure for Each Test Case:
Each object in the JSON array must conform to the following structure:
{{
   "testCaseId": "string (e.g., TC001, TC002)",
   "name": "string (concise test name)",
   "description": "string (what this test validates)",
   "category": "string (Positive/Negative/Validation/Security/EdgeCase)",
   "method": "POST",
   "url": "string (GraphQL endpoint URL)",
   "headers": {{}},
   "requestBody": {{
      "query": "string (GraphQL query/mutation)",
      "variables": {{}} or null
   }},
   "expectedStatusCode": integer,
   "expectedResponseContains": {{}} (key fields expected in response, e.g., {{"data": {{}}, "errors": null}})
}}

Return ONLY the JSON array. No markdown, no code blocks, no explanations."""

        # Call Google Gemini AI
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            logger.error("GOOGLE_API_KEY not configured, using fallback tests")
            return generate_fallback_tests(request_type, data)
        
        logger.info("Calling Google Gemini AI for test generation...")
        logger.info(f"Using model: {os.getenv('GOOGLE_API_MODEL', 'gemini-2.0-flash-exp')}")
        
        full_prompt = f"""You are an expert API testing engineer. Generate executable test cases as valid JSON arrays only. No markdown, no code blocks, just pure JSON.

{prompt}"""
        
        logger.info(f"Prompt length: {len(full_prompt)} characters")
        
        response = model.generate_content(full_prompt)
        
        ai_response = response.text.strip()
        logger.info(f"AI Response received, length: {len(ai_response)} characters")
        logger.info(f"AI Response preview: {ai_response[:500]}...")
        
        # Extract JSON from response (matching working pattern from line 5460)
        json_match = re.search(r'```json\n(.+?)\n```', ai_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            logger.info("Found JSON in code block")
        else:
            # Try to find JSON array directly
            json_match = re.search(r'(\[.+\])', ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                logger.info("Found JSON array in response")
            else:
                # Use the whole response
                json_str = ai_response
                logger.info("Using full response as JSON")
        
        logger.info(f"JSON string to parse: {json_str[:300]}...")
        
        # Parse JSON response
        test_cases = json.loads(json_str)
        
        if not isinstance(test_cases, list):
            logger.error(f"AI returned non-list response: {type(test_cases)}")
            return generate_fallback_tests(request_type, data)
        
        if len(test_cases) == 0:
            logger.error("AI returned empty test cases array")
            return generate_fallback_tests(request_type, data)
        
        # Return properly structured response
        result = {
            'success': True,
            'tests': test_cases,
            'type': request_type,
            'generated_at': datetime.now().isoformat(),
            'ai_powered': True
        }
        logger.info(f"Successfully generated {len(test_cases)} test cases")
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {str(e)}")
        logger.error(f"AI Response was: {ai_response if 'ai_response' in locals() else 'N/A'}")
        # Fallback to rule-based tests
        return generate_fallback_tests(request_type, data)
    except Exception as e:
        logger.error(f"Error generating AI tests: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        # Fallback to rule-based tests
        return generate_fallback_tests(request_type, data)

def generate_fallback_tests(request_type, data):
    """Generate fallback test cases when AI fails"""
    if request_type == 'REST':
        method = data.get('method', 'GET')
        url = data.get('url', '')
        body = data.get('body', '')
        headers = data.get('headers', [])
        
        tests = [
            {
                "name": "Valid Request",
                "description": "Test successful request with valid data",
                "method": method,
                "url": url,
                "headers": {h['key']: h['value'] for h in headers} if headers else {},
                "body": body,
                "expectedStatus": 200 if method == 'GET' else 201,
                "validations": ["Response is successful", "Data structure is valid"]
            },
            {
                "name": "Missing Authentication",
                "description": "Test request without authentication",
                "method": method,
                "url": url,
                "headers": {},
                "body": body,
                "expectedStatus": 401,
                "validations": ["Returns 401 Unauthorized", "Error message present"]
            },
            {
                "name": "Invalid Data",
                "description": "Test request with invalid data",
                "method": method,
                "url": url,
                "headers": {h['key']: h['value'] for h in headers} if headers else {},
                "body": "{}",
                "expectedStatus": 400,
                "validations": ["Returns 400 Bad Request", "Validation errors present"]
            }
        ]
    else:  # GraphQL
        url = data.get('url', '')
        query = data.get('query', '')
        
        tests = [
            {
                "name": "Valid Query",
                "description": "Test successful query execution",
                "url": url,
                "query": query,
                "variables": None,
                "headers": {},
                "expectedStatus": 200,
                "validations": ["No errors in response", "Data is defined"]
            },
            {
                "name": "Invalid Field",
                "description": "Test query with invalid field",
                "url": url,
                "query": "{ invalidField }",
                "variables": None,
                "headers": {},
                "expectedStatus": 200,
                "validations": ["Errors array present", "Error mentions invalid field"]
            }
        ]
    
    return {
        'success': True,
        'tests': tests,
        'type': request_type,
        'generated_at': datetime.now().isoformat(),
        'fallback': True
    }

def generate_mock_tests(request_type, data):
    """Generate intelligent test scenarios based on actual request data"""
    import re
    
    if request_type == 'REST':
        method = data.get('method', 'GET')
        url = data.get('url', '')
        body = data.get('body', '')
        headers = data.get('headers', [])
        
        # Analyze URL for patterns
        url_parts = url.split('/')
        has_id = any(re.match(r'^\d+$|^[a-f0-9-]{36}$', part) for part in url_parts)
        resource_name = next((part for part in reversed(url_parts) if part and not re.match(r'^\d+$|^[a-f0-9-]{36}$', part)), 'resource')
        
        # Parse body if JSON
        body_fields = []
        body_obj = None
        if body:
            try:
                body_obj = json.loads(body)
                if isinstance(body_obj, dict):
                    body_fields = list(body_obj.keys())
            except:
                pass
        
        # Check for auth headers
        has_auth = any(h.get('key', '').lower() in ['authorization', 'x-api-key', 'api-key'] for h in headers)
        
        tests = f"""# 🤖 AI-Generated Test Scenarios
# Endpoint: {method} {url}
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{'='*70}
## 📋 ENDPOINT ANALYSIS
{'='*70}

Resource: {resource_name}
Method: {method}
Authentication: {'✓ Detected' if has_auth else '✗ Not detected'}
Request Body: {'✓ Present' if body else '✗ None'}
"""
        
        if body_fields:
            tests += f"Body Fields: {', '.join(body_fields)}\n"
        
        tests += f"\n{'='*70}\n## 1️⃣ HAPPY PATH TESTS\n{'='*70}\n\n"
        
        if method == 'GET':
            if has_id:
                tests += f"""✓ Test: Get specific {resource_name} by ID
  Request: GET {url}
  Expected: 200 OK
  Validation:
    - Response contains {resource_name} data
    - ID matches requested ID
    - All required fields present

✓ Test: Get {resource_name} with valid filters
  Request: GET {url}?limit=10&offset=0
  Expected: 200 OK
  Validation:
    - Returns array of {resource_name}s
    - Respects pagination parameters
"""
            else:
                tests += f"""✓ Test: List all {resource_name}s
  Request: GET {url}
  Expected: 200 OK
  Validation:
    - Returns array of {resource_name}s
    - Response time < 2s
    - Proper pagination metadata

✓ Test: List with filters
  Request: GET {url}?limit=10&sort=created_at
  Expected: 200 OK
  Validation:
    - Results are filtered correctly
    - Sort order is applied
"""
        
        elif method == 'POST':
            tests += f"""✓ Test: Create new {resource_name} with valid data
  Request: POST {url}
  Body: {body if body else 'Valid JSON payload'}
  Expected: 201 Created
  Validation:
    - Response contains created {resource_name}
    - ID is generated
    - Location header present
    - All fields saved correctly
"""
            
            if body_fields:
                tests += f"\n✓ Test: Create {resource_name} with all optional fields\n"
                tests += f"  Body: Include all fields: {', '.join(body_fields)}\n"
                tests += f"  Expected: 201 Created\n\n"
        
        elif method == 'PUT':
            tests += f"""✓ Test: Update existing {resource_name}
  Request: PUT {url}
  Body: {body if body else 'Updated data'}
  Expected: 200 OK
  Validation:
    - Response contains updated {resource_name}
    - Changes are persisted
    - Timestamp updated
"""
        
        elif method == 'DELETE':
            tests += f"""✓ Test: Delete existing {resource_name}
  Request: DELETE {url}
  Expected: 204 No Content or 200 OK
  Validation:
    - Resource is deleted
    - Subsequent GET returns 404
"""
        
        tests += f"\n{'='*70}\n## 2️⃣ AUTHENTICATION & AUTHORIZATION TESTS\n{'='*70}\n\n"
        
        if has_auth:
            tests += f"""✓ Test: Request without authentication
  Request: {method} {url} (no auth header)
  Expected: 401 Unauthorized
  Validation:
    - Error message: "Authentication required"
    - WWW-Authenticate header present

✓ Test: Request with invalid token
  Request: {method} {url}
  Headers: Authorization: Bearer invalid_token_xyz
  Expected: 401 Unauthorized
  Validation:
    - Error message: "Invalid token"

✓ Test: Request with expired token
  Expected: 401 Unauthorized
  Validation:
    - Error message: "Token expired"

✓ Test: Request with insufficient permissions
  Expected: 403 Forbidden
  Validation:
    - Error message: "Insufficient permissions"
"""
        else:
            tests += f"""⚠️  No authentication detected in request
  Recommended tests:
  - Verify if endpoint should be public
  - Test rate limiting
  - Test CORS headers
"""
        
        tests += f"\n{'='*70}\n## 3️⃣ VALIDATION TESTS\n{'='*70}\n\n"
        
        if method in ['POST', 'PUT', 'PATCH']:
            if body_fields:
                for field in body_fields:
                    tests += f"""✓ Test: Missing required field '{field}'
  Body: {{{', '.join(f'"{f}": "value"' for f in body_fields if f != field)}}}
  Expected: 400 Bad Request
  Validation:
    - Error message mentions '{field}'
    - Error code for missing field

"""
                
                tests += f"""✓ Test: Invalid data types
  Body: {{"""
                for i, field in enumerate(body_fields[:3]):
                    tests += f'"{field}": null' if i == 0 else f', "{field}": null'
                tests += f"""}}
  Expected: 400 Bad Request
  Validation:
    - Field-specific error messages
    - Validation error codes

✓ Test: Empty strings in required fields
  Body: {{"""
                for i, field in enumerate(body_fields[:3]):
                    tests += f'"{field}": ""' if i == 0 else f', "{field}": ""'
                tests += f"""}}
  Expected: 400 Bad Request

✓ Test: Extremely long strings (boundary test)
  Body: {{"{body_fields[0] if body_fields else 'field'}": "{'x' * 1000}..."}}
  Expected: 400 Bad Request or 413 Payload Too Large

✓ Test: Special characters and SQL injection
  Body: {{"{body_fields[0] if body_fields else 'field'}": "'; DROP TABLE users; --"}}
  Expected: 400 Bad Request
  Validation:
    - Input is sanitized
    - No SQL injection vulnerability
"""
            else:
                tests += f"""✓ Test: Malformed JSON
  Body: {{invalid json}}
  Expected: 400 Bad Request

✓ Test: Empty body
  Body: {{}}
  Expected: 400 Bad Request
"""
        
        tests += f"\n{'='*70}\n## 4️⃣ ERROR HANDLING TESTS\n{'='*70}\n\n"
        
        if has_id:
            tests += f"""✓ Test: Non-existent resource ID
  Request: {method} {url.rsplit('/', 1)[0]}/99999999
  Expected: 404 Not Found
  Validation:
    - Error message: "{resource_name} not found"
    - Proper error structure

✓ Test: Invalid ID format
  Request: {method} {url.rsplit('/', 1)[0]}/invalid-id-format
  Expected: 400 Bad Request
  Validation:
    - Error message: "Invalid ID format"
"""
        
        tests += f"""✓ Test: Duplicate resource (if applicable)
  Request: POST {url.rsplit('/', 1)[0] if has_id else url}
  Body: Duplicate unique field
  Expected: 409 Conflict
  Validation:
    - Error message indicates duplicate

✓ Test: Rate limiting
  Request: Multiple rapid requests
  Expected: 429 Too Many Requests
  Validation:
    - Retry-After header present
    - Rate limit info in response

✓ Test: Server error simulation
  Expected: 500 Internal Server Error
  Validation:
    - Graceful error message
    - No sensitive data leaked
"""
        
        tests += f"\n{'='*70}\n## 5️⃣ PERFORMANCE & LOAD TESTS\n{'='*70}\n\n"
        
        tests += f"""✓ Test: Response time under normal load
  Expected: < 500ms for simple queries
  Expected: < 2s for complex queries

✓ Test: Concurrent requests
  Scenario: 100 concurrent {method} requests
  Expected: All succeed without errors
  Validation:
    - No race conditions
    - Data consistency maintained

✓ Test: Large payload handling
  Body: Large JSON (1MB+)
  Expected: Handles gracefully or returns 413
"""
        
        tests += f"\n{'='*70}\n## 6️⃣ SECURITY TESTS\n{'='*70}\n\n"
        
        tests += f"""✓ Test: XSS prevention
  Body: {{"field": "<script>alert('xss')</script>"}}
  Expected: Input sanitized or rejected

✓ Test: HTTPS enforcement
  Request: HTTP instead of HTTPS
  Expected: Redirect to HTTPS or reject

✓ Test: CORS headers
  Origin: https://malicious-site.com
  Expected: Proper CORS policy enforced

✓ Test: Content-Type validation
  Headers: Content-Type: text/plain
  Expected: 415 Unsupported Media Type
"""
        
        tests += f"\n{'='*70}\n## 📝 SAMPLE TEST CODE (JavaScript/Jest)\n{'='*70}\n\n"
        
        tests += f"""describe('{method} {url}', () => {{
  const baseURL = '{url}';
  const validPayload = {body if body else '{}'};
  
  describe('Happy Path', () => {{
    test('should return success with valid request', async () => {{
      const response = await fetch(baseURL, {{
        method: '{method}',
        headers: {{
          'Content-Type': 'application/json',"""
        
        if has_auth:
            tests += """
          'Authorization': 'Bearer valid_token_here'"""
        
        tests += f"""
        }},"""
        
        if method in ['POST', 'PUT', 'PATCH']:
            tests += """
        body: JSON.stringify(validPayload)"""
        
        tests += f"""
      }});
      
      expect(response.status).toBe({200 if method != 'POST' else 201});
      const data = await response.json();
      expect(data).toBeDefined();
"""
        
        if body_fields:
            for field in body_fields[:3]:
                tests += f"      expect(data.{field}).toBeDefined();\n"
        
        tests += """    });
  });
  
  describe('Validation', () => {{"""
        
        if method in ['POST', 'PUT', 'PATCH'] and body_fields:
            tests += f"""
    test('should reject missing required fields', async () => {{
      const invalidPayload = {{}};
      const response = await fetch(baseURL, {{
        method: '{method}',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(invalidPayload)
      }});
      
      expect(response.status).toBe(400);
      const error = await response.json();
      expect(error.message).toBeDefined();
    }});
"""
        
        tests += """  });
  
  describe('Authentication', () => {{"""
        
        if has_auth:
            tests += f"""
    test('should reject request without auth', async () => {{
      const response = await fetch(baseURL, {{
        method: '{method}'
      }});
      
      expect(response.status).toBe(401);
    }});
"""
        
        tests += """  });
  
  describe('Error Handling', () => {{"""
        
        if has_id:
            tests += f"""
    test('should return 404 for non-existent resource', async () => {{
      const response = await fetch(baseURL.replace(/\\/\\d+$/, '/99999999'), {{
        method: '{method}'
      }});
      
      expect(response.status).toBe(404);
    }});
"""
        
        tests += """  });
});
"""
        
        return tests
    
    else:  # GraphQL
        url = data.get('url', '')
        query = data.get('query', '')
        variables = data.get('variables', '')
        
        # Parse GraphQL query
        query_type = 'query'
        if query.strip().startswith('mutation'):
            query_type = 'mutation'
        elif query.strip().startswith('subscription'):
            query_type = 'subscription'
        
        # Extract field names
        fields = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\(|{)', query)
        operation_name = fields[0] if fields else 'operation'
        
        tests = f"""# 🤖 AI-Generated GraphQL Test Scenarios
# Endpoint: {url}
# Operation: {query_type} - {operation_name}
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{'='*70}
## 📋 QUERY ANALYSIS
{'='*70}

Type: {query_type.upper()}
Operation: {operation_name}
Fields: {', '.join(fields[1:5]) if len(fields) > 1 else 'N/A'}
Variables: {'✓ Present' if variables else '✗ None'}

{'='*70}
## 1️⃣ HAPPY PATH TESTS
{'='*70}

✓ Test: Execute {query_type} successfully
  Query: {query[:100]}...
  Variables: {variables if variables else 'None'}
  Expected: 200 OK with data
  Validation:
    - data.{operation_name} is defined
    - No errors in response
    - All requested fields present

✓ Test: Query with all optional parameters
  Expected: 200 OK
  Validation:
    - Optional fields handled correctly
    - Null values handled gracefully

{'='*70}
## 2️⃣ VALIDATION TESTS
{'='*70}

✓ Test: Invalid field name
  Query: {{ invalidField }}
  Expected: GraphQL validation error
  Validation:
    - errors array present
    - Error message: "Cannot query field 'invalidField'"

✓ Test: Wrong argument type
  Variables: {{ "id": "not-a-number" }}
  Expected: Variable type mismatch error

✓ Test: Missing required arguments
  Query: Remove required arguments
  Expected: Validation error
  Validation:
    - Error indicates missing argument

✓ Test: Malformed query syntax
  Query: {{ {operation_name} {{ }}
  Expected: Syntax error
  Validation:
    - Clear syntax error message

{'='*70}
## 3️⃣ EDGE CASES
{'='*70}

✓ Test: Null values in variables
  Variables: {{ "input": null }}
  Expected: Handled gracefully or validation error

✓ Test: Empty arrays
  Variables: {{ "ids": [] }}
  Expected: Returns empty result set

✓ Test: Very large result set
  Arguments: {{ limit: 10000 }}
  Expected: Pagination enforced or limit applied

✓ Test: Deeply nested query (10+ levels)
  Expected: Query depth limit enforced

{'='*70}
## 4️⃣ ERROR HANDLING
{'='*70}

✓ Test: Non-existent resource
  Variables: {{ "id": "99999999" }}
  Expected: null data or error
  Validation:
    - Graceful error message
    - Partial data if applicable

✓ Test: Resolver error
  Expected: errors array with resolver error
  Validation:
    - Error path indicates field
    - Partial data returned if possible

✓ Test: Network timeout
  Expected: Timeout error after 30s

{'='*70}
## 5️⃣ PERFORMANCE TESTS
{'='*70}

✓ Test: Query complexity
  Expected: < 1s for simple queries
  Expected: < 5s for complex queries

✓ Test: N+1 query detection
  Query: List with nested relations
  Validation:
    - DataLoader or batching used
    - Reasonable number of DB queries

✓ Test: Concurrent queries
  Scenario: 50 concurrent identical queries
  Expected: All succeed
  Validation:
    - Caching works correctly

{'='*70}
## 6️⃣ SECURITY TESTS
{'='*70}

✓ Test: Query depth limit
  Query: 20 levels deep
  Expected: Rejected with depth limit error

✓ Test: Query complexity limit
  Query: Extremely complex with many fields
  Expected: Rejected with complexity error

✓ Test: Introspection in production
  Query: __schema {{ types {{ name }} }}
  Expected: Disabled in production

{'='*70}
## 📝 SAMPLE TEST CODE (JavaScript/Jest)
{'='*70}

describe('GraphQL {query_type}: {operation_name}', () => {{
  const endpoint = '{url}';
  const query = `{query}`;
  
  describe('Happy Path', () => {{
    test('should execute {query_type} successfully', async () => {{
      const response = await fetch(endpoint, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          query,
          variables: {variables if variables else '{}'}
        }})
      }});
      
      const {{ data, errors }} = await response.json();
      
      expect(errors).toBeUndefined();
      expect(data).toBeDefined();
      expect(data.{operation_name}).toBeDefined();
    }});
  }});
  
  describe('Validation', () => {{
    test('should reject invalid field', async () => {{
      const invalidQuery = `{{ invalidField }}`;
      const response = await fetch(endpoint, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ query: invalidQuery }})
      }});
      
      const {{ errors }} = await response.json();
      expect(errors).toBeDefined();
      expect(errors[0].message).toContain('Cannot query field');
    }});
  }});
  
  describe('Error Handling', () => {{
    test('should handle non-existent resource', async () => {{
      const variables = {{ id: '99999999' }};
      const response = await fetch(endpoint, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ query, variables }})
      }});
      
      const {{ data, errors }} = await response.json();
      expect(data.{operation_name}).toBeNull();
    }});
  }});
}});
"""
        
        return tests
    
    return tests

@app.route('/convert_collection', methods=['POST'])
def convert_collection():
    mode = request.form.get('mode', 'deterministic')
    if 'collection' not in request.files:
        return 'No file uploaded', 400
    file = request.files['collection']
    try:
        collection = json.load(file)
    except Exception as e:
        return f'Invalid JSON: {e}', 400

    if mode == 'upgrad':
        # Upgrad Context: Use Upgrad project utilities
        import re
        items = extract_requests(collection.get('item', []))
        variable_setup = [
            '        String firstName = RandomGenerator.randomfirstname();',
            '        String lastName = RandomGenerator.randomlastname();',
            '        String email = RandomGenerator.randomEmail();',
            '        String phone = "9" + (long)(Math.random() * 1_000_000_000L);',
            '        String password = "password";'
        ]
        variable_map = {
            'first_name': 'firstName',
            'last_name': 'lastName',
            'user_email_OMS': 'email',
            'phone_number': 'phone',
            'password': 'password',
        }
        scenario_steps = []
        property_writes = []
        last_response_var = None
        for idx, item in enumerate(items):
            req = item.get('request', {})
            step_lines = []
            payload_decl = ''
            method = req.get('method', 'GET').upper()
            # --- Build payload using JSONObject ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                try:
                    import json as pyjson
                    body_dict = pyjson.loads(req['body']['raw'])
                except Exception:
                    body_dict = None
                if body_dict:
                    step_lines.append('        JSONObject payload = new JSONObject();')
                    for k, v in body_dict.items():
                        m = re.match(r'{{(.+?)}}', str(v))
                        if m and m.group(1) in variable_map:
                            step_lines.append(f'        payload.put("{k}", {variable_map[m.group(1)]});')
                        else:
                            if isinstance(v, str):
                                step_lines.append(f'        payload.put("{k}", "{v}");')
                            else:
                                step_lines.append(f'        payload.put("{k}", {v});')
                else:
                    payload = req['body']['raw']
                    for k, v in variable_map.items():
                        payload = payload.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    step_lines.append(f'        JSONObject payload = new JSONObject("{payload}");')
            elif req.get('body', {}).get('mode') == 'graphql':
                gql = req['body'].get('graphql', {})
                query = gql.get('query', '').replace('"', '\\"').replace('\n', ' ')
                variables = gql.get('variables', '').replace('"', '\\"').replace('\n', ' ')
                for k, v in variable_map.items():
                    query = query.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    variables = variables.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                step_lines.append(f'        String gqlPayload = "{{\\"query\\":\\"{query}\\",\\"variables\\":{variables}}}";')
            # --- Build request ---
            url = ''
            if isinstance(req.get('url'), dict):
                url = req['url'].get('raw') or ''
            elif isinstance(req.get('url'), str):
                url = req['url']
            for k, v in variable_map.items():
                url = url.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
            # --- Query params ---
            query_params = ''
            if isinstance(req.get('url'), dict) and req['url'].get('query'):
                for qp in req['url']['query']:
                    k = qp.get('key')
                    v = qp.get('value')
                    for vk, vv in variable_map.items():
                        v = v.replace(f"{{{{{vk}}}}}", '" + ' + vv + ' + "')
                    query_params += f'.queryParam("{k}", "{v}")\n'
            # --- URL Handling for RestAssured ---
            use_direct_url = False
            base_uri, base_path = '', ''
            if url.startswith('http'):
                from urllib.parse import urlparse
                u = urlparse(url)
                base_uri = f'{u.scheme}://{u.netloc}'
                base_path = u.path
            elif url.startswith('{{') and '}}' in url:
                # variable-based url, e.g. {{Stage_Auth_APIs}}/auth/v5/login
                var_end = url.index('}}') + 2
                base_uri = url[:var_end]
                base_path = url[var_end:]
                if base_path.startswith('/'):
                    pass
                else:
                    base_path = '/' + base_path if base_path else ''
            elif url:
                use_direct_url = True
            # --- Get a safe Java variable name from request name ---
            req_name = item.get('name', f'request{idx+1}')
            safe_req_name = re.sub(r'[^0-9a-zA-Z_]', '_', req_name.strip().replace(' ', '_'))
            response_var = f'response_{safe_req_name}'
            if use_direct_url:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
            else:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
                if base_uri:
                    step_lines.append(f'                .baseUri("{base_uri}")')
                if base_path:
                    step_lines.append(f'                .basePath("{base_path}")')
            # --- Headers ---
            header_keys = set()
            for h in req.get('header', []):
                h_val = h.get('value', '')
                for k, v in variable_map.items():
                    h_val = h_val.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                if h.get("key") not in header_keys:
                    step_lines.append(f'                .header("{h.get("key")}", "{h_val}")')
                    header_keys.add(h.get("key"))
            # --- Query Params ---
            if query_params:
                for qline in query_params.strip().split('\n'):
                    step_lines.append(f'                {qline}')
            # --- Auth (Bearer) ---
            if req.get('auth', {}).get('type') == 'bearer':
                for b in req['auth'].get('bearer', []):
                    if 'Authorization' not in header_keys:
                        step_lines.append(f'                .header("Authorization", "Bearer {b.get("value")}")')
                        header_keys.add('Authorization')
            # --- Body ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                step_lines.append('                .body(payload.toString())')
            elif req.get('body', {}).get('mode') == 'graphql':
                step_lines.append('                .body(gqlPayload)')
            # --- HTTP Method and URL ---
            if use_direct_url:
                if method == 'GET':
                    step_lines.append(f'                .get("{url}")')
                elif method == 'POST':
                    step_lines.append(f'                .post("{url}")')
                elif method == 'PUT':
                    step_lines.append(f'                .put("{url}")')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete("{url}")')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch("{url}")')
                else:
                    step_lines.append(f'                .request("{method}", "{url}")')
            else:
                if method == 'GET':
                    step_lines.append(f'                .get()')
                elif method == 'POST':
                    step_lines.append(f'                .post()')
                elif method == 'PUT':
                    step_lines.append(f'                .put()')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete()')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch()')
                else:
                    step_lines.append(f'                .request("{method}")')
            step_lines.append(f'        ;')
            step_lines.append(f'        if ({response_var}.statusCode() != 200) {{')
            step_lines.append(f'            throw new RuntimeException("Request failed: " + {response_var}.asString());')
            step_lines.append('        }')
            # --- Extract variables from response (test script) ---
            for event in item.get('event', []):
                if event.get('listen') == 'test':
                    script = '\n'.join(event['script'].get('exec', []))
                    m = re.search(r'pm\\.environment\\.set\\([\"\'](\\w+)[\"\'],\\s*jsondata\\.(\\w+)\\)', script)
                    if m:
                        varname, respfield = m.group(1), m.group(2)
                        variable_map[varname] = varname
                        step_lines.append(f'        String {varname} = {response_var}.jsonPath().getString("{respfield}");')
            if idx == len(items)-1:
                property_writes.append('        try {')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "FIRSTNAME", firstName);')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "LASTNAME", lastName);')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "PHONE", phone);')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "USERNAME", email);')
                property_writes.append('            System.out.println("[JAVA] USERNAME property written to: src/test/resources/TestData/Prism/PrismTestData.properties");')
                property_writes.append('        } catch (Exception e) { e.printStackTrace(); }')
            scenario_steps.extend(step_lines)
        class_code = (
            'import io.restassured.RestAssured;\n'
            'import io.restassured.response.Response;\n'
            'import org.json.JSONObject;\n'
            'import org.junit.Test;\n'
            'import static io.restassured.RestAssured.*;\n'
            'import static org.hamcrest.Matchers.*;\n'
            'import java.time.LocalDateTime;\n'
            'import java.time.format.DateTimeFormatter;\n'
            'import com.Upgrad.CommonLibrary.utilities.RandomGenerator;\n'
            'import com.Upgrad.CommonLibrary.utilities.PropertyHandler;\n'
            'public class RestAssuredTests {\n'
            '    @Test\n'
            '    public void scenario() throws Exception {\n'
            + ('\n'.join(variable_setup) + '\n' if variable_setup else '')
            + '\n'.join(scenario_steps) + '\n'
            + ('\n'.join(property_writes) + '\n' if property_writes else '')
            + '    }\n'
            + '}'
        )
        collection_name = collection.get('info', {}).get('name', 'RestAssuredTests')
        safe_collection_name = re.sub(r'[^0-9a-zA-Z_]', '_', collection_name.strip().replace(' ', '_'))
        java_filename = f"{safe_collection_name}.java"
        fd, path = tempfile.mkstemp(suffix='.java')
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.write(class_code)
        return send_file(path, as_attachment=True, download_name=java_filename, mimetype='text/x-java-source')
    elif mode == 'general':
        # General Purpose: Use only standard Java and open-source libraries
        import re
        items = extract_requests(collection.get('item', []))
        variable_setup = [
            '        DateTimeFormatter dtf = DateTimeFormatter.ofPattern("ssmmddMMyy");',
            '        String uniqueNumber = LocalDateTime.now().format(dtf);',
            '        String firstName = "Auto" + uniqueNumber;',
            '        String lastName = "User" + uniqueNumber;',
            '        String email = firstName + lastName + "@mailinator.com";',
            '        String phone = "9" + (long)(Math.random() * 1_000_000_000L);',
            '        String password = "password";'
        ]
        variable_map = {
            'first_name': 'firstName',
            'last_name': 'lastName',
            'user_email_OMS': 'email',
            'phone_number': 'phone',
            'password': 'password',
        }
        scenario_steps = []
        property_writes = []
        last_response_var = None
        for idx, item in enumerate(items):
            req = item.get('request', {})
            step_lines = []
            payload_decl = ''
            method = req.get('method', 'GET').upper()
            # --- Build payload using JSONObject ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                try:
                    import json as pyjson
                    body_dict = pyjson.loads(req['body']['raw'])
                except Exception:
                    body_dict = None
                if body_dict:
                    step_lines.append('        JSONObject payload = new JSONObject();')
                    for k, v in body_dict.items():
                        m = re.match(r'{{(.+?)}}', str(v))
                        if m and m.group(1) in variable_map:
                            step_lines.append(f'        payload.put("{k}", {variable_map[m.group(1)]});')
                        else:
                            if isinstance(v, str):
                                step_lines.append(f'        payload.put("{k}", "{v}");')
                            else:
                                step_lines.append(f'        payload.put("{k}", {v});')
                else:
                    payload = req['body']['raw']
                    for k, v in variable_map.items():
                        payload = payload.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    step_lines.append(f'        JSONObject payload = new JSONObject("{payload}");')
            elif req.get('body', {}).get('mode') == 'graphql':
                gql = req['body'].get('graphql', {})
                query = gql.get('query', '').replace('"', '\\"').replace('\n', ' ')
                variables = gql.get('variables', '').replace('"', '\\"').replace('\n', ' ')
                for k, v in variable_map.items():
                    query = query.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    variables = variables.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                step_lines.append(f'        String gqlPayload = "{{\\"query\\":\\"{query}\\",\\"variables\\":{variables}}}";')
            # --- Build request ---
            url = ''
            if isinstance(req.get('url'), dict):
                url = req['url'].get('raw') or ''
            elif isinstance(req.get('url'), str):
                url = req['url']
            for k, v in variable_map.items():
                url = url.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
            # --- Query params ---
            query_params = ''
            if isinstance(req.get('url'), dict) and req['url'].get('query'):
                for qp in req['url']['query']:
                    k = qp.get('key')
                    v = qp.get('value')
                    for vk, vv in variable_map.items():
                        v = v.replace(f"{{{{{vk}}}}}", '" + ' + vv + ' + "')
                    query_params += f'.queryParam("{k}", "{v}")\n'
            # --- URL Handling for RestAssured ---
            use_direct_url = False
            base_uri, base_path = '', ''
            if url.startswith('http'):
                from urllib.parse import urlparse
                u = urlparse(url)
                base_uri = f'{u.scheme}://{u.netloc}'
                base_path = u.path
            elif url.startswith('{{') and '}}' in url:
                # variable-based url, e.g. {{Stage_Auth_APIs}}/auth/v5/login
                var_end = url.index('}}') + 2
                base_uri = url[:var_end]
                base_path = url[var_end:]
                if base_path.startswith('/'):
                    pass
                else:
                    base_path = '/' + base_path if base_path else ''
            elif url:
                use_direct_url = True
            # --- Get a safe Java variable name from request name ---
            req_name = item.get('name', f'request{idx+1}')
            safe_req_name = re.sub(r'[^0-9a-zA-Z_]', '_', req_name.strip().replace(' ', '_'))
            response_var = f'response_{safe_req_name}'
            if use_direct_url:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
            else:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
                if base_uri:
                    step_lines.append(f'                .baseUri("{base_uri}")')
                if base_path:
                    step_lines.append(f'                .basePath("{base_path}")')
            # --- Headers ---
            header_keys = set()
            for h in req.get('header', []):
                h_val = h.get('value', '')
                for k, v in variable_map.items():
                    h_val = h_val.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                if h.get("key") not in header_keys:
                    step_lines.append(f'                .header("{h.get("key")}", "{h_val}")')
                    header_keys.add(h.get("key"))
            # --- Query Params ---
            if query_params:
                for qline in query_params.strip().split('\n'):
                    step_lines.append(f'                {qline}')
            # --- Auth (Bearer) ---
            if req.get('auth', {}).get('type') == 'bearer':
                for b in req['auth'].get('bearer', []):
                    if 'Authorization' not in header_keys:
                        step_lines.append(f'                .header("Authorization", "Bearer {b.get("value")}")')
                        header_keys.add('Authorization')
            # --- Body ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                step_lines.append('                .body(payload.toString())')
            elif req.get('body', {}).get('mode') == 'graphql':
                step_lines.append('                .body(gqlPayload)')
            # --- HTTP Method and URL ---
            if use_direct_url:
                if method == 'GET':
                    step_lines.append(f'                .get("{url}")')
                elif method == 'POST':
                    step_lines.append(f'                .post("{url}")')
                elif method == 'PUT':
                    step_lines.append(f'                .put("{url}")')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete("{url}")')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch("{url}")')
                else:
                    step_lines.append(f'                .request("{method}", "{url}")')
            else:
                if method == 'GET':
                    step_lines.append(f'                .get()')
                elif method == 'POST':
                    step_lines.append(f'                .post()')
                elif method == 'PUT':
                    step_lines.append(f'                .put()')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete()')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch()')
                else:
                    step_lines.append(f'                .request("{method}")')
            step_lines.append(f'        ;')
            step_lines.append(f'        if ({response_var}.statusCode() != 200) {{')
            step_lines.append(f'            throw new RuntimeException("Request failed: " + {response_var}.asString());')
            step_lines.append('        }')
            for event in item.get('event', []):
                if event.get('listen') == 'test':
                    script = '\n'.join(event['script'].get('exec', []))
                    m = re.search(r'pm\\.environment\\.set\\([\"\'](\\w+)[\"\'],\\s*jsondata\\.(\\w+)\\)', script)
                    if m:
                        varname, respfield = m.group(1), m.group(2)
                        variable_map[varname] = varname
                        step_lines.append(f'        String {varname} = {response_var}.jsonPath().getString("{respfield}");')
            if idx == len(items)-1:
                property_writes.append('        try {')
                property_writes.append('            Properties props = new Properties();')
                property_writes.append('            File file = new File("src/test/resources/TestData/Prism/PrismTestData.properties");')
                property_writes.append('            if (file.exists()) {')
                property_writes.append('                try (FileInputStream fis = new FileInputStream(file)) {')
                property_writes.append('                    props.load(fis);')
                property_writes.append('                }')
                property_writes.append('            }')
                property_writes.append('            props.setProperty("FIRSTNAME", firstName);')
                property_writes.append('            props.setProperty("LASTNAME", lastName);')
                property_writes.append('            props.setProperty("PHONE", phone);')
                property_writes.append('            props.setProperty("USERNAME", email);')
                property_writes.append('            try (FileOutputStream fos = new FileOutputStream(file)) {')
                property_writes.append('                props.store(fos, "Updated by SelfPacedLearnerEnrollmentHook");')
                property_writes.append('            }')
                property_writes.append('            System.out.println("[JAVA] USERNAME property written to: " + file.getAbsolutePath());')
                property_writes.append('        } catch (Exception e) { e.printStackTrace(); }')
            scenario_steps.extend(step_lines)
        class_code = (
            'import io.restassured.RestAssured;\n'
            'import io.restassured.response.Response;\n'
            'import org.json.JSONObject;\n'
            'import org.junit.Test;\n'
            'import static io.restassured.RestAssured.*;\n'
            'import static org.hamcrest.Matchers.*;\n'
            'import java.time.LocalDateTime;\n'
            'import java.time.format.DateTimeFormatter;\n'
            'import java.io.*;\n'
            'import java.util.Properties;\n'
            'public class RestAssuredTests {\n'
            '    @Test\n'
            '    public void scenario() throws Exception {\n'
            + ('\n'.join(variable_setup) + '\n' if variable_setup else '')
            + '\n'.join(scenario_steps) + '\n'
            + ('\n'.join(property_writes) + '\n' if property_writes else '')
            + '    }\n'
            + '}'
        )
        collection_name = collection.get('info', {}).get('name', 'RestAssuredTests')
        safe_collection_name = re.sub(r'[^0-9a-zA-Z_]', '_', collection_name.strip().replace(' ', '_'))
        java_filename = f"{safe_collection_name}.java"
        fd, path = tempfile.mkstemp(suffix='.java')
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.write(class_code)
        return send_file(path, as_attachment=True, download_name=java_filename, mimetype='text/x-java-source')
    else:
        return 'AI mode not implemented yet', 400

@app.route('/proxy')
def proxy():
    """
    Acts as a proxy for external websites to bypass X-Frame-Options restrictions.
    """
    url = request.args.get('url')
    if not url:
        return "Missing URL parameter", 400
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    try:
        # Fetch the target website
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        content_type = response.headers.get('Content-Type', 'text/html')
        
        # Process the HTML content to fix relative URLs
        if 'text/html' in content_type:
            html = response.text
            
            # Fix relative URLs for images, scripts, stylesheets, etc.
            parsed_url = urlparse(url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            # Fix relative URLs in src and href attributes
            html = re.sub(r'(src|href)=[\'"](?!http)([^\'"]+)[\'"]', 
                         lambda m: f'{m.group(1)}="{urljoin(base_url, m.group(2))}"', 
                         html)
            
            # Add our recording script
            inject_script = """
            <script>
            // UI Recording script will be injected here
            console.log('UI Recorder proxy is active on this page');
            
            // Connect back to parent window for recording events
            window.addEventListener('click', function(e) {
                window.parent.postMessage({
                    type: 'recorder_event',
                    eventType: 'click',
                    selector: e.target.tagName.toLowerCase(),
                    innerText: e.target.innerText
                }, '*');
            }, true);
            
            // More event listeners could be added here
            </script>
            """
            html = html.replace('</body>', inject_script + '</body>')
            
            return html
        else:
            # For non-HTML content, just pass it through
            return response.content, 200, {'Content-Type': content_type}
            
    except Exception as e:
        return f"Error proxying content: {str(e)}", 500

@app.route('/direct-recorder')
def direct_recorder():
    """
    An alternative recorder that uses a bookmarklet approach
    to handle websites with X-Frame-Options restrictions.
    """
    # Create a much simpler bookmarklet
    bookmarklet_code = """
    (function(){
      // Create UI
      var d = document.createElement('div');
      d.style.position = 'fixed';
      d.style.top = '0';
      d.style.right = '0';
      d.style.zIndex = '9999999';
      d.style.background = 'red';
      d.style.color = 'white';
      d.style.padding = '10px';
      d.innerHTML = '🔴 Recording';
      document.body.appendChild(d);
      
      // Store actions
      var acts = [];
      
      // Record navigation
      acts.push({type:'nav', url:location.href});
      
      // Record clicks
      document.addEventListener('click', function(e){
        var t = e.target;
        var s = t.id ? '#'+t.id : t.tagName;
        acts.push({type:'click', sel:s, txt:t.innerText});
        d.innerHTML = '🔴 Click recorded';
        setTimeout(function(){d.innerHTML='🔴 Recording';}, 1000);
      }, true);
      
      // Stop button
      var b = document.createElement('button');
      b.innerHTML = 'Stop';
      b.style.marginLeft = '10px';
      b.onclick = function(){
        var w = window.open();
        w.document.write('<h1>Recorded Actions</h1><pre>'+JSON.stringify(acts,null,2)+'</pre>');
        w.document.write('<h1>Java Code</h1><pre>'+genCode(acts)+'</pre>');
        document.body.removeChild(d);
      };
      d.appendChild(b);
      
      // Generate code
      function genCode(a){
        var c = 'import org.openqa.selenium.*;\n';
        c += 'import org.openqa.selenium.chrome.ChromeDriver;\n\n';
        c += 'public class UiTest {\n';
        c += '    public static void main(String[] args) {\n';
        c += '        WebDriver driver = new ChromeDriver();\n';
        
        a.forEach(function(x){
          if(x.type == 'nav') {
            c += '        driver.get("'+x.url+'");\n';
          } else if(x.type == 'click') {
            c += '        driver.findElement(By.cssSelector("'+x.sel+'")).click();\n';
          }
        });
        
        c += '        driver.quit();\n';
        c += '    }\n';
        c += '}';
        return c;
      }
    })();
    """
    
    # Clean up the code
    bookmarklet_code = "javascript:" + bookmarklet_code.replace('\n', '').replace('    ', '').replace('  ', '')
    
    # return render_template('direct-recorder.html', bookmarklet=bookmarklet_code)  # Template missing
    return redirect('/static/record.html')  # Redirect to static recorder instead

@app.route('/simple-recorder')
def simple_recorder():
    """
    Redirect to the static recorder page that has a guaranteed working bookmarklet
    """
    return redirect('/static/record.html')

# @app.route('/selenium-recorder')
# def selenium_recorder():
#     return render_template('selenium-recorder.html')  # Template missing

# @app.route('/download-extension')
# def download_extension():
#     return render_template('download_extension.html')  # Template missing

@app.route('/dom-extractor')
def dom_extractor():
    return render_template('dom-extractor.html', active_tab='ui')

@app.route('/upload-session', methods=['POST'])
def upload_session():
    file = request.files.get('sessionfile')
    if not file:
        return 'No file uploaded.', 400
    # Save the uploaded file to a directory (e.g., uploads/)
    import os
    upload_dir = os.path.join(os.path.dirname(__file__), 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, file.filename)
    file.save(filepath)
    return f'Session uploaded successfully as {file.filename}!'

@app.route('/convert_curl', methods=['POST'])
def convert_curl():
    """
    Convert a curl command to Java RestAssured code
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        curl_command = data.get('curl')
        mode = data.get('mode', 'general')
        
        if not curl_command:
            return jsonify({"error": "No curl command provided"}), 400
        
        # Parse the curl command
        parsed_curl = parse_curl_command(curl_command)
        
        # Generate Java code based on mode
        if mode == 'upgrad':
            java_code = generate_upgrad_java_code(parsed_curl)
        else:  # general or any other mode
            java_code = generate_general_java_code(parsed_curl)
            
        # If requested as file download
        if data.get('download'):
            # Extract endpoint name from URL for naming
            url_parts = parsed_curl['url'].split('/')
            endpoint = url_parts[-1] if url_parts[-1] else 'endpoint'
            class_name = 'Test' + endpoint.capitalize().replace('-', '_')
            
            fd, path = tempfile.mkstemp(suffix='.java')
            with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
                tmp.write(java_code)
            return send_file(path, as_attachment=True, download_name=f"{class_name}.java", mimetype='text/x-java-source')
        
        # Otherwise return as JSON
        return jsonify({"code": java_code})
        
    except Exception as e:
        logger.error(f"Error converting curl: {str(e)}")
        return jsonify({"error": str(e)}), 500

def parse_curl_command(curl):
    """
    Parse a curl command into its components
    """
    result = {
        'method': 'GET',
        'url': '',
        'headers': {},
        'body': '',
        'content_type': 'application/json'
    }
    
    # Extract URL - looking for the first URL-like string
    url_match = re.search(r'https?://[^\s\'"]+', curl)
    if url_match:
        result['url'] = url_match.group(0).strip('"\'')
    
    # Extract method
    method_match = re.search(r'-X\s+([A-Z]+)', curl)
    if method_match:
        result['method'] = method_match.group(1)
    
    # Extract headers
    header_matches = re.finditer(r'-H\s+[\'"]([^:]+):\s*([^\'"]+)[\'"]', curl)
    for match in header_matches:
        header_name = match.group(1).strip()
        header_value = match.group(2).strip()
        result['headers'][header_name] = header_value
        
        # Check for content type
        if header_name.lower() == 'content-type':
            result['content_type'] = header_value
    
    # Extract body - look for -d or --data or --data-raw (handle multi-line)
    # First try to find quoted multi-line JSON
    body_patterns = [
        r'--data-raw\s+[\'"](.*?)[\'"]\s',
        r'--data\s+[\'"](.*?)[\'"]\s', 
        r'-d\s+[\'"](.*?)[\'"]\s'
    ]
    
    for pattern in body_patterns:
        body_match = re.search(pattern, curl + ' ', re.DOTALL)
        if body_match:
            body_text = body_match.group(1)
            # Clean up the body text - remove extra whitespace but preserve JSON structure
            result['body'] = body_text.strip()
            break
    
    # If method is GET but we have a body, assume it's actually POST
    if result['method'] == 'GET' and result['body']:
        result['method'] = 'POST'
    
    return result

def generate_upgrad_java_code(parsed_curl):
    """
    Generate Java code for Upgrad context using their utilities
    """
    method = parsed_curl['method']
    url = parsed_curl['url']
    headers = parsed_curl['headers']
    body = parsed_curl['body']
    content_type = parsed_curl.get('content_type', 'application/json')

    # Fix Content-Type header if needed
    fixed_headers = {}
    for k, v in headers.items():
        if k.lower() == 'content-type' and v.lower().startswith('application/json'):
            fixed_headers[k] = 'application/json'
        else:
            fixed_headers[k] = v
    headers = fixed_headers

    # Extract endpoint for naming
    url_parts = url.split('/')
    endpoint = url_parts[-1] if url_parts[-1] else 'endpoint'
    class_name = 'Test' + ''.join(word.capitalize() for word in re.sub(r'[^a-zA-Z0-9]', ' ', endpoint).split())
    
    # Start building the Java code
    java = f"""package com.upgrad.test.api;

import com.upgrad.test.base.TestBase;
import com.upgrad.test.util.PropertyHandler;
import com.upgrad.test.util.RandomGenerator;
import io.restassured.response.Response;
import org.testng.annotations.Test;
import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.*;

public class {class_name} extends TestBase {{

    @Test
    public void test{method.lower()}{endpoint.capitalize()}() {{
        // Set base URI from config
        String baseURI = PropertyHandler.getProperty("api.base.url");

        // Build request
        Response response = given()
            .spec(getRequestSpecification())
"""
    
    # Add headers
    if headers:
        java += "            // Add headers\n"
        for key, value in headers.items():
                java += f'            .header("{key}", PropertyHandler.getProperty("api.auth.token"))\n'
    
    # Add body if present
    if body:
        java += "            // Add request body\n"
        if 'json' in content_type.lower():
            try:
                # Try to parse as JSON to see if it's valid
                json_body = json.loads(body)
                java += '            .body(' + repr(json.dumps(json_body, indent=4)) + ')\n'
            except:
                # Not valid JSON, use as string
                body_escaped = body.replace('"', '\\"')
                java += f'            .body("{body_escaped}")\n'
        else:
            body_escaped = body.replace('"', '\\"')
            java += f'            .body("{body_escaped}")\n'
    
    # Add request method and path
    base_url_parts = url.split('/')[:3]  # http(s)://domain.com
    base_url = '/'.join(base_url_parts)
    path = '/' + '/'.join(url.split('/')[3:])
    
    java += f"""            // Send request
            .when()
            .{method.lower()}("{path}")
            // Process response
            .then()
            .log().all()
            .assertThat().statusCode(200)
            .extract().response();

        // Validate response
        validateResponse(response, "{endpoint}");
    }}
}}
"""
    
    return java

def generate_general_java_code(parsed_curl):
    """
    Generate general-purpose Java code using standard RestAssured
    """
    method = parsed_curl['method']
    url = parsed_curl['url']
    headers = parsed_curl['headers']
    body = parsed_curl['body']
    content_type = parsed_curl.get('content_type', 'application/json')

    # Fix Content-Type header if needed
    fixed_headers = {}
    for k, v in headers.items():
        if k.lower() == 'content-type' and v.lower().startswith('application/json'):
            fixed_headers[k] = 'application/json'
        else:
            fixed_headers[k] = v
    headers = fixed_headers

    # Extract endpoint for naming
    url_parts = url.split('/')
    endpoint = url_parts[-1] if url_parts[-1] else 'endpoint'
    class_name = 'Test' + ''.join(word.capitalize() for word in re.sub(r'[^a-zA-Z0-9]', ' ', endpoint).split())
    
    # Start building the Java code
    java_code = []
    java_code.append("import io.restassured.RestAssured;")
    java_code.append("import io.restassured.response.Response;")
    java_code.append("import io.restassured.http.ContentType;")
    java_code.append("import org.junit.Test;")
    java_code.append("import static io.restassured.RestAssured.*;")
    java_code.append("import static org.hamcrest.Matchers.*;")
    java_code.append("")
    java_code.append(f"public class {class_name} {{")
    java_code.append("")
    java_code.append(f"    @Test")
    java_code.append(f"    public void test{method.lower()}{endpoint.capitalize()}() {{")
    java_code.append(f"        // Set base URI")
    java_code.append(f"        RestAssured.baseURI = \"{'/'.join(url.split('/')[:3])}\";")
    java_code.append("")
    java_code.append(f"        // Build request")
    java_code.append(f"        Response response = given()")
    
    # Add headers
    if headers:
        java_code.append("            // Add headers")
        for key, value in headers.items():
            java_code.append(f'            .header("{key}", "{value}")')
    
    # Add body if present
    if body:
        if 'json' in content_type.lower():
            try:
                # Try to parse as JSON to see if it's valid
                json_body = json.loads(body)
                java_code.append("            // Add JSON body")
                # Use a different approach that doesn't cause syntax errors
                java_code.append('            .body(' + repr(json.dumps(json_body, indent=4)) + ')\n')
            except:
                # Not valid JSON, use as string
                java_code.append("            // Add request body")
                body_escaped = body.replace('"', '\\"')
                body_escaped = body.replace('"', '\\"')
                java_code.append(f'            .body("{body_escaped}")')
        else:
            java_code.append("            // Add request body")
            body_escaped = body.replace('"', '\\"')
            java_code.append(f'            .body("{body_escaped}")')
    
    # Add request method and path
    path = '/' + '/'.join(url.split('/')[3:])
    
    java_code.append("            // Send request")
    java_code.append("            .when()")
    java_code.append(f"            .{method.lower()}(\"{path}\")")
    java_code.append("            // Process response")
    java_code.append("            .then()")
    java_code.append("            .log().all()")
    java_code.append("            .assertThat().statusCode(200)")
    java_code.append("            .extract().response();")
    java_code.append("")
    java_code.append("        // Print response details")
    java_code.append("        System.out.println(\"Status Code: \" + response.getStatusCode());")
    java_code.append("        System.out.println(\"Response Body: \" + response.getBody().asString());")
    java_code.append("    }")
    java_code.append("}")
    
    return "\n".join(java_code)

@app.route('/convert_json', methods=['POST'])
def convert_json():
    """Convert JSON payload to Java code."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        json_str = data.get('json')
        mode = data.get('mode', 'general')
        
        if not json_str:
            return jsonify({'error': 'No JSON string provided'}), 400
            
        try:
            json_obj = json.loads(json_str)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON: {str(e)}'}), 400
            
        code = generate_java_from_json(json_obj, mode)
        return jsonify({'code': code})
        
    except Exception as e:
        logger.error(f"Error converting JSON to Java: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-zip', methods=['POST'])
def generate_zip():
    try:
        data = request.get_json()
        steps = data.get('steps', [])
        mode = data.get('mode', 'general')
        # Validate all UI steps have a non-empty pageName
        for s in steps:
            if s.get('type') == 'ui' and (not s.get('pageName') or not s.get('pageName').strip()):
                return jsonify({'error': 'All UI Steps must have a non-empty Page Name.'}), 400
        # Optionally, get user email if logged in
        user_email = getattr(current_user, 'email', None) if hasattr(current_user, 'email') else None
        zip_path = create_gradle_zip(steps, mode, user_email)
        return send_file(zip_path, mimetype='application/zip', as_attachment=True, download_name='e2e-test-project.zip')
    except Exception as e:
        logging.exception('Error generating zip')
        return jsonify({'error': str(e)}), 500

CONTEXT_DIR = "context"

def save_context_to_db(context_data, name, description=''):
    """Save context data to database"""
    try:
        # Get user ID
        user_id = get_user_identifier()
        
        # Create a new context record
        new_context = TestContext(
            user_id=user_id,
            name=name,
            description=description,
            # Store the full JSON for backward compatibility
            context_data=json.dumps(context_data),
            # Store individual fields for better querying
            feature_summary=context_data.get('feature_summary', ''),
            # Renamed from 'requirements' to 'functional_requirements' in the prompt
            requirements=json.dumps(context_data.get('functional_requirements', context_data.get('requirements', []))),
            user_flows=json.dumps(context_data.get('user_flows', [])),
            validation_points=json.dumps(context_data.get('validation_points', [])),
            dependencies=json.dumps(context_data.get('dependencies', [])),
            edge_cases=json.dumps(context_data.get('edge_cases', [])),
            data_requirements=json.dumps(context_data.get('data_requirements', [])),
            # Add new fields from enhanced prompt
            performance_criteria=json.dumps(context_data.get('performance_criteria', [])),
            security_considerations=json.dumps(context_data.get('security_considerations', [])),
        )
        
        db.session.add(new_context)
        db.session.commit()
        
        return new_context.id
    except Exception as e:
        app.logger.error(f"Error saving context to database: {str(e)}")
        db.session.rollback()
        return None

def generate_structured_context(content):
    """
    Process raw requirements document with AI to generate structured context
    """
    try:
        # Prepare the prompt for the AI
        prompt = f"""
        You are an advanced analysis system designed explicitly to deeply interpret complex software requirements and generate exhaustive, structured context optimized for automated test case generation using advanced LLMs, specifically Gemini Pro.

        Conduct a meticulous and comprehensive analysis of the provided detailed software requirements document:

        {content}

        Upon completion of your analysis, deliver a highly detailed and structured JSON object containing the following explicitly defined and comprehensive sections:

        1. **"feature_summary"**: Provide an in-depth, clear, and precise summary of the primary features, functionalities, and objectives captured by the requirements, highlighting core purpose and scope.

        2. **"requirements"**: Detail each explicitly stated functional requirement individually, ensuring precision, completeness, and clarity. Organize requirements logically and cohesively, capturing all key functionalities.

        3. **"user_flows"**: Clearly articulate each critical user journey or workflow in detailed, sequential steps. Include clear entry and exit points, decision branches, alternative paths, and interactions within the workflow.

        4. **"validation_points"**: Identify exhaustive validation checks critical for ensuring comprehensive quality standards. Cover aspects such as functionality, usability, accessibility, performance, security, compliance, and user experience considerations.

        5. **"dependencies"**: Thoroughly list and describe all necessary system dependencies, integrations with external or internal services, APIs, databases, infrastructure requirements, and other resources needed for successful implementation and validation.

        6. **"edge_cases"**: Meticulously identify and detail all possible edge cases, exceptional conditions, boundary scenarios, error handling situations, and unexpected user interactions requiring rigorous testing.

        7. **"data_requirements"**: Clearly and comprehensively specify all data-related needs and constraints. Include test data requirements, data formats, expected data types, database schema details, data volume considerations, and any constraints or limitations that impact testing scenarios.

        8. **"performance_criteria"**: Define precise performance metrics, scalability expectations, load conditions, response times, throughput expectations, and other relevant benchmarks critical for validating system performance under realistic conditions.

        9. **"security_considerations"**: Explicitly outline security requirements, including access controls, authentication, authorization protocols, encryption standards, data privacy measures, compliance with relevant security standards, and any vulnerability points that must be rigorously tested.

        Format your output strictly as a clearly structured, valid JSON object containing exactly these keys. Ensure exhaustive coverage, clarity, completeness, and accuracy optimized specifically for use with Gemini Pro-driven automated test generation systems.
        """
        
        # Call Google Generative AI
        genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
        # Use model from environment variable
        model = genai.GenerativeModel(os.environ.get('GOOGLE_API_MODEL'))
        response = model.generate_content(prompt)
        
        # Extract and parse the JSON from the response
        response_text = response.text
        # Find JSON content between triple backticks if present
        json_match = re.search(r'```json\n(.+?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # If no code blocks, try to find a JSON object directly
            json_match = re.search(r'(\{.+\})', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text
                
        # Clean up and parse JSON
        context_data = json.loads(json_str)
        return context_data
    except Exception as e:
        app.logger.error(f"Error generating structured context: {str(e)}")
        raise

def get_context_text(context_name):
    """
    Reads the content of a context file and formats it for the prompt.
    Extracts related scenarios and key terms for better test case generation.
    """
    if not context_name:
        return ""
    path = os.path.join(CONTEXT_DIR, f"{context_name}.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            context_content = f.read()

            # Extract key terms (words in all caps or after "Verify", "Test", "Check")
            key_term_pattern = r"(?:Verify|Test|Check)\s+([A-Za-z\s]+)|([A-Z]{2,})"
            key_terms = re.findall(key_term_pattern, context_content)
            key_terms = list(set(term[0].strip() or term[1].strip() for term in key_terms if term[0] or term[1]))

            # Look for scenario patterns
            scenario_pattern = r"(?:Scenario|Test Scenario|Test Case)\s*\d*:\s*(.*?)(?=(?:Scenario|Test Scenario|Test Case)\s*\d*:|$)"
            scenarios = re.findall(scenario_pattern, context_content, re.DOTALL)
            scenarios = [s.strip() for s in scenarios if s.strip()]

            # Format the context with clear sections
            formatted_context = (
                "Context Information:\n"
                f"{context_content}\n\n"
                "Related Scenarios:\n"
                + "\n".join(f"- {scenario}" for scenario in scenarios) + "\n\n"
                "Key Terms and Dependencies:\n"
                + "\n".join(f"- {term}" for term in key_terms) + "\n\n"
                "Instructions:\n"
                "Based on the information above, generate comprehensive manual test scenarios for the described functionality. Ensure your test cases:\n"
                "1. Directly relate to and build upon the 'Context Information'.\n"
                "2. Extend and validate the 'Related Scenarios'.\n"
                "3. Thoroughly test all 'Key Terms and Dependencies'.\n"
                "4. Cover functional flows, edge cases, negative cases, and validations.\n"
                "5. Consider API interactions and UI/UX aspects if relevant to the context.\n"
                "6. Do NOT assume login or unrelated features.\n"
            )
            return formatted_context
    except FileNotFoundError:
        logger.error(f"Context file not found: {path}")
        return ""
    except Exception as e:
        logger.error(f"Error reading context file: {str(e)}")
        return ""

import os
import traceback
import stat
from flask import send_from_directory
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'gif', 'doc', 'docx', 'txt'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            app.logger.warning('Upload attempt with no file part')
            return jsonify({'error': 'No file part'}), 400
            
        file = request.files['file']
        if file.filename == '':
            app.logger.warning('Upload attempt with empty filename')
            return jsonify({'error': 'No selected file'}), 400
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            # Ensure upload folder exists
            if not os.path.exists(UPLOAD_FOLDER):
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                app.logger.info(f"Created upload folder: {UPLOAD_FOLDER}")
                
            # Get absolute path for logging
            abs_upload_folder = os.path.abspath(UPLOAD_FOLDER)
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            
            # Save the file
            file.save(save_path)
            app.logger.info(f"File saved successfully: {save_path}")
            
            # Get server name and protocol for absolute URL
            server_name = request.headers.get('Host', '')
            protocol = 'https' if request.is_secure else 'http'
            
            # Create both relative and absolute URLs
            relative_url = f'/uploads/{filename}'
            absolute_url = f"{protocol}://{server_name}{relative_url}"
            
            app.logger.info(f"File URL: {absolute_url}")
            return jsonify({
                'url': relative_url,
                'absolute_url': absolute_url,
                'filename': filename
            })
        else:
            app.logger.warning(f"Invalid file type: {file.filename}")
            return jsonify({'error': 'File type not allowed'}), 400
    except Exception as e:
        app.logger.error(f"Error in upload_file: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    try:
        # Log request details
        request_id = id(request)
        app.logger.info(f"[{request_id}] File access request for: {filename}")
        app.logger.info(f"[{request_id}] Request headers: {dict(request.headers)}")
        app.logger.info(f"[{request_id}] Request remote addr: {request.remote_addr}")
        
        # Ensure the upload folder exists
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            app.logger.warning(f"[{request_id}] Upload folder {UPLOAD_FOLDER} did not exist, created it")
            
        # Check if the file exists
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        app.logger.info(f"[{request_id}] Looking for file at: {os.path.abspath(file_path)}")
        
        if not os.path.isfile(file_path):
            app.logger.error(f"[{request_id}] File not found: {file_path}")
            app.logger.info(f"[{request_id}] Directory contents: {os.listdir(UPLOAD_FOLDER) if os.path.exists(UPLOAD_FOLDER) else 'upload folder does not exist'}")
            return jsonify({'error': 'File not found'}), 404
            
        # Log successful file access
        app.logger.info(f"[{request_id}] File found, size: {os.path.getsize(file_path)} bytes, serving file...")
        
        # Get server name and protocol for logging
        server_name = request.headers.get('Host', '')
        protocol = 'https' if request.is_secure else 'http'
        app.logger.info(f"[{request_id}] Serving from: {protocol}://{server_name}/uploads/{filename}")
        
        app.logger.info(f"Serving file: {file_path}")
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        request_id = id(request)
        app.logger.error(f"[{request_id}] Error serving file {filename}: {str(e)}")
        app.logger.error(f"[{request_id}] Exception type: {type(e).__name__}")
        app.logger.error(f"[{request_id}] Exception traceback: {traceback.format_exc()}")
        
        # Check file permissions
        try:
            if os.path.exists(file_path):
                stat_info = os.stat(file_path)
                app.logger.info(f"[{request_id}] File permissions: {stat.filemode(stat_info.st_mode)}")
                app.logger.info(f"[{request_id}] File owner: {stat_info.st_uid}, group: {stat_info.st_gid}")
        except Exception as perm_error:
            app.logger.error(f"[{request_id}] Error checking file permissions: {str(perm_error)}")
            
        return jsonify({
            'error': f'Error serving file: {str(e)}',
            'filename': filename,
            'path': file_path,
            'exception_type': type(e).__name__
        }), 500

# Add this helper function near the top (with other helpers)
def chunk_text(text, chunk_size=15000, overlap=1000):
    """Yield successive chunk_size character chunks from text, with optional overlap."""
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        yield text[start:end]
        start += chunk_size - overlap  # overlap to preserve context continuity

@app.route('/api/generate-testcases', methods=['POST'])
@llm_rate_limit
def generate_testcases():
    import logging
    import json
    import re
    try:
        data = request.json
        scenario = data.get('scenario', '')
        context_name = data.get('context', '')
        visual_image_urls = data.get('visual_image_urls', [])
        visual_doc_url = data.get('visual_doc_url', '')
        jira_image_urls = data.get('jira_image_urls', [])
        if not scenario:
            return jsonify({'error': 'No scenario provided'}), 400

        context_text = get_context_text(context_name)

        # Build visual context section for the prompt
        visual_section = ""
        if visual_doc_url:
            visual_section = (
                f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url}\n"
                "Use the images in the document to infer layout, field positions, and user flow.\n\n"
            )
        # If both doc and images, combine all image URLs
        all_image_urls = []
        
        # Process visual_image_urls to prefer absolute URLs when available
        if visual_image_urls:
            processed_urls = []
            for url_data in visual_image_urls:
                # Check if this is a dict with absolute_url (from our enhanced upload endpoint)
                if isinstance(url_data, dict) and 'absolute_url' in url_data:
                    processed_urls.append(url_data['absolute_url'])
                    app.logger.info(f"Using absolute URL for image: {url_data['absolute_url']}")
                # Check if this is a dict with url (fallback to relative)
                elif isinstance(url_data, dict) and 'url' in url_data:
                    processed_urls.append(url_data['url'])
                    app.logger.info(f"Using relative URL for image: {url_data['url']}")
                # If it's just a string URL
                else:
                    processed_urls.append(url_data)
                    app.logger.info(f"Using provided URL for image: {url_data}")
            all_image_urls.extend(processed_urls)
            
        # Add Jira image URLs
        if jira_image_urls:
            all_image_urls.extend(jira_image_urls)
            
        # Process visual_doc_url to prefer absolute URL if available
        if visual_doc_url:
            if isinstance(visual_doc_url, dict) and 'absolute_url' in visual_doc_url:
                visual_section = (
                    f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url['absolute_url']}\n"
                    "Use the images in the document to infer layout, field positions, and user flow.\n\n"
                )
                app.logger.info(f"Using absolute URL for document: {visual_doc_url['absolute_url']}")
            elif isinstance(visual_doc_url, dict) and 'url' in visual_doc_url:
                visual_section = (
                    f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url['url']}\n"
                    "Use the images in the document to infer layout, field positions, and user flow.\n\n"
                )
                app.logger.info(f"Using relative URL for document: {visual_doc_url['url']}")
            else:
                visual_section = (
                    f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url}\n"
                    "Use the images in the document to infer layout, field positions, and user flow.\n\n"
                )
                app.logger.info(f"Using provided URL for document: {visual_doc_url}")
                
        # Add all image URLs to the visual section
        if all_image_urls:
            visual_section += (
                "Refer to the following UI image(s) that show screen layout, component states, and user flow:\n" +
                "\n".join(all_image_urls) + "\n"
                "Use these visuals to derive field visibility, workflows, and validation points.\n\n"
            )
            app.logger.info(f"Added {len(all_image_urls)} image URLs to prompt")

        # --- CHUNKED CONTEXT LOGIC ---
        if context_name and context_text and len(context_text) > 15000:
            chunk_size = 15000
            overlap = 1000
            all_testcases = []
            context_chunks = list(chunk_text(context_text, chunk_size, overlap))
            for idx, chunk in enumerate(context_chunks):
                chunk_prompt = (
    f"Context chunk {idx+1} of {len(context_chunks)}:\n"
    f"{chunk}\n\n"
    f"{visual_section if visual_section else ''}"
    "You are a **Senior QA Engineer** responsible for ensuring deep functional coverage across API, UI, and data workflows.\n\n"
    
    "Your task is to generate a **thorough and exhaustive list of manual test scenarios** based on the following functionality.\n"
    "Design tests that validate functionality from every angle — core workflows, edge behaviors, data conditions, and integrations.\n\n"
    
    "You must rigorously apply the following **black-box functional test design techniques** when crafting scenarios (do NOT label techniques in the output; they are for internal guidance only):\n"
    "- **Equivalence Partitioning (EP):** Identify valid/invalid input classes for every input and constraint; include at least one representative per class.\n"
    "- **Boundary Value Analysis (BVA):** For ranges/limits (numbers, lengths, dates, counts), include just-below/at/just-above boundaries on both ends.\n"
    "- **Decision Tables / Cause–Effect Graphing:** For rules with multiple conditions → outcomes, derive a minimal but complete set of condition combinations and expected actions.\n"
    "- **State Transition Testing:** For workflows with states/events, cover valid transitions, invalid transitions, retries, cancellations, and time-based state changes.\n"
    "- **Combinatorial (Pairwise / 3-wise):** For multi-parameter inputs/configs, select cases ensuring at least pairwise coverage; use 3-wise for high-risk areas (money, identity, compliance).\n"
    "- **Syntax/Schema-Based & Contract Testing:** For APIs and structured payloads, validate against schemas (types, required/optional, enums), unknown/extra fields, and nullability.\n"
    "- **Error Guessing / Negative Heuristics:** Include malformed inputs, large values, special characters/Unicode/whitespace-only, duplicates, rate limits, and concurrency/idempotency checks as applicable.\n"
    "- **Property-Based Invariants (black-box lens):** Where business rules imply invariants (e.g., totals never negative), include randomized or varied data sets validating those properties.\n\n"
    
    "Each test case must be formatted as a **JSON object** with the following keys ONLY:\n"
    "- 'step': Describes the exact user/system action or precondition\n"
    "- 'expected': Describes the precise, observable, verifiable outcome\n"
    "- 'estimate_minutes': A realistic duration to execute, including setup, execution, validation, and evidence collection\n\n"

    "Allowed values for 'estimate_minutes' are: **5, 10, 15, 20, 30, 45, or 60** — based on the depth and complexity of the scenario. Choose wisely:\n"
    "- 5 mins → Atomic checks (simple UI visibility, tooltip, toggle states)\n"
    "- 10 mins → One-step validations (basic API, single-form validation)\n"
    "- 15 mins → Medium-complex UI/API workflows (validation + feedback + transition)\n"
    "- 20 mins → State-dependent logic or cross-condition checks\n"
    "- 30 mins → Composite flows (multi-role or chained interaction across components)\n"
    "- 45 mins → Partial end-to-end journeys or integration with environment dependency\n"
    "- 60 mins → Full-scale integration flows involving multiple modules or roles\n\n"

    "You are expected to generate **30–50 well-formed test cases**, ensuring coverage in the following categories:\n\n"
    
    "🔹 **API-Level Scenarios** (if applicable):\n"
    "- Valid/invalid payloads (EP) and boundary sizes/limits (BVA)\n"
    "- Required vs optional fields; nullability; unknown/extra fields (schema-based)\n"
    "- Status codes (200, 400, 401/403, 404, 409, 422, 429, 500)\n"
    "- Header behavior, auth dependencies, and rate limiting\n"
    "- Data returned, field types, enumerations, pagination, sorting, filtering (pairwise across params)\n"
    "- Contract/schema conformance and backward-compatibility checks\n\n"

    "🔹 **UI and UX Scenarios** (if applicable):\n"
    "- Element visibility, enabled/disabled states; default values (EP)\n"
    "- Input validation, inline errors/success, masking/formatting; length/format BVA\n"
    "- Modal/dialog behavior, transitions, scroll/overflow, tab order/focus\n"
    "- Conditional rendering and calculated fields (decision tables)\n"
    "- Accessibility implications (labels, focus order, keyboard navigation, contrast)\n\n"

    "🔹 **Data-Intensive Scenarios**:\n"
    "- Input limits, special chars/Unicode/whitespace-only; malformed/oversized values (error guessing + BVA)\n"
    "- Data lifecycle (create, update, delete, restore); merge/overwrite and version conflicts\n"
    "- Concurrency, idempotency, duplicate detection; timestamps/time-zone boundaries (state/time)\n"
    "- Audit trails/logs (if applicable): presence, accuracy, immutability\n\n"

    "🔹 **Negative, Role-Based, and Integration Scenarios**:\n"
    "- Unauthorized/forbidden actions, permission matrices (decision tables)\n"
    "- Multi-role workflows and handoffs; conditional states and time-based rules (state transitions)\n"
    "- Cross-module/configuration-driven behaviors; feature flags/toggles (pairwise across config × role)\n"
    "- Failure injection for dependent services (graceful degradation where applicable)\n\n"

    "⚠️ **Constraints:**\n"
    "- DO NOT assume anything outside the described scope (e.g., login, navigation, unrelated features)\n"
    "- DO NOT add extra keys, markdown, explanation, comments, or grouping in the output\n"
    "- DO NOT summarize — only return test cases\n\n"

    "✅ **Your final output must be a single JSON array** like this:\n"
    "[\n"
    "  {'step': '...', 'expected': '...', 'estimate_minutes': 10},\n"
    "  {'step': '...', 'expected': '...', 'estimate_minutes': 30},\n"
    "  ...\n"
    "]\n\n"

    f"Scenario:\n{scenario}\n\n"
    "Test Cases:"
)

                try:
                    api_key = os.environ.get("GOOGLE_API_KEY")
                    if not api_key:
                        logging.error("GOOGLE_API_KEY is not set in environment variables.")
                        continue
                    genai.configure(api_key=api_key)

                    model_name = os.environ.get('GOOGLE_API_MODEL')
                    if not model_name:
                        logging.error("GOOGLE_API_MODEL is not set in environment variables.")
                        continue
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(chunk_prompt)
                    content = response.text
                    match = re.search(r'(\[.*\])', content, re.DOTALL)
                    if match:
                        try:
                            testcases = json.loads(match.group(1))
                            all_testcases.extend(testcases)
                        except Exception as e:
                            continue  # skip this chunk if JSON is invalid
                except Exception as e:
                    continue  # skip this chunk if LLM call fails

            # Deduplicate test cases
            unique_testcases = []
            seen = set()
            for tc in all_testcases:
                key = (tc.get('step'), tc.get('expected'))
                if key not in seen:
                    unique_testcases.append(tc)
                    seen.add(key)
            total_estimated_time = sum(tc.get('estimate_minutes', 0) for tc in unique_testcases if isinstance(tc, dict))
            return jsonify({'testcases': unique_testcases, 'total_estimated_time': total_estimated_time})

        # --- ORIGINAL LOGIC FOR SMALL CONTEXT OR NO CONTEXT ---
        prompt = (
    "[ADVANCED] PROMPT TEMPLATE FOR QA TEST GENERATION (FINAL VERSION)\n"
    "Persona:\n"
    "You are a Senior QA Engineer and a specialist in Software Test Design. You are an expert at applying formal test methodologies to achieve maximum coverage with minimum effort. You will rigorously apply techniques like Equivalence Partitioning (EP), Boundary Value Analysis (BVA), Decision Table Testing, and State Transition Testing where appropriate. Your primary goal is to generate a lean, precise, and highly effective test suite.\n\n"

    "Core Task:\n"
    "Analyze the provided feature specifications. First, mentally identify the relevant test conditions, equivalence classes, and boundary values. Then, generate a comprehensive suite of manual test scenarios based on your analysis.\n\n"

    "Output Requirements:\n"
    "Format: A single, raw JSON array. Do not include markdown formatting or any text outside the JSON structure.\n"
    "JSON Object Structure: Each test case must be a JSON object with the following keys. The category and rationale fields are critical for demonstrating that formal methodologies were used.\n\n"

    "{\n"
    '  "test_case_id": "CATEGORY-001",\n'
    '  "category": "Happy Path | EP | BVA | Decision Table | Negative | UI/UX | State Transition",\n'
    '  "step": "A clear, concise, and repeatable action taken by the user or system.",\n'
    '  "expected": "The specific, verifiable, and observable outcome. Should be unambiguous.",\n'
    '  "rationale": "Briefly explains which test design principle justifies this test case.",\n'
    '  "estimate_minutes": 10\n'
    "}\n\n"

    "Key Definitions:\n"
    "test_case_id: Unique ID (e.g., BVA-001, EP-002).\n"
    "category: The primary test design technique used.\n"
    "step: The action to perform.\n"
    "expected: The exact expected result.\n"
    "rationale: Crucial. A short explanation of the testing theory behind the case.\n"
    "estimate_minutes: Rounded up to the nearest top 10th minute block (see below).\n\n"

    "Estimation Guidelines (estimate_minutes):\n"
    "Assume an experienced tester working in a fast, stable test environment.\n"
    "The estimate covers execution and validation only, not test authoring.\n"
    "Allowed Values: 10, 20 (minimum is 10 minutes)\n"
    "10 mins: All basic to moderate complexity test scenarios including UI checks, single interactions, API calls, and multi-step flows.\n"
    "20 mins: Complex scenarios with dependencies, role/permission checks, data branching, or end-to-end workflows.\n"
    "(Example: Any scenario that would normally take 1-10 mins is set to 10. Scenarios taking 11-20 mins are set to 20.)\n\n"

    "FEATURE CONTEXT (FILL THIS IN)\n"
    "1. Feature Description & User Story:\n"
    f"{scenario}\n"
    "2. UI/UX Details & Visuals:\n"
    f"{visual_section if visual_section else 'No visual context provided.'}\n"
    "3. Business Rules & Acceptance Criteria (AC):\n"
    f"{context_text if context_text else 'Extract business rules from the feature description above.'}\n"
    "4. API Endpoint(s) (if applicable):\n"
    "(Include any relevant API information.)\n"
    "5. User Roles & Permissions (if applicable):\n"
    "(Define different user types.)\n"
    "6. Data Validation Rules & Field Boundaries:\n"
    "(Be explicit about boundaries for BVA and classes for EP.)\n\n"

    "Final Instruction:\n"
    "Based on all the context provided, generate the test scenarios. Apply the specified test design techniques to ensure the test suite is efficient and robust. For each test case, populate the rationale field to justify its existence based on those techniques. Ensure estimate_minutes is set to either 10 or 20 (minimum is 10 minutes)."
)


        prompt = prompt[:20000]  # Truncate prompt if too long

        try:
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                logging.error("GOOGLE_API_KEY is not set in environment variables.")
                return jsonify({'error': 'GOOGLE_API_KEY is not set'}), 500
            genai.configure(api_key=api_key)

            model_name = os.environ.get('GOOGLE_API_MODEL')
            if not model_name:
                logging.error("GOOGLE_API_MODEL is not set in environment variables.")
                return jsonify({'error': 'GOOGLE_API_MODEL is not set'}), 500
            logging.info(f"Using Gemini model: {model_name}")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            content = response.text
            logging.info(f"Model output: {content}")
            match = re.search(r'(\[.*\])', content, re.DOTALL)
            logging.info(f"Regex matched: {match.group(1)[:500]}" if match else "No match found in model output.")
            if match:
                try:
                    testcases = json.loads(match.group(1))
                    total_estimated_time = sum(tc.get('estimate_minutes', 0) for tc in testcases if isinstance(tc, dict))
                    return jsonify({'testcases': testcases, 'total_estimated_time': total_estimated_time})
                except Exception as e:
                    return jsonify({'error': 'Gemini returned invalid JSON', 'raw': content}), 500
            return jsonify({'error': 'Gemini did not return a JSON array', 'raw': content}), 500

        except Exception as e:
            import traceback
            logging.error(f'Error generating test cases: {str(e)}\n{traceback.format_exc()}')
            return jsonify({'error': f'Error generating test cases: {str(e)}'}), 500

    except Exception as e:
        import traceback
        logging.error(f'Internal server error: {str(e)}\n{traceback.format_exc()}')
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/e2e-co-test')
def e2e_co_test():
    return render_template('e2e-co-test.html', active_tab='e2e')

@app.route('/api/fetch-html')
def fetch_html():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing URL'}), 400
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return jsonify({'html': resp.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/jira/oauth/login')
def jira_oauth_login():
    try:
        client_id = app.config['JIRA_CLIENT_ID']
        redirect_uri = app.config['JIRA_CALLBACK_URL']
        if not client_id or client_id == "your-client-id-here":
            logger.error("JIRA_CLIENT_ID not configured")
            return "Jira OAuth client ID not configured. Please set JIRA_CLIENT_ID in environment variables.", 500
            
        params = {
            "audience": "api.atlassian.com",
            "client_id": client_id,
            "scope": "read:jira-work write:jira-work read:jira-user read:me offline_access",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "prompt": "consent"
        }
        
        logger.info(f"Starting Jira OAuth flow with params: {params}")
        url = JIRA_AUTH_URL + "?" + "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
        return redirect(url)
    except Exception as e:
        logger.error(f"Error in Jira OAuth login: {str(e)}")
        return f"Error starting Jira OAuth flow: {str(e)}", 500

@app.route('/api/jira/oauth/callback')
def jira_oauth_callback():
    # Check if user denied access
    error = request.args.get("error")
    if error == "access_denied":
        # User cancelled the authorization, redirect to dashboard
        return redirect(url_for('index'))
    
    code = request.args.get("code")
    if not code:
        # No code and no error, redirect to dashboard with error message
        return redirect(url_for('index'))
    client_id = app.config['JIRA_CLIENT_ID']
    client_secret = app.config['JIRA_CLIENT_SECRET']
    redirect_uri = app.config['JIRA_CALLBACK_URL']
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri
    }
    resp = requests.post(JIRA_TOKEN_URL, json=data)
    if resp.status_code != 200:
        return f"Token exchange failed: {resp.text}", 400
    tokens = resp.json()
    
    # Store both access and refresh tokens
    session['jira_access_token'] = tokens['access_token']
    session['jira_refresh_token'] = tokens.get('refresh_token')
    session['jira_token_expires'] = time.time() + tokens.get('expires_in', 3600)
    
    # Get accessible Jira resources and find the correct one
    headers = {
        'Authorization': f"Bearer {tokens['access_token']}",
        'Accept': 'application/json'
    }
    cloud_id_resp = requests.get(
        'https://api.atlassian.com/oauth/token/accessible-resources',
        headers=headers
    )
    if cloud_id_resp.status_code == 200:
        cloud_id_data = cloud_id_resp.json()
        logger.info(f"Available Jira resources: {cloud_id_data}")
        
        if cloud_id_data and isinstance(cloud_id_data, list) and len(cloud_id_data) > 0:
            # Look for upgrad-jira.atlassian.net specifically
            target_resource = None
            for resource in cloud_id_data:
                resource_url = resource.get('url', '')
                if 'upgrad-jira.atlassian.net' in resource_url:
                    target_resource = resource
                    break
            
            # If we found the target, use it; otherwise use the first one
            if target_resource:
                session['jira_cloud_id'] = target_resource['id']
                session['jira_domain'] = target_resource['url']
                logger.info(f"Found target Jira resource: {target_resource['url']}")
            else:
                # Fallback to first available resource
                session['jira_cloud_id'] = cloud_id_data[0]['id']
                session['jira_domain'] = cloud_id_data[0]['url']
                logger.info(f"Using first available Jira resource: {cloud_id_data[0]['url']}")
            
            logger.info(f"Stored Jira cloud ID: {session['jira_cloud_id']}")
            logger.info(f"Using Jira domain: {session['jira_domain']}")
    else:
        # Fallback to default domain if API call fails
        session['jira_domain'] = 'https://upgrad-jira.atlassian.net'
        logger.warning(f"Failed to get accessible resources, using default domain")
    
    # Fetch user information
    try:
        logger.info("Attempting to fetch user info from Atlassian API...")
        user_info_resp = requests.get(
            'https://api.atlassian.com/me',
            headers=headers,
            timeout=10
        )
        logger.info(f"User info response status: {user_info_resp.status_code}")
        logger.info(f"User info response headers: {dict(user_info_resp.headers)}")
        
        if user_info_resp.status_code == 200:
            user_data = user_info_resp.json()
            logger.info(f"Raw user data from Atlassian: {user_data}")
            
            # Try different field names that Atlassian might use
            user_name = (user_data.get('name') or 
                        user_data.get('displayName') or 
                        user_data.get('display_name') or 
                        user_data.get('nickname') or 
                        user_data.get('account_id') or  # Sometimes Atlassian uses account_id
                        'User')
            
            user_email = (user_data.get('email') or 
                         user_data.get('emailAddress') or 
                         user_data.get('email_address') or 
                         '')
            
            user_avatar = (user_data.get('picture') or 
                          user_data.get('avatar') or 
                          user_data.get('avatarUrl') or 
                          user_data.get('avatar_url') or 
                          user_data.get('avatarUrls', {}).get('48x48') or  # Atlassian format
                          '')
            
            session['jira_user_name'] = user_name
            session['jira_user_email'] = user_email
            session['jira_user_avatar'] = user_avatar
            session['jira_login_time'] = time.time()
            session['show_welcome_message'] = True
            logger.info(f"Successfully stored user info: {user_name} ({user_email})")
        else:
            logger.error(f"Failed to fetch user info. Status: {user_info_resp.status_code}, Response: {user_info_resp.text}")
            # Store default values so the profile still shows
            session['jira_user_name'] = 'Jira User'
            session['jira_user_email'] = 'Connected to Jira'
            session['jira_user_avatar'] = ''
            session['jira_login_time'] = time.time()
            session['show_welcome_message'] = True
    except Exception as e:
        logger.error(f"Exception while fetching user info: {str(e)}")
        # Store default values so the profile still shows
        session['jira_user_name'] = 'Jira User'
        session['jira_user_email'] = 'Connected to Jira'
        session['jira_user_avatar'] = ''
        session['jira_login_time'] = time.time()
        session['show_welcome_message'] = True
    
    return redirect(url_for('my_details'))

def refresh_jira_token():
    """Refresh the Jira access token using the refresh token."""
    refresh_token = session.get('jira_refresh_token')
    if not refresh_token:
        return False
    
    try:
        client_id = app.config['JIRA_CLIENT_ID']
        client_secret = app.config['JIRA_CLIENT_SECRET']
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token
        }
        resp = requests.post(JIRA_TOKEN_URL, json=data)
        if resp.status_code == 200:
            tokens = resp.json()
            session['jira_access_token'] = tokens['access_token']
            session['jira_token_expires'] = time.time() + tokens.get('expires_in', 3600)
            return True
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
    return False

@app.route('/api/jira/issues', methods=['GET'])
def fetch_jira_issues():
    """
    Fetch Jira issues using the stored access token.
    Supports filtering by project, status, and search query.
    """
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira. Please connect first.'}), 401
    if not cloud_id:
        return jsonify({'error': 'No Jira cloud ID found. Please reconnect to Jira.'}), 401

    # Check if token needs refresh
    token_expires = session.get('jira_token_expires', 0)
    if time.time() >= token_expires:
        if not refresh_jira_token():
            return jsonify({'error': 'Token expired. Please reconnect to Jira.'}), 401
        access_token = session['jira_access_token']

    try:
        # Get query parameters
        project = request.args.get('project')
        status = request.args.get('status')
        search = request.args.get('search')
        max_results = request.args.get('maxResults', '50')

        # Build JQL query
        jql_parts = []
        
        
        # Handle specific issue key search (e.g., "IRA-62215")
        if search and '-' in search:
            # If search looks like an issue key (contains a hyphen), search by key
            jql_parts.append(f'key = "{search}"')
        else:
            # For My Details page, default to showing user's assigned issues
            user_email = session.get('jira_user_email')
            if user_email and not search and not project and not status:
                jql_parts.append(f'assignee = "{user_email}"')
                
            # Otherwise use the regular search parameters
            if project:
                jql_parts.append(f'project = "{project}"')
            if status:
                jql_parts.append(f'status = "{status}"')
            if search:
                jql_parts.append(f'text ~ "{search}"')
        
        # Add ordering and default fallback
        if jql_parts:
            jql = ' AND '.join(jql_parts) + ' ORDER BY updated DESC'
        else:
            # Fallback for My Details: show recent issues for the user
            user_email = session.get('jira_user_email')
            if user_email:
                jql = f'assignee = "{user_email}" ORDER BY updated DESC'
            else:
                jql = 'assignee = currentUser() ORDER BY updated DESC'
        logger.info(f"Generated JQL query: {jql}")

        # Make request to Jira API
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        # Now fetch issues using stored cloud ID - Updated to use /search/jql endpoint
        issues_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql'
        params = {
            'jql': jql,
            'maxResults': max_results,
            'fields': 'summary,description,status,assignee,created,updated',
            'expand': 'renderedFields'
        }
        
        logger.info(f"Fetching issues from: {issues_url}")
        logger.info(f"With params: {params}")
        logger.info(f"Using headers: {headers}")
        
        # Add timeout and verify SSL
        response = requests.get(
            issues_url, 
            headers=headers, 
            params=params,
            timeout=30,
            verify=True
        )
        
        # Log the response for debugging
        logger.info(f"Issues Response Status: {response.status_code}")
        logger.info(f"Issues Response Headers: {dict(response.headers)}")
        logger.info(f"Issues Response Body: {response.text[:1000]}")  # Log first 1000 chars
        
        # Check if response is HTML instead of JSON
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' in content_type:
            logger.error(f"Received HTML instead of JSON. Response: {response.text[:1000]}")
            # Try to refresh token and retry once
            if refresh_jira_token():
                # Retry the request with new token
                headers['Authorization'] = f'Bearer {session["jira_access_token"]}'
                response = requests.get(
                    issues_url, 
                    headers=headers, 
                    params=params,
                    timeout=30,
                    verify=True
                )
                content_type = response.headers.get('content-type', '').lower()
                if 'text/html' in content_type:
                    return jsonify({
                        'error': 'Authentication failed even after token refresh. Please reconnect to Jira.',
                        'status_code': response.status_code,
                        'content_type': content_type,
                        'response': response.text[:1000]
                    }), 401
            
            return jsonify({
                'error': 'Received HTML response instead of JSON. Token may be invalid or expired.',
                'status_code': response.status_code,
                'content_type': content_type,
                'response': response.text[:1000]
            }), 401
        
        if response.status_code != 200:
            return jsonify({
                'error': 'Failed to fetch Jira issues',
                'status_code': response.status_code,
                'response': response.text[:1000]  # Limit response size
            }), response.status_code

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Error parsing issues response: {str(e)}")
            return jsonify({
                'error': 'Invalid JSON response from Jira API',
                'details': str(e),
                'response': response.text[:1000]  # Limit response size
            }), 500

        # Process and format the response
        issues = []
        
        for issue in data.get('issues', []):
            fields = issue.get('fields') or {}
            rendered = fields.get('renderedFields') or issue.get('renderedFields') or {}
            issue_key = issue.get('key')
            description = fields.get('description')
            description_html = ''
            # Prefer rendered HTML if available
            if rendered and rendered.get('description'):
                description_html = rendered['description']
                # --- Rewrite Jira attachment image URLs (classic and blob) ---
                # Classic attachment: /rest/api/3/attachment/content/145995
                description_html = re.sub(
                    r'<img([^>]+)src=["\"]/rest/api/3/attachment/content/(\d+)["\"]',
                    r'<img\1src="/api/jira/attachment?id=\2"',
                    description_html
                )
                # Media Service blob: blob:https://...id=UUID...&collection=COLLECTION
                def blob_rewrite(match):
                    attrs = match.group(1)
                    blob_url = match.group(2)
                    m = re.search(r'id=([a-f0-9\-]+)', blob_url)
                    id = m.group(1) if m else ''
                    m2 = re.search(r'collection=([a-zA-Z0-9\-_]*)', blob_url)
                    collection = m2.group(1) if m2 else 'jira-issue'
                    return f'<img{attrs}src="/api/jira/attachment?id={id}&collection={collection}"'
                description_html = re.sub(
                    r'<img([^>]+)src=["\"]blob:[^"\"]*id=([a-f0-9\-]+)[^"\"]*collection=([a-zA-Z0-9\-_]*)["\"]',
                    blob_rewrite,
                    description_html
                )
            elif isinstance(description, dict) and description.get('type') == 'doc':
                description_html = adf_to_html(description)
            elif isinstance(description, str):
                description_html = f'<p>{description}</p>'
            else:
                description_html = ''
            issues.append({
                'key': issue_key,
                'summary': fields.get('summary') or '',
                'description': description or '',
                'description_html': description_html,
                'status': (fields.get('status') or {}).get('name'),
                'assignee': (fields.get('assignee') or {}).get('displayName'),
                'created': fields.get('created'),
                'updated': fields.get('updated'),
                'url': f"{domain}/browse/{issue_key}" if issue_key else None
            })

        return jsonify({
            'issues': issues,
            'total': data.get('total', 0),
            'jira_domain': session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        })

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while fetching Jira issues: {str(e)}")
        return jsonify({
            'error': 'Network error while connecting to Jira',
            'details': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Error fetching Jira issues: {str(e)}")
        return jsonify({
            'error': 'Failed to fetch Jira issues',
            'details': str(e)
        }), 500

@app.route('/data-generator')
@jira_auth_required
def data_generator():
    return render_template('data-generation.html')

# Keep old route for backward compatibility
@app.route('/data')
@jira_auth_required
def data():
    return redirect('/data-generator', code=301)

# Jira API endpoints

# Duplicate route removed - using fetch_jira_issues() at line 5021 instead

@app.route('/api/jira/time-entries', methods=['GET'])
@jira_auth_required
def get_jira_time_entries():
    """Get time entries for Jira issues for a specific date"""
    logger.info("=== Time Entries API Called ===")
    
    # Get date filter from query parameters
    date_filter = request.args.get('date', '')
    logger.info(f"Date filter: {date_filter}")
    
    # Use OAuth token from session
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    
    if not access_token or not cloud_id:
        logger.error("Missing OAuth credentials in session")
        return jsonify({'error': 'Jira OAuth not configured. Please re-authenticate.'}), 401
    
    logger.info("Using OAuth authentication for time entries")
    return get_time_entries_oauth(access_token, cloud_id, date_filter)


def _extract_comment_text(comment):
    """Best-effort conversion of Jira worklog comment to plain text.
    Jira may return ADF (Atlassian Document Format) objects or plain strings.
    """
    try:
        # Plain string already
        if isinstance(comment, str):
            return comment

        # ADF object
        if isinstance(comment, dict):
            def walk(node):
                texts = []
                if isinstance(node, dict):
                    node_type = node.get('type')
                    # Collect text nodes
                    if node_type == 'text' and 'text' in node:
                        texts.append(node['text'])
                    # Treat hard breaks as newlines
                    if node_type == 'hardBreak':
                        texts.append('\n')
                    # Recurse into children
                    for child in node.get('content', []):
                        texts.extend(walk(child))
                elif isinstance(node, list):
                    for child in node:
                        texts.extend(walk(child))
                return texts

            parts = walk(comment)
            return ''.join(parts).strip()
    except Exception as e:
        try:
            logger.warning(f"Failed to parse worklog comment: {e}")
        except Exception:
            pass
    return ''

def get_time_entries_basic_auth(jira_email, jira_token, jira_base_url):
    """Get time entries using basic authentication - matching team_manager implementation"""
    date_filter = request.args.get('date', '')
    
    try:
        import requests
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(jira_email, jira_token)
        headers = {"Accept": "application/json"}
        
        # Get current user info
        user_url = f'{jira_base_url}/rest/api/3/myself'
        logger.info(f"Testing basic auth with URL: {user_url}")
        logger.info(f"Using email: {jira_email}")
        
        user_response = requests.get(user_url, headers=headers, auth=auth, timeout=30)
        logger.info(f"Basic auth response status: {user_response.status_code}")
        
        if user_response.status_code != 200:
            logger.error(f"Basic auth failed: {user_response.text}")
            return jsonify({'error': f'Failed to authenticate with Jira (status: {user_response.status_code})'}), 401
            
        user_data = user_response.json()
        user_account_id = user_data.get('accountId')
        
        # Build JQL for worklogs - exactly like team_manager
        if date_filter:
            worklog_jql = f'worklogAuthor = "{user_account_id}" AND worklogDate = "{date_filter}"'
        else:
            worklog_jql = f'worklogAuthor = "{user_account_id}"'
        
        # Search for issues with worklogs - exactly like team_manager
        search_url = f'{jira_base_url}/rest/api/3/search/jql'
        search_params = {
            'jql': worklog_jql,
            'fields': 'worklog,summary',
            'maxResults': 1000
        }
        
        search_response = requests.get(search_url, headers=headers, params=search_params, auth=auth, timeout=30)
        
        if search_response.status_code != 200:
            return jsonify({'error': 'Failed to search for issues with worklogs'}), 500
        
        search_data = search_response.json()
        all_time_entries = []
        total_seconds = 0
        
        # Process each issue and extract relevant worklogs
        for issue in search_data.get('issues', []):
            issue_key = issue.get('key', 'Unknown')
            issue_summary = issue.get('fields', {}).get('summary', 'No summary available')
            
            worklog_data = issue.get('fields', {}).get('worklog', {})
            worklogs = worklog_data.get('worklogs', [])
            
            for worklog in worklogs:
                worklog_author_id = worklog.get('author', {}).get('accountId', '')
                worklog_started = worklog.get('started', '')
                
                if worklog_author_id == user_account_id:
                    if date_filter:
                        worklog_date = worklog_started.split('T')[0] if 'T' in worklog_started else worklog_started
                        if worklog_date != date_filter:
                            continue
                    
                    time_spent_seconds = worklog.get('timeSpentSeconds', 0)
                    total_seconds += time_spent_seconds
                    hours = time_spent_seconds // 3600
                    minutes = (time_spent_seconds % 3600) // 60
                    time_spent_display = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                    
                    comment_raw = worklog.get('comment', '')
                    comment_text = _extract_comment_text(comment_raw)
                    all_time_entries.append({
                        'id': worklog.get('id', ''),
                        'issueKey': issue_key,
                        'issueSummary': issue_summary,
                        'timeSpent': time_spent_display,
                        'timeSpentSeconds': time_spent_seconds,
                        'comment': comment_text,
                        'started': worklog_started,
                        'author': worklog.get('author', {}).get('displayName', 'User')
                    })
        
        # Aggregate by issue and sort by latest started
        aggregated_entries = _aggregate_time_entries(all_time_entries)
        aggregated_entries.sort(key=lambda x: x.get('started', ''), reverse=True)
        
        # Calculate total time display
        total_hours = total_seconds // 3600
        total_minutes = (total_seconds % 3600) // 60
        total_time_display = f"{total_hours}h {total_minutes}m" if total_hours > 0 else f"{total_minutes}m"
        
        return jsonify({
            'timeEntries': aggregated_entries,
            'totalTimeSeconds': total_seconds,
            'totalTimeDisplay': total_time_display,
            'date': date_filter,
            'entriesCount': len(aggregated_entries)
        })
        
    except Exception as e:
        logger.error(f"Error in basic auth time entries: {str(e)}")
        return jsonify({'error': f'Failed to fetch time entries: {str(e)}'}), 500


def get_time_entries_oauth(access_token, cloud_id, date_filter):
    """Get time entries using OAuth authentication"""
    logger.info(f"OAuth time entries - Token: {access_token[:20]}...")
    logger.info(f"OAuth time entries - Cloud ID: {cloud_id}")
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    try:
        # Get current user info directly instead of searching
        myself_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself'
        logger.info(f"Calling myself endpoint: {myself_url}")
        
        user_response = requests.get(myself_url, headers=headers, timeout=30)
        logger.info(f"Myself response status: {user_response.status_code}")
        
        if user_response.status_code != 200:
            logger.error(f"Myself endpoint failed: {user_response.text}")
            return jsonify({'error': f'Failed to authenticate with Jira. Please re-authenticate. (status: {user_response.status_code})'}), 401
            
        user_data = user_response.json()
        user_account_id = user_data.get('accountId')
        
        if not user_account_id:
            return jsonify({'error': 'Could not get user account ID'}), 400
        
        # Build JQL to find issues with worklogs by the current user
        if date_filter:
            worklog_jql = f'worklogAuthor = currentUser() AND worklogDate = "{date_filter}"'
        else:
            worklog_jql = f'worklogAuthor = currentUser()'
        
        # Search for issues with worklogs
        search_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql'
        search_params = {
            'jql': worklog_jql,
            'fields': 'summary,worklog,issuetype,priority,status,assignee,project,sprint,epic',
            'expand': 'worklog',
            'maxResults': 100
        }
        
        search_response = requests.get(search_url, headers=headers, params=search_params, timeout=30)
        
        if search_response.status_code != 200:
            logger.error(f"Worklog search failed: {search_response.status_code} - {search_response.text}")
            return jsonify({'error': f'Failed to search for issues with worklogs (status: {search_response.status_code})'}), 500
        
        search_data = search_response.json()
        all_time_entries = []
        total_seconds = 0
        
        # Process each issue and extract relevant worklogs
        for issue in search_data.get('issues', []):
            issue_key = issue.get('key', 'Unknown')
            fields = issue.get('fields', {})
            issue_summary = fields.get('summary', 'No summary available')
            
            # Extract additional issue details
            issue_type = fields.get('issuetype', {})
            issue_type_name = issue_type.get('name', 'Unknown')
            issue_type_icon = issue_type.get('iconUrl', '')
            
            priority = fields.get('priority', {})
            priority_name = priority.get('name', 'None')
            priority_icon = priority.get('iconUrl', '')
            
            status = fields.get('status', {})
            status_name = status.get('name', 'Unknown')
            status_category = status.get('statusCategory', {}).get('name', 'Unknown')
            
            assignee = fields.get('assignee', {})
            assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
            
            project = fields.get('project', {})
            project_name = project.get('name', 'Unknown')
            project_key = project.get('key', 'Unknown')
            
            # Handle sprint - could be an array or single object
            sprint_info = None
            sprint_field = fields.get('sprint')
            if sprint_field:
                if isinstance(sprint_field, list) and sprint_field:
                    # Get the last (current) sprint
                    sprint_info = sprint_field[-1].get('name', '') if sprint_field[-1] else ''
                elif isinstance(sprint_field, dict):
                    sprint_info = sprint_field.get('name', '')
            
            # Handle epic
            epic_field = fields.get('epic')
            epic_name = epic_field.get('name', '') if epic_field else ''
            
            worklog_data = fields.get('worklog', {})
            worklogs = worklog_data.get('worklogs', [])
            
            for worklog in worklogs:
                worklog_author_id = worklog.get('author', {}).get('accountId', '')
                worklog_started = worklog.get('started', '')
                
                if worklog_author_id == user_account_id:
                    if date_filter:
                        worklog_date = worklog_started.split('T')[0] if 'T' in worklog_started else worklog_started
                        if worklog_date != date_filter:
                            continue
                    
                    time_spent_seconds = worklog.get('timeSpentSeconds', 0)
                    total_seconds += time_spent_seconds
                    hours = time_spent_seconds // 3600
                    minutes = (time_spent_seconds % 3600) // 60
                    time_spent_display = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                    
                    comment_raw = worklog.get('comment', '')
                    comment_text = _extract_comment_text(comment_raw)
                    all_time_entries.append({
                        'id': worklog.get('id', ''),
                        'issueKey': issue_key,
                        'issueSummary': issue_summary,
                        'timeSpent': time_spent_display,
                        'timeSpentSeconds': time_spent_seconds,
                        'comment': comment_text,
                        'started': worklog_started,
                        'author': worklog.get('author', {}).get('displayName', session.get('jira_user_name', 'User')),
                        # Additional issue details
                        'issueType': issue_type_name,
                        'issueTypeIcon': issue_type_icon,
                        'priority': priority_name,
                        'priorityIcon': priority_icon,
                        'status': status_name,
                        'statusCategory': status_category,
                        'assignee': assignee_name,
                        'project': project_name,
                        'projectKey': project_key,
                        'sprint': sprint_info,
                        'epic': epic_name
                    })
    
    except Exception as e:
        logger.error(f"Error fetching OAuth time entries: {str(e)}")
        return jsonify({'error': f'Failed to fetch time entries: {str(e)}'}), 500
    
    # Aggregate by issue and sort by latest started (most recent first)
    aggregated_entries = _aggregate_time_entries(all_time_entries)
    aggregated_entries.sort(key=lambda x: x.get('started', ''), reverse=True)
    
    # Calculate total time display
    total_hours = total_seconds // 3600
    total_minutes = (total_seconds % 3600) // 60
    total_time_display = f"{total_hours}h {total_minutes}m" if total_hours > 0 else f"{total_minutes}m"
    
    return jsonify({
        'timeEntries': aggregated_entries,
        'totalTimeSeconds': total_seconds,
        'totalTimeDisplay': total_time_display,
        'date': date_filter,
        'entriesCount': len(aggregated_entries)
    })

@app.route('/api/jira/time-entries', methods=['POST'])
def add_jira_time_entry():
    """Add a new time entry for a Jira issue"""
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira'}), 401
    
    # Get Jira cloud ID from session
    cloud_id = session.get('jira_cloud_id')
    if not cloud_id:
        return jsonify({'error': 'Jira cloud ID not found in session'}), 400
    
    # Get request data
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    # Validate required fields
    required_fields = ['issueKey', 'timeSpent', 'started']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # In a real implementation, you would make an API call to Jira
    # to add the worklog entry. For this demo, we'll simulate success.
    
    # Return success response
    return jsonify({
        'success': True,
        'message': 'Time entry added successfully',
        'timeEntry': {
            'id': '123', # This would be returned by the Jira API
            'issueKey': data['issueKey'],
            'timeSpent': data['timeSpent'],
            'started': data['started'],
            'comment': data.get('comment', ''),
            'author': session.get('jira_user_name', 'User')
        }
    })

@app.route('/my-details')
@jira_auth_required
def my_details():
    """My Details page - shows user profile, Jira issues, and worklog activity"""
    return render_template('my-jira.html', active_tab='jira')

# Keep old route for backward compatibility
@app.route('/my-jira')
@jira_auth_required
def my_jira():
    return redirect('/my-details', code=301)

# ===================== Admin: Time Entries by User =====================
@app.route('/admin/time-entries')
@jira_auth_required
@admin_required
def admin_time_entries_page():
    """Admin UI to search Jira worklogs by any user."""
    return render_template('admin-time-entries.html', active_tab='admin')


# ===================== Admin: Jira Dashboards =====================
@app.route('/dashboards')
@jira_auth_required
def jira_dashboards_page():
    """Jira-helper dashboard - Release progress & Issue tracking."""
    jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    return render_template('jira-helper-dashboard.html', active_tab='dashboards', jira_domain=jira_domain)

@app.route('/admin/dashboards')
@jira_auth_required
@admin_required
def admin_jira_dashboards_page():
    """Admin UI for Jira dashboards with JQL-powered views and charts."""
    return render_template('admin-jira-dashboards.html', active_tab='admin-dashboards')


@app.route('/api/jira-helper/jql', methods=['POST'])
@jira_auth_required
def jira_helper_jql():
    """Jira-helper API: Run JQL and return issues with status buckets."""
    try:
        payload = request.get_json(silent=True) or {}
        jql_query = (payload.get('jql') or '').strip()
        
        if not jql_query:
            return jsonify({'error': 'JQL query is required'}), 400
        
        # Auth/session
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        
        if not access_token:
            return jsonify({'error': 'Jira authentication required'}), 401
        if not cloud_id:
            return jsonify({'error': 'Jira cloud ID not found in session'}), 400
        
        # Ensure token fresh
        try:
            token_expires = session.get('jira_token_expires', 0)
            if time.time() >= token_expires:
                if refresh_jira_token():
                    access_token = session.get('jira_access_token')
                else:
                    return jsonify({'error': 'Token expired. Please reconnect to Jira.'}), 401
        except Exception:
            pass
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # Define status buckets
        STATUS_BUCKETS = {
            'qa': ['Ready for QA', 'QA-Ready', 'QA Progress - Blocked', 'Resolved', 'QA In Progress', 'QA Inprogress', 'Ready for UAT'],
            'dev': ['OPEN', 'Reopen', 'ToDo', 'To Do', 'Reopened', 'Dev Inprogress', 'Dev - Building', 'Build Broken', 'Ready for Development', 'Dev - Frontend - InProgress', 'Dev - Backend - InProgress', 'Dev - Backend - Todo', 'Dev - Frontend - Todo', 'Dev- UI - InProgress', 'Dev- UI - Todo', 'Backlog Item', 'Open (migrated)', 'Open', 'QA - Building', 'Groomed'],
            'product': ['UAT', 'UAT In Progress', 'UAT Inprogress', 'UAT Status'],
            'completed': ['Accepted', 'Closed in QA', 'In Stage'],
            'dropped': ['Dropped'],
            'deployed': ['In Production']
        }
        
        def normalize_status(status):
            return status.lower().strip().replace('-', ' ').replace('_', ' ').replace('  ', ' ')
        
        # Build normalized bucket map
        normalized_buckets = {}
        for bucket, statuses in STATUS_BUCKETS.items():
            for status in statuses:
                normalized = normalize_status(status)
                normalized_buckets[normalized] = bucket
        
        def get_bucket(status):
            if not status:
                return 'other'
            normalized = normalize_status(status)
            return normalized_buckets.get(normalized, 'other')
        
        # Fetch all issues with pagination using nextPageToken (not startAt)
        all_issues = []
        page_size = 100
        next_page_token = None
        page_number = 1
        
        logger.info(f"Starting JQL query: {jql_query}")
        
        while True:
            logger.info(f"Fetching page {page_number}, pageSize={page_size}")
            
            # Build request payload for POST
            search_payload = {
                'jql': jql_query,
                'maxResults': page_size,
                'fields': ['id', 'key', 'summary', 'status', 'assignee', 'priority', 'updated', 'created', 'issuetype', 'project', 'parent', 'fixVersions', 'timetracking', 'timeoriginalestimate', 'timeestimate', 'timespent', 'aggregatetimeoriginalestimate', 'aggregatetimeestimate', 'aggregatetimespent'],
                'expand': 'changelog'
            }
            
            # Add nextPageToken for subsequent requests
            if next_page_token:
                search_payload['nextPageToken'] = next_page_token
            
            resp = requests.post(
                f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
                headers=headers,
                json=search_payload,
                timeout=30
            )
            
            if resp.status_code == 401:
                if refresh_jira_token():
                    access_token = session.get('jira_access_token')
                    headers['Authorization'] = f'Bearer {access_token}'
                    resp = requests.post(
                        f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
                        headers=headers,
                        json=search_payload,
                        timeout=30
                    )
            
            if resp.status_code != 200:
                body = resp.text[:500] if resp.text else ''
                logger.error(f"Jira API error: {resp.status_code} - {body}")
                return jsonify({'error': f'Jira API error {resp.status_code}', 'details': body}), 400
            
            data = resp.json() or {}
            issues = data.get('issues', []) or []
            total_issues = data.get('total', 0)
            next_page_token = data.get('nextPageToken')
            is_last = data.get('isLast', True)
            
            logger.info(f"Page {page_number}: Fetched {len(issues)} issues ({len(all_issues) + len(issues)} collected so far, Jira reports {total_issues} total)")
            logger.info(f"  - nextPageToken: {'EXISTS' if next_page_token else 'NULL'}, isLast: {is_last}")
            
            if not issues:
                logger.info("No more issues to fetch")
                break
            
            for issue in issues:
                # Add bucket classification
                status_name = issue.get('fields', {}).get('status', {}).get('name')
                issue['bucket'] = get_bucket(status_name)
                all_issues.append(issue)
            
            page_number += 1
            
            # Continue if there's more data (either nextPageToken exists or we got a full page)
            has_more_pages = next_page_token or (len(issues) == page_size and not is_last)
            
            if not has_more_pages:
                logger.info(f"  - Stopping: {'No nextPageToken' if not next_page_token else ''} {'isLast=true' if is_last else ''} {'Partial page' if len(issues) < page_size else ''}")
                break
        
        logger.info(f"✓ Completed: Fetched all {len(all_issues)} issues in {page_number - 1} page(s)")
        
        # Organize issues into buckets
        buckets = {
            'dev': [],
            'qa': [],
            'product': [],
            'completed': [],
            'dropped': [],
            'deployed': [],
            'other': []
        }
        
        for issue in all_issues:
            bucket = issue.get('bucket', 'other')
            buckets[bucket].append(issue)
        
        bucket_counts = {k: len(v) for k, v in buckets.items()}
        
        return jsonify({
            'total': len(all_issues),
            'issues': all_issues,
            'buckets': buckets,
            'bucketCounts': bucket_counts
        })
        
    except Exception as e:
        logger.error(f"Jira-helper JQL error: {str(e)}")
        return jsonify({'error': 'Failed to fetch Jira issues', 'details': str(e)}), 500

@app.route('/api/jira/admin/run-jql', methods=['POST'])
@jira_auth_required
@admin_required
def admin_run_jql():
    """Admin API: Run arbitrary JQL and return ALL issues with proper pagination plus useful aggregates.
    Body JSON:
      - jql: string (required)
    """
    try:
        payload = request.get_json(silent=True) or {}
        import requests
        jql_query = (payload.get('jql') or '').strip()

        if not jql_query:
            return jsonify({'success': False, 'error': 'JQL is required'}), 400

        # Auth/session
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        if not access_token:
            return jsonify({'success': False, 'error': 'Jira authentication required'}), 401
        if not cloud_id:
            return jsonify({'success': False, 'error': 'Jira cloud ID not found in session'}), 400

        # Ensure token fresh
        try:
            token_expires = session.get('jira_token_expires', 0)
            if time.time() >= token_expires:
                if refresh_jira_token():
                    access_token = session.get('jira_access_token')
                else:
                    return jsonify({'success': False, 'error': 'Token expired. Please reconnect to Jira.'}), 401
        except Exception:
            pass

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        # Fetch ALL issues using nextPageToken pagination
        items = []
        page_size = 100
        next_page_token = None
        page_number = 1
        
        logger.info(f"Admin JQL query: {jql_query}")
        
        while True:
            logger.info(f"Admin fetching page {page_number}")
            
            search_payload = {
                'jql': jql_query,
                'maxResults': page_size,
                'fields': ['key', 'summary', 'status', 'assignee', 'reporter', 'priority', 'created', 'updated', 'resolutiondate', 'issuetype', 'labels', 'customfield_10026', 'project']
            }
            
            if next_page_token:
                search_payload['nextPageToken'] = next_page_token
            
            resp = requests.post(
                f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
                headers=headers,
                json=search_payload,
                timeout=30
            )
            
            if resp.status_code == 401:
                if refresh_jira_token():
                    access_token = session.get('jira_access_token')
                    headers['Authorization'] = f'Bearer {access_token}'
                    resp = requests.post(
                        f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
                        headers=headers,
                        json=search_payload,
                        timeout=30
                    )
                
            if resp.status_code != 200:
                body = resp.text[:500] if resp.text else ''
                logger.error(f"Admin JQL error: {resp.status_code} - {body}")
                return jsonify({'success': False, 'error': f'Jira API error {resp.status_code}', 'details': body}), 400

            data = resp.json() or {}
            issues = data.get('issues', []) or []
            next_page_token = data.get('nextPageToken')
            is_last = data.get('isLast', True)
            
            logger.info(f"Page {page_number}: Fetched {len(issues)} issues ({len(items) + len(issues)} total)")
            
            if not issues:
                break
            
            for it in issues:
                f = it.get('fields', {}) or {}
                items.append({
                    'key': it.get('key'),
                    'summary': f.get('summary'),
                    'status': (f.get('status') or {}).get('name'),
                    'statusCategory': (f.get('status') or {}).get('statusCategory', {}).get('name'),
                    'assignee': (f.get('assignee') or {}).get('displayName') if f.get('assignee') else None,
                    'reporter': (f.get('reporter') or {}).get('displayName') if f.get('reporter') else None,
                    'priority': (f.get('priority') or {}).get('name'),
                    'issuetype': (f.get('issuetype') or {}).get('name'),
                    'project': (f.get('project') or {}).get('name'),
                    'labels': f.get('labels') or [],
                    'created': f.get('created'),
                    'updated': f.get('updated'),
                    'resolved': f.get('resolutiondate'),
                    'storyPoints': f.get('customfield_10026')
                })
            
            page_number += 1
            
            # Continue if there's more data
            has_more_pages = next_page_token or (len(issues) == page_size and not is_last)
            if not has_more_pages:
                logger.info(f"Admin completed: Fetched all {len(items)} issues in {page_number - 1} pages")
                break

        # Build comprehensive aggregates
        def _inc(map_obj, key):
            map_obj[key or 'Unassigned'] = map_obj.get(key or 'Unassigned', 0) + 1

        agg_status = {}
        agg_status_category = {}
        agg_priority = {}
        agg_assignee = {}
        agg_issuetype = {}
        agg_project = {}
        created_by_day = {}
        resolved_by_day = {}
        total_story_points = 0
        story_points_by_status = {}

        for it in items:
            _inc(agg_status, it.get('status'))
            _inc(agg_status_category, it.get('statusCategory'))
            _inc(agg_priority, it.get('priority'))
            _inc(agg_assignee, it.get('assignee'))
            _inc(agg_issuetype, it.get('issuetype'))
            _inc(agg_project, it.get('project'))
            
            # Story points
            sp = it.get('storyPoints')
            if sp and isinstance(sp, (int, float)):
                total_story_points += sp
                status = it.get('status') or 'Unknown'
                story_points_by_status[status] = story_points_by_status.get(status, 0) + sp
            
            # Created by day
            c = it.get('created')
            if c:
                try:
                    d = c.split('T')[0]
                    created_by_day[d] = created_by_day.get(d, 0) + 1
                except Exception:
                    pass
            
            # Resolved by day
            r = it.get('resolved')
            if r:
                try:
                    d = r.split('T')[0]
                    resolved_by_day[d] = resolved_by_day.get(d, 0) + 1
                except Exception:
                    pass

        # Sort aggregates into arrays for frontend
        def to_kv_arr(d):
            return [{'key': k, 'value': d[k]} for k in sorted(d.keys(), key=lambda x: d[x], reverse=True)]

        result = {
            'success': True,
            'jiraBaseUrl': jira_domain,
            'total': len(items),
            'issues': items,
            'aggregates': {
                'byStatus': to_kv_arr(agg_status),
                'byStatusCategory': to_kv_arr(agg_status_category),
                'byPriority': to_kv_arr(agg_priority),
                'byAssignee': to_kv_arr(agg_assignee)[:15],
                'byIssueType': to_kv_arr(agg_issuetype),
                'byProject': to_kv_arr(agg_project),
                'createdByDay': [{'key': k, 'value': created_by_day[k]} for k in sorted(created_by_day.keys())],
                'resolvedByDay': [{'key': k, 'value': resolved_by_day[k]} for k in sorted(resolved_by_day.keys())],
                'storyPoints': {
                    'total': total_story_points,
                    'byStatus': to_kv_arr(story_points_by_status)
                }
            }
        }
        return jsonify(result)
    except Exception as e:
        try:
            logger.error(f"Admin run JQL error: {e}")
        except Exception:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/jira/admin/time-entries', methods=['GET'])
@jira_auth_required
@admin_required
def admin_get_time_entries_by_user():
    """Admin API: Get aggregated time entries for a specified Jira user and optional date.
    Query params:
      - q: user search query (email or display name)
      - accountId: optional exact Jira accountId (skips search if provided)
      - date: optional YYYY-MM-DD filter
    """
    q = request.args.get('q', '').strip()
    account_id = request.args.get('accountId', '').strip()
    date_filter = request.args.get('date', '').strip()

    # Use OAuth token from session instead of server credentials
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    
    if not access_token or not cloud_id:
        return jsonify({'error': 'Jira OAuth not configured. Please reconnect to Jira.'}), 401

    try:
        import requests
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        jira_base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}"

        # Resolve accountId if not provided
        user_info = None
        if not account_id:
            if not q:
                return jsonify({'error': 'Missing user query (q) or accountId'}), 400
            search_url = f'{jira_base_url}/rest/api/3/user/search'
            params = { 'query': q, 'maxResults': 10 }
            s_resp = requests.get(search_url, headers=headers, params=params, timeout=20)
            if s_resp.status_code != 200:
                return jsonify({'error': f'User search failed: {s_resp.status_code}'}), 502
            users = s_resp.json() if isinstance(s_resp.json(), list) else []
            if not users:
                return jsonify({'error': 'No Jira users matched query'}), 404
            # Basic selection: prefer exact email match, else first result
            q_lower = q.lower()
            exact = next((u for u in users if (u.get('emailAddress') or '').lower() == q_lower), None)
            user_info = exact or users[0]
            account_id = user_info.get('accountId')
        else:
            # Optionally fetch user info for display
            user_url = f'{jira_base_url}/rest/api/3/user'
            u_resp = requests.get(user_url, headers=headers, params={'accountId': account_id}, timeout=20)
            if u_resp.status_code == 200:
                user_info = u_resp.json()

        if not account_id:
            return jsonify({'error': 'Could not resolve Jira accountId for user'}), 400

        # Build JQL for specified user
        if date_filter:
            worklog_jql = f'worklogAuthor = "{account_id}" AND worklogDate = "{date_filter}"'
        else:
            worklog_jql = f'worklogAuthor = "{account_id}"'

        search_url = f'{jira_base_url}/rest/api/3/search/jql'
        search_params = {
            'jql': worklog_jql,
            'fields': 'worklog,summary',
            'maxResults': 1000
        }
        search_response = requests.get(search_url, headers=headers, params=search_params, timeout=30)
        if search_response.status_code != 200:
            return jsonify({'error': 'Failed to search for issues with worklogs'}), 500

        data = search_response.json()
        all_time_entries = []
        total_seconds = 0

        for issue in data.get('issues', []):
            issue_key = issue.get('key', 'Unknown')
            issue_summary = issue.get('fields', {}).get('summary', 'No summary available')
            worklog_data = issue.get('fields', {}).get('worklog', {})
            worklogs = worklog_data.get('worklogs', [])
            # Fetch all worklogs if Jira only returned a partial list (default 20)
            try:
                total_wl = int(worklog_data.get('total', len(worklogs)))
            except Exception:
                total_wl = len(worklogs)
            if total_wl > len(worklogs):
                all_wls = []
                fetched = 0
                while fetched < total_wl and fetched < 10000:  # sane upper bound
                    wl_url = f"{jira_base_url}/rest/api/3/issue/{issue_key}/worklog"
                    wl_params = { 'startAt': fetched, 'maxResults': 1000 }
                    wl_resp = requests.get(wl_url, headers=headers, params=wl_params, timeout=30)
                    if wl_resp.status_code != 200:
                        break
                    wl_page = wl_resp.json() or {}
                    page_items = wl_page.get('worklogs', [])
                    all_wls.extend(page_items)
                    step = wl_page.get('maxResults') or len(page_items)
                    fetched += step
                    total_wl = wl_page.get('total', total_wl)
                if all_wls:
                    worklogs = all_wls
            for wl in worklogs:
                wl_author_id = wl.get('author', {}).get('accountId', '')
                wl_started = wl.get('started', '')
                if wl_author_id != account_id:
                    continue
                if date_filter:
                    wl_date = wl_started.split('T')[0] if 'T' in wl_started else wl_started
                    if wl_date != date_filter:
                        continue
                secs = wl.get('timeSpentSeconds', 0)
                total_seconds += secs
                hours = secs // 3600
                minutes = (secs % 3600) // 60
                display = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                comment_raw = wl.get('comment', '')
                comment_text = _extract_comment_text(comment_raw)
                all_time_entries.append({
                    'id': wl.get('id', ''),
                    'issueKey': issue_key,
                    'issueSummary': issue_summary,
                    'timeSpent': display,
                    'timeSpentSeconds': secs,
                    'comment': comment_text,
                    'started': wl_started,
                    'author': wl.get('author', {}).get('displayName', (user_info or {}).get('displayName', 'User'))
                })

        aggregated = _aggregate_time_entries(all_time_entries)
        aggregated.sort(key=lambda x: x.get('started', ''), reverse=True)
        total_hours = total_seconds // 3600
        total_minutes = (total_seconds % 3600) // 60
        total_display = f"{total_hours}h {total_minutes}m" if total_hours > 0 else f"{total_minutes}m"

        return jsonify({
            'user': {
                'accountId': account_id,
                'displayName': (user_info or {}).get('displayName'),
                'emailAddress': (user_info or {}).get('emailAddress')
            },
            'timeEntries': aggregated,
            'totalTimeSeconds': total_seconds,
            'totalTimeDisplay': total_display,
            'date': date_filter,
            'entriesCount': len(aggregated)
        })

    except Exception as e:
        try:
            logger.error(f"Admin time entries error: {e}")
        except Exception:
            pass
        return jsonify({'error': f'Failed to fetch admin time entries: {str(e)}'}), 500


@app.route('/api/jira/admin/time-entries-overview', methods=['GET'])
@jira_auth_required
@admin_required
def admin_time_entries_overview():
    """Admin API: Overview of everyone's time entries for a specific date.
    Query params:
      - date: required YYYY-MM-DD
    Returns totals grouped by worklog author (user).
    """
    date_filter = request.args.get('date', '').strip()
    if not date_filter:
        return jsonify({'error': 'Missing required date (YYYY-MM-DD)'}), 400

    # Use OAuth token from session instead of server credentials
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    
    if not access_token or not cloud_id:
        return jsonify({'error': 'Jira OAuth not configured. Please reconnect to Jira.'}), 401

    try:
        import requests
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        jira_base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}"

        # Search for all issues that have worklogs on the specified date
        search_url = f'{jira_base_url}/rest/api/3/search/jql'
        start_at = 0
        page_size = 100
        max_issues = 2000  # safeguard cap
        users_map = {}  # accountId -> aggregate
        total_seconds = 0

        while start_at < max_issues:
            params = {
                'jql': f'worklogDate = "{date_filter}"',
                'fields': 'worklog',
                'startAt': start_at,
                'maxResults': page_size
            }
            resp = requests.get(search_url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                return jsonify({'error': f'Failed to search issues: {resp.status_code}'}), 500
            data = resp.json() or {}
            issues = data.get('issues', []) or []
            if not issues:
                break

            for issue in issues:
                issue_key = issue.get('key')
                worklog_data = (issue.get('fields', {}) or {}).get('worklog', {}) or {}
                worklogs = worklog_data.get('worklogs', []) or []
                # Fetch all worklogs if Jira only returned a partial list (default 20)
                try:
                    total_wl = int(worklog_data.get('total', len(worklogs)))
                except Exception:
                    total_wl = len(worklogs)
                if total_wl > len(worklogs):
                    all_wls = []
                    fetched = 0
                    while fetched < total_wl and fetched < 10000:  # sane upper bound
                        wl_url = f"{jira_base_url}/rest/api/3/issue/{issue_key}/worklog"
                        wl_params = { 'startAt': fetched, 'maxResults': 1000 }
                        wl_resp = requests.get(wl_url, headers=headers, params=wl_params, timeout=30)
                        if wl_resp.status_code != 200:
                            break
                        wl_page = wl_resp.json() or {}
                        page_items = wl_page.get('worklogs', []) or []
                        all_wls.extend(page_items)
                        step = wl_page.get('maxResults') or len(page_items)
                        fetched += step
                        total_wl = wl_page.get('total', total_wl)
                    if all_wls:
                        worklogs = all_wls

                # Aggregate by author for the specific date
                for wl in worklogs:
                    started = wl.get('started', '')
                    wl_date = started.split('T')[0] if 'T' in started else started
                    if wl_date != date_filter:
                        continue
                    secs = int(wl.get('timeSpentSeconds') or 0)
                    total_seconds += secs
                    author = wl.get('author') or {}
                    acc_id = author.get('accountId') or 'unknown'
                    agg = users_map.get(acc_id)
                    if not agg:
                        agg = {
                            'accountId': acc_id,
                            'displayName': author.get('displayName') or 'User',
                            'emailAddress': author.get('emailAddress'),
                            'timeSpentSeconds': 0,
                            'entriesCount': 0
                        }
                        users_map[acc_id] = agg
                    agg['timeSpentSeconds'] += secs
                    agg['entriesCount'] += 1

            start_at += len(issues)
            total = data.get('total', start_at)
            if start_at >= total or start_at >= max_issues:
                break

        # Prepare response
        def fmt(secs: int) -> str:
            h = secs // 3600
            m = (secs % 3600) // 60
            return f"{h}h {m}m" if h > 0 else f"{m}m"

        users = []
        for acc_id, agg in users_map.items():
            users.append({
                **agg,
                'timeSpent': fmt(agg['timeSpentSeconds'])
            })
        users.sort(key=lambda x: x['timeSpentSeconds'], reverse=True)

        return jsonify({
            'success': True,
            'date': date_filter,
            'totalUsers': len(users),
            'totalTimeSeconds': total_seconds,
            'totalTimeDisplay': fmt(total_seconds),
            'users': users
        })
    except Exception as e:
        try:
            logger.error(f"Admin overview time entries error: {e}")
        except Exception:
            pass
        return jsonify({'error': f'Failed to fetch overview: {str(e)}'}), 500

# ===================== Admin: Jira Users Directory =====================
@app.route('/api/jira/admin/sync-users', methods=['POST'])
@jira_auth_required
@admin_required
def admin_sync_jira_users():
    """Admin API: Sync Jira users into local DB for fast lookup/autocomplete.
    Uses OAuth token + cloud_id from session and pages through Jira users/search.
    """
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    if not access_token:
        return jsonify({'error': 'Jira authentication required'}), 401
    if not cloud_id:
        return jsonify({'error': 'Jira cloud ID not found in session'}), 400

    import requests
    # Ensure token is fresh
    try:
        token_expires = session.get('jira_token_expires', 0)
        if time.time() >= token_expires:
            if not refresh_jira_token():
                return jsonify({'error': 'Token expired. Please reconnect to Jira.'}), 401
            access_token = session.get('jira_access_token')
    except Exception:
        pass

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    base_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/users/search'

    start_at = 0
    max_results = 100
    inserted = 0
    updated = 0
    total = 0

    try:
        retried_auth = False
        while True:
            params = {
                'startAt': start_at,
                'maxResults': max_results,
                'query': ''
            }
            resp = requests.get(base_url, headers=headers, params=params, timeout=30)
            if resp.status_code == 401 and not retried_auth:
                # Try token refresh once and retry
                if refresh_jira_token():
                    access_token = session.get('jira_access_token')
                    headers['Authorization'] = f'Bearer {access_token}'
                    resp = requests.get(base_url, headers=headers, params=params, timeout=30)
                    retried_auth = True
            if resp.status_code != 200:
                # Return more detailed error to aid debugging (status + body snippet)
                body = ''
                try:
                    body = resp.text[:500]
                except Exception:
                    body = ''
                return jsonify({'error': f'Jira users search failed: {resp.status_code}', 'details': body}), 502
            page = resp.json() or []
            if not isinstance(page, list):
                page = []
            if not page:
                break

            for u in page:
                total += 1
                account_id = u.get('accountId')
                if not account_id:
                    continue
                display_name = u.get('displayName')
                email = u.get('emailAddress')  # May be None due to privacy settings
                avatar_48 = (u.get('avatarUrls', {}) or {}).get('48x48')
                active = bool(u.get('active', True))
                time_zone = u.get('timeZone')

                existing = JiraUser.query.filter_by(account_id=account_id).first()
                if existing:
                    # Update existing
                    existing.display_name = display_name
                    existing.email = email
                    existing.avatar_48 = avatar_48
                    existing.active = active
                    existing.time_zone = time_zone
                    existing.synced_at = datetime.utcnow()
                    updated += 1
                else:
                    db.session.add(JiraUser(
                        account_id=account_id,
                        display_name=display_name,
                        email=email,
                        avatar_48=avatar_48,
                        active=active,
                        time_zone=time_zone,
                        synced_at=datetime.utcnow()
                    ))
                    inserted += 1

            db.session.commit()
            if len(page) < max_results:
                break
            start_at += max_results

        return jsonify({
            'success': True,
            'inserted': inserted,
            'updated': updated,
            'totalProcessed': total,
            'lastSync': datetime.utcnow().isoformat() + 'Z'
        })
    except Exception as e:
        db.session.rollback()
        try:
            logger.error(f"Admin sync users error: {e}")
        except Exception:
            pass
        return jsonify({'error': f'Failed to sync Jira users: {str(e)}'}), 500


@app.route('/api/jira/admin/users', methods=['GET'])
@jira_auth_required
@admin_required
def admin_search_local_jira_users():
    """Admin API: Search locally stored Jira users for autocomplete.
    Query params: q (string), limit (int, default 20)
    """
    q = (request.args.get('q') or '').strip()
    try:
        limit = int(request.args.get('limit') or 20)
        limit = max(1, min(limit, 50))
    except Exception:
        limit = 20

    query = JiraUser.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            JiraUser.display_name.ilike(like),
            JiraUser.email.ilike(like)
        ))
    users = query.order_by(JiraUser.display_name.asc()).limit(limit).all()
    return jsonify({'results': [u.to_dict() for u in users], 'count': len(users)})
def extract_issues_manually(text):
    """
    Extract issues and recommendations from raw AI response text when JSON parsing fails.
    Uses regex patterns to find issues and recommendations in the text.
    """
    logger.info("Attempting to extract issues manually from text")
    
    result = {
        'issues': [],
        'recommendations': [],
        'overallScore': 70,  # Default moderate score for manual extraction
        'factorScores': {
            'accessibility': 70,
            'designConsistency': 70,
            'usability': 70,
            'visualHierarchy': 70,
            'responsiveness': 70
        },
        'summary': 'UI analysis completed using manual text extraction due to parsing issues.'
    }
    
    # Extract issues
    issue_patterns = [
        r'(?:Issue|Problem|Concern)\s*\d*\s*:\s*([^\n.]+)',  # Issue: Text
        r'"title"\s*:\s*"([^"]+)"',  # "title": "Text"
        r'\*\*([^*]+)\*\*',  # **Text** (markdown bold)
        r'- ([A-Z][^\n.]+)'  # - Capitalized text
    ]
    
    for pattern in issue_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            logger.info(f"Found {len(matches)} issues using pattern: {pattern}")
            for i, match in enumerate(matches):
                issue_title = match.group(1).strip()
                # Skip if it looks like a recommendation
                if any(rec_word in issue_title.lower() for rec_word in ['recommend', 'suggestion', 'improve', 'enhance']):
                    continue
                    
                # Create a structured issue
                severity = 'Medium'  # Default severity
                # Try to detect severity
                if any(high_word in text[max(0, match.start()-50):match.start()+len(match.group(0))+50].lower() 
                       for high_word in ['critical', 'high', 'severe', 'major']):
                    severity = 'High'
                elif any(low_word in text[max(0, match.start()-50):match.start()+len(match.group(0))+50].lower() 
                         for low_word in ['minor', 'low', 'small', 'slight']):
                    severity = 'Low'
                
                result['issues'].append({
                    'title': issue_title,
                    'severity': severity,
                    'description': issue_title,  # Use title as description if no specific description found
                    'location': 'UI Element'  # Default location
                })
                
                # Limit to 5 issues to avoid noise
                if len(result['issues']) >= 5:
                    break
            
            if result['issues']:
                break  # Stop after finding issues with one pattern
    
    # Extract recommendations
    rec_patterns = [
        r'(?:Recommendation|Suggestion)\s*\d*\s*:\s*([^\n.]+)',  # Recommendation: Text
        r'- ([Rr]ecommend[^\n.]+)',  # - Recommend...
        r'"recommendation"\s*:\s*"([^"]+)"'  # "recommendation": "Text"
    ]
    
    for pattern in rec_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            logger.info(f"Found {len(matches)} recommendations using pattern: {pattern}")
            for match in matches:
                result['recommendations'].append(match.group(1).strip())
            break  # Stop after finding recommendations with one pattern
    
    return result

def find_potential_misspellings(text):
    """
    Analyze OCR text to find potential misspellings or unusual words.
    Returns a list of potentially misspelled words.
    """
    if not text or text == "OCR text extraction not available (Tesseract not installed)":
        return []
        
    # Split text into words
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text)
    
    # Common UI words that might be flagged incorrectly
    common_ui_words = {
        'login', 'signup', 'navbar', 'dropdown', 'checkbox', 'tooltip', 'popup',
        'modal', 'sidebar', 'footer', 'header', 'button', 'submit', 'cancel',
        'username', 'password', 'email', 'admin', 'dashboard', 'logout', 'profile',
        'settings', 'notification', 'menu', 'toggle', 'slider', 'checkbox',
        'radio', 'input', 'form', 'label', 'placeholder', 'textarea', 'select',
        'option', 'datepicker', 'timepicker', 'calendar', 'pagination', 'breadcrumb',
        'accordion', 'tab', 'panel', 'dialog', 'alert', 'toast', 'badge', 'card',
        'carousel', 'spinner', 'loader', 'progress', 'avatar', 'icon', 'tooltip',
        'popover', 'navbar', 'toolbar', 'sidebar', 'offcanvas', 'collapse', 'dropdown'
    }
    
    # Simple heuristic: words with unusual character patterns
    potential_misspellings = []
    for word in words:
        word_lower = word.lower()
        
        # Skip common UI words
        if word_lower in common_ui_words:
            continue
            
        # Check for unusual character patterns
        if (len(word) >= 4 and 
            ('zx' in word_lower or 'qp' in word_lower or 'vf' in word_lower) or
            (word_lower.count('z') > 1) or
            (word_lower.count('q') > 1) or
            (word_lower.count('x') > 1)):
            potential_misspellings.append(word)
            
        # Check for repeated characters (more than 2)
        for i in range(len(word) - 2):
            if word[i] == word[i+1] == word[i+2]:
                potential_misspellings.append(word)
                break
    
    return potential_misspellings[:5]  # Limit to 5 potential issues

@app.route('/ui-analyzer')
@jira_auth_required
def ui_analyzer():
    return render_template('screen-analysis-redesigned.html', active_tab='screen-analysis')

# Keep old route for backward compatibility
@app.route('/screen-analysis')
@jira_auth_required
def screen_analysis():
    return redirect('/ui-analyzer', code=301)

@app.route('/api/rest/execute', methods=['POST'])
def execute_rest_request():
    """Execute a comprehensive REST API request with advanced features"""
    try:
        data = request.get_json()
        
        # Extract comprehensive request details
        url = data.get('url', '')
        method = data.get('method', 'GET').upper()
        headers = data.get('headers', {})
        params = data.get('params', {})
        body = data.get('body', '')
        body_type = data.get('bodyType', 'none')
        auth = data.get('auth', {})
        environment = data.get('environment', {})
        timeout = data.get('timeout', 30)
        follow_redirects = data.get('followRedirects', True)
        verify_ssl = data.get('verifySsl', True)
        
        # Apply environment variables
        url = substitute_environment_variables(url, environment)
        headers = {k: substitute_environment_variables(str(v), environment) for k, v in headers.items() if v}
        params = {k: substitute_environment_variables(str(v), environment) for k, v in params.items() if v}
        
        # Handle authentication
        auth_obj = None
        if auth.get('type') == 'basic':
            auth_obj = (auth.get('username', ''), auth.get('password', ''))
        elif auth.get('type') == 'bearer':
            headers['Authorization'] = f"Bearer {auth.get('token', '')}"
        elif auth.get('type') == 'api_key':
            if auth.get('in') == 'header':
                headers[auth.get('key', 'X-API-Key')] = auth.get('value', '')
            elif auth.get('in') == 'query':
                params[auth.get('key', 'api_key')] = auth.get('value', '')
        
        # Handle request body based on type
        request_kwargs = {}
        if body and body_type != 'none':
            if body_type == 'json':
                try:
                    request_kwargs['json'] = json.loads(body) if isinstance(body, str) else body
                    if 'Content-Type' not in headers:
                        headers['Content-Type'] = 'application/json'
                except json.JSONDecodeError:
                    return jsonify({'error': 'Invalid JSON in request body'}), 400
            elif body_type == 'text':
                request_kwargs['data'] = body
            elif body_type == 'form':
                try:
                    form_data = json.loads(body) if isinstance(body, str) else body
                    request_kwargs['data'] = form_data
                    if 'Content-Type' not in headers:
                        headers['Content-Type'] = 'application/x-www-form-urlencoded'
                except:
                    request_kwargs['data'] = body
            elif body_type == 'xml':
                request_kwargs['data'] = body
                if 'Content-Type' not in headers:
                    headers['Content-Type'] = 'application/xml'
        
        # Measure execution time
        start_time = time.time()
        
        # Make the request with comprehensive error handling
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                auth=auth_obj,
                timeout=timeout,
                allow_redirects=follow_redirects,
                verify=verify_ssl,
                **request_kwargs
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            # Parse response body
            response_body = response.text
            content_type = response.headers.get('content-type', '').lower()
            
            try:
                if 'application/json' in content_type:
                    json_data = response.json()
                    # Return formatted JSON for better readability
                    response_body = json.dumps(json_data, indent=2)
                elif 'application/xml' in content_type or 'text/xml' in content_type:
                    # Keep as text for XML
                    pass
            except:
                pass
            
            # Extract cookies
            cookies = []
            for cookie in response.cookies:
                cookies.append({
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': cookie.domain,
                    'path': cookie.path,
                    'secure': cookie.secure,
                    'httpOnly': cookie.has_nonstandard_attr('HttpOnly')
                })
            
            # Response headers as list for better display
            response_headers = [{'key': k, 'value': v} for k, v in response.headers.items()]
            
            return jsonify({
                'success': True,
                'status': response.status_code,
                'statusText': response.reason,
                'headers': response_headers,
                'body': response_body,
                'cookies': cookies,
                'time': round(execution_time, 2),
                'size': len(response.content),
                'redirects': len(response.history) if hasattr(response, 'history') else 0,
                'finalUrl': response.url
            })
            
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False,
                'error': 'Request timeout',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 408
        except requests.exceptions.ConnectionError as e:
            return jsonify({
                'success': False,
                'error': f'Connection error: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 503
        except requests.exceptions.SSLError as e:
            return jsonify({
                'success': False,
                'error': f'SSL verification failed: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 495
        except requests.exceptions.HTTPError as e:
            return jsonify({
                'success': False,
                'error': f'HTTP error: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 400
            
    except Exception as e:
        logger.error(f"Error executing REST request: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500

def substitute_environment_variables(text, environment):
    """Replace {{variable}} with environment values"""
    if not isinstance(text, str) or not environment:
        return text
    
    import re
    def replace_var(match):
        var_name = match.group(1)
        return environment.get(var_name, match.group(0))
    
    return re.sub(r'\{\{(\w+)\}\}', replace_var, text)

@app.route('/api/environment/validate', methods=['POST'])
def validate_environment():
    """Validate environment variables in a request"""
    try:
        data = request.get_json()
        url = data.get('url', '')
        headers = data.get('headers', {})
        body = data.get('body', '')
        environment = data.get('environment', {})
        
        # Find all variables
        import re
        variables_found = set()
        
        # Search in URL
        variables_found.update(re.findall(r'\{\{(\w+)\}\}', url))
        
        # Search in headers
        for value in headers.values():
            if isinstance(value, str):
                variables_found.update(re.findall(r'\{\{(\w+)\}\}', value))
        
        # Search in body
        if isinstance(body, str):
            variables_found.update(re.findall(r'\{\{(\w+)\}\}', body))
        
        # Check which variables are missing
        missing_variables = []
        available_variables = []
        
        for var in variables_found:
            if var in environment:
                available_variables.append(var)
            else:
                missing_variables.append(var)
        
        return jsonify({
            'variables': list(variables_found),
            'available': available_variables,
            'missing': missing_variables,
            'isValid': len(missing_variables) == 0
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/capture-url', methods=['POST'])
def capture_url():
    """Capture a screenshot of a website URL"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
        
        url = data['url']
        
        # Auto-resolve URL if needed (add https:// if no protocol)
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Validate URL format
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.netloc:
                return jsonify({'success': False, 'error': 'Invalid URL format'}), 400
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid URL format'}), 400
        
        # Import selenium for web scraping
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            import base64
            import time
        except ImportError:
            return jsonify({
                'success': False, 
                'error': 'Selenium not installed. Please install selenium and chromedriver for URL capture functionality.'
            }), 500
        
        # Setup Chrome options
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-plugins')
        chrome_options.add_argument('--disable-images')  # Speed up loading
        
        driver = None
        urls_to_try = [url]
        
        # If we're trying HTTPS, also prepare HTTP fallback
        if url.startswith('https://'):
            http_url = url.replace('https://', 'http://', 1)
            urls_to_try.append(http_url)
        
        last_error = None
        
        for attempt_url in urls_to_try:
            try:
                # Initialize Chrome driver
                driver = webdriver.Chrome(options=chrome_options)
                driver.set_page_load_timeout(30)  # 30 second timeout
                
                # Navigate to URL
                driver.get(attempt_url)
                
                # Wait for page to load
                time.sleep(3)
                
                # Take screenshot
                screenshot_base64 = driver.get_screenshot_as_base64()
                
                return jsonify({
                    'success': True,
                    'image': screenshot_base64,
                    'url': attempt_url
                })
                
            except Exception as e:
                last_error = e
                logging.warning(f"Failed to capture {attempt_url}: {str(e)}")
                
                if driver:
                    driver.quit()
                    driver = None
                
                # If this was HTTPS and we have HTTP to try, continue
                if attempt_url.startswith('https://') and len(urls_to_try) > 1:
                    continue
                else:
                    break
            
            finally:
                if driver:
                    driver.quit()
                    driver = None
        
        # If we get here, all attempts failed
        error_message = f'Failed to capture screenshot: {str(last_error)}'
        if len(urls_to_try) > 1:
            error_message += ' (tried both HTTPS and HTTP)'
            
        logging.error(f"Error capturing URL screenshot after all attempts: {error_message}")
        return jsonify({
            'success': False,
            'error': error_message
        }), 500
                
    except Exception as e:
        logging.error(f"URL capture error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def _safe_js_identifier(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", name or "")
    if not name:
        name = "el"
    if re.match(r"^\d", name):
        name = "el_" + name
    return name

def _build_locator_chain_js(locators):
    parts = []
    for loc in locators:
        sel = auto_healing_recorder.convert_to_playwright_selector(loc)
        sel = sel.replace('\\', '\\\\').replace("'", r"\'")
        parts.append(f"this.page.locator('{sel}')")
    if not parts:
        return "this.page.locator('[data-qa-missing]')"
    chain = parts[0]
    for p in parts[1:]:
        chain = f"{chain}.or({p})"
    return chain

@app.route('/api/pom/generate', methods=['POST'])
@jira_auth_required
def generate_pom():
    """Generate a JavaScript Page Object with auto-healing locator chains.
    Accepts: {
      session_id?, url?, class_name?, replay_to_state?, storage_state_json?, storage_state_path?,
      elements?: [{ name: str, seed?: str }]
      elements_text?: "name=seed\n..."
    }
    Returns: { js_code, manifest }
    """
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        sess = auto_healing_recorder.get_session(session_id) if session_id else None
        url = data.get('url') or (sess or {}).get('url')
        if not url:
            return jsonify({'success': False, 'error': 'No URL provided or in session'}), 400

        class_name = data.get('class_name') or 'GeneratedPage'
        class_name = re.sub(r"[^a-zA-Z0-9_]", "", class_name) or 'GeneratedPage'

        # Parse element specs
        elements = data.get('elements') or []
        if not elements and data.get('elements_text'):
            lines = [l.strip() for l in str(data.get('elements_text')).splitlines() if l.strip()]
            for ln in lines:
                if '=' in ln:
                    n, s = ln.split('=', 1)
                    elements.append({'name': n.strip(), 'seed': s.strip()})
                else:
                    elements.append({'name': ln.strip()})
        # If still empty, fall back to using recorded actions as candidates
        if not elements and session_id:
            actions = auto_healing_recorder.recorded_actions.get(session_id, [])
            for idx, act in enumerate(actions):
                nm = act.get('data', {}).get('name') or act.get('element_info', {}).get('data-testid') or act.get('element_info', {}).get('id') or act.get('element_info', {}).get('text') or f'el_{idx+1}'
                elements.append({'name': str(nm)[:50]})

        if not elements:
            return jsonify({'success': False, 'error': 'No elements provided to generate POM'}), 400

        # Options
        storage_state_json = data.get('storage_state_json')
        storage_state_path = data.get('storage_state_path')
        replay_to_state = bool(data.get('replay_to_state'))

        storage_state = None
        if storage_state_json:
            try:
                storage_state = json.loads(storage_state_json)
            except Exception as e:
                return jsonify({'success': False, 'error': f'Invalid storage_state_json: {e}'}), 400
        elif storage_state_path:
            storage_state = storage_state_path

        # Result containers
        manifest = {
            'className': class_name,
            'url': url,
            'elements': []
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=os.getenv('PLAYWRIGHT_HEADLESS', 'false').lower() == 'true')
            context = browser.new_context(storage_state=storage_state) if storage_state else browser.new_context()
            page = context.new_page()

            def _navigate():
                page.goto(url)
                page.wait_for_load_state('networkidle')

            def _perform_action(act):
                atype = (act.get('type') or '').lower()
                locs = act.get('locators') or []
                for loc in locs:
                    sel = auto_healing_recorder.convert_to_playwright_selector(loc)
                    try:
                        l = page.locator(sel).first
                        if l.count() == 0:
                            continue
                        if atype == 'click':
                            l.click(timeout=5000)
                            return True
                        elif atype == 'fill':
                            val = (act.get('data') or {}).get('value', '')
                            l.fill(val, timeout=5000)
                            return True
                        elif atype == 'select':
                            val = (act.get('data') or {}).get('value', '')
                            l.select_option(val, timeout=5000)
                            return True
                    except Exception:
                        continue
                return False

            # Optional replay of recorded actions to reach deep state
            acts = auto_healing_recorder.recorded_actions.get(session_id, []) if session_id else []

            for el in elements:
                name = _safe_js_identifier(el.get('name'))
                seed = el.get('seed')
                _navigate()
                if replay_to_state and acts:
                    for a in acts:
                        _perform_action(a)
                        try:
                            page.wait_for_load_state('networkidle', timeout=3000)
                        except Exception:
                            pass

                handle = None
                # Try seed first if provided
                seeds = []
                if seed: seeds.append(seed)
                # else try to find by text/id/testid hints from recorded actions
                # Not strictly necessary; seeds can be empty

                for s in seeds or ['']:  # if no seed, skip to mining via generic heuristics by querying common candidates
                    try:
                        if not s:
                            break
                        loc = page.locator(s)
                        if loc.count() > 0:
                            handle = loc.first
                            break
                    except Exception:
                        continue

                # If no handle yet, skip enrichment for this element
                if not handle:
                    # record as empty with just the name
                    manifest['elements'].append({'name': name, 'locators': []})
                    continue

                # Harvest attributes similar to enrichment
                def attr(nm):
                    try:
                        return handle.get_attribute(nm)
                    except Exception:
                        return None

                el_info = {}
                got_id = attr('id')
                if got_id and _looks_stable_token(got_id):
                    el_info['id'] = got_id
                for test_key in ['data-testid', 'data-test', 'data-qa']:
                    v = attr(test_key)
                    if v and _looks_stable_token(v):
                        el_info['data-testid'] = v
                        break
                for k in ['name', 'placeholder', 'aria-label', 'title']:
                    v = attr(k)
                    if v and v.strip():
                        if k == 'aria-label':
                            el_info['aria_label'] = v.strip()
                        else:
                            el_info[k] = v.strip()
                try:
                    txt = handle.inner_text().strip()
                    if txt and len(txt) <= 120:
                        el_info['text'] = txt
                except Exception:
                    pass
                try:
                    cls = handle.evaluate("el => (el.className || '').toString()") or ''
                    if cls:
                        tokens = [t for t in re.split(r"\s+", cls) if _looks_stable_token(t)]
                        if tokens:
                            el_info['class'] = ' '.join(tokens[:3])
                            tag = handle.evaluate("el => el.tagName.toLowerCase()")
                            el_info['css_selector'] = f"{tag}{''.join(['.'+t for t in tokens[:3]])}"
                except Exception:
                    pass

                locators = auto_healing_recorder.generate_auto_healing_locators(el_info)
                manifest['elements'].append({'name': name, 'locators': locators})

            context.close()
            browser.close()

        # Build JS class code
        lines = []
        lines.append(f"export default class {class_name} {{")
        lines.append("  constructor(page) { this.page = page; }")
        for el in manifest['elements']:
            nm = el['name']
            locs = el['locators']
            chain = _build_locator_chain_js(locs)
            lines.append("")
            lines.append(f"  {nm}() {{")
            lines.append(f"    return {chain};")
            lines.append("  }")
        lines.append("}")
        js_code = "\n".join(lines)

        return jsonify({'success': True, 'js_code': js_code, 'manifest': manifest})
    except Exception as e:
        logging.error(f"Error generating POM: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def _looks_stable_token(token: str) -> bool:
    if not token:
        return False
    if len(token) > 32:
        return False
    # Reject UUID-like or hashed tokens
    if re.match(r"^[a-f0-9]{8,}$", token, re.IGNORECASE):
        return False
    # Too many digits
    if re.search(r"\d{4,}", token):
        return False
    return True

def _build_seed_selectors(recorder, element_data: dict):
    seeds = []
    locs = recorder.generate_auto_healing_locators(element_data)
    for loc in locs:
        seeds.append(recorder.convert_to_playwright_selector(loc))
    # include raw css/xpath if present
    if element_data.get('css_selector'):
        seeds.insert(0, element_data['css_selector'])
    if element_data.get('xpath'):
        seeds.append(f"xpath={element_data['xpath']}")
    # dedup preserving order
    dedup = []
    seen = set()
    for s in seeds:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup

@app.route('/api/recorder-v2/enrich-locators', methods=['POST'])
@jira_auth_required
def enrich_recorder_v2_locators():
    """Re-locate elements on the live page and enrich locator strategies per action.
    Supports:
      - storage_state_json / storage_state_path: to load authenticated state
      - replay_to_state: replay prior actions to reach the right UI before enrichment
    """
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'No active session found'}), 400

        sess = auto_healing_recorder.get_session(session_id) or {}
        url = data.get('url') or sess.get('url')
        if not url:
            return jsonify({'success': False, 'error': 'Session has no URL'}), 400

        actions = auto_healing_recorder.recorded_actions.get(session_id, [])
        if not actions:
            return jsonify({'success': False, 'error': 'No actions to enrich'}), 400

        if not playwright_available:
            return jsonify({'success': False, 'error': 'Playwright not available on server'}), 500

        # Options
        storage_state_json = data.get('storage_state_json')
        storage_state_path = data.get('storage_state_path')
        replay_to_state = bool(data.get('replay_to_state'))

        # Parse storage state if provided
        storage_state = None
        if storage_state_json:
            try:
                storage_state = json.loads(storage_state_json)
            except Exception as e:
                return jsonify({'success': False, 'error': f'Invalid storage_state_json: {e}'}), 400
        elif storage_state_path:
            storage_state = storage_state_path  # Playwright accepts path

        enriched_count = 0
        # Launch a temporary browser, navigate to URL once
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=os.getenv('PLAYWRIGHT_HEADLESS', 'false').lower() == 'true')
            # create context with optional storage state
            context = browser.new_context(storage_state=storage_state) if storage_state else browser.new_context()
            page = context.new_page()
            
            def _navigate_fresh():
                page.goto(url)
                page.wait_for_load_state('networkidle')

            def _perform_action(act):
                atype = (act.get('type') or '').lower()
                locs = act.get('locators') or []
                # Try each locator in order
                for loc in locs:
                    sel = auto_healing_recorder.convert_to_playwright_selector(loc)
                    try:
                        l = page.locator(sel).first
                        if l.count() == 0:
                            continue
                        if atype == 'click':
                            l.click(timeout=5000)
                            return True
                        elif atype == 'fill':
                            val = (act.get('data') or {}).get('value', '')
                            l.fill(val, timeout=5000)
                            return True
                        elif atype == 'select':
                            val = (act.get('data') or {}).get('value', '')
                            l.select_option(val, timeout=5000)
                            return True
                        elif atype == 'check':
                            l.check(timeout=5000)
                            return True
                        elif atype == 'uncheck':
                            l.uncheck(timeout=5000)
                            return True
                        else:
                            # Unsupported action types are skipped
                            continue
                    except Exception:
                        continue
                return False

            def _find_handle_for_action(act):
                el_info = dict(act.get('element_info') or {})
                seed_selectors = _build_seed_selectors(auto_healing_recorder, el_info)
                for s in seed_selectors:
                    try:
                        loc = page.locator(s)
                        if loc.count() > 0:
                            return loc.first
                    except Exception:
                        continue
                return None

            for idx, action in enumerate(actions):
                # Recreate page state for each action if needed
                _navigate_fresh()
                if replay_to_state and idx > 0:
                    for j in range(0, idx):
                        _perform_action(actions[j])
                        # best-effort wait after interactions
                        try:
                            page.wait_for_load_state('networkidle', timeout=3000)
                        except Exception:
                            pass

                el_info = dict(action.get('element_info') or {})
                if not el_info:
                    continue
                handle = _find_handle_for_action(action)
                if not handle:
                    continue

                # Harvest attributes
                def attr(name):
                    try:
                        return handle.get_attribute(name)
                    except Exception:
                        return None

                got_id = attr('id')
                if got_id and _looks_stable_token(got_id):
                    el_info['id'] = got_id

                for test_key in ['data-testid', 'data-test', 'data-qa']:
                    val = attr(test_key)
                    if val and _looks_stable_token(val):
                        # normalize to data-testid primary key
                        el_info['data-testid'] = val
                        break

                for name_key in ['name', 'placeholder', 'aria-label', 'title']:
                    val = attr(name_key)
                    if val and val.strip():
                        if name_key == 'aria-label':
                            el_info['aria_label'] = val.strip()
                        else:
                            el_info[name_key if name_key != 'aria-label' else 'aria_label'] = val.strip()

                # text content
                try:
                    txt = handle.inner_text().strip()
                    if txt and len(txt) <= 120:
                        el_info['text'] = txt
                except Exception:
                    pass

                # class filtering for stable CSS
                try:
                    cls = handle.evaluate("el => (el.className || '').toString()") or ''
                    if cls:
                        tokens = [t for t in re.split(r"\s+", cls) if _looks_stable_token(t)]
                        if tokens:
                            # limit to top 3 stable tokens
                            el_info['class'] = ' '.join(tokens[:3])
                            # simple css by tag + classes
                            tag = handle.evaluate("el => el.tagName.toLowerCase()")
                            el_info['css_selector'] = f"{tag}{''.join(['.'+t for t in tokens[:3]])}"
                except Exception:
                    pass

                # Recompute locators and update action
                action['element_info'] = el_info
                action['locators'] = auto_healing_recorder.generate_auto_healing_locators(el_info)
                enriched_count += 1

            context.close()
            browser.close()

        return jsonify({
            'success': True,
            'enriched_count': enriched_count,
            'actions_preview': actions[-10:]  # send last 10 for UI refresh
        })
    except Exception as e:
        logger.error(f"Error enriching locators: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/analyze-screen', methods=['POST'])
@llm_rate_limit
def analyze_screen():
    # Handle both FormData (new frontend) and JSON (legacy)
    if request.content_type and 'multipart/form-data' in request.content_type:
        # New FormData approach
        screenshots = []
        figma_file = None
        options = {}
        
        # Get screenshots
        for key in request.files:
            if key.startswith('screenshot_'):
                screenshots.append(request.files[key])
            elif key == 'url_screenshot':
                screenshots.append(request.files[key])
        
        # Get URL source if available
        url_source = request.form.get('url_source', '')
        
        # Get figma file
        if 'figma_design' in request.files:
            figma_file = request.files['figma_design']
        
        # Get options
        if 'options' in request.form:
            try:
                options = json.loads(request.form['options'])
            except:
                options = {}
        
        if not screenshots:
            return jsonify({'error': 'No screenshot files provided'}), 400
        
        # Process first screenshot for now
        main_screenshot = screenshots[0]
        
        # Save screenshot to temporary file with proper handle management
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()  # Close the file handle immediately
        
        # Now save the screenshot to the closed temp file
        main_screenshot.save(temp_path)
    else:
        # Legacy JSON approach
        data = request.get_json()
        
        if not data or 'screenshot' not in data:
            return jsonify({'error': 'No screenshot data provided'}), 400
    
        # Extract image data from base64 string
        image_data = data['screenshot']
        if image_data.startswith('data:image'):
            # Remove the data URL prefix
            image_data = image_data.split(',')[1]
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        
        # Create a temporary file to save the image with proper handle management
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.write(image_bytes)
        temp_file.close()  # Close the file handle immediately
        # Extract options and figma data
        options = data.get('options', {})
        figma_design = data.get('figmaDesign', None)
        comparison_focus = data.get('comparisonFocus', {})
    
    try:
        # Handle figma file for FormData requests
        if request.content_type and 'multipart/form-data' in request.content_type and figma_file:
            # Process Figma file
            figma_design = {
                'type': 'image' if figma_file.content_type.startswith('image/') else 'text',
                'filename': figma_file.filename
            }
            
            if figma_design['type'] == 'image':
                # Save figma file temporarily and encode as base64 with proper handle management
                figma_temp = tempfile.NamedTemporaryFile(delete=False)
                figma_temp_path = figma_temp.name
                figma_temp.close()  # Close handle immediately
                
                try:
                    figma_file.save(figma_temp_path)
                    with open(figma_temp_path, 'rb') as f:
                        figma_base64 = base64.b64encode(f.read()).decode()
                    figma_design['data'] = f"data:{figma_file.content_type};base64,{figma_base64}"
                finally:
                    # Clean up immediately
                    if os.path.exists(figma_temp_path):
                        try:
                            os.unlink(figma_temp_path)
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup Figma temp file: {cleanup_error}")
            else:
                # Read text/json content
                figma_content = figma_file.read().decode('utf-8')
                if figma_file.filename.endswith('.json'):
                    try:
                        figma_design['data'] = json.loads(figma_content)
                        figma_design['type'] = 'json'
                    except:
                        figma_design['data'] = figma_content
                        figma_design['type'] = 'text'
                else:
                    figma_design['data'] = figma_content
        
        # Extract Figma comparison options if present
        figma_compare = options.get('figma', False)  # Updated key name
        comparison_focus = options  # Use options directly for focus areas
        
        # Open image with PIL for analysis
        image = None
        try:
            image = Image.open(temp_path)
            
            # Try to extract text using OCR if Tesseract is available
            ocr_text = ""
            ocr_available = True
            try:
                ocr_text = pytesseract.image_to_string(image)
                logger.info("Successfully extracted text using OCR")
            except Exception as e:
                logger.warning(f"OCR extraction failed: {str(e)}. Continuing without OCR.")
                ocr_text = ""
                ocr_available = False
        except Exception as e:
            logger.error(f"Error opening image: {str(e)}")
            return jsonify({'error': 'Failed to process image'}), 500
        
            # Close the image to release file handle
            image.close()
            image = None
            
        except Exception as e:
            logger.error(f"Error opening image: {str(e)}")
            ocr_text = ""
            ocr_available = False
            if image:
                image.close()
        
        # Prepare image for AI analysis
        with open(temp_path, 'rb') as f:
            image_bytes = f.read()
        
        # Create prompt for AI analysis based on selected options
        prompt = "You are an expert UI/UX analyst specializing in identifying UI issues from screenshots. Analyze this UI screenshot and identify potential issues. BE CRITICAL, THOROUGH and SPECIFIC in your analysis. Even minor issues should be reported with clear explanations. "
        if options.get('alignment', True):
            prompt += "Check for alignment issues, uneven spacing, and layout problems. Look for elements that are not properly aligned or have inconsistent spacing. Identify specific misalignments with their exact locations. "
        if options.get('text', True):
            prompt += "Identify any text quality issues, spelling errors, typos, grammatical errors, or readability problems. Pay special attention to text that appears cut off, overlapping, or has poor contrast. Quote the problematic text when possible. "
        if options.get('contrast', True):
            prompt += "Evaluate color contrast and accessibility concerns. Check if text is readable against its background and if colors meet WCAG accessibility standards. Specify which elements have contrast issues and why they're problematic. "
        if options.get('consistency', True):
            prompt += "Look for UI inconsistencies in styling, fonts, or component usage. Check for mismatched styles, font sizes, or inconsistent UI elements. Point out specific inconsistencies between elements. "
        
        prompt += "\n\nIMPORTANT INSTRUCTIONS:\n"
        prompt += "1. You MUST identify at least one issue if anything in the UI could be improved, even slightly.\n"
        prompt += "2. Be specific about the location of each issue.\n"
        prompt += "3. Provide actionable recommendations for each issue.\n"
        prompt += "4. ALWAYS respond in valid JSON format.\n"
        prompt += "5. Do not say 'no issues found' unless the UI is absolutely perfect.\n\n"
        
        prompt += "Format your response STRICTLY as a JSON object with these properties: \n"
        prompt += "1. 'overallScore': Overall UI health score (0-100)\n"
        prompt += "2. 'factorScores': Object with scores for each factor: accessibility (0-100), designConsistency (0-100), usability (0-100), visualHierarchy (0-100), responsiveness (0-100)\n"
        prompt += "3. 'issues': Array of objects with {title, severity (High/Medium/Low), description, location, impact (0-10)}\n"
        prompt += "4. 'recommendations': Array of objects with {title, priority (High/Medium/Low), description, expectedImprovement (0-10)}\n"
        prompt += "5. 'summary': Brief summary of the overall assessment\n\n"
        prompt += "SCORING GUIDELINES:\n"
        prompt += "- Overall Score: 90-100 (Excellent), 80-89 (Good), 70-79 (Fair), 60-69 (Poor), <60 (Critical Issues)\n"
        prompt += "- Factor Scores: Rate each factor independently based on best practices\n"
        prompt += "- Impact: How much each issue affects user experience (1=minimal, 10=critical)\n"
        prompt += "- Expected Improvement: How much fixing the recommendation would improve the score\n\n"
        prompt += "Example response format:\n"
        prompt += "```json\n{"
        prompt += "\n  \"overallScore\": 75,"
        prompt += "\n  \"factorScores\": {\"accessibility\": 70, \"designConsistency\": 80, \"usability\": 75, \"visualHierarchy\": 70, \"responsiveness\": 85},"
        prompt += "\n  \"issues\": [{\"title\": \"Issue Title\", \"severity\": \"Medium\", \"description\": \"Detailed description\", \"location\": \"Top navigation bar\", \"impact\": 6}],"
        prompt += "\n  \"recommendations\": [{\"title\": \"Recommendation Title\", \"priority\": \"High\", \"description\": \"Detailed recommendation\", \"expectedImprovement\": 8}],"
        prompt += "\n  \"summary\": \"Overall assessment summary\""
        prompt += "\n}"
        prompt += "\n```"
        
        logger.info(f"Screen analysis prompt: {prompt}")
        
        try:
            # Use Google Gemini API for image analysis (already configured in the app)
            logger.info("Using Google Gemini API for screenshot analysis")
            
            # Check if Gemini API key is set
            if not os.getenv('GOOGLE_API_KEY'):
                logger.error("GOOGLE_API_KEY environment variable is not set")
                raise ValueError("GOOGLE_API_KEY environment variable is not set")
                
            logger.info(f"Using Gemini model: {model_name}")
            
            # Load the image for Gemini with proper file handling
            with open(temp_path, "rb") as img_file:
                image_data = img_file.read()
            
            image_parts = [
                {"mime_type": "image/png", "data": image_data}
            ]
            
            # Create Gemini model
            generation_config = {
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": 2048,
            }
            
            # Initialize the Gemini model
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config
            )
            
            # Send request to Gemini
            logger.info("Sending image to Gemini API for analysis")
            response = model.generate_content(
                [
                    prompt,
                    image_parts[0]
                ]
            )
            
            # Extract the AI response
            ai_response = response.text
            logger.info(f"Received response from Gemini (length: {len(ai_response)})")
            
            # Log a sample of the response for debugging
            sample_length = min(500, len(ai_response))
            logger.info(f"Sample of Gemini response: {ai_response[:sample_length]}...")
            
            # Process Figma comparison if requested
            figma_comparison_results = None
            if figma_compare and figma_design:
                try:
                    logger.info("Processing Figma comparison")
                    # Process Figma design data
                    figma_type = figma_design.get('type')
                    figma_data = figma_design.get('data')
                    
                    # Create a prompt for Figma comparison
                    comparison_prompt = f"""
                    Compare this UI screenshot with the provided Figma design specification and identify meaningful mismatches.
                    Focus on issues that affect design fidelity or user experience, not minor pixel-level differences.
                    
                    Comparison areas to focus on:
                    {"Missing or extra UI elements" if comparison_focus.get('elements', True) else ""}
                    {"Text value differences" if comparison_focus.get('textValues', True) else ""}
                    {"Layout and alignment issues" if comparison_focus.get('layout', True) else ""}
                    {"Font property differences" if comparison_focus.get('fonts', True) else ""}
                    {"Color and styling differences" if comparison_focus.get('colors', True) else ""}
                    
                    For each issue found, provide:
                    1. A brief summary of the issue
                    2. Severity level (Critical, Major, or Minor)
                    3. Element details (what component has the issue)
                    4. Expected design (from Figma)
                    5. Actual implementation (from screenshot)
                    6. Brief rationale for why this matters to users or design fidelity
                    
                    For alignment issues, provide specific measurements or coordinates when possible.
                    
                    Calculate comprehensive design fidelity scores and provide actionable insights.
                    
                    Format your response as a JSON object with this structure:
                    {{"summary": "Overall comparison summary",
                     "overallScore": 85,
                     "comparisonMetrics": {{"designFidelity": 85, "elementAccuracy": 90, "textAccuracy": 85, "layoutAccuracy": 80, "styleAccuracy": 85, "interactionFidelity": 88}},
                     "issues": [
                        {{"title": "Issue title",
                         "severity": "Critical|Major|Minor",
                         "element": "Element description",
                         "expected": "Expected design from Figma",
                         "actual": "Actual implementation in screenshot",
                         "impact": 8,
                         "description": "Why this matters for user experience"}},
                        ...
                     ],
                     "recommendations": [
                        {{"title": "Recommendation title",
                         "priority": "High|Medium|Low",
                         "description": "Specific improvement suggestion",
                         "expectedImprovement": 7,
                         "effort": "Low|Medium|High"}},
                        ...
                     ]}}
                    
                    SCORING GUIDELINES:
                    - Overall Score: Average of all comparison metrics (0-100)
                    - Design Fidelity: How closely the implementation matches the design intent
                    - Element Accuracy: Presence and positioning of UI elements
                    - Text Accuracy: Correctness of text content, fonts, and typography
                    - Layout Accuracy: Spacing, alignment, and structural fidelity
                    - Style Accuracy: Colors, borders, shadows, and visual styling
                    - Interaction Fidelity: Button states, hover effects, and interactive elements
                    - Impact: How much each issue affects the design-implementation gap (1-10)
                    - Expected Improvement: How much fixing the recommendation would improve the overall score (1-10)
                    """
                    
                    logger.info("Figma comparison prompt created")
                    
                    # Add Figma design as second image if it's an image
                    if figma_type == 'image':
                        logger.info("Processing Figma image data")
                        # Extract base64 data if needed
                        if ',' in figma_data:
                            figma_data = figma_data.split(',')[1]
                        
                        # Decode the image
                        figma_image_data = base64.b64decode(figma_data)
                        
                        # Create a temporary file for the Figma image with proper handle management
                        figma_temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                        figma_temp_path = figma_temp_file.name
                        figma_temp_file.write(figma_image_data)
                        figma_temp_file.close()  # Close handle immediately
                        
                        # Add to image parts with proper file handling
                        with open(temp_path, "rb") as main_img_file:
                            main_img_data = main_img_file.read()
                        
                        with open(figma_temp_path, "rb") as figma_img_file:
                            figma_img_data = figma_img_file.read()
                        
                        figma_image_parts = [
                            {"mime_type": "image/png", "data": main_img_data},
                            {"mime_type": "image/png", "data": figma_img_data}
                        ]
                        
                        # Generate comparison content
                        logger.info("Sending Figma comparison request to Gemini")
                        comparison_response = model.generate_content(
                            [
                                comparison_prompt,
                                *figma_image_parts
                            ]
                        )
                        comparison_text = comparison_response.text
                        
                        # Clean up temporary file
                        os.unlink(figma_temp_path)
                        
                    elif figma_type == 'json':
                        logger.info("Processing Figma JSON data")
                        # For JSON data, extract design specs and include in prompt
                        figma_specs = json.dumps(figma_data, indent=2)
                        figma_prompt = f"{comparison_prompt}\n\nFigma Design Specifications:\n{figma_specs}"
                        
                        # Generate comparison content
                        comparison_response = model.generate_content(
                            [
                                figma_prompt,
                                image_parts[0]
                            ]
                        )
                        comparison_text = comparison_response.text
                    else:
                        logger.info("Processing Figma text data")
                        # Text data, use as is
                        figma_prompt = f"{comparison_prompt}\n\nFigma Design Specifications:\n{figma_data}"
                        
                        # Generate comparison content
                        comparison_response = model.generate_content(
                            [
                                figma_prompt,
                                image_parts[0]
                            ]
                        )
                        comparison_text = comparison_response.text
                    
                    logger.info(f"Received Figma comparison response (length: {len(comparison_text)})")
                    sample_length = min(500, len(comparison_text))
                    logger.info(f"Sample of Figma comparison response: {comparison_text[:sample_length]}...")
                    
                    # Try to parse JSON from the comparison response
                    try:
                        # Extract JSON from markdown code blocks if present
                        json_match = re.search(r'```(?:json)?\s*({[\s\S]*?})\s*```', comparison_text)
                        if json_match:
                            json_str = json_match.group(1)
                            figma_comparison_results = json.loads(json_str)
                            logger.info("Successfully parsed Figma comparison JSON from code block")
                        else:
                            # Try to find any JSON-like structure
                            json_pattern = r'{[\s\S]*?"issues"[\s\S]*?}'
                            json_match = re.search(json_pattern, comparison_text)
                            if json_match:
                                json_str = json_match.group(0)
                                figma_comparison_results = json.loads(json_str)
                                logger.info("Successfully parsed Figma comparison JSON from text")
                            else:
                                # Create a basic structure if no JSON found
                                logger.warning("Could not find JSON in Figma comparison response")
                                figma_comparison_results = {
                                    'summary': 'Comparison completed but structured results could not be extracted.',
                                    'issues': [{
                                        'summary': 'Unstructured comparison results',
                                        'severity': 'Minor',
                                        'description': comparison_text,
                                        'element': 'N/A',
                                        'expected': 'See description',
                                        'actual': 'See description'
                                    }]
                                }
                    except json.JSONDecodeError as e:
                        # Create a basic structure if JSON parsing fails
                        logger.error(f"JSON decode error in Figma comparison: {str(e)}")
                        figma_comparison_results = {
                            'summary': 'Comparison completed but results could not be parsed as JSON.',
                            'issues': [{
                                'summary': 'JSON parsing error',
                                'severity': 'Minor',
                                'description': 'The comparison results could not be parsed as JSON. Please try again.',
                                'element': 'N/A',
                                'expected': 'Valid JSON response',
                                'actual': 'Invalid JSON format'
                            }]
                        }
                except Exception as e:
                    logger.error(f"Error in Figma comparison: {str(e)}")
                    figma_comparison_results = {
                        'summary': f"Error during Figma comparison: {str(e)}",
                        'issues': [{
                            'summary': 'Comparison error',
                            'severity': 'Major',
                            'description': f"An error occurred during the comparison: {str(e)}",
                            'element': 'N/A',
                            'expected': 'Successful comparison',
                            'actual': 'Error during processing'
                        }]
                    }
            
            logger.info("Used Google Gemini API for screen analysis")
            # Log the AI response for debugging
            logger.info(f"AI response (truncated): {ai_response[:500]}...")
        
        except Exception as e:
            logger.error(f"Error in AI analysis: {str(e)}")
            # Create a default response with the error
            ai_response = json.dumps({
                "issues": [{
                    "title": "AI Analysis Error",
                    "severity": "High",
                    "description": f"Error during analysis: {str(e)}"
                }],
                "recommendations": ["Please try again with a different image or check system logs."]
            })
        
        # Define helper function for finding potential misspellings
        def find_potential_misspellings(text):
            common_words = set(['the', 'to', 'and', 'a', 'in', 'is', 'it', 'you', 'that', 'was', 'for', 'on', 'are', 'with', 'as', 'I', 'his', 'they', 'be', 'at', 'one', 'have', 'this', 'from', 'by', 'hot', 'word', 'but', 'what', 'some', 'we', 'can', 'out', 'other', 'were', 'all', 'there', 'when', 'up', 'use', 'your', 'how', 'said', 'an', 'each', 'she', 'which', 'do', 'their', 'time', 'if', 'will', 'way', 'about', 'many', 'then', 'them', 'write', 'would', 'like', 'so', 'these', 'her', 'long', 'make', 'thing', 'see', 'him', 'two', 'has', 'look', 'more', 'day', 'could', 'go', 'come', 'did', 'number', 'sound', 'no', 'most', 'people', 'my', 'over', 'know', 'water', 'than', 'call', 'first', 'who', 'may', 'down', 'side', 'been', 'now', 'find', 'any', 'new', 'work', 'part', 'take', 'get', 'place', 'made', 'live', 'where', 'after', 'back', 'little', 'only', 'round', 'man', 'year', 'came', 'show', 'every', 'good', 'me', 'give', 'our', 'under', 'name', 'very', 'through', 'just', 'form', 'sentence', 'great', 'think', 'say', 'help', 'low', 'line', 'differ', 'turn', 'cause', 'much', 'mean', 'before', 'move', 'right', 'boy', 'old', 'too', 'same', 'tell', 'does', 'set', 'three', 'want', 'air', 'well', 'also', 'play', 'small', 'end', 'put', 'home', 'read', 'hand', 'port', 'large', 'spell', 'add', 'even', 'land', 'here', 'must', 'big', 'high', 'such', 'follow', 'act', 'why', 'ask', 'men', 'change', 'went', 'light', 'kind', 'off', 'need', 'house', 'picture', 'try', 'us', 'again', 'animal', 'point', 'mother', 'world', 'near', 'build', 'self', 'earth', 'father'])
            words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
            unusual_words = [word for word in words if word not in common_words and len(word) > 3]
            
            # Look for potential typos (repeated characters, unusual character combinations)
            typos = []
            for word in unusual_words:
                if len(word) > 7 and word not in ['information', 'available', 'different', 'important', 'something', 'everything', 'development', 'management', 'experience', 'technology']:
                    typos.append(word)
                elif re.search(r'(.)\1{2,}', word):  # Repeated characters more than twice
                    typos.append(word)
                    
            return typos[:5]  # Return up to 5 potential issues
            
        # Define helper function for manual extraction
        def extract_issues_manually(text):
            logger.info("Extracting issues manually from text")
            result = {
                'issues': [],
                'recommendations': [],
                'overallScore': 70,  # Default moderate score for manual extraction
                'factorScores': {
                    'accessibility': 70,
                    'designConsistency': 70,
                    'usability': 70,
                    'visualHierarchy': 70,
                    'responsiveness': 70
                },
                'summary': 'UI analysis completed using manual text extraction due to parsing issues.'
            }
            
            # Extract issues using various patterns
            issue_patterns = [
                r'(?:issue|problem)\s*(?:\d+)?\s*:?\s*([^\n.]+)',  # Issue: Description
                r'(?:\d+\.\s*|-)\s*([^\n.]+)(?=\s*(?:issue|problem))',  # 1. Description (issue)
                r'"title"\s*:\s*"([^"]+)"',  # "title": "Description"
                r'<issue>\s*([^<]+)\s*</issue>'  # <issue>Description</issue>
            ]
            
            for pattern in issue_patterns:
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                if matches:
                    logger.info(f"Found {len(matches)} issues using pattern: {pattern}")
                    for i, match in enumerate(matches):
                        result['issues'].append({
                            'title': f"UI Issue {i+1}",
                            'severity': 'Medium',
                            'description': match.group(1).strip(),
                            'location': 'Unknown'
                        })
                    break  # Stop after finding issues with one pattern
            
            # Extract recommendations
            rec_patterns = [
                r'(?:recommendation|suggestion)\s*(?:\d+)?\s*:?\s*([^\n.]+)',  # Recommendation: Text
                r'(?:\d+\.\s*|-)\s*([^\n.]+)(?=\s*(?:recommend|suggest))',  # 1. Text (recommendation)
                r'"recommendation"\s*:\s*"([^"]+)"'  # "recommendation": "Text"
            ]
            
            for pattern in rec_patterns:
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                if matches:
                    logger.info(f"Found {len(matches)} recommendations using pattern: {pattern}")
                    for match in matches:
                        result['recommendations'].append(match.group(1).strip())
                    break  # Stop after finding recommendations with one pattern
            
            return result
            
        # Try to parse JSON from AI response
        try:
            logger.info(f"Full AI response: {ai_response}")
            
            # Step 1: First try to parse the entire response as JSON directly (most likely with response_format=json_object)
            try:
                logger.info("Attempting to parse entire response as JSON")
                ai_results = json.loads(ai_response)
                logger.info("Successfully parsed entire response as JSON")
            except json.JSONDecodeError:
                logger.info("Direct JSON parsing failed, trying alternative methods")
                
                # Step 2: Look for JSON in code blocks (common in LLM responses)
                json_match = re.search(r'```(?:json)?\s*\n(.+?)\n```', ai_response, re.DOTALL)
                if json_match:
                    logger.info("Found JSON in code block")
                    json_content = json_match.group(1).strip()
                    logger.info(f"Extracted JSON from code block: {json_content[:200]}...")
                    try:
                        ai_results = json.loads(json_content)
                        logger.info("Successfully parsed JSON from code block")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Error parsing JSON from code block: {str(e)}")
                        # Try to clean up common JSON formatting issues
                        cleaned_json = re.sub(r'(?<!\\)\\n', '\n', json_content)  # Fix escaped newlines
                        cleaned_json = re.sub(r',\s*}', '}', cleaned_json)  # Fix trailing commas
                        cleaned_json = re.sub(r',\s*]', ']', cleaned_json)  # Fix trailing commas in arrays
                        
                        try:
                            ai_results = json.loads(cleaned_json)
                            logger.info("Successfully parsed cleaned JSON from code block")
                        except json.JSONDecodeError:
                            logger.warning("Could not parse cleaned JSON from code block, trying pattern extraction")
                            raise  # Continue to the next method
                else:
                    # Step 3: Try to extract JSON-like content with a robust pattern
                    logger.info("No code block found, trying to extract JSON pattern")
                    # Look for a complete JSON object from the start of a line
                    json_pattern = re.search(r'(?m)^\s*(\{[\s\S]*?\})\s*$', ai_response)
                    if not json_pattern:
                        # Try to find any JSON-like structure with both issues and recommendations
                        json_pattern = re.search(r'\{[\s\S]*?"issues"[\s\S]*?"recommendations"[\s\S]*?\}', ai_response)
                    
                    if json_pattern:
                        logger.info("Found JSON-like pattern")
                        json_content = json_pattern.group(0)
                        logger.info(f"Extracted JSON-like content: {json_content[:200]}...")
                        
                        # Try to clean up and parse
                        try:
                            ai_results = json.loads(json_content)
                            logger.info("Successfully parsed extracted JSON pattern")
                        except json.JSONDecodeError:
                            logger.warning("Could not parse JSON pattern, using manual extraction")
                            # Step 4: Manual extraction as last resort
                            ai_results = extract_issues_manually(ai_response)
                    else:
                        logger.warning("No JSON pattern found, using manual extraction")
                        # Step 4: Manual extraction as last resort
                        ai_results = extract_issues_manually(ai_response)
            
            # Validate the structure of the parsed results
            if not isinstance(ai_results, dict):
                logger.warning(f"Parsed result is not a dictionary: {type(ai_results)}")
                ai_results = {'issues': [], 'recommendations': []}
            
            # Ensure required fields exist
            if 'issues' not in ai_results:
                logger.warning("No 'issues' field in parsed results, adding empty array")
                ai_results['issues'] = []
                
            if 'recommendations' not in ai_results:
                logger.warning("No 'recommendations' field in parsed results, adding empty array")
                ai_results['recommendations'] = []
                
            # Validate each issue has required fields
            for i, issue in enumerate(ai_results['issues']):
                if not isinstance(issue, dict):
                    logger.warning(f"Issue {i} is not a dictionary: {issue}")
                    ai_results['issues'][i] = {
                        'title': 'Invalid Issue Format',
                        'severity': 'Medium',
                        'description': str(issue)
                    }
                    continue
                    
                # Ensure required fields
                if 'title' not in issue or not issue['title']:
                    issue['title'] = f"UI Issue {i+1}"
                    
                if 'severity' not in issue or not issue['severity'] or issue['severity'] not in ['High', 'Medium', 'Low']:
                    issue['severity'] = 'Medium'
                    
                if 'description' not in issue or not issue['description']:
                    issue['description'] = "No description provided"
                    
                if 'location' not in issue or not issue['location']:
                    issue['location'] = "Unknown location"
            
            logger.info(f"Validated AI results structure with {len(ai_results['issues'])} issues and {len(ai_results['recommendations'])} recommendations")
            
        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}")
            # Create a default response with the error including scoring fields
            ai_results = {
                'issues': [{
                    'title': 'Response Parsing Error',
                    'severity': 'Medium',
                    'description': f"Could not parse the AI analysis response: {str(e)}",
                    'location': 'Unknown'
                }],
                'recommendations': ['Try again with a clearer screenshot or check system logs for details.'],
                'overallScore': 70,  # Default moderate score
                'factorScores': {
                    'accessibility': 70,
                    'designConsistency': 70,
                    'usability': 70,
                    'visualHierarchy': 70,
                    'responsiveness': 70
                },
                'summary': 'Analysis completed but response could not be fully parsed.'
            }
        os.unlink(temp_path)
        
        logger.info(f"Parsed AI results: {ai_results}")
        
        # Force issues to be found - NEVER return "no issues found"
        # If no issues were detected or parsing failed, create default issues
        if 'issues' not in ai_results or not ai_results['issues']:
            logger.info("No issues found in AI response, creating default issues")
            
            # Always create at least one issue
            default_issues = [{
                'title': 'UI Enhancement Opportunity',
                'severity': 'Low',
                'description': 'While no critical issues were detected, consider reviewing the UI for potential improvements in alignment, spacing, and visual hierarchy.',
                'location': 'Overall UI'
            }]
            
            # If OCR text is available, try to find potential issues
            if ocr_text and len(ocr_text.strip()) > 0:
                logger.info(f"OCR text available, analyzing for issues: {ocr_text[:100]}...")
                # Look for potential issues in the OCR text
                potential_issues = []
                
                # Check for common typos or misspellings
                misspelled_words = find_potential_misspellings(ocr_text)
                if misspelled_words:
                    logger.info(f"Found potential misspellings: {misspelled_words}")
                    potential_issues.append({
                        'title': 'Potential Text Issues',
                        'severity': 'Medium',
                        'description': f"Possible misspelled or unusual words detected: {', '.join(misspelled_words)}",
                        'location': 'Text content'
                    })
                
                # Check for potential layout issues
                if '  ' in ocr_text or ocr_text.count('\n\n') > 2:
                    logger.info("Found potential layout issues based on text spacing")
                    potential_issues.append({
                        'title': 'Potential Layout Issues',
                        'severity': 'Low',
                        'description': 'Text spacing appears inconsistent, which may indicate layout problems.',
                        'location': 'Text layout'
                    })
                
                # Add any found issues
                if potential_issues:
                    ai_results['issues'] = potential_issues
                else:
                    ai_results['issues'] = default_issues
            else:
                logger.info("No OCR text available, using default issues")
                ai_results['issues'] = default_issues
        
        # Ensure we have recommendations
        if 'recommendations' not in ai_results or not ai_results['recommendations']:
            logger.info("No recommendations found, adding defaults")
            ai_results['recommendations'] = [
                'Review the UI with actual users to validate the design and identify any usability concerns.',
                'Consider A/B testing different UI variations to optimize user experience.',
                'Ensure the UI follows accessibility guidelines for all users.'
            ]
            
        # Ensure we have scoring fields
        if 'overallScore' not in ai_results:
            logger.info("No overall score found, adding default")
            ai_results['overallScore'] = 75  # Default moderate score
            
        if 'factorScores' not in ai_results:
            logger.info("No factor scores found, adding defaults")
            ai_results['factorScores'] = {
                'accessibility': 75,
                'designConsistency': 75,
                'usability': 75,
                'visualHierarchy': 75,
                'responsiveness': 75
            }
            
        if 'summary' not in ai_results:
            logger.info("No summary found, adding default")
            ai_results['summary'] = f"Analyzed UI screenshot and found {len(ai_results.get('issues', []))} issues with actionable recommendations."
            
        # Clean up temporary files before returning response
        # Force garbage collection and add delay on Windows to ensure file handles are released
        import gc
        import platform
        
        # Force garbage collection to release any remaining file references
        gc.collect()
        
        if platform.system() == 'Windows':
            import time
            # Longer delay on Windows to ensure all file handles are fully released
            time.sleep(0.5)
        
        # Clean up main screenshot temporary file with retry mechanism
        def safe_delete_file(file_path, max_attempts=3):
            for attempt in range(max_attempts):
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                        logger.info(f"Successfully cleaned up temp file: {file_path}")
                        return True
                except Exception as e:
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed to delete {file_path}: {e}. Retrying...")
                        time.sleep(0.2)  # Brief pause before retry
                    else:
                        logger.warning(f"Failed to delete {file_path} after {max_attempts} attempts: {e}")
                        return False
            return False
        
        safe_delete_file(temp_path)
        
        # Clean up any Figma temporary files
        if 'figma_temp_path' in locals():
            safe_delete_file(figma_temp_path)
            
        # Prepare response data with scoring information
        response_data = {
            'issues': ai_results.get('issues', []),
            'recommendations': ai_results.get('recommendations', []),
            'overallScore': ai_results.get('overallScore', 0),
            'factorScores': ai_results.get('factorScores', {}),
            'summary': ai_results.get('summary', '')
        }
        
        # Add OCR text if available
        if ocr_available and ocr_text and ocr_text.strip():
            response_data['ocr'] = ocr_text
            
        # Add Figma comparison results if available
        if figma_comparison_results:
            response_data['figmaComparison'] = figma_comparison_results
            # Include comparison metrics in main response for unified scoring display
            if 'comparisonMetrics' in figma_comparison_results:
                response_data['comparisonMetrics'] = figma_comparison_results['comparisonMetrics']
            if 'overallScore' in figma_comparison_results:
                response_data['overallScore'] = figma_comparison_results['overallScore']
            if 'summary' in figma_comparison_results:
                response_data['summary'] = figma_comparison_results['summary']
            
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in screen analysis: {str(e)}")
        
        # Clean up temporary files even on error
        import gc
        import platform
        
        # Force garbage collection to release any remaining file references
        gc.collect()
        
        if platform.system() == 'Windows':
            import time
            # Longer delay on Windows to ensure all file handles are fully released
            time.sleep(0.5)
        
        # Clean up temporary files using robust deletion
        def safe_delete_file_on_error(file_path, max_attempts=3):
            for attempt in range(max_attempts):
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                        logger.info(f"Cleaned up temp file on error: {file_path}")
                        return True
                except Exception as e:
                    if attempt < max_attempts - 1:
                        logger.warning(f"Cleanup attempt {attempt + 1} failed for {file_path}: {e}. Retrying...")
                        time.sleep(0.2)
                    else:
                        logger.warning(f"Failed to cleanup {file_path} after {max_attempts} attempts: {e}")
                        return False
            return False
        
        # Clean up main screenshot temporary file
        if 'temp_path' in locals():
            safe_delete_file_on_error(temp_path)
        
        # Clean up any Figma temporary files
        if 'figma_temp_path' in locals():
            safe_delete_file_on_error(figma_temp_path)
        
        return jsonify({'error': str(e)}), 500

@app.route('/parse_curl_to_json', methods=['POST'])
def parse_curl_to_json():
    data = request.get_json()
    curl = data.get('curl', '')
    if not curl:
        return jsonify({'error': 'No curl command provided'}), 400
    try:
        parsed = parse_curl_command(curl)
        return jsonify({'json': parsed})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Helper: Convert Jira ADF to HTML (basic, extend as needed) ---
def adf_to_html(adf):
    if not adf:
        return ''
    t = adf.get('type') if isinstance(adf, dict) else None
    if t == 'text':
        text = adf.get('text', '')
        marks = adf.get('marks', [])
        for mark in marks:
            if mark['type'] == 'strong':
                text = f'<strong>{text}</strong>'
            elif mark['type'] == 'em':
                text = f'<em>{text}</em>'
            elif mark['type'] == 'underline':
                text = f'<u>{text}</u>'
            elif mark['type'] == 'link':
                href = mark.get('attrs', {}).get('href', '#')
                text = f'<a href="{href}" target="_blank">{text}</a>'
        return text
    elif t == 'paragraph':
        return '<p>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</p>'
    elif t == 'heading':
        level = adf.get('attrs', {}).get('level', 1)
        return f'<h{level}>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + f'</h{level}>'
    elif t == 'bulletList':
        return '<ul>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</ul>'
    elif t == 'orderedList':
        return '<ol>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</ol>'
    elif t == 'listItem':
        return '<li>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</li>'
    elif t == 'media':
        attrs = adf.get('attrs', {})
        media_id = attrs.get('id')
        collection = attrs.get('collection') or 'jira-issue'
        if media_id:
            return f'<img src="/api/jira/attachment?id={media_id}&collection={collection}" alt="Jira Image" style="max-width:100%;">'
        url = attrs.get('url') or attrs.get('dataURI')
        if url:
            return f'<img src="{url}" alt="Jira Image" style="max-width:100%;">'
        return ''
    elif t == 'table':
        return '<table class="table table-bordered">' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</table>'
    elif t == 'tableRow':
        return '<tr>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</tr>'
    elif t == 'tableCell' or t == 'tableHeader':
        tag = 'th' if t == 'tableHeader' else 'td'
        return f'<{tag}>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + f'</{tag}>'
    elif t == 'blockquote':
        return '<blockquote>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</blockquote>'
    elif t == 'codeBlock':
        return '<pre><code>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</code></pre>'
    elif t == 'panel':
        return '<div class="panel" style="border:1px solid #eee;padding:0.5em;margin:0.5em 0;background:#f8f9fa;">' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</div>'
    elif t == 'rule':
        return '<hr>'
    elif t == 'hardBreak':
        return '<br>'
    elif t == 'emoji':
        return adf.get('attrs', {}).get('shortName', '')
    elif isinstance(adf, dict) and 'content' in adf:
        return ''.join(adf_to_html(child) for child in adf['content'])
    elif isinstance(adf, list):
        return ''.join(adf_to_html(child) for child in adf)
    return ''

@app.route('/api/jira/attachment')
def jira_attachment():
    attachment_id = request.args.get('id')
    collection = request.args.get('collection') or 'jira-issue'
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    if not (attachment_id and access_token and cloud_id):
        app.logger.error(f'Missing info: id={attachment_id}, token={bool(access_token)}, cloud_id={cloud_id}')
        return '', 404
    # Distinguish numeric (classic) vs UUID (media)
    if re.match(r'^\d+$', attachment_id):
        # Classic attachment
        url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/attachment/{attachment_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        resp = requests.get(url, headers=headers)
        app.logger.info(f'Jira attachment metadata GET {url} status={resp.status_code}')
        if resp.status_code != 200:
            app.logger.error(f'Attachment metadata fetch failed: {resp.text}')
            return '', 404
        data = resp.json()
        content_url = data.get('content')
        if not content_url:
            app.logger.error(f'No content URL in attachment metadata: {data}')
            return '', 404
        img_resp = requests.get(content_url, headers=headers, stream=True)
        app.logger.info(f'Jira attachment content GET {content_url} status={img_resp.status_code}')
        if img_resp.status_code != 200:
            app.logger.error(f'Attachment content fetch failed: {img_resp.text}')
            return '', 404
        return Response(img_resp.iter_content(chunk_size=4096), content_type=img_resp.headers.get('Content-Type', 'image/png'))
    else:
        # Media Service (UUID)
        media_url = f'https://api.media.atlassian.com/file/{attachment_id}/binary?collection={collection}'
        headers = {'Authorization': f'Bearer {access_token}'}
        img_resp = requests.get(media_url, headers=headers, stream=True)
        app.logger.info(f'Jira media service GET {media_url} status={img_resp.status_code}')
        if img_resp.status_code != 200:
            app.logger.error(f'Media service fetch failed: {img_resp.text}')
            return '', 404
        return Response(img_resp.iter_content(chunk_size=4096), content_type=img_resp.headers.get('Content-Type', 'image/png'))

@app.route('/api/jira/disconnect', methods=['POST'])
def disconnect_jira():
    for k in ['jira_access_token', 'jira_refresh_token', 'jira_token_expires', 'jira_cloud_id', 'jira_domain']:
        session.pop(k, None)
    return jsonify({'success': True})

@app.route('/api/jira/create-subtasks', methods=['POST'])
def create_jira_subtasks():
    """Create subtasks in Jira for each test case"""
    # Check if feature is enabled (development mode only)
    if FLASK_ENV != 'development':
        return jsonify({'error': 'Create subtasks feature is only available in development mode.'}), 403
    
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira. Please connect first.'}), 401
    if not cloud_id:
        return jsonify({'error': 'No Jira cloud ID found. Please reconnect to Jira.'}), 401

    # Check if token needs refresh
    token_expires = session.get('jira_token_expires', 0)
    if time.time() >= token_expires:
        if not refresh_jira_token():
            return jsonify({'error': 'Token expired. Please reconnect to Jira.'}), 401
        access_token = session['jira_access_token']
    
    # Get data from request
    try:
        data = request.json
        parent_issue_key = data.get('parentIssueKey')
        test_cases = data.get('testCases', [])
        
        if not parent_issue_key:
            return jsonify({'error': 'Parent issue key is required'}), 400
        if not test_cases:
            return jsonify({'error': 'No test cases provided'}), 400
        
        # Create subtasks
        created_count = 0
        failed_count = 0
        created_keys = []
        
        # Make request to Jira API
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # Get the parent issue to get the project key
        issue_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{parent_issue_key}'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        response = requests.get(issue_url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Error fetching parent issue: {response.text}")
            return jsonify({'error': f'Error fetching parent issue: {response.status_code}'}), response.status_code
        
        issue_data = response.json()
        project_key = issue_data.get('fields', {}).get('project', {}).get('key')
        
        if not project_key:
            return jsonify({'error': 'Could not determine project key from parent issue'}), 400
        
        # Get the subtask issue type ID and available fields
        meta_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/createmeta?projectKeys={project_key}&issuetypeNames=Sub-task&expand=projects.issuetypes.fields'
        response = requests.get(meta_url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Error fetching issue metadata: {response.text}")
            return jsonify({'error': f'Error fetching issue metadata: {response.status_code}'}), response.status_code
        
        meta_data = response.json()
        subtask_type_id = None
        available_fields = {}
        
        # Extract available fields for subtasks
        for project in meta_data.get('projects', []):
            if project.get('key') == project_key:
                for issue_type in project.get('issuetypes', []):
                    if issue_type.get('subtask', False) or issue_type.get('name') == 'Sub-task':
                        subtask_type_id = issue_type.get('id')
                        available_fields = issue_type.get('fields', {})
                        break
        
        if not subtask_type_id:
            return jsonify({'error': 'Could not find subtask issue type'}), 400
        
        logger.info(f"Available fields for subtasks: {list(available_fields.keys())}")
        
        # Initialize counters
        created_count = 0
        failed_count = 0
        created_keys = []
        
        # Create each subtask
        create_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue'
        
        # Log detailed information for debugging
        logger.info(f"Creating subtasks for parent issue: {parent_issue_key}")
        logger.info(f"Project key: {project_key}")
        logger.info(f"Subtask type ID: {subtask_type_id}")
        logger.info(f"Number of test cases to create: {len(test_cases)}")
        
        error_details = []
        
        for idx, test_case in enumerate(test_cases):
            step = test_case.get('step', '')
            expected = test_case.get('expected', '')
            estimate_minutes = test_case.get('estimate_minutes', 10)
            
            # Log the test case we're creating
            logger.info(f"Creating subtask {idx+1}/{len(test_cases)}: '{step[:50]}...'")
            
            # Create a subtask for this test case with only the fields that are available
            fields = {
                'project': {
                    'key': project_key
                },
                'parent': {
                    'key': parent_issue_key
                },
                'issuetype': {
                    'id': subtask_type_id
                },
                'summary': f'Test: {step[:80]}' + ('...' if len(step) > 80 else ''),
                'description': {
                    'type': 'doc',
                    'version': 1,
                    'content': [
                        {
                            'type': 'heading',
                            'attrs': {'level': 3},
                            'content': [{'type': 'text', 'text': 'Test Step'}]
                        },
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': step}]
                        },
                        {
                            'type': 'heading',
                            'attrs': {'level': 3},
                            'content': [{'type': 'text', 'text': 'Expected Result'}]
                        },
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': expected}]
                        },
                        {
                            'type': 'heading',
                            'attrs': {'level': 3},
                            'content': [{'type': 'text', 'text': 'Estimated Time'}]
                        },
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': f'{estimate_minutes} minutes'}]
                        }
                    ]
                }
            }
            
            # Try to set the original estimate if the timetracking field exists in available fields
            if 'timetracking' in available_fields:
                fields['timetracking'] = {
                    'originalEstimate': f'{estimate_minutes}m'
                }
                logger.info("Added timetracking field to subtask")
            
            # Look for any field that might be related to task type in the available fields
            logger.info("Examining available fields for task type fields")
            
            # Check if customfield_10010 is in available fields - this is often used for task type
            if 'customfield_10010' in available_fields:
                logger.info("Found customfield_10010 in available fields")
                field_info = available_fields['customfield_10010']
                
                # Check if this field has allowed values
                if 'allowedValues' in field_info:
                    logger.info(f"customfield_10010 has {len(field_info['allowedValues'])} allowed values")
                    
                    # Try to find a value that matches QA Testing or Test Execution
                    for value in field_info['allowedValues']:
                        value_name = value.get('value', '')
                        logger.info(f"Available value: {value_name}")
                        
                        if 'qa testing' in value_name.lower() or 'test execution' in value_name.lower():
                            if 'id' in value:
                                fields['customfield_10010'] = {'id': value['id']}
                                logger.info(f"Setting customfield_10010 to id: {value['id']} (value: {value_name})")
                            else:
                                fields['customfield_10010'] = {'value': value_name}
                                logger.info(f"Setting customfield_10010 to value: {value_name}")
                            break
                    else:
                        # If no matching value found, use the first one
                        if field_info['allowedValues']:
                            first_value = field_info['allowedValues'][0]
                            if 'id' in first_value:
                                fields['customfield_10010'] = {'id': first_value['id']}
                                logger.info(f"Setting customfield_10010 to first available id: {first_value['id']}")
                            else:
                                fields['customfield_10010'] = {'value': first_value['value']}
                                logger.info(f"Setting customfield_10010 to first available value: {first_value['value']}")
            
            # Look for any other fields that might be task type related
            for field_id, field_info in available_fields.items():
                field_name = field_info.get('name', '').lower()
                
                # Skip customfield_10010 as we already handled it
                if field_id == 'customfield_10010':
                    continue
                    
                # If this looks like a task type field and has allowed values
                if ('task' in field_name or 'type' in field_name) and 'allowedValues' in field_info:
                    logger.info(f"Found potential task type field: {field_id} ({field_name})")
                    
                    # Try to find a value that matches QA Testing or Test Execution
                    for value in field_info['allowedValues']:
                        value_name = value.get('value', '')
                        if 'qa testing' in value_name.lower() or 'test execution' in value_name.lower():
                            if 'id' in value:
                                fields[field_id] = {'id': value['id']}
                                logger.info(f"Setting {field_id} to id: {value['id']} (value: {value_name})")
                            else:
                                fields[field_id] = {'value': value_name}
                                logger.info(f"Setting {field_id} to value: {value_name}")
                            break
                    else:
                        # If no matching value found, use the first one
                        if field_info['allowedValues']:
                            first_value = field_info['allowedValues'][0]
                            if 'id' in first_value:
                                fields[field_id] = {'id': first_value['id']}
                                logger.info(f"Setting {field_id} to first available id: {first_value['id']}")
                            else:
                                fields[field_id] = {'value': first_value['value']}
                                logger.info(f"Setting {field_id} to first available value: {first_value['value']}")
            
            # Only use fields that are available in the metadata
            # Do not try to set fields that aren't available
            
            # DO NOT set any fields that aren't in the metadata
            # This was causing the errors we saw
            
            # Create the final payload with the fields
            payload = {'fields': fields}
            
            try:
                logger.info(f"Sending payload for subtask creation: {payload}")
                response = requests.post(create_url, headers=headers, json=payload, timeout=30)
                
                if response.status_code in (200, 201):
                    created_count += 1
                    created_keys.append(response.json().get('key'))
                    logger.info(f"Successfully created subtask {response.json().get('key')}")
                else:
                    failed_count += 1
                    error_message = f"Failed to create subtask: HTTP {response.status_code}: {response.text}"
                    logger.error(error_message)
                    error_details.append({
                        'step': step[:50] + '...',
                        'status_code': response.status_code,
                        'response': response.text[:200] + ('...' if len(response.text) > 200 else '')
                    })
            except Exception as e:
                failed_count += 1
                error_message = f"Exception creating subtask: {str(e)}"
                logger.error(error_message)
                error_details.append({
                    'step': step[:50] + '...',
                    'exception': str(e)
                })
        
        return jsonify({
            'status': 'success',
            'createdCount': created_count,
            'failedCount': failed_count,
            'createdKeys': created_keys,
            'errorDetails': error_details if failed_count > 0 else []
        })
        
    except Exception as e:
        logger.error(f"Error creating Jira subtasks: {str(e)}")
        return jsonify({'error': f'Error creating subtasks: {str(e)}'}), 500

# --- OCR and Vision API Hybrid Endpoint ---
import pytesseract
from PIL import Image
import requests
from flask import request, jsonify
# Configure Tesseract path - try to find it in common locations
import platform
import os
import subprocess
import tempfile
import base64
import io

# Check if Tesseract is installed and available
def check_tesseract_availability():
    try:
        # Try to execute tesseract command
        subprocess.run(['tesseract', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        return True
    except FileNotFoundError:
        logger.warning("Tesseract not found in PATH")
        return False

# Auto-detect Tesseract path based on platform
tesseract_available = False
if platform.system() == 'Windows':
    tesseract_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'
    ]
    for path in tesseract_paths:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            logger.info(f"Found Tesseract at: {path}")
            tesseract_available = True
            break
elif platform.system() == 'Linux':
    # On Linux, check if it's in PATH first
    if check_tesseract_availability():
        tesseract_available = True
        logger.info("Tesseract found in PATH")
    else:
        # Check common locations
        tesseract_paths = [
            '/usr/bin/tesseract',
            '/usr/local/bin/tesseract'
        ]
        for path in tesseract_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                logger.info(f"Found Tesseract at: {path}")
                tesseract_available = True
                break

if not tesseract_available:
    logger.warning("Tesseract OCR not found on system. Image-to-text will use fallback methods only.")

@app.route('/api/image-to-text', methods=['POST'])
@jira_auth_required
def image_to_text():
    try:
        data = request.json
        if not data:
            logger.error("No JSON data received in image-to-text request")
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Handle both URL and base64 encoded images
        image_url = data.get('image_url')
        image_base64 = data.get('image_base64')
        
        if not image_url and not image_base64:
            logger.error("Neither image_url nor image_base64 provided in request")
            return jsonify({'error': 'No image source provided. Please provide either image_url or image_base64'}), 400
        
        img = None
        source_type = "url" if image_url else "base64"
        
        # Process based on source type
        try:
            if source_type == "url":
                logger.info(f"Processing image from URL: {image_url}")
                
                # Handle both direct URLs and Jira attachment URLs
                if 'jira' in image_url.lower() and 'attachment' in image_url.lower():
                    logger.info("Detected Jira attachment URL, using authenticated session")
                    # Get Jira access token from session
                    access_token = session.get('jira_access_token')
                    if not access_token:
                        logger.error("No Jira access token found in session")
                        return jsonify({'error': 'Jira authentication required'}), 401
                    
                    # Make request with authorization header
                    headers = {'Authorization': f'Bearer {access_token}'}
                    response = requests.get(image_url, headers=headers, stream=True, timeout=10)
                else:
                    # Regular URL
                    response = requests.get(image_url, stream=True, timeout=10)
                
                response.raise_for_status()  # Raise exception for 4XX/5XX responses
                img = Image.open(response.raw)
            else:  # base64
                logger.info("Processing base64 encoded image")
                # Remove data URL prefix if present
                if image_base64.startswith('data:image'):
                    image_base64 = image_base64.split(',', 1)[1]
                
                # Decode base64 string to image
                image_data = base64.b64decode(image_base64)
                img = Image.open(io.BytesIO(image_data))
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching image: {str(e)}")
            return jsonify({'error': f'Error fetching image: {str(e)}'}), 500
        except Exception as e:
            logger.error(f"Error processing image data: {str(e)}")
            return jsonify({'error': f'Error processing image data: {str(e)}'}), 500
        
        # Try OCR if available
        text = None
        source = None
        
        # Try Tesseract OCR first if available
        if tesseract_available:
            try:
                logger.info("Attempting OCR with Tesseract")
                text = pytesseract.image_to_string(img)
                if text and text.strip():
                    logger.info(f"OCR successful, extracted {len(text.strip())} characters")
                    source = "ocr"
            except Exception as e:
                logger.error(f"Tesseract OCR error: {str(e)}")
                # Continue to fallback methods
        
        # If OCR failed or not available, try Google Vision API
        if not text or not text.strip():
            try:
                if genai and os.getenv('GOOGLE_API_KEY'):
                    logger.info("Attempting to use Google Generative AI for image description")
                    # Save image to temporary file
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                        img.save(temp_file, format='PNG')
                        temp_file_path = temp_file.name
                    
                    # Load image for Gemini
                    try:
                        import google.generativeai as genai
                        from google.generativeai.types import HarmCategory, HarmBlockThreshold
                        
                        # Configure safety settings
                        safety_settings = {
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                        }
                        
                        # Load image
                        with open(temp_file_path, 'rb') as f:
                            image_data = f.read()
                        
                        # Use Gemini model for vision tasks
                        model = genai.GenerativeModel(os.environ.get('GOOGLE_API_MODEL'), safety_settings=safety_settings)
                        response = model.generate_content(["Extract and return all text visible in this image. Return only the text content, no descriptions or explanations.", image_data])
                        
                        if response and hasattr(response, 'text'):
                            text = response.text
                            source = "vision"
                            logger.info(f"Google Vision API extracted {len(text)} characters")
                    except ImportError as e:
                        logger.error(f"Google Generative AI import error: {str(e)}")
                    except Exception as e:
                        logger.error(f"Google Vision API error: {str(e)}")
                    finally:
                        # Clean up temp file
                        try:
                            os.unlink(temp_file_path)
                        except:
                            pass
            except Exception as e:
                logger.error(f"Vision API fallback error: {str(e)}")
        
        # If all methods failed, return a helpful error
        if not text or not text.strip():
            logger.warning("All text extraction methods failed")
            return jsonify({
                'text': "No text could be extracted from this image.",
                'source': "none",
                'warning': "Text extraction failed with all available methods."
            })
        
        # Return the extracted text
        return jsonify({
            'text': text.strip(),
            'source': source
        })
        
    except Exception as e:
        logger.error(f"Unexpected error in image-to-text: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error processing image', 'details': str(e)}), 500

def call_vision_api(image_url):
    """Legacy function for backward compatibility"""
    try:
        if genai and os.getenv('GOOGLE_API_KEY'):
            # Download image
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            image_data = response.content
            
            # Use Gemini model
            model = genai.GenerativeModel(os.environ.get('GOOGLE_API_MODEL'))
            response = model.generate_content(["Extract all text visible in this image", image_data])
            if response and hasattr(response, 'text'):
                return response.text
    except Exception as e:
        logger.error(f"Error calling Vision API: {str(e)}")
    
    return "No text found in image. Vision API fallback not available or failed."
# --- End OCR and Vision API Hybrid Endpoint ---

def step_to_description(step):
    action = step.get('action', '')
    if action == 'navigate':
        return f"Navigate to URL: {step.get('url', '')}"
    elif action == 'click':
        return f"Click element: {step.get('selector', '')}"
    elif action == 'fill':
        return f"Fill form field: {step.get('selector', '')} with {step.get('value', '')}"
    elif action == 'extract_text':
        return f"Extract text from element: {step.get('selector', '')}"
    elif action == 'assert_visible':
        return f"Assert element is visible: {step.get('selector', '')}"
    elif action == 'assert_text':
        return f"Assert element contains text: {step.get('selector', '')} '{step.get('text', '')}'"
    elif action == 'wait_for_element':
        return f"Wait for element: {step.get('selector', '')}"
    elif action == 'custom':
        return step.get('instruction', '[custom instruction]')
    elif action == 'page_html':
        return "Extract page HTML"
    elif action == 'select':
        return f"Select from dropdown: {step.get('selector', '')} value {step.get('value', '')}"
    elif action == 'type':
        return f"Type text: {step.get('selector', '')} '{step.get('text', '')}'"
    elif action == 'press_key':
        return f"Press key: {step.get('key', '')}"
    elif action == 'assert_url':
        return f"Assert URL: {step.get('url', '')}"
    elif action == 'assert_title':
        return f"Assert page title: {step.get('title', '')}"
    # Add more actions as needed, matching UI labels
    else:
        return f"{action}: {step}" if action else str(step)

# Create a wrapper class to add compatibility attributes for browser_use
# This needs to be at module level so both BrowserUse endpoints can use it
class BrowserUseCompatibleLLM:
    def __init__(self, llm):
        self._llm = llm
        self.provider = 'google'
        self.model_name = os.getenv("GOOGLE_API_MODEL", "gemini-2.0-flash-exp")
    
    def __getattr__(self, name):
        # Delegate all other attributes to the wrapped LLM
        return getattr(self._llm, name)
    
    def __call__(self, *args, **kwargs):
        # Delegate calls to the wrapped LLM
        return self._llm(*args, **kwargs)

@app.route('/api/browseruse/navigation', methods=['POST'])
@llm_rate_limit
def browseruse_navigation():
    print("DEBUG: /api/browseruse/navigation endpoint was called")
    import os
    import json
    data = request.get_json() or {}
    steps = data.get('steps')
    task_prompt = data.get('prompt')
    # Initialize Google Generative AI using environment variables
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    base_llm = ChatGoogleGenerativeAI(
        model=os.getenv("GOOGLE_API_MODEL", "gemini-2.0-flash-exp"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.0,
        max_tokens=300
    )
    
    # Wrap the LLM with compatibility attributes
    llm = BrowserUseCompatibleLLM(base_llm)
    
    # Define a function to analyze screenshots for issues
    def analyze_screenshot(screenshot_data):
        """Analyze a screenshot for visual issues using Azure OpenAI."""
        if not screenshot_data:
            return None
            
        try:
            # Use the same LLM to analyze the screenshot
            analysis_prompt = (
                "Analyze this screenshot for visual issues such as: \n"
                "1. UI rendering problems (overlapping elements, misaligned components)\n"
                "2. Error messages or warnings visible on screen\n"
                "3. Missing content or broken images\n"
                "4. Unexpected popups or dialogs\n"
                "5. Form validation errors\n"
                "6. Responsive design issues\n\n"
                "If any issues are found, describe them in detail. If no issues are found, explicitly state 'No issues found'."
            )
            
            # Create a message with the screenshot as content
            messages = [
                {"role": "system", "content": analysis_prompt},
                {"role": "user", "content": f"Analyze this screenshot: {screenshot_data}"}
            ]
            
            # Use the Azure OpenAI client to analyze the screenshot
            response = openai.ChatCompletion.create(
                deployment_id=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                api_base=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_KEY"),
                messages=messages
            )
            
            analysis_result = response.choices[0].message.content
            
            # Check if the analysis found any issues
            if "no issues found" in analysis_result.lower():
                return {"has_issues": False, "analysis": analysis_result}
            else:
                return {"has_issues": True, "analysis": analysis_result}
                
        except Exception as e:
            logger.error(f"Error analyzing screenshot: {str(e)}")
            return {"has_issues": False, "analysis": f"Error during analysis: {str(e)}"}

    step_reports = []
    nav_data = None
    screenshot_url = None
    table_data = None
    error_count = 0
    # If steps are provided, build a single prompt and run the agent once
    if steps and isinstance(steps, list):
        # Build a single prompt from all steps
        prompt = '. '.join([step_to_description(step) for step in steps])
        agent = Agent(task=prompt, llm=llm)
        try:
            result = asyncio.run(agent.run())
            
            # Enhanced result parsing for better reporting
            error_val = None
            status = "pass"
            actual = ""
            
            # Check if result has success/error indicators
            if hasattr(result, 'success') and not result.success:
                status = "fail"
                error_val = getattr(result, 'error', 'Task failed without specific error')
            elif hasattr(result, 'error') and result.error:
                status = "fail"
                error_val = str(result.error)
            
            # Extract meaningful content
            if hasattr(result, 'extracted_content') and result.extracted_content:
                actual = str(result.extracted_content)
            elif hasattr(result, 'result') and result.result:
                actual = str(result.result)
            elif hasattr(result, 'output') and result.output:
                actual = str(result.output)
            else:
                # Parse the string representation for key information
                result_str = str(result)
                if 'success=True' in result_str:
                    actual = "Task completed successfully"
                elif 'success=False' in result_str:
                    status = "fail"
                    actual = "Task failed"
                    # Try to extract error details
                    import re
                    error_match = re.search(r'error=([^,\)]+)', result_str)
                    if error_match:
                        error_val = error_match.group(1).strip("'\"")
                else:
                    actual = "Task executed"
            
            # Extract additional details for comprehensive reporting
            navigation_info = []
            if hasattr(result, 'actions_taken'):
                for action in result.actions_taken:
                    if hasattr(action, 'action_type'):
                        navigation_info.append(f"{action.action_type}: {getattr(action, 'details', '')}")
            
            # Check if a screenshot was captured and analyze it
            screenshot_data = getattr(result, 'screenshot', None)
            screenshot_analysis = None
            if screenshot_data:
                # Analyze the screenshot for issues
                analysis_result = analyze_screenshot(screenshot_data)
                if analysis_result and analysis_result.get('has_issues'):
                    # If issues were found, update the status and error
                    status = "fail"
                    if not error_val:
                        error_val = f"Screenshot analysis found issues: {analysis_result.get('analysis')}"
                    screenshot_analysis = analysis_result.get('analysis')
                else:
                    screenshot_analysis = analysis_result.get('analysis') if analysis_result else None
                    
        except Exception as e:
            status = "fail"
            error_val = f"Agent execution failed: {str(e)}"
            actual = ""
        # Return a single step report for the whole flow
        def safe_serialize(val):
            # Only allow JSON-serializable types, else convert to string
            if isinstance(val, (str, int, float, bool)) or val is None:
                return val
            if isinstance(val, (list, dict)):
                return val
            return str(val)

        step_reports.append({
            "step": 1,
            "description": safe_serialize(prompt),
            "actual": safe_serialize(actual),
            "status": safe_serialize(status),
            "error": safe_serialize(error_val),
            "extracted_content": safe_serialize(getattr(result, 'extracted_content', None) if 'result' in locals() else None),
            "screenshot_analysis": safe_serialize(getattr(result, 'screenshot_analysis', None) if 'result' in locals() else None),
            "raw": str(result) if 'result' in locals() else ""
        })
        # Only include the raw output (no summary, errors, or step execution)
        raw_section = step_reports[0].get('raw', '') if step_reports and step_reports[0].get('raw') else 'No raw output.'
        details = raw_section
        # Build a summary report
        report = {
            "summary": f"Ran {len(steps)} steps as a single flow.",
            "error_count": 1 if status == "fail" else 0,
            "details": details
        }
        # Return as a single step in the response
        combined_steps = [{
            "intent": {"description": prompt},
            "result": step_reports[0]
        }]
        return jsonify({
            "steps": combined_steps,
            "report": report
        })
    # Fallback: single prompt mode (legacy)
    if not task_prompt or not task_prompt.strip():
        return jsonify({"error": "Prompt is required."}), 400
        
    agent = Agent(task=task_prompt, llm=llm)
    try:
        result = asyncio.run(agent.run())
        print("DEBUG: type(result) =", type(result))
        print("DEBUG: result repr =", repr(result))
        
        # Enhanced result processing for better error reporting
        nav_data = None
        screenshot_url = None
        table_data = None
        error_count = 0
        step_reports = []
        
        # Extract meaningful information from the result
        overall_status = "pass"
        overall_error = None
        
        # Check overall success/failure
        if hasattr(result, 'success') and not result.success:
            overall_status = "fail"
            overall_error = getattr(result, 'error', 'Task failed')
            error_count = 1
        elif hasattr(result, 'error') and result.error:
            overall_status = "fail"
            overall_error = str(result.error)
            error_count = 1
            
        # Try to extract individual action results for detailed reporting
        if hasattr(result, 'all_results') and result.all_results:
            print(f"DEBUG: Processing {len(result.all_results)} action results")
            for idx, action in enumerate(result.all_results):
                # Extract action details
                error_val = getattr(action, 'error', None)
                status = "pass" if not error_val else "fail"
                
                # Get action description
                action_type = getattr(action, 'action_type', 'unknown')
                action_input = getattr(action, 'action_input', '')
                if hasattr(action, 'tool_name'):
                    description = f"{action.tool_name}: {action_input}"
                elif action_type and action_type != 'unknown':
                    description = f"{action_type}: {action_input}"
                else:
                    description = str(action_input) or f"Action {idx + 1}"
                
                # Get action result
                actual = getattr(action, 'result', '') or getattr(action, 'extracted_content', '') or str(action)
                
                # Screenshot analysis for this action
                screenshot_data = getattr(action, 'screenshot', None)
                screenshot_analysis = None
                if screenshot_data:
                    analysis_result = analyze_screenshot(screenshot_data)
                    if analysis_result and analysis_result.get('has_issues'):
                        status = "fail"
                        if not error_val:
                            error_val = f"Screenshot analysis found issues: {analysis_result.get('analysis')}"
                        screenshot_analysis = analysis_result.get('analysis')
                    else:
                        screenshot_analysis = analysis_result.get('analysis') if analysis_result else None
                
                step_reports.append({
                    "step": idx + 1,
                    "description": description,
                    "actual": actual,
                    "status": status,
                    "error": error_val,
                    "extracted_content": getattr(action, 'extracted_content', None),
                    "screenshot_analysis": screenshot_analysis,
                    "raw": str(action)
                })
                
                if status == "fail":
                    error_count += 1
        else:
            # Fallback: create a single step report for the overall result
            result_str = str(result)
            description = task_prompt
            
            # Try to parse meaningful information from result string
            if 'NavigationResult' in result_str:
                actual = "Navigation completed"
            elif 'success=True' in result_str:
                actual = "Task completed successfully"
            elif 'success=False' in result_str:
                actual = "Task failed"
                overall_status = "fail"
                error_count = 1
            else:
                actual = "Task executed"
            
            step_reports.append({
                "step": 1,
                "description": description,
                "actual": actual,
                "status": overall_status,
                "error": overall_error,
                "extracted_content": None,
                "screenshot_analysis": None,
                "raw": result_str
            })
    
    except Exception as e:
        print(f"DEBUG: Exception during agent execution: {e}")
        overall_status = "fail"
        overall_error = f"Agent execution failed: {str(e)}"
        error_count = 1
        step_reports = [{
            "step": 1,
            "description": task_prompt,
            "actual": "",
            "status": "fail",
            "error": overall_error,
            "extracted_content": None,
            "screenshot_analysis": None,
            "raw": str(e)
        }]
    # Build combined steps for response
    combined_steps = []
    for idx, step_report in enumerate(step_reports):
        combined_steps.append({
            "intent": {"description": step_report.get("description", "")},
            "result": step_report
        })
    
    # Build comprehensive report
    total_steps = len(step_reports)
    failed_steps = len([s for s in step_reports if s.get("status") == "fail"])
    passed_steps = total_steps - failed_steps
    
    # Create detailed summary
    if total_steps == 0:
        summary = "No steps were executed"
        details = "The browser automation agent did not generate any actionable steps"
    elif failed_steps == 0:
        summary = f"✅ All {total_steps} step(s) completed successfully"
        details = f"Browser automation executed {total_steps} step(s) without errors"
    else:
        summary = f"⚠️ {failed_steps} of {total_steps} step(s) failed"
        details = f"Browser automation completed with {passed_steps} successful and {failed_steps} failed step(s)"
        
        # Add error details to summary
        error_details = []
        for step in step_reports:
            if step.get("status") == "fail" and step.get("error"):
                error_details.append(f"Step {step.get('step', '?')}: {step.get('error', 'Unknown error')}")
        
        if error_details:
            details += "\n\nErrors encountered:\n" + "\n".join(error_details[:3])  # Limit to first 3 errors
            if len(error_details) > 3:
                details += f"\n... and {len(error_details) - 3} more error(s)"
    
    report = {
        "summary": summary,
        "error_count": failed_steps,
        "total_steps": total_steps,
        "details": details
    }
    
    return jsonify({
        "navigation": nav_data or [],
        "screenshot_url": screenshot_url,
        "table_data": table_data,
        "raw": str(result) if 'result' in locals() else "",
        "report": report,
        "steps": combined_steps
    })

@app.route('/browseruse-automation')
def browseruse_automation():
    """BrowserUse automation page with redesigned UI"""
    return render_template('browseruse-automation-simple.html', active_tab='browseruse')

@app.route('/api/browseruse/custom-instruction', methods=['POST'])
def browseruse_custom_instruction():
    """Execute custom AI instruction using Google Gemini Computer Use"""
    try:
        from google import genai
        from google.genai import types
        from playwright.sync_api import sync_playwright
        import time
        
        data = request.json
        instruction = data.get('instruction', '').strip()
        
        if not instruction:
            return jsonify({
                "success": False,
                "error": "No instruction provided"
            }), 400
        
        # Initialize Google Gemini Client
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        
        # Screen dimensions
        SCREEN_WIDTH = 1440
        SCREEN_HEIGHT = 900
        
        # Initialize execution report data
        execution_report = {
            "instruction": instruction,
            "start_time": time.time(),
            "steps": [],
            "screenshots": [],
            "errors": [],
            "success": False
        }
        
        # Helper functions for coordinate conversion
        def denormalize_x(x: int, screen_width: int) -> int:
            return int(x / 1000 * screen_width)
        
        def denormalize_y(y: int, screen_height: int) -> int:
            return int(y / 1000 * screen_height)
        
        def execute_function_calls(candidate, page, screen_width, screen_height):
            """Execute function calls from Gemini Computer Use"""
            results = []
            function_calls = []
            
            for part in candidate.content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)
            
            for function_call in function_calls:
                action_result = {}
                fname = function_call.name
                args = function_call.args
                
                print(f"  🎬 Action: {fname} | Args: {args}")
                
                try:
                    if fname == "open_web_browser":
                        print("  ✅ Browser already open")
                    elif fname == "navigate":
                        print(f"  🌐 Navigating to: {args['url']}")
                        page.goto(args["url"], timeout=30000)
                        time.sleep(1)  # Let page settle
                        print(f"  ✅ Navigated to: {page.url}")
                    elif fname == "click_at":
                        actual_x = denormalize_x(args["x"], screen_width)
                        actual_y = denormalize_y(args["y"], screen_height)
                        print(f"  🖱️ Clicking at ({actual_x}, {actual_y})")
                        page.mouse.click(actual_x, actual_y)
                        time.sleep(0.5)  # Let action complete
                        print("  ✅ Click completed")
                    elif fname == "type_text_at":
                        actual_x = denormalize_x(args["x"], screen_width)
                        actual_y = denormalize_y(args["y"], screen_height)
                        text = args["text"]
                        press_enter = args.get("press_enter", False)
                        clear_before = args.get("clear_before_typing", True)
                        
                        page.mouse.click(actual_x, actual_y)
                        time.sleep(0.3)
                        if clear_before:
                            page.keyboard.press("Control+A")
                            page.keyboard.press("Backspace")
                            time.sleep(0.2)
                        page.keyboard.type(text, delay=50)  # 50ms between keystrokes
                        if press_enter:
                            page.keyboard.press("Enter")
                            time.sleep(0.5)
                    elif fname == "scroll_document":
                        direction = args["direction"]
                        if direction == "down":
                            page.keyboard.press("PageDown")
                        elif direction == "up":
                            page.keyboard.press("PageUp")
                    elif fname == "go_back":
                        page.go_back()
                    elif fname == "go_forward":
                        page.go_forward()
                    elif fname == "search":
                        page.goto("https://www.google.com")
                    elif fname == "wait_5_seconds":
                        time.sleep(5)
                    elif fname == "hover_at":
                        actual_x = denormalize_x(args["x"], screen_width)
                        actual_y = denormalize_y(args["y"], screen_height)
                        page.mouse.move(actual_x, actual_y)
                    elif fname == "key_combination":
                        page.keyboard.press(args["keys"])
                    else:
                        action_result = {"warning": f"Unimplemented function {fname}"}
                    
                    # Wait for page to settle (increased timeout, make it optional)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception as wait_error:
                        # Continue even if wait times out - page might be functional
                        print(f"Wait timeout (non-critical): {wait_error}")
                    
                except Exception as e:
                    print(f"Error executing {fname}: {e}")
                    action_result = {"error": str(e)}
                
                results.append((fname, action_result))
            
            return results
        
        def get_function_responses(page, results):
            """Get function responses with screenshot"""
            screenshot_bytes = page.screenshot(type="png")
            current_url = page.url
            function_responses = []
            
            for name, result in results:
                response_data = {"url": current_url}
                response_data.update(result)
                function_responses.append(
                    types.FunctionResponse(
                        name=name,
                        response=response_data,
                        parts=[types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type="image/png",
                                data=screenshot_bytes
                            )
                        )]
                    )
                )
            return function_responses
        
        # Initialize Playwright browser
        print(f"🚀 Starting Computer Use automation for: {instruction}")
        playwright = sync_playwright().start()
        
        # Launch browser in visible mode so you can see what's happening
        browser = playwright.chromium.launch(
            headless=False,  # Changed to False - browser will be visible!
            args=['--start-maximized']
        )
        context = browser.new_context(
            viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
            no_viewport=False
        )
        page = context.new_page()
        print("✅ Browser launched successfully")
        
        # Set default navigation timeout
        page.set_default_navigation_timeout(30000)  # 30 seconds
        page.set_default_timeout(30000)  # 30 seconds for all operations
        
        try:
            # Go to initial page (with generous timeout)
            print("🌐 Navigating to initial page...")
            try:
                page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30000)
                print(f"✅ Loaded: {page.url}")
            except Exception as goto_error:
                print(f"⚠️ Initial navigation warning: {goto_error}")
                # Continue anyway - page might be loaded enough
            
            # Configure Computer Use
            print("🤖 Configuring Gemini 2.5 Computer Use...")
            config = types.GenerateContentConfig(
                tools=[types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER
                    )
                )],
            )
            
            # Initialize history with screenshot
            print("📸 Capturing initial screenshot...")
            initial_screenshot = page.screenshot(type="png")
            print(f"✅ Screenshot captured ({len(initial_screenshot)} bytes)")
            
            contents = [
                types.Content(role="user", parts=[
                    types.Part(text=instruction),
                    types.Part.from_bytes(data=initial_screenshot, mime_type='image/png')
                ])
            ]
            
            # Agent loop
            turn_limit = 10
            steps_executed = 0
            final_result = None
            
            print(f"🔄 Starting agent loop (max {turn_limit} turns)...")
            for i in range(turn_limit):
                steps_executed = i + 1
                step_start_time = time.time()
                print(f"\n--- Turn {steps_executed}/{turn_limit} ---")
                
                # Generate response
                print("🧠 Asking Gemini 2.5 Computer Use for next action...")
                response = client.models.generate_content(
                    model='gemini-2.5-computer-use-preview-10-2025',
                    contents=contents,
                    config=config,
                )
                print("✅ Got response from Gemini")
                
                candidate = response.candidates[0]
                contents.append(candidate.content)
                
                # Check if task is complete
                has_function_calls = any(part.function_call for part in candidate.content.parts)
                print(f"📋 Function calls to execute: {sum(1 for part in candidate.content.parts if part.function_call)}")
                
                if not has_function_calls:
                    # Extract text response as final result
                    final_result = " ".join([part.text for part in candidate.content.parts if part.text])
                    print(f"✅ Task complete! Result: {final_result[:100]}...")
                    
                    # Record final step
                    execution_report["steps"].append({
                        "step_number": steps_executed,
                        "action": "task_complete",
                        "result": final_result,
                        "url": page.url,
                        "duration_ms": int((time.time() - step_start_time) * 1000)
                    })
                    break
                
                # Execute actions
                print("⚡ Executing actions...")
                results = execute_function_calls(candidate, page, SCREEN_WIDTH, SCREEN_HEIGHT)
                print(f"✅ Executed {len(results)} actions")
                
                # Capture screenshot after actions
                screenshot = page.screenshot(type="png")
                import base64
                screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                
                # Record step details
                step_data = {
                    "step_number": steps_executed,
                    "actions": [],
                    "url": page.url,
                    "screenshot": screenshot_base64,
                    "duration_ms": int((time.time() - step_start_time) * 1000)
                }
                
                # Record each action
                for action_name, action_result in results:
                    step_data["actions"].append({
                        "name": action_name,
                        "result": action_result
                    })
                
                execution_report["steps"].append(step_data)
                execution_report["screenshots"].append({
                    "step": steps_executed,
                    "url": page.url,
                    "data": screenshot_base64
                })
                
                # Get function responses
                print("📸 Capturing feedback screenshot...")
                function_responses = get_function_responses(page, results)
                print(f"✅ Got {len(function_responses)} function responses")
                
                # Add to conversation
                contents.append(
                    types.Content(role="user", parts=[
                        types.Part(function_response=fr) for fr in function_responses
                    ])
                )
            
            # Complete execution report
            execution_report["success"] = True
            execution_report["end_time"] = time.time()
            execution_report["duration_seconds"] = round(execution_report["end_time"] - execution_report["start_time"], 2)
            execution_report["final_url"] = page.url
            execution_report["final_result"] = final_result or f"Task completed in {steps_executed} steps"
            execution_report["steps_executed"] = steps_executed
            
            # Capture final screenshot
            final_screenshot = page.screenshot(type="png")
            final_screenshot_base64 = base64.b64encode(final_screenshot).decode('utf-8')
            execution_report["final_screenshot"] = final_screenshot_base64
            
            # Return success
            print(f"\n🎉 Task completed successfully!")
            print(f"📊 Steps executed: {steps_executed}")
            print(f"🌐 Final URL: {page.url}")
            print(f"💬 Result: {final_result or 'Task completed'}")
            print(f"⏱️  Duration: {execution_report['duration_seconds']}s")
            print(f"📸 Screenshots captured: {len(execution_report['screenshots'])}")
            
            result = {
                "success": True,
                "result": final_result or f"Task completed in {steps_executed} steps",
                "steps_executed": steps_executed,
                "final_url": page.url,
                "duration_seconds": execution_report["duration_seconds"],
                "execution_report": execution_report
            }
            
            return jsonify(result)
            
        finally:
            # Cleanup
            print("🧹 Cleaning up browser...")
            try:
                browser.close()
                playwright.stop()
                print("✅ Cleanup complete")
            except Exception as cleanup_error:
                print(f"⚠️ Cleanup warning: {cleanup_error}")
            
    except Exception as e:
        print(f"\n❌ ERROR in custom instruction execution: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            "success": False,
            "error": str(e),
            "details": traceback.format_exc()
        }), 500

@app.route('/playwright-mcp-automation')
def playwright_mcp_automation():
    """Playwright MCP automation with plain text instructions"""
    return render_template('playwright-mcp-automation.html', active_tab='playwright-mcp')

@app.route('/api/playwright-mcp/execute', methods=['POST'])
def playwright_mcp_execute():
    """Execute Playwright automation from plain text instructions using AI interpretation"""
    try:
        from google import genai
        from google.genai import types
        from playwright.sync_api import sync_playwright
        import time
        
        data = request.json
        instruction = data.get('instruction', '').strip()
        
        if not instruction:
            return jsonify({
                "success": False,
                "error": "No instruction provided"
            }), 400
        
        print(f"\n🎭 Starting Playwright MCP Automation")
        print(f"📝 Instruction: {instruction}")
        
        # Initialize Google Gemini Client for instruction interpretation
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        
        # Initialize execution report
        execution_report = {
            "instruction": instruction,
            "start_time": time.time(),
            "steps": [],
            "screenshots": [],
            "errors": [],
            "success": False
        }
        
        # Launch Playwright browser
        print("🌐 Launching browser...")
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=False,
            args=['--start-maximized']
        )
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = context.new_page()
        
        try:
            # Use AI to interpret instructions and generate Playwright actions
            print("🤖 Interpreting instructions with AI...")
            
            interpretation_prompt = f"""You are a Playwright automation expert. Convert the following plain text instruction into a structured list of Playwright actions.

Instruction: {instruction}

Provide a JSON array of action objects. Each action should have:
- action: The Playwright method (navigate, click, fill, select, press, wait, screenshot, etc.)
- selector: CSS selector (if applicable)
- value: Text value or option (if applicable)
- url: URL (if navigate)
- description: Human-readable description

Available actions:
- navigate: Go to URL
- click: Click element
- fill: Fill input field
- select: Select dropdown option
- press: Press keyboard key
- wait: Wait for milliseconds
- waitForSelector: Wait for element to appear
- screenshot: Take screenshot
- getText: Get text content
- getAttribute: Get element attribute

Example output:
[
  {{"action": "navigate", "url": "https://google.com", "description": "Navigate to Google"}},
  {{"action": "fill", "selector": "input[name='q']", "value": "playwright", "description": "Search for playwright"}},
  {{"action": "press", "selector": "input[name='q']", "value": "Enter", "description": "Submit search"}},
  {{"action": "screenshot", "description": "Capture search results"}}
]

Return ONLY the JSON array, no other text."""

            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=interpretation_prompt
            )
            
            # Parse AI response to get actions
            response_text = response.text.strip()
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            actions = json.loads(response_text)
            print(f"✅ Generated {len(actions)} actions")
            
            # Execute each action
            for i, action_spec in enumerate(actions, 1):
                step_start = time.time()
                action_type = action_spec.get('action', '')
                description = action_spec.get('description', f'Step {i}')
                
                print(f"\n📍 Step {i}: {description}")
                
                try:
                    result = None
                    
                    if action_type == 'navigate':
                        url = action_spec.get('url', '')
                        print(f"   → Navigating to {url}")
                        page.goto(url, wait_until='domcontentloaded', timeout=30000)
                        result = f"Navigated to {url}"
                        
                    elif action_type == 'click':
                        selector = action_spec.get('selector', '')
                        print(f"   → Clicking {selector}")
                        page.click(selector, timeout=10000)
                        result = f"Clicked {selector}"
                        
                    elif action_type == 'fill':
                        selector = action_spec.get('selector', '')
                        value = action_spec.get('value', '')
                        print(f"   → Filling {selector} with '{value}'")
                        page.fill(selector, value, timeout=10000)
                        result = f"Filled {selector} with '{value}'"
                        
                    elif action_type == 'select':
                        selector = action_spec.get('selector', '')
                        value = action_spec.get('value', '')
                        print(f"   → Selecting '{value}' in {selector}")
                        page.select_option(selector, value, timeout=10000)
                        result = f"Selected '{value}' in {selector}"
                        
                    elif action_type == 'press':
                        selector = action_spec.get('selector', '')
                        key = action_spec.get('value', '')
                        print(f"   → Pressing '{key}' on {selector}")
                        if selector:
                            page.press(selector, key, timeout=10000)
                        else:
                            page.keyboard.press(key)
                        result = f"Pressed '{key}'"
                        
                    elif action_type == 'wait':
                        ms = int(action_spec.get('value', 1000))
                        print(f"   → Waiting {ms}ms")
                        time.sleep(ms / 1000)
                        result = f"Waited {ms}ms"
                        
                    elif action_type == 'waitForSelector':
                        selector = action_spec.get('selector', '')
                        print(f"   → Waiting for {selector}")
                        page.wait_for_selector(selector, timeout=10000)
                        result = f"Element {selector} appeared"
                        
                    elif action_type == 'screenshot':
                        print(f"   → Taking screenshot")
                        screenshot = page.screenshot(type="png")
                        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                        execution_report["screenshots"].append({
                            "step": i,
                            "description": description,
                            "data": screenshot_base64
                        })
                        result = "Screenshot captured"
                        
                    elif action_type == 'getText':
                        selector = action_spec.get('selector', '')
                        print(f"   → Getting text from {selector}")
                        text = page.locator(selector).inner_text(timeout=10000)
                        result = f"Text: {text[:100]}"
                        
                    elif action_type == 'getAttribute':
                        selector = action_spec.get('selector', '')
                        attr = action_spec.get('attribute', 'value')
                        print(f"   → Getting {attr} from {selector}")
                        value = page.locator(selector).get_attribute(attr, timeout=10000)
                        result = f"{attr}: {value}"
                    
                    else:
                        result = f"Unknown action: {action_type}"
                        print(f"   ⚠️ {result}")
                    
                    # Capture screenshot after each step
                    step_screenshot = page.screenshot(type="png")
                    step_screenshot_base64 = base64.b64encode(step_screenshot).decode('utf-8')
                    
                    # Record step
                    step_duration = int((time.time() - step_start) * 1000)
                    execution_report["steps"].append({
                        "step_number": i,
                        "action": action_type,
                        "description": description,
                        "selector": action_spec.get('selector', ''),
                        "value": action_spec.get('value', ''),
                        "url": page.url,
                        "result": result,
                        "screenshot": step_screenshot_base64,
                        "duration_ms": step_duration,
                        "success": True
                    })
                    
                    print(f"   ✅ Success: {result}")
                    
                except Exception as step_error:
                    error_msg = str(step_error)
                    print(f"   ❌ Error: {error_msg}")
                    
                    # Record failed step
                    step_duration = int((time.time() - step_start) * 1000)
                    execution_report["steps"].append({
                        "step_number": i,
                        "action": action_type,
                        "description": description,
                        "error": error_msg,
                        "url": page.url,
                        "duration_ms": step_duration,
                        "success": False
                    })
                    execution_report["errors"].append({
                        "step": i,
                        "error": error_msg
                    })
                    
                    # Continue with next step
                    continue
            
            # Finalize report
            execution_report["end_time"] = time.time()
            execution_report["duration_seconds"] = round(execution_report["end_time"] - execution_report["start_time"], 2)
            execution_report["success"] = len(execution_report["errors"]) == 0
            execution_report["final_url"] = page.url
            
            # Final screenshot
            final_screenshot = page.screenshot(type="png")
            execution_report["final_screenshot"] = base64.b64encode(final_screenshot).decode('utf-8')
            
            print(f"\n🎉 Automation completed!")
            print(f"📊 Steps: {len(execution_report['steps'])}")
            print(f"✅ Success: {execution_report['success']}")
            print(f"❌ Errors: {len(execution_report['errors'])}")
            print(f"⏱️  Duration: {execution_report['duration_seconds']}s")
            
            return jsonify({
                "success": True,
                "execution_report": execution_report
            })
            
        finally:
            # Cleanup
            print("🧹 Cleaning up browser...")
            try:
                browser.close()
                playwright.stop()
                print("✅ Cleanup complete")
            except Exception as cleanup_error:
                print(f"⚠️ Cleanup warning: {cleanup_error}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        print(traceback.format_exc())
        return jsonify({
            "success": False,
            "error": str(e),
            "details": traceback.format_exc()
        }), 500

@app.route('/api/playwright-mcp/import-jira/<ticket_id>', methods=['GET'])
def playwright_mcp_import_jira(ticket_id):
    """Import Jira ticket description as automation instruction"""
    try:
        # Check if user is authenticated with Jira
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not access_token or not cloud_id:
            return jsonify({
                'success': False,
                'error': 'Not authenticated with Jira. Please connect to Jira first.'
            }), 401
        
        # Check if token needs refresh
        token_expires = session.get('jira_token_expires', 0)
        if time.time() >= token_expires:
            if not refresh_jira_token():
                return jsonify({
                    'success': False,
                    'error': 'Jira token expired. Please reconnect to Jira.'
                }), 401
            access_token = session['jira_access_token']
        
        # Fetch issue from Jira API
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        jira_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{ticket_id}'
        response = requests.get(jira_url, headers=headers, timeout=30)
        
        if response.status_code == 404:
            return jsonify({
                'success': False,
                'error': f'Jira ticket {ticket_id} not found'
            }), 404
        elif response.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'Failed to fetch Jira ticket: {response.status_code}'
            }), response.status_code
        
        issue_data = response.json()
        
        # Extract description
        description = issue_data.get('fields', {}).get('description', '')
        
        # Handle different description formats (ADF or plain text)
        if isinstance(description, dict):
            # Atlassian Document Format (ADF)
            description_text = extract_text_from_adf(description)
        else:
            description_text = description or ''
        
        if not description_text:
            return jsonify({
                'success': False,
                'error': f'Jira ticket {ticket_id} has no description'
            }), 400
        
        return jsonify({
            'success': True,
            'description': description_text,
            'ticket_id': ticket_id,
            'summary': issue_data.get('fields', {}).get('summary', '')
        })
        
    except Exception as e:
        logger.error(f"Error importing from Jira: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def extract_text_from_adf(adf_content):
    """Extract plain text from Atlassian Document Format (ADF)"""
    if not isinstance(adf_content, dict):
        return str(adf_content)
    
    text_parts = []
    
    def traverse(node):
        if isinstance(node, dict):
            # Extract text from text nodes
            if node.get('type') == 'text':
                text_parts.append(node.get('text', ''))
            
            # Traverse content array
            if 'content' in node:
                for child in node['content']:
                    traverse(child)
        elif isinstance(node, list):
            for item in node:
                traverse(item)
    
    traverse(adf_content)
    return ' '.join(text_parts).strip()

@app.route('/api/playwright-mcp/export-jira/<ticket_id>', methods=['POST'])
def playwright_mcp_export_jira(ticket_id):
    """Export Playwright MCP execution results to Jira as a comment"""
    try:
        # Check if user is authenticated with Jira
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not access_token or not cloud_id:
            return jsonify({
                'success': False,
                'error': 'Not authenticated with Jira. Please connect to Jira first.'
            }), 401
        
        # Check if token needs refresh
        token_expires = session.get('jira_token_expires', 0)
        if time.time() >= token_expires:
            if not refresh_jira_token():
                return jsonify({
                    'success': False,
                    'error': 'Jira token expired. Please reconnect to Jira.'
                }), 401
            access_token = session['jira_access_token']
        
        # Get results from request
        data = request.json
        results = data.get('results', '')
        screenshots_data = data.get('screenshots', {})
        
        if not results:
            return jsonify({
                'success': False,
                'error': 'No results to export'
            }), 400
        
        # Upload test report and screenshots as attachments
        uploaded_attachments = []
        attachment_ids = []
        
        # Get full report data
        report_data = data.get('report', {})
        
        # 1. Upload comprehensive test report as HTML file
        try:
            html_report = generate_html_test_report(report_data, results)
            report_attachment_result = upload_html_report_to_jira(
                access_token, cloud_id, ticket_id, html_report, 
                f'playwright_test_report_{ticket_id}.html'
            )
            if report_attachment_result and len(report_attachment_result) > 0:
                uploaded_attachments.append({
                    'filename': f'playwright_test_report_{ticket_id}.html',
                    'id': report_attachment_result[0].get('id'),
                    'description': 'Comprehensive Test Report'
                })
                attachment_ids.append(report_attachment_result[0].get('id'))
        except Exception as report_error:
            logger.warning(f"Failed to upload test report: {report_error}")
        
        # 2. Upload final screenshot if available
        if screenshots_data:
            try:
                final_screenshot = screenshots_data.get('final_screenshot')
                if final_screenshot:
                    attachment_result = upload_screenshot_to_jira(
                        access_token, cloud_id, ticket_id, 
                        final_screenshot, 'automation_result.png'
                    )
                    if attachment_result and len(attachment_result) > 0:
                        uploaded_attachments.append({
                            'filename': 'automation_result.png',
                            'id': attachment_result[0].get('id'),
                            'description': 'Final Automation Screenshot'
                        })
                        attachment_ids.append(attachment_result[0].get('id'))
            except Exception as attach_error:
                logger.warning(f"Failed to upload screenshot: {attach_error}")
        
        # Convert markdown to ADF format for Jira (with embedded images)
        try:
            adf_comment = convert_markdown_to_adf(results, uploaded_attachments)
            
            # Validate ADF structure
            if not validate_adf_structure(adf_comment):
                logger.warning("Generated ADF structure is invalid, using fallback")
                # Fallback to simple text format
                adf_comment = create_simple_adf_comment(results, uploaded_attachments)
        except Exception as adf_error:
            logger.error(f"ADF conversion failed: {adf_error}, using simple format")
            # Fallback to simple text format
            adf_comment = create_simple_adf_comment(results, uploaded_attachments)
        
        # Post comment to Jira
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        jira_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{ticket_id}/comment'
        comment_payload = {
            'body': adf_comment
        }
        
        response = requests.post(jira_url, headers=headers, json=comment_payload, timeout=30)
        
        if response.status_code == 404:
            return jsonify({
                'success': False,
                'error': f'Jira ticket {ticket_id} not found'
            }), 404
        elif response.status_code not in [200, 201]:
            # Log the error details for debugging
            error_detail = response.text
            logger.error(f"Jira API error: {response.status_code} - {error_detail}")
            
            # For ADF validation errors, provide more specific guidance
            if "ATTACHMENT_VALIDATION_ERROR" in error_detail:
                logger.error("ADF validation error - likely due to media reference issues")
                return jsonify({
                    'success': False,
                    'error': 'ADF format validation failed - screenshot was uploaded but could not be embedded in comment',
                    'details': 'Screenshot attached successfully, but comment formatting had validation issues'
                }), 400
            else:
                # Only log ADF payload for other errors to avoid sensitive data exposure
                logger.debug(f"ADF payload structure: {len(adf_comment.get('content', []))} content blocks")
                
            return jsonify({
                'success': False,
                'error': f'Failed to post comment to Jira: {response.status_code}',
                'details': error_detail
            }), response.status_code
        
        comment_id = response.json().get('id')
        
        return jsonify({
            'success': True,
            'ticket_id': ticket_id,
            'comment_id': comment_id,
            'attachments_uploaded': len(uploaded_attachments),
            'attachment_names': [a['filename'] for a in uploaded_attachments]
        })
        
    except Exception as e:
        logger.error(f"Error exporting to Jira: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def generate_html_test_report(report_data, markdown_results):
    """Generate a comprehensive HTML test report"""
    import html
    
    try:
        # Extract key information from report
        instruction = html.escape(report_data.get('instruction', 'No instruction provided'))
        status = report_data.get('status', 'UNKNOWN')
        duration = report_data.get('duration', 0)
        steps = report_data.get('steps', [])
        
        # Calculate success rate
        total_steps = len(steps)
        passed_steps = sum(1 for step in steps if step.get('status') == 'PASS')
        failed_steps = total_steps - passed_steps
        success_rate = (passed_steps / total_steps * 100) if total_steps > 0 else 0
        
        # Determine overall status color and icon
        status_class = 'status-success' if status == 'SUCCESS' else 'status-failed'
        status_icon = '✓' if status == 'SUCCESS' else '✗'
        
        # Generate HTML report
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Playwright MCP Test Report</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            line-height: 1.6;
            background: #f5f7fa;
            color: #333;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
        .header h1 {{ margin: 0 0 15px 0; font-size: 2em; }}
        .header p {{ margin: 5px 0; opacity: 0.95; }}
        .status-badge {{
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 1.1em;
            margin-top: 10px;
        }}
        .status-success {{ background: #28a745; color: white; }}
        .status-failed {{ background: #dc3545; color: white; }}
        .summary-grid {{ 
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .summary-card {{ 
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border: none;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .summary-value {{ font-size: 2.5em; font-weight: bold; margin: 10px 0; color: #667eea; }}
        .summary-label {{ font-size: 0.9em; color: #666; text-transform: uppercase; letter-spacing: 1px; }}
        .summary-sublabel {{ font-size: 1.2em; font-weight: 600; margin-top: 5px; color: #333; }}
        .steps-section {{ margin-top: 30px; }}
        .steps-section h2 {{ color: #667eea; border-bottom: 3px solid #667eea; padding-bottom: 10px; }}
        .steps-table {{ 
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .steps-table th, .steps-table td {{ 
            border: 1px solid #e1e8ed;
            padding: 14px;
            text-align: left;
        }}
        .steps-table th {{ 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85em;
            letter-spacing: 0.5px;
        }}
        .steps-table tbody tr:hover {{ background: #f8f9fa; }}
        .step-pass {{ background: #d4edda; }}
        .step-fail {{ background: #f8d7da; }}
        .step-number {{ font-weight: bold; font-size: 1.1em; color: #667eea; }}
        .step-status-pass {{ color: #28a745; font-weight: bold; }}
        .step-status-fail {{ color: #dc3545; font-weight: bold; }}
        .code {{ 
            background: #f4f5f7;
            padding: 3px 8px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            color: #d73a49;
            border: 1px solid #e1e4e8;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 2px solid #e1e8ed;
            text-align: center;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎭 Playwright MCP Automation Report</h1>
            <p><strong>Test Instruction:</strong> {instruction}</p>
            <p><strong>Generated:</strong> {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
            <div class="status-badge {status_class}">{status_icon} {status}</div>
        </div>
        
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-label">Total Steps</div>
                <div class="summary-value">{total_steps}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Passed</div>
                <div class="summary-value" style="color: #28a745;">{passed_steps}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Failed</div>
                <div class="summary-value" style="color: #dc3545;">{failed_steps}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Success Rate</div>
                <div class="summary-value">{success_rate:.1f}%</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Duration</div>
                <div class="summary-value" style="font-size: 1.8em;">{duration/1000:.2f}s</div>
            </div>
        </div>
        
        <div class="steps-section">
            <h2>📋 Execution Steps</h2>
            <table class="steps-table">
                <thead>
                    <tr>
                        <th style="width: 60px;">Step</th>
                        <th style="width: 100px;">Status</th>
                        <th>Description</th>
                        <th style="width: 120px;">Action</th>
                        <th style="width: 100px;">Duration</th>
                    </tr>
                </thead>
                <tbody>
"""
        
        # Add step details
        for i, step in enumerate(steps, 1):
            step_status = step.get('status', 'UNKNOWN')
            step_class = 'step-pass' if step_status == 'PASS' else 'step-fail'
            status_text_class = 'step-status-pass' if step_status == 'PASS' else 'step-status-fail'
            status_icon = '✓' if step_status == 'PASS' else '✗'
            
            description = html.escape(step.get('description', 'No description'))
            action = html.escape(step.get('action', 'N/A'))
            duration_ms = step.get('duration', 0)
            
            html_content += f"""
                    <tr class="{step_class}">
                        <td class="step-number">{i}</td>
                        <td class="{status_text_class}">{status_icon} {step_status}</td>
                        <td>{description}</td>
                        <td><span class="code">{action}</span></td>
                        <td>{duration_ms}ms</td>
                    </tr>
"""
        
        html_content += f"""
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>Generated by Playwright MCP Automation Framework</p>
            <p>Total Execution Time: {duration/1000:.2f} seconds | Success Rate: {success_rate:.1f}%</p>
        </div>
    </div>
</body>
</html>
"""
        
        return html_content
        
    except Exception as e:
        logger.error(f"Failed to generate HTML report: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Fallback simple report
        return f"""
<!DOCTYPE html>
<html><head>
    <meta charset="UTF-8">
    <title>Test Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        .error {{ background: #f8d7da; border: 1px solid #dc3545; padding: 15px; border-radius: 5px; }}
    </style>
</head>
<body>
    <h1>Playwright MCP Test Report</h1>
    <div class="error">
        <p><strong>Error generating detailed report.</strong></p>
        <p>Report data: {str(report_data)[:200]}</p>
    </div>
</body></html>
"""

def upload_html_report_to_jira(access_token, cloud_id, ticket_id, html_content, filename):
    """Upload an HTML report as attachment to Jira ticket"""
    try:
        # Convert HTML content to bytes
        html_bytes = html_content.encode('utf-8')
        
        # Prepare multipart form data
        files = {
            'file': (filename, html_bytes, 'text/html')
        }
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Atlassian-Token': 'no-check'
        }
        
        # Upload to Jira
        upload_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{ticket_id}/attachments'
        
        response = requests.post(upload_url, headers=headers, files=files, timeout=60)
        
        if response.status_code == 200:
            attachments = response.json()
            logger.info(f"Successfully uploaded HTML report: {filename}")
            return attachments
        else:
            logger.error(f"Failed to upload HTML report: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error uploading HTML report: {str(e)}")
        return None

def upload_screenshot_to_jira(access_token, cloud_id, ticket_id, screenshot_base64, filename):
    """Upload a screenshot as attachment to Jira ticket"""
    import base64
    import io
    
    try:
        # Decode base64 screenshot
        screenshot_bytes = base64.b64decode(screenshot_base64)
        
        # Prepare multipart upload
        files = {
            'file': (filename, io.BytesIO(screenshot_bytes), 'image/png')
        }
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'X-Atlassian-Token': 'no-check'
        }
        
        attachment_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{ticket_id}/attachments'
        
        response = requests.post(attachment_url, headers=headers, files=files, timeout=30)
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            logger.error(f"Failed to upload attachment {filename}: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Error uploading screenshot {filename}: {str(e)}")
        return None

def convert_markdown_to_adf(markdown_text, uploaded_attachments=None):
    """Convert markdown-style Jira wiki text to Atlassian Document Format (ADF)"""
    import re
    
    # Parse the markdown and convert to ADF
    adf = {
        "version": 1,
        "type": "doc",
        "content": []
    }
    
    uploaded_attachments = uploaded_attachments or []
    
    lines = markdown_text.split('\n')
    current_paragraph = []
    in_table = False
    table_rows = []
    
    def parse_text_with_formatting(text):
        """Parse text with color and code formatting"""
        parts = []
        
        # Clean up text - remove double backslashes and other problematic characters
        text = text.replace('\\\\', ' / ').replace('\\', ' / ')
        
        # Handle {color:xxx}text{color}
        color_pattern = r'\{color:(\w+)\}([^{]+)\{color\}'
        text_parts = re.split(color_pattern, text)
        
        i = 0
        while i < len(text_parts):
            part = text_parts[i]
            if not part:
                i += 1
                continue
            
            # Check if this is a color name followed by colored text
            if i + 2 < len(text_parts) and text_parts[i] in ['green', 'red', 'blue', 'orange']:
                color = text_parts[i]
                colored_text = text_parts[i + 1]
                parts.append({"type": "text", "text": colored_text})
                i += 3
            # Handle inline code {{text}}
            elif '{{' in part and '}}' in part:
                code_parts = re.split(r'\{\{([^}]+)\}\}', part)
                for j, code_part in enumerate(code_parts):
                    if j % 2 == 1:  # Odd indices are code
                        parts.append({"type": "text", "text": code_part, "marks": [{"type": "code"}]})
                    elif code_part:
                        parts.append({"type": "text", "text": code_part})
                i += 1
            else:
                if part:
                    parts.append({"type": "text", "text": part})
                i += 1
        
        return parts if parts else [{"type": "text", "text": text}]
    
    def finalize_paragraph():
        nonlocal current_paragraph
        if current_paragraph:
            text = ' '.join(current_paragraph)
            adf["content"].append({
                "type": "paragraph",
                "content": parse_text_with_formatting(text)
            })
            current_paragraph = []
    
    def finalize_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            # Build ADF table structure
            table = {
                "type": "table",
                "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
                "content": []
            }
            
            for row_idx, row in enumerate(table_rows):
                is_header = row_idx == 0
                table_row = {
                    "type": "tableRow",
                    "content": []
                }
                
                for cell in row:
                    table_row["content"].append({
                        "type": "tableHeader" if is_header else "tableCell",
                        "content": [{
                            "type": "paragraph",
                            "content": parse_text_with_formatting(cell)
                        }]
                    })
                
                table["content"].append(table_row)
            
            adf["content"].append(table)
            table_rows = []
            in_table = False
    
    for line in lines:
        line_stripped = line.strip()
        
        if not line_stripped:
            finalize_paragraph()
            finalize_table()
            continue
        
        # Handle Jira table rows (||header|| or |cell|)
        if line_stripped.startswith('||') or (line_stripped.startswith('|') and line_stripped.endswith('|')):
            finalize_paragraph()
            
            if not in_table:
                in_table = True
            
            # Parse table row
            if line_stripped.startswith('||'):
                # Header row
                cells = [cell.strip() for cell in line_stripped.split('||') if cell.strip()]
            else:
                # Data row
                cells = [cell.strip() for cell in line_stripped.split('|') if cell.strip()]
            
            table_rows.append(cells)
            continue
        
        # Not a table line - finalize any pending table
        finalize_table()
        
        # Handle headers (h3, h4)
        if line_stripped.startswith('h3.'):
            finalize_paragraph()
            adf["content"].append({
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": line_stripped[4:].strip()}]
            })
        elif line_stripped.startswith('h4.'):
            finalize_paragraph()
            adf["content"].append({
                "type": "heading",
                "attrs": {"level": 4},
                "content": [{"type": "text", "text": line_stripped[4:].strip()}]
            })
        # Handle bold text (*text*)
        elif line_stripped.startswith('*') and not line_stripped.startswith('**'):
            finalize_paragraph()
            # Remove leading asterisk
            text = line_stripped[1:].strip()
            adf["content"].append({
                "type": "paragraph",
                "content": parse_text_with_formatting(text)
            })
        else:
            current_paragraph.append(line_stripped)
    
    # Finalize any remaining content
    finalize_paragraph()
    finalize_table()
    
    # Add attachments section if available
    if uploaded_attachments and len(uploaded_attachments) > 0:
        # Add separator and heading
        adf["content"].append({
            "type": "rule"
        })
        
        adf["content"].append({
            "type": "heading",
            "attrs": {"level": 4},
            "content": [{"type": "text", "text": "� Test Artifacts"}]
        })
        
        # List all attachments
        for attachment in uploaded_attachments:
            filename = attachment.get('filename', 'attachment')
            description = attachment.get('description', 'Attachment')
            
            adf["content"].append({
                "type": "paragraph",
                "content": [{"type": "text", "text": f"� {description}: {filename}"}]
            })
    
    return adf

def validate_adf_structure(adf):
    """Validate basic ADF structure before sending to Jira"""
    try:
        if not isinstance(adf, dict):
            return False
        
        if adf.get('version') != 1 or adf.get('type') != 'doc':
            return False
        
        content = adf.get('content', [])
        if not isinstance(content, list):
            return False
        
        # Check each content block
        for block in content:
            if not isinstance(block, dict) or 'type' not in block:
                return False
            
            block_type = block.get('type')
            if block_type in ['paragraph', 'heading']:
                # These should have content array
                if 'content' not in block or not isinstance(block['content'], list):
                    return False
            elif block_type == 'table':
                # Tables should have content with rows
                if 'content' not in block or not isinstance(block['content'], list):
                    return False
            elif block_type == 'rule':
                # Rules are simple - no content validation needed
                pass
            elif block_type == 'mediaSingle':
                # Media blocks should have content with media
                if 'content' not in block or not isinstance(block['content'], list):
                    return False
        
        return True
    except Exception as e:
        logger.error(f"ADF validation error: {e}")
        return False

def create_simple_adf_comment(markdown_text, uploaded_attachments=None):
    """Create a simple, guaranteed-valid ADF comment as fallback"""
    adf = {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Playwright MCP Automation Results"}]
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Automation execution completed successfully."}]
            }
        ]
    }
    
    # Add basic results as text blocks
    lines = markdown_text.split('\n')
    current_text = []
    
    for line in lines[:20]:  # Limit to first 20 lines to avoid issues
        line = line.strip()
        if line and not line.startswith('|'):  # Skip table lines
            # Clean problematic characters
            clean_line = line.replace('\\', ' / ').replace('{{', '').replace('}}', '')
            current_text.append(clean_line)
            
            if len(current_text) >= 5:  # Group lines into paragraphs
                adf["content"].append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": " ".join(current_text)}]
                })
                current_text = []
    
    # Add any remaining text
    if current_text:
        adf["content"].append({
            "type": "paragraph",
            "content": [{"type": "text", "text": " ".join(current_text)}]
        })
    
    # Add attachment references if available
    if uploaded_attachments and len(uploaded_attachments) > 0:
        adf["content"].append({
            "type": "paragraph",
            "content": [{"type": "text", "text": "📎 Attachments:"}]
        })
        
        for attachment in uploaded_attachments:
            filename = attachment.get('filename', 'attachment')
            description = attachment.get('description', 'Attachment')
            adf["content"].append({
                "type": "paragraph",
                "content": [{"type": "text", "text": f"  • {description}: {filename}"}]
            })
    
    return adf

@app.route('/browseruse-automation-stepwise')
def browseruse_automation_stepwise():
    """Legacy route - redirect to main browseruse automation"""
    return render_template('browseruse-automation-stepwise.html', active_tab='browseruse')

@app.route('/pom-step-builder')
def pom_step_builder():
    return render_template('pom-step-builder-integrated.html', active_tab='pom-step-builder')

@app.route('/pom-builder')
@jira_auth_required
def pom_builder():
    """Integrated POM Builder - combines element extraction and POM generation"""
    return render_template('pom-builder.html', active_tab='pom-builder')

@app.route('/automation-studio-element-extractor')
@jira_auth_required
def element_extractor():
    """Original Element Extractor (legacy)"""
    return render_template('AutomationStudio-ElementExtractor.html', active_tab='element-extractor')

@app.route('/automation-studio-pom-generator')
@jira_auth_required
def pom_generator():
    """Original POM Generator (legacy)"""
    return render_template('AutomationStudio-pomgenerator.html', active_tab='pom-generator')

@app.route('/api/extract-elements', methods=['POST'])
def extract_elements():
    """Extract UI elements from uploaded screenshots or HTML files"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        # Get file extension
        filename = file.filename.lower()
        
        if filename.endswith(('.png', '.jpg', '.jpeg')):
            # For image files, return mock elements (in production, use OCR/CV)
            elements = [
                {'id': 1, 'type': 'button', 'text': 'Submit', 'selector': 'button[type="submit"]', 'x': 100, 'y': 200, 'width': 80, 'height': 32},
                {'id': 2, 'type': 'input', 'text': 'Email', 'selector': 'input[type="email"]', 'x': 50, 'y': 150, 'width': 200, 'height': 32},
                {'id': 3, 'type': 'input', 'text': 'Password', 'selector': 'input[type="password"]', 'x': 50, 'y': 190, 'width': 200, 'height': 32},
                {'id': 4, 'type': 'link', 'text': 'Sign Up', 'selector': 'a[href="/signup"]', 'x': 260, 'y': 250, 'width': 60, 'height': 20},
                {'id': 5, 'type': 'text', 'text': 'Welcome', 'selector': '.welcome-message', 'x': 50, 'y': 100, 'width': 200, 'height': 24}
            ]
        elif filename.endswith(('.html', '.htm')):
            # For HTML files, parse the content
            content = file.read().decode('utf-8')
            elements = parse_html_elements(content)
        else:
            return jsonify({'error': 'Unsupported file type. Please upload PNG, JPG, or HTML files.'}), 400
            
        return jsonify({
            'success': True,
            'elements': elements,
            'filename': file.filename
        })
        
    except Exception as e:
        logger.error(f"Error extracting elements: {str(e)}")
        return jsonify({'error': str(e)}), 500

def parse_html_elements(html_content):
    """Parse HTML content and extract UI elements"""
    from bs4 import BeautifulSoup
    import re
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        elements = []
        element_id = 1
        
        # Extract different types of elements
        element_types = [
            ('button', 'button'),
            ('input', 'input'),
            ('link', 'a'),
            ('text', 'h1, h2, h3, h4, h5, h6, p, span, div.text'),
            ('image', 'img'),
            ('select', 'select'),
            ('textarea', 'textarea')
        ]
        
        for elem_type, selector in element_types:
            found_elements = soup.select(selector)
            
            for elem in found_elements[:10]:  # Limit to 10 elements per type
                # Generate selector
                css_selector = generate_css_selector(elem)
                
                # Get text content
                text = elem.get_text(strip=True) if elem_type != 'image' else elem.get('alt', 'Image')
                if elem_type == 'input':
                    text = elem.get('placeholder') or elem.get('name') or elem.get('id') or f'{elem.get("type", "text")} input'
                elif elem_type == 'link':
                    text = text or elem.get('href', 'Link')
                elif elem_type == 'button':
                    text = text or 'Button'
                
                if text and len(text.strip()) > 0:
                    elements.append({
                        'id': element_id,
                        'type': elem_type,
                        'text': text[:50],  # Truncate long text
                        'selector': css_selector,
                        'x': 0,  # HTML parsing doesn't provide coordinates
                        'y': 0,
                        'width': 0,
                        'height': 0
                    })
                    element_id += 1
        
        return elements[:20]  # Return max 20 elements
        
    except ImportError:
        # If BeautifulSoup is not available, return mock elements
        logger.warning("BeautifulSoup not available, returning mock elements")
        return [
            {'id': 1, 'type': 'button', 'text': 'Submit Button', 'selector': 'button.submit', 'x': 0, 'y': 0, 'width': 0, 'height': 0},
            {'id': 2, 'type': 'input', 'text': 'Username Field', 'selector': 'input#username', 'x': 0, 'y': 0, 'width': 0, 'height': 0},
            {'id': 3, 'type': 'input', 'text': 'Password Field', 'selector': 'input#password', 'x': 0, 'y': 0, 'width': 0, 'height': 0}
        ]
    except Exception as e:
        logger.error(f"Error parsing HTML: {str(e)}")
        return []

def generate_css_selector(element):
    """Generate a CSS selector for a BeautifulSoup element"""
    try:
        # Try ID first
        if element.get('id'):
            return f"#{element['id']}"
        
        # Try class names
        if element.get('class'):
            classes = ' '.join(element['class'])
            return f"{element.name}.{classes.replace(' ', '.')}"
        
        # Try name attribute
        if element.get('name'):
            return f"{element.name}[name='{element['name']}']"
        
        # Try type for inputs
        if element.name == 'input' and element.get('type'):
            return f"input[type='{element['type']}']"
        
        # Try placeholder for inputs
        if element.name == 'input' and element.get('placeholder'):
            return f"input[placeholder='{element['placeholder']}']"
        
        # Try href for links
        if element.name == 'a' and element.get('href'):
            return f"a[href='{element['href']}']"
        
        # Fallback to tag name
        return element.name
        
    except Exception:
        return element.name if element.name else 'element'

@app.route('/api/pom/pages', methods=['POST'])
def get_pom_pages():
    data = request.json
    pom_path = data.get('path')
    
    if not pom_path or not os.path.exists(pom_path):
        return jsonify({'error': 'Invalid POM path'}), 400
    
    try:
        # Find all JavaScript files that might be page objects
        pages = []
        
        # If the path already ends with 'pages', use it directly
        if os.path.basename(pom_path) == 'pages':
            pages_dir = pom_path
        else:
            # Try different possible locations for page objects
            possible_paths = [
                os.path.join(pom_path, 'pages'),
                os.path.join(pom_path, 'features', 'pages')
            ]
            
            pages_dir = None
            for path in possible_paths:
                if os.path.exists(path):
                    pages_dir = path
                    break
            
            if not pages_dir:
                return jsonify({'error': 'Could not find pages directory'}), 404
        
        logger.info(f"Looking for page objects in: {pages_dir}")
        
        # Track page names to avoid duplicates
        added_pages = set()
        
        # Look for JS files in the pages directory
        if os.path.exists(pages_dir):
            for file in os.listdir(pages_dir):
                if file.endswith('.js') and file != 'BasePage.js':
                    page_name = file.replace('.js', '')
                    if page_name not in added_pages:
                        pages.append({
                            'name': page_name,
                            'path': os.path.join(pages_dir, file)
                        })
                        added_pages.add(page_name)
        
        # Also check for page objects in subdirectories
        for root, dirs, files in os.walk(pages_dir):
            # Skip the root directory as we already processed it above
            if root == pages_dir:
                continue
                
            for file in files:
                if file.endswith('.js') and file != 'BasePage.js':
                    page_name = file.replace('.js', '')
                    if page_name not in added_pages:
                        pages.append({
                            'name': page_name,
                            'path': os.path.join(root, file)
                        })
                        added_pages.add(page_name)
        
        return jsonify({'pages': pages})
    except Exception as e:
        logger.error(f"Error getting POM pages: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/elements', methods=['POST'])
def get_pom_elements():
    data = request.json
    pom_path = data.get('path')
    page_name = data.get('page')
    
    if not pom_path or not os.path.exists(pom_path) or not page_name:
        return jsonify({'error': 'Invalid POM path or page name'}), 400
    
    try:
        # Find the page file
        page_file = None
        
        # If the path already ends with 'pages', use it directly
        if os.path.basename(pom_path) == 'pages':
            pages_dir = pom_path
        else:
            # Try different possible locations for page objects
            possible_paths = [
                os.path.join(pom_path, 'pages'),
                os.path.join(pom_path, 'features', 'pages')
            ]
            
            pages_dir = None
            for path in possible_paths:
                if os.path.exists(path):
                    pages_dir = path
                    break
            
            if not pages_dir:
                return jsonify({'error': 'Could not find pages directory'}), 404
        
        logger.info(f"Looking for page {page_name} in: {pages_dir}")
        
        # Check direct file
        direct_file = os.path.join(pages_dir, f"{page_name}.js")
        if os.path.exists(direct_file):
            page_file = direct_file
        else:
            # Search in subdirectories
            for root, dirs, files in os.walk(pages_dir):
                for file in files:
                    if file == f"{page_name}.js":
                        page_file = os.path.join(root, file)
                        break
                if page_file:
                    break
        
        if not page_file:
            return jsonify({'error': f'Page file for {page_name} not found'}), 404
        
        # Import our simple POM parser
        from simple_pom_parser import get_page_elements
        
        # Parse the page file to extract elements
        logger.info(f"Parsing page file: {page_file}")
        elements = get_page_elements(page_file)
        
        return jsonify({'elements': elements})
    except Exception as e:
        logger.error(f"Error getting POM elements: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/functions', methods=['POST'])
def get_pom_functions():
    data = request.json
    pom_path = data.get('path')
    page_name = data.get('page')
    
    if not pom_path or not os.path.exists(pom_path) or not page_name:
        return jsonify({'error': 'Invalid POM path or page name'}), 400
    
    try:
        # Find the page file
        page_file = None
        
        # If the path already ends with 'pages', use it directly
        if os.path.basename(pom_path) == 'pages':
            pages_dir = pom_path
        else:
            # Try different possible locations for page objects
            possible_paths = [
                os.path.join(pom_path, 'pages'),
                os.path.join(pom_path, 'features', 'pages')
            ]
            
            pages_dir = None
            for path in possible_paths:
                if os.path.exists(path):
                    pages_dir = path
                    break
            
            if not pages_dir:
                return jsonify({'error': 'Could not find pages directory'}), 404
        
        logger.info(f"Looking for page {page_name} in: {pages_dir}")
        
        # Check direct file
        direct_file = os.path.join(pages_dir, f"{page_name}.js")
        if os.path.exists(direct_file):
            page_file = direct_file
        else:
            # Search in subdirectories
            for root, dirs, files in os.walk(pages_dir):
                for file in files:
                    if file == f"{page_name}.js":
                        page_file = os.path.join(root, file)
                        break
                if page_file:
                    break
        
        if not page_file:
            return jsonify({'error': f'Page file for {page_name} not found'}), 404
        
        # Import our simple POM parser
        from simple_pom_parser import get_page_functions
        
        # Parse the page file to extract functions
        logger.info(f"Parsing page file for functions: {page_file}")
        functions = get_page_functions(page_file)
        
        return jsonify({'functions': functions})
    except Exception as e:
        logger.error(f"Error getting POM functions: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/generate-steps', methods=['POST'])
@llm_rate_limit
def generate_ai_steps():
    data = request.json
    steps = data.get('steps')
    feature_name = data.get('feature_name')
    scenario_name = data.get('scenario_name')
    
    if not steps or not isinstance(steps, list):
        return jsonify({'error': 'Invalid steps data'}), 400
    
    try:
        # Create a prompt for the AI
        prompt = f"""Generate high-quality Cucumber step definitions in JavaScript for the following feature:

Feature: {feature_name}
  Scenario: {scenario_name}
"""
        
        # Add steps to the prompt
        for i, step in enumerate(steps):
            step_text = ""
            
            if step.get('action') == 'navigate':
                step_text = f"Given I navigate to {step.get('page')}"
            elif step.get('action') == 'click':
                step_text = f"When I click the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'fill':
                step_text = f"When I fill the {step.get('element')} with \"{step.get('value')}\" on {step.get('page')}"
            elif step.get('action') == 'select':
                step_text = f"When I select \"{step.get('value')}\" from the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'check':
                step_text = f"When I check the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'verify':
                step_text = f"Then I should see \"{step.get('value')}\" in the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'wait':
                step_text = f"When I wait for the {step.get('element')} on {step.get('page')}"
            else:
                step_text = f"When I {step.get('action')} the {step.get('element')} on {step.get('page')}"
            
            prompt += f"\n    {step_text}"
        
        prompt += "\n\nGenerate JavaScript step definitions that use the Page Object Model pattern. Include proper imports, hooks for setup, and well-structured step definitions with async/await. Make sure to handle element selectors properly and include error handling. The step definitions should be compatible with Cucumber.js and Playwright."
        
        # Use Google AI to generate step definitions
        try:
            google_api_key = os.environ.get('GOOGLE_API_KEY')
            google_api_model = os.environ.get('GOOGLE_API_MODEL', 'gemini-pro')
            
            if not google_api_key or not genai:
                # Fall back to basic step definitions if no API key or module
                return generate_basic_step_definitions(steps, feature_name, scenario_name)
            
            # Configure the API
            genai.configure(api_key=google_api_key)
            
            # Set up the model
            model = genai.GenerativeModel(google_api_model)
            
            # Generate content
            system_instruction = "You are an expert test automation engineer specializing in Cucumber.js, Playwright, and Page Object Model pattern."
            
            response = model.generate_content(
                [
                    system_instruction,
                    prompt
                ],
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 2048,
                }
            )
            
            # Extract the generated step definitions
            step_definitions = response.text
            
            # Clean up the response if needed
            if '```javascript' in step_definitions:
                step_definitions = step_definitions.split('```javascript')[1].split('```')[0].strip()
            elif '```js' in step_definitions:
                step_definitions = step_definitions.split('```js')[1].split('```')[0].strip()
            
            return jsonify({
                'step_definitions': step_definitions,
                'ai_generated': True
            })
            
        except Exception as e:
            logger.error(f"Error generating AI step definitions: {str(e)}")
            # Fall back to basic step definitions
            return generate_basic_step_definitions(steps, feature_name, scenario_name)
            
    except Exception as e:
        logger.error(f"Error in generate_ai_steps: {str(e)}")
        return jsonify({'error': str(e)}), 500

def generate_basic_step_definitions(steps, feature_name, scenario_name):
    """Generate basic step definitions without AI"""
    try:
        # Create basic step definitions
        step_defs = "const { Given, When, Then } = require('@cucumber/cucumber');\n\n"
        
        # Add page imports
        unique_pages = set()
        for step in steps:
            if 'page' in step:
                unique_pages.add(step['page'])
        
        for page in unique_pages:
            step_defs += f"const {page} = require('../pages/{page}');\n"
        
        step_defs += "\n// Page objects initialization\nlet pageObjects = {};\n\n"
        step_defs += "// Before hook to initialize page objects\nBefore(async function() {\n"
        step_defs += "  const { page } = this;\n"
        
        for page in unique_pages:
            step_defs += f"  pageObjects.{page} = new {page}(page);\n"
        
        step_defs += "});\n\n"
        
        # Generate step definitions
        step_patterns = set()
        
        for step in steps:
            action = step.get('action', '')
            element = step.get('element', '')
            page = step.get('page', '')
            value = step.get('value', '')
            
            if action == 'navigate':
                pattern = "I navigate to (.*)"
                impl = "async function(page) {\n  await pageObjects[page].navigate();\n}"
                prefix = "Given"
            elif action == 'click':
                pattern = "I click the (.*) on (.*)"
                impl = f"async function(element, page) {{\n  await pageObjects[page].click('{element}');\n}}"
                prefix = "When"
            elif action == 'fill':
                pattern = "I fill the (.*) with \"(.*)\" on (.*)"
                impl = f"async function(element, value, page) {{\n  await pageObjects[page].fill('{element}', value);\n}}"
                prefix = "When"
            elif action == 'select':
                pattern = "I select \"(.*)\" from the (.*) on (.*)"
                impl = f"async function(value, element, page) {{\n  await pageObjects[page].selectOption('{element}', value);\n}}"
                prefix = "When"
            elif action == 'check':
                pattern = "I check the (.*) on (.*)"
                impl = f"async function(element, page) {{\n  await pageObjects[page].check('{element}');\n}}"
                prefix = "When"
            elif action == 'verify':
                pattern = "I should see \"(.*)\" in the (.*) on (.*)"
                impl = f"async function(text, element, page) {{\n  const actualText = await pageObjects[page].getText('{element}');\n  expect(actualText).to.include(text);\n}}"
                prefix = "Then"
            elif action == 'wait':
                pattern = "I wait for the (.*) on (.*)"
                impl = f"async function(element, page) {{\n  await pageObjects[page].waitForElement('{element}');\n}}"
                prefix = "When"
            else:
                pattern = f"I {action} the (.*) on (.*)"
                impl = "async function(element, page) {\n  // Implement custom action\n}"
                prefix = "When"
            
            step_def = f"{prefix}(/^{pattern}$/, {impl});"
            step_patterns.add(step_def)
        
        for step_def in step_patterns:
            step_defs += step_def + "\n\n"
        
        return jsonify({
            'step_definitions': step_defs,
            'ai_generated': False
        })
        
    except Exception as e:
        logger.error(f"Error generating basic step definitions: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/save', methods=['POST'])
def save_pom_file():
    data = request.json
    pom_path = data.get('path')
    filename = data.get('filename')
    content = data.get('content')
    file_type = data.get('type')  # 'feature' or 'steps'
    
    if not all([pom_path, filename, content, file_type]):
        return jsonify({'error': 'Missing required parameters'}), 400
    
    try:
        # Handle path that might already include 'features'
        if 'features' in pom_path:
            # Extract the base path (remove everything from 'features' onwards)
            base_path = pom_path.split('features')[0].rstrip('\\')
        else:
            base_path = pom_path
            
        logger.info(f"Base path for saving files: {base_path}")
        
        # Determine the target directory based on file type
        if file_type == 'feature':
            target_dir = os.path.join(base_path, 'features')
        else:  # steps
            target_dir = os.path.join(base_path, 'features', 'step_definitions')
        
        logger.info(f"Saving {file_type} file to: {target_dir}")
        
        # Create directory if it doesn't exist
        os.makedirs(target_dir, exist_ok=True)
        
        # Write the file
        file_path = os.path.join(target_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({'success': True, 'path': file_path})
    except Exception as e:
        logger.error(f"Error saving POM file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/extract-text', methods=['POST'])
def extract_text_from_document():
    """Extract text from uploaded documents (PDF, Word, etc)"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
        
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
        
    try:
        # Create a temporary file to save the uploaded document
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp:
            file.save(temp.name)
            temp_path = temp.name
        
        extracted_text = ''
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext == '.pdf':
            # Use PyPDF2 to extract text from PDF
            try:
                import PyPDF2
                with open(temp_path, 'rb') as pdf_file:
                    pdf_reader = PyPDF2.PdfReader(pdf_file)
                    for page_num in range(len(pdf_reader.pages)):
                        page = pdf_reader.pages[page_num]
                        extracted_text += page.extract_text() + '\n'
            except ImportError:
                return jsonify({'error': 'PDF extraction library not available'}), 500
                
        elif file_ext in ['.doc', '.docx']:
            # Use python-docx to extract text from Word documents
            try:
                import docx
                doc = docx.Document(temp_path)
                extracted_text = '\n'.join([para.text for para in doc.paragraphs])
            except ImportError:
                return jsonify({'error': 'Word document extraction library not available'}), 500
                
        else:
            # For other file types, try to read as text
            try:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    extracted_text = f.read()
            except UnicodeDecodeError:
                return jsonify({'error': 'Unsupported file format'}), 400
        
        # Clean up the temporary file
        try:
            os.unlink(temp_path)
        except:
            pass
            
        return jsonify({
            'text': extracted_text,
            'filename': file.filename
        })
        
    except Exception as e:
        logger.error(f"Error extracting text from document: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/browseruse/navigation', methods=['POST'])
@llm_rate_limit
def browseruse_navigation_executor():
    """Enhanced browser automation endpoint with comprehensive action support"""
    logger.info("Browser automation endpoint called")
    
    try:
        if not playwright_available:
            logger.error("Playwright is not installed. Cannot run browser automation.")
            return jsonify({
                'success': False,
                'error': 'Playwright is not installed. Please install it with: pip install playwright && playwright install',
                'report': {
                    'message': 'Browser automation is not available. Playwright is not installed.'
                }
            }), 500
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        prompt = data.get('prompt')
        steps = data.get('steps')
        capture_screenshot = data.get('captureScreenshotOnFailure', True)
        
        logger.info(f"Running browser automation with {len(steps) if steps else 0} steps")
        
        if not steps:
            return jsonify({'success': False, 'error': 'No steps provided'}), 400
        
        results = []
        failure_screenshot = None
        success = True
        page = None
        browser = None
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage']
                )
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 720},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                page = context.new_page()
                
                # Set default timeouts
                page.set_default_timeout(30000)  # 30 seconds
                
                for i, step in enumerate(steps):
                    action = step.get('action')
                    step_num = i + 1
                    logger.info(f"Executing step {step_num}/{len(steps)}: {action}")
                    
                    try:
                        if action == 'navigate':
                            url = step.get('url')
                            if not url:
                                raise ValueError("URL is required for navigate action")
                            if not url.startswith(('http://', 'https://')):
                                url = 'https://' + url
                            page.goto(url, wait_until='networkidle', timeout=30000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'url': url})
                        
                        elif action == 'click':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for click action")
                            page.click(selector, timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector})
                        
                        elif action == 'double_click':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for double_click action")
                            page.dblclick(selector, timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector})
                        
                        elif action == 'right_click':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for right_click action")
                            page.click(selector, button='right', timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector})
                        
                        elif action == 'hover':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for hover action")
                            page.hover(selector, timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector})
                        
                        elif action == 'fill':
                            selector = step.get('selector')
                            value = step.get('value')
                            if not selector or value is None:
                                raise ValueError("Selector and value are required for fill action")
                            page.fill(selector, str(value), timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector, 'value': value})
                        
                        elif action == 'select':
                            selector = step.get('selector')
                            value = step.get('value')
                            if not selector or value is None:
                                raise ValueError("Selector and value are required for select action")
                            page.select_option(selector, value, timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector, 'value': value})
                        
                        elif action == 'check':
                            selector = step.get('selector')
                            value = step.get('value', 'check').lower()
                            if not selector:
                                raise ValueError("Selector is required for check action")
                            if value == 'check':
                                page.check(selector, timeout=10000)
                            else:
                                page.uncheck(selector, timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector, 'checked': value == 'check'})
                        
                        elif action == 'wait_for_element':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for wait_for_element action")
                            page.wait_for_selector(selector, timeout=30000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector})
                        
                        elif action == 'wait_for_navigation':
                            page.wait_for_load_state('networkidle', timeout=30000)
                            results.append({'step': step_num, 'action': action, 'success': True})
                        
                        elif action == 'wait_for_url':
                            url = step.get('url')
                            if not url:
                                raise ValueError("URL is required for wait_for_url action")
                            page.wait_for_url(url, timeout=30000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'url': url})
                        
                        elif action == 'wait_for_timeout':
                            timeout = step.get('timeout', 1000)
                            try:
                                timeout = int(timeout)
                            except ValueError:
                                timeout = 1000
                            page.wait_for_timeout(timeout)
                            results.append({'step': step_num, 'action': action, 'success': True, 'timeout': timeout})
                        
                        elif action == 'scroll':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for scroll action")
                            element = page.locator(selector).first
                            element.scroll_into_view_if_needed(timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector})
                        
                        elif action == 'extract_text':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for extract_text action")
                            text = page.text_content(selector, timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector, 'extracted_text': text})
                        
                        elif action == 'extract_attribute':
                            selector = step.get('selector')
                            attribute = step.get('attribute')
                            if not selector or not attribute:
                                raise ValueError("Selector and attribute are required for extract_attribute action")
                            value = page.get_attribute(selector, attribute, timeout=10000)
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector, 'attribute': attribute, 'value': value})
                        
                        elif action == 'screenshot':
                            screenshot = page.screenshot(full_page=True)
                            screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                            results.append({
                                'step': step_num, 
                                'action': action, 
                                'success': True,
                                'screenshot': f"data:image/png;base64,{screenshot_base64}"
                            })
                        
                        elif action == 'page_html':
                            html = page.content()
                            results.append({'step': step_num, 'action': action, 'success': True, 'html': html[:1000] + '...' if len(html) > 1000 else html})
                        
                        elif action == 'assert_visible':
                            selector = step.get('selector')
                            if not selector:
                                raise ValueError("Selector is required for assert_visible action")
                            element = page.locator(selector).first
                            if not element.is_visible(timeout=10000):
                                raise ValueError(f"Element {selector} is not visible")
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector})
                        
                        elif action == 'assert_text':
                            selector = step.get('selector')
                            text = step.get('text')
                            if not selector or not text:
                                raise ValueError("Selector and text are required for assert_text action")
                            element_text = page.text_content(selector, timeout=10000)
                            if text not in element_text:
                                raise ValueError(f"Text '{text}' not found in element {selector}")
                            results.append({'step': step_num, 'action': action, 'success': True, 'selector': selector, 'expected_text': text})
                        
                        elif action == 'assert_title':
                            title = step.get('title')
                            if not title:
                                raise ValueError("Title is required for assert_title action")
                            page_title = page.title()
                            if title not in page_title:
                                raise ValueError(f"Title '{title}' not found in page title '{page_title}'")
                            results.append({'step': step_num, 'action': action, 'success': True, 'expected_title': title, 'actual_title': page_title})
                        
                        elif action == 'assert_url':
                            url = step.get('url')
                            if not url:
                                raise ValueError("URL is required for assert_url action")
                            current_url = page.url
                            if url not in current_url:
                                raise ValueError(f"URL '{url}' not found in current URL '{current_url}'")
                            results.append({'step': step_num, 'action': action, 'success': True, 'expected_url': url, 'actual_url': current_url})
                        
                        elif action == 'js':
                            script = step.get('script')
                            if not script:
                                raise ValueError("Script is required for js action")
                            result = page.evaluate(script)
                            results.append({'step': step_num, 'action': action, 'success': True, 'script': script, 'result': str(result)})
                        
                        elif action == 'custom':
                            instruction = step.get('instruction', '')
                            results.append({'step': step_num, 'action': action, 'success': True, 'instruction': instruction, 'note': 'Custom instructions are logged but not executed'})
                        
                        else:
                            logger.warning(f"Unsupported action: {action}")
                            results.append({'step': step_num, 'action': action, 'success': False, 'error': f'Unsupported action: {action}'})
                    
                    except Exception as step_error:
                        logger.error(f"Error in step {step_num} ({action}): {str(step_error)}")
                        results.append({
                            'step': step_num, 
                            'action': action, 
                            'success': False,
                            'error': str(step_error)
                        })
                        # Don't break on step errors, continue with remaining steps
                
                if browser:
                    browser.close()
        
        except Exception as e:
            logger.error(f"Error during browser automation: {str(e)}")
            success = False
            if capture_screenshot and page:
                try:
                    screenshot = page.screenshot()
                    failure_screenshot = f"data:image/png;base64,{base64.b64encode(screenshot).decode('utf-8')}"
                except Exception as screenshot_error:
                    logger.error(f"Failed to capture failure screenshot: {str(screenshot_error)}")
            
            if browser:
                browser.close()
            
            # Add the error to results if not already added
            if not results or results[-1].get('success', True):
                results.append({
                    'step': len(results) + 1, 
                    'action': 'error', 
                    'success': False,
                    'error': str(e)
                })
        
        # Calculate success based on individual step results
        successful_steps = sum(1 for result in results if result.get('success', False))
        total_steps = len(results)
        overall_success = successful_steps == total_steps and total_steps > 0
        
        # Prepare response
        report = {
            'steps_executed': total_steps,
            'steps_successful': successful_steps,
            'total_steps': len(steps),
            'success': overall_success,
            'message': f'Automation completed: {successful_steps}/{total_steps} steps successful' if total_steps > 0 else 'No steps executed'
        }
        
        if failure_screenshot:
            report['failureScreenshot'] = failure_screenshot
        
        return jsonify({
            'success': overall_success,
            'steps': results,
            'report': report,
            'rawOutput': f"ActionResult(is_done=True, success={overall_success})\n{prompt or 'Browser automation'}\n{successful_steps}/{total_steps} steps successful."
        })
        
    except Exception as unexpected_error:
        logger.error(f"Unexpected error in browser automation endpoint: {str(unexpected_error)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred',
            'report': {
                'message': 'Browser automation failed due to an unexpected error. Please check server logs.'
            }
        }), 500

@app.route('/api/llm-usage', methods=['GET'])
def check_llm_usage():
    """Check current LLM usage for the user"""
    try:
        user_id = get_user_identifier()
        current_usage, limit = get_user_llm_usage()
        remaining = max(0, limit - current_usage)
        
        user_info = get_user_display_info()
        return jsonify({
            'user': user_info,
            'usage': {
                'used': current_usage,
                'limit': limit,
                'remaining': remaining,
                'percentage': (current_usage / limit) * 100 if limit > 0 else 0
            },
            'reset_time': 'Next day at 00:00 UTC',
            'date': datetime.now().strftime('%Y-%m-%d')
        })
    except Exception as e:
        logger.error(f"Error checking LLM usage: {str(e)}")
        return jsonify({'error': 'Failed to check LLM usage'}), 500

@app.route('/api/llm-usage/reset', methods=['POST'])
def reset_llm_usage():
    """Reset LLM usage for the current user (admin only in production)"""
    try:
        # Only allow reset in development mode for now
        if FLASK_ENV != 'development':
            return jsonify({'error': 'Usage reset is only available in development mode'}), 403
        
        user_id = get_user_identifier()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Reset the user's usage
        user_llm_usage[user_id] = {'count': 0, 'date': today}
        
        logger.info(f"LLM usage reset for user {user_id}")
        user_info = get_user_display_info()
        return jsonify({
            'message': 'LLM usage has been reset successfully',
            'user': user_info,
            'usage': {
                'new_usage': 0,
                'limit': DAILY_LLM_LIMIT,
                'remaining': DAILY_LLM_LIMIT
            },
            'reset_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
        })
    except Exception as e:
        logger.error(f"Error resetting LLM usage: {str(e)}")
        return jsonify({'error': 'Failed to reset LLM usage'}), 500

@app.route('/api/llm-usage/user/<user_id>', methods=['GET'])
def check_llm_usage_for_user(user_id):
    """Check LLM usage for a specific user ID"""
    try:
        # Validate user_id parameter
        if not user_id or len(user_id.strip()) == 0:
            return jsonify({'error': 'User ID is required'}), 400
        
        user_id = user_id.strip()
        today = datetime.now().strftime('%Y-%m-%d')
        user_data = user_llm_usage.get(user_id, {'count': 0, 'date': None})
        
        # Reset count if it's a new day for this user
        if user_data['date'] != today:
            user_data = {'count': 0, 'date': today}
            user_llm_usage[user_id] = user_data
        
        current_usage = user_data['count']
        limit = DAILY_LLM_LIMIT
        remaining = max(0, limit - current_usage)
        
        return jsonify({
            'target_user': {
                'user_id': user_id,
                'display_name': f'User: {user_id}',
                'query_type': 'specific_user'
            },
            'usage': {
                'used': current_usage,
                'limit': limit,
                'remaining': remaining,
                'percentage': (current_usage / limit) * 100 if limit > 0 else 0
            },
            'reset_time': 'Next day at 00:00 UTC',
            'date': today,
            'status': 'within_limit' if remaining > 0 else 'limit_exceeded'
        })
    except Exception as e:
        logger.error(f"Error checking LLM usage for user {user_id}: {str(e)}")
        return jsonify({'error': 'Failed to check LLM usage for user'}), 500

@app.route('/api/llm-usage/reset/<user_id>', methods=['POST'])
def reset_llm_usage_for_user(user_id):
    """Reset LLM usage for a specific user ID (development mode only)"""
    try:
        # Check if feature is enabled (development mode only)
        if FLASK_ENV != 'development':
            return jsonify({'error': 'Reset user usage feature is only available in development mode.'}), 403
        
        # Validate user_id parameter
        if not user_id or len(user_id.strip()) == 0:
            return jsonify({'error': 'User ID is required'}), 400
        
        user_id = user_id.strip()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Reset the user's usage
        user_llm_usage[user_id] = {'count': 0, 'date': today}
        
        logger.info(f"LLM usage reset for user {user_id} by admin")
        return jsonify({
            'message': f'LLM usage has been reset successfully for user: {user_id}',
            'target_user': {
                'user_id': user_id,
                'display_name': f'User: {user_id}',
                'reset_by': 'administrator'
            },
            'usage': {
                'new_usage': 0,
                'limit': DAILY_LLM_LIMIT,
                'remaining': DAILY_LLM_LIMIT
            },
            'reset_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'environment': FLASK_ENV
        })
    except Exception as e:
        logger.error(f"Error resetting LLM usage for user {user_id}: {str(e)}")
        return jsonify({'error': 'Failed to reset LLM usage for user'}), 500

# =============================================================================
# BUG BUILDER ROUTES
# =============================================================================

# Bug Builder Models
class BugSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    video_path = db.Column(db.String(500))
    annotations = db.Column(db.Text)  # JSON string
    action_logs = db.Column(db.Text)  # JSON string
    bug_report = db.Column(db.Text)  # JSON string
    jira_issue_key = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='recording')  # recording, processing, completed
    playwright_script_path = db.Column(db.String(500))
    playwright_trace_path = db.Column(db.String(500))
    playwright_video_path = db.Column(db.String(500))
    playwright_status = db.Column(db.String(20))  # pending, running, success, failed
    playwright_error = db.Column(db.Text)

def _get_playwright_output_root() -> str:
    root = current_app.config.get('PLAYWRIGHT_OUTPUT_DIR', 'playwright-output')
    if not os.path.isabs(root):
        root = os.path.join(current_app.root_path, root)
    os.makedirs(root, exist_ok=True)
    return root


def _playwright_worker(app, session_id: str):
    with app.app_context():
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return

        session.playwright_status = 'running'
        session.playwright_error = None
        db.session.commit()

        try:
            actions = json.loads(session.action_logs or '[]')
        except Exception as parse_exc:
            actions = []
            session.playwright_status = 'failed'
            session.playwright_error = f'Failed to parse action logs: {parse_exc}'
            db.session.commit()
            return

        if not actions:
            session.playwright_status = 'failed'
            session.playwright_error = 'No action logs available for replay.'
            db.session.commit()
            return

        output_root = _get_playwright_output_root()
        artifacts = ensure_replay_directories(output_root, session_id)

        try:
            script_text = generate_script_text(actions, artifacts)
            save_script(script_text, artifacts.script_path)
        except Exception as script_error:
            session.playwright_status = 'failed'
            session.playwright_error = f'Failed to generate Playwright script: {script_error}'
            db.session.commit()
            return

        replay_result = run_replay(actions, artifacts)

        script_rel = os.path.relpath(artifacts.script_path, current_app.root_path)
        trace_rel = os.path.relpath(artifacts.trace_path, current_app.root_path)
        video_path = replay_result.get('video_path') or artifacts.video_path
        video_rel = os.path.relpath(video_path, current_app.root_path) if video_path else None

        session.playwright_script_path = script_rel
        session.playwright_trace_path = trace_rel
        session.playwright_video_path = video_rel

        if replay_result.get('status') == 'success':
            session.playwright_status = 'success'
            warnings = replay_result.get('warnings')
            if warnings:
                session.playwright_error = json.dumps({'warnings': warnings})
            else:
                session.playwright_error = None
        else:
            session.playwright_status = 'failed'
            error_msg = replay_result.get('error') or 'Unknown Playwright error.'
            session.playwright_error = error_msg

        db.session.commit()


def trigger_playwright_replay(session: BugSession):
    if sync_playwright is None:
        session.playwright_status = 'failed'
        session.playwright_error = 'Playwright is not installed on the server.'
        db.session.commit()
        return

    session.playwright_status = 'pending'
    session.playwright_error = None
    db.session.commit()

    app_obj = current_app._get_current_object()
    worker = Thread(target=_playwright_worker, args=(app_obj, session.session_id), daemon=True)
    worker.start()

# Bulk Test Generator Models
class JQLSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    jql_query = db.Column(db.Text, nullable=False)
    jira_project_url = db.Column(db.String(500))
    total_stories = db.Column(db.Integer, default=0)
    processed_stories = db.Column(db.Integer, default=0)
    failed_stories = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='created')  # created, fetching, generating, completed, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    # Relationship to stories
    stories = db.relationship('JQLStory', backref='session', lazy=True, cascade='all, delete-orphan')

class JQLStory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('jql_session.id'), nullable=False)
    jira_key = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    story_type = db.Column(db.String(50))  # Story, Bug, Task, etc.
    priority = db.Column(db.String(20))
    status = db.Column(db.String(50))
    assignee = db.Column(db.String(100))
    labels = db.Column(db.Text)  # JSON array
    components = db.Column(db.Text)  # JSON array
    acceptance_criteria = db.Column(db.Text)
    test_generation_status = db.Column(db.String(20), default='pending')  # pending, generating, completed, failed
    test_cases = db.Column(db.Text)  # JSON array of test cases
    generation_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    generated_at = db.Column(db.DateTime)

@app.route('/bug-builder')
@jira_auth_required
def bug_builder():
    """Bug Builder main page - Simple version"""
    return render_template('bug-builder-simple.html', active_tab='bug-builder')

@app.route('/bug-builder-old')
@jira_auth_required
def bug_builder_old():
    """Bug Builder old version"""
    return render_template('bug-builder.html', active_tab='bug-builder')

@app.route('/api/bug-builder/start-session', methods=['POST'])
@jira_auth_required
def start_bug_session():
    """Initialize a new bug recording session"""
    try:
        data = request.get_json()
        user_id = get_user_identifier()
        
        # Generate unique session ID
        import uuid
        session_id = str(uuid.uuid4())
        
        # Create new session
        session = BugSession(
            user_id=user_id,
            session_id=session_id,
            status='recording'
        )
        db.session.add(session)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        logger.error(f"Error starting bug session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bug-builder/start-playwright-recording', methods=['POST'])
@jira_auth_required
def start_playwright_recording():
    """Start Playwright recorder with video recording"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL required'}), 400
        
        import uuid
        import subprocess
        import os
        from threading import Thread
        
        session_id = str(uuid.uuid4())
        user_id = get_user_identifier()
        
        # Create session
        session = BugSession(
            user_id=user_id,
            session_id=session_id,
            status='recording'
        )
        
        # Create output directory
        output_dir = os.path.join('playwright-output', 'bug-builder', session_id)
        os.makedirs(output_dir, exist_ok=True)
        script_path = os.path.join(output_dir, 'recording.py')
        video_dir = os.path.join(output_dir, 'videos')
        os.makedirs(video_dir, exist_ok=True)
        
        session.playwright_script_path = script_path
        session.playwright_status = 'recording'
        session.video_path = video_dir  # Store video directory path
        
        db.session.add(session)
        db.session.commit()
        
        # Custom recorder with optional video recording via button
        def run_playwright_with_video():
            try:
                logger.info(f"Starting Playwright with optional video recording for session {session_id}")
                
                # Use simple Playwright codegen for step recording
                logger.info("Starting Playwright codegen for step recording...")
                
                # Run Playwright codegen
                cmd_codegen = [
                    sys.executable, '-m', 'playwright',
                    'codegen',
                    url,
                    '--target=python',
                    f'--output={script_path}'
                ]
                
                process = subprocess.Popen(
                    cmd_codegen,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=os.getcwd()
                )
                
                # Wait for user to close the browser
                stdout, _ = process.communicate()
                
                if stdout:
                    logger.info(f"Codegen output: {stdout.decode('utf-8', errors='ignore')}")
                
                logger.info(f"Playwright recording completed for session {session_id}")
                
                # Update session status
                with app.app_context():
                    sess = BugSession.query.filter_by(session_id=session_id).first()
                    if sess:
                        sess.playwright_status = 'completed'
                        sess.status = 'completed'
                        
                        # Find the generated video file
                        if os.path.exists(video_dir):
                            video_files = [f for f in os.listdir(video_dir) if f.endswith('.webm')]
                            if video_files:
                                sess.video_path = os.path.join(video_dir, video_files[0])
                                logger.info(f"Video saved at: {sess.video_path}")
                            else:
                                logger.warning("No video file found in video directory")
                                sess.video_path = None
                        else:
                            logger.warning("Video directory does not exist")
                            sess.video_path = None
                        
                        db.session.commit()
                        logger.info(f"Session {session_id} marked as completed")
                        
            except Exception as e:
                logger.error(f"Error in Playwright recording: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                with app.app_context():
                    sess = BugSession.query.filter_by(session_id=session_id).first()
                    if sess:
                        sess.playwright_status = 'failed'
                        sess.playwright_error = str(e)
                        db.session.commit()
        
        thread = Thread(target=run_playwright_with_video)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': 'Playwright recorder starting with video recording...'
        })
        
    except Exception as e:
        logger.error(f"Error starting Playwright recording: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bug-builder/get-playwright-recording/<session_id>', methods=['GET'])
@jira_auth_required
def get_playwright_recording(session_id):
    """Get the recorded Playwright script, video, and extract steps"""
    try:
        session = BugSession.query.filter_by(session_id=session_id).first()
        
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Check status
        if session.playwright_status == 'recording':
            return jsonify({
                'success': True,
                'status': 'recording',
                'playwright_status': 'recording',
                'message': 'Recording in progress...'
            })
        
        if session.playwright_status == 'failed':
            return jsonify({
                'success': False,
                'status': 'failed',
                'error': session.playwright_error or 'Recording failed'
            })
        
        # Read the actions and generate steps
        steps = []
        script_content = ''
        video_url = None
        
        # First try to read from actions.json (our new format)
        output_dir = os.path.dirname(session.playwright_script_path) if session.playwright_script_path else None
        actions_file = os.path.join(output_dir, 'actions.json') if output_dir else None
        
        if actions_file and os.path.exists(actions_file):
            try:
                with open(actions_file, 'r') as f:
                    actions_data = json.load(f)
                
                logger.info(f"Found {len(actions_data)} actions in JSON file")
                
                # Convert actions to readable steps
                for i, action in enumerate(actions_data):
                    action_type = action.get('type', '')
                    selector = action.get('selector', '')
                    value = action.get('value', '')
                    
                    if action_type == 'navigate':
                        if selector.startswith('http'):
                            steps.append(f"Navigate to {selector}")
                        else:
                            steps.append(f"Navigate to {selector}")
                    elif action_type == 'click':
                        if value:  # Text content
                            steps.append(f"Click on '{value}'")
                        elif selector:
                            # Clean up selector for readability
                            clean_selector = selector.replace('#', '').replace('.', ' ')
                            steps.append(f"Click on {clean_selector}")
                        else:
                            steps.append("Click on element")
                    elif action_type == 'input':
                        if value:  # Placeholder text
                            steps.append(f"Enter text in field ({value})")
                        elif selector:
                            clean_selector = selector.replace('#', '').replace('.', ' ')
                            steps.append(f"Enter text in {clean_selector}")
                        else:
                            steps.append("Enter text in field")
                    else:
                        steps.append(f"Perform action: {action_type}")
                
            except Exception as e:
                logger.warning(f"Could not read actions.json: {e}")
        
        # Fallback to Playwright script parsing if no actions.json or no steps
        if not steps and session.playwright_script_path and os.path.exists(session.playwright_script_path):
            try:
                logger.info(f"Reading Playwright script from: {session.playwright_script_path}")
                with open(session.playwright_script_path, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                logger.info(f"Script content preview: {script_content[:500]}")
                
                # Parse steps from Playwright script with better extraction
                logger.info(f"Parsing Playwright script, length: {len(script_content)}")
                lines = script_content.split('\n')
                
                for line in lines:
                    line = line.strip()
                    
                    # Skip empty lines, comments, imports and setup
                    if not line or line.startswith('#'):
                        continue
                    if any(skip in line for skip in ['import ', 'from ', 'def ', 'with sync_playwright', 'browser =', 'context =', 'page = ', 'browser.close', 'context.close']):
                        continue
                    
                    # Extract goto
                    if 'page.goto(' in line or '.goto(' in line:
                        try:
                            if '"' in line:
                                url = line.split('"')[1]
                            elif "'" in line:
                                url = line.split("'")[1]
                            else:
                                url = 'the application'
                            steps.append(f"Navigate to {url}")
                        except:
                            steps.append("Navigate to the application")
                    
                    # Extract get_by_role clicks
                    elif 'get_by_role(' in line and 'click()' in line:
                        try:
                            # Extract role and name
                            if 'name=' in line:
                                name_part = line.split('name=')[1]
                                if '"' in name_part:
                                    name = name_part.split('"')[1]
                                elif "'" in name_part:
                                    name = name_part.split("'")[1]
                                else:
                                    name = 'element'
                                steps.append(f"Click on '{name}'")
                            else:
                                steps.append("Click on element")
                        except:
                            steps.append("Click on element")
                    
                    # Extract get_by_text clicks
                    elif 'get_by_text(' in line and 'click()' in line:
                        try:
                            if '"' in line:
                                text = line.split('"')[1]
                            elif "'" in line:
                                text = line.split("'")[1]
                            else:
                                text = 'element'
                            steps.append(f"Click on text '{text}'")
                        except:
                            steps.append("Click on element")
                    
                    # Extract regular clicks
                    elif 'page.click(' in line or '.click(' in line:
                        try:
                            if '"' in line:
                                selector = line.split('"')[1]
                            elif "'" in line:
                                selector = line.split("'")[1]
                            else:
                                selector = 'element'
                            # Simplify selector
                            if selector.startswith('#'):
                                selector = selector[1:]
                            steps.append(f"Click on {selector}")
                        except:
                            steps.append("Click on element")
                    
                    # Extract fill/type actions
                    elif 'page.fill(' in line or '.fill(' in line or 'page.type(' in line or '.type(' in line:
                        try:
                            parts = line.split('"') if '"' in line else line.split("'")
                            if len(parts) >= 2:
                                selector = parts[1]
                                if selector.startswith('#'):
                                    selector = selector[1:]
                                steps.append(f"Enter text in {selector}")
                        except:
                            steps.append("Enter text in field")
                    
                    # Extract press/keyboard actions
                    elif 'page.press(' in line or '.press(' in line:
                        try:
                            if '"' in line:
                                key = line.split('"')[-2]
                            elif "'" in line:
                                key = line.split("'")[-2]
                            else:
                                key = 'key'
                            steps.append(f"Press {key}")
                        except:
                            steps.append("Press key")
                
                logger.info(f"Extracted {len(steps)} steps from script")
                
            except Exception as e:
                logger.warning(f"Could not read Playwright script: {e}")
                import traceback
                logger.warning(traceback.format_exc())
        
        # If still no steps, provide a helpful message
        if not steps:
            logger.warning(f"No steps extracted for session {session_id}")
            steps = ["Recording completed but no actions were captured. Please try recording again and perform clear actions like clicks and typing."]
        
        # Check for video file
        if session.video_path:
            if os.path.isdir(session.video_path):
                # It's a directory, find the video file
                video_files = [f for f in os.listdir(session.video_path) if f.endswith('.webm')]
                if video_files:
                    video_url = f"/api/bug-builder/video/{session_id}/{video_files[0]}"
            elif os.path.isfile(session.video_path):
                # It's a file
                video_filename = os.path.basename(session.video_path)
                video_url = f"/api/bug-builder/video/{session_id}/{video_filename}"
        
        return jsonify({
            'success': True,
            'status': 'completed',
            'steps': steps,
            'script': script_content,
            'video_url': video_url
        })
            
    except Exception as e:
        logger.error(f"Error getting Playwright recording: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bug-builder/video/<session_id>/<filename>', methods=['GET'])
@jira_auth_required
def get_bug_builder_video(session_id, filename):
    """Serve the recorded video file"""
    try:
        session = BugSession.query.filter_by(session_id=session_id).first()
        
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Construct video path
        if os.path.isdir(session.video_path):
            video_path = os.path.join(session.video_path, filename)
        else:
            video_path = session.video_path
        
        if not os.path.exists(video_path):
            return jsonify({'success': False, 'error': 'Video not found'}), 404
        
        return send_file(video_path, mimetype='video/webm')
        
    except Exception as e:
        logger.error(f"Error serving video: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bug-builder/upload-video', methods=['POST'])
@jira_auth_required
def upload_bug_builder_video():
    """Upload screen recording video for a bug session"""
    try:
        session_id = request.form.get('session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID required'}), 400
        
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Get the uploaded video file
        if 'video' not in request.files:
            return jsonify({'success': False, 'error': 'No video file provided'}), 400
        
        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({'success': False, 'error': 'No video file selected'}), 400
        
        # Create video directory if it doesn't exist
        output_dir = os.path.dirname(session.playwright_script_path) if session.playwright_script_path else None
        if not output_dir:
            output_dir = os.path.join('playwright-output', 'bug-builder', session_id)
            os.makedirs(output_dir, exist_ok=True)
        
        video_dir = os.path.join(output_dir, 'videos')
        os.makedirs(video_dir, exist_ok=True)
        
        # Save the video file
        video_filename = f"screen-recording-{int(time.time())}.webm"
        video_path = os.path.join(video_dir, video_filename)
        
        video_file.save(video_path)
        
        # Update session with video path
        session.video_path = video_path
        db.session.commit()
        
        logger.info(f"Screen recording uploaded for session {session_id}: {video_path}")
        
        return jsonify({
            'success': True,
            'video_url': f"/api/bug-builder/video/{session_id}/{video_filename}",
            'message': 'Video uploaded successfully'
        })
        
    except Exception as e:
        logger.error(f"Error uploading video: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bug-builder/process-recording', methods=['POST'])
@jira_auth_required
@llm_rate_limit
def process_bug_recording():
    """Process recorded video and generate bug report using AI"""
    try:
        session_id = request.form.get('session_id')
        annotations = json.loads(request.form.get('annotations', '[]'))
        action_logs = json.loads(request.form.get('actions', '[]'))
        clarification = json.loads(request.form.get('clarification', '{}'))
        
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Save video file
        video_file = request.files.get('video')
        if video_file:
            import os
            video_filename = f"bug_recording_{session_id}.webm"
            video_path = os.path.join('uploads', video_filename)
            
            # Ensure uploads directory exists
            os.makedirs('uploads', exist_ok=True)
            video_file.save(video_path)
            session.video_path = video_path
        
        # Update session with data
        session.annotations = json.dumps(annotations)
        session.action_logs = json.dumps(action_logs)
        session.status = 'processing'
        db.session.commit()
        
        # Generate bug report using AI with clarification
        bug_report = generate_ai_bug_report(action_logs, annotations, clarification)
        
        # Save bug report
        session.bug_report = json.dumps(bug_report)
        session.status = 'completed'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'bug_report': bug_report
        })
        
    except Exception as e:
        logger.error(f"Error processing bug recording: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def generate_ai_bug_report(action_logs, annotations, clarification=None):
    """Generate bug report using AI analysis"""
    try:
        # Prepare context for AI
        context = {
            'actions': action_logs,
            'annotations': annotations,
            'clarification': clarification,
            'total_actions': len(action_logs),
            'total_annotations': len(annotations)
        }
        
        # Create prompt for AI
        action_summary = analyze_action_patterns(action_logs)
        
        prompt = f"""
Analyze this comprehensive bug recording data and generate a detailed, structured bug report.

=== USER ISSUE DESCRIPTION ===
{clarification.get('issue_description', 'No specific issue described')}

=== USER EXPECTED BEHAVIOR ===
{clarification.get('expected_behavior', 'Not specified')}

=== USER ACTUAL BEHAVIOR ===
{clarification.get('actual_behavior', 'Not specified')}

=== RECORDING SUMMARY ===
Total Actions Recorded: {len(action_logs)}
User Annotations: {len(annotations)}
Recording Duration: {action_logs[-1]['timestamp'] if action_logs else 0}ms

=== ACTION ANALYSIS ===
{action_summary}

=== DETAILED ACTION LOG ===
{format_action_logs_for_ai(action_logs[:15])}

=== USER ANNOTATIONS ===
{format_annotations_for_ai(annotations)}

=== ANALYSIS REQUIREMENTS ===
Generate a comprehensive bug report with the following EXACT structure:

SUMMARY: [Brief one-line summary of the bug]

DESCRIPTION: [Detailed description of the issue, including context from user clarification and observed behavior]

STEPS TO REPRODUCE:
1. [Step 1]
2. [Step 2]
3. [Step 3]
[... continue with numbered steps based on the action logs]

EXPECTED RESULT:
[What should happen according to user expectation and normal behavior]

ACTUAL RESULT:
[What actually happened according to user observation and recorded actions]

Pay special attention to:
- User's specific issue description
- Behavioral issues where actions don't match expectations
- API response inconsistencies
- JavaScript errors or console warnings
- Form submission issues
- Navigation problems
- Performance or timing issues

Make the steps to reproduce clear and actionable, based on the recorded user actions.
Ensure the summary is concise and captures the core issue.
The description should provide context and impact of the bug.
"""
        
        # Use Google AI if available
        if genai:
            model = genai.GenerativeModel(os.environ.get('GOOGLE_API_MODEL'))
            response = model.generate_content(prompt)
            ai_analysis = response.text
        else:
            # Fallback to basic analysis
            ai_analysis = generate_basic_bug_report(action_logs, annotations, clarification)
        
        # Parse AI response into structured format
        bug_report = parse_ai_bug_report(ai_analysis, action_logs, annotations, clarification)
        
        return bug_report
        
    except Exception as e:
        logger.error(f"Error generating AI bug report: {str(e)}")
        return generate_basic_bug_report(action_logs, annotations, clarification)

def analyze_action_patterns(action_logs):
    """Analyze action patterns to identify potential issues"""
    if not action_logs:
        return "No actions recorded."
    
    analysis = []
    
    # Count action types
    action_counts = {}
    error_count = 0
    api_calls = 0
    form_submissions = 0
    navigation_count = 0
    
    for action in action_logs:
        action_type = action.get('type', 'unknown')
        action_counts[action_type] = action_counts.get(action_type, 0) + 1
        
        if action_type in ['javascript_error', 'console_error', 'unhandled_promise_rejection']:
            error_count += 1
        elif action_type in ['xhr_request', 'fetch_request']:
            api_calls += 1
        elif action_type == 'submit':
            form_submissions += 1
        elif action_type == 'navigation':
            navigation_count += 1
    
    # Generate analysis summary
    analysis.append(f"Action Types: {', '.join([f'{k}: {v}' for k, v in sorted(action_counts.items())])}")
    
    if error_count > 0:
        analysis.append(f"⚠️ {error_count} JavaScript/Console errors detected")
    
    if api_calls > 0:
        analysis.append(f"🌐 {api_calls} API calls made")
        
        # Analyze API response patterns
        failed_apis = []
        for action in action_logs:
            if action.get('type') in ['xhr_response', 'fetch_response']:
                status = action.get('status', 0)
                if status >= 400:
                    failed_apis.append(f"{action.get('method', 'GET')} {action.get('url', 'unknown')} ({status})")
        
        if failed_apis:
            analysis.append(f"❌ Failed API calls: {', '.join(failed_apis[:3])}")
    
    if form_submissions > 0:
        analysis.append(f"📝 {form_submissions} form submissions")
    
    if navigation_count > 0:
        analysis.append(f"🔄 {navigation_count} page navigations")
    
    # Identify potential issues
    issues = []
    
    # Check for rapid clicking (potential UI responsiveness issue)
    click_times = [action['timestamp'] for action in action_logs if action.get('type') == 'click']
    if len(click_times) > 1:
        rapid_clicks = sum(1 for i in range(1, len(click_times)) if click_times[i] - click_times[i-1] < 500)
        if rapid_clicks > 2:
            issues.append(f"Rapid clicking detected ({rapid_clicks} instances) - possible UI responsiveness issue")
    
    # Check for repeated actions (potential confusion)
    repeated_actions = {}
    for action in action_logs:
        if action.get('type') in ['click', 'input']:
            target = str(action.get('target', ''))
            repeated_actions[target] = repeated_actions.get(target, 0) + 1
    
    high_repeat = [target for target, count in repeated_actions.items() if count > 3]
    if high_repeat:
        issues.append(f"Repeated interactions with same elements: {len(high_repeat)} elements")
    
    if issues:
        analysis.append("\n🔍 Potential Issues Identified:")
        analysis.extend([f"  - {issue}" for issue in issues])
    
    return '\n'.join(analysis)

def format_action_logs_for_ai(actions):
    """Format action logs for AI analysis with enhanced detail"""
    formatted = []
    for i, action in enumerate(actions):
        timestamp = action.get('timestamp', 0)
        action_type = action.get('type', 'unknown')
        
        if action_type == 'click':
            target = action.get('target', {})
            if isinstance(target, dict):
                element_desc = get_element_description(target)
                coords = action.get('coordinates', {})
                formatted.append(f"{i+1}. [{timestamp}ms] Click on {element_desc} at ({coords.get('x', 0)}, {coords.get('y', 0)})")
            else:
                formatted.append(f"{i+1}. [{timestamp}ms] Click on {target}")
                
        elif action_type == 'input':
            target = action.get('target', {})
            value = action.get('value', '')
            if isinstance(target, dict):
                element_desc = get_element_description(target)
                formatted.append(f"{i+1}. [{timestamp}ms] Input '{value[:30]}' in {element_desc}")
            else:
                formatted.append(f"{i+1}. [{timestamp}ms] Input '{value[:30]}' in {target}")
                
        elif action_type in ['xhr_request', 'fetch_request']:
            method = action.get('method', 'GET')
            url = action.get('url', 'unknown')
            formatted.append(f"{i+1}. [{timestamp}ms] API {method} request to {url}")
            
        elif action_type in ['xhr_response', 'fetch_response']:
            method = action.get('method', 'GET')
            url = action.get('url', 'unknown')
            status = action.get('status', 'unknown')
            formatted.append(f"{i+1}. [{timestamp}ms] API {method} response from {url} (Status: {status})")
            
        elif action_type in ['javascript_error', 'console_error']:
            message = action.get('message', 'Unknown error')
            formatted.append(f"{i+1}. [{timestamp}ms] ❌ Error: {message[:50]}")
            
        elif action_type == 'navigation':
            from_url = action.get('fromUrl', '')
            to_url = action.get('toUrl', '')
            formatted.append(f"{i+1}. [{timestamp}ms] Navigate from {from_url} to {to_url}")
            
        elif action_type == 'submit':
            target = action.get('target', {})
            if isinstance(target, dict):
                element_desc = get_element_description(target)
                formatted.append(f"{i+1}. [{timestamp}ms] Submit {element_desc}")
            else:
                formatted.append(f"{i+1}. [{timestamp}ms] Submit form")
                
        else:
            formatted.append(f"{i+1}. [{timestamp}ms] {action_type} on {action.get('target', 'unknown')}")
    
    return '\n'.join(formatted)

def format_annotations_for_ai(annotations):
    """Format annotations for AI analysis"""
    if not annotations:
        return "No user annotations provided."
    
    formatted = []
    for i, annotation in enumerate(annotations, 1):
        formatted.append(f"{i}. At {annotation['timestamp']}ms: {annotation['text']}")
    return '\n'.join(formatted)

def parse_ai_bug_report(ai_text, action_logs, annotations):
    """Parse AI-generated text into structured bug report"""
    # Basic parsing - can be enhanced with more sophisticated NLP
    lines = ai_text.split('\n')
    
    bug_report = {
        'title': 'Bug Report Generated from Recording',
        'description': ai_text[:500] + '...' if len(ai_text) > 500 else ai_text,
        'steps_to_reproduce': extract_steps_from_actions(action_logs),
        'expected_result': extract_expected_from_annotations(annotations),
        'actual_result': extract_actual_from_annotations(annotations),
        'priority': 'medium',
        'evidence': [
            {'type': 'video', 'name': 'Screen Recording', 'description': 'Complete user session recording'},
            {'type': 'logs', 'name': 'Action Logs', 'description': f'{len(action_logs)} user interactions captured'},
            {'type': 'annotations', 'name': 'User Notes', 'description': f'{len(annotations)} behavioral observations'}
        ]
    }
    
    # Try to extract title from AI response
    for line in lines:
        if 'title:' in line.lower() or line.startswith('#'):
            bug_report['title'] = line.replace('Title:', '').replace('#', '').strip()
            break
    
    return bug_report

def extract_steps_from_actions(action_logs):
    """Convert comprehensive action logs to detailed reproduction steps"""
    steps = []
    step_num = 1
    
    # Group related actions and create meaningful steps
    i = 0
    while i < len(action_logs) and step_num <= 20:  # Limit to 20 steps
        action = action_logs[i]
        
        if action['type'] == 'navigation':
            steps.append(f"{step_num}. Navigate to {action.get('toUrl', action.get('url', 'page'))}")
            step_num += 1
            
        elif action['type'] == 'click':
            target_info = action.get('target', {})
            if isinstance(target_info, dict):
                element_desc = get_element_description(target_info)
                coordinates = action.get('coordinates', {})
                steps.append(f"{step_num}. Click on {element_desc}")
            else:
                steps.append(f"{step_num}. Click on {target_info}")
            step_num += 1
            
        elif action['type'] == 'input' and action.get('value'):
            target_info = action.get('target', {})
            value = action.get('value', '')
            if isinstance(target_info, dict):
                element_desc = get_element_description(target_info)
                if value != '[SENSITIVE_DATA_HIDDEN]':
                    steps.append(f"{step_num}. Enter '{value[:50]}' in {element_desc}")
                else:
                    steps.append(f"{step_num}. Enter sensitive data in {element_desc}")
            else:
                steps.append(f"{step_num}. Enter '{value[:50]}' in {target_info}")
            step_num += 1
            
        elif action['type'] == 'submit':
            target_info = action.get('target', {})
            if isinstance(target_info, dict):
                element_desc = get_element_description(target_info)
                steps.append(f"{step_num}. Submit {element_desc}")
            else:
                steps.append(f"{step_num}. Submit form")
            step_num += 1
        
        i += 1
    
    return '\n'.join(steps) if steps else 'Steps will be extracted from recording analysis'

def get_element_description(target_info):
    """Generate human-readable description of an element"""
    if not isinstance(target_info, dict):
        return str(target_info)
    
    # Priority order for element identification
    if target_info.get('id'):
        return f"element with ID '{target_info['id']}'"
    elif target_info.get('name'):
        return f"'{target_info['name']}' field"
    elif target_info.get('placeholder'):
        return f"field with placeholder '{target_info['placeholder']}'"
    elif target_info.get('text') and len(target_info['text'].strip()) > 0:
        return f"'{target_info['text'][:30]}' element"
    elif target_info.get('type'):
        return f"{target_info['type']} input"
    elif target_info.get('tagName'):
        return f"{target_info['tagName']} element"
    else:
        return "element"

def extract_expected_from_annotations(annotations):
    """Extract expected behavior from user annotations"""
    expected_parts = []
    for annotation in annotations:
        text = annotation['text'].lower()
        if 'expected' in text or 'should' in text:
            expected_parts.append(annotation['text'])
    
    return ' '.join(expected_parts) if expected_parts else 'Expected behavior as per requirements'

def extract_actual_from_annotations(annotations):
    """Extract actual behavior from user annotations"""
    actual_parts = []
    for annotation in annotations:
        text = annotation['text'].lower()
        if 'actual' in text or 'but' in text or 'instead' in text:
            actual_parts.append(annotation['text'])
    
    return ' '.join(actual_parts) if actual_parts else 'Actual behavior differs from expected'

def generate_basic_bug_report(action_logs, annotations):
    """Generate basic bug report without AI"""
    return {
        'title': f'Bug Report - {len(action_logs)} actions recorded',
        'description': f'Bug identified during testing session with {len(annotations)} user observations.',
        'steps_to_reproduce': extract_steps_from_actions(action_logs),
        'expected_result': extract_expected_from_annotations(annotations),
        'actual_result': extract_actual_from_annotations(annotations),
        'priority': 'medium',
        'evidence': [
            {'type': 'video', 'name': 'Screen Recording'},
            {'type': 'logs', 'name': f'{len(action_logs)} Action Logs'},
            {'type': 'annotations', 'name': f'{len(annotations)} User Notes'}
        ]
    }

@app.route('/api/bug-builder/upload-video', methods=['POST'])
@jira_auth_required
def upload_bug_video():
    """Upload video for preview and save action logs"""
    try:
        session_id = request.form.get('session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID required'}), 400
        
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Save action logs if provided (optional - for future enhancement)
        action_logs_str = request.form.get('actions')
        if action_logs_str:
            try:
                import json
                action_logs = json.loads(action_logs_str)
                session.action_logs = action_logs_str
                logger.info(f"📝 Saved {len(action_logs)} actions to session {session_id}")
            except Exception as log_error:
                logger.error(f"Error saving action logs: {log_error}")
        
        # Save video file
        video_file = request.files.get('video')
        if video_file:
            import os
            video_filename = f"bug_recording_{session_id}.webm"
            video_path = os.path.join('uploads', video_filename)
            
            # Ensure uploads directory exists
            os.makedirs('uploads', exist_ok=True)
            video_file.save(video_path)
            
            # Update session with video path
            session.video_path = video_path
            db.session.commit()
            
            return jsonify({
                'success': True,
                'video_url': f'/api/bug-builder/video/{session_id}',
                'actions_saved': len(json.loads(action_logs_str)) if action_logs_str else 0
            })
        else:
            return jsonify({'success': False, 'error': 'No video file provided'}), 400
            
    except Exception as e:
        logger.error(f"Error uploading video: {str(e)}")
        import traceback
        logger.error(f"Upload error traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': 'Failed to upload video'}), 500

@app.route('/api/bug-builder/video/<session_id>')
@jira_auth_required
def serve_bug_video(session_id):
    """Serve recorded video for preview"""
    try:
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session or not session.video_path:
            return jsonify({'error': 'Video not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Serve video file with proper headers for streaming
        import os
        if os.path.exists(session.video_path):
            from flask import Response
            
            def generate():
                with open(session.video_path, 'rb') as f:
                    data = f.read(1024)
                    while data:
                        yield data
                        data = f.read(1024)
            
            # Get file size for Content-Length header
            file_size = os.path.getsize(session.video_path)
            
            return Response(
                generate(),
                mimetype='video/webm',
                headers={
                    'Content-Length': str(file_size),
                    'Accept-Ranges': 'bytes',
                    'Cache-Control': 'no-cache',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET',
                    'Access-Control-Allow-Headers': 'Range'
                }
            )
        else:
            return jsonify({'error': 'Video file not found'}), 404
            
    except Exception as e:
        logger.error(f"Error serving video: {str(e)}")
        return jsonify({'error': 'Failed to serve video'}), 500
@app.route('/api/bug-builder/session-summary/<session_id>', methods=['GET'])
@jira_auth_required
def bug_builder_session_summary(session_id):
    try:
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404

        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        try:
            actions = json.loads(session.action_logs or '[]')
        except Exception:
            actions = []

        summary = {
            'session_id': session.session_id,
            'status': session.status,
            'created_at': session.created_at.isoformat() if session.created_at else None,
            'video_path': session.video_path,
            'action_count': len(actions),
            'action_highlights': summarize_actions(actions)[:10],
            'playwright': {
                'status': session.playwright_status,
                'script_path': session.playwright_script_path,
                'trace_path': session.playwright_trace_path,
                'video_path': session.playwright_video_path,
                'error': session.playwright_error,
            },
        }

        return jsonify({'success': True, 'summary': summary})
    except Exception as exc:
        logger.error(f"Error fetching session summary: {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 500
        
@app.route('/api/bug-builder/submit-to-jira', methods=['POST'])
@jira_auth_required
def submit_bug_to_jira():
    """Submit bug report to Jira with optional video attachment"""
    try:
        data = request.get_json()
        project_key = data.get('project_key')
        summary = data.get('summary', 'Bug Report from Co-Tester')
        description = data.get('description', '')
        priority = data.get('priority', 'Medium')
        steps = data.get('steps', [])
        expected_result = data.get('expected_result', '')
        actual_result = data.get('actual_result', '')
        attach_video = data.get('attach_video', False)
        session_id = data.get('session_id')
        
        if not project_key:
            return jsonify({'success': False, 'error': 'Project key is required'}), 400
        
        # Check if token needs refresh
        token_expires = session.get('jira_token_expires', 0)
        if time.time() >= token_expires:
            logger.info("Jira token expired, attempting refresh...")
            if not refresh_jira_token():
                return jsonify({'success': False, 'error': 'Jira token expired. Please reconnect to Jira.'}), 401
        
        # Get Jira credentials from Flask session
        jira_token = session.get('jira_access_token')
        jira_domain = session.get('jira_domain')
        
        if not jira_token:
            return jsonify({'success': False, 'error': 'Jira authentication required. Please connect to Jira first.'}), 401
        
        if not jira_domain:
            # Fallback to default domain
            jira_domain = 'https://upgrad-jira.atlassian.net'
            logger.warning("No jira_domain in session, using default")
        
        # Format description with steps
        steps_text = '\n'.join(f"{i+1}. {step}" for i, step in enumerate(steps)) if steps else "No steps provided"
        full_description = f"""{description}

*Steps to Reproduce:*
{steps_text}

*Expected Result:*
{expected_result}

*Actual Result:*
{actual_result}

---
_Generated by Co-Tester Bug Builder_"""
        
        # Extract base URL from jira_domain (remove https:// if present)
        if jira_domain.startswith('http'):
            jira_base_url = jira_domain
        else:
            jira_base_url = f"https://{jira_domain}"
        
        # Prepare Jira issue data
        issue_data = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": full_description,
                "issuetype": {"name": "Bug"},
                "priority": {"name": priority.title()}
            }
        }
        
        # Create Jira issue
        logger.info(f"Creating Jira issue in project {project_key}")
        logger.info(f"Using Jira base URL: {jira_base_url}")
        
        jira_response = requests.post(
            f"{jira_base_url}/rest/api/3/issue",
            headers={
                'Authorization': f'Bearer {jira_token}',
                'Content-Type': 'application/json'
            },
            json=issue_data
        )
        
        logger.info(f"Jira API response status: {jira_response.status_code}")
        
        if jira_response.status_code == 201:
            issue_key = jira_response.json()['key']
            issue_id = jira_response.json()['id']
            video_attached = False
            
            # Attach video if requested and available
            if attach_video and session_id:
                bug_session = BugSession.query.filter_by(session_id=session_id).first()
                if bug_session and bug_session.video_path and os.path.exists(bug_session.video_path):
                    try:
                        logger.info(f"Attaching video to Jira issue {issue_key}")
                        
                        # Upload video as attachment
                        with open(bug_session.video_path, 'rb') as video_file:
                            files = {
                                'file': ('bug-recording.webm', video_file, 'video/webm')
                            }
                            attach_response = requests.post(
                                f"{jira_base_url}/rest/api/3/issue/{issue_key}/attachments",
                                headers={
                                    'Authorization': f'Bearer {jira_token}',
                                    'X-Atlassian-Token': 'no-check'
                                },
                                files=files
                            )
                            
                            if attach_response.status_code == 200:
                                video_attached = True
                                logger.info(f"Video attached successfully to {issue_key}")
                            else:
                                logger.warning(f"Failed to attach video: {attach_response.text}")
                    except Exception as attach_error:
                        logger.error(f"Error attaching video: {str(attach_error)}")
            
            # Update bug session if exists
            if session_id:
                bug_session = BugSession.query.filter_by(session_id=session_id).first()
                if bug_session:
                    bug_session.jira_issue_key = issue_key
                    db.session.commit()
            
            return jsonify({
                'success': True,
                'issue_key': issue_key,
                'issue_url': f"{jira_base_url}/browse/{issue_key}",
                'video_attached': video_attached
            })
        else:
            error_text = jira_response.text
            logger.error(f"Jira API error: {error_text}")
            
            # Check if it's an authentication error
            if jira_response.status_code == 401:
                # Try to refresh token and retry once
                if refresh_jira_token():
                    jira_token = session.get('jira_access_token')
                    logger.info("Token refreshed, retrying Jira API call...")
                    
                    jira_response = requests.post(
                        f"{jira_base_url}/rest/api/3/issue",
                        headers={
                            'Authorization': f'Bearer {jira_token}',
                            'Content-Type': 'application/json'
                        },
                        json=issue_data
                    )
                    
                    if jira_response.status_code == 201:
                        issue_key = jira_response.json()['key']
                        issue_id = jira_response.json()['id']
                        
                        return jsonify({
                            'success': True,
                            'issue_key': issue_key,
                            'issue_url': f"{jira_base_url}/browse/{issue_key}",
                            'video_attached': False
                        })
            
            return jsonify({
                'success': False,
                'error': f'Jira API error ({jira_response.status_code}): {error_text}'
            }), 400
            
    except Exception as e:
        logger.error(f"Error submitting to Jira: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

def format_jira_description(bug_data):
    """Format bug report for Jira description"""
    description = f"""
*Description:*
{bug_data.get('description', '')}

*Steps to Reproduce:*
{bug_data.get('steps_to_reproduce', '')}

*Expected Result:*
{bug_data.get('expected_result', '')}

*Actual Result:*
{bug_data.get('actual_result', '')}

*Generated by:* Co-Tester Bug Builder
*Session ID:* {bug_data.get('session_id', '')}
"""
    return description

# =============================================================================
# BULK TEST GENERATOR ROUTES
# =============================================================================

@app.route('/api/bulk-generator/validate-jql', methods=['POST'])
@jira_auth_required
def validate_jql():
    """Validate JQL query against Jira API"""
    try:
        data = request.get_json()
        jql_query = data.get('jql_query', '').strip()
        
        if not jql_query:
            return jsonify({'success': False, 'error': 'JQL query is required'}), 400
        
        # Get Jira credentials from session
        jira_token = session.get('jira_access_token')
        jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        cloud_id = session.get('jira_cloud_id')
        
        if not jira_token:
            return jsonify({'success': False, 'error': 'Jira authentication required'}), 401
        
        # Check if token needs refresh
        import time
        token_expires = session.get('jira_token_expires', 0)
        logger.info(f"Token expires at: {token_expires}, current time: {time.time()}")
        if time.time() >= token_expires:
            logger.info("Token expired, attempting refresh...")
            if not refresh_jira_token():
                logger.error("Token refresh failed")
                return jsonify({'success': False, 'error': 'Token expired. Please reconnect to Jira.'}), 401
            logger.info("Token refresh successful")
            jira_token = session['jira_access_token']
        
        # Extract site name from domain URL
        jira_site = jira_domain.replace('https://', '').replace('.atlassian.net', '')
        
        # Log debug information
        logger.info(f"Validating JQL query: {jql_query}")
        logger.info(f"Using Jira domain: {jira_domain}")
        logger.info(f"Has access token: {bool(jira_token)}")
        
        # Test JQL query with maxResults=1 to validate syntax
        jira_response = requests.get(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
            headers={
                'Authorization': f'Bearer {jira_token}',
                'Content-Type': 'application/json'
            },
            params={
                'jql': jql_query,
                'maxResults': 1,
                'fields': 'key,summary'
            },
            timeout=30
        )
        
        logger.info(f"Jira API response status: {jira_response.status_code}")
        logger.info(f"Jira API response headers: {dict(jira_response.headers)}")
        logger.info(f"Jira API response content length: {len(jira_response.content)}")
        
        if jira_response.status_code == 200:
            try:
                result = jira_response.json()
                total_count = result.get('total', 0)
                
                return jsonify({
                    'success': True,
                    'valid': True,
                    'total_stories': total_count,
                    'message': f'JQL query is valid. Found {total_count} stories.'
                })
            except ValueError as e:
                logger.error(f"Failed to parse Jira response JSON: {str(e)}")
                logger.error(f"Response content: {jira_response.text}")
                return jsonify({
                    'success': True,
                    'valid': False,
                    'error': 'Invalid response from Jira API'
                })
        elif jira_response.status_code == 401:
            # Try to refresh token and retry once
            logger.info("Got 401, attempting token refresh and retry")
            refresh_success = refresh_jira_token()
            logger.info(f"Token refresh result: {refresh_success}")
            if refresh_success:
                logger.info("Retrying request with refreshed token")
                # Retry the request with new token
                jira_response = requests.get(
                    f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
                    headers={
                        'Authorization': f'Bearer {session["jira_access_token"]}',
                        'Content-Type': 'application/json'
                    },
                    params={
                        'jql': jql_query,
                        'maxResults': 1,
                        'fields': 'key,summary'
                    },
                    timeout=30
                )
                
                if jira_response.status_code == 200:
                    try:
                        result = jira_response.json()
                        total_count = result.get('total', 0)
                        
                        return jsonify({
                            'success': True,
                            'valid': True,
                            'total_stories': total_count,
                            'message': f'JQL query is valid. Found {total_count} stories.'
                        })
                    except ValueError as e:
                        logger.error(f"Failed to parse Jira response JSON after retry: {str(e)}")
                        return jsonify({
                            'success': True,
                            'valid': False,
                            'error': 'Invalid response from Jira API'
                        })
            
            logger.error("Token refresh failed, user needs to reconnect")
            return jsonify({
                'success': False,
                'error': 'Authentication failed. Please refresh the page and reconnect to Jira.',
                'action': 'reconnect'
            }), 401
        else:
            try:
                error_data = jira_response.json() if jira_response.content else {}
                error_messages = error_data.get('errorMessages', [])
                error_message = error_messages[0] if error_messages else 'Invalid JQL query'
            except ValueError:
                logger.error(f"Failed to parse Jira error response: {jira_response.text}")
                error_message = f'Jira API error (Status: {jira_response.status_code})'
            
            return jsonify({
                'success': True,
                'valid': False,
                'error': error_message
            })
            
    except Exception as e:
        logger.error(f"Error validating JQL: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/create-session', methods=['POST'])
@jira_auth_required
def create_bulk_session():
    """Create a new bulk test generation session"""
    try:
        data = request.get_json()
        jql_query = data.get('jql_query', '').strip()
        
        if not jql_query:
            return jsonify({'success': False, 'error': 'JQL query is required'}), 400
        
        user_id = get_user_identifier()
        
        # Generate unique session ID
        import uuid
        session_id = str(uuid.uuid4())
        
        # Get Jira site URL
        jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        jira_project_url = jira_domain
        
        # Create new session
        bulk_session = JQLSession(
            user_id=user_id,
            session_id=session_id,
            jql_query=jql_query,
            jira_project_url=jira_project_url,
            status='created'
        )
        db.session.add(bulk_session)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        logger.error(f"Error creating bulk session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/fetch-stories', methods=['POST'])
@jira_auth_required
def fetch_stories():
    """Fetch stories from Jira using JQL query"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID is required'}), 400
        
        # Get session
        bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
        if not bulk_session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Get Jira credentials from session
        jira_token = session.get('jira_access_token')
        jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        cloud_id = session.get('jira_cloud_id')
        
        if not jira_token:
            return jsonify({'success': False, 'error': 'Jira authentication required'}), 401
        
        # Update session status
        bulk_session.status = 'fetching'
        db.session.commit()
        
        # Fetch stories from Jira
        stories = []
        start_at = 0
        max_results = 50
        
        while True:
            jira_response = requests.get(
                f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
                headers={
                    'Authorization': f'Bearer {jira_token}',
                    'Content-Type': 'application/json'
                },
                params={
                    'jql': bulk_session.jql_query,
                    'startAt': start_at,
                    'maxResults': max_results,
                    'fields': 'key,summary,description,issuetype,priority,status,assignee,labels,components'
                }
            )
            
            if jira_response.status_code != 200:
                bulk_session.status = 'failed'
                db.session.commit()
                return jsonify({'success': False, 'error': 'Failed to fetch stories from Jira'}), 400
            
            result = jira_response.json()
            issues = result.get('issues', [])
            
            if not issues:
                break
            
            # Process each issue
            for issue in issues:
                fields = issue.get('fields', {})
                
                # Extract acceptance criteria from description
                description = fields.get('description', {})
                description_text = ''
                acceptance_criteria = ''
                
                if description and isinstance(description, dict):
                    # Handle Atlassian Document Format (ADF)
                    description_text = extract_text_from_adf(description)
                    acceptance_criteria = extract_acceptance_criteria(description_text)
                elif isinstance(description, str):
                    description_text = description
                    acceptance_criteria = extract_acceptance_criteria(description_text)
                
                # Create story record
                story = JQLStory(
                    session_id=bulk_session.id,
                    jira_key=issue['key'],
                    title=fields.get('summary', ''),
                    description=description_text,
                    story_type=fields.get('issuetype', {}).get('name', ''),
                    priority=fields.get('priority', {}).get('name', ''),
                    status=fields.get('status', {}).get('name', ''),
                    assignee=fields.get('assignee', {}).get('displayName', '') if fields.get('assignee') else '',
                    labels=json.dumps(fields.get('labels', [])),
                    components=json.dumps([c.get('name', '') for c in fields.get('components', [])]),
                    acceptance_criteria=acceptance_criteria
                )
                db.session.add(story)
                stories.append({
                    'key': story.jira_key,
                    'title': story.title,
                    'type': story.story_type,
                    'priority': story.priority,
                    'status': story.status
                })
            
            start_at += max_results
            if start_at >= result.get('total', 0):
                break
        
        # Update session with totals
        bulk_session.total_stories = len(stories)
        bulk_session.status = 'fetched'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'stories': stories,
            'total_count': len(stories)
        })
        
    except Exception as e:
        logger.error(f"Error fetching stories: {str(e)}")
        # Update session status to failed
        if 'bulk_session' in locals():
            bulk_session.status = 'failed'
            db.session.commit()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/generate-tests', methods=['POST'])
@jira_auth_required
def generate_bulk_tests():
    """Generate test cases for all stories in the session"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        selected_stories = data.get('selected_stories', [])
        context_name = data.get('context', '')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID is required'}), 400
        
        if not selected_stories:
            return jsonify({'success': False, 'error': 'No stories selected for generation'}), 400
        
        if len(selected_stories) > 10:
            return jsonify({'success': False, 'error': 'Maximum 10 stories allowed per generation session'}), 400
        
        if not context_name:
            return jsonify({'success': False, 'error': 'Context is required for test generation'}), 400
        
        # Get session
        bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
        if not bulk_session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Update session status
        bulk_session.status = 'generating'
        bulk_session.processed_stories = 0
        bulk_session.failed_stories = 0
        db.session.commit()
        
        # Get only selected stories for this session
        stories = JQLStory.query.filter_by(session_id=bulk_session.id).filter(JQLStory.jira_key.in_(selected_stories)).all()
        
        # Update session with actual story count
        bulk_session.total_stories = len(stories)
        db.session.commit()
        
        logger.info(f"Starting generation for {len(stories)} selected stories: {[s.jira_key for s in stories]}")
        
        # Process stories synchronously for now to avoid threading issues
        logger.info(f"Processing {len(stories)} stories synchronously")
        
        try:
            # Generate test cases for each story
            for i, story in enumerate(stories):
                try:
                    logger.info(f"Processing story {i+1}/{len(stories)}: {story.jira_key}")
                    story.test_generation_status = 'generating'
                    db.session.commit()
                    
                    # Generate test cases using AI with context
                    logger.info(f"Starting generation for {story.jira_key} with context {context_name}")
                    test_cases = generate_test_cases_for_story(story, context_name)
                    logger.info(f"Generation completed for {story.jira_key}, got {len(test_cases) if test_cases else 0} test cases")
                    
                    if test_cases and len(test_cases) > 0:
                        test_cases_json = json.dumps(test_cases)
                        story.test_cases = test_cases_json
                        story.test_generation_status = 'completed'
                        logger.info(f"Saved {len(test_cases)} test cases for {story.jira_key}")
                        logger.info(f"Test cases JSON length: {len(test_cases_json)}")
                        logger.info(f"First test case: {test_cases[0] if test_cases else 'None'}")
                    else:
                        logger.error(f"No test cases generated for {story.jira_key}, marking as failed")
                        story.test_generation_status = 'failed'
                        story.generation_error = 'No test cases were generated. This could be due to missing API key or generation failure.'
                        bulk_session.failed_stories += 1
                    
                    story.generated_at = datetime.utcnow()
                    if story.test_generation_status == 'completed':
                        bulk_session.processed_stories += 1
                    
                    logger.info(f"Completed story {story.jira_key}. Progress: {bulk_session.processed_stories}/{len(stories)}, Failed: {bulk_session.failed_stories}")
                    
                except Exception as story_error:
                    logger.error(f"Error processing story {story.jira_key}: {str(story_error)}")
                    story.test_generation_status = 'failed'
                    story.generation_error = str(story_error)
                    bulk_session.failed_stories += 1
                    
                # Commit after each story to ensure progress is visible
                db.session.commit()
            
            # Update session status
            logger.info(f"Generation completed. Processed: {bulk_session.processed_stories}, Failed: {bulk_session.failed_stories}")
            bulk_session.status = 'completed'
            bulk_session.completed_at = datetime.utcnow()
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Error in synchronous generation: {str(e)}")
            bulk_session.status = 'failed'
            db.session.commit()
            return jsonify({'success': False, 'error': str(e)}), 500
        
        return jsonify({
            'success': True,
            'message': 'Test generation completed',
            'total': len(stories),
            'processed': bulk_session.processed_stories,
            'failed': bulk_session.failed_stories,
            'thread_started': True
        })
        
    except Exception as e:
        logger.error(f"Error generating bulk tests: {str(e)}")
        # Update session status to failed
        if 'bulk_session' in locals():
            bulk_session.status = 'failed'
            db.session.commit()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/session-status/<session_id>')
@jira_auth_required
def get_session_status(session_id):
    """Get current status of bulk generation session"""
    try:
        bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
        if not bulk_session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        return jsonify({
            'success': True,
            'status': bulk_session.status,
            'total_stories': bulk_session.total_stories,
            'processed_stories': bulk_session.processed_stories,
            'failed_stories': bulk_session.failed_stories,
            'progress_percentage': (bulk_session.processed_stories + bulk_session.failed_stories) / max(bulk_session.total_stories, 1) * 100
        })
        
    except Exception as e:
        logger.error(f"Error getting session status: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/test-thread')
@jira_auth_required
def test_background_thread():
    """Test if background threading works"""
    import threading
    import time
    from flask import current_app
    
    test_result = {'started': False, 'completed': False, 'error': None}
    
    def test_thread():
        try:
            test_result['started'] = True
            logger.info("Test thread started")
            time.sleep(2)
            with current_app.app_context():
                logger.info("Test thread in app context")
                test_result['completed'] = True
        except Exception as e:
            test_result['error'] = str(e)
            logger.error(f"Test thread error: {str(e)}")
    
    thread = threading.Thread(target=test_thread)
    thread.daemon = True
    thread.start()
    
    # Wait a bit to see if thread starts
    time.sleep(0.5)
    
    return jsonify({
        'success': True,
        'thread_alive': thread.is_alive(),
        'test_result': test_result
    })

@app.route('/api/bulk-generator/debug-session/<session_id>')
def debug_bulk_session(session_id):
    """Debug endpoint to see session data"""
    try:
        bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
        if not bulk_session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Only return stories that were actually processed (have test_generation_status set)
        stories = JQLStory.query.filter_by(session_id=bulk_session.id).filter(
            JQLStory.test_generation_status.isnot(None)
        ).all()
        
        stories_data = []
        for story in stories:
            # Debug logging for each story
            logger.info(f"Debug - Story {story.jira_key}: status={story.test_generation_status}, test_cases_length={len(story.test_cases) if story.test_cases else 0}")
            
            story_data = {
                'jira_key': story.jira_key,
                'title': story.title,
                'description': story.description,
                'acceptance_criteria': story.acceptance_criteria,
                'test_generation_status': story.test_generation_status,
                'generation_error': story.generation_error,
                'generated_at': story.generated_at.isoformat() if story.generated_at else None,
                'test_cases': story.test_cases  # Include actual test cases data
            }
            stories_data.append(story_data)
            
            # Log first few characters of test_cases for debugging
            if story.test_cases:
                logger.info(f"Debug - Story {story.jira_key} test_cases preview: {story.test_cases[:100]}...")
            else:
                logger.info(f"Debug - Story {story.jira_key} has NO test_cases data")
        
        return jsonify({
            'success': True,
            'session': {
                'session_id': bulk_session.session_id,
                'status': bulk_session.status,
                'total_stories': bulk_session.total_stories,
                'processed_stories': bulk_session.processed_stories,
                'failed_stories': bulk_session.failed_stories,
                'created_at': bulk_session.created_at.isoformat() if bulk_session.created_at else None,
                'completed_at': bulk_session.completed_at.isoformat() if bulk_session.completed_at else None
            },
            'stories': stories_data
        })
        
    except Exception as e:
        logger.error(f"Error in debug session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/update-test-case', methods=['POST'])
def update_bulk_test_case():
    """Update a specific test case in a story"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        story_key = data.get('story_key')
        test_index = data.get('test_index')
        new_step = data.get('step')
        new_expected = data.get('expected')
        
        if not all([session_id, story_key, test_index is not None, new_step, new_expected]):
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        
        # Find the session and story
        bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
        if not bulk_session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        story = JQLStory.query.filter_by(session_id=bulk_session.id, jira_key=story_key).first()
        if not story:
            return jsonify({'success': False, 'error': 'Story not found'}), 404
        
        # Parse and update test cases
        if story.test_cases:
            test_cases = json.loads(story.test_cases)
            if 0 <= test_index < len(test_cases):
                test_cases[test_index]['step'] = new_step
                test_cases[test_index]['expected'] = new_expected
                story.test_cases = json.dumps(test_cases)
                db.session.commit()
                
                return jsonify({'success': True, 'message': 'Test case updated successfully'})
            else:
                return jsonify({'success': False, 'error': 'Invalid test case index'}), 400
        else:
            return jsonify({'success': False, 'error': 'No test cases found'}), 404
            
    except Exception as e:
        logger.error(f"Error updating test case: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/delete-test-case', methods=['POST'])
def delete_bulk_test_case():
    """Delete a specific test case from a story"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        story_key = data.get('story_key')
        test_index = data.get('test_index')
        
        if not all([session_id, story_key, test_index is not None]):
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        
        # Find the session and story
        bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
        if not bulk_session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        story = JQLStory.query.filter_by(session_id=bulk_session.id, jira_key=story_key).first()
        if not story:
            return jsonify({'success': False, 'error': 'Story not found'}), 404
        
        # Parse and delete test case
        if story.test_cases:
            test_cases = json.loads(story.test_cases)
            if 0 <= test_index < len(test_cases):
                test_cases.pop(test_index)
                story.test_cases = json.dumps(test_cases)
                db.session.commit()
                
                return jsonify({'success': True, 'message': 'Test case deleted successfully'})
            else:
                return jsonify({'success': False, 'error': 'Invalid test case index'}), 400
        else:
            return jsonify({'success': False, 'error': 'No test cases found'}), 404
            
    except Exception as e:
        logger.error(f"Error deleting test case: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/add-test-case', methods=['POST'])
def add_bulk_test_case():
    """Add a new test case to a story"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        story_key = data.get('story_key')
        step = data.get('step')
        expected = data.get('expected')
        estimate_minutes = data.get('estimate_minutes', 15)
        
        if not all([session_id, story_key, step, expected]):
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        
        # Find the session and story
        bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
        if not bulk_session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        story = JQLStory.query.filter_by(session_id=bulk_session.id, jira_key=story_key).first()
        if not story:
            return jsonify({'success': False, 'error': 'Story not found'}), 404
        
        # Parse and add new test case
        if story.test_cases:
            test_cases = json.loads(story.test_cases)
        else:
            test_cases = []
        
        new_test_case = {
            'step': step,
            'expected': expected,
            'estimate_minutes': estimate_minutes
        }
        
        test_cases.append(new_test_case)
        story.test_cases = json.dumps(test_cases)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Test case added successfully'})
            
    except Exception as e:
        logger.error(f"Error adding test case: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-generator/add-to-jira', methods=['POST'])
def add_bulk_tests_to_jira():
    """Add test cases from a story to Jira"""
    try:
        data = request.get_json()
        story_key = data.get('parent_key') or data.get('story_key')  # Accept both parameter names
        test_cases = data.get('test_cases')
        
        if not all([story_key, test_cases]):
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        
        if not isinstance(test_cases, list) or len(test_cases) == 0:
            return jsonify({'success': False, 'error': 'No test cases provided'}), 400
        
        # Get Jira credentials from session (OAuth)
        jira_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        
        if not jira_token:
            return jsonify({'success': False, 'error': 'Jira authentication required'}), 401
        
        # Get the subtask issue type ID using the same logic as individual generator
        headers = {
            'Authorization': f'Bearer {jira_token}',
            'Accept': 'application/json'
        }
        
        # Get project key from story key
        project_key = story_key.split('-')[0]
        
        # Get the subtask issue type ID and available fields
        meta_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/createmeta?projectKeys={project_key}&issuetypeNames=Sub-task&expand=projects.issuetypes.fields'
        response = requests.get(meta_url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Error fetching issue metadata: {response.text}")
            return jsonify({'success': False, 'error': f'Error fetching issue metadata: {response.status_code}'}), response.status_code
        
        meta_data = response.json()
        subtask_type_id = None
        available_fields = {}
        
        # Extract available fields for subtasks
        for project in meta_data.get('projects', []):
            if project.get('key') == project_key:
                for issue_type in project.get('issuetypes', []):
                    if issue_type.get('subtask', False) or issue_type.get('name') == 'Sub-task':
                        subtask_type_id = issue_type.get('id')
                        available_fields = issue_type.get('fields', {})
                        break
        
        if not subtask_type_id:
            return jsonify({'success': False, 'error': 'Could not find subtask issue type'}), 400
        
        logger.info(f"Available fields for subtasks: {list(available_fields.keys())}")
        
        # Create subtasks using the same logic as individual generator
        created_subtasks = []
        failed_subtasks = []
        create_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue'
        
        for i, test_case in enumerate(test_cases):
            try:
                step = test_case.get('step', '')
                expected = test_case.get('expected', '')
                estimate_minutes = test_case.get('estimate_minutes', 15)
                
                # Create subtask with proper issue type ID
                fields = {
                    'project': {
                        'key': project_key
                    },
                    'parent': {
                        'key': story_key
                    },
                    'issuetype': {
                        'id': subtask_type_id
                    },
                    'summary': f'Test: {step[:80]}' + ('...' if len(step) > 80 else ''),
                    'description': {
                        'type': 'doc',
                        'version': 1,
                        'content': [
                            {
                                'type': 'heading',
                                'attrs': {'level': 3},
                                'content': [{'type': 'text', 'text': 'Test Step'}]
                            },
                            {
                                'type': 'paragraph',
                                'content': [{'type': 'text', 'text': step}]
                            },
                            {
                                'type': 'heading',
                                'attrs': {'level': 3},
                                'content': [{'type': 'text', 'text': 'Expected Result'}]
                            },
                            {
                                'type': 'paragraph',
                                'content': [{'type': 'text', 'text': expected}]
                            },
                            {
                                'type': 'heading',
                                'attrs': {'level': 3},
                                'content': [{'type': 'text', 'text': 'Estimated Time'}]
                            },
                            {
                                'type': 'paragraph',
                                'content': [{'type': 'text', 'text': f'{estimate_minutes} minutes'}]
                            }
                        ]
                    }
                }
                
                # Try to set the original estimate if the timetracking field exists in available fields
                if 'timetracking' in available_fields:
                    fields['timetracking'] = {
                        'originalEstimate': f'{estimate_minutes}m'
                    }
                    logger.info("Added timetracking field to subtask")
                
                # Look for any field that might be related to task type in the available fields
                logger.info("Examining available fields for task type fields")
                
                # Check if customfield_10010 is in available fields - this is often used for task type
                if 'customfield_10010' in available_fields:
                    logger.info("Found customfield_10010 in available fields")
                    field_info = available_fields['customfield_10010']
                    
                    # Check if this field has allowed values
                    if 'allowedValues' in field_info:
                        logger.info(f"customfield_10010 has {len(field_info['allowedValues'])} allowed values")
                        
                        # Try to find a value that matches QA Testing or Test Execution
                        for value in field_info['allowedValues']:
                            value_name = value.get('value', '')
                            logger.info(f"Available value: {value_name}")
                            
                            if 'qa testing' in value_name.lower() or 'test execution' in value_name.lower():
                                if 'id' in value:
                                    fields['customfield_10010'] = {'id': value['id']}
                                    logger.info(f"Setting customfield_10010 to id: {value['id']} (value: {value_name})")
                                else:
                                    fields['customfield_10010'] = {'value': value_name}
                                    logger.info(f"Setting customfield_10010 to value: {value_name}")
                                break
                        else:
                            # If no matching value found, use the first one
                            if field_info['allowedValues']:
                                first_value = field_info['allowedValues'][0]
                                if 'id' in first_value:
                                    fields['customfield_10010'] = {'id': first_value['id']}
                                    logger.info(f"Setting customfield_10010 to first available id: {first_value['id']}")
                                else:
                                    fields['customfield_10010'] = {'value': first_value['value']}
                                    logger.info(f"Setting customfield_10010 to first available value: {first_value['value']}")
                
                # Look for any other fields that might be task type related
                for field_id, field_info in available_fields.items():
                    field_name = field_info.get('name', '').lower()
                    
                    # Skip customfield_10010 as we already handled it
                    if field_id == 'customfield_10010':
                        continue
                        
                    # If this looks like a task type field and has allowed values
                    if ('task' in field_name or 'type' in field_name) and 'allowedValues' in field_info:
                        logger.info(f"Found potential task type field: {field_id} ({field_name})")
                        
                        # Try to find a value that matches QA Testing or Test Execution
                        for value in field_info['allowedValues']:
                            value_name = value.get('value', '')
                            if 'qa testing' in value_name.lower() or 'test execution' in value_name.lower():
                                if 'id' in value:
                                    fields[field_id] = {'id': value['id']}
                                    logger.info(f"Setting {field_id} to id: {value['id']} (value: {value_name})")
                                else:
                                    fields[field_id] = {'value': value_name}
                                    logger.info(f"Setting {field_id} to value: {value_name}")
                                break
                        else:
                            # If no matching value found, use the first one
                            if field_info['allowedValues']:
                                first_value = field_info['allowedValues'][0]
                                if 'id' in first_value:
                                    fields[field_id] = {'id': first_value['id']}
                                    logger.info(f"Setting {field_id} to first available id: {first_value['id']}")
                                else:
                                    fields[field_id] = {'value': first_value['value']}
                                    logger.info(f"Setting {field_id} to first available value: {first_value['value']}")
                
                subtask_data = {'fields': fields}
                
                logger.info(f"Sending payload for subtask creation: {subtask_data}")
                response = requests.post(
                    create_url,
                    headers={
                        'Authorization': f'Bearer {jira_token}',
                        'Content-Type': 'application/json'
                    },
                    json=subtask_data
                )
                
                if response.status_code == 201:
                    issue_data = response.json()
                    created_subtasks.append({
                        'key': issue_data['key'],
                        'url': f"{jira_domain}/browse/{issue_data['key']}"
                    })
                else:
                    logger.error(f"Failed to create subtask {i+1}: {response.status_code} - {response.text}")
                    failed_subtasks.append({
                        'index': i+1,
                        'error': f"HTTP {response.status_code}: {response.text}"
                    })
                
            except Exception as subtask_error:
                logger.error(f"Error creating subtask {i+1}: {str(subtask_error)}")
                failed_subtasks.append({
                    'index': i+1,
                    'error': str(subtask_error)
                })
        
        # Return results
        if created_subtasks:
            message = f"Successfully created {len(created_subtasks)} test subtasks in Jira"
            if failed_subtasks:
                message += f" ({len(failed_subtasks)} failed)"
            
            return jsonify({
                'success': True,
                'created_count': len(created_subtasks),
                'failed_count': len(failed_subtasks),
                'message': message,
                'created_subtasks': created_subtasks,
                'failed_subtasks': failed_subtasks
            })
        else:
            return jsonify({
                'success': False,
                'error': f"Failed to create any subtasks. {len(failed_subtasks)} attempts failed.",
                'failed_subtasks': failed_subtasks
            }), 400
            
    except Exception as e:
        logger.error(f"Error adding tests to Jira: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/jira/fetch-jql-stories', methods=['POST'])
@jira_auth_required
def fetch_jql_stories():
    """Fetch stories from Jira using JQL query for manual test generator"""
    try:
        logger.info("JQL fetch endpoint called")
        data = request.get_json()
        jql_query = data.get('jql')
        
        logger.info(f"JQL query received: {jql_query}")
        
        if not jql_query:
            logger.error("No JQL query provided")
            return jsonify({'success': False, 'error': 'JQL query is required'}), 400
        
        # Get Jira credentials from session
        jira_token = session.get('jira_access_token')
        jira_domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        cloud_id = session.get('jira_cloud_id')
        
        logger.info(f"Jira token exists: {bool(jira_token)}")
        logger.info(f"Cloud ID: {cloud_id}")
        
        if not jira_token:
            logger.error("No Jira token in session")
            return jsonify({'success': False, 'error': 'Jira authentication required'}), 401
        
        # Fetch stories from Jira
        stories = []
        start_at = 0
        max_results = 50
        
        while True:
            logger.info(f"Making Jira API request with JQL: {jql_query}")
            jira_response = requests.get(
                f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search/jql",
                headers={
                    'Authorization': f'Bearer {jira_token}',
                    'Content-Type': 'application/json'
                },
                params={
                    'jql': jql_query,
                    'startAt': start_at,
                    'maxResults': max_results,
                    'fields': 'key,summary,description,issuetype,priority,status,assignee,reporter,labels,components'
                }
            )
            
            logger.info(f"Jira API response status: {jira_response.status_code}")
            
            if jira_response.status_code != 200:
                logger.error(f"Jira API error: {jira_response.text}")
                return jsonify({'success': False, 'error': f'Jira API error: {jira_response.status_code} - {jira_response.text}'}), 400
            
            result = jira_response.json()
            issues = result.get('issues', [])
            
            if not issues:
                break
            
            # Process each issue
            for issue in issues:
                fields = issue.get('fields', {})
                
                # Extract acceptance criteria from description
                description = fields.get('description', {})
                description_text = ''
                acceptance_criteria = ''
                
                if description and isinstance(description, dict):
                    # Handle Atlassian Document Format (ADF)
                    description_text = extract_text_from_adf(description)
                    acceptance_criteria = extract_acceptance_criteria(description_text)
                elif isinstance(description, str):
                    description_text = description
                    acceptance_criteria = extract_acceptance_criteria(description_text)
                
                # Create story object for response
                story_data = {
                    'key': issue['key'],  # Changed from jira_key to key for bulk generator compatibility
                    'jira_key': issue['key'],
                    'title': fields.get('summary', ''),
                    'summary': fields.get('summary', ''),  # Add summary field for bulk generator
                    'description': description_text,
                    'story_type': fields.get('issuetype', {}).get('name', ''),
                    'priority': fields.get('priority', {}).get('name', ''),
                    'status': fields.get('status', {}).get('name', ''),
                    'assignee': fields.get('assignee', {}).get('displayName', '') if fields.get('assignee') else '',
                    'reporter': fields.get('reporter', {}).get('displayName', '') if fields.get('reporter') else '',
                    'labels': fields.get('labels', []),
                    'components': [c.get('name', '') for c in fields.get('components', [])],
                    'acceptance_criteria': acceptance_criteria,
                    'jira_base_url': jira_domain
                }
                stories.append(story_data)
            
            start_at += max_results
            if start_at >= result.get('total', 0):
                break
        
        logger.info(f"Successfully fetched {len(stories)} stories")
        return jsonify({
            'success': True,
            'stories': stories,
            'total_count': len(stories)
        })
        
    except Exception as e:
        logger.error(f"Error fetching JQL stories: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/jira/generate-story-tests', methods=['POST'])
@jira_auth_required
def generate_story_tests():
    """Generate test cases for a single story - for manual test generator"""
    try:
        data = request.get_json()
        story_key = data.get('story_key', '').strip()
        context_name = data.get('context_name', '').strip() or data.get('context', '').strip()
        
        if not story_key:
            return jsonify({'success': False, 'error': 'Story key is required'}), 400
        
        # Context is optional, use empty string if not provided
        if not context_name:
            context_name = None
        
        logger.info(f"Generating test cases for story {story_key} with context {context_name}")
        
        # Get Jira credentials from session
        jira_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not jira_token:
            return jsonify({'success': False, 'error': 'Jira authentication required'}), 401
        
        # Fetch story details from Jira
        jira_response = requests.get(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{story_key}",
            headers={
                'Authorization': f'Bearer {jira_token}',
                'Content-Type': 'application/json'
            },
            params={
                'fields': 'key,summary,description,issuetype,priority,status,assignee,labels,components'
            }
        )
        
        if jira_response.status_code != 200:
            logger.error(f"Failed to fetch story {story_key}: {jira_response.status_code} - {jira_response.text}")
            return jsonify({'success': False, 'error': f'Failed to fetch story from Jira: {jira_response.status_code}'}), 400
        
        issue_data = jira_response.json()
        
        # Create a story object similar to the bulk generator format
        class StoryObject:
            def __init__(self, issue_data):
                self.jira_key = issue_data['key']
                self.title = issue_data['fields']['summary']
                description = issue_data['fields'].get('description', '')
                if isinstance(description, dict):
                    # Handle Atlassian Document Format (ADF)
                    self.description = extract_text_from_adf(description)
                else:
                    self.description = description or ''
                self.acceptance_criteria = extract_acceptance_criteria(self.description)
        
        story_obj = StoryObject(issue_data)
        
        # Generate test cases using the existing function
        test_cases = generate_test_cases_for_story(story_obj, context_name)
        
        logger.info(f"Generated {len(test_cases)} test cases for story {story_key}")
        
        return jsonify({
            'success': True,
            'test_cases': test_cases,
            'story_key': story_key,
            'total_tests': len(test_cases)
        })
        
    except Exception as e:
        logger.error(f"Error generating test cases for story: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def extract_text_from_adf(adf_content):
    """Extract plain text from Atlassian Document Format (ADF)"""
    def extract_text_recursive(node):
        if isinstance(node, dict):
            text = ""
            if node.get('type') == 'text':
                text += node.get('text', '')
            elif 'content' in node:
                for child in node['content']:
                    text += extract_text_recursive(child)
            return text
        elif isinstance(node, list):
            return ''.join(extract_text_recursive(item) for item in node)
        return str(node) if node else ''
    
    return extract_text_recursive(adf_content)

def extract_acceptance_criteria(description_text):
    """Extract acceptance criteria from story description"""
    if not description_text:
        return ''
    
    # Look for common acceptance criteria patterns
    patterns = [
        r'acceptance criteria[:\s]*(.*?)(?=\n\n|\n[A-Z]|$)',
        r'ac[:\s]*(.*?)(?=\n\n|\n[A-Z]|$)',
        r'given.*when.*then.*',
        r'scenario[:\s]*(.*?)(?=\n\n|\n[A-Z]|$)'
    ]
    
    for pattern in patterns:
        import re
        match = re.search(pattern, description_text.lower(), re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return ''

def generate_test_cases_for_story(story, context_name=None):
    """Generate test cases for a single story using AI - matches individual test generator approach"""
    try:
        logger.info(f"Generating test cases for story: {story.jira_key} with context: {context_name}")
        
        # Get context text (same as individual generator)
        context_text = get_context_text(context_name) if context_name else ""
        
        # Build comprehensive scenario from story details
        scenario = f"Story: {story.title or 'No title provided'}\n"
        if story.description:
            scenario += f"Description: {story.description}\n"
        if story.acceptance_criteria:
            scenario += f"Acceptance Criteria: {story.acceptance_criteria}\n"
        
        # Use the EXACT same prompt structure as individual test generator (no fixed count)
        prompt = (
            "[ADVANCED] PROMPT TEMPLATE FOR QA TEST GENERATION (FINAL VERSION)\n"
            "Persona:\n"
            "You are a Senior QA Engineer and a specialist in Software Test Design. You are an expert at applying formal test methodologies to achieve maximum coverage with minimum effort. You will rigorously apply techniques like Equivalence Partitioning (EP), Boundary Value Analysis (BVA), Decision Table Testing, and State Transition Testing where appropriate. Your primary goal is to generate a lean, precise, and highly effective test suite.\n\n"

            "Core Task:\n"
            "Analyze the provided feature specifications. First, mentally identify the relevant test conditions, equivalence classes, and boundary values. Then, generate a comprehensive suite of manual test scenarios based on your analysis.\n\n"

            "Output Requirements:\n"
            "Format: A single, raw JSON array. Do not include markdown formatting or any text outside the JSON structure.\n"
            "JSON Object Structure: Each test case must be a JSON object with the following keys. The category and rationale fields are critical for demonstrating that formal methodologies were used.\n\n"

            "{\n"
            '  "test_case_id": "CATEGORY-001",\n'
            '  "category": "Happy Path | EP | BVA | Decision Table | Negative | UI/UX | State Transition",\n'
            '  "step": "A clear, concise, and repeatable action taken by the user or system.",\n'
            '  "expected": "The specific, verifiable, and observable outcome. Should be unambiguous.",\n'
            '  "rationale": "Briefly explains which test design principle justifies this test case.",\n'
            '  "estimate_minutes": 10\n'
            "}\n\n"

            "Key Definitions:\n"
            "test_case_id: Unique ID (e.g., BVA-001, EP-002).\n"
            "category: The primary test design technique used.\n"
            "step: The action to perform.\n"
            "expected: The exact expected result.\n"
            "rationale: Crucial. A short explanation of the testing theory behind the case.\n"
            "estimate_minutes: Rounded up to the nearest top 10th minute block (see below).\n\n"

            "Estimation Guidelines (estimate_minutes):\n"
            "Assume an experienced tester working in a fast, stable test environment.\n"
            "The estimate covers execution and validation only, not test authoring.\n"
            "Allowed Values: 10, 20 (minimum is 10 minutes)\n"
            "10 mins: All basic to moderate complexity test scenarios including UI checks, single interactions, API calls, and multi-step flows.\n"
            "20 mins: Complex scenarios with dependencies, role/permission checks, data branching, or end-to-end workflows.\n"
            "(Example: Any scenario that would normally take 1-10 mins is set to 10. Scenarios taking 11-20 mins are set to 20.)\n\n"

            "FEATURE CONTEXT (FILL THIS IN)\n"
            "1. Feature Description & User Story:\n"
            f"{scenario}\n"
            "2. UI/UX Details & Visuals:\n"
            "No visual context provided.\n"
            "3. Business Rules & Acceptance Criteria (AC):\n"
            f"{context_text if context_text else 'Extract business rules from the feature description above.'}\n"
            "4. API Endpoint(s) (if applicable):\n"
            "(Include any relevant API information.)\n"
            "5. User Roles & Permissions (if applicable):\n"
            "(Define different user types.)\n"
            "6. Data Validation Rules & Field Boundaries:\n"
            "(Be explicit about boundaries for BVA and classes for EP.)\n\n"

            "Final Instruction:\n"
            "Based on all the context provided, generate the test scenarios. Apply the specified test design techniques to ensure the test suite is efficient and robust. For each test case, populate the rationale field to justify its existence based on those techniques. Ensure estimate_minutes is set to either 10 or 20 (minimum is 10 minutes)."
        )
        
        # Try to use Google AI first (same as individual generator)
        import google.generativeai as genai
        import os
        import re
        import json
        
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            logger.warning(f"GOOGLE_API_KEY not set for {story.jira_key}, using fallback test cases")
            fallback_cases = generate_fallback_test_cases(story)
            logger.info(f"Generated {len(fallback_cases)} fallback test cases for {story.jira_key}")
            return fallback_cases
            
        try:
            genai.configure(api_key=api_key)
            model_name = os.environ.get('GOOGLE_API_MODEL')
            model = genai.GenerativeModel(model_name)
            
            logger.info(f"Calling Google AI API for {story.jira_key} with model {model_name}")
            response = model.generate_content(prompt)
            content = response.text
            logger.info(f"Received AI response for {story.jira_key}, length: {len(content)}")
            
            # Extract JSON array from response - try multiple patterns
            # First try to find JSON array directly
            match = re.search(r'(\[.*\])', content, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1)
                    test_cases = json.loads(json_str)
                    logger.info(f"Successfully generated {len(test_cases)} AI test cases for {story.jira_key}")
                    return test_cases
                except json.JSONDecodeError as json_error:
                    logger.warning(f"JSON decode error for {story.jira_key}: {str(json_error)}")
            
            # If direct extraction fails, try to clean the response
            # Remove markdown formatting and extract JSON
            cleaned_content = re.sub(r'#+\s*[^\n]*\n', '', content)  # Remove headers
            cleaned_content = re.sub(r'\*\*[^*]*\*\*', '', cleaned_content)  # Remove bold
            cleaned_content = re.sub(r'```[^`]*```', '', cleaned_content)  # Remove code blocks
            
            # Try again with cleaned content
            match = re.search(r'(\[.*\])', cleaned_content, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1)
                    test_cases = json.loads(json_str)
                    logger.info(f"Successfully extracted {len(test_cases)} AI test cases after cleaning for {story.jira_key}")
                    return test_cases
                except json.JSONDecodeError as json_error:
                    logger.warning(f"JSON decode error after cleaning for {story.jira_key}: {str(json_error)}")
            
            logger.warning(f"Could not extract JSON from AI response for {story.jira_key}, response: {content[:500]}...")
            fallback_cases = generate_fallback_test_cases(story)
            logger.info(f"Using {len(fallback_cases)} fallback test cases for {story.jira_key}")
            return fallback_cases
                
        except Exception as ai_error:
            logger.error(f"AI API error for {story.jira_key}: {str(ai_error)}")
            fallback_cases = generate_fallback_test_cases(story)
            logger.info(f"Using {len(fallback_cases)} fallback test cases due to AI error for {story.jira_key}")
            return fallback_cases
        
    except Exception as e:
        logger.error(f"Error generating test cases for story {story.jira_key}: {str(e)}")
        fallback_cases = generate_fallback_test_cases(story)
        logger.info(f"Exception fallback: Generated {len(fallback_cases)} fallback test cases for {story.jira_key}")
        return fallback_cases

def generate_fallback_test_cases(story):
    """Generate comprehensive fallback test cases when AI generation fails - 15-20 test cases"""
    title = story.title or "the feature"
    
    return [
        # Happy Path Scenarios (5 test cases)
        {
            "step": f"Verify basic functionality of {title} with valid inputs",
            "expected": "Feature works as described in the story requirements",
            "estimate_minutes": 15
        },
        {
            "step": f"Test successful completion of primary workflow for {title}",
            "expected": "User can complete the main workflow without errors",
            "estimate_minutes": 20
        },
        {
            "step": f"Verify data is saved correctly when using {title}",
            "expected": "All entered data is persisted and retrievable",
            "estimate_minutes": 15
        },
        {
            "step": f"Test navigation flow within {title}",
            "expected": "User can navigate between screens/sections smoothly",
            "estimate_minutes": 10
        },
        {
            "step": f"Verify confirmation messages are displayed for {title}",
            "expected": "Success messages are shown for completed actions",
            "estimate_minutes": 5
        },
        
        # Input Validation Scenarios (4 test cases)
        {
            "step": f"Test required field validation for {title}",
            "expected": "System shows error messages for missing required fields",
            "estimate_minutes": 10
        },
        {
            "step": f"Test input format validation for {title}",
            "expected": "System validates email, phone, date formats and shows appropriate errors",
            "estimate_minutes": 15
        },
        {
            "step": f"Test input length limits for {title}",
            "expected": "System enforces minimum and maximum character limits",
            "estimate_minutes": 10
        },
        {
            "step": f"Test special character handling in {title}",
            "expected": "System handles special characters appropriately without breaking",
            "estimate_minutes": 10
        },
        
        # Edge Cases and Boundary Conditions (4 test cases)
        {
            "step": f"Test {title} with maximum allowed data volume",
            "expected": "System handles large data sets without performance degradation",
            "estimate_minutes": 30
        },
        {
            "step": f"Test {title} with empty/null data scenarios",
            "expected": "System gracefully handles empty states and null values",
            "estimate_minutes": 15
        },
        {
            "step": f"Test concurrent access to {title}",
            "expected": "Multiple users can use the feature simultaneously without conflicts",
            "estimate_minutes": 45
        },
        {
            "step": f"Test {title} performance under load",
            "expected": "Feature responds within acceptable time limits under normal load",
            "estimate_minutes": 30
        },
        
        # Security and Access Control (3 test cases)
        {
            "step": f"Verify user permissions and access control for {title}",
            "expected": "Only authorized users can access the feature based on their roles",
            "estimate_minutes": 20
        },
        {
            "step": f"Test unauthorized access attempts to {title}",
            "expected": "System blocks unauthorized users and shows appropriate error messages",
            "estimate_minutes": 15
        },
        {
            "step": f"Test data privacy and security in {title}",
            "expected": "Sensitive data is protected and not exposed inappropriately",
            "estimate_minutes": 25
        },
        
        # Error Handling and Recovery (4 test cases)
        {
            "step": f"Test error handling and recovery for {title}",
            "expected": "System provides clear error messages and recovery options",
            "estimate_minutes": 20
        },
        {
            "step": f"Test {title} behavior during system failures",
            "expected": "Feature degrades gracefully and maintains data integrity",
            "estimate_minutes": 30
        },
        {
            "step": f"Test undo/rollback functionality in {title}",
            "expected": "Users can reverse actions when undo functionality is available",
            "estimate_minutes": 15
        },
        {
            "step": f"Test {title} recovery after network interruption",
            "expected": "Feature handles network issues and recovers appropriately",
            "estimate_minutes": 25
        }
    ]

@app.route('/auto-healing-recorder')
@jira_auth_required
def auto_healing_recorder_redirect():
    """Deprecated: redirect to V2 Auto-Healing Test Recorder"""
    return redirect(url_for('auto_healing_recorder_v2'))

@app.route('/api/auto-healing/start-codegen', methods=['POST'])
@jira_auth_required
def start_auto_healing_codegen():
    """Deprecated: use /api/recorder-v2/start-session"""
    return jsonify({
        'success': False,
        'error': 'Legacy endpoint removed. Use /api/recorder-v2/start-session.'
    }), 410

# Old route removed - replaced by V2 endpoints

# Old test browser route removed - replaced by V2 endpoints

@app.route('/api/auto-healing/check-playwright', methods=['GET'])
@jira_auth_required
def check_playwright_status():
    """Deprecated: use V2 Recorder commands and session endpoints"""
    return jsonify({
        'success': False,
        'error': 'Legacy endpoint removed. Use /api/recorder-v2/* endpoints and MCP commands shown in the UI.'
    }), 410

@app.route('/api/auto-healing/close-browser', methods=['POST'])
@jira_auth_required
def close_auto_healing_browser():
    """Deprecated: use /api/recorder-v2/close-session"""
    return jsonify({
        'success': False,
        'error': 'Legacy endpoint removed. Use /api/recorder-v2/close-session.'
    }), 410

@app.route('/api/auto-healing/session-status', methods=['GET'])
@jira_auth_required
def get_auto_healing_session_status():
    """Deprecated: use /api/recorder-v2/session-status"""
    return jsonify({
        'success': False,
        'error': 'Legacy endpoint removed. Use /api/recorder-v2/session-status.'
    }), 410

# Old debug route removed - replaced by V2 endpoints

# Old record action route removed - replaced by V2 endpoints

# Old generate test route removed - replaced by V2 endpoints

def generate_playwright_test_code(actions, url, session_id):
    """Generate Playwright test code with auto-healing locators"""
    test_name = f'AutoHealingTest_{session_id[:8]}'
    timestamp = datetime.now().isoformat()
    
    test_code = f'''import {{ test, expect }} from '@playwright/test';

/**
 * Auto-Healing Test Generated by Co-Test
 * Generated: {timestamp}
 * Target URL: {url}
 * Session ID: {session_id}
 * Actions Recorded: {len(actions)}
 */

class AutoHealingLocator {{
    constructor(page, strategies) {{
        this.page = page;
        this.strategies = strategies;
    }}

    async locate() {{
        for (const strategy of this.strategies) {{
            try {{
                let locator;
                
                // Handle different locator types
                switch (strategy.strategy) {{
                    case 'id':
                        locator = this.page.locator(strategy.locator);
                        break;
                    case 'data-attribute':
                        locator = this.page.locator(strategy.locator);
                        break;
                    case 'role':
                        // Extract role and name from playwright command
                        const roleMatch = strategy.playwright.match(/get_by_role\\('([^']+)'(?:,\s*{{\s*name:\s*'([^']+)'\s*}})?\\)/);
                        if (roleMatch) {{
                            const [, role, name] = roleMatch;
                            locator = name ? 
                                this.page.getByRole(role, {{ name }}) : 
                                this.page.getByRole(role);
                        }} else {{
                            locator = this.page.locator(strategy.locator);
                        }}
                        break;
                    case 'text':
                        const textMatch = strategy.playwright.match(/get_by_text\\('([^']+)'\\)/);
                        if (textMatch) {{
                            locator = this.page.getByText(textMatch[1]);
                        }} else {{
                            locator = this.page.locator(strategy.locator);
                        }}
                        break;
                    default:
                        locator = this.page.locator(strategy.locator);
                }}
                
                await locator.waitFor({{ timeout: 5000 }});
                console.log(`✅ Located element using ${{strategy.strategy}}: ${{strategy.locator}}`);
                return locator;
            }} catch (error) {{
                console.log(`❌ Failed to locate using ${{strategy.strategy}}: ${{strategy.locator}}`);
                continue;
            }}
        }}
        throw new Error('All locator strategies failed');
    }}
}}

test('{test_name}', async ({{ page }}) => {{
    // Navigate to the target URL
    await page.goto('{url}');
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
'''

    # Generate test steps for each recorded action
    for index, action in enumerate(actions):
        test_code += f'''
    // Step {index + 1}: {action['type']} action
    {{
        const strategies = {json.dumps(action['locators'], indent=8)};
        const autoLocator = new AutoHealingLocator(page, strategies);
        const element = await autoLocator.locate();
        
'''

        action_type = action['type']
        value = action.get('value', '')
        
        if action_type == 'click':
            test_code += f'        await element.click();\n'
        elif action_type == 'fill':
            test_code += f'        await element.fill(\'{value}\');\n'
        elif action_type == 'type':
            test_code += f'        await element.type(\'{value}\');\n'
        elif action_type == 'select':
            test_code += f'        await element.selectOption(\'{value}\');\n'
        else:
            test_code += f'        // {action_type} action\n'

        test_code += '    }\n'

    test_code += '''
    // Add assertions as needed
    // await expect(page).toHaveURL(/expected-url/);
    // await expect(page.locator('selector')).toBeVisible();
});
'''

    return test_code

@app.route('/api/auto-healing/generate-locators', methods=['POST'])
@jira_auth_required
def generate_auto_healing_locators():
    """Generate multiple locator strategies for an element"""
    try:
        data = request.get_json()
        element_info = data.get('element', {})
        
        # Generate multiple locator strategies
        locators = generate_multiple_locators(element_info)
        
        return jsonify({
            'success': True,
            'locators': locators
        })
        
    except Exception as e:
        logger.error(f"Error generating locators: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def generate_multiple_locators(element_info):
    """Generate multiple locator strategies for robust element identification"""
    locators = []
    
    # Strategy 1: ID-based (highest priority)
    if element_info.get('id'):
        locators.append({
            'strategy': 'id',
            'locator': f"#{element_info['id']}",
            'playwright': f"page.locator('#{element_info['id']}')",
            'priority': 1,
            'description': 'ID-based locator (most reliable)'
        })
    
    # Strategy 2: Data attributes
    for attr in ['data-testid', 'data-test', 'data-cy']:
        if element_info.get(attr):
            locators.append({
                'strategy': 'data-attribute',
                'locator': f"[{attr}='{element_info[attr]}']",
                'playwright': f"page.locator('[{attr}=\"{element_info[attr]}\"]')",
                'priority': 2,
                'description': f'{attr} attribute locator'
            })
    
    # Strategy 3: Role-based (accessibility)
    if element_info.get('role'):
        locators.append({
            'strategy': 'role',
            'locator': f"role={element_info['role']}",
            'playwright': f"page.get_by_role('{element_info['role']}')",
            'priority': 3,
            'description': 'Role-based locator (accessibility-friendly)'
        })
    
    # Strategy 4: Text-based
    if element_info.get('text'):
        locators.append({
            'strategy': 'text',
            'locator': f"text={element_info['text']}",
            'playwright': f"page.get_by_text('{element_info['text']}')",
            'priority': 4,
            'description': 'Text-based locator'
        })
    
    # Strategy 5: CSS class combination
    if element_info.get('classes'):
        class_selector = '.' + '.'.join(element_info['classes'])
        locators.append({
            'strategy': 'css-class',
            'locator': class_selector,
            'playwright': f"page.locator('{class_selector}')",
            'priority': 5,
            'description': 'CSS class-based locator'
        })
    
    # Strategy 6: XPath (last resort)
    if element_info.get('xpath'):
        locators.append({
            'strategy': 'xpath',
            'locator': element_info['xpath'],
            'playwright': f"page.locator('xpath={element_info['xpath']}')",
            'priority': 6,
            'description': 'XPath locator (fallback)'
        })
    
    # Sort by priority
    locators.sort(key=lambda x: x['priority'])
    
    return locators

# =============================================
# SIMPLIFIED AUTO-HEALING TEST RECORDER V2 ENDPOINTS
# =============================================

@app.route('/api/recorder-v2/start-session', methods=['POST'])
@jira_auth_required
def start_recorder_v2_session():
    """Start a new auto-healing recording session V2"""
    try:
        data = request.get_json()
        url = data.get('url', 'https://example.com')
        
        # Generate unique session ID
        session_id = f"auto_healing_{int(datetime.now().timestamp())}"
        
        # Start recording session
        success, message = auto_healing_recorder.start_session(session_id, url)
        
        if success:
            # Store session in Flask session for persistence
            session['auto_healing_session_id'] = session_id
            session['auto_healing_url'] = url
            
            return jsonify({
                'success': True,
                'session_id': session_id,
                'url': url,
                'message': message,
                'mcp_commands': {
                    'navigate': f'mcp0_playwright_navigate --url "{url}" --headless false',
                    'start_codegen': 'mcp0_start_codegen_session --outputPath "./tests" --testNamePrefix "AutoHealing"',
                    'screenshot': 'mcp0_playwright_screenshot --name "recording-start"'
                }
            })
        else:
            return jsonify({'success': False, 'error': message}), 500
        
    except Exception as e:
        logger.error(f"Error starting auto-healing session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recorder-v2/launch-codegen', methods=['POST'])
@jira_auth_required
def launch_recorder_v2_codegen():
    """Launch Playwright codegen (headed) for the active session URL"""
    try:
        data = request.get_json() or {}
        url = data.get('url') or session.get('auto_healing_url') or 'https://example.com'
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'No active session found'}), 400

        # Prepare output path for codegen file
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'codegen-output')
        os.makedirs(output_dir, exist_ok=True)
        output_file = f"codegen_{session_id}_{int(time.time())}.spec.ts"
        output_path = os.path.join(output_dir, output_file)

        # Launch Playwright codegen as a subprocess
        # Requires Playwright to be installed (Python) and browsers installed.
        # Try to use --output to save the generated script automatically.
        cmd = [
            "playwright", "codegen",
            "--target", "javascript",
            "--output", output_path,
            url
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            # Fallback to python module invocation
            proc = subprocess.Popen([
                "python", "-m", "playwright", "codegen",
                "--target", "javascript",
                "--output", output_path,
                url
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Save pid into session data
        sess = auto_healing_recorder.get_session(session_id) or {}
        sess['codegen_pid'] = proc.pid
        sess['codegen_output_path'] = output_path
        auto_healing_recorder.active_sessions[session_id] = sess

        logger.info(f"Launched Playwright codegen (pid={proc.pid}) for session {session_id} on {url}")
        return jsonify({
            'success': True,
            'session_id': session_id,
            'url': url,
            'pid': proc.pid,
            'output_path': output_path
        })
    except Exception as e:
        logger.error(f"Error launching codegen: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recorder-v2/stop-codegen', methods=['POST'])
@jira_auth_required
def stop_recorder_v2_codegen():
    """Stop Playwright codegen process for the active session"""
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'No active session found'}), 400

        sess = auto_healing_recorder.get_session(session_id) or {}
        pid = sess.get('codegen_pid')
        if not pid:
            return jsonify({'success': False, 'error': 'No codegen process found for this session'}), 400

        # Attempt to terminate process (Windows-friendly)
        try:
            if os.name == 'nt':
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
        except Exception as kill_err:
            logger.warning(f"Failed to terminate codegen pid={pid}: {kill_err}")

        # Attempt to read generated code if available
        code = None
        output_path = sess.get('codegen_output_path')
        try:
            if output_path and os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8') as f:
                    code = f.read()
        except Exception as read_err:
            logger.warning(f"Could not read codegen output at {output_path}: {read_err}")

        # Cleanup
        sess.pop('codegen_pid', None)
        # keep output path for later viewing
        auto_healing_recorder.active_sessions[session_id] = sess
        logger.info(f"Stopped Playwright codegen (pid={pid}) for session {session_id}")
        return jsonify({'success': True, 'session_id': session_id, 'output_path': output_path, 'codegen_code': code})
    except Exception as e:
        logger.error(f"Error stopping codegen: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# -------- Codegen Import (convert to auto-healing actions) ---------
def _extract_element_data_from_target(target: str):
    """Parse a Playwright target expression into element_data for auto-healing.
    Supports getByRole, getByText, getByPlaceholder, getByTestId, locator, and direct selectors.
    """
    try:
        # Normalize whitespace
        t = re.sub(r"\s+", " ", target.strip())

        # getByRole('button', { name: 'Sign in' })
        m = re.search(r"getByRole\(\s*(['\"]) (?P<role>.+?) \1 \s*(?:,\s*\{[^}]*name\s*:\s*(['\"]) (?P<name>.+?) \3 [^}]*\})?\s*\)", t, re.VERBOSE)
        if m:
            role = m.group('role')
            name = m.group('name') if 'name' in m.groupdict() else None
            el = {'role': role}
            if name:
                el['text'] = name
            return el

        # getByText('Text')
        m = re.search(r"getByText\(\s*(['\"]) (?P<text>.*?) \1 \s*\)", t, re.VERBOSE)
        if m:
            return {'text': m.group('text')}

        # getByPlaceholder('Placeholder')
        m = re.search(r"getByPlaceholder\(\s*(['\"]) (?P<ph>.*?) \1 \s*\)", t, re.VERBOSE)
        if m:
            return {'placeholder': m.group('ph')}

        # getByTestId('tid')
        m = re.search(r"getByTestId\(\s*(['\"]) (?P<tid>.*?) \1 \s*\)", t, re.VERBOSE)
        if m:
            return {'data-testid': m.group('tid')}

        # locator('...') or direct selector string
        m = re.search(r"locator\(\s*(['\"]) (?P<sel>.*?) \1 \s*\)", t, re.VERBOSE)
        if not m:
            # direct selector variant (from page.click('...'))
            m = re.search(r"^(['\"]) (?P<sel>.*?) \1$", t, re.VERBOSE)
        if m:
            sel = m.group('sel')
            if sel.startswith('xpath=') or sel.startswith('//'):
                return {'xpath': sel.replace('xpath=', '')}
            if sel.startswith('text='):
                return {'text': sel[len('text='):]}
            # Heuristics for CSS
            if sel.startswith('#'):
                return {'id': sel[1:]}
            if sel.startswith('.'):
                return {'class': sel[1:].replace('.', ' ')}
            return {'css_selector': sel}

        return {}
    except Exception as e:
        logger.warning(f"Failed to extract element data from target '{target}': {e}")
        return {}

def parse_codegen_actions(code_text: str):
    """Parse Playwright codegen script into a list of actions consumable by AutoHealingRecorder."""
    actions = []
    if not code_text:
        return actions

    # Match typical patterns: await page.getByRole(...).click('..'); etc.
    action_re = re.compile(r"await\s+page\.(?P<target>getByRole\(.*?\)|getByText\(.*?\)|getByPlaceholder\(.*?\)|getByTestId\(.*?\)|locator\(.*?\))\.(?P<method>click|fill|type|check|uncheck|selectOption)\((?P<args>.*?)\)\s*;", re.DOTALL)
    direct_re = re.compile(r"await\s+page\.(?P<method>click|fill|type|check|uncheck|selectOption)\(\s*(['\"]) (?P<sel>.*?) \2 (?:\s*,\s*(?P<args>[^\)]*))?\)\s*;", re.VERBOSE | re.DOTALL)

    for m in action_re.finditer(code_text):
        target = m.group('target')
        method = m.group('method')
        args = m.group('args') or ''

        el = _extract_element_data_from_target(target)
        action_type = {
            'click': 'click',
            'fill': 'fill',
            'type': 'fill',
            'check': 'check',
            'uncheck': 'uncheck',
            'selectOption': 'select'
        }[method]

        additional = {}
        if action_type in ('fill', 'select'):
            mval = re.search(r"(['\"]) (?P<val>.*?) \1", args, re.VERBOSE)
            if mval:
                additional['value'] = mval.group('val')

        actions.append({'type': action_type, 'element_data': el, 'additional_data': additional})

    for m in direct_re.finditer(code_text):
        method = m.group('method')
        sel = m.group('sel')
        args = m.group('args') or ''
        el = _extract_element_data_from_target(sel)
        action_type = {
            'click': 'click',
            'fill': 'fill',
            'type': 'fill',
            'check': 'check',
            'uncheck': 'uncheck',
            'selectOption': 'select'
        }[method]
        additional = {}
        if action_type in ('fill', 'select'):
            mval = re.search(r"(['\"]) (?P<val>.*?) \1", args, re.VERBOSE)
            if mval:
                additional['value'] = mval.group('val')
        actions.append({'type': action_type, 'element_data': el, 'additional_data': additional})

    return actions

@app.route('/api/recorder-v2/import-codegen', methods=['POST'])
@jira_auth_required
def import_recorder_v2_codegen():
    """Import Playwright codegen text, convert to auto-healing actions, and add to the active session."""
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        code = data.get('code', '')
        if not session_id:
            return jsonify({'success': False, 'error': 'No active session found'}), 400
        if not code:
            return jsonify({'success': False, 'error': 'No code provided'}), 400

        parsed = parse_codegen_actions(code)
        imported = []
        for a in parsed:
            action = auto_healing_recorder.record_action(
                session_id,
                a['type'],
                a.get('element_data') or {},
                a.get('additional_data') or {}
            )
            imported.append(action)

        return jsonify({
            'success': True,
            'imported_count': len(imported),
            'actions': imported[-25:]  # return last 25 imported actions as preview
        })
    except Exception as e:
        logger.error(f"Error importing codegen: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recorder-v2/record-action', methods=['POST'])
@jira_auth_required
def record_recorder_v2_action():
    """Record an action with auto-healing locators V2"""
    try:
        data = request.get_json()
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        action_type = data.get('action_type', 'click')
        element_data = data.get('element_data', {})
        additional_data = data.get('additional_data', {})
        
        if not session_id:
            return jsonify({'success': False, 'error': 'No active session found'}), 400
        
        # Record the action
        action = auto_healing_recorder.record_action(session_id, action_type, element_data, additional_data)
        
        return jsonify({
            'success': True,
            'action': action,
            'message': f'Recorded {action_type} action successfully',
            'locators_generated': len(action['locators'])
        })
        
    except Exception as e:
        logger.error(f"Error recording action: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recorder-v2/generate-test', methods=['POST'])
@jira_auth_required
def generate_recorder_v2_test():
    """Generate Playwright test code with auto-healing locators V2"""
    try:
        data = request.get_json()
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'No active session found'}), 400
        
        # Generate test code
        test_code, message = auto_healing_recorder.generate_test_code(session_id)
        
        if test_code:
            return jsonify({
                'success': True,
                'test_code': test_code,
                'message': message,
                'session_id': session_id
            })
        else:
            return jsonify({'success': False, 'error': message}), 400
        
    except Exception as e:
        logger.error(f"Error generating test: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recorder-v2/session-status', methods=['GET'])
@jira_auth_required
def get_recorder_v2_session_status():
    """Get current session status and recorded actions V2"""
    try:
        session_id = session.get('auto_healing_session_id')
        
        if not session_id:
            return jsonify({
                'success': True,
                'session_active': False,
                'message': 'No active session'
            })
        
        session_data = auto_healing_recorder.get_session(session_id)
        actions = auto_healing_recorder.recorded_actions.get(session_id, [])
        
        return jsonify({
            'success': True,
            'session_active': True,
            'session_id': session_id,
            'session_data': session_data,
            'actions_count': len(actions),
            'actions': actions[-5:] if actions else []  # Last 5 actions
        })
        
    except Exception as e:
        logger.error(f"Error getting session status: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recorder-v2/close-session', methods=['POST'])
@jira_auth_required
def close_recorder_v2_session():
    """Close the current recording session V2"""
    try:
        data = request.get_json()
        session_id = data.get('session_id') or session.get('auto_healing_session_id')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'No active session found'}), 400
        
        success, message = auto_healing_recorder.close_session(session_id)
        
        if success:
            # Clear Flask session
            session.pop('auto_healing_session_id', None)
            session.pop('auto_healing_url', None)
            
            return jsonify({
                'success': True,
                'message': message
            })
        else:
            return jsonify({'success': False, 'error': message}), 400
        
    except Exception as e:
        logger.error(f"Error closing session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/auto-healing-recorder-v2')
@jira_auth_required
def auto_healing_recorder_v2():
    """Simplified Auto-Healing Test Recorder V2"""
    return render_template('auto-healing-recorder-v2.html', active_tab='auto-healing')

# Create tables for bug builder
with app.app_context():
    db.create_all()

def generate_steps_from_text(steps_text):
    """Helper function to generate structured steps from plain text using AI"""
    try:
        # Use AI to structure the steps
        prompt = f"""You are a QA expert. Convert the following bug reproduction notes into clear, numbered steps.

Input text:
{steps_text}

Requirements:
- Create clear, actionable steps
- Number them sequentially
- Be specific and concise
- Each step should be one action
- Return ONLY the steps, one per line, without numbering (I'll add numbers)

Example output format:
Navigate to the login page
Enter username in the email field
Enter password in the password field
Click the Login button
Observe the error message

Now convert the input text above:"""

        # Use Gemini API
        model_name = os.environ.get('GOOGLE_API_MODEL', 'gemini-1.5-flash-latest')
        model = genai.GenerativeModel(model_name)
        
        response = model.generate_content(prompt)
        ai_response = response.text.strip()
        
        # Parse steps from AI response
        steps = []
        for line in ai_response.split('\n'):
            line = line.strip()
            if line:
                # Remove any existing numbering
                line = line.lstrip('0123456789.-) ')
                if line:
                    steps.append(line)
        
        if not steps:
            # Fallback: split by newlines
            steps = [s.strip() for s in steps_text.split('\n') if s.strip()]
        
        return jsonify({
            'success': True,
            'steps': steps,  # No limit on steps
            'raw_response': ai_response
        })
        
    except Exception as e:
        logger.error(f"Error generating steps from text: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        # Fallback: return original text split by lines
        steps = [s.strip() for s in steps_text.split('\n') if s.strip()]
        return jsonify({
            'success': True,
            'steps': steps,  # No limit on steps
            'error': str(e)
        })

@app.route('/api/bug-builder/generate-steps', methods=['POST'])
@jira_auth_required
@llm_rate_limit
def generate_steps_from_video():
    """Generate steps from video OR text using AI analysis"""
    try:
        data = request.get_json()
        
        # Check if this is text-based input (new feature)
        steps_text = data.get('steps_text')
        if steps_text:
            return generate_steps_from_text(steps_text)
        
        # Otherwise, process as video (existing feature)
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID or steps_text required'}), 400
        
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Check if video exists
        if not session.video_path or not os.path.exists(session.video_path):
            return jsonify({'success': False, 'error': 'Video not found for analysis'}), 404
        
        # Prepare analysis metadata holders (used in success and fallback paths)
        frames = []
        frame_info = []
        last_ai_response = None
        analysis_error = None
        
        # Process video and extract frames for AI analysis
        try:
            logger.info(f"Starting video analysis for session {session_id}")
            logger.info(f"Video path: {session.video_path}")
            
            # Check if video file actually exists and is readable
            if not os.path.exists(session.video_path):
                logger.error(f"Video file does not exist: {session.video_path}")
                raise Exception(f"Video file not found: {session.video_path}")
            
            file_size = os.path.getsize(session.video_path)
            logger.info(f"Video file size: {file_size} bytes")
            
            if file_size == 0:
                logger.error("Video file is empty")
                raise Exception("Video file is empty")
            
            # Extract frames from video
            logger.info("Attempting to extract frames from video...")
            frames = extract_video_frames(session.video_path)
            
            if not frames:
                logger.error("Could not extract any frames from video")
                raise Exception("Could not extract frames from video - check video format and OpenCV installation")
            
            logger.info(f"Successfully extracted {len(frames)} frames from video")
            frame_info = [
                {
                    'index': frame.get('frame_index'),
                    'timestamp': round(frame.get('timestamp', 0.0), 2)
                }
                for frame in frames
            ]
            used_fallback = any(frame.get('source') == 'imageio' for frame in frames)
            
            # Parse action log from session (if available)
            action_log = []
            if session.action_logs:
                try:
                    import json
                    action_log = json.loads(session.action_logs)
                    logger.info(f"✅ Loaded {len(action_log)} actions from session - will enhance AI analysis")
                except Exception as parse_error:
                    logger.error(f"Error parsing action log: {parse_error}")
                    action_log = []
            
            # Analyze frames using Gemini Vision with action context
            logger.info("Sending frames and action log to Gemini Vision for analysis...")
            analysis_result = analyze_video_frames_with_ai(frames, action_log)
            if isinstance(analysis_result, dict):
                steps = analysis_result.get('steps') or []
                last_ai_response = analysis_result.get('raw_response')
                analysis_error = analysis_result.get('error')
            else:
                steps = analysis_result or []
            
            if steps and len(steps) > 0:
                logger.info(f"Successfully generated {len(steps)} steps from video analysis")
                logger.info(f"Generated steps: {steps}")
                return jsonify({
                    'success': True,
                    'steps': steps,
                    'analysis_method': 'video_frame_analysis',
                    'frames_analyzed': len(frames),
                    'frame_info': frame_info,
                    'analysis_details': {
                        'ai_parse_method': analysis_result.get('parse_method') if isinstance(analysis_result, dict) else 'unknown',
                        'used_fallback_frames': used_fallback
                    }
                })
            else:
                logger.warning("AI analysis returned empty or invalid steps")
                raise Exception(analysis_error or "AI could not generate meaningful steps from video frames")
                
        except Exception as video_error:
            logger.error(f"Video analysis failed with error: {str(video_error)}")
            logger.error(f"Error type: {type(video_error).__name__}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            
            # Fallback to intelligent default steps with context
            logger.info("Using fallback step generation due to video analysis failure")
            steps = [
                "Open the web application in a browser",
                "Navigate to the main feature or page where the issue occurs", 
                "Perform the primary user action that triggers the bug",
                "Interact with any relevant UI elements or forms",
                "Complete the workflow or process being tested",
                "Observe the unexpected behavior or error that occurred"
            ]
            
            return jsonify({
                'success': True,
                'steps': steps,
                'analysis_method': 'fallback',
                'error_reason': str(video_error),
                'note': 'Steps generated using fallback analysis due to video processing limitations',
                'frame_info': frame_info,
                'debug_info': {
                    'analysis_error': analysis_error,
                    'ai_response_excerpt': (last_ai_response[:300] if last_ai_response else None)
                }
            })
        
    except Exception as e:
        logger.error(f"Error generating steps: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def extract_video_frames(video_path, max_frames=10):
    """Extract frames from video for AI analysis"""
    try:
        logger.info(f"Starting frame extraction from: {video_path}")

        import base64
        from PIL import Image
        import io

        try:
            import cv2
        except ImportError:
            cv2 = None
            logger.warning("OpenCV not available; will rely on imageio fallback")

        frames = []
        frame_source = 'opencv'
        fps = 0.0

        if cv2 is not None:
            logger.info("Opening video file with OpenCV...")
            cap = cv2.VideoCapture(video_path)

            if cap.isOpened():
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                duration = total_frames / fps if fps and fps > 0 else 0
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                logger.info("Video properties (OpenCV):")
                logger.info(f"  - Total frames: {total_frames}")
                logger.info(f"  - FPS: {fps}")
                logger.info(f"  - Duration: {duration:.2f}s")
                logger.info(f"  - Resolution: {width}x{height}")

                if total_frames == 0:
                    logger.error("Video has 0 frames - possibly corrupted or unsupported format")
                else:
                    if total_frames <= max_frames:
                        frame_indices = list(range(0, total_frames))
                    else:
                        step = max(1, total_frames // max_frames)
                        frame_indices = list(range(0, total_frames, step))
                    frame_indices = frame_indices[:max_frames]
                    logger.info(f"Will extract frames at indices: {frame_indices}")

                    opencv_frames = []
                    for index, frame_idx in enumerate(frame_indices):
                        logger.debug(f"Extracting frame {index+1}/{len(frame_indices)} at index {frame_idx}")
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                        ret, frame = cap.read()

                        if ret and frame is not None:
                            try:
                                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                pil_image = Image.fromarray(frame_rgb)
                                max_size = 1024
                                original_size = pil_image.size
                                if pil_image.width > max_size or pil_image.height > max_size:
                                    pil_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                                    logger.debug(f"Resized frame from {original_size} to {pil_image.size}")
                                buffer = io.BytesIO()
                                pil_image.save(buffer, format='JPEG', quality=85)
                                img_base64 = base64.b64encode(buffer.getvalue()).decode()
                                opencv_frames.append({
                                    'frame_index': frame_idx,
                                    'timestamp': frame_idx / fps if fps and fps > 0 else 0,
                                    'image_data': img_base64,
                                    'size': pil_image.size,
                                    'source': 'opencv'
                                })
                                logger.debug(f"Successfully processed frame {frame_idx}")
                            except Exception as frame_error:
                                logger.error(f"Error processing frame {frame_idx}: {frame_error}")
                        else:
                            logger.warning(f"Could not read frame at index {frame_idx}")

                    cap.release()

                    required_frames = min(max_frames, 3)
                    if len(opencv_frames) < required_frames and frame_indices:
                        logger.warning("OpenCV random seek produced only %s/%s frames; retrying sequential capture", len(opencv_frames), len(frame_indices))
                        sequential_frames = []
                        cap_seq = cv2.VideoCapture(video_path)
                        if cap_seq.isOpened():
                            frame_source = 'opencv-sequential'
                            target_iter = iter(frame_indices)
                            target_idx = next(target_iter, None)
                            current_idx = 0
                            while target_idx is not None:
                                ret, frame = cap_seq.read()
                                if not ret or frame is None:
                                    logger.warning(f"Sequential read failed at frame {current_idx}")
                                    break
                                if current_idx == target_idx:
                                    try:
                                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                        pil_image = Image.fromarray(frame_rgb)
                                        max_size = 1024
                                        original_size = pil_image.size
                                        if pil_image.width > max_size or pil_image.height > max_size:
                                            pil_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                                            logger.debug(f"Sequential resized frame from {original_size} to {pil_image.size}")
                                        buffer = io.BytesIO()
                                        pil_image.save(buffer, format='JPEG', quality=85)
                                        img_base64 = base64.b64encode(buffer.getvalue()).decode()
                                        sequential_frames.append({
                                            'frame_index': target_idx,
                                            'timestamp': target_idx / fps if fps and fps > 0 else current_idx / (fps or 1),
                                            'image_data': img_base64,
                                            'size': pil_image.size,
                                            'source': 'opencv-sequential'
                                        })
                                        logger.debug(f"Sequentially captured frame {target_idx}")
                                    except Exception as seq_error:
                                        logger.error(f"Error processing sequential frame {target_idx}: {seq_error}")
                                    target_idx = next(target_iter, None)
                                current_idx += 1
                            cap_seq.release()
                            opencv_frames = sequential_frames if sequential_frames else opencv_frames
                        else:
                            logger.error("OpenCV sequential fallback could not reopen the video file")

                    frames.extend(opencv_frames)

                    if len(frames) < required_frames:
                        logger.warning("OpenCV extraction yielded only %s frames (<%s required); will rely on imageio fallback", len(frames), required_frames)
                        frames = []
                        frame_source = 'opencv-insufficient'
            else:
                logger.error(f"OpenCV could not open video file: {video_path}")
        else:
            logger.info("Skipping OpenCV extraction because cv2 is unavailable")

        # Fallback to imageio/ffmpeg if needed
        if not frames:
            logger.info("Attempting imageio fallback for frame extraction")
            try:
                import imageio

                reader = imageio.get_reader(video_path, format='ffmpeg')
                metadata = reader.get_meta_data()
                fps = metadata.get('fps', fps or 0.0)
                total_frames = metadata.get('nframes')
                frame_source = 'imageio'
                
                logger.info(f"imageio metadata: fps={fps}, nframes={total_frames}")

                # Calculate sampling step to only decode needed frames
                # Estimate ~1000 frames if metadata doesn't provide count (common for VP8/WebM)
                estimated_total = int(total_frames) if total_frames and total_frames != float('inf') else 1000
                step = max(1, estimated_total // max_frames)
                logger.info(f"imageio sampling: will process every {step}th frame, targeting {max_frames} frames")

                try:
                    frame_count = 0
                    for idx, frame_array in enumerate(reader):
                        # Only process frames at the sampling interval
                        if idx % step == 0:
                            try:
                                pil_image = Image.fromarray(frame_array)
                                max_size = 1024
                                original_size = pil_image.size
                                if pil_image.width > max_size or pil_image.height > max_size:
                                    pil_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                                    logger.debug(f"Fallback resized frame from {original_size} to {pil_image.size}")
                                buffer = io.BytesIO()
                                pil_image.save(buffer, format='JPEG', quality=85)
                                img_base64 = base64.b64encode(buffer.getvalue()).decode()
                                frame_timestamp = idx / fps if fps and fps > 0 else idx / 30.0
                                frames.append({
                                    'frame_index': idx,
                                    'timestamp': frame_timestamp,
                                    'image_data': img_base64,
                                    'size': pil_image.size,
                                    'source': 'imageio'
                                })
                                frame_count += 1
                                logger.debug(f"Processed imageio frame {idx} ({frame_count}/{max_frames})")
                                
                                # Stop after collecting enough frames
                                if frame_count >= max_frames:
                                    logger.info(f"Collected {frame_count} frames, stopping imageio extraction")
                                    break
                            except Exception as fallback_frame_error:
                                logger.error(f"Error processing fallback frame {idx}: {fallback_frame_error}")
                finally:
                    try:
                        reader.close()
                    except Exception:
                        pass
                    logger.info(f"imageio extraction complete: collected {len(frames)} frames")

                if not frames:
                    logger.error("imageio fallback found 0 frames")
            except ImportError as fallback_import_error:
                logger.error(f"imageio fallback unavailable: {fallback_import_error}")
            except Exception as fallback_error:
                logger.error(f"imageio fallback failed: {fallback_error}")
                import traceback
                logger.error(f"imageio fallback traceback: {traceback.format_exc()}")

        if frames:
            logger.info(f"Successfully extracted {len(frames)} frames for analysis using {frame_source}")
            frame_timestamps = ["{:.2f}s".format(frame.get('timestamp', 0.0)) for frame in frames]
            logger.info(f"Frame timestamps: {frame_timestamps}")
        else:
            logger.error("No frames were successfully extracted from the video")

        return frames

    except Exception as e:
        logger.error(f"Error extracting video frames: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return []

def analyze_video_frames_with_ai(frames, action_log=None):
    """Analyze video frames using Gemini Vision to generate steps
    
    Args:
        frames: List of frame dicts with image_data, timestamp, etc.
        action_log: Optional list of user actions (clicks, inputs, navigation) captured during recording
    """
    try:
        logger.info("Starting AI analysis of video frames")
        
        # Check API key first
        api_key = os.environ.get('GOOGLE_API_KEY')
        if not api_key:
            logger.error("GOOGLE_API_KEY environment variable is not set")
            return {'steps': [], 'error': 'GOOGLE_API_KEY not configured', 'raw_response': None}
        
        logger.info("Google API key is configured")
        
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        if not frames:
            logger.error("No frames provided for AI analysis")
            return {'steps': [], 'error': 'No frames provided for analysis', 'raw_response': None}
        
        logger.info(f"Preparing {len(frames)} frames for Gemini Vision analysis")
        
        # Prepare frames for Gemini Vision
        frame_parts = []
        max_ai_frames = 8
        if len(frames) <= max_ai_frames:
            selected_indices = list(range(len(frames)))
        else:
            selected_indices = [
                int(round(i * (len(frames) - 1) / (max_ai_frames - 1)))
                for i in range(max_ai_frames)
            ]

        logger.info(f"Selected frame indices for AI: {selected_indices}")

        for idx_position, frame_index in enumerate(selected_indices):
            frame = frames[frame_index]
            try:
                frame_parts.append({
                    'mime_type': 'image/jpeg',
                    'data': base64.b64decode(frame['image_data'])
                })
                logger.debug(
                    f"Prepared frame {idx_position + 1} (source index {frame_index}, timestamp: {frame['timestamp']:.2f}s)"
                )
            except Exception as frame_prep_error:
                logger.error(f"Error preparing frame {frame_index}: {str(frame_prep_error)}")
                continue
        
        if not frame_parts:
            logger.error("No frames could be prepared for AI analysis")
            return {'steps': [], 'error': 'No frames available after preparation', 'raw_response': None}
        
        logger.info(f"Successfully prepared {len(frame_parts)} frames for analysis")
        
        # Build action log context if available
        action_context = ""
        if action_log and len(action_log) > 0:
            logger.info(f"Building context from {len(action_log)} user actions")
            action_lines = []
            for action in action_log[:60]:  # Limit for token efficiency
                timestamp = action.get('timestamp', 0) / 1000.0
                action_type = (action.get('type') or 'unknown').lower()

                if action_type == 'click':
                    target = action.get('target', {})
                    target_desc = target.get('text') or target.get('ariaLabel') or target.get('placeholder')
                    if not target_desc:
                        tag = target.get('tagName') or 'element'
                        target_desc = f"<{tag.lower()}>"
                    action_lines.append(f"  {timestamp:.1f}s: Clicked {target_desc}")
                elif action_type in ('input', 'change'):
                    target = action.get('target', {})
                    field_name = target.get('name') or target.get('placeholder') or target.get('ariaLabel') or target.get('tagName', 'field')
                    value = (action.get('value') or '')[:80]
                    display_value = value if value else '[cleared]'
                    action_lines.append(f"  {timestamp:.1f}s: Updated {field_name} with '{display_value}'")
                elif action_type == 'submit':
                    target = action.get('target', {}).get('name') or 'form'
                    action_lines.append(f"  {timestamp:.1f}s: Submitted {target}")
                elif action_type == 'keydown':
                    key = action.get('key', '').upper()
                    action_lines.append(f"  {timestamp:.1f}s: Pressed {key} key")
                elif action_type == 'navigation':
                    url = action.get('url') or action.get('pageUrl') or '(unknown URL)'
                    source = action.get('source') or 'navigation'
                    action_lines.append(f"  {timestamp:.1f}s: {source} → {url}")
                elif action_type in ('fetch_request', 'xhr_request'):
                    method = action.get('method', 'GET')
                    url = action.get('url', '')
                    action_lines.append(f"  {timestamp:.1f}s: {method} request to {url}")
                elif action_type in ('fetch_response', 'xhr_response'):
                    method = action.get('method', 'GET')
                    url = action.get('url', '')
                    status = action.get('status')
                    action_lines.append(f"  {timestamp:.1f}s: {method} response {status} from {url}")
                elif action_type in ('fetch_error', 'xhr_error'):
                    method = action.get('method', 'GET')
                    url = action.get('url', '')
                    message = action.get('message') or action.get('status')
                    action_lines.append(f"  {timestamp:.1f}s: {method} request error on {url} ({message})")
                elif action_type == 'annotation':
                    note = (action.get('value') or action.get('note') or '')[:100]
                    action_lines.append(f"  {timestamp:.1f}s: USER NOTE – {note}")
                elif action_type in ('recording_started', 'recording_stopped'):
                    continue
                else:
                    # Generic fallback for unknown types
                    summary = action.get('value') or action.get('message') or ''
                    summary = summary[:60] if summary else ''
                    action_lines.append(f"  {timestamp:.1f}s: {action_type} {summary}")

            if action_lines:
                action_context = "\n\nUSER ACTIONS CAPTURED DURING RECORDING:\n" + "\n".join(action_lines) + "\n"
                logger.info(f"Generated action context with {len(action_lines)} formatted actions")
        
        # Create comprehensive prompt for video analysis
        prompt = f"""
        Analyze this screen recording ({len(frame_parts)} frames in chronological order) and generate concise reproduction steps.
        {action_context if action_context else ""}
        
        RULES:
        1. Identify USER ACTIONS (clicks, navigation, typing) by looking for UI changes between frames
        2. Summarize what happened, don't describe every visible element
        3. Include URLs from address bar when they change
        4. Mention key UI elements only when they're interacted with or when they appear/disappear
        5. Be CONCISE - combine related observations into single steps
        6. Do NOT conclude what the bug is - just document what was observed
        
        GOOD examples:
        1. Open Chrome Incognito window
        2. Navigate to https://example.com/dashboard
        3. Click on "Getting Started with NoSQL" course card
        4. "Access Paused!" modal appears blocking course content
        
        BAD examples (too verbose):
        1. The screen displays "You've gone Incognito" page in a Chrome browser
        2. The text "Chrome won't save: Your browsing history..." is visible
        3. The text "Your activity might still be visible to..." is visible
        4. The message "Third-party cookies are blocked" is visible at the bottom
        
        Generate 3-6 concise steps describing the user's actions and key observations:
        """
        
        # Use Gemini Vision model from environment configuration
        try:
            model_name = os.environ.get('GOOGLE_API_MODEL', 'gemini-1.5-flash-latest')
            logger.info(f"Initializing Gemini Vision model: {model_name}")
            model = genai.GenerativeModel(model_name)
            
            # Combine prompt with images
            content = [prompt] + frame_parts
            
            logger.info(f"Sending request to Gemini Vision with {len(frame_parts)} frames...")
            response = model.generate_content(content)
            
            if response and response.text:
                ai_text = response.text.strip()
                logger.info(f"Received AI response ({len(ai_text)} characters)")
                logger.info(f"AI response preview: {ai_text[:300]}...")
                
                # Parse steps from AI response
                steps = []
                lines = ai_text.split('\n')
                
                logger.info(f"Parsing {len(lines)} lines from AI response")
                
                for line_num, line in enumerate(lines):
                    line = line.strip()
                    if line and (line[0].isdigit() or line.startswith('-') or line.startswith('*')):
                        # Clean up the step text
                        step = line
                        # Remove numbering and bullet points
                        step = re.sub(r'^\d+\.?\s*', '', step)
                        step = re.sub(r'^[-*]\s*', '', step)
                        if step and len(step) > 10:  # Ensure meaningful steps
                            steps.append(step.strip())
                            logger.debug(f"Parsed step {len(steps)}: {step[:50]}...")
                
                logger.info(f"Parsed {len(steps)} steps from AI response")
                
                # Ensure we have reasonable number of steps
                if len(steps) > 7:
                    logger.info(f"Limiting steps from {len(steps)} to 7")
                    steps = steps[:7]
                elif len(steps) < 3:
                    logger.warning(f"Only {len(steps)} steps parsed, adding descriptive fallback messaging")
                    if len(steps) == 0:
                        steps = [
                            "Start the screen recording",
                            "Perform the actions related to the bug scenario",
                            "Recording ends with the same screen displayed; no additional interactions captured"
                        ]
                    elif len(steps) == 1:
                        steps.append("No additional user interactions were detected after this step")
                        steps.append("Recording ends with the screen unchanged")
                    elif len(steps) == 2:
                        steps.append("Recording ends with the same interface visible; no further actions captured")
                
                logger.info(f"Final step count: {len(steps)}")
                for i, step in enumerate(steps):
                    logger.info(f"Step {i+1}: {step}")
                
                return {
                    'steps': steps,
                    'raw_response': ai_text,
                    'parse_method': 'numbered_lines',
                    'error': None
                }
                
            else:
                logger.error("Gemini Vision returned empty or null response")
                return {'steps': [], 'error': 'Gemini Vision returned empty response', 'raw_response': None}
                
        except Exception as api_error:
            logger.error(f"Error calling Gemini Vision API: {str(api_error)}")
            logger.error(f"API error type: {type(api_error).__name__}")
            import traceback
            logger.error(f"API error traceback: {traceback.format_exc()}")
            return {'steps': [], 'error': str(api_error), 'raw_response': None}
            
    except Exception as e:
        logger.error(f"Error in AI video analysis: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return {'steps': [], 'error': str(e), 'raw_response': None}

@app.route('/api/bug-builder/generate-final-report', methods=['POST'])
@jira_auth_required
@llm_rate_limit
def generate_final_bug_report():
    """Generate final bug report with AI summary"""
    try:
        data = request.get_json()
        steps = data.get('steps', [])
        expected_result = data.get('expected_result', '')
        actual_result = data.get('actual_result', '')
        additional_data = data.get('additional_data', '')
        
        if not expected_result or not actual_result:
            return jsonify({'success': False, 'error': 'Expected and actual results are required'}), 400
        
        # Format steps for the prompt
        steps_text = '\n'.join(f"{i+1}. {step}" for i, step in enumerate(steps)) if steps else "No steps provided"
        
        # Generate AI summary and bug report
        try:
            # Create AI prompt for bug report generation
            prompt = f"""Generate a professional bug report based on the following information:

Steps to Reproduce:
{steps_text}

Expected Result: {expected_result}
Actual Result: {actual_result}
Additional Context: {additional_data}

Please create:
1. A concise bug title (one line, max 100 characters)
2. A detailed description that includes:
   - What the issue is
   - The steps to reproduce (formatted nicely)
   - Expected vs Actual results
   - Any additional context

Format your response EXACTLY like this:
TITLE: [your bug title here]

DESCRIPTION:
[your detailed description here including all the information above]
"""
            
            # Generate bug report using AI
            model_name = os.environ.get('GOOGLE_API_MODEL', 'gemini-1.5-flash-latest')
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            
            if response and response.text:
                ai_text = response.text.strip()
                
                # Extract title and description
                title_match = re.search(r'TITLE:\s*(.+?)(?:\n|$)', ai_text, re.IGNORECASE)
                desc_match = re.search(r'DESCRIPTION:\s*(.*)', ai_text, re.IGNORECASE | re.DOTALL)
                
                if title_match and desc_match:
                    title = title_match.group(1).strip()
                    description = desc_match.group(1).strip()
                else:
                    # Fallback parsing
                    lines = ai_text.split('\n')
                    title = lines[0].strip() if lines else f"Bug: {expected_result[:50]}"
                    description = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ai_text
                
                # Clean up title
                title = title.replace('TITLE:', '').replace('Title:', '').strip()
                title = title[:100]  # Limit length
                
            else:
                raise Exception("AI did not generate a valid response")
                
        except Exception as ai_error:
            logger.error(f"AI bug report generation failed: {str(ai_error)}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Fallback to structured template
            title = f"Bug: {expected_result[:50]}" if len(expected_result) > 50 else f"Bug: {expected_result}"
            description = f"""**Steps to Reproduce:**
{steps_text}

**Expected Result:**
{expected_result}

**Actual Result:**
{actual_result}"""
            
            if additional_data:
                description += f"\n\n**Additional Context:**\n{additional_data}"
        
        return jsonify({
            'success': True,
            'title': title,
            'description': description
        })
        
    except Exception as e:
        logger.error(f"Error generating final report: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Bug Builder - Jira Integration
@app.route('/api/jira/create-issue', methods=['POST'])
@jira_auth_required
def create_jira_issue_from_bug():
    """Create a Jira issue from bug builder"""
    try:
        data = request.get_json()
        project_key = data.get('project_key')
        summary = data.get('summary')
        description = data.get('description')
        priority = data.get('priority', 'Medium')
        trivial_bug = data.get('trivial_bug', 'No')
        
        if not project_key or not summary:
            return jsonify({'success': False, 'error': 'Project key and summary are required'}), 400
        
        # Get Jira credentials
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        
        if not access_token or not cloud_id:
            return jsonify({'success': False, 'error': 'Not authenticated with Jira'}), 401
        
        # Check token expiry
        token_expires = session.get('jira_token_expires', 0)
        if time.time() >= token_expires:
            if not refresh_jira_token():
                return jsonify({'success': False, 'error': 'Token expired'}), 401
            access_token = session['jira_access_token']
        
        # Create issue
        url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Build fields payload
        fields = {
            'project': {'key': project_key},
            'summary': summary,
            'description': {
                'type': 'doc',
                'version': 1,
                'content': [
                    {
                        'type': 'paragraph',
                        'content': [
                            {
                                'type': 'text',
                                'text': description
                            }
                        ]
                    }
                ]
            },
            'issuetype': {'name': 'Bug'},
            'priority': {'name': priority},
            'customfield_10290': {'value': trivial_bug}  # Trivial bug field
        }
        
        payload = {'fields': fields}
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            issue_data = response.json()
            issue_key = issue_data.get('key')
            issue_url = f"{domain}/browse/{issue_key}"
            
            logger.info(f"Created Jira issue: {issue_key}")
            
            return jsonify({
                'success': True,
                'issue_key': issue_key,
                'issue_url': issue_url,
                'issue_id': issue_data.get('id')
            })
        else:
            # Better error handling
            try:
                error_data = response.json()
                error_messages = error_data.get('errorMessages', [])
                errors_dict = error_data.get('errors', {})
                
                if error_messages:
                    error_msg = error_messages[0]
                elif errors_dict:
                    error_msg = '; '.join([f"{k}: {v}" for k, v in errors_dict.items()])
                else:
                    error_msg = error_data.get('message', response.text)
            except:
                error_msg = response.text
            
            logger.error(f"Failed to create Jira issue: {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), response.status_code
            
    except Exception as e:
        logger.error(f"Error creating Jira issue: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/jira/project-create-meta', methods=['GET'])
@jira_auth_required
def get_project_create_meta():
    """Get project metadata for creating issues"""
    try:
        project_key = request.args.get('project_key')
        if not project_key:
            return jsonify({'success': False, 'error': 'Project key is required'}), 400
        
        # Get Jira credentials
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not access_token or not cloud_id:
            return jsonify({'success': False, 'error': 'Not authenticated with Jira'}), 401
        
        # Check token expiry
        token_expires = session.get('jira_token_expires', 0)
        if time.time() >= token_expires:
            if not refresh_jira_token():
                return jsonify({'success': False, 'error': 'Token expired'}), 401
            access_token = session['jira_access_token']
        
        # Get create metadata
        url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/createmeta'
        params = {
            'projectKeys': project_key,
            'expand': 'projects.issuetypes.fields'
        }
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': 'Failed to fetch project metadata'}), response.status_code
        
        data = response.json()
        projects = data.get('projects', [])
        
        if not projects:
            return jsonify({'success': False, 'error': f'Project {project_key} not found or you don\'t have access'}), 404
        
        project = projects[0]
        issue_types = project.get('issuetypes', [])
        
        # Find Bug issue type or use first one
        bug_type = next((it for it in issue_types if it['name'] == 'Bug'), issue_types[0] if issue_types else None)
        
        if not bug_type:
            return jsonify({'success': False, 'error': 'No issue types available'}), 400
        
        fields = bug_type.get('fields', {})
        
        # Extract priorities
        priorities = []
        if 'priority' in fields:
            priority_field = fields['priority']
            if 'allowedValues' in priority_field:
                priorities = [{'id': p['id'], 'name': p['name']} for p in priority_field['allowedValues']]
        
        # Extract custom fields
        custom_fields = []
        for field_id, field_data in fields.items():
            if field_id.startswith('customfield_'):
                field_name = field_data.get('name', field_id)
                field_required = field_data.get('required', False)
                field_schema = field_data.get('schema', {})
                field_type = field_schema.get('type', 'string')
                
                custom_field = {
                    'id': field_id,
                    'name': field_name,
                    'required': field_required,
                    'type': 'text'
                }
                
                # Determine field type
                if 'allowedValues' in field_data:
                    custom_field['type'] = 'select'
                    custom_field['allowed_values'] = [
                        {'id': v.get('id'), 'value': v.get('value', v.get('name', str(v)))}
                        for v in field_data['allowedValues']
                    ]
                elif field_type in ['number', 'float']:
                    custom_field['type'] = 'number'
                
                custom_fields.append(custom_field)
        
        return jsonify({
            'success': True,
            'project_key': project_key,
            'issue_types': [{'id': it['id'], 'name': it['name']} for it in issue_types],
            'priorities': priorities,
            'custom_fields': custom_fields
        })
        
    except Exception as e:
        logger.error(f"Error fetching project metadata: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/jira/attach-file', methods=['POST'])
@jira_auth_required
def attach_file_to_jira():
    """Attach a file to a Jira issue"""
    try:
        issue_key = request.form.get('issue_key')
        if not issue_key:
            return jsonify({'success': False, 'error': 'Issue key is required'}), 400
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Get Jira credentials
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not access_token or not cloud_id:
            return jsonify({'success': False, 'error': 'Not authenticated with Jira'}), 401
        
        # Check token expiry
        token_expires = session.get('jira_token_expires', 0)
        if time.time() >= token_expires:
            if not refresh_jira_token():
                return jsonify({'success': False, 'error': 'Token expired'}), 401
            access_token = session['jira_access_token']
        
        # Upload attachment
        url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{issue_key}/attachments'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Atlassian-Token': 'no-check',
            'Accept': 'application/json'
        }
        
        files = {'file': (file.filename, file.stream, file.content_type)}
        
        response = requests.post(url, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            logger.info(f"Attached file to Jira issue: {issue_key}")
            return jsonify({'success': True, 'message': 'File attached successfully'})
        else:
            # Better error handling
            try:
                error_data = response.json()
                error_messages = error_data.get('errorMessages', [])
                errors_dict = error_data.get('errors', {})
                
                if error_messages:
                    error_msg = error_messages[0]
                elif errors_dict:
                    error_msg = '; '.join([f"{k}: {v}" for k, v in errors_dict.items()])
                else:
                    error_msg = error_data.get('message', response.text)
            except:
                error_msg = response.text
            
            logger.error(f"Failed to attach file: {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), response.status_code
            
    except Exception as e:
        logger.error(f"Error attaching file to Jira: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# Playwright Codegen API (for Automation Test Creator)
# ========================================

# Session storage for Playwright Codegen sessions
playwright_codegen_sessions = {}

def beautify_playwright_code_with_ai(code):
    """
    Use AI to add comments, improve readability, and beautify Playwright code.
    Returns the enhanced code with step-by-step comments.
    """
    import google.generativeai as genai
    
    genai_api_key = os.getenv('GOOGLE_API_KEY')
    if not genai_api_key:
        logger.warning('Google API key not configured, skipping code beautification')
        return code
    
    try:
        genai.configure(api_key=genai_api_key)
        model_name = os.getenv('GOOGLE_API_MODEL', 'gemini-1.5-flash')
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""You are a code quality expert. Enhance the following Playwright test code by:

1. Adding clear, descriptive comments before each test step explaining WHAT and WHY
2. Grouping related actions with section comments (e.g., # Setup, # Navigation, # Form filling, # Assertions, # Cleanup)
3. Adding inline comments for complex selectors explaining what element is being targeted
4. Improving variable names if needed for better readability
5. Adding a docstring at the top of the function explaining the test purpose
6. **CRITICAL - Selector Specificity**: 
   - If a selector looks ambiguous (like a common class name: `.icon`, `.button`, `.item`, etc.), add `.first` or use more specific selectors
   - Keep specific selectors unchanged (with IDs, unique attributes, or text content)
   - Add comments explaining why `.first` is used: "# Click the first/leftmost/topmost element" or "# Target the primary action button"
   - Example: `page.locator(".icon-square")` → `page.locator(".icon-square").first  # Click the first icon in the toolbar`
   - Example: `page.locator("button")` → Keep as is if text content makes it unique: `page.locator("button").filter(has_text="Submit")`
7. Keeping the code functional and executable - DO NOT change the logic or break working tests

Original Code:
```python
{code}
```

Return ONLY the enhanced Python code. Do not include any explanatory text, markdown code blocks, or anything else - just the pure Python code that can be directly executed.

The output should be clean, well-commented, production-ready test code that avoids Playwright strict mode violations."""

        response = model.generate_content(prompt)
        enhanced_code = response.text.strip()
        
        # Remove markdown code blocks if present
        if '```python' in enhanced_code:
            enhanced_code = enhanced_code.split('```python')[1].split('```')[0].strip()
        elif '```' in enhanced_code:
            enhanced_code = enhanced_code.split('```')[1].split('```')[0].strip()
        
        # Post-process: Add .first ONLY to obviously ambiguous class-only selectors
        # that don't have any other specificity and don't already have .first/.nth/.last
        import re
        
        # Pattern: .locator with only class selector (starts with .) and nothing else
        # Example: .locator(".icon-square") but NOT .locator("#id") or .locator("button[name='submit']")
        pattern = r'\.locator\(["\'](\.[a-zA-Z0-9_-]+)["\']?\)(?!\.(?:first|last|nth\(|filter\(|get_by_|count\(\)|and_\(|or_\())'
        
        def add_first_with_comment(match):
            full_match = match.group(0)
            selector = match.group(1)
            # Only add .first if it's a simple class selector with no other attributes
            # and the class name suggests it could match multiple elements
            ambiguous_keywords = ['icon', 'button', 'item', 'card', 'tile', 'box', 'container', 'wrapper', 'list', 'element']
            selector_lower = selector.lower()
            
            # Check if selector contains any ambiguous keywords
            is_ambiguous = any(keyword in selector_lower for keyword in ambiguous_keywords)
            
            if is_ambiguous:
                return f'{full_match}.first'
            return full_match
        
        enhanced_code = re.sub(pattern, add_first_with_comment, enhanced_code)
        
        logger.info(f"Code beautified: {len(code)} chars → {len(enhanced_code)} chars")
        return enhanced_code
        
    except Exception as e:
        logger.error(f"Error beautifying code with AI: {str(e)}")
        return code  # Return original code if beautification fails

def generate_test_details_with_ai(code, video_path=None):
    """
    Generate test details using AI with optional video analysis.
    Returns: (summary, description, automated_steps, manual_steps)
    """
    import google.generativeai as genai
    import io
    
    genai_api_key = os.getenv('GOOGLE_API_KEY')
    if not genai_api_key:
        raise Exception('Google API key not configured')
    
    genai.configure(api_key=genai_api_key)
    model_name = os.getenv('GOOGLE_API_MODEL', 'gemini-1.5-flash')
    model = genai.GenerativeModel(model_name)
    
    # Base prompt for code analysis
    prompt = f"""
Analyze the following Playwright automation code and generate test documentation.

CODE:
```python
{code}
```

IMPORTANT: You MUST respond with ONLY a valid JSON object. Do not include any explanatory text, markdown formatting, or anything else before or after the JSON.

Required JSON format:
{{
    "summary": "one sentence test summary suitable for Jira task title",
    "description": "2-3 sentences explaining what the test validates",
    "manual_steps": ["manual step 1", "manual step 2", "manual step 3", ...]
}}

Generate:
1. summary: A concise test summary (one sentence)
2. description: A detailed test description (2-3 sentences)
3. manual_steps: Step-by-step instructions for a human tester to manually perform this test (5-10 clear, actionable steps)

Return ONLY the JSON object, nothing else."""
    
    # If video is provided, add video analysis
    content_parts = [prompt]
    
    if video_path and os.path.exists(video_path):
        try:
            # Extract frames from video for analysis
            import cv2
            import numpy as np
            # Import PIL at the function level to ensure it's available
            try:
                from PIL import Image as PILImage
            except ImportError:
                logger.error("PIL/Pillow not installed")
                raise
            
            video = cv2.VideoCapture(video_path)
            frames = []
            frame_count = 0
            total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # Extract 5 evenly spaced frames
            frame_indices = [int(total_frames * i / 5) for i in range(5)]
            
            while True:
                ret, frame = video.read()
                if not ret:
                    break
                
                if frame_count in frame_indices:
                    # Convert BGR to RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    # Create PIL Image from numpy array
                    pil_image = PILImage.fromarray(frame_rgb)
                    
                    # Convert PIL Image to bytes to avoid PIL plugin issues
                    img_byte_arr = io.BytesIO()
                    pil_image.save(img_byte_arr, format='PNG')
                    img_byte_arr = img_byte_arr.getvalue()
                    
                    # Recreate PIL Image from bytes (this ensures proper initialization)
                    frames.append(PILImage.open(io.BytesIO(img_byte_arr)))
                
                frame_count += 1
            
            video.release()
            
            # Add video analysis instruction
            video_instruction = """

ADDITIONAL CONTEXT: Video frames from the actual test execution are provided.
Enhance the manual steps with visual observations from these video frames.
The video shows the actual UI interactions being performed.

Remember: Respond with ONLY the JSON object."""
            
            content_parts = [prompt + video_instruction] + frames
            
            logger.info(f"Analyzing with {len(frames)} video frames")
            
        except Exception as e:
            import traceback
            logger.error(f"Error processing video: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Continue without video analysis
            frames = []
    
    try:
        response = model.generate_content(content_parts)
        result_text = response.text.strip()
        
        logger.info(f"AI Response: {result_text[:500]}...")  # Log first 500 chars for debugging
        
        # Extract JSON from response (handle various formats)
        json_text = result_text
        
        # Try to extract from markdown code blocks
        if '```json' in result_text:
            json_text = result_text.split('```json')[1].split('```')[0].strip()
        elif '```' in result_text:
            json_text = result_text.split('```')[1].split('```')[0].strip()
        
        # Try to find JSON object boundaries
        if not json_text.startswith('{'):
            # Look for the first { and last }
            start_idx = json_text.find('{')
            end_idx = json_text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                json_text = json_text[start_idx:end_idx+1]
        
        # Parse JSON
        result = json.loads(json_text)
        
        return (
            result.get('summary', ''),
            result.get('description', ''),
            result.get('automated_steps', []),
            result.get('manual_steps', [])
        )
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}")
        logger.error(f"Attempted to parse: {json_text[:500] if 'json_text' in locals() else result_text[:500]}")
        raise Exception(f"Failed to parse AI response as JSON: {str(e)}")
    except Exception as e:
        logger.error(f"Error generating test details with AI: {str(e)}")
        raise

@app.route('/api/playwright-codegen/start', methods=['POST'])
@jira_auth_required
def start_playwright_codegen():
    """Start Playwright Codegen for test recording"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        import uuid
        import subprocess
        import os
        from threading import Thread
        
        session_id = str(uuid.uuid4())
        
        # Create output directory
        output_dir = os.path.join('playwright-output', 'automation-test-creator', session_id)
        os.makedirs(output_dir, exist_ok=True)
        script_path = os.path.join(output_dir, 'test.spec.ts')
        
        # Store session info
        playwright_codegen_sessions[session_id] = {
            'status': 'recording',
            'script_path': script_path,
            'output_dir': output_dir,
            'url': url,
            'process': None,
            'code': ''
        }
        
        def run_codegen():
            try:
                logger.info(f"Starting Playwright Codegen for session {session_id}")
                
                # Build codegen command
                cmd = [
                    sys.executable, '-m', 'playwright',
                    'codegen',
                    '--target=python',
                    f'--output={script_path}'
                ]
                
                if url:
                    cmd.append(url)
                
                # Start the process
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=os.getcwd()
                )
                
                playwright_codegen_sessions[session_id]['process'] = process
                
                # Wait for completion
                stdout, _ = process.communicate()
                
                if stdout:
                    logger.info(f"Codegen output: {stdout.decode('utf-8', errors='ignore')}")
                
                # Read the generated code
                if os.path.exists(script_path):
                    with open(script_path, 'r', encoding='utf-8') as f:
                        code = f.read()
                    playwright_codegen_sessions[session_id]['code'] = code
                    playwright_codegen_sessions[session_id]['status'] = 'completed'
                else:
                    playwright_codegen_sessions[session_id]['status'] = 'failed'
                    playwright_codegen_sessions[session_id]['error'] = 'No script file generated'
                
                logger.info(f"Codegen completed for session {session_id}")
                
            except Exception as e:
                logger.error(f"Error in Codegen: {str(e)}")
                playwright_codegen_sessions[session_id]['status'] = 'failed'
                playwright_codegen_sessions[session_id]['error'] = str(e)
        
        thread = Thread(target=run_codegen)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': 'Playwright Codegen started'
        })
        
    except Exception as e:
        logger.error(f"Error starting Codegen: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/playwright-codegen/stop', methods=['POST'])
@jira_auth_required
def stop_playwright_codegen():
    """Stop Playwright Codegen recording"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id or session_id not in playwright_codegen_sessions:
            return jsonify({'success': False, 'error': 'Invalid session'}), 400
        
        session = playwright_codegen_sessions[session_id]
        
        # Try to terminate the process
        if session.get('process'):
            try:
                session['process'].terminate()
                session['process'].wait(timeout=5)
            except:
                session['process'].kill()
        
        # Read the final code
        script_path = session.get('script_path')
        if script_path and os.path.exists(script_path):
            with open(script_path, 'r', encoding='utf-8') as f:
                code = f.read()
            session['code'] = code
            session['status'] = 'completed'
        
        return jsonify({
            'success': True,
            'code': session.get('code', ''),
            'status': session.get('status')
        })
        
    except Exception as e:
        logger.error(f"Error stopping Codegen: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/playwright-codegen/code/<session_id>', methods=['GET'])
@jira_auth_required
def get_playwright_codegen_code(session_id):
    """Get the current recorded code for a session"""
    try:
        if session_id not in playwright_codegen_sessions:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        session = playwright_codegen_sessions[session_id]
        
        # Try to read the latest code from file
        script_path = session.get('script_path')
        if script_path and os.path.exists(script_path):
            with open(script_path, 'r', encoding='utf-8') as f:
                code = f.read()
            session['code'] = code
        
        return jsonify({
            'success': True,
            'code': session.get('code', ''),
            'status': session.get('status', 'unknown')
        })
        
    except Exception as e:
        logger.error(f"Error getting code: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# Automation Test Creator Routes
# ========================================

@app.route('/api/automation-test-creator/start-recording', methods=['POST'])
@jira_auth_required
def automation_test_creator_start_recording():
    """Start Playwright recording for Automation Test Creator"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        import uuid
        import subprocess
        from threading import Thread
        
        session_id = str(uuid.uuid4())
        logger.info(f"Creating new Automation Test Creator session: {session_id}")
        
        # Create output directory
        output_dir = os.path.join('playwright-output', 'automation-test-creator', session_id)
        os.makedirs(output_dir, exist_ok=True)
        script_path = os.path.join(output_dir, 'test.spec.py')  # Changed to .py for Python
        
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Script path: {script_path}")
        
        # Store session info
        playwright_codegen_sessions[session_id] = {
            'status': 'launching',
            'script_path': script_path,
            'output_dir': output_dir,
            'url': url,
            'process': None,
            'code': '',
            'video_path': None
        }
        
        logger.info(f"Session created. Total active sessions: {len(playwright_codegen_sessions)}")
        
        def run_codegen():
            try:
                logger.info(f"Starting Playwright Codegen for Automation Test Creator session {session_id}")
                
                # Build codegen command
                cmd = [
                    sys.executable, '-m', 'playwright',
                    'codegen',
                    '--target=python',
                    f'--output={script_path}'
                ]
                
                if url:
                    cmd.append(url)
                
                # Start the process
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=os.getcwd()
                )
                
                playwright_codegen_sessions[session_id]['process'] = process
                playwright_codegen_sessions[session_id]['status'] = 'recording'
                
                # Wait for completion
                stdout, _ = process.communicate()
                
                if stdout:
                    logger.info(f"Codegen output: {stdout.decode('utf-8', errors='ignore')}")
                
                # Read the generated code
                if os.path.exists(script_path):
                    with open(script_path, 'r', encoding='utf-8') as f:
                        code = f.read()
                    playwright_codegen_sessions[session_id]['code'] = code
                    playwright_codegen_sessions[session_id]['status'] = 'completed'
                else:
                    playwright_codegen_sessions[session_id]['status'] = 'failed'
                    playwright_codegen_sessions[session_id]['error'] = 'No script file generated'
                
                logger.info(f"Codegen completed for Automation Test Creator session {session_id}")
                
            except Exception as e:
                logger.error(f"Error in Codegen: {str(e)}")
                playwright_codegen_sessions[session_id]['status'] = 'failed'
                playwright_codegen_sessions[session_id]['error'] = str(e)
        
        thread = Thread(target=run_codegen)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': 'Playwright browser launching...'
        })
        
    except Exception as e:
        logger.error(f"Error starting recording: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/automation-test-creator/recording-status/<session_id>', methods=['GET'])
@jira_auth_required
def automation_test_creator_recording_status(session_id):
    """Check the status of a recording session"""
    try:
        if session_id not in playwright_codegen_sessions:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        session = playwright_codegen_sessions[session_id]
        
        return jsonify({
            'success': True,
            'status': session.get('status', 'unknown'),
            'error': session.get('error')
        })
        
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/automation-test-creator/stop-recording/<session_id>', methods=['POST'])
@jira_auth_required
def automation_test_creator_stop_recording(session_id):
    """Stop recording and return the generated code"""
    try:
        logger.info(f"Attempting to stop recording for session {session_id}")
        logger.info(f"Active sessions: {list(playwright_codegen_sessions.keys())}")
        
        if session_id not in playwright_codegen_sessions:
            return jsonify({'success': False, 'error': 'Invalid session. Session may have expired or never started.'}), 400
        
        session = playwright_codegen_sessions[session_id]
        logger.info(f"Session status: {session.get('status')}, has process: {session.get('process') is not None}")
        
        # Try to terminate the process
        if session.get('process'):
            try:
                logger.info("Terminating Playwright process...")
                session['process'].terminate()
                session['process'].wait(timeout=5)
                logger.info("Process terminated successfully")
            except Exception as e:
                logger.warning(f"Error terminating process: {e}, trying to kill...")
                try:
                    session['process'].kill()
                    logger.info("Process killed")
                except Exception as e2:
                    logger.error(f"Error killing process: {e2}")
        
        # Read the final code
        script_path = session.get('script_path')
        logger.info(f"Script path: {script_path}, exists: {os.path.exists(script_path) if script_path else False}")
        
        if script_path and os.path.exists(script_path):
            with open(script_path, 'r', encoding='utf-8') as f:
                code = f.read()
            session['code'] = code
            session['status'] = 'completed'
            logger.info(f"Code read successfully, length: {len(code)}")
        else:
            # If no script file yet, check if we have code from the session
            if session.get('code'):
                logger.info("Using code from session (script file not found)")
            else:
                logger.warning(f"No script file found at {script_path}")
                session['status'] = 'failed'
                session['error'] = 'No script file generated'
        
        return jsonify({
            'success': True,
            'code': session.get('code', ''),
            'status': session.get('status', 'unknown')
        })
        
    except Exception as e:
        logger.error(f"Error stopping recording: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/automation-test-creator/generate-with-ai', methods=['POST'])
@jira_auth_required
def automation_test_creator_generate_with_ai():
    """Generate test details using AI with optional video analysis"""
    try:
        code = request.form.get('code', '').strip()
        session_id = request.form.get('session_id', '').strip()
        video = request.files.get('video')
        
        if not code:
            return jsonify({'success': False, 'error': 'No code provided'}), 400
        
        # Save video if provided
        video_path = None
        if video:
            session = playwright_codegen_sessions.get(session_id, {})
            output_dir = session.get('output_dir')
            if output_dir:
                video_path = os.path.join(output_dir, 'recording.webm')
                video.save(video_path)
                session['video_path'] = video_path
                logger.info(f"Video saved to {video_path}, size: {os.path.getsize(video_path)} bytes")
        
        # Generate test details with AI (AI only generates summary, description, manual_steps now)
        logger.info(f"Calling AI generation with code length: {len(code)}, video: {video_path is not None}")
        summary, description, automated_steps, manual_steps = generate_test_details_with_ai(code, video_path)
        logger.info("AI generation completed successfully")
        
        # Step 1: Beautify code with AI comments and formatting
        logger.info("Beautifying code with AI...")
        beautified_code = beautify_playwright_code_with_ai(code)
        
        # Step 2: Add waits and stability improvements to the beautified code
        logger.info("Adding waits to code...")
        enhanced_code = add_waits_to_playwright_code(beautified_code)
        
        # Return enhanced code as automated_code instead of AI-generated steps
        return jsonify({
            'success': True,
            'summary': summary,
            'description': description,
            'automated_code': enhanced_code,  # Return the beautified + enhanced Playwright code
            'manual_steps': manual_steps
        })
        
    except Exception as e:
        import traceback
        logger.error(f"Error generating with AI: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/api/automation-test-creator/download-zip', methods=['POST'])
@jira_auth_required
def automation_test_creator_download_zip():
    """Generate and download a ZIP package with test files"""
    try:
        test_name = request.form.get('test_name', 'automation_test').strip()
        summary = request.form.get('summary', '').strip()
        description = request.form.get('description', '').strip()
        automated_code = request.form.get('automated_code', '').strip()
        automated_steps_json = request.form.get('automated_steps', '[]')
        manual_steps_json = request.form.get('manual_steps', '[]')
        video = request.files.get('video')
        
        import json
        import zipfile
        from io import BytesIO
        
        automated_steps = json.loads(automated_steps_json)
        manual_steps = json.loads(manual_steps_json)
        
        # Create ZIP in memory
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add Playwright test file
            test_filename = f'{test_name}.spec.py'
            zip_file.writestr(test_filename, automated_code)
            
            # Add manual test document
            manual_doc = f"""# {summary}

## Description
{description}

## Automated Steps
{chr(10).join([f"{i+1}. {step}" for i, step in enumerate(automated_steps)])}

## Manual Test Steps
{chr(10).join([f"{i+1}. {step}" for i, step in enumerate(manual_steps)])}
"""
            zip_file.writestr('MANUAL_STEPS.md', manual_doc)
            
            # Add package.json
            package_json = {
                "name": test_name,
                "version": "1.0.0",
                "description": summary,
                "scripts": {
                    "test": f"pytest {test_filename}"
                },
                "dependencies": {
                    "playwright": "^1.40.0"
                },
                "devDependencies": {
                    "pytest": "^7.4.0",
                    "pytest-playwright": "^0.4.3"
                }
            }
            zip_file.writestr('package.json', json.dumps(package_json, indent=2))
            
            # Add README
            readme = f"""# {test_name}

## Setup
```bash
# Install Python dependencies
pip install pytest playwright pytest-playwright

# Install Playwright browsers
playwright install
```

## Run Test
```bash
pytest {test_filename}
```

## Manual Test Steps
See MANUAL_STEPS.md for manual testing procedures.
"""
            zip_file.writestr('README.md', readme)
            
            # Add video if provided
            if video:
                video_bytes = video.read()
                zip_file.writestr('test-recording.webm', video_bytes)
        
        zip_buffer.seek(0)
        
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{test_name}_{int(time.time())}.zip'
        )
        
    except Exception as e:
        logger.error(f"Error generating ZIP: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==============================
# AI Test Studio - Unified Entry Point
# ==============================

@app.route('/ai-test-studio')
@jira_auth_required
def ai_test_studio():
    """AI Test Studio - Smart routing and cross-feature integration"""
    return render_template('ai-test-studio.html', active_tab='ui-automation')

@app.route('/api/analyze-test-goal', methods=['POST'])
@jira_auth_required
def analyze_test_goal():
    """Analyze user's testing goal and recommend the best tool using AI"""
    try:
        data = request.json
        goal = data.get('goal', '')
        
        if not goal:
            return jsonify({'success': False, 'error': 'No goal provided'}), 400
        
        # Always use AI for intelligent recommendations
        try:
            model = genai.GenerativeModel(
                model_name=os.getenv('GOOGLE_API_MODEL', 'gemini-2.0-flash-exp'),
                generation_config=generation_config
            )
            
            prompt = f"""Analyze this testing goal and recommend the BEST tool with detailed reasoning.

Testing Goal: "{goal}"

Tools Available:
1. **Record & Enhance (Playwright Codegen)**
   - Visual recording with browser automation
   - AI code beautification and documentation
   - Manual editing and refinement
   - Best for: Simple-to-moderate UI tests, learning, quick prototypes
   - Limitations: Requires manual recording, less flexible for dynamic content

2. **AI Agent (Computer Use)**
   - Vision-based interaction using screenshots
   - Natural language instructions
   - Self-healing when elements change
   - Handles complex workflows automatically
   - Best for: Complex workflows, dynamic content, visual verification, CAPTCHA
   - Limitations: Slower, requires more resources

3. **Conversational MCP (Model Context Protocol)**
   - Chat-based test creation
   - API and E2E testing
   - Structured test generation
   - Iterative refinement through conversation
   - Best for: API testing, structured tests, when you can describe requirements clearly
   - Limitations: Requires clear descriptions, not visual

Consider:
- Complexity of the testing scenario
- Type of application (UI-heavy, API, mixed)
- Need for visual verification
- Dynamic vs static content
- User's technical level

Respond in JSON format (ensure valid JSON, no markdown):
{{
    "tool": "<exact tool name from list above>",
    "reason": "<3-4 sentences with specific reasoning about why this tool is best for this goal. Include what makes it better than the alternatives.>",
    "confidence": "<high/medium/low>",
    "alternative": "<optional: another tool if user needs different approach>"
}}"""
            
            response = model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            ai_recommendation = json.loads(response_text)
            
            # Map tool name to URL
            tool_name = ai_recommendation['tool']
            if 'Record' in tool_name or 'Codegen' in tool_name:
                url = '/automation-test-creator'
            elif 'Agent' in tool_name or 'Computer Use' in tool_name:
                url = '/browseruse-automation'
            elif 'MCP' in tool_name or 'Conversational' in tool_name:
                url = '/playwright-mcp-automation'
            else:
                # Default to Record & Enhance
                url = '/automation-test-creator'
            
            return jsonify({
                'success': True,
                'tool': ai_recommendation['tool'],
                'reason': ai_recommendation['reason'],
                'url': url,
                'confidence': ai_recommendation.get('confidence', 'medium'),
                'alternative': ai_recommendation.get('alternative', '')
            })
                
        except Exception as e:
            logger.error(f"AI analysis error: {str(e)}")
            logger.error(f"Response text: {response.text if 'response' in locals() else 'No response'}")
            # Fallback to Record & Enhance with keyword-based logic
            goal_lower = goal.lower()
            
            # Simple keyword fallback
            if any(word in goal_lower for word in ['api', 'rest', 'graphql', 'endpoint']):
                tool = 'Conversational MCP'
                reason = 'For API testing scenarios, Conversational MCP provides the best chat-based interface for creating structured tests.'
                url = '/playwright-mcp-automation'
            elif any(word in goal_lower for word in ['complex', 'dynamic', 'captcha', 'visual']):
                tool = 'AI Agent (Computer Use)'
                reason = 'For complex or dynamic scenarios, AI Agent uses vision-based interaction and self-healing capabilities.'
                url = '/browseruse-automation'
            else:
                tool = 'Record & Enhance'
                reason = 'Record & Enhance is a versatile tool perfect for most testing scenarios. Record your interactions and AI will beautify the code.'
                url = '/automation-test-creator'
            
            return jsonify({
                'success': True,
                'tool': tool,
                'reason': reason,
                'url': url,
                'confidence': 'low',
                'alternative': ''
            })
        
    except Exception as e:
        logger.error(f"Error analyzing test goal: {str(e)}")
        return jsonify({
            'success': False, 
            'error': 'Failed to analyze test goal. Please try again.',
            'details': str(e)
        }), 500

# ==============================
# Cross-Tool Integration APIs
# ==============================

@app.route('/api/integration/export-to-mcp', methods=['POST'])
@jira_auth_required
def export_codegen_to_mcp():
    """Export Codegen/Agent test to MCP for refinement"""
    try:
        data = request.json
        source = data.get('source', 'codegen')  # 'codegen' or 'agent'
        code = data.get('code', '')
        actions = data.get('actions', [])
        url = data.get('url', '')
        metadata = data.get('metadata', {})
        
        if not code:
            return jsonify({'success': False, 'error': 'No code provided'}), 400
        
        # Create integration package
        integration_id = f"integration_{int(time.time())}_{source}"
        integration_data = {
            'id': integration_id,
            'source': source,
            'code': code,
            'actions': actions,
            'url': url,
            'metadata': metadata,
            'timestamp': datetime.now().isoformat(),
            'context': {
                'original_tool': source,
                'purpose': 'refinement',
                'preserved_state': True
            }
        }
        
        # Store in session for MCP to retrieve
        session[f'integration_{integration_id}'] = integration_data
        
        logger.info(f"Created integration package: {integration_id}")
        
        return jsonify({
            'success': True,
            'integration_id': integration_id,
            'message': 'Test exported successfully. Opening MCP...',
            'redirect_url': f'/playwright-mcp-automation?import={integration_id}'
        })
        
    except Exception as e:
        logger.error(f"Error exporting to MCP: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/integration/import-from-source', methods=['POST'])
@jira_auth_required
def import_from_source():
    """Import test from another tool (for MCP/Codegen/Agent)"""
    try:
        data = request.json
        integration_id = data.get('integration_id', '')
        target_tool = data.get('target_tool', 'mcp')  # 'mcp', 'codegen', or 'agent'
        
        if not integration_id:
            return jsonify({'success': False, 'error': 'No integration ID provided'}), 400
        
        # Retrieve integration data from session
        integration_key = f'integration_{integration_id}'
        integration_data = session.get(integration_key)
        
        if not integration_data:
            return jsonify({'success': False, 'error': 'Integration data not found or expired'}), 404
        
        # Transform data for target tool
        transformed_data = {
            'original_source': integration_data['source'],
            'code': integration_data['code'],
            'actions': integration_data['actions'],
            'url': integration_data['url'],
            'metadata': integration_data['metadata'],
            'suggestions': []
        }
        
        # Add tool-specific suggestions using AI
        if target_tool == 'mcp':
            transformed_data['suggestions'] = [
                'Add assertions to verify expected outcomes',
                'Include error handling for edge cases',
                'Optimize selectors for better stability',
                'Add comments explaining test logic'
            ]
        elif target_tool == 'codegen':
            transformed_data['suggestions'] = [
                'Record missing UI interactions',
                'Capture additional user flows',
                'Fill gaps in visual testing'
            ]
        elif target_tool == 'agent':
            transformed_data['suggestions'] = [
                'Use natural language for complex interactions',
                'Enable self-healing for dynamic elements',
                'Add visual verification steps'
            ]
        
        return jsonify({
            'success': True,
            'data': transformed_data,
            'message': f'Successfully imported from {integration_data["source"]}'
        })
        
    except Exception as e:
        logger.error(f"Error importing from source: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/integration/export-agent-exploration', methods=['POST'])
@jira_auth_required
def export_agent_exploration():
    """Export AI Agent exploration results to Codegen"""
    try:
        data = request.json
        exploration_id = data.get('exploration_id', '')
        successful_paths = data.get('successful_paths', [])
        selectors = data.get('selectors', {})
        interactions = data.get('interactions', [])
        screenshots = data.get('screenshots', [])
        
        # Create exploration package
        integration_id = f"agent_exploration_{int(time.time())}"
        exploration_data = {
            'id': integration_id,
            'source': 'agent_exploration',
            'exploration_id': exploration_id,
            'successful_paths': successful_paths,
            'selectors': selectors,
            'interactions': interactions,
            'screenshots': screenshots,
            'timestamp': datetime.now().isoformat(),
            'analysis': {
                'total_paths': len(successful_paths),
                'unique_selectors': len(selectors),
                'interaction_count': len(interactions)
            }
        }
        
        # Store for Codegen to retrieve
        session[f'integration_{integration_id}'] = exploration_data
        
        return jsonify({
            'success': True,
            'integration_id': integration_id,
            'message': 'Exploration exported successfully',
            'redirect_url': f'/automation-test-creator?import={integration_id}'
        })
        
    except Exception as e:
        logger.error(f"Error exporting agent exploration: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/integration/merge-tests', methods=['POST'])
@jira_auth_required
def merge_test_sources():
    """Merge tests from multiple sources into unified test"""
    try:
        data = request.json
        sources = data.get('sources', [])  # Array of integration_ids
        merge_strategy = data.get('strategy', 'sequential')  # 'sequential', 'parallel', 'conditional'
        
        if not sources or len(sources) < 2:
            return jsonify({'success': False, 'error': 'At least 2 sources required for merging'}), 400
        
        merged_code = []
        merged_actions = []
        all_metadata = []
        
        # Retrieve all source data
        for source_id in sources:
            integration_key = f'integration_{source_id}'
            source_data = session.get(integration_key)
            
            if source_data:
                merged_actions.extend(source_data.get('actions', []))
                all_metadata.append({
                    'source': source_data.get('source'),
                    'timestamp': source_data.get('timestamp')
                })
        
        # Use AI to intelligently merge the code
        try:
            model = genai.GenerativeModel(
                model_name=os.getenv('GOOGLE_API_MODEL', 'gemini-2.0-flash-exp'),
                generation_config=generation_config
            )
            
            merge_prompt = f"""You are merging multiple Playwright test sources into a single cohesive test.

Sources: {len(sources)}
Strategy: {merge_strategy}
Total Actions: {len(merged_actions)}

Merge Strategy Guidelines:
- sequential: Execute tests one after another
- parallel: Run tests concurrently (use Promise.all)
- conditional: Add logic to choose execution path

Generate a unified Playwright test that:
1. Combines all test logic efficiently
2. Eliminates redundant steps
3. Maintains proper error handling
4. Includes clear comments
5. Follows best practices

Return only the merged Playwright code."""
            
            response = model.generate_content(merge_prompt)
            merged_code_text = response.text.strip()
            
            # Clean up code markers
            merged_code_text = merged_code_text.replace('```javascript', '').replace('```python', '').replace('```', '').strip()
            
        except Exception as ai_error:
            logger.error(f"AI merge error: {str(ai_error)}")
            # Fallback: simple concatenation
            merged_code_text = "\n\n// Merged Test - Sequential Execution\n\n"
            for idx, source_id in enumerate(sources, 1):
                merged_code_text += f"\n// Source {idx}\n"
        
        # Create merged integration package
        merge_id = f"merged_{int(time.time())}"
        merged_data = {
            'id': merge_id,
            'source': 'merged',
            'code': merged_code_text,
            'actions': merged_actions,
            'metadata': {
                'source_count': len(sources),
                'merge_strategy': merge_strategy,
                'sources': all_metadata
            },
            'timestamp': datetime.now().isoformat()
        }
        
        session[f'integration_{merge_id}'] = merged_data
        
        return jsonify({
            'success': True,
            'merge_id': merge_id,
            'merged_code': merged_code_text,
            'source_count': len(sources),
            'message': 'Tests merged successfully'
        })
        
    except Exception as e:
        logger.error(f"Error merging tests: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/integration/get-context', methods=['GET'])
@jira_auth_required
def get_integration_context():
    """Retrieve integration context by ID"""
    try:
        integration_id = request.args.get('id', '')
        
        if not integration_id:
            return jsonify({'success': False, 'error': 'No integration ID provided'}), 400
        
        integration_key = f'integration_{integration_id}'
        context_data = session.get(integration_key)
        
        if not context_data:
            return jsonify({'success': False, 'error': 'Context not found or expired'}), 404
        
        return jsonify({
            'success': True,
            'context': context_data
        })
        
    except Exception as e:
        logger.error(f"Error retrieving context: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/automation-test-creator')
@jira_auth_required
def automation_test_creator():
    """Automation Test Creator - Integrated workflow for test creation"""
    return render_template('automation-test-creator.html', active_tab='ui-automation')

@app.route('/api/automation-test-creator/generate-details', methods=['POST'])
@jira_auth_required
def generate_test_details():
    """Generate test summary, description, and manual steps using AI"""
    try:
        data = request.json
        code = data.get('code', '')
        
        if not code:
            return jsonify({'success': False, 'error': 'No code provided'}), 400
        
        # Use Gemini to analyze the code and generate test details
        import google.generativeai as genai
        
        genai_api_key = os.getenv('GEMINI_API_KEY')
        if not genai_api_key:
            return jsonify({'success': False, 'error': 'Gemini API key not configured'}), 500
        
        genai.configure(api_key=genai_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
Analyze the following Playwright automation code and generate:

1. A concise test summary (one sentence, suitable for Jira task title)
2. A detailed test description (2-3 sentences explaining what the test validates)
3. Manual test steps (step-by-step instructions for a human tester, 5-10 steps)

CODE:
```javascript
{code}
```

Respond in JSON format:
{{
    "summary": "...",
    "description": "...",
    "manual_steps": ["step 1", "step 2", ...]
}}
"""
        
        response = model.generate_content(prompt)
        result_text = response.text.strip()
        
        # Extract JSON from response (handle markdown code blocks)
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0].strip()
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0].strip()
        
        result = json.loads(result_text)
        
        return jsonify({
            'success': True,
            'summary': result.get('summary', ''),
            'description': result.get('description', ''),
            'manual_steps': result.get('manual_steps', [])
        })
        
    except Exception as e:
        logger.error(f"Error generating test details: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/automation-test-creator/export-jira', methods=['POST'])
@jira_auth_required
def export_test_to_jira():
    """Create a Jira Task with automated code and manual steps"""
    try:
        data = request.json
        summary = data.get('summary', '')
        description = data.get('description', '')
        automated_code = data.get('automated_code', '')
        manual_steps = data.get('manual_steps', [])
        project = data.get('project', 'IRA')
        
        if not summary or not automated_code:
            return jsonify({'success': False, 'error': 'Summary and code are required'}), 400
        
        # Get Jira credentials
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not access_token or not cloud_id:
            return jsonify({'success': False, 'error': 'Not authenticated with Jira'}), 401
        
        # Build description with automated code and manual steps
        jira_description = {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "Test Description"}]
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}]
                },
                {
                    "type": "rule"
                },
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "🤖 Automated Test Code"}]
                },
                {
                    "type": "codeBlock",
                    "attrs": {"language": "javascript"},
                    "content": [{"type": "text", "text": automated_code}]
                }
            ]
        }
        
        # Add manual test steps if available
        if manual_steps and len(manual_steps) > 0:
            jira_description["content"].extend([
                {
                    "type": "rule"
                },
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "📋 Manual Test Steps"}]
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Follow these steps to manually validate the test:"}]
                },
                {
                    "type": "orderedList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": step}]
                                }
                            ]
                        } for step in manual_steps
                    ]
                }
            ])
        
        # Create Jira issue
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        jira_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue'
        
        # Get project ID first
        project_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/{project}'
        project_response = requests.get(project_url, headers=headers, timeout=30)
        
        if project_response.status_code != 200:
            return jsonify({'success': False, 'error': f'Project {project} not found'}), 404
        
        project_data = project_response.json()
        project_id = project_data.get('id')
        
        # Create issue payload
        issue_payload = {
            "fields": {
                "project": {"id": project_id},
                "summary": summary,
                "description": jira_description,
                "issuetype": {"name": "Task"}
            }
        }
        
        response = requests.post(jira_url, headers=headers, json=issue_payload, timeout=30)
        
        if response.status_code in [200, 201]:
            issue_data = response.json()
            issue_key = issue_data.get('key')
            issue_url = f"https://upgrad-jira.atlassian.net/browse/{issue_key}"
            
            return jsonify({
                'success': True,
                'issue_key': issue_key,
                'issue_url': issue_url,
                'issue_id': issue_data.get('id')
            })
        else:
            error_detail = response.text
            logger.error(f"Jira API error: {response.status_code} - {error_detail}")
            return jsonify({
                'success': False,
                'error': f'Failed to create Jira issue: {response.status_code}',
                'details': error_detail
            }), response.status_code
        
    except Exception as e:
        logger.error(f"Error exporting to Jira: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/automation-test-creator/import-jira/<ticket_id>', methods=['GET'])
@jira_auth_required
def import_test_from_jira(ticket_id):
    """Import test from Jira task"""
    try:
        # Get Jira credentials
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not access_token or not cloud_id:
            return jsonify({'success': False, 'error': 'Not authenticated with Jira'}), 401
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        # Fetch issue from Jira
        jira_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{ticket_id}'
        response = requests.get(jira_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': f'Failed to fetch Jira issue: {response.status_code}'}), response.status_code
        
        issue_data = response.json()
        fields = issue_data.get('fields', {})
        
        summary = fields.get('summary', '')
        description_adf = fields.get('description', {})
        
        # Extract code from ADF description
        code = extract_code_from_adf(description_adf)
        description_text = extract_text_from_adf(description_adf)
        
        return jsonify({
            'success': True,
            'test_data': {
                'jira_key': ticket_id,
                'summary': summary,
                'description': description_text,
                'code': code
            }
        })
        
    except Exception as e:
        logger.error(f"Error importing from Jira: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

def extract_code_from_adf(adf):
    """Extract code blocks from ADF format"""
    try:
        if not isinstance(adf, dict):
            return ''
        
        content = adf.get('content', [])
        code_blocks = []
        
        for block in content:
            if block.get('type') == 'codeBlock':
                code_content = block.get('content', [])
                for code_item in code_content:
                    if code_item.get('type') == 'text':
                        code_blocks.append(code_item.get('text', ''))
        
        return '\n\n'.join(code_blocks)
    except Exception as e:
        logger.error(f"Error extracting code from ADF: {e}")
        return ''

def extract_text_from_adf(adf):
    """Extract plain text from ADF format"""
    try:
        if not isinstance(adf, dict):
            return ''
        
        def walk_content(content):
            text_parts = []
            if isinstance(content, list):
                for item in content:
                    text_parts.extend(walk_content(item))
            elif isinstance(content, dict):
                if content.get('type') == 'text':
                    text_parts.append(content.get('text', ''))
                elif 'content' in content:
                    text_parts.extend(walk_content(content['content']))
            return text_parts
        
        text_parts = walk_content(adf.get('content', []))
        return ' '.join(text_parts)
    except Exception as e:
        logger.error(f"Error extracting text from ADF: {e}")
        return ''

def add_waits_to_playwright_code(code):
    """
    Add waits and stability improvements to Playwright code.
    Transforms common patterns to include proper waits.
    """
    import re
    
    def extract_locator(line):
        """Extract the complete locator call including nested parentheses"""
        # Find where page.locator( starts
        locator_start = line.find('page.locator(')
        if locator_start == -1:
            return None
        
        # Count parentheses to find the matching close
        paren_count = 0
        start_idx = locator_start + len('page.locator')
        
        for i in range(start_idx, len(line)):
            if line[i] == '(':
                paren_count += 1
            elif line[i] == ')':
                paren_count -= 1
                if paren_count == 0:
                    # Found the matching close parenthesis
                    return line[locator_start:i+1]
        
        return None
    
    lines = code.split('\n')
    enhanced_lines = []
    
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        indent_str = ' ' * indent
        
        # Add wait_for_load_state after goto()
        if '.goto(' in stripped and 'wait_for_load_state' not in stripped:
            enhanced_lines.append(line)
            enhanced_lines.append(f'{indent_str}page.wait_for_load_state("networkidle")')
            continue
        
        # Add wait_for() before click() - wait for element to be visible and stable
        if '.click(' in stripped and 'wait_for(' not in stripped and 'page.locator(' in stripped:
            locator = extract_locator(stripped)
            if locator:
                enhanced_lines.append(f'{indent_str}{locator}.wait_for(state="visible", timeout=10000)')
                enhanced_lines.append(line)
                continue
        
        # Add wait_for() before fill() - wait for element to be visible
        if '.fill(' in stripped and 'wait_for(' not in stripped and 'page.locator(' in stripped:
            locator = extract_locator(stripped)
            if locator:
                enhanced_lines.append(f'{indent_str}{locator}.wait_for(state="visible", timeout=10000)')
                enhanced_lines.append(line)
                continue
        
        # Add set_default_timeout after browser/context creation
        if 'browser = playwright.' in stripped or 'context = browser.' in stripped:
            enhanced_lines.append(line)
            if 'context = browser.' in stripped:
                enhanced_lines.append(f'{indent_str}context.set_default_timeout(30000)  # 30 second default timeout')
            continue
        
        # Add default timeout after page creation
        if 'page = ' in stripped and 'new_page()' in stripped:
            enhanced_lines.append(line)
            enhanced_lines.append(f'{indent_str}page.set_default_timeout(30000)  # 30 second default timeout')
            continue
        
        # Keep line as-is
        enhanced_lines.append(line)
    
    enhanced_code = '\n'.join(enhanced_lines)
    
    # Log the transformation
    logger.info(f"Enhanced Playwright code with waits. Original lines: {len(lines)}, Enhanced lines: {len(enhanced_lines)}")
    
    return enhanced_code

@app.route('/api/automation-test-creator/execute', methods=['POST'])
@jira_auth_required
def execute_test():
    """Execute the imported test code using Playwright (Python)"""
    try:
        data = request.json
        code = data.get('code', '')
        ticket_id = data.get('ticket_id', '')
        
        if not code:
            return jsonify({'success': False, 'error': 'No code provided'}), 400
        
        # Save code to temporary file
        import tempfile
        import uuid
        import re
        
        session_id = str(uuid.uuid4())
        temp_dir = tempfile.gettempdir()
        test_file = os.path.join(temp_dir, f'test_{session_id}.py')
        
        # Add waits and stability improvements to Playwright code
        code = add_waits_to_playwright_code(code)
        
        # Convert Playwright codegen format to pytest format if needed
        if 'def test_' not in code and 'from playwright.sync_api import' in code:
            # Extract the function body from the run() function
            # Playwright codegen creates: def run(playwright: Playwright) -> None:
            code_lines = code.split('\n')
            
            # Find where the run() function body starts
            run_func_start = -1
            for i, line in enumerate(code_lines):
                if 'def run(playwright:' in line:
                    run_func_start = i + 1
                    break
            
            if run_func_start > 0:
                # Extract just the function body (indented code after def run())
                body_lines = []
                for line in code_lines[run_func_start:]:
                    # Stop at the with sync_playwright() line or other function defs
                    if 'with sync_playwright()' in line or (line.strip() and not line.startswith(' ')):
                        break
                    # Skip empty lines at the start
                    if not body_lines and not line.strip():
                        continue
                    body_lines.append(line)
                
                # Remove trailing empty lines
                while body_lines and not body_lines[-1].strip():
                    body_lines.pop()
                
                # Remove one level of indentation
                dedented_body = []
                for line in body_lines:
                    if line.strip():  # Non-empty lines
                        # Remove 4 spaces of indentation
                        if line.startswith('    '):
                            dedented_body.append(line[4:])
                        else:
                            dedented_body.append(line)
                    else:  # Empty lines
                        dedented_body.append(line)
                
                # Create pytest-compatible test
                code = f"""import re
from playwright.sync_api import Playwright, sync_playwright, expect

def test_example(playwright: Playwright) -> None:
{chr(10).join('    ' + line for line in dedented_body)}

# For direct execution without pytest
if __name__ == '__main__':
    with sync_playwright() as playwright:
        test_example(playwright)
"""
                logger.info("Successfully extracted run() function body and wrapped in test_example()")
            else:
                # Fallback: just wrap the entire code
                logger.warning("Could not find run() function, wrapping entire code")
                code = f"""import re
from playwright.sync_api import Playwright, sync_playwright, expect

def test_example(playwright: Playwright) -> None:
{chr(10).join('    ' + line for line in code.split(chr(10)))}

# For direct execution without pytest
if __name__ == '__main__':
    with sync_playwright() as playwright:
        test_example(playwright)
"""
        
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        logger.info(f"Test saved to {test_file}")
        logger.info(f"Test code preview:\n{code[:500]}...")
        
        # Execute the test directly with Python (not pytest)
        try:
            import sys
            python_executable = sys.executable
            
            # Run the Python file directly - it has __main__ block that uses sync_playwright
            result = subprocess.run(
                [python_executable, test_file],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=temp_dir
            )
            
            # Parse results from execution
            execution_results = {
                'status': 'SUCCESS' if result.returncode == 0 else 'FAILED',
                'duration': 0,
                'steps': [],
                'output': result.stdout + '\n' + result.stderr
            }
            
            # Check if there were any errors in stderr
            if result.stderr and 'Error' in result.stderr:
                execution_results['steps'].append({
                    'status': 'FAIL',
                    'description': 'Test execution encountered errors',
                    'duration': 0
                })
            elif result.returncode == 0:
                execution_results['steps'].append({
                    'status': 'PASS',
                    'description': 'Test executed successfully',
                    'duration': 0
                })
            else:
                execution_results['steps'].append({
                    'status': 'FAIL',
                    'description': f'Test failed with exit code {result.returncode}',
                    'duration': 0
                })
            
            logger.info(f"Test execution completed. Return code: {result.returncode}")
            logger.info(f"Output length: {len(execution_results['output'])} chars")
            
            return jsonify({
                'success': True,
                'results': execution_results
            })
            
        finally:
            # Clean up temp file
            try:
                os.remove(test_file)
            except:
                pass
        
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Test execution timed out'}), 500
    except Exception as e:
        logger.error(f"Error executing test: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/automation-test-creator/export-results/<ticket_id>', methods=['POST'])
@jira_auth_required
def export_results_to_jira(ticket_id):
    """Export test execution results back to Jira as a comment"""
    try:
        data = request.json
        results = data.get('results', {})
        
        # Get Jira credentials
        access_token = session.get('jira_access_token')
        cloud_id = session.get('jira_cloud_id')
        
        if not access_token or not cloud_id:
            return jsonify({'success': False, 'error': 'Not authenticated with Jira'}), 401
        
        # Build ADF comment
        status = results.get('status', 'UNKNOWN')
        steps = results.get('steps', [])
        output = results.get('output', '')
        
        status_icon = '✓' if status == 'SUCCESS' else '✗'
        
        comment_adf = {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "🎭 Automation Test Execution Results"}]
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Status: "},
                        {"type": "text", "text": f"{status_icon} {status}", "marks": [{"type": "strong"}]}
                    ]
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"Executed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
                    ]
                }
            ]
        }
        
        # Add steps summary if available
        if steps and len(steps) > 0:
            passed = sum(1 for s in steps if s.get('status') == 'PASS')
            failed = len(steps) - passed
            
            comment_adf["content"].append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": f"Total Steps: {len(steps)} | Passed: {passed} | Failed: {failed}"}
                ]
            })
            
            # Add individual step results
            comment_adf["content"].append({
                "type": "heading",
                "attrs": {"level": 4},
                "content": [{"type": "text", "text": "Step Details"}]
            })
            
            for i, step in enumerate(steps, 1):
                step_status = step.get('status', 'UNKNOWN')
                step_desc = step.get('description', 'No description')
                step_icon = '✓' if step_status == 'PASS' else '✗'
                
                comment_adf["content"].append({
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"{step_icon} Step {i}: {step_desc}"}
                    ]
                })
        
        # Add execution output if available
        if output and len(output.strip()) > 0:
            comment_adf["content"].append({
                "type": "heading",
                "attrs": {"level": 4},
                "content": [{"type": "text", "text": "Execution Output"}]
            })
            
            # Truncate output if too long (Jira has limits)
            max_output_length = 5000
            if len(output) > max_output_length:
                output = output[:max_output_length] + "\n\n... (output truncated)"
            
            comment_adf["content"].append({
                "type": "codeBlock",
                "attrs": {"language": "text"},
                "content": [
                    {"type": "text", "text": output}
                ]
            })
        
        # Post comment to Jira
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        jira_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{ticket_id}/comment'
        comment_payload = {'body': comment_adf}
        
        logger.info(f"Posting comment to Jira: {ticket_id}")
        response = requests.post(jira_url, headers=headers, json=comment_payload, timeout=30)
        
        if response.status_code in [200, 201]:
            return jsonify({'success': True, 'comment_id': response.json().get('id')})
        else:
            error_detail = response.text
            logger.error(f"Jira API error: {response.status_code} - {error_detail}")
            return jsonify({
                'success': False,
                'error': f'Failed to post comment: {response.status_code}',
                'details': error_detail
            }), response.status_code
        
    except Exception as e:
        logger.error(f"Error exporting results to Jira: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# End Automation Test Creator Routes
# ========================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

let recording = false;
let actions = [];

function getSelector(el) {
  if (el.id) return '#' + el.id;
  let path = '';
  while (el && el.nodeType === 1 && el !== document.body) {
    let sib = el, nth = 1;
    while ((sib = sib.previousElementSibling)) if (sib.tagName === el.tagName) nth++;
    path = el.tagName.toLowerCase() + (nth > 1 ? `:nth-child(${nth})` : '') + (path ? '>' + path : '');
    el = el.parentElement;
  }
  return path;
}

function recordEvent(e) {
  if (!recording) return;
  let action = null;
  if (e.type === 'click') {
    action = {type: 'click', selector: getSelector(e.target)};
  } else if (e.type === 'input') {
    action = {type: 'input', selector: getSelector(e.target), value: e.target.value};
  } else if (e.type === 'change' && e.target.tagName === 'SELECT') {
    action = {type: 'select', selector: getSelector(e.target), value: e.target.value};
  }
  if (action) {
    actions.push(action);
    chrome.storage.local.set({seleniumActions: actions});
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg === 'start-recording') {
    recording = true;
    actions = [{type: 'url', url: location.href}];
    chrome.storage.local.set({seleniumActions: actions});
    window.addEventListener('click', recordEvent, true);
    window.addEventListener('input', recordEvent, true);
    window.addEventListener('change', recordEvent, true);
    alert('Selenium Recorder: Recording started!');
    sendResponse('started');
  } else if (msg === 'stop-recording') {
    recording = false;
    window.removeEventListener('click', recordEvent, true);
    window.removeEventListener('input', recordEvent, true);
    window.removeEventListener('change', recordEvent, true);
    alert('Selenium Recorder: Recording stopped!');
    sendResponse('stopped');
  } else if (msg === 'get-actions') {
    sendResponse(actions);
  }
});
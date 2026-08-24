/* Rudra floating assistant — decoupled frontend widget.
 *
 * Contract with the backend (see src/rudra/):
 *   POST {chatUrl}  JSON  {message, context, conversation_id, stream:true}
 *     → text/event-stream, lines "data: {json}":
 *         {"type":"start","conversation_id","tools_used"}
 *         {"type":"delta","text"}
 *         {"type":"done","message_id","provider","sources":[{label,url}]}
 *         {"type":"error","error"}
 *     → or stream:false for a single JSON reply.
 *   GET  {suggestionsUrl} → {"suggestions":[{id,text}]}
 *   POST {feedbackUrl}    {message_id, feedback:"up"|"down"|null}
 *   POST {newChatUrl} / {clearUrl}
 *
 * The widget never touches app internals; it renders whatever it is given
 * and degrades to an error card on any failure.
 */
(function () {
  'use strict';

  var root = document.getElementById('rudra-widget');
  if (!root) return;

  var cfg = {};
  try {
    cfg = JSON.parse(root.getAttribute('data-rudra-config') || '{}');
  } catch (err) { /* keep defaults */ }

  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  var launcher = root.querySelector('#rw-launcher');
  var panel = root.querySelector('#rw-panel');
  var messagesEl = root.querySelector('#rw-messages');
  var statusEl = root.querySelector('#rw-status');
  var suggestionsEl = root.querySelector('#rw-suggestions');
  var form = root.querySelector('#rw-composer');
  var input = root.querySelector('#rw-input');
  var sendBtn = root.querySelector('#rw-send');
  var minimizeBtn = root.querySelector('#rw-minimize');
  var newChatBtn = root.querySelector('#rw-new-chat');

  var state = {
    open: false,
    busy: false,
    conversationId: null,
    lastUserMessage: null,
    suggestionsShown: {},
    currentSources: []
  };

  function setState(next) {
    root.setAttribute('data-state', next);
    if (next === 'loading') statusEl.textContent = 'Rudra is thinking…';
    else if (next === 'streaming') statusEl.textContent = 'Rudra is replying…';
    else statusEl.textContent = 'AI Career Assistant · advisory only';
    sendBtn.disabled = state.busy;
  }

  /* ---------- rendering ---------- */

  function addMessage(kind, text) {
    var el = document.createElement(kind === 'user' ? 'div' : 'div');
    el.className = 'rw-msg ' + (kind === 'user' ? 'rw-msg-user' : 'rw-msg-bot');
    el.textContent = text;
    messagesEl.appendChild(el);
    scrollToEnd();
    return el;
  }

  function scrollToEnd() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function showEmptyOnce() {
    if (!messagesEl.children.length) {
      var empty = document.createElement('p');
      empty.className = 'rw-empty';
      empty.textContent = 'Namaste! Ask me about eligibility, deadlines, or how to prepare.';
      messagesEl.appendChild(empty);
    }
  }

  function clearEmpty() {
    var empties = messagesEl.querySelectorAll('.rw-empty');
    empties.forEach(function (el) { el.remove(); });
  }

  function showError(message) {
    setState('idle');
    state.busy = false;
    var card = document.createElement('div');
    card.className = 'rw-error';
    var span = document.createElement('span');
    span.textContent = message || 'Something went wrong.';
    var retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'rw-retry';
    retry.textContent = 'Retry';
    retry.addEventListener('click', function () {
      card.remove();
      if (state.lastUserMessage) send(state.lastUserMessage);
    });
    card.appendChild(span);
    card.appendChild(retry);
    messagesEl.appendChild(card);
    scrollToEnd();
  }

  function attachAssistantActions(msgEl, metaRow, messageId) {
    var copyBtn = chipButton('Copy', false);
    copyBtn.addEventListener('click', function () {
      navigator.clipboard.writeText(msgEl.textContent).then(function () {
        copyBtn.textContent = 'Copied';
        setTimeout(function () { copyBtn.textContent = 'Copy'; }, 1200);
      }).catch(function () {});
    });

    metaRow.appendChild(copyBtn);

    if (!messageId) return;

    function feedbackButton(kind) {
      var b = chipButton(kind === 'up' ? '👍' : '👎', false);
      b.setAttribute('aria-label', 'Rate reply ' + (kind === 'up' ? 'helpful' : 'unhelpful'));
      b.addEventListener('click', function () {
        var active = b.getAttribute('aria-pressed') === 'true';
        postJSON(cfg.feedbackUrl, {
          message_id: messageId,
          feedback: active ? null : kind
        }).then(function () {
          metaRow.querySelectorAll('[data-feedback]').forEach(function (other) {
            other.setAttribute('aria-pressed', 'false');
          });
          b.setAttribute('aria-pressed', active ? 'false' : 'true');
        }).catch(function () {});
      });
      b.setAttribute('data-feedback', kind);
      return b;
    }
    metaRow.appendChild(feedbackButton('up'));
    metaRow.appendChild(feedbackButton('down'));

    if (state.currentSources.length) {
      var wrap = document.createElement('div');
      wrap.className = 'rw-sources';
      state.currentSources.forEach(function (src) {
        var link = document.createElement('a');
        link.className = 'rw-source';
        link.href = src.url || '#';
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = src.label || 'source';
        wrap.appendChild(link);
      });
      messagesEl.insertBefore(wrap, metaRow.nextSibling);
      scrollToEnd();
    }
  }

  function chipButton(label, pressed) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'rw-chip-btn';
    b.textContent = label;
    b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    return b;
  }

  /* ---------- suggestions ---------- */

  var DISMISS_KEY = 'rudra_dismissed_suggestions';

  function dismissedIds() {
    try {
      return JSON.parse(localStorage.getItem(DISMISS_KEY) || '{}');
    } catch (err) { return {}; }
  }

  function rememberDismissal(id) {
    var store = dismissedIds();
    store[id] = Date.now();
    try { localStorage.setItem(DISMISS_KEY, JSON.stringify(store)); } catch (err) {}
  }

  function renderSuggestions(list) {
    suggestionsEl.innerHTML = '';
    suggestionsEl.hidden = true;
    var visible = list.filter(function (s) {
      var seen = dismissedIds()[s.id];
      return !seen;
    }).slice(0, 2);

    visible.forEach(function (s) {
      var row = document.createElement('div');
      row.className = 'rw-suggestion';

      var use = document.createElement('button');
      use.type = 'button';
      use.className = 'rw-suggestion-text';
      use.textContent = s.text;
      use.addEventListener('click', function () {
        hideSuggestions();
        send(s.text);
      });

      var dismiss = document.createElement('button');
      dismiss.type = 'button';
      dismiss.className = 'rw-suggestion-dismiss';
      dismiss.setAttribute('aria-label', 'Dismiss suggestion');
      dismiss.textContent = '×';
      dismiss.addEventListener('click', function () {
        rememberDismissal(s.id);
        row.remove();
        if (!suggestionsEl.children.length) suggestionsEl.hidden = true;
      });

      row.appendChild(use);
      row.appendChild(dismiss);
      suggestionsEl.appendChild(row);
    });

    if (visible.length && !state.suggestionsShown[pageKey()]) {
      suggestionsEl.hidden = false;
      state.suggestionsShown[pageKey()] = true;
    }
  }

  function hideSuggestions() {
    suggestionsEl.hidden = true;
  }

  function pageKey() {
    return (cfg.page || '') + ':' + (cfg.opportunityId || '');
  }

  function loadSuggestions() {
    getJSON(cfg.suggestionsUrl + '?page=' + encodeURIComponent(pageKey()))
      .then(function (data) {
        renderSuggestions((data && data.suggestions) || []);
      })
      .catch(function () {}); // suggestions are best-effort
  }

  /* ---------- networking ---------- */

  function getJSON(url) {
    return fetch(url, { credentials: 'same-origin' })
      .then(function (resp) {
        if (!resp.ok) throw new Error('http ' + resp.status);
        return resp.json();
      });
  }

  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf
      },
      body: JSON.stringify(body || {})
    }).then(function (resp) {
      if (!resp.ok) throw new Error('http ' + resp.status);
      return resp.json();
    });
  }

  function pageContext() {
    var context = { page: guessPage(), opportunity_id: cfg.opportunityId || null };
    return context;
  }

  function guessPage() {
    var p = window.location.pathname || '';
    if (cfg.opportunityId) return 'opportunity';
    if (p.indexOf('/resume') === 0) return 'resume';
    if (p.indexOf('/applications') === 0) return 'applications';
    if (p.indexOf('/saved') === 0) return 'saved';
    if (p === '/' || p === '') return 'dashboard';
    if (p.indexOf('/opportunit') === 0 || p === '/internships' ||
        p === '/fellowships' || p === '/top' || p === '/urgent') return 'opportunities';
    return 'dashboard';
  }

  /* ---------- chat flow ---------- */

  function send(text) {
    var message = (text !== undefined ? text : input.value).trim();
    if (!message || state.busy) return;
    clearEmpty();
    state.lastUserMessage = message;
    if (text === undefined) input.value = '';
    autoResize();

    addMessage('user', message);
    state.busy = true;
    hideSuggestions();
    setState('loading');

    var typing = document.createElement('div');
    typing.className = 'rw-typing';
    typing.innerHTML = '<span class="dots">Rudra is thinking</span>';
    messagesEl.appendChild(typing);
    scrollToEnd();

    fetch(cfg.chatUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf,
        'Accept': 'text/event-stream'
      },
      body: JSON.stringify({
        message: message,
        context: pageContext(),
        conversation_id: state.conversationId,
        stream: true
      })
    }).then(function (resp) {
      typing.remove();
      if (!resp.ok || !resp.body) {
        return resp.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.error || ('HTTP ' + resp.status));
        });
      }
      readStream(resp.body);
    }).catch(function () {
      typing.remove();
      showError('Rudra is unreachable right now.');
    });
  }

  function readStream(body) {
    var reader = body.getReader();
    var decoder = new TextDecoder();
    var botEl = null;
    var metaRow = null;
    var buffer = '';

    function handleEvent(evt) {
      if (evt.type === 'start') {
        state.conversationId = evt.conversation_id || state.conversationId;
        setState('streaming');
      } else if (evt.type === 'delta') {
        if (!botEl) {
          botEl = addMessage('bot', '');
          metaRow = document.createElement('div');
          metaRow.className = 'rw-msg-meta';
          messagesEl.appendChild(metaRow);
        }
        botEl.textContent += evt.text;
        scrollToEnd();
      } else if (evt.type === 'done') {
        state.currentSources = evt.sources || [];
        attachAssistantActions(botEl, metaRow, evt.message_id);
        finish();
      } else if (evt.type === 'error') {
        showError(evt.error);
      }
    }

    function finish() {
      state.busy = false;
      setState('idle');
      loadSuggestions();
      input.focus({ preventScroll: true });
    }

    function pump() {
      reader.read().then(function (result) {
        if (result.done) {
          if (!botEl && !state.busy) return;
          if (state.busy) showError('The connection dropped mid-reply.');
          return;
        }
        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split('\n');
        buffer = lines.pop();
        lines.forEach(function (line) {
          var m = line.match(/^data:\s?(.*)$/);
          if (!m) return;
          var evt;
          try { evt = JSON.parse(m[1]); } catch (err) { return; }
          handleEvent(evt);
        });
        pump();
      }).catch(function () {
        showError('Network error while streaming the reply.');
      });
    }

    pump();
  }

  /* ---------- controls ---------- */

  function openPanel() {
    state.open = true;
    panel.hidden = false;
    root.setAttribute('data-open', 'true');
    launcher.setAttribute('aria-expanded', 'true');
    showEmptyOnce();
    setState('idle');
    input.focus({ preventScroll: true });
    loadSuggestions();

    // Restore the latest conversation so the panel feels continuous.
    if (!messagesEl.children.length) restoreHistory();
  }

  function restoreHistory() {
    var historyEl = document.getElementById('rw-history');
    if (!historyEl) return;
    var rows;
    try { rows = JSON.parse(historyEl.textContent || '[]'); } catch (err) { return; }
    if (!rows.length) return;
    clearEmpty();
    rows.forEach(function (row) {
      if (row.role === 'user' || row.role === 'assistant') {
        addMessage(row.role === 'user' ? 'user' : 'bot', row.content);
      }
    });
    if (rows.length && rows[0].conversation_id) {
      state.conversationId = rows[0].conversation_id;
    }
  }

  function closePanel() {
    state.open = false;
    root.setAttribute('data-open', 'false');
    panel.hidden = true;
    launcher.setAttribute('aria-expanded', 'false');
    launcher.focus({ preventScroll: true });
  }

  launcher.addEventListener('click', openPanel);
  minimizeBtn.addEventListener('click', closePanel);

  newChatBtn.addEventListener('click', function () {
    postJSON(cfg.newChatUrl, {}).then(function (data) {
      state.conversationId = data.conversation_id || null;
      state.lastUserMessage = null;
      messagesEl.innerHTML = '';
      state.currentSources = [];
      showEmptyOnce();
    }).catch(function () {
      showError('Could not start a new conversation.');
    });
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && state.open &&
        document.activeElement !== input) {
      closePanel();
    }
  });
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && state.open) closePanel();
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    send();
  });

  function autoResize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 110) + 'px';
  }
  input.addEventListener('input', autoResize);

  setState('idle');
})();

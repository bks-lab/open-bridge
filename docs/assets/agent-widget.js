/* =============================================================================
 * open-bridge floating chat widget — self-contained vanilla JS.
 *
 * A floating bubble launcher (bottom-right) + a slide-up chat panel that talks
 * to an A2A agent. No framework, no build step, no dependencies, and NO external
 * loads (all CSS + SVG inline; the only network calls are to the configured
 * agent endpoint). Escape-first, XSS-safe rendering of agent replies.
 *
 * ENDPOINT RESOLUTION — the widget names NO host itself. It reads the endpoint
 * from, in order:
 *   1. window.OB_AGENT_ENDPOINT  (set once in assets/agent-config.js)
 *   2. a data-agent-endpoint="…" attribute on this script's own <script> tag
 * If neither is present (or it is not a valid http/https URL), the widget stays
 * fully DORMANT: it builds no DOM and renders nothing. A fork with no agent
 * backend therefore shows no widget at all.
 *
 * A2A PROTOCOL (mirrors the reference client): JSON-RPC 2.0 over HTTP.
 *   - message/stream (SSE) preferred, message/send (buffered) as fallback
 *   - params.message = { role, parts:[{kind:'text',text}], messageId, contextId }
 *   - contextId persisted in localStorage (stable per browser)
 *   - agent-card fetched from <endpoint>/.well-known/agent-card.json
 *
 * THEME + LANGUAGE — the widget inherits the site's design tokens (CSS custom
 * properties), so light/dark "just work" via the page's `html.dark` class. UI
 * strings ship in EN + DE; the active language follows the page's
 * `data-active-lang` / `lang` (open-bridge's ob-lang switch), EN default, and
 * re-localizes live when the visitor flips the site language.
 * ========================================================================== */

(function () {
  'use strict';

  // Capture this script tag NOW (document.currentScript is only valid during the
  // script's own synchronous top-level execution) so we can read a per-tag
  // data-agent-endpoint override if the global is not used.
  var THIS_SCRIPT = document.currentScript;

  // --- Endpoint resolution → dormant if unset/invalid -----------------------
  function resolveEndpoint() {
    var ep = '';
    try {
      if (window.OB_AGENT_ENDPOINT) ep = String(window.OB_AGENT_ENDPOINT).trim();
    } catch (e) {}
    if (!ep && THIS_SCRIPT && THIS_SCRIPT.getAttribute) {
      ep = (THIS_SCRIPT.getAttribute('data-agent-endpoint') || '').trim();
    }
    return ep;
  }

  var ENDPOINT_RAW = resolveEndpoint();
  if (!ENDPOINT_RAW) return; // DORMANT: no endpoint configured.

  var ENDPOINT, ENDPOINT_ORIGIN;
  try {
    var _u = new URL(ENDPOINT_RAW);
    if (_u.protocol !== 'https:' && _u.protocol !== 'http:') return; // DORMANT
    ENDPOINT = ENDPOINT_RAW.replace(/\/+$/, ''); // trim trailing slashes
    ENDPOINT_ORIGIN = _u.origin;
  } catch (e) {
    return; // DORMANT: not a URL
  }

  // Deferred scripts run after the document is parsed, so document.body exists;
  // guard anyway in case the widget is loaded non-deferred.
  if (document.body) {
    boot();
  } else {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  }

  function boot() {
    if (document.getElementById('ob-agent-widget-root')) return; // idempotent

    // ── i18n bundles (vocabulary translation only; EN default) ──────────────
    var STRINGS = {
      en: {
        launcherLabel: 'Ask the open-bridge assistant',
        launcherText: 'Ask about open-bridge',
        headerTitle: 'open-bridge assistant',
        headerSubtitle: 'Ask anything about the project',
        inputPlaceholder: 'Ask about open-bridge…',
        send: 'Send',
        close: 'Close',
        greeting: 'Hi! I can answer questions about **open-bridge** — what it is, how the CORE/USER split works, skills, the session-start flow, and how to get started. What would you like to know?',
        connecting: 'Connecting…',
        working: 'Thinking…',
        errorConnect: "I couldn't reach the assistant just now. Please try again in a moment.",
        errorSend: 'Something went wrong sending that. Please try again.',
        errorAgent: 'The assistant ran into a problem answering that.',
        emptyAnswer: "I didn't get a response for that. Try rephrasing your question.",
        retry: 'Try again',
        maximize: 'Enlarge',
        restore: 'Restore size',
        resize: 'Drag to resize',
        cardOpen: 'Show agent card',
        cardBack: 'Back to chat',
        cardTitle: 'Agent card',
        cardIntro: 'This is the live A2A capability card the assistant advertises.',
        cardProtocol: 'A2A protocol',
        cardEndpoint: 'Endpoint',
        cardModes: 'I/O',
        cardSkills: 'Skills',
        cardExamplesHint: 'Try one:',
        cardStreaming: 'Streaming',
        cardPush: 'Push',
        cardLoading: 'Loading…',
        cardUnavailable: 'Agent card unavailable right now.',
        privacyNote: 'Messages are sent to the connected agent to answer your question.'
      },
      de: {
        launcherLabel: 'Den open-bridge Assistenten fragen',
        launcherText: 'open-bridge fragen',
        headerTitle: 'open-bridge Assistent',
        headerSubtitle: 'Frag alles zum Projekt',
        inputPlaceholder: 'Frag etwas zu open-bridge…',
        send: 'Senden',
        close: 'Schließen',
        greeting: 'Hallo! Ich beantworte Fragen zu **open-bridge** — was es ist, wie der CORE/USER-Split funktioniert, Skills, der Session-Start-Ablauf und der Einstieg. Was möchtest du wissen?',
        connecting: 'Verbinde…',
        working: 'Denke nach…',
        errorConnect: 'Ich konnte den Assistenten gerade nicht erreichen. Bitte versuch es gleich noch einmal.',
        errorSend: 'Beim Senden ist etwas schiefgelaufen. Bitte versuch es erneut.',
        errorAgent: 'Der Assistent hatte ein Problem bei der Beantwortung.',
        emptyAnswer: 'Darauf kam keine Antwort. Formulier die Frage gern anders.',
        retry: 'Erneut versuchen',
        maximize: 'Vergrößern',
        restore: 'Größe zurücksetzen',
        resize: 'Zum Ändern der Größe ziehen',
        cardOpen: 'Agent-Card anzeigen',
        cardBack: 'Zurück zum Chat',
        cardTitle: 'Agent-Card',
        cardIntro: 'Das ist die live A2A-Capability-Card, die der Assistent bereitstellt.',
        cardProtocol: 'A2A-Protokoll',
        cardEndpoint: 'Endpunkt',
        cardModes: 'I/O',
        cardSkills: 'Skills',
        cardExamplesHint: 'Probier eine:',
        cardStreaming: 'Streaming',
        cardPush: 'Push',
        cardLoading: 'Lade…',
        cardUnavailable: 'Agent-Card gerade nicht verfügbar.',
        privacyNote: 'Nachrichten werden zur Beantwortung an den verbundenen Agenten gesendet.'
      }
    };

    function detectLang() {
      var r = document.documentElement;
      var l = (r.getAttribute('data-active-lang') || r.getAttribute('lang') || 'en').toLowerCase();
      return l.indexOf('de') === 0 ? 'de' : 'en';
    }
    var lang = detectLang();
    var t = STRINGS[lang];

    // ── localStorage keys (namespaced so a fork's other state never collides) ─
    var CONTEXT_KEY = 'obAgentContextId';
    var SIZE_KEY = 'obAgentWidgetSize';
    var OPEN_KEY = 'obAgentWidgetOpen';

    // ── Terminal A2A task states that mean "stopped without an answer" ────────
    var FAILED_STATES = { failed: 1, canceled: 1, cancelled: 1, rejected: 1, unknown: 1 };

    // ── Inline SVG glyphs (no external image loads) ──────────────────────────
    var SVG_CHAT =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>';

    // =========================================================================
    // STYLE — inline, namespaced under #ob-agent-widget-root / .obw-*.
    // Colors pull from the site's DESIGN.md tokens (--surface / --on-surface /
    // --accent / --accent-from|to / --border / --font-*), so light + dark follow
    // the page automatically. Fallbacks keep the widget sane on a token-less page.
    // =========================================================================
    var CSS = [
      '#ob-agent-widget-root{',
      '--obw-w:380px;--obw-h:560px;--obw-max-w:min(720px,92vw);--obw-max-h:min(840px,90vh);',
      '--obw-radius:var(--r-xl,16px);--obw-radius-md:var(--r-md,8px);--obw-radius-sm:var(--r-sm,4px);',
      '--obw-pad:16px;--obw-gap:8px;',
      '--obw-surface:var(--surface,#ffffff);',
      '--obw-text:var(--on-surface,#374151);',
      '--obw-heading:var(--primary,#111827);',
      '--obw-muted:var(--secondary,#6b7280);',
      '--obw-accent:var(--accent,#6366f1);',
      '--obw-accent-text:var(--accent-text,var(--accent,#4f46e5));',
      '--obw-grad:linear-gradient(135deg,var(--accent-from,#667eea) 0%,var(--accent-to,#764ba2) 100%);',
      '--obw-border:var(--border,color-mix(in srgb,var(--on-surface,#374151) 14%,transparent));',
      '--obw-border-strong:color-mix(in srgb,var(--on-surface,#374151) 22%,transparent);',
      '--obw-elev-panel:0 16px 48px -8px rgba(0,0,0,.18),0 4px 12px -4px rgba(0,0,0,.10);',
      '--obw-elev-launcher:0 8px 24px -6px rgba(0,0,0,.28),0 2px 6px -2px rgba(0,0,0,.18);',
      'font-family:var(--font-sans,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif);font-weight:400;}',
      'html.dark #ob-agent-widget-root{',
      '--obw-elev-panel:0 16px 48px -8px rgba(0,0,0,.55),0 4px 12px -4px rgba(0,0,0,.35);',
      '--obw-elev-launcher:0 8px 24px -6px rgba(0,0,0,.6),0 2px 6px -2px rgba(0,0,0,.4);}',
      '@media print{#ob-agent-widget-root{display:none !important;}}',

      /* launcher */
      '#obw-launcher{position:fixed;bottom:1.25rem;right:1.25rem;z-index:2147483000;width:56px;height:56px;border-radius:9999px;border:none;cursor:pointer;background:var(--obw-grad);color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:var(--obw-elev-launcher);transition:transform .2s ease-out,box-shadow .2s ease-out,filter .2s ease-out;}',
      '#obw-launcher:hover{transform:translateY(-2px);filter:brightness(1.06);}',
      '#obw-launcher:active{transform:translateY(0);}',
      '#obw-launcher:focus-visible{outline:2px solid var(--obw-accent);outline-offset:3px;}',
      '#obw-launcher svg{width:26px;height:26px;}',
      '#obw-launcher.obw-hidden{display:none;}',

      '#obw-label{position:fixed;bottom:1.55rem;right:5.45rem;z-index:2147483000;display:inline-flex;align-items:center;gap:7px;max-width:min(260px,calc(100vw - 7rem));padding:8px 11px;border:1px solid var(--obw-border);border-radius:9999px;background:color-mix(in srgb,var(--obw-surface) 86%,transparent);color:var(--obw-text);box-shadow:0 8px 24px -12px rgba(0,0,0,.45);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);cursor:pointer;font:inherit;font-size:.78rem;line-height:1.1;transition:transform .2s ease-out,border-color .2s ease-out;}',
      '#obw-label:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--obw-accent) 38%,transparent);}',
      '#obw-label.obw-hidden{display:none;}',
      '.obw-label-dot{width:6px;height:6px;border-radius:9999px;background:var(--obw-accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--obw-accent) 12%,transparent);flex-shrink:0;}',
      '.obw-label-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',

      /* panel */
      '#obw-panel{position:fixed;bottom:1.25rem;right:1.25rem;z-index:2147483001;width:var(--obw-w);height:var(--obw-h);max-width:95vw;max-height:92vh;min-width:320px;min-height:420px;display:flex;flex-direction:column;background:var(--obw-surface);color:var(--obw-text);border:1px solid var(--obw-border);border-radius:16px;box-shadow:var(--obw-elev-panel);overflow:hidden;margin:0;padding:0;animation:obw-pop .2s ease-out;}',
      '#obw-panel[hidden]{display:none;}',
      '#obw-panel.obw-resizing{animation:none;user-select:none;}',
      '#obw-panel.obw-is-max{width:var(--obw-max-w);height:var(--obw-max-h);}',
      '@keyframes obw-pop{from{opacity:0;transform:translateY(12px) scale(.98);}to{opacity:1;transform:translateY(0) scale(1);}}',

      /* resize grip */
      '.obw-resize-handle{position:absolute;top:0;left:0;width:22px;height:22px;z-index:2;cursor:nwse-resize;display:flex;align-items:flex-start;justify-content:flex-start;padding:5px 0 0 5px;color:var(--obw-muted);opacity:.55;transition:opacity .18s ease-out;touch-action:none;}',
      '.obw-resize-handle:hover{opacity:1;}',
      '.obw-resize-handle svg{width:12px;height:12px;}',

      /* header */
      '#obw-header{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--obw-gap);padding:14px 14px 14px 26px;background:color-mix(in srgb,var(--obw-text) 3%,var(--obw-surface));border-bottom:1px solid var(--obw-border);}',
      '.obw-header-text{min-width:0;}',
      '.obw-header-actions{display:flex;align-items:center;gap:2px;flex-shrink:0;}',
      '#obw-title{font-size:.9375rem;font-weight:600;line-height:1.25;letter-spacing:-.01em;margin:0;color:var(--obw-heading);}',
      '#obw-subtitle{font-size:.75rem;font-weight:400;line-height:1.4;margin:3px 0 0;color:var(--obw-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.obw-icon-btn{flex-shrink:0;background:transparent;border:none;color:var(--obw-muted);cursor:pointer;width:30px;height:30px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;transition:background-color .15s ease-out;}',
      '.obw-icon-btn:hover{color:var(--obw-heading);background:color-mix(in srgb,var(--obw-text) 9%,transparent);}',
      '.obw-icon-btn:focus-visible{outline:2px solid var(--obw-accent);outline-offset:1px;}',
      '.obw-icon-btn:disabled{opacity:.4;cursor:not-allowed;}',
      '.obw-icon-btn svg{width:16px;height:16px;}',
      '.obw-ico-restore{display:none;}',
      '#obw-panel.obw-is-max .obw-ico-expand{display:none;}',
      '#obw-panel.obw-is-max .obw-ico-restore{display:inline-flex;}',
      '.obw-ico-chat{display:none;}',
      '#obw-panel.obw-show-card .obw-ico-card{display:none;}',
      '#obw-panel.obw-show-card .obw-ico-chat{display:inline-flex;}',

      /* messages */
      '#obw-messages{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:var(--obw-pad);display:flex;flex-direction:column;gap:var(--obw-gap);font-size:.875rem;line-height:1.6;scrollbar-width:thin;scrollbar-color:var(--obw-border-strong) transparent;}',
      '#obw-messages::-webkit-scrollbar{width:8px;}',
      '#obw-messages::-webkit-scrollbar-track{background:transparent;}',
      '#obw-messages::-webkit-scrollbar-thumb{background:var(--obw-border-strong);border-radius:9999px;border:2px solid transparent;background-clip:padding-box;}',

      /* rows */
      '.obw-row{display:flex;gap:8px;align-items:flex-end;max-width:92%;animation:obw-msg-in .18s ease-out;}',
      '.obw-row-user{align-self:flex-end;justify-content:flex-end;}',
      '.obw-row-agent{align-self:flex-start;}',
      '@keyframes obw-msg-in{from{opacity:0;transform:translateY(4px);}to{opacity:1;transform:translateY(0);}}',
      '.obw-avatar{flex-shrink:0;width:28px;height:28px;border-radius:9999px;display:flex;align-items:center;justify-content:center;margin-bottom:1px;background:color-mix(in srgb,var(--obw-accent) 16%,var(--obw-surface));color:var(--obw-accent);border:1px solid color-mix(in srgb,var(--obw-accent) 30%,transparent);}',
      '.obw-avatar svg{width:15px;height:15px;}',

      /* bubbles */
      '.obw-msg{max-width:100%;padding:8px 12px;border-radius:12px;word-wrap:break-word;overflow-wrap:anywhere;}',
      '.obw-msg.obw-user{background:var(--obw-grad);color:#fff;border-bottom-right-radius:4px;box-shadow:0 2px 6px -2px color-mix(in srgb,var(--obw-accent) 55%,transparent);}',
      '.obw-msg.obw-user a{color:#fff;}',
      '.obw-msg.obw-agent{background:color-mix(in srgb,var(--obw-text) 6%,var(--obw-surface));border:1px solid var(--obw-border-strong);color:var(--obw-text);border-bottom-left-radius:4px;box-shadow:0 1px 3px -1px rgba(0,0,0,.10);}',
      '.obw-msg.obw-error{background:color-mix(in srgb,#c0392b 16%,var(--obw-surface));border:1px solid color-mix(in srgb,#c0392b 38%,transparent);color:var(--obw-text);border-bottom-left-radius:4px;}',
      '.obw-msg a{color:inherit;text-decoration:underline;text-underline-offset:2px;}',
      '.obw-msg.obw-agent a{color:var(--obw-accent-text);}',
      '.obw-msg strong{font-weight:600;}',
      '.obw-msg p:first-child{margin-top:0;}',
      '.obw-msg p:last-child{margin-bottom:0;}',
      '.obw-retry{display:inline-block;margin-top:.5rem;padding:.3rem .7rem;font:inherit;font-size:.78rem;line-height:1.2;cursor:pointer;border-radius:8px;border:1px solid color-mix(in srgb,var(--obw-text) 22%,transparent);background:color-mix(in srgb,var(--obw-text) 8%,transparent);color:var(--obw-text);transition:background-color .15s ease-out,opacity .15s ease-out;}',
      '.obw-retry:hover:not(:disabled){background:color-mix(in srgb,var(--obw-text) 16%,transparent);}',
      '.obw-retry:disabled{opacity:.5;cursor:not-allowed;}',

      /* working indicator */
      '.obw-working{display:flex;align-items:center;gap:var(--obw-gap);font-size:.75rem;color:var(--obw-muted);padding:6px 12px;background:color-mix(in srgb,var(--obw-text) 6%,var(--obw-surface));border:1px solid var(--obw-border-strong);border-radius:12px;border-bottom-left-radius:4px;box-shadow:0 1px 3px -1px rgba(0,0,0,.10);}',
      '.obw-dots{display:inline-flex;gap:3px;flex-shrink:0;}',
      '.obw-dots span{width:5px;height:5px;border-radius:9999px;background:var(--obw-accent);animation:obw-blink 1.2s infinite ease-in-out both;}',
      '.obw-dots span:nth-child(2){animation-delay:.2s;}',
      '.obw-dots span:nth-child(3){animation-delay:.4s;}',
      '@keyframes obw-blink{0%,80%,100%{opacity:.25;}40%{opacity:1;}}',
      '.obw-step{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;font-size:.6875rem;letter-spacing:.04em;}',

      /* safe-markdown blocks */
      '.obw-msg.obw-agent .obw-md-p,.obw-msg.obw-error .obw-md-p{margin:0 0 .5rem;}',
      '.obw-msg.obw-agent .obw-md-p:last-child,.obw-msg.obw-error .obw-md-p:last-child{margin-bottom:0;}',
      '.obw-msg.obw-agent .obw-md-h{font-weight:600;line-height:1.25;margin:.6rem 0 .35rem;color:var(--obw-heading);}',
      '.obw-msg.obw-agent h4.obw-md-h{font-size:1rem;}',
      '.obw-msg.obw-agent h5.obw-md-h{font-size:.9rem;}',
      '.obw-msg.obw-agent h6.obw-md-h{font-size:.82rem;color:var(--obw-muted);}',
      '.obw-msg.obw-agent .obw-md-h:first-child{margin-top:0;}',
      '.obw-msg.obw-agent .obw-md-list{margin:.25rem 0 .5rem;padding-left:1.25rem;}',
      '.obw-msg.obw-agent .obw-md-list li{margin:.1rem 0;}',
      '.obw-msg.obw-agent .obw-md-nested{margin:.15rem 0;padding-left:1.1rem;}',
      '.obw-msg.obw-agent ul.obw-md-list{list-style:disc;}',
      '.obw-msg.obw-agent ol.obw-md-list{list-style:decimal;}',
      '.obw-msg.obw-agent .obw-md-quote{margin:.4rem 0;padding:.3rem .7rem;border-left:3px solid color-mix(in srgb,var(--obw-accent) 60%,transparent);background:color-mix(in srgb,var(--obw-text) 5%,transparent);color:var(--obw-muted);border-radius:0 6px 6px 0;}',
      '.obw-msg.obw-agent .obw-md-code,.obw-msg.obw-agent .obw-md-pre code{font-family:var(--font-mono,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);font-size:.8em;}',
      '.obw-msg.obw-agent .obw-md-code{background:color-mix(in srgb,var(--obw-text) 10%,transparent);border:1px solid var(--obw-border);border-radius:4px;padding:.05em .35em;white-space:nowrap;}',
      '.obw-msg.obw-agent .obw-md-pre{margin:.4rem 0;padding:.6rem .7rem;background:color-mix(in srgb,var(--obw-text) 7%,var(--obw-surface));border:1px solid var(--obw-border);border-radius:8px;overflow-x:auto;-webkit-overflow-scrolling:touch;}',
      '.obw-msg.obw-agent .obw-md-pre code{display:block;white-space:pre;color:var(--obw-text);}',

      /* GFM tables */
      '.obw-msg.obw-agent .obw-md-table-wrap{margin:.5rem 0;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--obw-border);border-radius:8px;}',
      '.obw-msg.obw-agent .obw-md-table{border-collapse:collapse;width:100%;table-layout:auto;font-size:.78rem;line-height:1.45;}',
      '.obw-msg.obw-agent .obw-md-table th,.obw-msg.obw-agent .obw-md-table td{padding:.4rem .6rem;border-bottom:1px solid var(--obw-border);border-right:1px solid color-mix(in srgb,var(--obw-text) 7%,transparent);text-align:left;vertical-align:top;white-space:normal;overflow-wrap:anywhere;word-break:normal;hyphens:auto;min-width:4.5rem;max-width:22rem;}',
      '.obw-msg.obw-agent .obw-md-table th:last-child,.obw-msg.obw-agent .obw-md-table td:last-child{border-right:none;}',
      '.obw-msg.obw-agent .obw-md-table th:first-child,.obw-msg.obw-agent .obw-md-table td:first-child{overflow-wrap:normal;min-width:5.5rem;max-width:14rem;}',
      '.obw-msg.obw-agent .obw-md-table thead th{background:color-mix(in srgb,var(--obw-accent) 14%,var(--obw-surface));color:var(--obw-heading);font-weight:600;border-bottom:1px solid color-mix(in srgb,var(--obw-text) 16%,transparent);}',
      '.obw-msg.obw-agent .obw-md-table tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--obw-text) 4%,transparent);}',
      '.obw-msg.obw-agent .obw-md-table tbody tr:last-child td{border-bottom:none;}',
      '.obw-msg.obw-agent .obw-md-table td[style*="right"],.obw-msg.obw-agent .obw-md-table th[style*="right"]{white-space:nowrap;font-variant-numeric:tabular-nums;}',
      '.obw-msg.obw-agent .obw-md-table code.obw-md-code{white-space:normal;overflow-wrap:anywhere;}',
      '.obw-msg.obw-agent .obw-md-table.obw-md-wide th,.obw-msg.obw-agent .obw-md-table.obw-md-wide td{white-space:nowrap;max-width:none;min-width:6.5rem;}',
      '.obw-msg.obw-agent .obw-md-table.obw-md-wide th:first-child,.obw-msg.obw-agent .obw-md-table.obw-md-wide td:first-child{min-width:6.5rem;max-width:none;}',

      /* agent-card view */
      '#obw-card{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:var(--obw-pad);scrollbar-width:thin;scrollbar-color:var(--obw-border-strong) transparent;}',
      '#obw-panel.obw-show-card #obw-messages{display:none;}',
      '#obw-panel.obw-show-card #obw-card{display:flex;flex-direction:column;}',
      '#obw-card::-webkit-scrollbar{width:8px;}',
      '#obw-card::-webkit-scrollbar-thumb{background:var(--obw-border-strong);border-radius:9999px;border:2px solid transparent;background-clip:padding-box;}',
      '.obw-card-eyebrow{font-size:.6875rem;letter-spacing:.08em;text-transform:uppercase;color:var(--obw-accent-text);font-weight:600;margin:0 0 .25rem;}',
      '.obw-card-name{font-size:1.05rem;font-weight:600;line-height:1.25;margin:0 0 .35rem;color:var(--obw-heading);}',
      '.obw-card-desc{font-size:.82rem;line-height:1.5;color:var(--obw-text);margin:0 0 .5rem;white-space:pre-line;}',
      '.obw-card-intro{font-size:.72rem;line-height:1.45;color:var(--obw-muted);margin:0 0 .5rem;}',
      '.obw-card-section{margin-top:.7rem;}',
      '.obw-card-section-h{font-size:.6875rem;letter-spacing:.06em;text-transform:uppercase;color:var(--obw-muted);font-weight:600;margin:0 0 .45rem;}',
      '.obw-card-badges{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:.5rem;}',
      '.obw-card-badge{font-size:.7rem;line-height:1;padding:.3rem .5rem;border-radius:9999px;background:color-mix(in srgb,var(--obw-accent) 14%,var(--obw-surface));border:1px solid color-mix(in srgb,var(--obw-accent) 28%,transparent);color:var(--obw-text);white-space:nowrap;}',
      '.obw-card-meta{font-size:.72rem;color:var(--obw-muted);margin:.15rem 0;word-break:break-word;}',
      '.obw-card-meta strong{color:var(--obw-heading);font-weight:600;}',
      '.obw-card-meta a{color:var(--obw-accent-text);text-decoration:underline;text-underline-offset:2px;}',
      '.obw-card-skill{padding:.55rem .65rem;margin-bottom:.5rem;background:color-mix(in srgb,var(--obw-text) 5%,var(--obw-surface));border:1px solid var(--obw-border);border-radius:10px;}',
      '.obw-card-skill-name{font-size:.82rem;font-weight:600;color:var(--obw-heading);margin:0;}',
      '.obw-card-skill-desc{font-size:.74rem;line-height:1.45;color:var(--obw-muted);margin-top:.15rem;white-space:pre-line;}',
      '.obw-card-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:.4rem;}',
      '.obw-card-tag{font-size:.66rem;color:var(--obw-muted);padding:.12rem .4rem;border-radius:4px;background:color-mix(in srgb,var(--obw-text) 8%,transparent);}',
      '.obw-card-ex-hint{font-size:.66rem;color:var(--obw-muted);margin:.5rem 0 .3rem;}',
      '.obw-card-examples{display:flex;flex-direction:column;gap:4px;}',
      '.obw-card-ex{text-align:left;font:inherit;font-size:.74rem;line-height:1.3;padding:.38rem .55rem;border-radius:8px;cursor:pointer;border:1px solid color-mix(in srgb,var(--obw-accent) 28%,transparent);background:color-mix(in srgb,var(--obw-accent) 8%,transparent);color:var(--obw-text);transition:background-color .15s ease-out;}',
      '.obw-card-ex::before{content:"\\203A  ";color:var(--obw-accent-text);font-weight:700;}',
      '.obw-card-ex:hover{background:color-mix(in srgb,var(--obw-accent) 16%,transparent);}',
      '.obw-card-ex:focus-visible{outline:2px solid var(--obw-accent);outline-offset:1px;}',
      '.obw-card-empty,.obw-card-loading{font-size:.8rem;color:var(--obw-muted);padding:.5rem 0;}',

      /* composer */
      '#obw-form{display:flex;align-items:flex-end;gap:var(--obw-gap);padding:10px 12px;border-top:1px solid var(--obw-border);background:color-mix(in srgb,var(--obw-text) 3%,var(--obw-surface));}',
      '#obw-input{flex:1 1 auto;min-width:0;padding:9px 12px;border-radius:8px;border:1px solid var(--obw-border);background:var(--obw-surface);color:var(--obw-text);font-size:.875rem;font-family:inherit;line-height:1.4;transition:border-color .15s ease-out,box-shadow .15s ease-out;}',
      '#obw-input::placeholder{color:var(--obw-muted);}',
      '#obw-input:focus-visible{outline:none;border-color:var(--obw-accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--obw-accent) 22%,transparent);}',
      '#obw-send{flex-shrink:0;width:38px;height:38px;border:none;border-radius:8px;background:var(--obw-grad);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform .15s ease-out,filter .15s ease-out,opacity .15s ease-out;}',
      '#obw-send:hover:not(:disabled){filter:brightness(1.06);transform:translateY(-1px);}',
      '#obw-send:active:not(:disabled){transform:translateY(0);}',
      '#obw-send:focus-visible{outline:2px solid var(--obw-accent);outline-offset:2px;}',
      '#obw-send:disabled{opacity:.5;cursor:not-allowed;}',
      '#obw-send svg{width:17px;height:17px;}',
      '.obw-privacy{margin:0;padding:0 12px 8px;font-size:.66rem;line-height:1.35;text-align:center;color:var(--obw-muted);}',

      /* mobile fullscreen */
      '@media (max-width:639px){',
      '#obw-panel,#obw-panel.obw-is-max{inset:0;width:100% !important;height:100% !important;max-width:100%;max-height:100%;min-width:0;min-height:0;border-radius:0;border:none;}',
      '.obw-resize-handle{display:none;}',
      '#obw-maximize{display:none;}',
      '#obw-header{padding-left:16px;}',
      '.obw-row{max-width:94%;}',
      '#obw-label{right:1rem;bottom:5.15rem;max-width:min(230px,calc(100vw - 2rem));font-size:.72rem;opacity:.92;}',
      '.obw-msg.obw-agent .obw-md-table{font-size:.75rem;}',
      '}',

      '@media (prefers-reduced-motion:reduce){',
      '#obw-panel,.obw-msg,.obw-working{animation:none;}',
      '#obw-launcher,#obw-send{transition:none;}',
      '.obw-dots span{animation:none;opacity:.6;}',
      '}'
    ].join('');

    var styleEl = document.createElement('style');
    styleEl.id = 'ob-agent-widget-style';
    styleEl.textContent = CSS;
    document.head.appendChild(styleEl);

    // ── Build the widget shell (trusted, hardcoded HTML — no untrusted bytes) ──
    var root = document.createElement('div');
    root.id = 'ob-agent-widget-root';
    root.innerHTML =
      '<button id="obw-launcher" type="button" aria-haspopup="dialog" aria-expanded="false" aria-controls="obw-panel">' + SVG_CHAT + '</button>' +
      '<button id="obw-label" type="button" aria-hidden="true" tabindex="-1"><span class="obw-label-dot"></span><span class="obw-label-text"></span></button>' +
      '<section id="obw-panel" role="dialog" aria-modal="false" aria-labelledby="obw-title" hidden>' +
        '<div id="obw-resize" class="obw-resize-handle" aria-hidden="true">' +
          '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><line x1="3" y1="11" x2="11" y2="3"></line><line x1="6" y1="12" x2="12" y2="6"></line></svg>' +
        '</div>' +
        '<header id="obw-header">' +
          '<div class="obw-header-text"><h2 id="obw-title"></h2><p id="obw-subtitle"></p></div>' +
          '<div class="obw-header-actions">' +
            '<button id="obw-cardbtn" type="button" class="obw-icon-btn">' +
              '<svg class="obw-ico-card" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"></rect><circle cx="8.5" cy="11" r="1.8"></circle><line x1="13" y1="10" x2="18" y2="10"></line><line x1="13" y1="13.5" x2="18" y2="13.5"></line><line x1="6.5" y1="15.6" x2="11" y2="15.6"></line></svg>' +
              '<svg class="obw-ico-chat" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>' +
            '</button>' +
            '<button id="obw-maximize" type="button" class="obw-icon-btn">' +
              '<svg class="obw-ico-expand" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>' +
              '<svg class="obw-ico-restore" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4 14 10 14 10 20"></polyline><polyline points="20 10 14 10 14 4"></polyline><line x1="14" y1="10" x2="21" y2="3"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>' +
            '</button>' +
            '<button id="obw-close" type="button" class="obw-icon-btn">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>' +
            '</button>' +
          '</div>' +
        '</header>' +
        '<div id="obw-messages" aria-live="polite" aria-atomic="false"></div>' +
        '<section id="obw-card" hidden></section>' +
        '<form id="obw-form" autocomplete="off">' +
          '<input id="obw-input" type="text" autocomplete="off" enterkeyhint="send">' +
          '<button id="obw-send" type="submit">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>' +
          '</button>' +
        '</form>' +
        '<p id="obw-privacy" class="obw-privacy" hidden></p>' +
      '</section>';
    document.body.appendChild(root);

    // ── Element refs ─────────────────────────────────────────────────────────
    var launcher = document.getElementById('obw-launcher');
    var launcherLabel = document.getElementById('obw-label');
    var panel = document.getElementById('obw-panel');
    var closeBtn = document.getElementById('obw-close');
    var maximizeBtn = document.getElementById('obw-maximize');
    var cardBtn = document.getElementById('obw-cardbtn');
    var cardEl = document.getElementById('obw-card');
    var resizeHandle = document.getElementById('obw-resize');
    var messagesEl = document.getElementById('obw-messages');
    var form = document.getElementById('obw-form');
    var input = document.getElementById('obw-input');
    var sendBtn = document.getElementById('obw-send');
    var titleEl = document.getElementById('obw-title');
    var subtitleEl = document.getElementById('obw-subtitle');
    var privacyWrap = document.getElementById('obw-privacy');

    // ── Mutable state ────────────────────────────────────────────────────────
    var panelOpen = false;
    var greeted = false;
    var cardFetched = false;
    var streamingSupported = true;
    var cardEverReached = false;
    var busy = false;
    var lastUserMessage = '';
    var agentCard = null;
    var cardInflight = null;
    var cardShown = false;
    var cardRendered = false;

    // ── contextId persistence ────────────────────────────────────────────────
    function uuid() {
      try {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
      } catch (e) {}
      return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        var r = (Math.random() * 16) | 0;
        var v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      });
    }
    function getContextId() {
      try {
        var id = localStorage.getItem(CONTEXT_KEY) || '';
        if (!id) { id = uuid(); localStorage.setItem(CONTEXT_KEY, id); }
        return id;
      } catch (e) { return uuid(); }
    }
    var contextId = getContextId();

    // =========================================================================
    // SAFE rich-text renderer — escape-FIRST, then re-introduce an audited subset.
    // The agent's output is influenced by untrusted public visitors (prompt
    // injection). escapeHtml() runs ONCE on the WHOLE raw string first; every
    // later step only inserts OUR OWN tags or matches already-escaped text, so
    // no visitor byte is ever re-interpreted as HTML.
    // =========================================================================
    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function safeUrl(escapedUrl) {
      var probe = escapedUrl.replace(/&amp;/g, '&');
      if (!/^https?:\/\//i.test(probe) && !/^mailto:/i.test(probe)) return null;
      if (!/^[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%&#]+$/.test(escapedUrl)) return null;
      return escapedUrl;
    }

    function inlineFormat(escaped) {
      var segs = escaped.split(/(`[^`]+`)/g);
      return segs.map(function (seg) {
        if (seg.length >= 2 && seg.charCodeAt(0) === 96 && seg.charCodeAt(seg.length - 1) === 96) {
          return '<code class="obw-md-code">' + seg.slice(1, -1) + '</code>';
        }
        var s = seg.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, text, url) {
          var href = safeUrl(url);
          if (!href) return m;
          return '<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + text + '</a>';
        });
        s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
        s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
        return s;
      }).join('');
    }

    function splitRow(line) {
      var tt = line.trim();
      if (tt.charAt(0) === '|') tt = tt.slice(1);
      if (tt.charAt(tt.length - 1) === '|') tt = tt.slice(0, -1);
      var cells = [];
      var cur = '';
      for (var i = 0; i < tt.length; i++) {
        if (tt[i] === '\\' && tt[i + 1] === '|') { cur += '|'; i++; continue; }
        if (tt[i] === '|') { cells.push(cur); cur = ''; continue; }
        cur += tt[i];
      }
      cells.push(cur);
      return cells.map(function (c) { return c.trim(); });
    }

    function parseAlignRow(line) {
      var cells = splitRow(line);
      if (cells.length === 0) return null;
      var aligns = [];
      for (var i = 0; i < cells.length; i++) {
        var c = cells[i];
        if (!/^:?-+:?$/.test(c)) return null;
        var left = c.charAt(0) === ':';
        var right = c.charAt(c.length - 1) === ':';
        aligns.push(left && right ? 'center' : right ? 'right' : left ? 'left' : 'none');
      }
      return aligns;
    }

    function buildList(lines, start, kind) {
      var anyItem = /^(\s*)(?:\d+\.|[-*+])\s+(.*)$/;
      var isOlLine = function (s) { return /^\s*\d+\.\s+/.test(s); };
      var i = start;
      var html = '<' + kind + ' class="obw-md-list">';
      var inNested = false;
      while (i < lines.length) {
        var m = anyItem.exec(lines[i]);
        if (!m) break;
        var indent = m[1].length;
        var content = inlineFormat(m[2]);
        if (indent >= 2) {
          if (!inNested) { html += '<ul class="obw-md-list obw-md-nested">'; inNested = true; }
          html += '<li>' + content + '</li>';
        } else {
          if ((kind === 'ol') !== isOlLine(lines[i])) break;
          if (inNested) { html += '</ul>'; inNested = false; }
          html += '<li>' + content + '</li>';
        }
        i++;
      }
      if (inNested) html += '</ul>';
      html += '</' + kind + '>';
      return { html: html, next: i };
    }

    // Strip any machine-only ⟦…⟧ directive sentinels from display (defensive:
    // this widget never acts on them), then normalise whitespace. Parsing the RAW
    // text is safe — ⟦ ⟧ are not HTML-special.
    function normalizeText(raw) {
      var text = String(raw == null ? '' : raw).replace(/⟦[^⟧]*⟧/g, '');
      text = text.replace(/⟦[^⟧]*$/, ''); // drop a not-yet-closed (streaming) sentinel
      text = text.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
      return text;
    }

    function safeMarkdown(raw) {
      var escaped = escapeHtml(normalizeText(raw));
      var lines = escaped.split('\n');
      var out = [];
      var i = 0;
      var para = [];
      var flushPara = function () {
        if (!para.length) return;
        out.push('<p class="obw-md-p">' + para.map(inlineFormat).join('<br>') + '</p>');
        para = [];
      };

      while (i < lines.length) {
        var line = lines[i];
        var trimmed = line.trim();

        if (/^```/.test(trimmed)) {
          flushPara();
          i++;
          var code = [];
          while (i < lines.length && !/^```/.test(lines[i].trim())) { code.push(lines[i]); i++; }
          i++;
          out.push('<pre class="obw-md-pre"><code>' + code.join('\n') + '</code></pre>');
          continue;
        }

        if (trimmed === '') { flushPara(); i++; continue; }

        if (trimmed.indexOf('|') !== -1 && i + 1 < lines.length) {
          var aligns = parseAlignRow(lines[i + 1]);
          if (aligns) {
            flushPara();
            var headerCells = splitRow(line);
            var colCount = Math.max(headerCells.length, aligns.length);
            var alignAttr = function (idx) {
              var a = aligns[idx] || 'none';
              return a === 'none' ? '' : ' style="text-align:' + a + '"';
            };
            var padCells = function (cells) {
              var r = cells.slice(0, colCount);
              while (r.length < colCount) r.push('');
              return r;
            };
            var tableCls = colCount >= 4 ? 'obw-md-table obw-md-wide' : 'obw-md-table';
            var html = '<div class="obw-md-table-wrap"><table class="' + tableCls + '"><thead><tr>';
            padCells(headerCells).forEach(function (c, idx) { html += '<th' + alignAttr(idx) + '>' + inlineFormat(c) + '</th>'; });
            html += '</tr></thead><tbody>';
            i += 2;
            while (i < lines.length && lines[i].trim().indexOf('|') !== -1 && lines[i].trim() !== '') {
              if (/^```/.test(lines[i].trim())) break;
              html += '<tr>';
              padCells(splitRow(lines[i])).forEach(function (c, idx) { html += '<td' + alignAttr(idx) + '>' + inlineFormat(c) + '</td>'; });
              html += '</tr>';
              i++;
            }
            html += '</tbody></table></div>';
            out.push(html);
            continue;
          }
        }

        var h = /^(#{1,6})\s+(.*)$/.exec(trimmed);
        if (h) {
          flushPara();
          var level = Math.min(6, h[1].length);
          var tag = level <= 1 ? 'h4' : level === 2 ? 'h5' : 'h6';
          out.push('<' + tag + ' class="obw-md-h">' + inlineFormat(h[2].trim()) + '</' + tag + '>');
          i++;
          continue;
        }

        if (/^&gt;\s?/.test(trimmed)) {
          flushPara();
          var quote = [];
          while (i < lines.length && /^&gt;\s?/.test(lines[i].trim())) {
            quote.push(lines[i].trim().replace(/^&gt;\s?/, ''));
            i++;
          }
          out.push('<blockquote class="obw-md-quote">' + quote.map(inlineFormat).join('<br>') + '</blockquote>');
          continue;
        }

        var isUl = /^([-*+])\s+/.test(trimmed);
        var isOl = /^(\d+)\.\s+/.test(trimmed);
        if (isUl || isOl) {
          flushPara();
          var r = buildList(lines, i, isOl ? 'ol' : 'ul');
          out.push(r.html);
          i = r.next;
          continue;
        }

        para.push(line);
        i++;
      }
      flushPara();
      return out.join('');
    }

    // ── DOM helpers ──────────────────────────────────────────────────────────
    function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }
    function stickToBottom() {
      var slack = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight;
      if (slack < 120) messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function makeAvatar() {
      var a = document.createElement('div');
      a.className = 'obw-avatar';
      a.setAttribute('aria-hidden', 'true');
      a.innerHTML = SVG_CHAT;
      return a;
    }
    function makeRow(role) {
      var row = document.createElement('div');
      row.className = 'obw-row ' + (role === 'user' ? 'obw-row-user' : 'obw-row-agent');
      if (role !== 'user') row.appendChild(makeAvatar());
      return row;
    }
    function addBubble(role, text) {
      var row = makeRow(role);
      var el = document.createElement('div');
      el.className = 'obw-msg ' + (role === 'user' ? 'obw-user' : 'obw-agent');
      if (role === 'user') el.textContent = text; // plain, never interpreted
      else el.innerHTML = safeMarkdown(text);
      row.appendChild(el);
      messagesEl.appendChild(row);
      scrollToBottom();
      return el;
    }
    function addErrorBubble(text) {
      var row = makeRow('agent');
      var wrap = document.createElement('div');
      wrap.className = 'obw-msg obw-error';
      var msg = document.createElement('div');
      msg.innerHTML = safeMarkdown(text);
      wrap.appendChild(msg);
      if (lastUserMessage) {
        var retryBtn = document.createElement('button');
        retryBtn.type = 'button';
        retryBtn.className = 'obw-retry';
        retryBtn.textContent = t.retry;
        retryBtn.disabled = busy;
        retryBtn.addEventListener('click', function () {
          if (busy) return;
          var msgToRetry = lastUserMessage;
          row.remove();
          send(msgToRetry);
        });
        wrap.appendChild(retryBtn);
      }
      row.appendChild(wrap);
      messagesEl.appendChild(row);
      scrollToBottom();
      return wrap;
    }
    function makeWorkingIndicator() {
      var row = makeRow('agent');
      var pill = document.createElement('div');
      pill.className = 'obw-working';
      var dots = document.createElement('span');
      dots.className = 'obw-dots';
      dots.innerHTML = '<span></span><span></span><span></span>';
      var label = document.createElement('span');
      label.className = 'obw-step';
      label.textContent = t.working;
      pill.appendChild(dots);
      pill.appendChild(label);
      row.appendChild(pill);
      messagesEl.appendChild(row);
      scrollToBottom();
      return { el: row, setStep: function (s) { label.textContent = s || t.working; scrollToBottom(); } };
    }

    function extractText(parts) {
      if (!Array.isArray(parts)) return '';
      return parts.filter(function (p) { return p && p.kind === 'text'; }).map(function (p) { return p.text; }).join('\n');
    }

    // ── Agent card (capability + reachability detection) ─────────────────────
    function loadAgentCard() {
      if (agentCard) return Promise.resolve(agentCard);
      if (cardInflight) return cardInflight;
      cardInflight = (function () {
        var signal;
        try { if (AbortSignal && AbortSignal.timeout) signal = AbortSignal.timeout(8000); } catch (e) {}
        return fetch(ENDPOINT + '/.well-known/agent-card.json', {
          method: 'GET',
          headers: { Accept: 'application/json' },
          mode: 'cors',
          signal: signal
        }).then(function (res) {
          if (!res.ok) return null;
          cardEverReached = true;
          return res.json();
        }).then(function (card) {
          if (card && typeof card === 'object') agentCard = card;
          if (card && card.capabilities && typeof card.capabilities.streaming === 'boolean') {
            streamingSupported = card.capabilities.streaming;
          }
          if (card && card.description) subtitleEl.textContent = card.description;
          return (card && typeof card === 'object') ? card : null;
        }).catch(function () {
          return null;
        }).then(function (v) { cardInflight = null; return v; });
      })();
      return cardInflight;
    }

    // ── Agent-card view (all values via textContent — XSS-safe) ──────────────
    function isHttpUrl(u) {
      if (typeof u !== 'string') return false;
      try { var p = new URL(u); return p.protocol === 'https:' || p.protocol === 'http:'; }
      catch (e) { return false; }
    }
    // Only LINK a card endpoint if it points at the SAME origin the widget was
    // configured for; otherwise show it as plain text (no open-redirect vector).
    function isSameOrigin(u) {
      try { return new URL(u).origin === ENDPOINT_ORIGIN; } catch (e) { return false; }
    }
    function mkEl(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text != null) n.textContent = text;
      return n;
    }
    function cardSection(heading) {
      var s = mkEl('div', 'obw-card-section');
      s.appendChild(mkEl('h4', 'obw-card-section-h', heading));
      return s;
    }
    function metaLine(label, value, href) {
      var p = mkEl('p', 'obw-card-meta');
      p.appendChild(mkEl('strong', null, label + ': '));
      if (href && isHttpUrl(href) && isSameOrigin(href)) {
        var a = document.createElement('a');
        a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = value;
        p.appendChild(a);
      } else {
        p.appendChild(document.createTextNode(value));
      }
      return p;
    }
    function renderCard(card) {
      if (!cardEl) return;
      cardEl.textContent = '';
      if (!card) { cardEl.appendChild(mkEl('p', 'obw-card-empty', t.cardUnavailable)); return; }

      cardEl.appendChild(mkEl('p', 'obw-card-eyebrow', t.cardTitle));
      cardEl.appendChild(mkEl('h3', 'obw-card-name', String(card.name || t.headerTitle)));
      var desc = typeof card.description === 'string' ? card.description.trim() : '';
      if (desc) cardEl.appendChild(mkEl('p', 'obw-card-desc', desc));
      if (t.cardIntro) cardEl.appendChild(mkEl('p', 'obw-card-intro', t.cardIntro));

      var proto = cardSection(t.cardProtocol);
      var badges = mkEl('div', 'obw-card-badges');
      var ifaces = Array.isArray(card.supportedInterfaces) ? card.supportedInterfaces : [];
      ifaces.forEach(function (i) { if (i && typeof i.protocolBinding === 'string') badges.appendChild(mkEl('span', 'obw-card-badge', i.protocolBinding)); });
      if (card.capabilities && card.capabilities.streaming) badges.appendChild(mkEl('span', 'obw-card-badge', t.cardStreaming));
      if (card.capabilities && card.capabilities.pushNotifications) badges.appendChild(mkEl('span', 'obw-card-badge', t.cardPush));
      if (card.version) badges.appendChild(mkEl('span', 'obw-card-badge', 'v' + String(card.version)));
      if (badges.childNodes.length) proto.appendChild(badges);

      var inModes = Array.isArray(card.defaultInputModes) ? card.defaultInputModes.join(', ') : '';
      var outModes = Array.isArray(card.defaultOutputModes) ? card.defaultOutputModes.join(', ') : '';
      if (inModes || outModes) proto.appendChild(metaLine(t.cardModes, [inModes, outModes].filter(Boolean).join(' / ')));

      var endpoint = (ifaces[0] && typeof ifaces[0].url === 'string') ? ifaces[0].url : (typeof card.url === 'string' ? card.url : '');
      if (endpoint) {
        var host = endpoint;
        try { host = new URL(endpoint).host; } catch (e) {}
        proto.appendChild(metaLine(t.cardEndpoint, host, endpoint));
      }
      cardEl.appendChild(proto);

      var skills = Array.isArray(card.skills) ? card.skills : [];
      if (skills.length) {
        var sec = cardSection(t.cardSkills);
        skills.forEach(function (s) {
          if (!s) return;
          var item = mkEl('div', 'obw-card-skill');
          item.appendChild(mkEl('h5', 'obw-card-skill-name', String(s.name || s.id || '')));
          if (typeof s.description === 'string' && s.description.trim()) {
            item.appendChild(mkEl('div', 'obw-card-skill-desc', s.description.trim()));
          }
          if (Array.isArray(s.tags) && s.tags.length) {
            var tg = mkEl('div', 'obw-card-tags');
            s.tags.forEach(function (tag) { if (tag != null) tg.appendChild(mkEl('span', 'obw-card-tag', String(tag))); });
            item.appendChild(tg);
          }
          var examples = Array.isArray(s.examples) ? s.examples.filter(function (q) { return typeof q === 'string' && q.trim(); }) : [];
          if (examples.length) {
            if (t.cardExamplesHint) item.appendChild(mkEl('div', 'obw-card-ex-hint', t.cardExamplesHint));
            var list = mkEl('div', 'obw-card-examples');
            examples.forEach(function (q) {
              var text = q.trim();
              var chip = document.createElement('button');
              chip.type = 'button';
              chip.className = 'obw-card-ex';
              chip.textContent = text;
              chip.addEventListener('click', function () { closeCard(); input.focus(); send(text); });
              list.appendChild(chip);
            });
            item.appendChild(list);
          }
          sec.appendChild(item);
        });
        cardEl.appendChild(sec);
      }
    }

    function setCardBtnState() {
      if (!cardBtn) return;
      var label = cardShown ? t.cardBack : t.cardOpen;
      cardBtn.setAttribute('aria-label', label);
      cardBtn.setAttribute('title', label);
      cardBtn.setAttribute('aria-pressed', cardShown ? 'true' : 'false');
    }
    function openCard() {
      if (!cardEl) return Promise.resolve();
      cardShown = true;
      cardEl.hidden = false;
      panel.classList.add('obw-show-card');
      cardEl.setAttribute('aria-label', t.cardTitle);
      setCardBtnState();
      if (!cardRendered) {
        cardEl.textContent = '';
        cardEl.appendChild(mkEl('p', 'obw-card-loading', t.cardLoading));
        return loadAgentCard().then(function (card) {
          if (!cardShown) return;
          renderCard(card);
          cardRendered = !!card;
          cardEl.scrollTop = 0;
        });
      }
      cardEl.scrollTop = 0;
      return Promise.resolve();
    }
    function closeCard() {
      cardShown = false;
      panel.classList.remove('obw-show-card');
      if (cardEl) cardEl.hidden = true;
      setCardBtnState();
    }
    function toggleCard() { if (cardShown) closeCard(); else openCard().catch(function () {}); }

    // ── Advisory runtime context (public, non-PII) ───────────────────────────
    function buildRuntimeContext() {
      var path = '';
      try { path = location.pathname; } catch (e) {}
      if (lang === 'de') {
        return 'Eingebettet auf der open-bridge Website (Pfad ' + path + ', Oberflächensprache ' + lang + '). Nur-Lese-Q&A zum open-bridge Projekt.';
      }
      return 'Embedded on the open-bridge website (path ' + path + ', UI language ' + lang + '). Read-only Q&A about the open-bridge project.';
    }

    // ── JSON-RPC request body (A2A message/send | message/stream) ────────────
    function buildBody(message, useStreaming) {
      return JSON.stringify({
        jsonrpc: '2.0',
        id: uuid(),
        method: useStreaming ? 'message/stream' : 'message/send',
        params: {
          message: {
            role: 'user',
            parts: [{ kind: 'text', text: message }],
            messageId: uuid(),
            contextId: contextId,
            metadata: { runtime_context: buildRuntimeContext() }
          }
        }
      });
    }
    function postMessage(message, useStreaming) {
      return fetch(ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: useStreaming ? 'text/event-stream' : 'application/json'
        },
        mode: 'cors',
        body: buildBody(message, useStreaming)
      });
    }

    // ── Streaming (SSE over fetch) → outcome ─────────────────────────────────
    function handleStream(res, indicator) {
      var reader = res.body && res.body.getReader ? res.body.getReader() : null;
      if (!reader) return Promise.reject(new Error('no-stream-body'));
      var decoder = new TextDecoder();
      var buffer = '';
      var finalContent = '';
      var artifactContent = '';
      var errorText = '';
      var sawError = false;
      var bubble = null;

      function ensureBubble() { if (!bubble) bubble = addBubble('agent', ''); return bubble; }

      var liveTarget = '';
      var liveShown = 0;
      var paceRAF = 0;
      var reduceMotion = false;
      try { reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
      function paintLive() { ensureBubble().innerHTML = safeMarkdown(liveTarget.slice(0, liveShown)); stickToBottom(); }
      function pump() {
        paceRAF = 0;
        if (liveShown >= liveTarget.length) return;
        var backlog = liveTarget.length - liveShown;
        liveShown = Math.min(liveTarget.length, liveShown + (backlog > 400 ? 60 : 18));
        paintLive();
        if (liveShown < liveTarget.length) paceRAF = requestAnimationFrame(pump);
      }
      function renderLive(text) {
        liveTarget = text;
        if (liveShown > liveTarget.length) liveShown = 0;
        if (reduceMotion) { liveShown = liveTarget.length; paintLive(); return; }
        if (!paceRAF) paceRAF = requestAnimationFrame(pump);
      }
      function finishLive() { if (paceRAF) { cancelAnimationFrame(paceRAF); paceRAF = 0; } }

      function processLine(line) {
        if (line.indexOf('data: ') !== 0) return;
        var data = line.slice(6);
        if (data === '[DONE]') return;
        var event;
        try { event = JSON.parse(data); } catch (e) { return; }
        if (event.jsonrpc !== '2.0' || !event.result) {
          if (event.error) { sawError = true; errorText = event.error.message || errorText; }
          return;
        }
        var result = event.result;
        if (result.kind === 'artifact-update' && result.artifact) {
          var txt = extractText(result.artifact.parts || []);
          if (txt) { artifactContent = txt; if (!finalContent.trim()) renderLive(artifactContent.trim()); }
          return;
        }
        if (result.kind === 'status-update' && result.status) {
          var status = result.status;
          var stxt = extractText((status.message && status.message.parts) || []);
          var state = status.state;
          if (state === 'working') { if (stxt) indicator.setStep(stxt); }
          else if (state === 'completed') { if (stxt) { finalContent = stxt.trim(); renderLive(finalContent); } }
          else if (FAILED_STATES[state]) { sawError = true; if (stxt) errorText = stxt.trim(); }
          return;
        }
        if (result.kind === 'message' && result.parts) {
          var mtxt = extractText(result.parts);
          if (mtxt) { finalContent += mtxt; renderLive(finalContent); }
        }
      }

      function readLoop() {
        return reader.read().then(function (chunk) {
          if (chunk.done) return;
          buffer += decoder.decode(chunk.value, { stream: true });
          var lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (var k = 0; k < lines.length; k++) processLine(lines[k]);
          return readLoop();
        });
      }

      return readLoop().then(function () {
        finishLive();
        indicator.el.remove();
        var answer = finalContent.trim() || artifactContent.trim();
        if (answer) {
          if (bubble) bubble.innerHTML = safeMarkdown(answer);
          return { kind: 'answer', text: answer };
        }
        if (bubble) { var rowEl = bubble.closest ? bubble.closest('.obw-row') : null; (rowEl || bubble).remove(); }
        if (sawError) return { kind: 'agent-error', text: errorText || t.errorAgent };
        return { kind: 'empty' };
      }, function (err) {
        finishLive();
        indicator.el.remove();
        throw err;
      });
    }

    // ── Buffered (message/send) fallback → outcome ───────────────────────────
    function parseBuffered(data) {
      if (data && data.error) return { kind: 'agent-error', text: (data.error.message) || t.errorAgent };
      if (!data || data.jsonrpc !== '2.0' || !data.result) return { kind: 'empty' };
      var result = data.result;
      var artifactText = '';
      if (Array.isArray(result.artifacts)) {
        artifactText = result.artifacts
          .map(function (a) { return extractText(a && a.parts ? a.parts : []); })
          .filter(Boolean).join('\n').trim();
      }
      var taskState = result.status && result.status.state;
      var statusText = extractText((result.status && result.status.message && result.status.message.parts) || []).trim();
      var taskFailed = taskState && FAILED_STATES[taskState];

      var plain = '';
      if (result.parts) plain = extractText(result.parts).trim();
      else if (result.message && result.message.parts) plain = extractText(result.message.parts).trim();
      else if (typeof result === 'string') plain = result.trim();
      else if (typeof result.text === 'string') plain = result.text.trim();
      else if (typeof result.content === 'string') plain = result.content.trim();

      var answer = artifactText || plain || (!taskFailed ? statusText : '');
      if (answer) return { kind: 'answer', text: answer };
      if (taskFailed) return { kind: 'agent-error', text: statusText || t.errorAgent };
      return { kind: 'empty' };
    }
    function handleBuffered(res, indicator) {
      return res.json().then(function (data) {
        indicator.el.remove();
        return parseBuffered(data);
      }, function (err) {
        indicator.el.remove();
        throw err;
      });
    }

    // ── Send orchestration ───────────────────────────────────────────────────
    function setBusy(b) {
      busy = b;
      sendBtn.disabled = b;
      input.disabled = b;
      if (cardBtn) cardBtn.disabled = b;
    }
    function renderOutcome(outcome) {
      if (outcome.kind === 'answer') addBubble('agent', outcome.text);
      else if (outcome.kind === 'empty') addBubble('agent', t.emptyAnswer);
      else addErrorBubble(outcome.text);
    }
    function send(message) {
      if (!message || !message.trim() || busy) return;
      lastUserMessage = message;
      if (cardShown) closeCard();
      setBusy(true);
      addBubble('user', message);

      var reached = false;
      var indicator = null;

      function finish() { setBusy(false); if (panelOpen) input.focus(); }

      function bufferedPath() {
        indicator = makeWorkingIndicator();
        return postMessage(message, false).then(function (res2) {
          reached = true; cardEverReached = true;
          if (!res2.ok) throw new Error('HTTP ' + res2.status);
          return handleBuffered(res2, indicator).then(function (outcome) {
            indicator = null;
            renderOutcome(outcome);
          });
        });
      }

      var chain;
      if (streamingSupported) {
        indicator = makeWorkingIndicator();
        chain = postMessage(message, true).then(function (res) {
          reached = true; cardEverReached = true;
          if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);
          return handleStream(res, indicator).then(function (outcome) {
            indicator = null;
            renderOutcome(outcome);
          });
        }).catch(function () {
          if (indicator) { try { indicator.el.remove(); } catch (e) {} indicator = null; }
          return bufferedPath(); // documented fallback
        });
      } else {
        chain = bufferedPath();
      }

      chain.catch(function () {
        if (indicator) { try { indicator.el.remove(); } catch (e) {} }
        var unreachable = !reached || !cardEverReached;
        addErrorBubble(unreachable ? t.errorConnect : t.errorSend);
      }).then(finish, finish);
    }

    // =========================================================================
    // RESIZE + MAXIMIZE
    // =========================================================================
    var MIN_W = 320, MIN_H = 420, DEFAULT_W = 380, DEFAULT_H = 560;
    var maxW = function () { return Math.round(window.innerWidth * 0.95); };
    var maxH = function () { return Math.round(window.innerHeight * 0.92); };
    var isMobile = function () { try { return window.matchMedia('(max-width: 639px)').matches; } catch (e) { return false; } };
    var clamp = function (v, lo, hi) { return Math.min(Math.max(v, lo), hi); };

    var sizeState = { mode: 'default' };
    function loadSizeState() {
      try {
        var raw = localStorage.getItem(SIZE_KEY);
        if (raw) {
          var p = JSON.parse(raw);
          if (p && (p.mode === 'default' || p.mode === 'max' || p.mode === 'custom')) return p;
        }
      } catch (e) {}
      return { mode: 'default' };
    }
    function saveSizeState(s) { try { localStorage.setItem(SIZE_KEY, JSON.stringify(s)); } catch (e) {} }
    function syncMaximizeAria() {
      if (!maximizeBtn) return;
      var maxed = panel.classList.contains('obw-is-max');
      maximizeBtn.setAttribute('aria-pressed', maxed ? 'true' : 'false');
      var label = maxed ? t.restore : t.maximize;
      maximizeBtn.setAttribute('aria-label', label);
      maximizeBtn.setAttribute('title', label);
    }
    function applySizeState(s) {
      if (isMobile()) { panel.classList.remove('obw-is-max'); return; }
      if (s.mode === 'max') {
        panel.classList.add('obw-is-max');
        root.style.removeProperty('--obw-w');
        root.style.removeProperty('--obw-h');
      } else if (s.mode === 'custom' && s.w && s.h) {
        panel.classList.remove('obw-is-max');
        root.style.setProperty('--obw-w', clamp(s.w, MIN_W, maxW()) + 'px');
        root.style.setProperty('--obw-h', clamp(s.h, MIN_H, maxH()) + 'px');
      } else {
        panel.classList.remove('obw-is-max');
        root.style.setProperty('--obw-w', DEFAULT_W + 'px');
        root.style.setProperty('--obw-h', DEFAULT_H + 'px');
      }
      syncMaximizeAria();
    }
    function toggleMaximize() {
      if (isMobile()) return;
      sizeState = sizeState.mode === 'max' ? { mode: 'default' } : { mode: 'max' };
      applySizeState(sizeState);
      saveSizeState(sizeState);
      scrollToBottom();
    }

    var dragging = false, startX = 0, startY = 0, startW = 0, startH = 0, pointerId = -1;
    function onResizeMove(e) {
      if (!dragging) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;
      root.style.setProperty('--obw-w', clamp(startW - dx, MIN_W, maxW()) + 'px');
      root.style.setProperty('--obw-h', clamp(startH - dy, MIN_H, maxH()) + 'px');
    }
    function onResizeUp() {
      if (!dragging) return;
      dragging = false;
      panel.classList.remove('obw-resizing');
      try { resizeHandle && resizeHandle.releasePointerCapture(pointerId); } catch (e) {}
      window.removeEventListener('pointermove', onResizeMove);
      window.removeEventListener('pointerup', onResizeUp);
      window.removeEventListener('pointercancel', onResizeUp);
      var rect = panel.getBoundingClientRect();
      sizeState = { mode: 'custom', w: Math.round(rect.width), h: Math.round(rect.height) };
      saveSizeState(sizeState);
      syncMaximizeAria();
      scrollToBottom();
    }
    function onResizeDown(e) {
      if (isMobile()) return;
      e.preventDefault();
      dragging = true;
      pointerId = e.pointerId;
      var rect = panel.getBoundingClientRect();
      startX = e.clientX; startY = e.clientY; startW = rect.width; startH = rect.height;
      panel.classList.add('obw-resizing');
      try { resizeHandle && resizeHandle.setPointerCapture(pointerId); } catch (e2) {}
      window.addEventListener('pointermove', onResizeMove);
      window.addEventListener('pointerup', onResizeUp);
      window.addEventListener('pointercancel', onResizeUp);
    }

    var resizeRaf = 0;
    window.addEventListener('resize', function () {
      if (resizeRaf) return;
      resizeRaf = requestAnimationFrame(function () {
        resizeRaf = 0;
        if (panelOpen) applySizeState(sizeState);
      });
    });
    if (resizeHandle) resizeHandle.addEventListener('pointerdown', onResizeDown);
    if (maximizeBtn) maximizeBtn.addEventListener('click', toggleMaximize);
    if (cardBtn) cardBtn.addEventListener('click', toggleCard);
    sizeState = loadSizeState();

    // ── Open / close ─────────────────────────────────────────────────────────
    function applyStrings() {
      launcher.setAttribute('aria-label', t.launcherLabel);
      launcher.setAttribute('title', t.launcherLabel);
      titleEl.textContent = t.headerTitle;
      // Keep a live agent-card description if we already have one; else the default.
      if (!(agentCard && agentCard.description)) subtitleEl.textContent = t.headerSubtitle;
      input.setAttribute('placeholder', t.inputPlaceholder);
      input.setAttribute('aria-label', t.inputPlaceholder);
      sendBtn.setAttribute('aria-label', t.send);
      sendBtn.setAttribute('title', t.send);
      closeBtn.setAttribute('aria-label', t.close);
      closeBtn.setAttribute('title', t.close);
      syncMaximizeAria();
      setCardBtnState();
      if (cardEl) cardEl.setAttribute('aria-label', t.cardTitle);
      if (resizeHandle) resizeHandle.setAttribute('title', t.resize);
      if (launcherLabel) {
        var lt = launcherLabel.querySelector('.obw-label-text');
        if (lt) lt.textContent = t.launcherText;
        launcherLabel.setAttribute('title', t.launcherLabel);
      }
      if (privacyWrap && t.privacyNote) {
        privacyWrap.textContent = t.privacyNote;
        privacyWrap.hidden = false;
      }
    }

    function shouldAutoOpen() {
      var s = null;
      try { s = localStorage.getItem(OPEN_KEY); } catch (e) {}
      return s === 'open'; // default (marketing site): collapsed until the visitor opens it
    }
    function openPanel(opts) {
      opts = opts || {};
      panel.hidden = false;
      panelOpen = true;
      applySizeState(sizeState);
      launcher.classList.add('obw-hidden');
      if (launcherLabel) launcherLabel.classList.add('obw-hidden');
      launcher.setAttribute('aria-expanded', 'true');
      if (!greeted) { addBubble('agent', t.greeting); greeted = true; }
      if (!cardFetched) { cardFetched = true; loadAgentCard(); }
      if (opts.persist !== false) { try { localStorage.setItem(OPEN_KEY, 'open'); } catch (e) {} }
      if (opts.focus !== false) setTimeout(function () { try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); } }, 50);
    }
    function closePanel() {
      panel.hidden = true;
      panelOpen = false;
      try { localStorage.setItem(OPEN_KEY, 'closed'); } catch (e) {}
      if (cardShown) closeCard();
      launcher.classList.remove('obw-hidden');
      if (launcherLabel) launcherLabel.classList.remove('obw-hidden');
      launcher.setAttribute('aria-expanded', 'false');
      launcher.focus();
    }

    applyStrings();
    launcher.addEventListener('click', function () { openPanel(); });
    if (launcherLabel) launcherLabel.addEventListener('click', function () { openPanel(); });
    closeBtn.addEventListener('click', closePanel);
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || !panelOpen) return;
      if (cardShown) { closeCard(); input.focus(); } else { closePanel(); }
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var v = input.value;
      input.value = '';
      send(v);
    });

    // Re-localize live when the site language flips (open-bridge ob-lang switch).
    // Theme flips need no JS — the widget reads the page's CSS tokens directly.
    try {
      var mo = new MutationObserver(function () {
        var nl = detectLang();
        if (nl !== lang) { lang = nl; t = STRINGS[lang]; applyStrings(); }
      });
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-active-lang', 'lang'] });
    } catch (e) {}

    if (shouldAutoOpen()) openPanel({ focus: false });
  }
})();

// Frigate SSO panel: obtains a Frigate session cookie from Home Assistant,
// then shows Frigate in an iframe and keeps the session renewed while open.

const MENU_ICON =
  "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z";
// Frigate refuses (for non-DB users) a token within auth.refresh_time of expiry.
const FRIGATE_REFRESH_WINDOW_S = 1800;

class FrigateSsoPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._panel = null;
    this._narrow = false;
    this._started = false;
    this._lastOk = 0;
    this._timer = null;
    this._renewing = null;
    this._onVisible = () => {
      if (document.visibilityState === "visible") this._resume();
    };
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: flex; flex-direction: column; height: 100%;
          background: var(--primary-background-color); color: var(--primary-text-color); }
        .toolbar { display: none; align-items: center; gap: 12px; height: var(--header-height, 56px);
          padding: 0 12px; flex: none; box-sizing: border-box;
          background: var(--app-header-background-color, var(--primary-color));
          color: var(--app-header-text-color, var(--text-primary-color, #fff));
          font-size: 20px; }
        :host([narrow]) .toolbar { display: flex; }
        .toolbar button { background: none; border: 0; padding: 8px; color: inherit; cursor: pointer;
          display: flex; border-radius: 50%; }
        .toolbar svg { width: 24px; height: 24px; fill: currentColor; }
        .content { flex: 1; position: relative; min-height: 0; }
        iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; display: block; }
        .msg { padding: 24px 16px; max-width: 520px; margin: 0 auto; line-height: 1.5; }
        .msg a { color: var(--primary-color); }
        .msg button { margin-top: 12px; padding: 8px 16px; border: 0; border-radius: 4px; cursor: pointer;
          background: var(--primary-color); color: var(--text-primary-color, #fff); font: inherit; }
      </style>
      <div class="toolbar">
        <button title="Меню" aria-label="Меню"><svg viewBox="0 0 24 24"><path d="${MENU_ICON}"></path></svg></button>
        <span class="title"></span>
      </div>
      <div class="content"></div>`;
    this.shadowRoot.querySelector(".toolbar button").addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
    });
    this._content = this.shadowRoot.querySelector(".content");
  }

  set hass(hass) {
    this._hass = hass;
    this._maybeStart();
  }

  set panel(panel) {
    this._panel = panel;
    this.shadowRoot.querySelector(".title").textContent = panel?.title || "Frigate";
    this._maybeStart();
  }

  set narrow(narrow) {
    this._narrow = !!narrow;
    this.toggleAttribute("narrow", this._narrow);
  }

  set route(_route) {}

  get _cfg() {
    return this._panel?.config || {};
  }

  connectedCallback() {
    document.addEventListener("visibilitychange", this._onVisible);
    if (this._started) {
      this._startTimer();
      this._resume();
    } else {
      this._maybeStart();
    }
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisible);
    this._stopTimer();
  }

  _maybeStart() {
    if (this._started || !this._hass || !this._panel || !this.isConnected) return;
    this._started = true;

    const domain = (this._cfg.cookie_domain || "").toLowerCase();
    const host = location.hostname.toLowerCase();
    if (!domain || (host !== domain && !host.endsWith("." + domain))) {
      const link = `https://${domain}/${this._panel.url_path || ""}`;
      this._message(
        `Вхід у Frigate через Home Assistant працює лише за адресою
         <a href="${link}" target="_top">${link}</a>. Відкрийте Home Assistant за нею.`
      );
      return;
    }
    this._open();
  }

  async _open() {
    this._message("Підключення до Frigate…");
    try {
      await this._renew();
    } catch (err) {
      this._message(`Не вдалося отримати доступ до Frigate: ${this._errText(err)}`, true);
      return;
    }
    this._showIframe();
    this._startTimer();
  }

  _showIframe() {
    const src = (this._cfg.url || "") + (this._cfg.start_path || "/");
    let iframe = this._content.querySelector("iframe");
    if (!iframe) {
      this._content.innerHTML = "";
      iframe = document.createElement("iframe");
      iframe.allow = "fullscreen; autoplay; microphone; camera; clipboard-write; picture-in-picture";
      iframe.allowFullscreen = true;
      iframe.title = "Frigate";
      this._content.appendChild(iframe);
    }
    iframe.setAttribute("src", src);
  }

  _renew() {
    if (!this._renewing) {
      this._renewing = this._hass
        .callApi("POST", "frigate_sso/session")
        .then((res) => {
          this._lastOk = Date.now();
          return res;
        })
        .finally(() => {
          this._renewing = null;
        });
    }
    return this._renewing;
  }

  async _resume() {
    if (!this._started) return;
    const iframe = this._content.querySelector("iframe");
    if (!iframe) return;
    const ttl = Number(this._cfg.token_ttl) || 3600;
    // Past this age the cookie may already be refused, and the iframe kicked to /login.
    const staleMs = Math.max((ttl - FRIGATE_REFRESH_WINDOW_S - 300) * 1000, 60000);
    const stale = Date.now() - this._lastOk > staleMs;
    try {
      await this._renew();
      if (stale) this._showIframe();
    } catch (err) {
      console.warn("frigate-sso: session renew failed", err);
    }
  }

  _startTimer() {
    this._stopTimer();
    const interval = (Number(this._cfg.renew_interval) || 600) * 1000;
    this._timer = setInterval(() => {
      this._renew().catch((err) => console.warn("frigate-sso: session renew failed", err));
    }, interval);
  }

  _stopTimer() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  _errText(err) {
    const text = (err && (err.body?.message || err.message || err.error)) || String(err);
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  _message(html, retry = false) {
    this._content.innerHTML = `<div class="msg">${html}${retry ? "<br><button>Повторити</button>" : ""}</div>`;
    if (retry) {
      this._content.querySelector("button").addEventListener("click", () => this._open());
    }
  }
}

if (!customElements.get("frigate-sso-panel")) {
  customElements.define("frigate-sso-panel", FrigateSsoPanel);
}

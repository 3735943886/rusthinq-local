// The rusthinq backup page (admin-only, not in the sidebar; the options flow links to it). It asks for the backup
// over the administrator's own websocket connection (`rusthinq/backup`) and saves it in the browser, as ZHA's
// "Download backup" does: the archive never has a URL of its own.

const TEXT = {
  en: {
    title: "rusthinq backup",
    intro: "A portable backup of rusthinq: the CA, the device records, the LG account and the daemon settings. "
      + "It restores into Home Assistant (\"Move an existing rusthinq into Home Assistant\") or into a "
      + "standalone rusthinq.",
    warning: "The file holds the CA key and the LG account. Keep it private.",
    download: "Download backup",
    working: "Creating backup…",
    back: "Back",
  },
  ko: {
    title: "rusthinq 백업",
    intro: "rusthinq의 포터블 백업입니다. CA, 기기 기록, LG 계정, 데몬 설정이 들어 있습니다. "
      + "Home Assistant(\"기존 rusthinq를 Home Assistant로 옮기기\")나 독립 실행 rusthinq로 복원할 수 있습니다.",
    warning: "파일에 CA 키와 LG 계정이 들어 있으니 공유하지 마세요.",
    download: "백업 다운로드",
    working: "백업을 만드는 중…",
    back: "뒤로",
  },
};

class RusthinqBackupPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this._render();
  }

  get _text() {
    const language = (this._hass && this._hass.language) || "en";
    return TEXT[language.split("-")[0]] || TEXT.en;
  }

  _render() {
    const t = this._text;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: block; min-height: 100%; background: var(--primary-background-color);
                color: var(--primary-text-color); font-family: var(--ha-font-family-body, Roboto, sans-serif); }
        header { display: flex; align-items: center; gap: 8px; height: var(--header-height, 56px); padding: 0 12px;
                 background: var(--app-header-background-color, var(--primary-color));
                 color: var(--app-header-text-color, var(--text-primary-color)); }
        header h1 { margin: 0; font-size: 20px; font-weight: 400; }
        header button { background: none; border: none; color: inherit; font-size: 20px; cursor: pointer;
                        padding: 8px; border-radius: 50%; }
        main { max-width: 640px; margin: 24px auto; padding: 0 16px; }
        .card { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px);
                box-shadow: var(--ha-card-box-shadow, none);
                border: 1px solid var(--divider-color); padding: 16px; }
        p { line-height: 1.5; margin: 0 0 12px; }
        .warning { color: var(--warning-color); }
        .error { color: var(--error-color); }
        .actions { display: flex; justify-content: flex-end; margin-top: 16px; }
        .download { background: var(--primary-color); color: var(--text-primary-color); border: none;
                    border-radius: 4px; padding: 10px 16px; font-size: 14px; font-weight: 500; cursor: pointer; }
        .download:disabled { opacity: 0.6; cursor: default; }
      </style>
      <header>
        <button class="back" title="${t.back}" aria-label="${t.back}">&#8592;</button>
        <h1>${t.title}</h1>
      </header>
      <main>
        <div class="card">
          <p>${t.intro}</p>
          <p class="warning">${t.warning}</p>
          <p class="error" hidden></p>
          <div class="actions"><button class="download">${t.download}</button></div>
        </div>
      </main>`;
    root.querySelector(".back").addEventListener("click", () => history.back());
    root.querySelector(".download").addEventListener("click", () => this._download());
  }

  async _download() {
    const t = this._text;
    const button = this.shadowRoot.querySelector(".download");
    const error = this.shadowRoot.querySelector(".error");
    button.disabled = true;
    button.textContent = t.working;
    error.hidden = true;
    try {
      const { filename, data } = await this._hass.callWS({ type: "rusthinq/backup" });
      const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: "application/gzip" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (err) {
      error.textContent = (err && err.message) || String(err);
      error.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = t.download;
    }
  }
}

if (!customElements.get("rusthinq-backup-panel")) {
  customElements.define("rusthinq-backup-panel", RusthinqBackupPanel);
}

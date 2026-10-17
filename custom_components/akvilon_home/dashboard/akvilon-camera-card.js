/*!
 * Akvilon InHome — custom card «Умная камера с ленивой загрузкой» (akvilon-camera-card)
 *
 * Особенности:
 *  1. Ленивая загрузка (Lazy loading): карточка использует IntersectionObserver.
 *     Пока камера не видна на экране (не попала в область видимости при скролле),
 *     запросы к Home Assistant и серверу здания НЕ отправляются!
 *  2. Авто-остановка: при прокрутке дашборда и уходе камеры с экрана обновление
 *     кадров немедленно прекращается, освобождая процессор и сеть.
 *  3. Умное обновление: при нахождении в зоне видимости кадр обновляется плавно
 *     раз в 20 секунд (настраивается), не перегружая Home Assistant.
 *  4. Поддержка избранного: кнопка ⭐ прямо на карточке камеры.
 *  5. Быстрое открытие: если камера связана с калиткой/домофоном, отображается
 *     кнопка отпирания замка в 1 клик.
 *  6. Клик по карточке открывает полноэкранный поток (live stream / more-info).
 *
 * Регистрация: window.customCards.push({ type: "akvilon-camera-card" }).
 */

class AkvilonCameraCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._isVisible = false;
    this._observer = null;
    this._timer = null;
    this._loadedOnce = false;
    this._imgSrc = "";
    this._token = "";
  }

  static getStubConfig() {
    return {
      entity: "camera.kamera_dvor_1",
      name: "Камера Двор",
      lazy: true,
      refresh_interval: 20,
    };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Необходимо указать entity камеры (например, camera.kamera_dvor_1)");
    }
    this._config = {
      name: "",
      lazy: true,
      refresh_interval: 20,
      aspect_ratio: "16/9",
      ...config,
    };
    this._renderBase();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    if (!this._config || !hass) return;

    const stateObj = hass.states[this._config.entity];
    if (!stateObj) {
      this._renderUnavailable();
      return;
    }

    const token = stateObj.attributes ? stateObj.attributes.access_token : "";
    const tokenChanged = token && token !== this._token;
    this._token = token;

    if (tokenChanged && this._isVisible) {
      this._updateImage();
    }

    if (!oldHass) {
      this._updateHeader(stateObj);
    }
  }

  connectedCallback() {
    this._setupObserver();
  }

  disconnectedCallback() {
    this._teardownObserver();
    this._stopTimer();
  }

  _setupObserver() {
    if (this._observer) return;
    if (!this._config || this._config.lazy === false) {
      this._isVisible = true;
      this._startTimer();
      this._updateImage();
      return;
    }

    if ("IntersectionObserver" in window) {
      this._observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              this._isVisible = true;
              this._updateImage();
              this._startTimer();
            } else {
              this._isVisible = false;
              this._stopTimer();
            }
          }
        },
        {
          rootMargin: "150px 0px", // начинаем предзагрузку за 150px до попадания в экран
          threshold: 0.01,
        }
      );
      this._observer.observe(this);
    } else {
      this._isVisible = true;
      this._startTimer();
      this._updateImage();
    }
  }

  _teardownObserver() {
    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    }
  }

  _startTimer() {
    this._stopTimer();
    const intervalSec = parseInt(this._config?.refresh_interval, 10);
    if (intervalSec && intervalSec >= 5) {
      this._timer = setInterval(() => {
        if (this._isVisible) {
          this._updateImage();
        }
      }, intervalSec * 1000);
    }
  }

  _stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _updateImage() {
    if (!this._hass || !this._config) return;
    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];
    if (!stateObj || stateObj.state === "unavailable") return;

    const img = this.shadowRoot.querySelector(".camera-feed");
    const placeholder = this.shadowRoot.querySelector(".placeholder");
    const loader = this.shadowRoot.querySelector(".loader-spinner");
    if (!img) return;

    const token = this._token || (stateObj.attributes && stateObj.attributes.access_token) || "";
    const ts = Date.now();
    const url = token
      ? `/api/camera_proxy/${entityId}?token=${token}&time=${ts}`
      : `/api/camera_proxy/${entityId}?time=${ts}`;

    const tempImg = new Image();
    tempImg.onload = () => {
      img.src = url;
      img.style.opacity = "1";
      if (placeholder) placeholder.style.opacity = "0";
      if (loader) loader.style.display = "none";
      this._loadedOnce = true;
    };
    tempImg.onerror = () => {
      if (loader) loader.style.display = "none";
    };
    tempImg.src = url;
  }

  _handleMoreInfo() {
    if (!this._config?.entity) return;
    const event = new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId: this._config.entity },
    });
    this.dispatchEvent(event);
  }

  _handleToggleFavorite(e) {
    e.stopPropagation();
    if (!this._hass || !this._config?.entity) return;
    const stateObj = this._hass.states[this._config.entity];
    const camId = (stateObj && (stateObj.attributes.object_id || stateObj.attributes.cam_id)) || "";

    if (this._hass.services.akvilon_home && this._hass.services.akvilon_home.toggle_favorite_camera) {
      this._hass.callService("akvilon_home", "toggle_favorite_camera", {
        camera_id: camId,
        entity_id: this._config.entity,
      });
    }

    const starBtn = this.shadowRoot.querySelector(".btn-fav");
    if (starBtn) {
      starBtn.classList.toggle("active");
    }
  }

  _handleOpenGate(e) {
    e.stopPropagation();
    if (!this._hass || !this._config?.entity) return;
    const stateObj = this._hass.states[this._config.entity];
    const gateId = stateObj?.attributes?.gate_id;
    if (gateId) {
      this._hass.callService("akvilon_home", "open_gate", { gate_id: gateId });
    }
  }

  _updateHeader(stateObj) {
    const titleEl = this.shadowRoot.querySelector(".camera-title");
    const favBtn = this.shadowRoot.querySelector(".btn-fav");
    const gateBtn = this.shadowRoot.querySelector(".btn-gate");

    if (titleEl) {
      const displayName =
        this._config.name ||
        stateObj.attributes?.friendly_name ||
        this._config.entity.replace("camera.", "").replace(/_/g, " ");
      titleEl.textContent = displayName;
    }

    if (favBtn && stateObj.attributes?.is_favorite) {
      favBtn.classList.add("active");
    }

    if (gateBtn && stateObj.attributes?.domofon) {
      gateBtn.style.display = "inline-flex";
    }
  }

  _renderUnavailable() {
    if (this.shadowRoot.querySelector(".unavailable-text")) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; margin: 4px; }
        .card {
          background: var(--ha-card-background, #1c1c1e);
          border-radius: var(--ha-card-border-radius, 12px);
          padding: 16px;
          color: var(--secondary-text-color, #8e8e93);
          text-align: center;
          border: 1px solid var(--divider-color, rgba(255,255,255,0.08));
        }
      </style>
      <div class="card">
        <div>📷 ${this._config?.name || this._config?.entity}</div>
        <div class="unavailable-text" style="font-size:12px; margin-top:4px;">Камера недоступна</div>
      </div>
    `;
  }

  _renderBase() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          outline: none;
        }
        .card {
          position: relative;
          background: var(--ha-card-background, #18181b);
          border-radius: var(--ha-card-border-radius, 14px);
          overflow: hidden;
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.25));
          border: 1px solid var(--divider-color, rgba(255,255,255,0.08));
          cursor: pointer;
          user-select: none;
          transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .card:hover {
          transform: translateY(-2px);
          box-shadow: 0 4px 16px rgba(0,0,0,0.4);
        }
        .aspect-box {
          position: relative;
          width: 100%;
          aspect-ratio: ${this._config.aspect_ratio || "16/9"};
          background: #09090b;
          overflow: hidden;
        }
        .camera-feed {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          opacity: 0;
          transition: opacity 0.4s ease-in-out;
          z-index: 1;
        }
        .placeholder {
          position: absolute;
          inset: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          background: linear-gradient(145deg, #18181b 0%, #0d0d0f 100%);
          color: var(--secondary-text-color, #71717a);
          transition: opacity 0.3s ease;
          z-index: 0;
        }
        .placeholder-icon {
          width: 44px;
          height: 44px;
          opacity: 0.5;
          margin-bottom: 8px;
        }
        .placeholder-text {
          font-size: 11px;
          letter-spacing: 0.3px;
          text-transform: uppercase;
        }
        .header-overlay {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 12px;
          background: linear-gradient(180deg, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0) 100%);
          z-index: 2;
        }
        .camera-info {
          display: flex;
          align-items: center;
          gap: 6px;
          overflow: hidden;
        }
        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #10b981;
          box-shadow: 0 0 6px #10b981;
          flex-shrink: 0;
        }
        .camera-title {
          font-size: 13px;
          font-weight: 500;
          color: #ffffff;
          text-shadow: 0 1px 3px rgba(0,0,0,0.8);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .actions-overlay {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .btn-action {
          background: rgba(0,0,0,0.4);
          border: 1px solid rgba(255,255,255,0.15);
          border-radius: 8px;
          color: #ffffff;
          padding: 4px 6px;
          cursor: pointer;
          font-size: 12px;
          backdrop-filter: blur(4px);
          transition: background 0.15s, color 0.15s;
        }
        .btn-action:hover {
          background: rgba(255,255,255,0.25);
        }
        .btn-fav {
          color: rgba(255,255,255,0.7);
        }
        .btn-fav.active {
          color: #fbbf24;
          text-shadow: 0 0 8px rgba(251,191,36,0.8);
        }
        .btn-gate {
          display: none;
          background: rgba(16, 185, 129, 0.4);
          border-color: rgba(16, 185, 129, 0.6);
          color: #a7f3d0;
        }
        .btn-gate:hover {
          background: rgba(16, 185, 129, 0.7);
        }
        .badge-bottom {
          position: absolute;
          bottom: 6px;
          right: 8px;
          background: rgba(0,0,0,0.65);
          color: #d1d5db;
          font-size: 10px;
          padding: 2px 6px;
          border-radius: 4px;
          backdrop-filter: blur(4px);
          z-index: 2;
        }
        .loader-spinner {
          position: absolute;
          width: 22px;
          height: 22px;
          border: 2px solid rgba(255,255,255,0.15);
          border-top-color: #38bdf8;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
          z-index: 1;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      </style>
      <div class="card">
        <div class="aspect-box">
          <div class="placeholder">
            <svg class="placeholder-icon" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
            </svg>
            <div class="placeholder-text">Ленивая загрузка (при скролле)</div>
          </div>
          <div class="loader-spinner"></div>
          <img class="camera-feed" alt="Video stream" />
          <div class="header-overlay">
            <div class="camera-info">
              <div class="status-dot"></div>
              <div class="camera-title">${this._config.name || "Камера"}</div>
            </div>
            <div class="actions-overlay">
              <button class="btn-action btn-gate" title="Открыть связанную дверь">🚪 Открыть</button>
              <button class="btn-action btn-fav" title="Добавить в избранное">⭐</button>
            </div>
          </div>
          <div class="badge-bottom">RTP / Live</div>
        </div>
      </div>
    `;

    const card = this.shadowRoot.querySelector(".card");
    const favBtn = this.shadowRoot.querySelector(".btn-fav");
    const gateBtn = this.shadowRoot.querySelector(".btn-gate");

    card.addEventListener("click", () => this._handleMoreInfo());
    favBtn.addEventListener("click", (e) => this._handleToggleFavorite(e));
    gateBtn.addEventListener("click", (e) => this._handleOpenGate(e));
  }
}

customElements.define("akvilon-camera-card", AkvilonCameraCard);

// Регистрация в списке customCards Home Assistant
window.customCards = window.customCards || [];
window.customCards.push({
  type: "akvilon-camera-card",
  name: "Akvilon Camera Card (Lazy Load)",
  description: "Энергоэффективная карточка камеры с ленивой загрузкой при скролле и кнопкой избранного.",
  preview: true,
  documentationURL: "https://github.com/Gakuzi/akvilon_home",
});

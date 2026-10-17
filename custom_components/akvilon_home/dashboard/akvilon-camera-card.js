/*!
 * Akvilon InHome — custom card «Умная камера с ленивой загрузкой и кэшированием» (akvilon-camera-card)
 * Версия 2.2 — ЖК «Река» (г. Архангельск)
 *
 * Новые возможности:
 *  1. Персистентный кэш последнего кадра (localStorage + память):
 *     Камера, получив кадр хотя бы один раз, сохраняет его навсегда.
 *     При повторном открытии дашборда или перезагрузке страницы последний
 *     снимок отображается мгновенно (0 мс), без пустых черных квадратов.
 *  2. Полноэкранный Live-просмотр с остановкой остальных потоков:
 *     При клике на камеру открывается большое HD окно прямого эфира.
 *     ВСЕ остальные камеры на дашборде немедленно останавливают запросы к серверу,
 *     разгружая Raspberry Pi и сервер здания. Поток идёт только с одной активной камеры.
 *  3. Полноценная работа с избранным (⭐):
 *     Нажатие звёздочки вызывает сервис toggle_favorite_camera, обновляет состояние
 *     в Home Assistant и поднимает камеру в блок избранного вверху дашборда.
 *  4. Крупные информативные карточки предпросмотра:
 *     Широкий формат 16:9, высокое разрешение, плотное заполнение экрана без пустых полей.
 */

class AkvilonCameraCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._isVisible = false;
    this._observer = null;
    this._timer = null;
    this._loadedOnce = false;
    this._token = "";
    this._isPausedForLive = false;
    this._liveInterval = null;
    this._activeModal = null;

    // Глобальная шина событий для управления активным Live-потоком
    this._onLiveModalState = (e) => {
      const activeEntity = e.detail?.entityId;
      if (e.detail?.active && activeEntity !== this._config?.entity) {
        this._isPausedForLive = true;
        this._stopTimer();
      } else if (!e.detail?.active) {
        this._isPausedForLive = false;
        if (this._isVisible) {
          this._startTimer();
        }
      }
    };

    this._onFavoriteToggled = (e) => {
      if (e.detail?.entityId === this._config?.entity) {
        this._updateFavoriteUI(e.detail.isFavorite);
      }
    };
  }

  static getStubConfig() {
    return {
      entity: "camera.kamera_dvor_2",
      name: "Камера Двор 2",
      lazy: true,
      refresh_interval: 20,
    };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Необходимо указать entity камеры (например, camera.kamera_dvor_2)");
    }
    this._config = {
      name: "",
      lazy: true,
      refresh_interval: 20,
      aspect_ratio: "16/9",
      stagger_delay: 0,
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

    if (tokenChanged && this._isVisible && !this._isPausedForLive) {
      this._updateImage();
    }

    if (!oldHass || stateObj.attributes?.is_favorite !== oldHass.states[this._config.entity]?.attributes?.is_favorite) {
      this._updateHeader(stateObj);
    }
  }

  connectedCallback() {
    window.addEventListener("akvilon-live-modal-state", this._onLiveModalState);
    window.addEventListener("akvilon-favorite-toggled", this._onFavoriteToggled);

    // Восстанавливаем сохраненный предпросмотр из localStorage мгновенно
    this._restoreCachedSnapshot();
    this._setupObserver();
  }

  disconnectedCallback() {
    window.removeEventListener("akvilon-live-modal-state", this._onLiveModalState);
    window.removeEventListener("akvilon-favorite-toggled", this._onFavoriteToggled);
    this._teardownObserver();
    this._stopTimer();
    this._closeLiveModal();
  }

  _restoreCachedSnapshot() {
    if (!this._config?.entity) return;
    try {
      const cached = localStorage.getItem("akvilon_cam_snapshot_" + this._config.entity);
      if (cached && cached.startsWith("data:image")) {
        const img = this.shadowRoot.querySelector(".camera-feed");
        const placeholder = this.shadowRoot.querySelector(".placeholder");
        const loader = this.shadowRoot.querySelector(".loader-spinner");
        if (img) {
          img.src = cached;
          img.style.opacity = "1";
          if (placeholder) placeholder.style.display = "none";
          if (loader) loader.style.display = "none";
          this._loadedOnce = true;
        }
      }
    } catch (e) {
      // Игнорируем ошибки доступа к storage
    }
  }

  _setupObserver() {
    if (this._observer) return;
    const stagger = Number(this._config.stagger_delay) || 0;

    const doInitLoad = () => {
      if (stagger > 0 && !this._loadedOnce) {
        setTimeout(() => {
          if (this._isVisible && !this._isPausedForLive) {
            this._updateImage();
            this._startTimer();
          }
        }, stagger);
      } else {
        this._updateImage();
        this._startTimer();
      }
    };

    if (!this._config || this._config.lazy === false) {
      this._isVisible = true;
      doInitLoad();
      return;
    }

    if ("IntersectionObserver" in window) {
      this._observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) {
              this._isVisible = true;
              if (!this._isPausedForLive) {
                doInitLoad();
              }
            } else {
              this._isVisible = false;
              this._stopTimer();
            }
          }
        },
        {
          rootMargin: "250px 0px", // Заблаговременная загрузка перед появлением в зоне видимости
          threshold: 0.01,
        }
      );
      this._observer.observe(this);
    } else {
      this._isVisible = true;
      doInitLoad();
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
    if (this._isPausedForLive) return;
    const intervalSec = parseInt(this._config?.refresh_interval, 10) || 20;
    this._timer = setInterval(() => {
      if (this._isVisible && !this._isPausedForLive) {
        this._updateImage();
      }
    }, Math.max(intervalSec, 10) * 1000);
  }

  _stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _updateImage() {
    if (!this._hass || !this._config || this._isPausedForLive) return;
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
      if (placeholder) placeholder.style.display = "none";
      if (loader) loader.style.display = "none";
      this._loadedOnce = true;

      // Кэшируем снимок в localStorage для мгновенного старта
      try {
        const canvas = document.createElement("canvas");
        const w = Math.min(tempImg.naturalWidth || 640, 800);
        const h = Math.round(w * (tempImg.naturalHeight / (tempImg.naturalWidth || 1)) || (w * 9) / 16);
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(tempImg, 0, 0, w, h);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.75);
        localStorage.setItem("akvilon_cam_snapshot_" + entityId, dataUrl);
      } catch (err) {
        // Защита от переполнения квоты или CORS
      }
    };
    tempImg.onerror = () => {
      if (loader) loader.style.display = "none";
      // ВАЖНО: Если уже есть снимок, никогда его не стираем!
    };
    tempImg.src = url;
  }

  _openLiveModal() {
    if (!this._hass || !this._config?.entity) return;
    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];
    const camName = this._config.name || stateObj?.attributes?.friendly_name || "Камера";
    const isFav = stateObj?.attributes?.is_favorite || false;
    const gateId = stateObj?.attributes?.gate_id;

    // Останавливаем все фоновые камеры на всех карточках дашборда
    window.dispatchEvent(
      new CustomEvent("akvilon-live-modal-state", {
        detail: { active: true, entityId },
      })
    );

    const modal = document.createElement("div");
    modal.className = "akvilon-live-modal-overlay";
    modal.innerHTML = `
      <style>
        .akvilon-live-modal-overlay {
          position: fixed;
          inset: 0;
          z-index: 999999;
          background: rgba(0, 0, 0, 0.92);
          backdrop-filter: blur(16px);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 16px;
          animation: akvilonFadeIn 0.2s ease-out;
        }
        @keyframes akvilonFadeIn {
          from { opacity: 0; transform: scale(0.98); }
          to { opacity: 1; transform: scale(1); }
        }
        .modal-container {
          position: relative;
          width: 100%;
          max-width: 1300px;
          background: #121214;
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 20px;
          overflow: hidden;
          box-shadow: 0 25px 60px rgba(0, 0, 0, 0.85);
          display: flex;
          flex-direction: column;
        }
        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          background: linear-gradient(180deg, #18181b 0%, #121214 100%);
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .modal-title-group {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .modal-live-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(239, 68, 68, 0.2);
          border: 1px solid rgba(239, 68, 68, 0.5);
          color: #fca5a5;
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          padding: 3px 8px;
          border-radius: 6px;
        }
        .live-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #ef4444;
          box-shadow: 0 0 8px #ef4444;
          animation: akvilonPulse 1.2s infinite;
        }
        @keyframes akvilonPulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.85); }
        }
        .modal-title {
          font-size: 18px;
          font-weight: 600;
          color: #ffffff;
        }
        .modal-actions {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .modal-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: #ffffff;
          padding: 8px 14px;
          border-radius: 10px;
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
        }
        .modal-btn:hover {
          background: rgba(255, 255, 255, 0.18);
        }
        .modal-btn-gate {
          background: rgba(16, 185, 129, 0.25);
          border-color: rgba(16, 185, 129, 0.6);
          color: #6ee7b7;
        }
        .modal-btn-gate:hover {
          background: rgba(16, 185, 129, 0.45);
        }
        .modal-btn-fav.active {
          color: #fbbf24;
          border-color: rgba(251, 191, 36, 0.6);
          background: rgba(251, 191, 36, 0.15);
        }
        .modal-btn-close {
          background: rgba(255, 255, 255, 0.12);
          font-size: 16px;
          padding: 8px 12px;
        }
        .modal-video-box {
          position: relative;
          width: 100%;
          aspect-ratio: 16/9;
          background: #000000;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .modal-live-img {
          width: 100%;
          height: 100%;
          object-fit: contain;
          user-select: none;
        }
        .modal-fps-info {
          position: absolute;
          bottom: 12px;
          left: 16px;
          background: rgba(0, 0, 0, 0.7);
          border: 1px solid rgba(255, 255, 255, 0.1);
          color: #a1a1aa;
          font-size: 11px;
          padding: 4px 10px;
          border-radius: 6px;
          backdrop-filter: blur(6px);
        }
      </style>
      <div class="modal-container">
        <div class="modal-header">
          <div class="modal-title-group">
            <div class="modal-live-badge"><span class="live-dot"></span> Прямой эфир</div>
            <div class="modal-title">${camName}</div>
          </div>
          <div class="modal-actions">
            ${gateId ? '<button class="modal-btn modal-btn-gate">🚪 Открыть калитку</button>' : ""}
            <button class="modal-btn modal-btn-fav ${isFav ? "active" : ""}">⭐ ${isFav ? "В избранном" : "В избранное"}</button>
            <button class="modal-btn modal-btn-close" title="Закрыть (Esc)">✕</button>
          </div>
        </div>
        <div class="modal-video-box">
          <img class="modal-live-img" alt="Прямой эфир ${camName}" />
          <div class="modal-fps-info">RTP H.264 Live Stream · ЖК «Река» · Все остальные потоки остановлены</div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);
    this._activeModal = modal;

    const modalImg = modal.querySelector(".modal-live-img");
    const closeBtn = modal.querySelector(".modal-btn-close");
    const favBtn = modal.querySelector(".modal-btn-fav");
    const gateBtn = modal.querySelector(".modal-btn-gate");

    // Инициализируем кадр текущим снимком
    const currentSrc = this.shadowRoot.querySelector(".camera-feed")?.src;
    if (currentSrc) modalImg.src = currentSrc;

    // Быстрый живой цикл обновления только для этой камеры (800 мс)
    const updateModalLive = () => {
      const token = this._token || (stateObj?.attributes && stateObj.attributes.access_token) || "";
      const ts = Date.now();
      const liveUrl = token
        ? `/api/camera_proxy/${entityId}?token=${token}&time=${ts}&live=1`
        : `/api/camera_proxy/${entityId}?time=${ts}&live=1`;

      const nextFrame = new Image();
      nextFrame.onload = () => {
        if (modalImg) modalImg.src = liveUrl;
      };
      nextFrame.src = liveUrl;
    };

    updateModalLive();
    this._liveInterval = setInterval(updateModalLive, 800);

    // Закрытие
    const closeModal = () => this._closeLiveModal();
    closeBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal();
    });

    const keyListener = (e) => {
      if (e.key === "Escape") {
        closeModal();
        window.removeEventListener("keydown", keyListener);
      }
    };
    window.addEventListener("keydown", keyListener);

    if (gateBtn && gateId) {
      gateBtn.addEventListener("click", () => {
        this._hass.callService("akvilon_home", "open_gate", { gate_id: gateId });
        gateBtn.textContent = "✓ Открыто!";
        setTimeout(() => {
          gateBtn.textContent = "🚪 Открыть калитку";
        }, 3000);
      });
    }

    if (favBtn) {
      favBtn.addEventListener("click", () => {
        this._handleToggleFavorite();
        const nowFav = favBtn.classList.toggle("active");
        favBtn.innerHTML = `⭐ ${nowFav ? "В избранном" : "В избранное"}`;
      });
    }
  }

  _closeLiveModal() {
    if (this._liveInterval) {
      clearInterval(this._liveInterval);
      this._liveInterval = null;
    }
    if (this._activeModal) {
      this._activeModal.remove();
      this._activeModal = null;
    }
    // Возобновляем работу фоновых камер
    window.dispatchEvent(
      new CustomEvent("akvilon-live-modal-state", {
        detail: { active: false },
      })
    );
  }

  _handleToggleFavorite(e) {
    if (e) e.stopPropagation();
    if (!this._hass || !this._config?.entity) return;
    const stateObj = this._hass.states[this._config.entity];
    const camId = (stateObj && (stateObj.attributes.object_id || stateObj.attributes.cam_id)) || "";
    const isCurrentlyFav = Boolean(stateObj?.attributes?.is_favorite);
    const newFav = !isCurrentlyFav;

    // Вызываем сервис интеграции
    this._hass.callService("akvilon_home", "toggle_favorite_camera", {
      entity_id: this._config.entity,
      camera_id: camId,
    });

    // Мгновенный отклик в интерфейсе
    this._updateFavoriteUI(newFav);

    // Оповещаем другие карточки этой камеры
    window.dispatchEvent(
      new CustomEvent("akvilon-favorite-toggled", {
        detail: { entityId: this._config.entity, isFavorite: newFav },
      })
    );

    // Показываем подтверждение пользователю
    this._showToast(newFav ? "⭐ Камера добавлена в избранное (вверху)" : "Камера удалена из избранного");
  }

  _updateFavoriteUI(isFav) {
    const favBtn = this.shadowRoot.querySelector(".btn-fav");
    if (favBtn) {
      if (isFav) {
        favBtn.classList.add("active");
        favBtn.title = "В избранном (нажмите, чтобы убрать)";
      } else {
        favBtn.classList.remove("active");
        favBtn.title = "Добавить в избранное";
      }
    }
  }

  _showToast(msg) {
    let toast = this.shadowRoot.querySelector(".cam-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "cam-toast";
      this.shadowRoot.appendChild(toast);
    }
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => {
      toast.classList.remove("show");
    }, 2500);
  }

  _handleOpenGate(e) {
    e.stopPropagation();
    if (!this._hass || !this._config?.entity) return;
    const stateObj = this._hass.states[this._config.entity];
    const gateId = stateObj?.attributes?.gate_id;
    if (gateId) {
      this._hass.callService("akvilon_home", "open_gate", { gate_id: gateId });
      this._showToast("🚪 Команда на открытие отправлена!");
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

    if (favBtn) {
      const isFav = Boolean(stateObj.attributes?.is_favorite);
      this._updateFavoriteUI(isFav);
    }

    if (gateBtn && stateObj.attributes?.domofon) {
      gateBtn.style.display = "inline-flex";
    }
  }

  _renderUnavailable() {
    if (this.shadowRoot.querySelector(".unavailable-text")) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; margin: 6px; }
        .card {
          background: var(--ha-card-background, #18181b);
          border-radius: var(--ha-card-border-radius, 16px);
          padding: 24px;
          color: var(--secondary-text-color, #71717a);
          text-align: center;
          border: 1px solid var(--divider-color, rgba(255,255,255,0.08));
        }
      </style>
      <div class="card">
        <div style="font-size:16px; font-weight:600; color:#e4e4e7;">📷 ${this._config?.name || this._config?.entity}</div>
        <div class="unavailable-text" style="font-size:13px; margin-top:6px;">Камера временно недоступна на сервере</div>
      </div>
    `;
  }

  _renderBase() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          outline: none;
          margin-bottom: 4px;
        }
        .card {
          position: relative;
          background: var(--ha-card-background, #141416);
          border-radius: var(--ha-card-border-radius, 16px);
          overflow: hidden;
          box-shadow: 0 4px 18px rgba(0,0,0,0.3);
          border: 1px solid rgba(255,255,255,0.09);
          cursor: pointer;
          user-select: none;
          transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.2s ease, border-color 0.2s;
        }
        .card:hover {
          transform: translateY(-3px) scale(1.008);
          box-shadow: 0 10px 30px rgba(0,0,0,0.55);
          border-color: rgba(255,255,255,0.22);
        }
        .aspect-box {
          position: relative;
          width: 100%;
          min-height: 280px;
          aspect-ratio: ${this._config.aspect_ratio || "16/9"};
          background: #09090b;
          overflow: hidden;
        }
        @media (max-width: 600px) {
          .aspect-box {
            min-height: 200px;
          }
        }
        .camera-feed {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          opacity: 0;
          transition: opacity 0.3s ease-in-out;
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
          color: #71717a;
          transition: opacity 0.3s ease;
          z-index: 0;
        }
        .placeholder-icon {
          width: 48px;
          height: 48px;
          opacity: 0.6;
          margin-bottom: 10px;
          animation: akvilonSoftPulse 2s infinite ease-in-out;
        }
        @keyframes akvilonSoftPulse {
          0%, 100% { transform: scale(1); opacity: 0.5; }
          50% { transform: scale(1.05); opacity: 0.8; }
        }
        .placeholder-text {
          font-size: 13px;
          font-weight: 500;
          letter-spacing: 0.2px;
          color: #a1a1aa;
        }
        .header-overlay {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 14px;
          background: linear-gradient(180deg, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.4) 65%, rgba(0,0,0,0) 100%);
          z-index: 2;
        }
        .camera-info {
          display: flex;
          align-items: center;
          gap: 8px;
          overflow: hidden;
        }
        .status-dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: #10b981;
          box-shadow: 0 0 8px #10b981;
          flex-shrink: 0;
        }
        .camera-title {
          font-size: 14px;
          font-weight: 600;
          color: #ffffff;
          text-shadow: 0 1px 4px rgba(0,0,0,0.9);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .actions-overlay {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .btn-action {
          background: rgba(0,0,0,0.55);
          border: 1px solid rgba(255,255,255,0.2);
          border-radius: 9px;
          color: #ffffff;
          padding: 6px 10px;
          cursor: pointer;
          font-size: 13px;
          font-weight: 500;
          backdrop-filter: blur(8px);
          transition: all 0.15s ease;
        }
        .btn-action:hover {
          background: rgba(255,255,255,0.3);
          transform: scale(1.05);
        }
        .btn-fav {
          color: rgba(255,255,255,0.75);
          font-size: 15px;
          padding: 4px 8px;
        }
        .btn-fav.active {
          color: #fbbf24;
          border-color: rgba(251,191,36,0.6);
          background: rgba(251,191,36,0.2);
          text-shadow: 0 0 10px rgba(251,191,36,0.9);
        }
        .btn-gate {
          display: none;
          background: rgba(16, 185, 129, 0.4);
          border-color: rgba(16, 185, 129, 0.7);
          color: #a7f3d0;
          font-size: 12px;
        }
        .btn-gate:hover {
          background: rgba(16, 185, 129, 0.75);
        }
        .badge-bottom {
          position: absolute;
          bottom: 8px;
          right: 10px;
          background: rgba(0,0,0,0.72);
          border: 1px solid rgba(255,255,255,0.12);
          color: #e4e4e7;
          font-size: 11px;
          font-weight: 600;
          padding: 3px 8px;
          border-radius: 6px;
          backdrop-filter: blur(8px);
          z-index: 2;
          display: flex;
          align-items: center;
          gap: 5px;
        }
        .badge-pulse {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #38bdf8;
          box-shadow: 0 0 6px #38bdf8;
        }
        .loader-spinner {
          position: absolute;
          width: 28px;
          height: 28px;
          border: 3px solid rgba(255,255,255,0.15);
          border-top-color: #38bdf8;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
          z-index: 1;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .cam-toast {
          position: absolute;
          bottom: 14px;
          left: 50%;
          transform: translateX(-50%) translateY(20px);
          background: rgba(24, 24, 27, 0.95);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #ffffff;
          padding: 6px 14px;
          border-radius: 8px;
          font-size: 12px;
          font-weight: 500;
          pointer-events: none;
          opacity: 0;
          transition: all 0.25s ease;
          z-index: 10;
          box-shadow: 0 8px 20px rgba(0,0,0,0.5);
          white-space: nowrap;
        }
        .cam-toast.show {
          opacity: 1;
          transform: translateX(-50%) translateY(0);
        }
      </style>
      <div class="card">
        <div class="aspect-box">
          <div class="placeholder">
            <svg class="placeholder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
              <circle cx="12" cy="13" r="3"/>
            </svg>
            <div class="placeholder-text">Загрузка снимка...</div>
          </div>
          <div class="loader-spinner"></div>
          <img class="camera-feed" alt="Кадр камеры" />
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
          <div class="badge-bottom"><span class="badge-pulse"></span> RTP Live</div>
        </div>
      </div>
    `;

    const card = this.shadowRoot.querySelector(".card");
    const favBtn = this.shadowRoot.querySelector(".btn-fav");
    const gateBtn = this.shadowRoot.querySelector(".btn-gate");

    card.addEventListener("click", () => this._openLiveModal());
    favBtn.addEventListener("click", (e) => this._handleToggleFavorite(e));
    gateBtn.addEventListener("click", (e) => this._handleOpenGate(e));

    this._restoreCachedSnapshot();
  }
}

customElements.define("akvilon-camera-card", AkvilonCameraCard);

/**
 * AkvilonCameraHub — хаб видеонаблюдения с боковым меню разделов,
 * отображением ровно 4-6 крупных камер на страницу, ступенчатой плавной
 * подгрузкой (staggered delay) и пагинацией.
 */
class AkvilonCameraHub extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._activeCatId = "fav";
    this._currentPage = 0;
    this._pageSize = 6;
    this._renderedCards = [];
    this._categories = [];

    this._onFavoriteToggled = () => {
      this._updateFavoriteBadges();
      if (this._activeCatId === "fav") {
        this._renderCurrentPage();
      }
    };
  }

  static getStubConfig() {
    return {
      title: "Видеонаблюдение ЖК «Река»",
      page_size: 6,
    };
  }

  setConfig(config) {
    this._config = {
      title: "Видеонаблюдение ЖК «Река»",
      page_size: 6,
      categories: [],
      ...config,
    };
    this._pageSize = Number(this._config.page_size) || 6;
    this._categories = Array.isArray(this._config.categories) ? [...this._config.categories] : [];

    const saved = localStorage.getItem("akvilon_camera_hub_cat");
    const validIds = this._categories.map((c) => c.id);
    if (saved && (validIds.includes(saved) || saved === "fav" || saved === "all")) {
      this._activeCatId = saved;
    } else if (this._categories.length > 0) {
      this._activeCatId = this._categories[0].id;
    } else {
      this._activeCatId = "fav";
    }

    this._renderBase();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;

    for (const card of this._renderedCards) {
      if (card) card.hass = hass;
    }

    this._updateFavoriteBadges();

    const grid = this.shadowRoot.querySelector(".hub-grid");
    if (grid && grid.children.length === 0) {
      this._renderCurrentPage();
    }
  }

  connectedCallback() {
    window.addEventListener("akvilon-favorite-toggled", this._onFavoriteToggled);
  }

  disconnectedCallback() {
    window.removeEventListener("akvilon-favorite-toggled", this._onFavoriteToggled);
    this._clearRenderedCards();
  }

  _clearRenderedCards() {
    const grid = this.shadowRoot ? this.shadowRoot.querySelector(".hub-grid") : null;
    if (grid) {
      grid.innerHTML = "";
    }
    this._renderedCards = [];
  }

  _getCamerasForCategory(catId) {
    if (!this._hass) return [];

    if (catId === "fav") {
      const favs = [];
      for (const [eid, state] of Object.entries(this._hass.states)) {
        if (eid.startsWith("camera.") && state.attributes?.is_favorite) {
          favs.push({
            entity: eid,
            name: state.attributes.friendly_name || eid,
          });
        }
      }
      return favs;
    }

    const cat = this._categories.find((c) => c.id === catId);
    if (!cat) return [];
    return cat.cameras || [];
  }

  _updateFavoriteBadges() {
    if (!this.shadowRoot || !this._hass) return;
    const favCount = Object.values(this._hass.states).filter(
      (s) => s.entity_id.startsWith("camera.") && s.attributes?.is_favorite
    ).length;
    const favBadge = this.shadowRoot.querySelector('.badge-count[data-cat="fav"]');
    if (favBadge) {
      favBadge.textContent = String(favCount);
    }
  }

  _selectCategory(catId) {
    if (this._activeCatId === catId) return;
    this._activeCatId = catId;
    this._currentPage = 0;
    try {
      localStorage.setItem("akvilon_camera_hub_cat", catId);
    } catch (e) {}

    const items = this.shadowRoot.querySelectorAll(".menu-item");
    items.forEach((it) => {
      if (it.getAttribute("data-cat") === catId) {
        it.classList.add("active");
      } else {
        it.classList.remove("active");
      }
    });

    this._renderCurrentPage();
  }

  _changePage(delta) {
    this._currentPage += delta;
    this._renderCurrentPage();
    const mainEl = this.shadowRoot.querySelector(".hub-main");
    if (mainEl) {
      mainEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  _renderCurrentPage() {
    if (!this.shadowRoot) return;
    const grid = this.shadowRoot.querySelector(".hub-grid");
    const headerTitle = this.shadowRoot.querySelector(".hub-category-title");
    const headerSubtitle = this.shadowRoot.querySelector(".hub-category-subtitle");
    const prevBtn = this.shadowRoot.querySelector(".btn-page-prev");
    const nextBtn = this.shadowRoot.querySelector(".btn-page-next");
    const pageIndicator = this.shadowRoot.querySelector(".page-indicator");
    const paginationBar = this.shadowRoot.querySelector(".pagination-bar");

    if (!grid) return;

    this._clearRenderedCards();

    const cameras = this._getCamerasForCategory(this._activeCatId);
    const catObj = this._categories.find((c) => c.id === this._activeCatId) || {
      id: "fav",
      title: "Избранные камеры",
      icon: "⭐",
    };

    if (headerTitle) {
      headerTitle.textContent = `${catObj.icon || "📹"} ${catObj.title || "Камеры"}`;
    }

    const total = cameras.length;
    const totalPages = Math.max(1, Math.ceil(total / this._pageSize));

    if (this._currentPage < 0) this._currentPage = 0;
    if (this._currentPage >= totalPages) this._currentPage = totalPages - 1;

    const start = this._currentPage * this._pageSize;
    const end = Math.min(start + this._pageSize, total);
    const pageSlice = cameras.slice(start, end);

    if (headerSubtitle) {
      if (total === 0) {
        headerSubtitle.textContent = "Камеры не выбраны";
      } else {
        headerSubtitle.textContent = `Показано: ${start + 1}–${end} из ${total} · Ступенчатая подгрузка без перегрузки CPU`;
      }
    }

    if (paginationBar) {
      if (totalPages > 1) {
        paginationBar.style.display = "flex";
        if (prevBtn) prevBtn.disabled = this._currentPage === 0;
        if (nextBtn) nextBtn.disabled = this._currentPage >= totalPages - 1;
        if (pageIndicator) {
          pageIndicator.textContent = `Камеры ${start + 1}–${end} из ${total} (Страница ${this._currentPage + 1} из ${totalPages})`;
        }
      } else {
        paginationBar.style.display = "none";
      }
    }

    if (pageSlice.length === 0) {
      const emptyDiv = document.createElement("div");
      emptyDiv.className = "empty-state";
      if (this._activeCatId === "fav") {
        emptyDiv.innerHTML = `
          <div class="empty-icon">⭐</div>
          <div class="empty-title">В избранном пока нет камер</div>
          <div class="empty-desc">Нажмите на звёздочку (⭐) на любой камере в разделах слева, чтобы добавить её в быстрый доступ.</div>
        `;
      } else {
        emptyDiv.innerHTML = `
          <div class="empty-icon">📹</div>
          <div class="empty-title">В этом разделе нет камер</div>
        `;
      }
      grid.appendChild(emptyDiv);
      return;
    }

    // Рендерим ровно 4-6 карточек с плавным ступенчатым запуском
    pageSlice.forEach((cam, idx) => {
      const card = document.createElement("akvilon-camera-card");
      card.setConfig({
        entity: cam.entity,
        name: cam.name,
        lazy: true,
        refresh_interval: 25,
        stagger_delay: idx * 500, // 0ms, 500ms, 1000ms, 1500ms, 2000ms, 2500ms
        aspect_ratio: "16/9",
      });
      if (this._hass) {
        card.hass = this._hass;
      }
      grid.appendChild(card);
      this._renderedCards.push(card);
    });
  }

  _renderBase() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          color: var(--primary-text-color, #f4f4f5);
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          box-sizing: border-box;
          padding: 8px 0;
        }
        * {
          box-sizing: border-box;
        }
        .hub-root {
          width: 100%;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .hub-layout {
          display: flex;
          gap: 20px;
          align-items: flex-start;
          width: 100%;
        }
        .hub-sidebar {
          width: 260px;
          flex-shrink: 0;
          background: rgba(24, 24, 27, 0.85);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 16px;
          padding: 12px;
          box-shadow: 0 8px 24px rgba(0,0,0,0.35);
          backdrop-filter: blur(12px);
          position: sticky;
          top: 16px;
        }
        .sidebar-title {
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.8px;
          color: #a1a1aa;
          padding: 4px 10px 10px 10px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
          margin-bottom: 8px;
        }
        .menu-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .menu-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 14px;
          border-radius: 10px;
          cursor: pointer;
          color: #d4d4d8;
          font-size: 14px;
          font-weight: 500;
          background: transparent;
          border: 1px solid transparent;
          transition: all 0.18s ease;
          user-select: none;
        }
        .menu-item:hover {
          background: rgba(255, 255, 255, 0.07);
          color: #ffffff;
          transform: translateX(2px);
        }
        .menu-item.active {
          background: linear-gradient(90deg, rgba(3, 169, 244, 0.25) 0%, rgba(3, 169, 244, 0.08) 100%);
          border-color: rgba(3, 169, 244, 0.35);
          color: #38bdf8;
          font-weight: 600;
        }
        .menu-label {
          display: flex;
          align-items: center;
          gap: 10px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .menu-icon {
          font-size: 16px;
          flex-shrink: 0;
        }
        .badge-count {
          font-size: 11px;
          font-weight: 700;
          padding: 2px 7px;
          border-radius: 10px;
          background: rgba(255, 255, 255, 0.1);
          color: #a1a1aa;
          flex-shrink: 0;
        }
        .menu-item.active .badge-count {
          background: rgba(56, 189, 248, 0.3);
          color: #38bdf8;
        }
        .hub-main {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .main-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: rgba(24, 24, 27, 0.6);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 14px;
          padding: 12px 18px;
        }
        .hub-category-title {
          font-size: 17px;
          font-weight: 700;
          color: #ffffff;
          margin: 0;
        }
        .hub-category-subtitle {
          font-size: 12px;
          color: #a1a1aa;
          margin-top: 3px;
        }
        .hub-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 18px;
          width: 100%;
        }
        .pagination-bar {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 14px;
          padding: 12px;
          background: rgba(24, 24, 27, 0.6);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 14px;
          margin-top: 6px;
        }
        .btn-page {
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: #ffffff;
          padding: 8px 16px;
          border-radius: 9px;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .btn-page:hover:not(:disabled) {
          background: rgba(3, 169, 244, 0.3);
          border-color: rgba(3, 169, 244, 0.5);
          transform: translateY(-1px);
        }
        .btn-page:disabled {
          opacity: 0.35;
          cursor: not-allowed;
        }
        .page-indicator {
          font-size: 13px;
          font-weight: 500;
          color: #d4d4d8;
        }
        .empty-state {
          grid-column: 1 / -1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 60px 20px;
          background: rgba(24, 24, 27, 0.4);
          border: 1px dashed rgba(255, 255, 255, 0.15);
          border-radius: 16px;
          text-align: center;
        }
        .empty-icon {
          font-size: 40px;
          margin-bottom: 12px;
        }
        .empty-title {
          font-size: 16px;
          font-weight: 600;
          color: #ffffff;
          margin-bottom: 6px;
        }
        .empty-desc {
          font-size: 13px;
          color: #a1a1aa;
          max-width: 440px;
          line-height: 1.5;
        }
        @media (max-width: 900px) {
          .hub-grid {
            grid-template-columns: 1fr;
            gap: 14px;
          }
        }
        @media (max-width: 768px) {
          .hub-layout {
            flex-direction: column;
            gap: 12px;
          }
          .hub-sidebar {
            width: 100%;
            position: static;
            padding: 8px;
            overflow: hidden;
          }
          .sidebar-title {
            display: none;
          }
          .menu-list {
            flex-direction: row;
            overflow-x: auto;
            gap: 8px;
            padding-bottom: 4px;
            white-space: nowrap;
            -webkit-overflow-scrolling: touch;
          }
          .menu-item {
            flex-shrink: 0;
            padding: 8px 12px;
          }
        }
      </style>

      <div class="hub-root">
        <div class="hub-layout">
          <!-- Боковое меню разделов -->
          <div class="hub-sidebar">
            <div class="sidebar-title">Разделы камер</div>
            <div class="menu-list">
              ${this._renderMenuItems()}
            </div>
          </div>

          <!-- Основная область с камерами (4-6 штук) -->
          <div class="hub-main">
            <div class="main-header">
              <div>
                <div class="hub-category-title">Камеры</div>
                <div class="hub-category-subtitle">Загрузка...</div>
              </div>
            </div>

            <div class="hub-grid"></div>

            <div class="pagination-bar" style="display: none;">
              <button class="btn-page btn-page-prev">◀ Назад</button>
              <div class="page-indicator">Страница 1</div>
              <button class="btn-page btn-page-next">Вперёд ▶</button>
            </div>
          </div>
        </div>
      </div>
    `;

    const items = this.shadowRoot.querySelectorAll(".menu-item");
    items.forEach((it) => {
      it.addEventListener("click", () => {
        const catId = it.getAttribute("data-cat");
        this._selectCategory(catId);
      });
    });

    const prevBtn = this.shadowRoot.querySelector(".btn-page-prev");
    const nextBtn = this.shadowRoot.querySelector(".btn-page-next");
    if (prevBtn) prevBtn.addEventListener("click", () => this._changePage(-1));
    if (nextBtn) nextBtn.addEventListener("click", () => this._changePage(1));

    this._renderCurrentPage();
  }

  _renderMenuItems() {
    return this._categories
      .map((cat) => {
        const isActive = cat.id === this._activeCatId ? " active" : "";
        const count = (cat.cameras || []).length;
        return `
          <div class="menu-item${isActive}" data-cat="${cat.id}">
            <div class="menu-label">
              <span class="menu-icon">${cat.icon || "📹"}</span>
              <span>${cat.title}</span>
            </div>
            <span class="badge-count" data-cat="${cat.id}">${count}</span>
          </div>
        `;
      })
      .join("");
  }
}

customElements.define("akvilon-camera-hub", AkvilonCameraHub);

// Регистрация в списке customCards Home Assistant
window.customCards = window.customCards || [];
window.customCards.push({
  type: "akvilon-camera-card",
  name: "Akvilon Camera Card (Smart Cache & Live)",
  description: "Крупная карточка камеры с мгновенным кэшем снимков, полноэкранным Live-режимом и избранным.",
  preview: true,
  documentationURL: "https://github.com/Gakuzi/akvilon_home",
});
window.customCards.push({
  type: "akvilon-camera-hub",
  name: "Akvilon Camera Hub (Sidebar & Groups)",
  description: "Хаб камер с боковым меню разделов (двор, улица, парадные, лифты), пагинацией по 4-6 крупных камер и плавной ступенчатой подгрузкой.",
  preview: true,
  documentationURL: "https://github.com/Gakuzi/akvilon_home",
});

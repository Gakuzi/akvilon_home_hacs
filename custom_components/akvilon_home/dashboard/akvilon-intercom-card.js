/*!
 * Akvilon InHome — custom card «Видеодомофон и калитки» (akvilon-intercom-card)
 * Версия 2.5 — ЖК «Река» (г. Архангельск)
 *
 * Особенности:
 *  1. Чистый Vanilla Web Component (extends HTMLElement, без внешних CDN и LitElement).
 *  2. Мгновенная загрузка снимка из кэша (localStorage + память, 0 мс).
 *  3. Ленивая подгрузка через IntersectionObserver — процессор не перегружается.
 *  4. Удобная и крупная кнопка «🚪 Открыть калитку» с тактильным откликом и анимацией.
 *  5. При клике на видео — полноэкранное окно прямого эфира (Live Modal),
 *     при этом ВСЕ остальные камеры на дашборде приостанавливаются для разгрузки CPU.
 *  6. Полная поддержка домофона (прием звонка, звук, открытие, сброс вызова).
 *  7. Если камера не привязана к калитке — аккуратная карточка управления с кнопкой открытия.
 */

(function () {
  const CARD_TYPE = "akvilon-intercom-card";

  class AkvilonIntercomCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._isVisible = false;
      this._observer = null;
      this._timer = null;
      this._loadedOnce = false;
      this._token = "";
      this._isPausedForLive = false;
      this._activeModal = null;
      this._isOpenActive = false;

      this._onLiveModalState = (e) => {
        const activeEntity = e.detail?.entityId;
        const myCam = this._getCamEntity();
        if (e.detail?.active && activeEntity !== myCam) {
          this._isPausedForLive = true;
          this._stopTimer();
        } else if (!e.detail?.active) {
          this._isPausedForLive = false;
          if (this._isVisible) {
            this._startTimer();
          }
        }
      };
    }

    static getStubConfig() {
      return {
        title: "Калитка",
        gate_button: "button.otkryt_kalitka_1",
        camera_entity: "camera.kamera_kalitka_1_reka_7",
        status_sensor: "sensor.kalitka_kalitka_1_sostoianie",
      };
    }

    getCardSize() {
      return 3;
    }

    setConfig(config) {
      this._config = {
        title: "",
        gate_button: "",
        camera_entity: "",
        status_sensor: "",
        call_sensor: "",
        show_fullscreen_button: true,
        refresh_interval: 20,
        ...config,
      };
      // Поддержка синонимов entity/camera_entity
      if (!this._config.camera_entity && this._config.entity) {
        this._config.camera_entity = this._config.entity;
      }
      this._renderBase();
    }

    set hass(hass) {
      const oldHass = this._hass;
      this._hass = hass;
      if (!this._config || !hass) return;

      const camEntity = this._getCamEntity();
      if (camEntity && hass.states[camEntity]) {
        const stateObj = hass.states[camEntity];
        const token = stateObj.attributes ? stateObj.attributes.access_token : "";
        const tokenChanged = token && token !== this._token;
        this._token = token;

        if (tokenChanged && this._isVisible && !this._isPausedForLive) {
          this._updateImage();
        }
      }

      this._updateStatus();
      this._checkIncomingCall();
    }

    connectedCallback() {
      window.addEventListener("akvilon-live-modal-state", this._onLiveModalState);
      this._restoreCachedSnapshot();
      this._setupObserver();
    }

    disconnectedCallback() {
      window.removeEventListener("akvilon-live-modal-state", this._onLiveModalState);
      this._teardownObserver();
      this._stopTimer();
      this._closeLiveModal();
    }

    _getCamEntity() {
      return this._config?.camera_entity || this._config?.entity || "";
    }

    _restoreCachedSnapshot() {
      const camEntity = this._getCamEntity();
      if (!camEntity) return;
      try {
        const cached = localStorage.getItem("akvilon_cam_snapshot_" + camEntity);
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
      } catch (_) {}
    }

    _setupObserver() {
      if (this._observer) return;
      const camEntity = this._getCamEntity();
      if (!camEntity) {
        this._isVisible = true;
        return;
      }

      const doInitLoad = () => {
        this._updateImage();
        this._startTimer();
      };

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
          { rootMargin: "250px 0px", threshold: 0.01 }
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
      const camEntity = this._getCamEntity();
      if (!camEntity) return;
      const stateObj = this._hass.states[camEntity];
      if (!stateObj || stateObj.state === "unavailable") return;

      const img = this.shadowRoot.querySelector(".camera-feed");
      const placeholder = this.shadowRoot.querySelector(".placeholder");
      const loader = this.shadowRoot.querySelector(".loader-spinner");
      if (!img) return;

      const token = this._token || (stateObj.attributes && stateObj.attributes.access_token) || "";
      const ts = Date.now();
      const url = token
        ? `/api/camera_proxy/${camEntity}?token=${token}&time=${ts}`
        : `/api/camera_proxy/${camEntity}?time=${ts}`;

      const tempImg = new Image();
      tempImg.onload = () => {
        img.src = url;
        img.style.opacity = "1";
        if (placeholder) placeholder.style.display = "none";
        if (loader) loader.style.display = "none";
        this._loadedOnce = true;

        try {
          const canvas = document.createElement("canvas");
          const w = Math.min(tempImg.naturalWidth || 640, 800);
          const h = Math.round(w * (tempImg.naturalHeight / (tempImg.naturalWidth || 1)) || (w * 9) / 16);
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(tempImg, 0, 0, w, h);
          const dataUrl = canvas.toDataURL("image/jpeg", 0.75);
          localStorage.setItem("akvilon_cam_snapshot_" + camEntity, dataUrl);
        } catch (_) {}
      };
      tempImg.onerror = () => {
        if (loader) loader.style.display = "none";
      };
      tempImg.src = url;
    }

    _handleOpenGate(e) {
      if (e) e.stopPropagation();
      if (!this._hass) return;

      const btnEntity = this._config?.gate_button;
      const gateId = this._config?.gate_id;

      if (btnEntity && this._hass.states[btnEntity]) {
        this._hass.callService("button", "press", { entity_id: btnEntity });
      } else if (gateId) {
        this._hass.callService("akvilon_home", "open_gate", { gate_id: gateId });
      } else if (btnEntity) {
        this._hass.callService("button", "press", { entity_id: btnEntity });
      }

      this._showSuccessAnimation();
      this._showToast("🚪 Команда на открытие отправлена!");
    }

    _showSuccessAnimation() {
      const openBtn = this.shadowRoot.querySelector(".btn-open-main");
      if (!openBtn) return;
      openBtn.classList.add("opened");
      const origText = openBtn.querySelector(".btn-text")?.textContent || "Открыть";
      if (openBtn.querySelector(".btn-text")) {
        openBtn.querySelector(".btn-text").textContent = "Открыто!";
      }
      setTimeout(() => {
        openBtn.classList.remove("opened");
        if (openBtn.querySelector(".btn-text")) {
          openBtn.querySelector(".btn-text").textContent = origText;
        }
      }, 2500);
    }

    _showToast(msg) {
      let toast = this.shadowRoot.querySelector(".toast");
      if (!toast) {
        toast = document.createElement("div");
        toast.className = "toast";
        this.shadowRoot.appendChild(toast);
      }
      toast.textContent = msg;
      toast.classList.add("show");
      setTimeout(() => toast.classList.remove("show"), 2500);
    }

    _updateStatus() {
      const statusSensor = this._config?.status_sensor;
      if (!statusSensor || !this._hass) return;
      const st = this._hass.states[statusSensor];
      const statusDot = this.shadowRoot.querySelector(".status-dot");
      const statusText = this.shadowRoot.querySelector(".status-text");
      if (!st) return;

      const isOnline = st.state === "online" || st.state === "on" || st.state === "open";
      if (statusDot) {
        statusDot.className = "status-dot " + (isOnline ? "online" : "offline");
      }
      if (statusText) {
        statusText.textContent = isOnline ? "В сети" : (st.state === "unknown" ? "Готов" : st.state);
      }
    }

    _checkIncomingCall() {
      const callSensor = this._config?.call_sensor;
      if (!callSensor || !this._hass) return;
      const st = this._hass.states[callSensor];
      const isRinging = st && (st.state === "on" || st.state === "true" || st.state === "ring");
      const banner = this.shadowRoot.querySelector(".incoming-call-banner");
      const card = this.shadowRoot.querySelector(".card");
      if (banner && card) {
        if (isRinging) {
          banner.style.display = "flex";
          card.classList.add("ringing");
        } else {
          banner.style.display = "none";
          card.classList.remove("ringing");
        }
      }
    }

    _openLiveModal() {
      const camEntity = this._getCamEntity();
      if (!camEntity || !this._hass) return;
      const stateObj = this._hass.states[camEntity];
      const title = this._config.title || stateObj?.attributes?.friendly_name || "Калитка / Камера";
      const isDomofon = title.toLowerCase().includes("домофон");
      const openBtnText = this._config?.open_button_text || (isDomofon ? "Открыть домофон" : "Открыть калитку");

      window.dispatchEvent(
        new CustomEvent("akvilon-live-modal-state", {
          detail: { active: true, entityId: camEntity },
        })
      );

      const modal = document.createElement("div");
      modal.className = "akvilon-intercom-modal-overlay";
      modal.innerHTML = `
        <style>
          .akvilon-intercom-modal-overlay {
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
            animation: fadeIn 0.2s ease-out;
          }
          @keyframes fadeIn {
            from { opacity: 0; transform: scale(0.98); }
            to { opacity: 1; transform: scale(1); }
          }
          .modal-box {
            position: relative;
            width: 100%;
            max-width: 1250px;
            background: #141416;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.9);
            display: flex;
            flex-direction: column;
          }
          .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 20px;
            background: #1c1c1f;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          }
          .modal-title-group {
            display: flex;
            align-items: center;
            gap: 12px;
          }
          .live-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid rgba(239, 68, 68, 0.5);
            color: #fca5a5;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 3px 8px;
            border-radius: 6px;
          }
          .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ef4444;
            box-shadow: 0 0 8px #ef4444;
          }
          .modal-title {
            font-size: 18px;
            font-weight: 600;
            color: #ffffff;
          }
          .modal-actions {
            display: flex;
            align-items: center;
            gap: 12px;
          }
          .modal-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 9px 16px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.15s ease;
          }
          .btn-open-modal {
            background: #10b981;
            color: #ffffff;
            box-shadow: 0 4px 14px rgba(16, 185, 129, 0.4);
          }
          .btn-open-modal:hover {
            background: #059669;
            transform: scale(1.02);
          }
          .btn-close-modal {
            background: rgba(255, 255, 255, 0.12);
            color: #ffffff;
            font-size: 16px;
            padding: 8px 14px;
          }
          .modal-video-area {
            position: relative;
            width: 100%;
            aspect-ratio: 16/9;
            background: #000000;
          }
          .modal-live-img {
            width: 100%;
            height: 100%;
            object-fit: contain;
          }
        </style>
        <div class="modal-box">
          <div class="modal-header">
            <div class="modal-title-group">
              <div class="live-badge"><span class="pulse-dot"></span> Прямой эфир</div>
              <div class="modal-title">${title}</div>
            </div>
            <div class="modal-actions">
              <button class="modal-btn btn-open-modal">🚪 ${openBtnText}</button>
              <button class="modal-btn btn-close-modal">✕</button>
            </div>
          </div>
          <div class="modal-video-area">
            <img class="modal-live-img" alt="${title}" />
          </div>
        </div>
      `;

      document.body.appendChild(modal);
      this._activeModal = modal;

      const modalImg = modal.querySelector(".modal-live-img");
      const closeBtn = modal.querySelector(".btn-close-modal");
      const openBtn = modal.querySelector(".btn-open-modal");

      const curSrc = this.shadowRoot.querySelector(".camera-feed")?.src;
      if (curSrc) modalImg.src = curSrc;

      const updateLive = () => {
        const token = this._token || (stateObj?.attributes && stateObj.attributes.access_token) || "";
        const ts = Date.now();
        const liveUrl = token
          ? `/api/camera_proxy/${camEntity}?token=${token}&time=${ts}&live=1`
          : `/api/camera_proxy/${camEntity}?time=${ts}&live=1`;

        const nextImg = new Image();
        nextImg.onload = () => {
          if (modalImg) modalImg.src = liveUrl;
        };
        nextImg.src = liveUrl;
      };

      this._liveInterval = setInterval(updateLive, 800);
      updateLive();

      const closeModal = () => this._closeLiveModal();
      closeBtn.addEventListener("click", closeModal);
      modal.addEventListener("click", (e) => {
        if (e.target === modal) closeModal();
      });

      openBtn.addEventListener("click", () => {
        this._handleOpenGate();
        openBtn.textContent = "✔ Открыто!";
        openBtn.style.background = "#059669";
        setTimeout(() => {
          openBtn.textContent = `🚪 ${openBtnText}`;
          openBtn.style.background = "#10b981";
        }, 2500);
      });

      const onKeyDown = (e) => {
        if (e.key === "Escape") {
          closeModal();
          window.removeEventListener("keydown", onKeyDown);
        }
      };
      window.addEventListener("keydown", onKeyDown);
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
      window.dispatchEvent(
        new CustomEvent("akvilon-live-modal-state", {
          detail: { active: false },
        })
      );
    }

    _renderBase() {
      const title = this._config?.title || "Калитка / Вход";
      const camEntity = this._getCamEntity();
      const hasCam = Boolean(camEntity);
      const isDomofon = title.toLowerCase().includes("домофон");
      const openBtnText = this._config?.open_button_text || (isDomofon ? "Открыть домофон" : "Открыть калитку");

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            margin-bottom: 6px;
            outline: none;
          }
          .card {
            position: relative;
            background: var(--ha-card-background, #161619);
            border-radius: var(--ha-card-border-radius, 16px);
            overflow: hidden;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35);
            border: 1px solid rgba(255, 255, 255, 0.09);
            transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.2s ease, border-color 0.2s;
            display: flex;
            flex-direction: column;
          }
          .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 28px rgba(0, 0, 0, 0.5);
            border-color: rgba(255, 255, 255, 0.2);
          }
          .card.ringing {
            border-color: #f59e0b;
            box-shadow: 0 0 25px rgba(245, 158, 11, 0.5);
            animation: ringPulse 1s infinite alternate;
          }
          @keyframes ringPulse {
            from { border-color: #f59e0b; }
            to { border-color: #ef4444; }
          }
          .incoming-call-banner {
            display: none;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(90deg, #d97706 0%, #b45309 100%);
            color: #ffffff;
            padding: 10px 14px;
            font-size: 13px;
            font-weight: 600;
          }
          .call-actions {
            display: flex;
            gap: 6px;
          }
          .btn-call-action {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.3);
            color: #fff;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            cursor: pointer;
          }
          .video-container {
            position: relative;
            width: 100%;
            aspect-ratio: 16/9;
            min-height: 220px;
            background: #09090b;
            overflow: hidden;
            cursor: pointer;
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
            z-index: 0;
          }
          .placeholder-icon {
            width: 44px;
            height: 44px;
            opacity: 0.6;
            margin-bottom: 8px;
          }
          .placeholder-text {
            font-size: 13px;
            color: #a1a1aa;
            font-weight: 500;
          }
          .loader-spinner {
            position: absolute;
            width: 26px;
            height: 26px;
            border: 3px solid rgba(255, 255, 255, 0.15);
            border-top-color: #10b981;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            z-index: 1;
          }
          @keyframes spin {
            to { transform: rotate(360deg); }
          }
          .header-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 12px;
            background: linear-gradient(180deg, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0) 100%);
            z-index: 2;
          }
          .gate-title-group {
            display: flex;
            align-items: center;
            gap: 8px;
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
          .status-dot.offline {
            background: #71717a;
            box-shadow: none;
          }
          .gate-title {
            font-size: 14px;
            font-weight: 600;
            color: #ffffff;
            text-shadow: 0 1px 3px rgba(0,0,0,0.8);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .badge-live-tag {
            background: rgba(0, 0, 0, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.18);
            color: #e4e4e7;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            letter-spacing: 0.5px;
          }
          .bottom-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 14px;
            background: #18181b;
            border-top: 1px solid rgba(255, 255, 255, 0.07);
          }
          .status-info {
            display: flex;
            align-items: center;
            gap: 6px;
            color: #a1a1aa;
            font-size: 12px;
          }
          .btn-open-main {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            background: #10b981;
            color: #ffffff;
            border: none;
            border-radius: 10px;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 2px 10px rgba(16, 185, 129, 0.35);
            transition: all 0.15s ease;
          }
          .btn-open-main:hover {
            background: #059669;
            transform: scale(1.02);
            box-shadow: 0 4px 14px rgba(16, 185, 129, 0.5);
          }
          .btn-open-main.opened {
            background: #047857;
            box-shadow: 0 0 12px #10b981;
          }
          .no-cam-box {
            padding: 28px 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            background: linear-gradient(180deg, #18181b 0%, #121214 100%);
            gap: 12px;
          }
          .no-cam-icon {
            width: 44px;
            height: 44px;
            color: #10b981;
            opacity: 0.85;
          }
          .no-cam-title {
            font-size: 15px;
            font-weight: 600;
            color: #ffffff;
          }
          .toast {
            position: absolute;
            bottom: 60px;
            left: 50%;
            transform: translateX(-50%) translateY(20px);
            background: rgba(24, 24, 27, 0.96);
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: #ffffff;
            padding: 7px 16px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 500;
            pointer-events: none;
            opacity: 0;
            transition: all 0.25s ease;
            z-index: 10;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
            white-space: nowrap;
          }
          .toast.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
          }
        </style>

        <div class="card">
          <div class="incoming-call-banner">
            <div>🔔 Входящий вызов!</div>
            <div class="call-actions">
              <button class="btn-call-action btn-call-answer">Ответить</button>
              <button class="btn-call-action btn-call-open">Открыть</button>
            </div>
          </div>

          ${
            hasCam
              ? `
            <div class="video-container">
              <div class="placeholder">
                <svg class="placeholder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
                  <circle cx="12" cy="13" r="3"/>
                </svg>
                <div class="placeholder-text">Загрузка снимка...</div>
              </div>
              <div class="loader-spinner"></div>
              <img class="camera-feed" alt="${title}" />
              <div class="header-overlay">
                <div class="gate-title-group">
                  <div class="status-dot"></div>
                  <div class="gate-title">${title}</div>
                </div>
                <div class="badge-live-tag">ЭФИР</div>
              </div>
            </div>
            `
              : `
            <div class="no-cam-box">
              <svg class="no-cam-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18"/>
                <path d="M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16"/>
                <circle cx="9" cy="12" r="1"/>
              </svg>
              <div class="no-cam-title">${title}</div>
            </div>
            `
          }

          <div class="bottom-bar">
            <div class="status-info">
              <div class="status-dot"></div>
              <span class="status-text">Контроллер онлайн</span>
            </div>
            <button class="btn-open-main">
              <span>🚪</span>
              <span class="btn-text">${openBtnText}</span>
            </button>
          </div>
        </div>
      `;

      const videoBox = this.shadowRoot.querySelector(".video-container");
      const openBtn = this.shadowRoot.querySelector(".btn-open-main");
      const callAnswerBtn = this.shadowRoot.querySelector(".btn-call-answer");
      const callOpenBtn = this.shadowRoot.querySelector(".btn-call-open");

      if (videoBox) {
        videoBox.addEventListener("click", () => this._openLiveModal());
      }
      if (openBtn) {
        openBtn.addEventListener("click", (e) => this._handleOpenGate(e));
      }
      if (callAnswerBtn) {
        callAnswerBtn.addEventListener("click", () => {
          this._hass?.callService("akvilon_home", "intercom_answer", {});
        });
      }
      if (callOpenBtn) {
        callOpenBtn.addEventListener("click", (e) => this._handleOpenGate(e));
      }

      this._restoreCachedSnapshot();
    }
  }

  if (!customElements.get(CARD_TYPE)) {
    customElements.define(CARD_TYPE, AkvilonIntercomCard);
  }

  // Каталог карточек Home Assistant
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === CARD_TYPE)) {
    window.customCards.push({
      type: CARD_TYPE,
      name: "Аквилон Видеодомофон и калитка",
      description: "Легкая карточка калитки с быстрым предпросмотром, прямым эфиром и кнопкой открытия",
      preview: false,
    });
  }

  console.info(`%c ${CARD_TYPE} v2.5 loaded`, "color:#10b981; font-weight:bold;");
})();
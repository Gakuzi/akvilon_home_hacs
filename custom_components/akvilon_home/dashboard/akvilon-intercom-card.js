/*!
 * Akvilon InHome — custom card «Видеодомофон» (intercom + входящий вызов)
 *
 * Что умеет:
 *  1. Карточка домофона/калитки с камерой и кнопками:
 *       Принять звук / Ответить / Открыть дверь / Сброс.
 *  2. Полноэкранный режим «Входящий вызов»: если задан `call_sensor`
 *     (binary_sensor.akvilon_home_intercom_call_*), при его включении
 *     карточка разворачивает камеру на весь экран с теми же кнопками.
 *  3. Автопривязка камеры к домофону: из атрибутов call_sensor (camera_id)
 *     или из cameraId калитки. Если ничего не задано — берётся camera_entity
 *     из конфига, либо камера подбирается по имени.
 *  4. Кнопки вызывают сервисы интеграции:
 *       akvilon_home.intercom_accept_audio / intercom_answer / intercom_unlock,
 *       с запасным вариантом open_gate / button.press.
 * Всё подтягивается из активной темы Home Assistant (CSS-переменные).
 *
 * Регистрация: window.customCards.push({ type: "akvilon-intercom-card" }).
 */
/* global customElements, LitElement, html, css, fireEvent */

const CARD_VERSION = "2.0.0";
const IS_ON = new Set(["on", "true", "1", "yes", "open", "ring", "active"]);
const DOMAIN_SERVICE_PREFIX = "akvilon_home.";

function truthy(val) {
  if (val === undefined || val === null) return false;
  if (typeof val === "boolean") return val;
  return IS_ON.has(String(val).toLowerCase());
}

class AkvilonIntercomCard extends LitElement {
  static get properties() {
    return {
      _hass: { type: Object },
      _config: { type: Object },
      _fullscreen: { type: Boolean, reflect: true },
      _callOpen: { type: Boolean, reflect: true },
      _error: { type: String },
    };
  }

  static getConfigElement() {
    return document.createElement("akvilon-intercom-card-editor");
  }

  static getStubConfig() {
    return {
      title: "Домофон",
      call_sensor: "binary_sensor.akvilon_home_intercom_call_1",
      camera_entity: "camera.kamera_paradnaia_1_2",
      gate_button: "button.otkryt_reka_4_prokhod_1_2",
      status_sensor: "sensor.kalitka_reka_4_prokhod_1_2_sostoianie",
      show_fullscreen_button: true,
    };
  }

  setConfig(config) {
    if (!config) throw new Error("Не задана конфигурация карточки");
    this._config = {
      title: "Домофон",
      show_fullscreen_button: true,
      auto_answer_audio: false,
      ...config,
    };
    // сбрасываем состояние вызова при новой конфигурации
    this._callOpen = false;
  }

  set hass(hass) {
    this._hass = hass;
    // следим за входящим вызовом: если call_sensor выключился —
    // закрываем оверлей
    if (this._config?.call_sensor) {
      const st = this._stateOf(this._config.call_sensor);
      if (st && !truthy(st.state) && this._callOpen) {
        this._callOpen = false;
      }
    }
  }

  get hass() {
    return this._hass;
  }

  // ---------- helpers ----------
  _stateOf(entity) {
    if (!this._hass || !entity) return null;
    return this._hass.states[entity] || null;
  }

  _attrOf(entity, key) {
    const s = this._stateOf(entity);
    return s ? s.attributes[key] : undefined;
  }

  _friendlyName(entity) {
    const s = this._stateOf(entity);
    if (s) return s.attributes.friendly_name || entity;
    return entity;
  }

  // Разрешение камеры из вызова: приоритет — атрибуты call_sensor.
  _resolveCallCamera() {
    const cfg = this._config || {};
    const call = this._stateOf(cfg.call_sensor);
    if (call) {
      const camId = call.attributes["camera_id"] || call.attributes["cameraId"] || "";
      if (camId) {
        const camTail = String(camId).split(":").pop();
        // ищем сущность camera.* по object_id в атрибутах
        for (const eid in this._hass.states) {
          if (!eid.startsWith("camera.")) continue;
          const st = this._hass.states[eid];
          const oid = String(
            st.attributes["object_id"] || st.attributes["objectId"] || ""
          );
          if (oid === String(camId) || oid.split(":").pop() === camTail) {
            return eid;
          }
        }
      }
      // иначе — по camera_name из вызова
      const camName = call.attributes["camera_name"] || "";
      if (camName) {
        const hit = this._findCameraByName(camName);
        if (hit) return hit;
      }
    }
    // конфиг-камера (если задана)
    if (cfg.camera_entity && this._stateOf(cfg.camera_entity)) {
      return cfg.camera_entity;
    }
    return cfg.camera_entity || "";
  }

  _findCameraByName(name) {
    const n = String(name).toLowerCase();
    if (!n) return null;
    for (const eid in this._hass.states) {
      if (!eid.startsWith("camera.")) continue;
      const fn = this._stateOf(eid).attributes.friendly_name || "";
      if (String(fn).toLowerCase().includes(n)) return eid;
    }
    return null;
  }

  // Разрешение калитки/двери из вызова.
  _resolveCallGateId() {
    const cfg = this._config || {};
    const call = this._stateOf(cfg.call_sensor);
    if (call) {
      const gid =
        call.attributes["gate_id"] ||
        call.attributes["gateId"] ||
        call.attributes["id"] ||
        "";
      if (gid) return gid;
    }
    return cfg.gate_id || "";
  }

  callCameraEntity() {
    return this._resolveCallCamera();
  }

  // Живой URL кадра камеры (HA camera_proxy), либо entity_picture.
  _cameraImg() {
    const cam = this.callCameraEntity();
    if (!cam) return null;
    const st = this._stateOf(cam);
    if (st?.attributes?.entity_picture) {
      return st.attributes.entity_picture;
    }
    // стандартный proxy HA: /api/camera_proxy_stream/<entity> — даёт кадр
    return this._hass.hassUrl(`/api/camera_proxy_stream/${cam}`);
  }

  // ---------- действия (сервисы интеграции) ----------
  async _callService(service, data) {
    if (!this._hass) return;
    try {
      await this._hass.callService(DOMAIN_SERVICE_PREFIX, service, data || {});
    } catch (e) {
      console.error(`[akvilon-intercom] service ${service} error`, e);
      this._error = String(e && e.message ? e.message : e);
      setTimeout(() => (this._error = null), 4000);
    }
  }

  // Открыть дверь: intercom_unlock, запасные open_gate / button.press.
  async _openGate() {
    const gateId = this._resolveCallGateId();
    if (gateId) {
      await this._callService("intercom_unlock", { gate_id: gateId });
      return;
    }
    const btn = this._config?.gate_button;
    if (btn) {
      await this._hass?.callService("button", "press", { entity_id: btn });
      return;
    }
    // последний запасной: калитка по имени кнопки не найдена
    await this._callService("open_gate", { gate_id: gateId });
  }

  // Ответить: intercom_answer (+ опционально принять звук сразу).
  async _answer() {
    const cam = this._resolveCallCamera();
    const gateId = this._resolveCallGateId();
    const data = {};
    if (cam) {
      const st = this._stateOf(cam);
      const oid = st?.attributes["object_id"] || st?.attributes["objectId"];
      if (oid) data.camera_id = oid;
    }
    if (gateId) data.gate_id = gateId;
    await this._callService("intercom_answer", data);
    if (this._config.auto_answer_audio) await this._acceptAudio();
  }

  // Принять звук (голосовой канал).
  async _acceptAudio() {
    const cam = this._resolveCallCamera();
    const data = {};
    if (cam) {
      const st = this._stateOf(cam);
      const oid = st?.attributes["object_id"] || st?.attributes["objectId"];
      if (oid) data.camera_id = oid;
    }
    await this._callService("intercom_accept_audio", data);
  }

  _dismiss() {
    this._callOpen = false;
    if (this._config?.call_sensor) {
      // сброс фиксируется локально; сенсор выключится сам, когда сервер
      // закончит вызов (или через automation).
    }
  }

  _toggleFullscreen() {
    this._fullscreen = !this._fullscreen;
    fireEvent(this, "akvilon-intercom-fullscreen", {
      fullscreen: this._fullscreen,
    });
  }

  // ---------- render ----------
  render() {
    if (!this._config || !this._hass) return html``;

    const title = this._config.title || "Домофон";
    const camEntity = this.callCameraEntity();
    const camUrl = camEntity ? this._cameraImg() : null;

    // входящий вызов: включаем оверлей, если сенсор активен
    let callActive = false;
    let callFrom = null;
    if (this._config.call_sensor) {
      const st = this._stateOf(this._config.call_sensor);
      callActive = truthy(st?.state);
      if (callActive) {
        callFrom =
          st.attributes["gate_name"] ||
          st.attributes["camera_name"] ||
          title;
      }
    }

    const showOverlay = callActive || this._callOpen;
    const status = this._stateOf(this._config.status_sensor);
    const statusName = this._config.status_sensor
      ? this._friendlyName(this._config.status_sensor)
      : null;
    const statusVal =
      status && status.state !== "unknown"
        ? status.state
        : statusName
        ? "неизвестно"
        : "—";

    if (showOverlay) {
      return this._renderCallOverlay({
        title,
        from: callFrom,
        camUrl,
        cameraLabel: camEntity ? this._friendlyName(camEntity) : null,
      });
    }

    return html`
      <ha-card class="card ${this._fullscreen ? "fullscreen" : ""}">
        <div class="video" @click=${() => this._toggleFullscreen()}>
          ${camUrl
            ? html`<img src=${camUrl} alt=${title} />`
            : html`<div class="placeholder">📷 ${camEntity || "видео недоступно"}</div>`}
          <span class="live">LIVE</span>
          <span class="name">${title}</span>
        </div>
        <div class="controls">
          <button class="ctrl sound" title="Принять звук" @click=${() => this._acceptAudio()}>
            <ha-icon icon="mdi:volume-high"></ha-icon><span>Звук</span>
          </button>
          <button class="ctrl open" title="Открыть дверь" @click=${() => this._openGate()}>
            <ha-icon icon="mdi:door-open"></ha-icon><span>Открыть</span>
          </button>
          <button class="ctrl answer" title="Ответить" @click=${() => this._answer()}>
            <ha-icon icon="mdi:phone"></ha-icon><span>Ответить</span>
          </button>
          ${this._config.show_fullscreen_button
            ? html`<button class="ctrl fs" title="Во весь экран" @click=${() => this._toggleFullscreen()}>
                <ha-icon icon=${this._fullscreen ? "mdi:fullscreen-exit" : "mdi:fullscreen"}></ha-icon>
                <span>Развернуть</span>
              </button>`
            : ""}
        </div>
        ${this._error
          ? html`<div class="error">${this._error}</div>`
          : ""}
        ${statusName
          ? html`<div class="foot">
              <span class="state ${truthy(status?.state) ? "on" : ""}">● ${statusName}: ${statusVal}</span>
            </div>`
          : ""}
      </ha-card>
    `;
  }

  _renderCallOverlay({ title, from, camUrl, cameraLabel }) {
    return html`
      <ha-card class="overlay">
        <div class="ov-video">
          ${camUrl
            ? html`<img src=${camUrl} alt=${title} />`
            : html`<div class="placeholder big">📷 ${cameraLabel || "видео недоступно"}</div>`}
          <div class="ov-hud">
            <span class="live">LIVE</span>
            <span class="ov-ring">🔔 Входящий вызов…</span>
            <span class="ov-name">${from || title}</span>
          </div>
        </div>
        <div class="ov-controls">
          <button class="ctrl sound" title="Принять звук" @click=${() => this._acceptAudio()}>
            <ha-icon icon="mdi:volume-high"></ha-icon><span>Звук</span>
          </button>
          <button class="ctrl open" title="Открыть дверь" @click=${() => this._openGate()}>
            <ha-icon icon="mdi:door-open"></ha-icon><span>Открыть</span>
          </button>
          <button class="ctrl answer" title="Ответить" @click=${() => this._answer()}>
            <ha-icon icon="mdi:phone"></ha-icon><span>Ответить</span>
          </button>
          <button class="ctrl hang" title="Сброс" @click=${() => this._dismiss()}>
            <ha-icon icon="mdi:phone-hangup"></ha-icon><span>Сброс</span>
          </button>
        </div>
        ${this._error
          ? html`<div class="error overlay-error">${this._error}</div>`
          : ""}
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      :host { --ac: var(--primary-color, var(--state-active-color, #03a9f4)); }
      .card {
        display: flex; flex-direction: column;
        background: var(--card-background-color, var(--secondary-background-color, #fff));
        color: var(--primary-text-color, #000);
        border: none; border-radius: 14px; overflow: hidden;
        height: 100%; min-height: 200px;
      }
      .card.fullscreen {
        position: fixed; inset: 40px; z-index: 999;
        border-radius: 0; box-shadow: none;
      }
      .video {
        position: relative; flex: 1; min-height: 140px;
        background: var(--primary-background-color, #000);
        display: flex; align-items: center; justify-content: center;
        cursor: pointer; overflow: hidden;
      }
      .video img { width: 100%; height: 100%; object-fit: cover; }
      .video .placeholder {
        color: var(--secondary-text-color, #888); font-size: 16px;
        display: flex; flex-direction: column; align-items: center; gap: 8px;
      }
      .placeholder.big { font-size: 22px; }
      .video .live, .ov-hud .live {
        position: absolute; top: 8px; left: 8px;
        background: var(--error-color, #e53935); color: #fff;
        font-size: 11px; font-weight: 700; letter-spacing: 1px;
        padding: 3px 8px; border-radius: 4px;
      }
      .video .name {
        position: absolute; bottom: 8px; left: 8px; right: 8px;
        background: rgba(0,0,0,.45); color: #fff; font-size: 13px;
        padding: 4px 8px; border-radius: 4px;
      }
      .controls {
        display: flex; gap: 6px; padding: 10px;
        background: var(--card-background-color);
        flex-wrap: wrap;
      }
      .ctrl {
        flex: 1; min-width: 60px;
        display: flex; flex-direction: column; align-items: center; gap: 4px;
        background: var(--divider-color, #eee); color: var(--primary-text-color);
        border: none; border-radius: 10px; padding: 8px 4px; font-size: 11px;
        cursor: pointer;
      }
      .ctrl:hover { filter: brightness(1.05); }
      .ctrl.open { background: var(--primary-color); color: #fff; }
      .ctrl.answer { background: var(--state-active-color, #00c853); color: #fff; }
      .ctrl.sound, .ctrl.fs { background: var(--secondary-color, #f5f5f5); }
      .ctrl.hang { background: var(--error-color, #e53935); color: #fff; }
      .error {
        padding: 6px 12px; font-size: 12px;
        color: #fff; background: var(--error-color, #e53935);
      }
      .overlay {
        position: fixed; inset: 0; z-index: 10000;
        display: flex; flex-direction: column;
        background: var(--primary-background-color, #000);
        color: var(--primary-text-color, #fff);
        border: none; border-radius: 0; overflow: hidden;
      }
      .ov-video { position: relative; flex: 1; overflow: hidden; }
      .ov-video img { width: 100%; height: 100%; object-fit: contain; background: #000; }
      .ov-video .placeholder {
        position: absolute; inset: 0;
        display: flex; align-items: center; justify-content: center;
        color: var(--secondary-text-color, #888); font-size: 22px;
      }
      .ov-hud {
        position: absolute; top: 0; left: 0; right: 0;
        display: flex; align-items: center; gap: 12px; padding: 12px;
        background: linear-gradient(rgba(0,0,0,.7), transparent);
      }
      .ov-hud .ov-ring {
        margin-left: auto; font-size: 15px; font-weight: 700;
        color: var(--state-active-color, #22c55e);
      }
      .ov-hud .ov-name {
        background: rgba(0,0,0,.55); color: #fff; padding: 6px 12px;
        border-radius: 8px; font-size: 14px;
      }
      .ov-controls {
        display: flex; gap: 14px; padding: 20px 16px 28px;
        justify-content: center; align-items: center;
        background: linear-gradient(transparent, rgba(0,0,0,.85));
      }
      .ov-controls .ctrl {
        width: 84px; height: 84px; flex: none; min-width: 0;
        border-radius: 50%; font-size: 12px; gap: 6px; padding: 6px;
      }
      .overlay-error {
        position: absolute; bottom: 120px; left: 12px; right: 12px;
        border-radius: 8px; text-align: center;
      }
      .foot {
        padding: 6px 12px; font-size: 12px;
        color: var(--secondary-text-color);
        background: var(--card-background-color);
        border-top: 1px solid var(--divider-color);
      }
      .state.on { color: var(--state-active-color, #00c853); }
    `;
  }
}

customElements.define("akvilon-intercom-card", AkvilonIntercomCard);

// Простой редактор конфига
class AkvilonIntercomCardEditor extends LitElement {
  static get properties() {
    return { hass: { type: Object }, config: { type: Object } };
  }
  setConfig(config) {
    this.config = config;
  }
  static get styles() {
    return css`
      .row { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; }
      input, select { width: 100%; padding: 8px; box-sizing: border-box; }
    `;
  }
  _valueChanged(e, key) {
    const val = e.target.value;
    const cfg = { ...(this.config || {}) };
    cfg[key] = val;
    fireEvent(this, "config-changed", { config: cfg });
  }
  render() {
    const c = this.config || {};
    const row = (label, key, placeholder) => html`
      <div class="row">
        <label>${label}</label>
        <input .value=${c[key] || ""} placeholder=${placeholder} @change=${(e) => this._valueChanged(e, key)} />
      </div>`;
    return html`
      ${row("Название", "title", "Домофон")}
      ${row("Входящий вызов (binary_sensor)", "call_sensor", "binary_sensor.akvilon_home_intercom_call_1")}
      ${row("Камера (entity)", "camera_entity", "camera.kamera_...")}
      ${row("Кнопка открытия (entity)", "gate_button", "button.otkryt_...")}
      ${row("Сенсор состояния (entity)", "status_sensor", "sensor.kalitka_...")}
    `;
  }
}
customElements.define("akvilon-intercom-card-editor", AkvilonIntercomCardEditor);

// Регистрация в каталоге custom cards
window.customCards = window.customCards || [];
window.customCards.push({
  type: "akvilon-intercom-card",
  name: "Аквилон Видеодомофон",
  description:
    "Карточка домофона с камерой; при входящем вызове — полноэкранный оверлей с кнопками Принять звук / Ответить / Открыть",
  preview: false,
  documentationURL: "https://github.com/Gakuzi/akvilon_home",
});

console.info(`%c akvilon-intercom-card ${CARD_VERSION} loaded`, "color:#2dd4bf");
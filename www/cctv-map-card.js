/**
 * Akvilon InHome — Interactive CCTV Campus Floorplan Card with Live Visual Editor
 * Custom card for Home Assistant Lovelace (ЖК «Река», ул. Советская)
 *
 * Full Feature Set:
 *  1. Interactive floorplan overlay with exact camera positions.
 *  2. Real-time vision sectors (FOV cones) with radar sweep pulse and gradients.
 *  3. Compact live preview popup modal (маленькое окно) on camera click in View mode.
 *  4. Direct integrated gate & intercom unlock buttons with countdown & haptic feedback.
 *  5. VISUAL EDITOR MODE (⚙️ Управление камерами):
 *     - Drag-and-drop cameras on the map ONLY when holding Left Shift (as requested).
 *     - NO hover jitter: SVG coordinates are completely protected from CSS transform overrides.
 *     - Interactive rotation handle on the map to rotate cameras 360°.
 *     - Interactive distance / FOV handles to scale the vision cone reach and angle.
 *     - Floating property inspector with precision sliders and building assignment.
 *  6. CAMERA LIST & ADD CAMERA (+):
 *     - «➕ Добавить камеру»: dialog listing all Home Assistant cameras with search.
 *     - Automatically links matching gate/intercom unlock buttons (`button.otkryt_...`).
 *     - «📋 Список камер»: drawer of all placed cameras with live search and locator.
 *     - Delete camera from map.
 *  7. PERSISTENCE:
 *     - Saves directly to Home Assistant Lovelace config via WebSocket (`lovelace/config/save`).
 *     - Secondary backup in browser `localStorage`.
 *  8. Multi-device touch & mouse support (pinch-to-zoom, pan, drag-and-drop).
 */

(function () {
  const CARD_TAG = "akvilon-cctv-map-card";
  const CARD_ALIAS = "cctv-map-card";

  // Pre-configured campus cameras with exact coordinates on cctv_plan.jpg (2112 x 2016)
const DEFAULT_CAMERAS = [
    {
        "id": "camera.kamera_ul_sovetskaia",
        "name": "ул. Советская (Север)",
        "building": "Советская",
        "category": "street",
        "x": 18.5,
        "y": 28.0,
        "angle": 165,
        "fov": 70,
        "distance": 14.0
    },
    {
        "id": "camera.kamera_ul_sovetskaia_2pod",
        "name": "ул. Советская (2 подъезд)",
        "building": "Дом 4",
        "category": "street",
        "x": 21.0,
        "y": 39.0,
        "angle": 180,
        "fov": 65,
        "distance": 12.0
    },
    {
        "id": "camera.kamera_ul_sovetskaia_2",
        "name": "ул. Советская (Центр)",
        "building": "Советская",
        "category": "street",
        "x": 18.5,
        "y": 47.0,
        "angle": 175,
        "fov": 70,
        "distance": 14.0
    },
    {
        "id": "camera.kamera_ul_sovetskaia_3_pod",
        "name": "ул. Советская (3 подъезд)",
        "building": "Дом 4",
        "category": "street",
        "x": 21.0,
        "y": 56.0,
        "angle": 180,
        "fov": 65,
        "distance": 12.0
    },
    {
        "id": "camera.kamera_ul_sovetskaia_3",
        "name": "ул. Советская (Юг)",
        "building": "Советская",
        "category": "street",
        "x": 18.5,
        "y": 65.0,
        "angle": 190,
        "fov": 70,
        "distance": 14.0
    },
    {
        "id": "camera.kamera_ul_sovetskaia_4",
        "name": "ул. Советская (Дом 2)",
        "building": "Дом 2",
        "category": "street",
        "x": 18.5,
        "y": 77.0,
        "angle": 195,
        "fov": 70,
        "distance": 14.0
    },
    {
        "id": "camera.kamera_kalitka_6_reka_4",
        "name": "Калитка 6 (Река 4)",
        "building": "Дом 4",
        "category": "gate",
        "x": 25.8,
        "y": 37.0,
        "angle": 13,
        "fov": 50,
        "distance": 13.5,
        "gate_button": "button.otkryt_kalitka_6",
        "status_sensor": "sensor.kalitka_kalitka_6_sostoianie"
    },
    {
        "id": "camera.kamera_4",
        "name": "Камера 4 (Калитка 4)",
        "building": "Дом 4",
        "category": "gate",
        "x": 25.5,
        "y": 43.0,
        "angle": 338,
        "fov": 50,
        "distance": 15.0,
        "gate_button": "button.otkryt_kalitka_4",
        "status_sensor": "sensor.kalitka_kalitka_4_sostoianie"
    },
    {
        "id": "camera.kamera_dvor_3",
        "name": "Двор 3 (Калитка 3)",
        "building": "Дом 4",
        "category": "gate",
        "x": 28.5,
        "y": 45.0,
        "angle": 14,
        "fov": 42,
        "distance": 12.7,
        "gate_button": "button.otkryt_kalitka_3",
        "status_sensor": "sensor.kalitka_kalitka_3_sostoianie"
    },
    {
        "id": "camera.kamera_dvor_2",
        "name": "Двор 2 (Калитка 2)",
        "building": "Дом 4",
        "category": "gate",
        "x": 28.3,
        "y": 52.0,
        "angle": 341,
        "fov": 50,
        "distance": 18.4,
        "gate_button": "button.otkryt_kalitka_2",
        "status_sensor": "sensor.kalitka_kalitka_2_sostoianie"
    },
    {
        "id": "camera.kamera_paradnaia_1_1",
        "name": "Парадная 1-1 (Домофон)",
        "building": "Дом 4",
        "category": "entrance",
        "x": 29.3,
        "y": 53.2,
        "angle": 6,
        "fov": 60,
        "distance": 9.0,
        "gate_button": "button.otkryt_domofon_reka4_prohod_1_1",
        "status_sensor": "sensor.kalitka_reka4_prohod_1_1_sostoianie"
    },
    {
        "id": "camera.kamera_paradnaia_1_2",
        "name": "Парадная 1-2 (Домофон)",
        "building": "Дом 4",
        "category": "entrance",
        "x": 23.6,
        "y": 53.5,
        "angle": 179,
        "fov": 60,
        "distance": 6.0,
        "gate_button": "button.otkryt_domofon_reka_4_prokhod_1_2",
        "status_sensor": "sensor.kalitka_reka_4_prokhod_1_2_sostoianie"
    },
    {
        "id": "camera.kamera_paradnaia_2_1",
        "name": "Парадная 2-1",
        "building": "Дом 4",
        "category": "entrance",
        "x": 28.9,
        "y": 47.2,
        "angle": 2,
        "fov": 60,
        "distance": 9.0,
        "gate_button": "button.otkryt_reka4_prohod_1_1"
    },
    {
        "id": "camera.kamera_paradnaia_2_2",
        "name": "Парадная 2-2",
        "building": "Дом 4",
        "category": "entrance",
        "x": 23.5,
        "y": 45.0,
        "angle": 183,
        "fov": 60,
        "distance": 6.3,
        "gate_button": "button.otkryt_reka_4_prokhod_1_2"
    },
    {
        "id": "camera.kamera_paradnaia_3_1",
        "name": "Парадная 3-1",
        "building": "Дом 4",
        "category": "entrance",
        "x": 29.5,
        "y": 41.0,
        "angle": 10,
        "fov": 60,
        "distance": 8.5,
        "gate_button": "button.otkryt_domofon_reka4_prohod_1_1"
    },
    {
        "id": "camera.kamera_paradnaia_3_2",
        "name": "Парадная 3-2",
        "building": "Дом 4",
        "category": "entrance",
        "x": 23.2,
        "y": 39.5,
        "angle": 180,
        "fov": 60,
        "distance": 6.5,
        "gate_button": "button.otkryt_domofon_reka_4_prokhod_1_2"
    },
    {
        "id": "camera.kamera_prokhod_3_i_4_kor",
        "name": "Проход 3 и 4 кор.",
        "building": "Дом 4",
        "category": "yard",
        "x": 23.7,
        "y": 58.6,
        "angle": 13,
        "fov": 30,
        "distance": 6.0
    },
    {
        "id": "camera.kamera_dvor_5",
        "name": "Двор 5 (Калитка 5)",
        "building": "Дом 24",
        "category": "gate",
        "x": 30.2,
        "y": 30.9,
        "angle": 30,
        "fov": 39,
        "distance": 19.0,
        "gate_button": "button.otkryt_kalitka_5",
        "status_sensor": "sensor.kalitka_kalitka_5_sostoianie"
    },
    {
        "id": "camera.kamera_dvor_1",
        "name": "Двор 1 (Калитка 1)",
        "building": "Дом 24",
        "category": "gate",
        "x": 45.0,
        "y": 25.0,
        "angle": 135,
        "fov": 75,
        "distance": 16.0,
        "gate_button": "button.otkryt_kalitka_1",
        "status_sensor": "sensor.kalitka_kalitka_1_sostoianie"
    },
    {
        "id": "camera.kamera_kalitka_8_reka_5",
        "name": "Калитка 8 (Река 5)",
        "building": "Дом 24",
        "category": "gate",
        "x": 55.0,
        "y": 23.5,
        "angle": 293,
        "fov": 70,
        "distance": 8.5,
        "gate_button": "button.otkryt_kalitka_8",
        "status_sensor": "sensor.kalitka_kalitka_8_sostoianie"
    },
    {
        "id": "camera.kamera_reka_5_podezd_1",
        "name": "Reka 5 (Подъезд 1)",
        "building": "Дом 24",
        "category": "entrance",
        "x": 43.5,
        "y": 21.0,
        "angle": 85,
        "fov": 60,
        "distance": 8.0,
        "gate_button": "button.otkryt_kalitka_7"
    },
    {
        "id": "camera.kamera_reka_5_podezd_2_1",
        "name": "Reka 5 (Подъезд 2-1)",
        "building": "28 к 1",
        "category": "entrance",
        "x": 41.9,
        "y": 24.2,
        "angle": 105,
        "fov": 60,
        "distance": 9.6
    },
    {
        "id": "camera.kamera_reka_5_podezd_2_2",
        "name": "Reka 5 (Подъезд 2-2)",
        "building": "28 к 1",
        "category": "entrance",
        "x": 39.5,
        "y": 24.0,
        "angle": 260,
        "fov": 60,
        "distance": 8.0
    },
    {
        "id": "camera.kamera_reka_5_8",
        "name": "Reka 5, 8 (Дом 4 к2)",
        "building": "Дом 24",
        "category": "yard",
        "x": 47.3,
        "y": 21.5,
        "angle": 18,
        "fov": 70,
        "distance": 6.0
    },
    {
        "id": "camera.kamera_prokhod_4_i_5_kor",
        "name": "Проход 4 и 5 кор.",
        "building": "Дом 2",
        "category": "yard",
        "x": 32.0,
        "y": 27.7,
        "angle": 229,
        "fov": 79,
        "distance": 6.0
    },
    {
        "id": "camera.kamera_kalitka_9_reka_6",
        "name": "Калитка 9 (Река 6)",
        "building": "Дом 26",
        "category": "gate",
        "x": 51.1,
        "y": 23.0,
        "angle": 294,
        "fov": 70,
        "distance": 6.0,
        "gate_button": "button.otkryt_kalitka_9",
        "status_sensor": "sensor.kalitka_kalitka_9_sostoianie"
    },
    {
        "id": "camera.kamera_kalitka_10_reka_6",
        "name": "Калитка 10 (Река 6)",
        "building": "Дом 26",
        "category": "gate",
        "x": 60.7,
        "y": 25.6,
        "angle": 293,
        "fov": 70,
        "distance": 6.0,
        "gate_button": "button.otkryt_kalitka_10",
        "status_sensor": "sensor.kalitka_kalitka_10_sostoianie"
    },
    {
        "id": "camera.kamera_reka_6_podezd_1",
        "name": "Reka 6 (Подъезд 1)",
        "building": "Дом 26",
        "category": "entrance",
        "x": 51.5,
        "y": 29.0,
        "angle": 260,
        "fov": 60,
        "distance": 9.0
    },
    {
        "id": "camera.kamera_reka_6_cam_17",
        "name": "Reka 6 (Северный проезд)",
        "building": "Дом 26",
        "category": "yard",
        "x": 45.9,
        "y": 23.5,
        "angle": 83,
        "fov": 41,
        "distance": 10.2
    },
    {
        "id": "camera.kamera_reka_6_cam_18",
        "name": "Reka 6 (Периметр / Парковка)",
        "building": "Дом 26",
        "category": "yard",
        "x": 55.5,
        "y": 27.0,
        "angle": 30,
        "fov": 70,
        "distance": 16.0
    },
    {
        "id": "camera.kamera_kalitka_11_reka_7",
        "name": "Калитка 11 (Река 7)",
        "building": "Дом 28",
        "category": "gate",
        "x": 63.6,
        "y": 27.1,
        "angle": 332,
        "fov": 57,
        "distance": 8.8,
        "gate_button": "button.otkryt_kalitka_11",
        "status_sensor": "sensor.kalitka_kalitka_11_sostoianie"
    },
    {
        "id": "camera.kamera_reka_7_vid_na_kalitku_2",
        "name": "Reka 7 (Вид на калитку 11)",
        "building": "Дом 28",
        "category": "gate",
        "x": 65.2,
        "y": 29.1,
        "angle": 221,
        "fov": 70,
        "distance": 6.0,
        "gate_button": "button.otkryt_kalitka_11"
    },
    {
        "id": "camera.kamera_kalitka_12_reka_7",
        "name": "Калитка 12 (Река 7)",
        "building": "Дом 28",
        "category": "gate",
        "x": 67.1,
        "y": 44.0,
        "angle": 5,
        "fov": 70,
        "distance": 6.0,
        "gate_button": "button.otkryt_kalitka_12",
        "status_sensor": "sensor.kalitka_kalitka_12_sostoianie"
    },
    {
        "id": "camera.kamera_reka_7_vid_na_kalitku",
        "name": "Reka 7 (Вид на калитку 12)",
        "building": "Дом 28",
        "category": "gate",
        "x": 67.5,
        "y": 41.5,
        "angle": 90,
        "fov": 70,
        "distance": 6.0,
        "gate_button": "button.otkryt_kalitka_12"
    },
    {
        "id": "camera.kamera_reka_7_podezd_1",
        "name": "Reka 7 (Подъезд 1)",
        "building": "Дом 28",
        "category": "entrance",
        "x": 63.9,
        "y": 35.0,
        "angle": 197,
        "fov": 60,
        "distance": 6.0
    },
    {
        "id": "camera.kamera_reka_7_torets_doma",
        "name": "Reka 7 (Торец дома)",
        "building": "Дом 28",
        "category": "yard",
        "x": 69.5,
        "y": 28.1,
        "angle": 11,
        "fov": 75,
        "distance": 6.0
    },
    {
        "id": "camera.kamera_reka_7_proezd",
        "name": "Reka 7 (Проезд)",
        "building": "Дом 28",
        "category": "yard",
        "x": 68.0,
        "y": 34.0,
        "angle": 285,
        "fov": 50,
        "distance": 7.5
    },
    {
        "id": "camera.kamera_reka_7_proezd_2",
        "name": "Reka 7 (Проезд 2)",
        "building": "Дом 28",
        "category": "yard",
        "x": 68.2,
        "y": 38.5,
        "angle": 292,
        "fov": 30,
        "distance": 8.4
    },
    {
        "id": "camera.kamera_reka_7_detskaia_ploshchadka",
        "name": "Reka 7 (Детская площадка)",
        "building": "Двор",
        "category": "yard",
        "x": 58.5,
        "y": 42.0,
        "angle": 210,
        "fov": 65,
        "distance": 9.0
    },
    {
        "id": "camera.kamera_dvor_4",
        "name": "Двор 4 (Центральная аллея)",
        "building": "Двор",
        "category": "yard",
        "x": 29.9,
        "y": 30.1,
        "angle": 71,
        "fov": 30,
        "distance": 6.0
    },
    {
        "id": "camera.kamera_detskaia_komnata",
        "name": "Детская комната (Улыбка)",
        "building": "Двор",
        "category": "yard",
        "x": 26.3,
        "y": 56.6,
        "angle": 342,
        "fov": 80,
        "distance": 6.0
    },
    {
        "id": "camera.kamera_reka_5_3",
        "name": "Reka 5, 3 (28 к1, Юг)",
        "building": "28 к 1",
        "category": "yard",
        "x": 32.8,
        "y": 23.1,
        "angle": 16,
        "fov": 44,
        "distance": 6.0
    }
];

  const HOUSES = [
    "Дом 4",
    "Дом 2",
    "Дом 24",
    "Дом 26",
    "Дом 28",
    "28 к 1",
  ];

  class AkvilonCctvMapCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._hass = null;
      this._config = {};
      this._cameras = [];
      this._activeFilter = "all";
      this._showSectors = true;

      // Mode states
      this._editMode = false;
      this._editingCam = null;
      this._viewCam = null;
      this._showAddDialog = false;
      this._showListDrawer = false;
      this._camSearchQuery = "";
      this._isShiftPressed = false;

      // Dragging states
      this._dragMode = null; // 'cam-pos', 'rotate', 'dist', 'fov', 'pan'
      this._dragCam = null;
      this._dragStartX = 0;
      this._dragStartY = 0;

      // Pan & Zoom
      this._zoomLevel = 1.0;
      this._panX = 0;
      this._panY = 0;

      // Live video & gate countdown
      this._liveTimer = null;
      this._isOpeningGate = false;
      this._gateCountdown = 0;
      this._countdownInterval = null;
    }

    static getStubConfig() {
      return {
        type: `custom:${CARD_TAG}`,
        map_image: "/local/cctv_plan.jpg",
        title: "Видеонаблюдение ЖК «Река»",
        show_sectors: true,
        show_toolbar: true,
      };
    }

    setConfig(config) {
      if (!config) throw new Error("Invalid configuration");
      this._config = {
        map_image: "/local/cctv_plan.jpg",
        title: "Видеонаблюдение ЖК «Река»",
        show_sectors: true,
        show_toolbar: true,
        cameras: DEFAULT_CAMERAS,
        ...config,
      };

      const baseCameras = (this._config.cameras && this._config.cameras.length > 0)
        ? this._config.cameras
        : DEFAULT_CAMERAS;

      let mergedCameras = JSON.parse(JSON.stringify(baseCameras));

      let saved = null;
      try {
        const local = localStorage.getItem("cctv_map_cameras_v1");
        if (local) saved = JSON.parse(local);
      } catch (e) {}

      if (Array.isArray(saved) && saved.length > 0) {
        const savedMap = new Map();
        saved.forEach((c) => {
          if (c && c.id) savedMap.set(c.id, c);
        });

        // Merge saved positioning/properties into base cameras
        mergedCameras = mergedCameras.map((cam) => {
          const s = savedMap.get(cam.id);
          if (s) {
            return {
              ...cam,
              ...s,
              gate_button: s.gate_button !== undefined ? s.gate_button : cam.gate_button,
              status_sensor: s.status_sensor !== undefined ? s.status_sensor : cam.status_sensor,
            };
          }
          return cam;
        });

        // Preserve any custom cameras user manually added in editor that aren't in base
        const baseIds = new Set(mergedCameras.map((c) => c.id));
        saved.forEach((c) => {
          if (c && c.id && !baseIds.has(c.id)) {
            mergedCameras.push(c);
          }
        });
      }

      this._cameras = mergedCameras;
      this._showSectors = this._config.show_sectors !== false;
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
    }

    disconnectedCallback() {
      this._stopLiveStream();
      this._stopInspectorLiveStream();
      this._removeGlobalListeners();
    }

    // ==========================================
    // MATHEMATICAL SECTOR PATHS
    // ==========================================
    _getSectorPath(cx, cy, r, angleDeg, fovDeg) {
      const a1 = ((angleDeg - fovDeg / 2) * Math.PI) / 180;
      const a2 = ((angleDeg + fovDeg / 2) * Math.PI) / 180;
      const x1 = cx + r * Math.cos(a1);
      const y1 = cy + r * Math.sin(a1);
      const x2 = cx + r * Math.cos(a2);
      const y2 = cy + r * Math.sin(a2);
      const largeArc = fovDeg > 180 ? 1 : 0;
      return `M ${cx} ${cy} L ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r.toFixed(1)} ${r.toFixed(1)} 0 ${largeArc} 1 ${x2.toFixed(1)} ${y2.toFixed(1)} Z`;
    }

    _getSectorArc(cx, cy, r, angleDeg, fovDeg) {
      const a1 = ((angleDeg - fovDeg / 2) * Math.PI) / 180;
      const a2 = ((angleDeg + fovDeg / 2) * Math.PI) / 180;
      const x1 = cx + r * Math.cos(a1);
      const y1 = cy + r * Math.sin(a1);
      const x2 = cx + r * Math.cos(a2);
      const y2 = cy + r * Math.sin(a2);
      const largeArc = fovDeg > 180 ? 1 : 0;
      return `M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r.toFixed(1)} ${r.toFixed(1)} 0 ${largeArc} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`;
    }

    _filterCameras() {
      if (this._activeFilter === "all") return this._cameras;
      if (this._activeFilter === "gate") {
        return this._cameras.filter(
          (c) =>
            c.category === "gate" ||
            c.gate_button ||
            c.id.includes("kalitka") ||
            c.id.includes("domofon")
        );
      }
      if (this._activeFilter === "yard") {
        return this._cameras.filter(
          (c) => c.category === "yard" || c.building === "Двор"
        );
      }
      if (this._activeFilter === "street") {
        return this._cameras.filter(
          (c) => c.category === "street" || c.building === "Советская"
        );
      }
      return this._cameras.filter(
        (c) =>
          c.building === this._activeFilter ||
          (!c.building && c.name && c.name.includes(this._activeFilter))
      );
    }

    // ==========================================
    // RENDER MAIN COMPONENT
    // ==========================================
    _render() {
      if (!this.shadowRoot) return;

      const filteredCams = this._filterCameras();
      const gateCount = this._cameras.filter(
        (c) => c.category === "gate" || c.gate_button
      ).length;

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            position: relative;
            width: 100%;
            height: 100%;
            min-height: 85vh;
            background: #070b14;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            overflow: hidden;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.7);
            user-select: none;
          }

          /* Top Floating Control Bar */
          .toolbar {
            position: absolute;
            top: 14px;
            left: 14px;
            right: 14px;
            z-index: 30;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            background: ${this._editMode ? "rgba(24, 20, 13, 0.94)" : "rgba(15, 23, 42, 0.88)"};
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid ${this._editMode ? "rgba(245, 158, 11, 0.45)" : "rgba(255, 255, 255, 0.12)"};
            border-radius: 14px;
            padding: 8px 14px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
            flex-wrap: wrap;
            transition: all 0.25s ease;
          }

          .title-group {
            display: flex;
            align-items: center;
            gap: 10px;
          }

          .badge-cctv {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: ${this._editMode ? "rgba(245, 158, 11, 0.2)" : "rgba(0, 229, 255, 0.15)"};
            border: 1px solid ${this._editMode ? "#f59e0b" : "rgba(0, 229, 255, 0.4)"};
            color: ${this._editMode ? "#fcd34d" : "#00e5ff"};
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 4px 8px;
            border-radius: 6px;
          }

          .pulse-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: ${this._editMode ? "#f59e0b" : "#10b981"};
            box-shadow: 0 0 8px ${this._editMode ? "#f59e0b" : "#10b981"};
            animation: pulse-ring 1.5s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
          }

          @keyframes pulse-ring {
            0% { transform: scale(0.9); opacity: 1; }
            50% { transform: scale(1.3); opacity: 0.6; }
            100% { transform: scale(0.9); opacity: 1; }
          }

          .app-title {
            font-size: 14px;
            font-weight: 600;
            color: #f8fafc;
            letter-spacing: 0.3px;
          }

          /* Shift Key Indicator Badge in Edit Mode */
          .shift-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.18);
            color: #cbd5e1;
            font-size: 11px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 7px;
            transition: all 0.15s ease;
          }

          .shift-badge.active {
            background: rgba(16, 185, 129, 0.3);
            border-color: #10b981;
            color: #6ee7b7;
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.5);
          }

          /* Filter Chips */
          .filter-chips {
            display: flex;
            align-items: center;
            gap: 6px;
            overflow-x: auto;
            max-width: 100%;
            scrollbar-width: none;
          }
          .filter-chips::-webkit-scrollbar { display: none; }

          .chip {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #cbd5e1;
            padding: 5px 11px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            white-space: nowrap;
            display: inline-flex;
            align-items: center;
            gap: 5px;
          }

          .chip:hover {
            background: rgba(255, 255, 255, 0.15);
            color: #ffffff;
            border-color: rgba(255, 255, 255, 0.25);
          }

          .chip.active {
            background: #00d2ff;
            color: #04101e;
            border-color: #00d2ff;
            font-weight: 600;
            box-shadow: 0 0 14px rgba(0, 210, 255, 0.5);
          }

          .chip.gate-chip.active {
            background: #10b981;
            color: #032014;
            border-color: #10b981;
            box-shadow: 0 0 14px rgba(16, 185, 129, 0.5);
          }

          /* Action Controls */
          .tool-actions {
            display: flex;
            align-items: center;
            gap: 6px;
          }

          .btn-tool {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.14);
            color: #f8fafc;
            padding: 5px 11px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.18s ease;
          }

          .btn-tool:hover {
            background: rgba(255, 255, 255, 0.18);
          }

          .btn-tool.active {
            background: rgba(0, 210, 255, 0.2);
            border-color: #00d2ff;
            color: #00e5ff;
          }

          .btn-edit-mode {
            background: ${this._editMode ? "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)" : "rgba(245, 158, 11, 0.15)"};
            border: 1px solid #f59e0b;
            color: ${this._editMode ? "#1a0f02" : "#fcd34d"};
            font-weight: 700;
            box-shadow: ${this._editMode ? "0 0 16px rgba(245, 158, 11, 0.6)" : "none"};
          }
          .btn-edit-mode:hover {
            background: #f59e0b;
            color: #1a0f02;
          }

          .btn-save-cfg {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            border: 1px solid #34d399;
            color: #ffffff;
            font-weight: 700;
            box-shadow: 0 0 14px rgba(16, 185, 129, 0.5);
          }
          .btn-save-cfg:hover {
            background: #34d399;
          }

          .btn-add-cam {
            background: rgba(0, 210, 255, 0.2);
            border: 1px solid #00d2ff;
            color: #38bdf8;
            font-weight: 700;
          }
          .btn-add-cam:hover {
            background: #00d2ff;
            color: #031422;
          }

          /* Viewport & Map */
          .viewport {
            position: absolute;
            inset: 0;
            cursor: grab;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
          }

          .viewport.grabbing {
            cursor: grabbing !important;
          }

          .map-container {
            position: relative;
            width: 100%;
            height: 100%;
            transform-origin: center center;
            transition: transform 0.08s ease-out;
            will-change: transform;
          }

          .map-bg {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            pointer-events: none;
            filter: contrast(1.04) brightness(0.96);
          }

          .svg-layer {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
          }

          /* Interactive SVG Elements without any transform jitter */
          .sector-path {
            pointer-events: auto;
            cursor: pointer;
            transition: opacity 0.2s, fill 0.2s;
          }

          .sector-path:hover {
            opacity: 0.85 !important;
            filter: brightness(1.25) drop-shadow(0 0 10px rgba(0, 229, 255, 0.7));
          }

          .sector-arc {
            pointer-events: none;
            stroke-dasharray: 6 3;
            animation: dash-flow 25s linear infinite;
          }

          @keyframes dash-flow {
            to { stroke-dashoffset: -1000; }
          }

          /* Camera Marker (Stable SVG coordinate positioning, NO CSS transform scale!) */
          .cam-marker {
            pointer-events: auto;
            cursor: pointer;
          }

          :host(.shift-active) .cam-marker {
            cursor: move !important;
          }

          .cam-marker circle.marker-bg {
            transition: r 0.15s ease, stroke-width 0.15s ease, stroke 0.15s ease;
          }

          .cam-marker:hover circle.marker-bg {
            r: 18.5;
            stroke-width: 3.5;
          }

          .cam-marker.selected-cam circle.marker-bg {
            r: 20;
            stroke-width: 4;
            stroke: #f59e0b !important;
            filter: url(#glow-gold) !important;
          }

          /* Interactive Edit Handles for Selected Camera */
          .edit-handle {
            pointer-events: auto;
            cursor: pointer;
          }
          .edit-handle circle {
            transition: r 0.12s ease;
          }
          .edit-handle:hover circle {
            r: 14;
          }
          .handle-rotate {
            cursor: grab;
          }
          .handle-rotate:active { cursor: grabbing; }
          .handle-distance {
            cursor: ns-resize;
          }
          .handle-fov {
            cursor: ew-resize;
          }

          /* Building Filter Group Divider & Chips */
          .chip-divider {
            width: 1px;
            height: 18px;
            background: rgba(255, 255, 255, 0.18);
            margin: 0 4px;
            flex-shrink: 0;
          }

          .chip.chip-building.active {
            background: #38bdf8;
            color: #04101e;
            border-color: #38bdf8;
            font-weight: 600;
            box-shadow: 0 0 14px rgba(56, 189, 248, 0.5);
          }

          /* Floating Inspector / Property Panel (Режим настройки) */
          .inspector-panel {
            position: absolute;
            bottom: 20px;
            right: 20px;
            z-index: 35;
            width: 360px;
            max-width: calc(100% - 40px);
            max-height: calc(100% - 40px);
            overflow-y: auto;
            overflow-x: hidden;
            background: rgba(15, 20, 30, 0.96);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(245, 158, 11, 0.45);
            border-radius: 16px;
            padding: 14px 18px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.85), 0 0 20px rgba(245, 158, 11, 0.15);
            display: flex;
            flex-direction: column;
            gap: 12px;
            animation: panelSlideUp 0.2s cubic-bezier(0.16, 1, 0.3, 1);
          }

          .inspector-panel::-webkit-scrollbar {
            width: 5px;
          }
          .inspector-panel::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 4px;
          }
          .inspector-panel::-webkit-scrollbar-thumb {
            background: rgba(245, 158, 11, 0.3);
            border-radius: 4px;
          }
          .inspector-panel::-webkit-scrollbar-thumb:hover {
            background: rgba(245, 158, 11, 0.6);
          }

          /* Inspector Live Video Preview Box */
          .inspector-preview-box {
            position: relative;
            width: 100%;
            background: #000000;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.14);
            overflow: hidden;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.5), inset 0 0 10px rgba(0, 0, 0, 0.6);
          }

          .inspector-video-wrap {
            position: relative;
            width: 100%;
            aspect-ratio: 16 / 9;
            background: radial-gradient(circle at center, #1e293b 0%, #090d16 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            cursor: pointer;
          }

          .inspector-video-wrap:hover .btn-inspector-fs {
            background: #f59e0b;
            color: #000000;
            border-color: #f59e0b;
          }

          .inspector-video-img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            transition: transform 0.2s ease;
          }
          .inspector-video-wrap:hover .inspector-video-img {
            transform: scale(1.02);
          }

          .inspector-preview-badge {
            position: absolute;
            top: 7px;
            left: 7px;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            color: #10b981;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 5px;
            border: 1px solid rgba(16, 185, 129, 0.35);
            pointer-events: none;
            z-index: 2;
          }

          .inspector-angle-overlay {
            position: absolute;
            top: 7px;
            right: 7px;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            color: #fcd34d;
            display: flex;
            align-items: center;
            gap: 4px;
            border: 1px solid rgba(245, 158, 11, 0.35);
            pointer-events: none;
            z-index: 2;
          }

          .inspector-video-osd {
            position: absolute;
            bottom: 6px;
            left: 8px;
            right: 36px;
            font-size: 10px;
            color: rgba(255, 255, 255, 0.9);
            font-family: monospace;
            text-shadow: 0 1px 3px rgba(0, 0, 0, 0.95);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            pointer-events: none;
            z-index: 2;
          }

          .btn-inspector-fs {
            position: absolute;
            bottom: 5px;
            right: 6px;
            background: rgba(0, 0, 0, 0.65);
            border: 1px solid rgba(255, 255, 255, 0.25);
            color: #ffffff;
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.15s;
            z-index: 3;
          }

          .inspector-cam-meta {
            padding: 7px 10px;
            background: rgba(255, 255, 255, 0.04);
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            flex-direction: column;
            gap: 2px;
          }

          .inspector-cam-title {
            font-size: 12px;
            font-weight: 700;
            color: #ffffff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }

          .inspector-cam-entity {
            font-size: 10px;
            font-family: monospace;
            color: #94a3b8;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }

          @keyframes panelSlideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
          }

          .inspector-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding-bottom: 8px;
          }

          .inspector-title {
            font-size: 14px;
            font-weight: 700;
            color: #fcd34d;
            display: flex;
            align-items: center;
            gap: 6px;
          }

          .btn-del-cam {
            background: rgba(239, 68, 68, 0.18);
            border: 1px solid rgba(239, 68, 68, 0.4);
            color: #fca5a5;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11px;
            cursor: pointer;
            transition: all 0.15s;
          }
          .btn-del-cam:hover {
            background: #ef4444;
            color: #ffffff;
          }

          .inspector-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            font-size: 12px;
          }

          .inspector-row input[type="range"] {
            flex: 1;
            cursor: pointer;
            accent-color: #f59e0b;
          }

          .inspector-val {
            width: 48px;
            text-align: right;
            font-family: monospace;
            font-weight: 600;
            color: #fcd34d;
          }

          .quick-angles {
            display: flex;
            align-items: center;
            gap: 4px;
          }
          .btn-q-angle {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #e2e8f0;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            cursor: pointer;
          }
          .btn-q-angle:hover {
            background: #f59e0b;
            color: #000;
          }

          .inspector-select {
            width: 100%;
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #f8fafc;
            padding: 6px 10px;
            border-radius: 8px;
            font-size: 12px;
          }

          /* Floating Popup Modal (Окно камеры при обычном просмотре) */
          .cam-modal-backdrop {
            position: absolute;
            inset: 0;
            z-index: 100;
            background: rgba(0, 0, 0, 0.55);
            backdrop-filter: blur(6px);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
            animation: modalFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
          }

          @keyframes modalFadeIn {
            from { opacity: 0; transform: scale(0.96); }
            to { opacity: 1; transform: scale(1); }
          }

          .cam-modal-card {
            position: relative;
            width: 100%;
            max-width: 520px;
            background: #11141d;
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 18px;
            overflow: hidden;
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.9), 0 0 25px rgba(0, 210, 255, 0.12);
            display: flex;
            flex-direction: column;
          }

          .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            background: linear-gradient(180deg, #181d29 0%, #11141d 100%);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          }

          .modal-title-box {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
          }

          .modal-cam-name {
            font-size: 15px;
            font-weight: 600;
            color: #ffffff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }

          .modal-building-badge {
            background: rgba(0, 210, 255, 0.15);
            border: 1px solid rgba(0, 210, 255, 0.35);
            color: #38bdf8;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 5px;
            white-space: nowrap;
          }

          .modal-live-indicator {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: rgba(239, 68, 68, 0.18);
            border: 1px solid rgba(239, 68, 68, 0.4);
            color: #f87171;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
          }

          .live-red-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #ef4444;
            box-shadow: 0 0 6px #ef4444;
            animation: pulse-ring 1.2s infinite;
          }

          .btn-modal-close {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #94a3b8;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.15s;
          }

          .btn-modal-close:hover {
            background: rgba(239, 68, 68, 0.3);
            border-color: #ef4444;
            color: #ffffff;
          }

          .modal-video-wrapper {
            position: relative;
            width: 100%;
            aspect-ratio: 16/9;
            background: #000000;
            display: flex;
            align-items: center;
            justify-content: center;
          }

          .modal-video-img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            user-select: none;
          }

          .modal-video-osd {
            position: absolute;
            bottom: 8px;
            left: 10px;
            background: rgba(0, 0, 0, 0.65);
            padding: 2px 7px;
            border-radius: 4px;
            font-family: "Courier New", monospace;
            font-size: 10px;
            color: #22c55e;
            letter-spacing: 0.5px;
            pointer-events: none;
          }

          .btn-fullscreen {
            position: absolute;
            top: 8px;
            right: 8px;
            background: rgba(0, 0, 0, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: #ffffff;
            width: 26px;
            height: 26px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.15s;
          }

          .btn-fullscreen:hover {
            background: rgba(255, 255, 255, 0.3);
          }

          /* Modal Action Footer */
          .modal-footer {
            padding: 12px 16px;
            background: #11141d;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            flex-direction: column;
            gap: 10px;
          }

          .btn-open-gate {
            position: relative;
            width: 100%;
            background: linear-gradient(135deg, #059669 0%, #10b981 100%);
            border: 1px solid rgba(16, 185, 129, 0.6);
            color: #ffffff;
            padding: 10px 16px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4);
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            overflow: hidden;
          }

          .btn-open-gate:hover {
            background: linear-gradient(135deg, #10b981 0%, #34d399 100%);
            box-shadow: 0 6px 20px rgba(16, 185, 129, 0.6);
            transform: translateY(-1px);
          }

          .btn-open-gate:active { transform: translateY(1px); }

          .btn-open-gate.opening {
            background: #0284c7;
            border-color: #38bdf8;
            box-shadow: 0 0 18px rgba(56, 189, 248, 0.5);
            cursor: not-allowed;
          }

          .gate-progress-bar {
            position: absolute;
            bottom: 0;
            left: 0;
            height: 3px;
            background: #38bdf8;
            transition: width 1s linear;
          }

          .modal-gate-status {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 11px;
            color: #94a3b8;
            padding: 0 4px;
          }

          .status-val {
            color: #34d399;
            font-weight: 600;
          }

          /* Drawer: All Placed Cameras List */
          .drawer-cams {
            position: absolute;
            top: 65px;
            bottom: 20px;
            left: 20px;
            width: 330px;
            background: rgba(15, 23, 42, 0.96);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 16px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.8);
            z-index: 40;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            animation: drawerSlide 0.2s cubic-bezier(0.16, 1, 0.3, 1);
          }

          @keyframes drawerSlide {
            from { transform: translateX(-30px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
          }

          .drawer-header {
            padding: 12px 14px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            display: flex;
            align-items: center;
            justify-content: space-between;
          }
          .drawer-title { font-weight: 700; font-size: 13px; color: #f8fafc; }
          .drawer-search {
            padding: 8px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          }
          .drawer-search input {
            width: 100%;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #fff;
            padding: 6px 10px;
            border-radius: 8px;
            font-size: 12px;
            box-sizing: border-box;
          }
          .drawer-list {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
            display: flex;
            flex-direction: column;
            gap: 6px;
          }
          .drawer-item {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 8px 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            cursor: pointer;
            transition: all 0.15s;
          }
          .drawer-item:hover {
            background: rgba(0, 210, 255, 0.12);
            border-color: #00d2ff;
          }
          .drawer-item.selected {
            border-color: #f59e0b;
            background: rgba(245, 158, 11, 0.15);
          }

          /* Dialog: Add New Camera Modal */
          .add-dialog-backdrop {
            position: absolute;
            inset: 0;
            background: rgba(0,0,0,0.65);
            backdrop-filter: blur(8px);
            z-index: 110;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
          }
          .add-dialog {
            width: 100%;
            max-width: 540px;
            max-height: 80vh;
            background: #11141e;
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 18px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            box-shadow: 0 25px 60px rgba(0,0,0,0.9);
          }

          /* Toast message */
          .toast-msg {
            position: absolute;
            top: 75px;
            left: 50%;
            transform: translateX(-50%) translateY(-20px);
            background: rgba(16, 185, 129, 0.95);
            color: #ffffff;
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
            opacity: 0;
            pointer-events: none;
            transition: all 0.25s ease;
            z-index: 120;
          }

          .toast-msg.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
          }
        </style>

        <!-- Top Floating Control Bar -->
        <div class="toolbar">
          <div class="title-group">
            <span class="badge-cctv">
              <span class="pulse-dot"></span>
              ${this._editMode ? "Редактор камер" : "CCTV Online"}
            </span>
            <span class="app-title">${this._config.title || "Видеонаблюдение ЖК «Река»"}</span>
          </div>

          <!-- Edit Mode Instructions & Actions -->
          ${
            this._editMode
              ? `
            <div class="filter-chips">
              <span class="shift-badge ${this._isShiftPressed ? "active" : ""}" id="shift-badge">
                ${this._isShiftPressed ? "🟢 Shift активен: перетаскивайте камеру" : "⌨️ Зажмите Shift для перемещения"}
              </span>
              <button class="btn-tool btn-add-cam" id="btn-open-add-dialog">
                ➕ Добавить камеру
              </button>
              <button class="btn-tool ${this._showListDrawer ? "active" : ""}" id="btn-toggle-cams-drawer">
                📋 Список (${this._cameras.length})
              </button>
              <button class="btn-tool btn-save-cfg" id="btn-save-changes">
                💾 Сохранить изменения
              </button>
            </div>
          `
              : `
            <!-- View Mode Filters with Building Grouping -->
            <div class="filter-chips">
              <button class="chip ${this._activeFilter === "all" ? "active" : ""}" data-filter="all">
                🌐 Все (${this._cameras.length})
              </button>
              <button class="chip gate-chip ${this._activeFilter === "gate" ? "active" : ""}" data-filter="gate">
                🚪 Калитки (${gateCount})
              </button>
              <button class="chip ${this._activeFilter === "yard" ? "active" : ""}" data-filter="yard">
                🏡 Двор
              </button>
              <button class="chip ${this._activeFilter === "street" ? "active" : ""}" data-filter="street">
                🚗 Советская
              </button>
              <div class="chip-divider"></div>
              ${HOUSES.map((h) => {
                const count = this._cameras.filter((c) => c.building === h || (!c.building && c.name && c.name.includes(h))).length;
                return `
                <button class="chip chip-building ${this._activeFilter === h ? "active" : ""}" data-filter="${h}">
                  🏢 ${h} (${count})
                </button>
                `;
              }).join("")}
            </div>
          `
          }

          <!-- Right Action Controls -->
          <div class="tool-actions">
            <button class="btn-tool ${this._showSectors ? "active" : ""}" id="btn-toggle-sectors" title="Скрыть/показать конусы обзора">
              📐 Секторы
            </button>
            <button class="btn-tool btn-edit-mode" id="btn-toggle-edit-mode" title="Включить управление и перетаскивание камер">
              ${this._editMode ? "✓ Готово" : "⚙️ Управление"}
            </button>
            <button class="btn-tool" id="btn-zoom-in" title="Приблизить">+</button>
            <button class="btn-tool" id="btn-zoom-out" title="Отдалить">−</button>
            <button class="btn-tool" id="btn-zoom-reset" title="Сбросить масштаб">⟲</button>
          </div>
        </div>

        <!-- Toast -->
        <div class="toast-msg" id="toast"></div>

        <!-- Interactive Viewport -->
        <div class="viewport ${this._dragMode === "pan" ? "grabbing" : ""}" id="viewport">
          <div class="map-container" id="map-container" style="transform: translate(${this._panX}px, ${this._panY}px) scale(${this._zoomLevel});">
            <img class="map-bg" src="${this._config.map_image || "/local/cctv_plan.jpg"}" alt="План камер" />



            <!-- SVG FOV Sectors and Camera Markers Layer -->
            <svg class="svg-layer" id="svg-layer" viewBox="0 0 2112 2016" preserveAspectRatio="xMidYMid meet">
              <defs>
                <filter id="glow-cyan" x="-50%" y="-50%" width="200%" height="200%">
                  <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#00e5ff" flood-opacity="0.8"/>
                </filter>
                <filter id="glow-emerald" x="-50%" y="-50%" width="200%" height="200%">
                  <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#10b981" flood-opacity="0.8"/>
                </filter>
                <filter id="glow-purple" x="-50%" y="-50%" width="200%" height="200%">
                  <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#a855f7" flood-opacity="0.85"/>
                </filter>
                <filter id="glow-gold" x="-50%" y="-50%" width="200%" height="200%">
                  <feDropShadow dx="0" dy="0" stdDeviation="8" flood-color="#f59e0b" flood-opacity="0.95"/>
                </filter>

                <!-- Dynamic Gradients for Vision Cones -->
                ${filteredCams
                  .map((c, idx) => {
                    const cx = (c.x * 2112) / 100;
                    const cy = (c.y * 2016) / 100;
                    const r = ((c.distance || 14) * 2112) / 100;
                    const devType = c.device_type || (c.category === "gate" || c.gate_button ? "gate" : c.category === "intercom" ? "intercom" : "camera");
                    const isGate = devType === "gate";
                    const isIntercom = devType === "intercom";
                    const isSelected = this._editingCam?.id === c.id;
                    const color = isSelected ? "#f59e0b" : isGate ? "#10b981" : isIntercom ? "#a855f7" : "#00d2ff";
                    return `
                      <radialGradient id="sector-grad-${idx}" cx="${cx}" cy="${cy}" r="${r}" gradientUnits="userSpaceOnUse">
                        <stop offset="0%" stop-color="${color}" stop-opacity="${isSelected ? "0.65" : "0.55"}" />
                        <stop offset="35%" stop-color="${color}" stop-opacity="0.28" />
                        <stop offset="75%" stop-color="${color}" stop-opacity="0.08" />
                        <stop offset="100%" stop-color="${color}" stop-opacity="0.0" />
                      </radialGradient>
                    `;
                  })
                  .join("")}
              </defs>

              <!-- Vision Sectors (FOV Cones) -->
              ${
                this._showSectors
                  ? filteredCams
                      .map((c, idx) => {
                        const cx = (c.x * 2112) / 100;
                        const cy = (c.y * 2016) / 100;
                        const r = ((c.distance || 14) * 2112) / 100;
                        const pathD = this._getSectorPath(cx, cy, r, c.angle || 0, c.fov || 70);
                        const arcD = this._getSectorArc(cx, cy, r, c.angle || 0, c.fov || 70);
                        const devType = c.device_type || (c.category === "gate" || c.gate_button ? "gate" : c.category === "intercom" ? "intercom" : "camera");
                        const isGate = devType === "gate";
                        const isIntercom = devType === "intercom";
                        const isSelected = this._editingCam?.id === c.id;
                        const strokeColor = isSelected
                          ? "#f59e0b"
                          : isGate
                          ? "rgba(16, 185, 129, 0.85)"
                          : isIntercom
                          ? "rgba(168, 85, 247, 0.85)"
                          : "rgba(0, 210, 255, 0.85)";

                        return `
                        <g class="sector-group" data-cam-id="${c.id}">
                          <path class="sector-path"
                                d="${pathD}"
                                fill="url(#sector-grad-${idx})"
                                opacity="${isSelected ? "0.85" : "0.65"}" />
                          <path class="sector-arc"
                                d="${arcD}"
                                fill="none"
                                stroke="${strokeColor}"
                                stroke-width="${isSelected ? "3.5" : "2.5"}" />
                        </g>
                      `;
                      })
                      .join("")
                  : ""
              }

              <!-- Camera Markers Pin -->
              ${filteredCams
                .map((c) => {
                  const cx = (c.x * 2112) / 100;
                  const cy = (c.y * 2016) / 100;
                  const devType = c.device_type || (c.category === "gate" || c.gate_button ? "gate" : c.category === "intercom" ? "intercom" : "camera");
                  const isGate = devType === "gate";
                  const isIntercom = devType === "intercom";
                  const isSelected = this._editingCam?.id === c.id;
                  const strokeColor = isSelected ? "#f59e0b" : isGate ? "#10b981" : isIntercom ? "#a855f7" : "#00d2ff";
                  const filterId = isSelected ? "glow-gold" : isGate ? "glow-emerald" : isIntercom ? "glow-purple" : "glow-cyan";

                  return `
                    <g class="cam-marker ${isSelected ? "selected-cam" : ""}"
                       data-cam-id="${c.id}"
                       transform="translate(${cx}, ${cy})">
                      
                      <!-- Direction pointer (Lens direction) -->
                      <polygon class="cam-pointer"
                               points="0,-24 7,-12 -7,-12"
                               transform="rotate(${c.angle + 90})"
                               fill="${strokeColor}" />

                      <!-- Marker Background circle (NO CSS transform scale on parent!) -->
                      <circle class="marker-bg" r="16" fill="#0b1120" stroke="${strokeColor}" stroke-width="${isSelected ? "3.5" : "2.5"}" filter="url(#${filterId})" />

                      <!-- Camera / Gate / Intercom Icon -->
                      ${
                        isGate
                          ? `<path d="M -5,-7 L 5,-7 L 5,7 L -5,7 Z M 2,0 A 1,1 0 1,1 2,0.1" fill="none" stroke="${strokeColor}" stroke-width="1.8" />`
                          : isIntercom
                          ? `<path d="M -4,-5 C -5,-5 -6,-3 -5,-1 L -3,1 C -2,3 0,4 2,5 L 3,5 C 5,5 5,3 4,2 L 3,0 C 2.5,-0.2 1.8,-0.2 1.5,0.2 L 1,0.7 C 0.5,0.3 -0.3,-0.5 -0.7,-1 L -0.2,-1.5 C 0.2,-1.8 0.2,-2.5 0,-3 Z" fill="${strokeColor}" opacity="0.95" />`
                          : `<path d="M -7,4 A 8,8 0 0,1 7,4 Z M -4,-3 L 4,-3 L 6,1 L -6,1 Z" fill="${strokeColor}" opacity="0.9" />`
                      }

                      <!-- Live Green Dot -->
                      <circle cx="9" cy="-9" r="3.5" fill="#22c55e" stroke="#0b1120" stroke-width="1.2" />
                    </g>
                  `;
                })
                .join("")}

              <!-- Dedicated Edit Handles Layer for selected camera -->
              <g id="edit-handles-layer"></g>
            </svg>
          </div>
        </div>

        <!-- Floating Camera Property Inspector (in Edit Mode) -->
        <div id="inspector-container"></div>

        <!-- Drawer: Placed Cameras List -->
        ${
          this._showListDrawer
            ? `
          <div class="drawer-cams">
            <div class="drawer-header">
              <span class="drawer-title">📋 Камеры на карте (${this._cameras.length})</span>
              <button class="btn-modal-close" id="btn-close-drawer">✕</button>
            </div>
            <div class="drawer-search">
              <input type="text" placeholder="Поиск по названию..." id="drawer-search-input" value="${this._camSearchQuery}" />
            </div>
            <div class="drawer-list">
              ${this._cameras
                .filter((c) =>
                  this._camSearchQuery
                    ? c.name.toLowerCase().includes(this._camSearchQuery.toLowerCase()) ||
                      c.id.toLowerCase().includes(this._camSearchQuery.toLowerCase())
                    : true
                )
                .map(
                  (c) => `
                <div class="drawer-item ${this._editingCam?.id === c.id ? "selected" : ""}" data-cam-id="${c.id}">
                  <div style="min-width: 0; flex: 1;">
                    <div style="font-size: 12px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                      ${c.name}
                    </div>
                    <div style="font-size: 10px; color: #94a3b8;">
                      ${c.building} · X:${c.x.toFixed(0)}% Y:${c.y.toFixed(0)}% · ${c.angle}°
                    </div>
                  </div>
                  <button class="btn-tool" style="padding: 2px 6px; font-size: 10px;" data-focus-id="${c.id}" title="Показать на карте">🎯</button>
                </div>
              `
                )
                .join("")}
            </div>
          </div>
        `
            : ""
        }

        <!-- Dialog: Add New Camera Modal -->
        ${
          this._showAddDialog
            ? `
          <div class="add-dialog-backdrop" id="add-dialog-backdrop">
            <div class="add-dialog">
              <div class="modal-header">
                <span class="modal-cam-name">➕ Добавить камеру из Home Assistant</span>
                <button class="btn-modal-close" id="btn-close-add-dialog">✕</button>
              </div>
              <div style="padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.08);">
                <input type="text" placeholder="Поиск камеры (например: двор, калитка, советская)..."
                       id="add-search-input"
                       style="width: 100%; background: #1e293b; border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 8px 12px; border-radius: 8px; font-size: 13px; box-sizing: border-box;" />
              </div>
              <div style="flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px;" id="add-cam-list">
                ${this._getUnplacedCameras()
                  .map(
                    (cam) => `
                  <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; gap: 10px;">
                    <div style="min-width: 0;">
                      <div style="font-size: 13px; font-weight: 600; color: #fff;">${cam.name}</div>
                      <div style="font-size: 11px; color: #94a3b8; font-family: monospace;">${cam.id}</div>
                    </div>
                    <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
                      <button class="btn-tool btn-add-cam" data-add-entity="${cam.id}" data-add-type="camera" title="Добавить как обычную камеру" style="padding: 5px 9px; font-size: 11px;">
                        📹 Камера
                      </button>
                      <button class="btn-tool btn-add-cam" data-add-entity="${cam.id}" data-add-type="gate" title="Добавить как калитку" style="padding: 5px 9px; font-size: 11px; background: rgba(16, 185, 129, 0.2); border-color: rgba(16, 185, 129, 0.5); color: #6ee7b7;">
                        🚪 Калитка
                      </button>
                      <button class="btn-tool btn-add-cam" data-add-entity="${cam.id}" data-add-type="intercom" title="Добавить как домофон" style="padding: 5px 9px; font-size: 11px; background: rgba(168, 85, 247, 0.2); border-color: rgba(168, 85, 247, 0.5); color: #d8b4fe;">
                        📞 Домофон
                      </button>
                    </div>
                  </div>
                `
                  )
                  .join("")}
              </div>
            </div>
          </div>
        `
            : ""
        }

        <!-- Floating Popup Modal (Окно камеры при клике) -->
        ${
          this._viewCam
            ? `
          <div class="cam-modal-backdrop" id="modal-backdrop">
            <div class="cam-modal-card" id="modal-card">
              <div class="modal-header">
                <div class="modal-title-box">
                  <span class="modal-cam-name">${this._viewCam.name}</span>
                  <span class="modal-building-badge">${this._viewCam.building || "ЖК Река"}</span>
                  <span class="modal-live-indicator">
                    <span class="live-red-dot"></span> LIVE
                  </span>
                </div>
                <button class="btn-modal-close" id="btn-close-modal" title="Закрыть (Esc)">✕</button>
              </div>

              <div class="modal-video-wrapper">
                <img class="modal-video-img" id="modal-live-img" alt="${this._viewCam.name}" />
                <button class="btn-fullscreen" id="btn-modal-fs" title="На весь экран">⛶</button>
                <div class="modal-video-osd" id="modal-osd-time">
                  ${this._viewCam.id} · LIVE
                </div>
              </div>

              ${
                this._viewCam.gate_button || this._viewCam.device_type === "gate" || this._viewCam.device_type === "intercom" || this._viewCam.category === "gate" || (this._hass?.states[this._viewCam.id]?.attributes?.gate_id)
                  ? `
                <div class="modal-footer">
                  <button class="btn-open-gate ${this._isOpeningGate ? "opening" : ""}" id="btn-open-door">
                    <span>${this._isOpeningGate ? `⏳ Открывается... (${this._gateCountdown}с)` : (this._viewCam.device_type === "intercom" ? "📞 Открыть домофон / дверь" : "🚪 Открыть калитку / дверь")}</span>
                    ${
                      this._isOpeningGate
                        ? `<div class="gate-progress-bar" style="width: ${(this._gateCountdown / 5) * 100}%;"></div>`
                        : ""
                    }
                  </button>
                  <div class="modal-gate-status">
                    <span>Управление доступом: <b>${this._viewCam.device_type === "intercom" ? "Домофон" : "Калитка"}</b></span>
                    <span class="status-val">${this._isOpeningGate ? "Разблокировано" : "Готово к открытию"}</span>
                  </div>
                </div>
              `
                  : `
                <div class="modal-footer">
                  <div class="modal-gate-status" style="width: 100%; text-align: center;">
                    <span>Режим: <b>Прямой эфир (Круглосуточная охрана)</b></span>
                  </div>
                </div>
              `
              }
            </div>
          </div>
        `
            : ""
        }
      `;

      this._attachEventListeners();
      this._updateHandles();
      this._updateInspector();

      if (this._viewCam) {
        this._startLiveStream(this._viewCam.id);
      }
    }

    // ==========================================
    // HANDLES & INSPECTOR DOM UPDATERS (NO TEARDOWN)
    // ==========================================
    _updateHandles() {
      const handlesLayer = this.shadowRoot.getElementById("edit-handles-layer");
      if (!handlesLayer) return;

      if (!this._editMode || !this._editingCam) {
        handlesLayer.innerHTML = "";
        return;
      }

      const c = this._editingCam;
      const cx = (c.x * 2112) / 100;
      const cy = (c.y * 2016) / 100;
      const r = ((c.distance || 14) * 2112) / 100;
      const angleRad = (c.angle * Math.PI) / 180;
      const a1Rad = ((c.angle - c.fov / 2) * Math.PI) / 180;
      const a2Rad = ((c.angle + c.fov / 2) * Math.PI) / 180;

      const rotDist = r + 45;
      const rx = cx + rotDist * Math.cos(angleRad);
      const ry = cy + rotDist * Math.sin(angleRad);
      const dx = cx + r * Math.cos(angleRad);
      const dy = cy + r * Math.sin(angleRad);
      const fov1x = cx + r * Math.cos(a1Rad);
      const fov1y = cy + r * Math.sin(a1Rad);
      const fov2x = cx + r * Math.cos(a2Rad);
      const fov2y = cy + r * Math.sin(a2Rad);

      handlesLayer.innerHTML = `
        <!-- Dotted Guide Line to Rotation Handle -->
        <line x1="${cx}" y1="${cy}" x2="${rx}" y2="${ry}"
              stroke="#f59e0b" stroke-width="2.5" stroke-dasharray="5 5" opacity="0.9" />

        <!-- Rotation Handle -->
        <g class="edit-handle handle-rotate" id="handle-rotate" transform="translate(${rx}, ${ry})">
          <circle r="13" fill="#f59e0b" stroke="#ffffff" stroke-width="2.5" />
          <path d="M -4,-3 L 4,0 L -4,3 Z" fill="#000" />
        </g>

        <!-- Distance / Reach Handle -->
        <g class="edit-handle handle-distance" id="handle-dist" transform="translate(${dx}, ${dy})">
          <circle r="11" fill="#00e5ff" stroke="#ffffff" stroke-width="2.5" />
        </g>

        <!-- FOV Angle Handles -->
        <g class="edit-handle handle-fov" id="handle-fov-1" transform="translate(${fov1x}, ${fov1y})">
          <circle r="10" fill="#34d399" stroke="#ffffff" stroke-width="2.5" />
        </g>
        <g class="edit-handle handle-fov" id="handle-fov-2" transform="translate(${fov2x}, ${fov2y})">
          <circle r="10" fill="#34d399" stroke="#ffffff" stroke-width="2.5" />
        </g>
      `;

      // Attach handle listeners directly
      const hRot = handlesLayer.querySelector("#handle-rotate");
      const hDist = handlesLayer.querySelector("#handle-dist");
      const hFov1 = handlesLayer.querySelector("#handle-fov-1");
      const hFov2 = handlesLayer.querySelector("#handle-fov-2");

      if (hRot) {
        hRot.addEventListener("mousedown", (e) => {
          e.stopPropagation();
          e.preventDefault();
          this._dragMode = "rotate";
          this._dragCam = this._editingCam;
        });
      }
      if (hDist) {
        hDist.addEventListener("mousedown", (e) => {
          e.stopPropagation();
          e.preventDefault();
          this._dragMode = "dist";
          this._dragCam = this._editingCam;
        });
      }
      if (hFov1) {
        hFov1.addEventListener("mousedown", (e) => {
          e.stopPropagation();
          e.preventDefault();
          this._dragMode = "fov";
          this._dragCam = this._editingCam;
        });
      }
      if (hFov2) {
        hFov2.addEventListener("mousedown", (e) => {
          e.stopPropagation();
          e.preventDefault();
          this._dragMode = "fov";
          this._dragCam = this._editingCam;
        });
      }
    }

    _updateInspector() {
      const container = this.shadowRoot.getElementById("inspector-container");
      if (!container) return;

      if (!this._editMode || !this._editingCam) {
        container.innerHTML = "";
        this._stopInspectorLiveStream();
        return;
      }

      container.innerHTML = `
        <div class="inspector-panel" id="inspector-panel">
          <div class="inspector-header">
            <div class="inspector-title">
              <span>⚙️ Свойства камеры</span>
            </div>
            <button class="btn-del-cam" id="btn-delete-cam" title="Удалить камеру с карты">🗑 Удалить</button>
          </div>

          <!-- Live Camera Preview Box -->
          <div class="inspector-preview-box">
            <div class="inspector-video-wrap" id="inspector-preview-click" title="Нажмите, чтобы открыть камеру в окне">
              <img class="inspector-video-img" id="inspector-live-img" alt="${this._editingCam.name}" />
              <div class="inspector-preview-badge">
                <span class="live-red-dot"></span> LIVE
              </div>
              <div class="inspector-angle-overlay" id="inspector-angle-badge" title="Угол направления камеры">
                🧭 ${this._editingCam.angle}°
              </div>
              <div class="inspector-video-osd" id="inspector-osd-time">
                ${this._editingCam.id} · Загрузка...
              </div>
              <button class="btn-inspector-fs" id="btn-inspector-fs" title="Развернуть видео">⛶</button>
            </div>
            <div class="inspector-cam-meta">
              <span class="inspector-cam-title">${this._editingCam.name}</span>
              <span class="inspector-cam-entity">${this._editingCam.id}</span>
            </div>
          </div>

          <div class="inspector-row">
            <span>Положение X:</span>
            <input type="range" min="0" max="100" step="0.2" value="${this._editingCam.x}" id="slider-x" />
            <span class="inspector-val" id="val-x">${this._editingCam.x.toFixed(1)}%</span>
          </div>
          <div class="inspector-row">
            <span>Положение Y:</span>
            <input type="range" min="0" max="100" step="0.2" value="${this._editingCam.y}" id="slider-y" />
            <span class="inspector-val" id="val-y">${this._editingCam.y.toFixed(1)}%</span>
          </div>

          <div class="inspector-row">
            <span>Поворот:</span>
            <input type="range" min="0" max="360" step="1" value="${this._editingCam.angle}" id="slider-angle" />
            <span class="inspector-val" id="val-angle">${this._editingCam.angle}°</span>
          </div>
          <div class="quick-angles">
            <span style="font-size: 10px; color: #94a3b8;">Быстрый угол:</span>
            <button class="btn-q-angle" data-a="0">0° (Вправо)</button>
            <button class="btn-q-angle" data-a="90">90° (Вниз)</button>
            <button class="btn-q-angle" data-a="180">180° (Влево)</button>
            <button class="btn-q-angle" data-a="270">270° (Вверх)</button>
          </div>

          <div class="inspector-row">
            <span>Длина сектора:</span>
            <input type="range" min="6" max="35" step="0.5" value="${this._editingCam.distance}" id="slider-dist" />
            <span class="inspector-val" id="val-dist">${this._editingCam.distance}%</span>
          </div>

          <div class="inspector-row">
            <span>Ширина обзора (FOV):</span>
            <input type="range" min="30" max="130" step="2" value="${this._editingCam.fov}" id="slider-fov" />
            <span class="inspector-val" id="val-fov">${this._editingCam.fov}°</span>
          </div>

          <div>
            <span style="font-size: 11px; color: #94a3b8; display: block; margin-bottom: 4px;">Тип устройства на карте:</span>
            <select class="inspector-select" id="select-cam-type">
              <option value="camera" ${(this._editingCam.device_type || (this._editingCam.category === "gate" || this._editingCam.gate_button ? "gate" : this._editingCam.category === "intercom" ? "intercom" : "camera")) === "camera" ? "selected" : ""}>📹 Обычная камера</option>
              <option value="gate" ${(this._editingCam.device_type || (this._editingCam.category === "gate" || this._editingCam.gate_button ? "gate" : this._editingCam.category === "intercom" ? "intercom" : "camera")) === "gate" ? "selected" : ""}>🚪 Калитка (Вход)</option>
              <option value="intercom" ${(this._editingCam.device_type || (this._editingCam.category === "gate" || this._editingCam.gate_button ? "gate" : this._editingCam.category === "intercom" ? "intercom" : "camera")) === "intercom" ? "selected" : ""}>📞 Домофон / Интерком</option>
            </select>
          </div>

          <div>
            <span style="font-size: 11px; color: #94a3b8; display: block; margin-bottom: 4px;">Здание / Зона:</span>
            <select class="inspector-select" id="select-building">
              <option value="Советская" ${this._editingCam.building === "Советская" ? "selected" : ""}>ул. Советская</option>
              <option value="Дом 4" ${this._editingCam.building === "Дом 4" ? "selected" : ""}>Дом 4</option>
              <option value="Дом 2" ${this._editingCam.building === "Дом 2" ? "selected" : ""}>Дом 2</option>
              <option value="Дом 24" ${this._editingCam.building === "Дом 24" ? "selected" : ""}>Дом 24</option>
              <option value="Дом 26" ${this._editingCam.building === "Дом 26" ? "selected" : ""}>Дом 26</option>
              <option value="Дом 28" ${this._editingCam.building === "Дом 28" ? "selected" : ""}>Дом 28</option>
              <option value="28 к 1" ${this._editingCam.building === "28 к 1" ? "selected" : ""}>28 к 1</option>
              <option value="Дом 4 к2" ${this._editingCam.building === "Дом 4 к2" ? "selected" : ""}>Дом 4 к2</option>
              <option value="Дом 4 к1" ${this._editingCam.building === "Дом 4 к1" ? "selected" : ""}>Дом 4 к1</option>
              <option value="Двор" ${this._editingCam.building === "Двор" ? "selected" : ""}>Двор / Детская площадка</option>
            </select>
          </div>

          <div>
            <span style="font-size: 11px; color: #94a3b8; display: block; margin-bottom: 4px;">Привязанная кнопка калитки/двери:</span>
            <select class="inspector-select" id="select-gate-btn">
              <option value="">(Нет калитки / обычная камера)</option>
              ${this._getAvailableGateButtons()
                .map(
                  (btn) => `
                <option value="${btn.id}" ${this._editingCam.gate_button === btn.id ? "selected" : ""}>
                  ${btn.name} (${btn.id})
                </option>
              `
                )
                .join("")}
            </select>
          </div>
        </div>
      `;

      // Click on preview box or FS button to open full popup
      const previewClick = container.querySelector("#inspector-preview-click");
      const btnFs = container.querySelector("#btn-inspector-fs");
      const openModalHandler = (e) => {
        e.stopPropagation();
        if (this._editingCam) {
          this._openViewModal(this._editingCam);
        }
      };
      if (previewClick) previewClick.addEventListener("click", openModalHandler);
      if (btnFs) btnFs.addEventListener("click", openModalHandler);

      // Bind inspector sliders
      this._bindInspectorInput("slider-x", "val-x", "x", "%", (v) => Math.min(Math.max(0, v), 100));
      this._bindInspectorInput("slider-y", "val-y", "y", "%", (v) => Math.min(Math.max(0, v), 100));
      this._bindInspectorInput("slider-angle", "val-angle", "angle", "°", (v) => {
        const a = (v % 360 + 360) % 360;
        const badge = container.querySelector("#inspector-angle-badge");
        if (badge) badge.textContent = `🧭 ${a}°`;
        return a;
      });
      this._bindInspectorInput("slider-dist", "val-dist", "distance", "%", (v) => Math.min(Math.max(5, v), 35));
      this._bindInspectorInput("slider-fov", "val-fov", "fov", "°", (v) => Math.min(Math.max(30, v), 130));

      container.querySelectorAll(".btn-q-angle").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const angle = parseInt(e.currentTarget.dataset.a, 10);
          this._editingCam.angle = angle;
          this._updateSvgOnly();
          const valAngle = container.querySelector("#val-angle");
          const sliderAngle = container.querySelector("#slider-angle");
          const badge = container.querySelector("#inspector-angle-badge");
          if (valAngle) valAngle.textContent = `${angle}°`;
          if (sliderAngle) sliderAngle.value = angle;
          if (badge) badge.textContent = `🧭 ${angle}°`;
        });
      });

      const selectBuilding = container.querySelector("#select-building");
      if (selectBuilding) {
        selectBuilding.addEventListener("change", (e) => {
          this._editingCam.building = e.target.value;
        });
      }

      const selectCamType = container.querySelector("#select-cam-type");
      if (selectCamType) {
        selectCamType.addEventListener("change", (e) => {
          const val = e.target.value;
          this._editingCam.device_type = val;
          if (val === "gate") {
            this._editingCam.category = "gate";
          } else if (val === "intercom") {
            this._editingCam.category = "intercom";
          } else {
            if (this._editingCam.category === "gate" || this._editingCam.category === "intercom") {
              this._editingCam.category = "yard";
            }
          }
          this._updateSvgOnly();
        });
      }

      const selectGate = container.querySelector("#select-gate-btn");
      if (selectGate) {
        selectGate.addEventListener("change", (e) => {
          this._editingCam.gate_button = e.target.value || null;
          if (e.target.value && (!this._editingCam.device_type || this._editingCam.device_type === "camera")) {
            this._editingCam.device_type = "gate";
            this._editingCam.category = "gate";
            const typeSel = container.querySelector("#select-cam-type");
            if (typeSel) typeSel.value = "gate";
          }
          this._updateSvgOnly();
        });
      }

      const btnDelete = container.querySelector("#btn-delete-cam");
      if (btnDelete) {
        btnDelete.addEventListener("click", () => {
          if (confirm(`Удалить камеру "${this._editingCam.name}" с карты?`)) {
            this._stopInspectorLiveStream();
            this._cameras = this._cameras.filter((c) => c.id !== this._editingCam.id);
            this._editingCam = null;
            this._showToast("Камера удалена с карты");
            this._render();
          }
        });
      }

      // Start live stream for inspector preview
      this._startInspectorLiveStream(this._editingCam.id);
    }

    _updateShiftUI() {
      const badge = this.shadowRoot.getElementById("shift-badge");
      if (this._isShiftPressed) {
        this.classList.add("shift-active");
        if (badge) {
          badge.classList.add("active");
          badge.innerHTML = "🟢 Shift активен: перетаскивайте камеру";
        }
      } else {
        this.classList.remove("shift-active");
        if (badge) {
          badge.classList.remove("active");
          badge.innerHTML = "⌨️ Зажмите Shift для перемещения";
        }
      }
    }

    // ==========================================
    // EVENT LISTENERS & INTERACTION
    // ==========================================
    _attachEventListeners() {
      // 1. Filter Chips (toggle on re-click)
      this.shadowRoot.querySelectorAll(".chip").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const filter = e.currentTarget.dataset.filter;
          this._activeFilter = this._activeFilter === filter ? "all" : filter;
          this._render();
        });
      });

      // 3. Toggle Sectors
      const btnToggleSectors = this.shadowRoot.getElementById("btn-toggle-sectors");
      if (btnToggleSectors) {
        btnToggleSectors.addEventListener("click", () => {
          this._showSectors = !this._showSectors;
          this._render();
        });
      }

      // 4. Toggle Edit Mode
      const btnEditMode = this.shadowRoot.getElementById("btn-toggle-edit-mode");
      if (btnEditMode) {
        btnEditMode.addEventListener("click", () => {
          this._editMode = !this._editMode;
          this._viewCam = null;
          this._stopLiveStream();
          this._stopInspectorLiveStream();
          if (!this._editMode) {
            this._editingCam = null;
          }
          this._showToast(
            this._editMode
              ? "⚙️ Режим управления: для перемещения камеры зажмите левый Shift и тащите мышью"
              : "Режим просмотра активирован"
          );
          this._render();
        });
      }

      // 5. Save Changes to Home Assistant
      const btnSave = this.shadowRoot.getElementById("btn-save-changes");
      if (btnSave) {
        btnSave.addEventListener("click", () => this._saveDashboardConfig());
      }

      // 6. Add Camera Dialog
      const btnOpenAdd = this.shadowRoot.getElementById("btn-open-add-dialog");
      if (btnOpenAdd) {
        btnOpenAdd.addEventListener("click", () => {
          this._showAddDialog = true;
          this._render();
        });
      }
      const btnCloseAdd = this.shadowRoot.getElementById("btn-close-add-dialog");
      const addBackdrop = this.shadowRoot.getElementById("add-dialog-backdrop");
      if (btnCloseAdd) {
        btnCloseAdd.addEventListener("click", () => {
          this._showAddDialog = false;
          this._render();
        });
      }
      if (addBackdrop) {
        addBackdrop.addEventListener("click", (e) => {
          if (e.target === addBackdrop) {
            this._showAddDialog = false;
            this._render();
          }
        });
      }

      this.shadowRoot.querySelectorAll("[data-add-entity]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const entityId = e.currentTarget.dataset.addEntity;
          const chosenType = e.currentTarget.dataset.addType || "camera";
          this._handleAddCameraToMap(entityId, chosenType);
        });
      });

      // 7. Placed Cameras Drawer Toggle
      const btnToggleDrawer = this.shadowRoot.getElementById("btn-toggle-cams-drawer");
      if (btnToggleDrawer) {
        btnToggleDrawer.addEventListener("click", () => {
          this._showListDrawer = !this._showListDrawer;
          this._render();
        });
      }
      const btnCloseDrawer = this.shadowRoot.getElementById("btn-close-drawer");
      if (btnCloseDrawer) {
        btnCloseDrawer.addEventListener("click", () => {
          this._showListDrawer = false;
          this._render();
        });
      }
      const drawerSearch = this.shadowRoot.getElementById("drawer-search-input");
      if (drawerSearch) {
        drawerSearch.addEventListener("input", (e) => {
          this._camSearchQuery = e.target.value;
          this._render();
        });
      }
      this.shadowRoot.querySelectorAll(".drawer-item").forEach((item) => {
        item.addEventListener("click", (e) => {
          const camId = item.dataset.camId;
          const cam = this._cameras.find((c) => c.id === camId);
          if (cam) {
            this._selectCameraForEditing(cam);
          }
        });
      });

      // 8. Zoom & Pan
      const btnIn = this.shadowRoot.getElementById("btn-zoom-in");
      const btnOut = this.shadowRoot.getElementById("btn-zoom-out");
      const btnReset = this.shadowRoot.getElementById("btn-zoom-reset");
      if (btnIn) btnIn.addEventListener("click", () => this._zoom(0.25));
      if (btnOut) btnOut.addEventListener("click", () => this._zoom(-0.25));
      if (btnReset) btnReset.addEventListener("click", () => this._resetZoom());

      const vp = this.shadowRoot.getElementById("viewport");
      if (vp) {
        vp.addEventListener("mousedown", (e) => this._onMouseDownViewport(e));
        vp.addEventListener("wheel", (e) => {
          e.preventDefault();
          this._zoom(e.deltaY < 0 ? 0.15 : -0.15);
        });
      }

      // 9. Camera Marker Click & Drag (STRICT SHIFT REQUIREMENT FOR DRAG)
      this.shadowRoot.querySelectorAll(".cam-marker").forEach((el) => {
        const camId = el.dataset.camId;
        const cam = this._cameras.find((c) => c.id === camId);
        if (!cam) return;

        el.addEventListener("mousedown", (e) => {
          if (this._editMode) {
            e.stopPropagation();

            // ONLY drag if Shift is held down!
            if (e.shiftKey) {
              e.preventDefault();
              this._dragMode = "cam-pos";
              this._dragCam = cam;
              this._selectCameraForEditing(cam);
            } else {
              // Click without Shift just selects the camera for property editing
              this._selectCameraForEditing(cam);
            }
          }
        });

        el.addEventListener("click", (e) => {
          e.stopPropagation();
          if (!this._editMode) {
            this._openViewModal(cam);
          }
        });
      });

      // Sector clicks
      this.shadowRoot.querySelectorAll(".sector-group").forEach((el) => {
        const camId = el.dataset.camId;
        const cam = this._cameras.find((c) => c.id === camId);
        if (!cam) return;
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          if (this._editMode) {
            this._selectCameraForEditing(cam);
          } else {
            this._openViewModal(cam);
          }
        });
      });

      // 10. Modal View Mode Controls
      const modalBackdrop = this.shadowRoot.getElementById("modal-backdrop");
      if (modalBackdrop) {
        modalBackdrop.addEventListener("click", (e) => {
          if (e.target === modalBackdrop) this._closeViewModal();
        });
      }
      const btnCloseModal = this.shadowRoot.getElementById("btn-close-modal");
      if (btnCloseModal) {
        btnCloseModal.addEventListener("click", () => this._closeViewModal());
      }
      const btnFs = this.shadowRoot.getElementById("btn-modal-fs");
      if (btnFs) {
        btnFs.addEventListener("click", () => {
          const wrapper = this.shadowRoot.querySelector(".modal-video-wrapper");
          if (wrapper) {
            if (!document.fullscreenElement) wrapper.requestFullscreen().catch(() => {});
            else document.exitFullscreen().catch(() => {});
          }
        });
      }
      const btnGate = this.shadowRoot.getElementById("btn-open-door");
      if (btnGate) {
        btnGate.addEventListener("click", () => this._handleGateOpen());
      }

      this._addGlobalListeners();
    }

    _selectCameraForEditing(cam) {
      this._editingCam = cam;
      // Update selected class on SVG markers without full re-render
      this.shadowRoot.querySelectorAll(".cam-marker").forEach((m) => {
        m.classList.toggle("selected-cam", m.dataset.camId === cam.id);
      });
      this._updateHandles();
      this._updateInspector();
    }

    _bindInspectorInput(sliderId, valId, prop, suffix, validator) {
      const slider = this.shadowRoot.getElementById(sliderId);
      const valEl = this.shadowRoot.getElementById(valId);
      if (slider && valEl) {
        slider.addEventListener("input", (e) => {
          let num = parseFloat(e.target.value);
          if (validator) num = validator(num);
          this._editingCam[prop] = num;
          valEl.textContent = `${num.toFixed(prop === "x" || prop === "y" ? 1 : 0)}${suffix}`;
          this._updateSvgOnly();
        });
      }
    }

    // ==========================================
    // MOUSE & TOUCH DRAG DISPATCHER
    // ==========================================
    _onMouseDownViewport(e) {
      if (e.button !== 0) return;
      // If clicking on empty canvas, pan the viewport
      if (!this._dragMode && !e.shiftKey) {
        this._dragMode = "pan";
        this._dragStartX = e.clientX - this._panX;
        this._dragStartY = e.clientY - this._panY;
        const vp = this.shadowRoot.getElementById("viewport");
        if (vp) vp.classList.add("grabbing");
      }
    }

    _addGlobalListeners() {
      this._removeGlobalListeners();

      this._boundMouseMove = (e) => this._onGlobalMouseMove(e);
      this._boundMouseUp = () => this._onGlobalMouseUp();
      this._boundKeyDown = (e) => {
        if (e.key === "Shift" && !this._isShiftPressed) {
          this._isShiftPressed = true;
          this._updateShiftUI();
        }
      };
      this._boundKeyUp = (e) => {
        if (e.key === "Shift") {
          this._isShiftPressed = false;
          this._updateShiftUI();
        }
      };

      window.addEventListener("mousemove", this._boundMouseMove);
      window.addEventListener("mouseup", this._boundMouseUp);
      window.addEventListener("keydown", this._boundKeyDown);
      window.addEventListener("keyup", this._boundKeyUp);
    }

    _removeGlobalListeners() {
      if (this._boundMouseMove) window.removeEventListener("mousemove", this._boundMouseMove);
      if (this._boundMouseUp) window.removeEventListener("mouseup", this._boundMouseUp);
      if (this._boundKeyDown) window.removeEventListener("keydown", this._boundKeyDown);
      if (this._boundKeyUp) window.removeEventListener("keyup", this._boundKeyUp);
    }

    _onGlobalMouseMove(e) {
      if (!this._dragMode) return;

      if (this._dragMode === "pan") {
        this._panX = e.clientX - this._dragStartX;
        this._panY = e.clientY - this._dragStartY;
        this._updateTransform();
        return;
      }

      // SVG coordinate projection using getScreenCTM()
      const svg = this.shadowRoot.getElementById("svg-layer");
      if (!svg || !this._dragCam) return;
      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());

      const cx = (this._dragCam.x * 2112) / 100;
      const cy = (this._dragCam.y * 2016) / 100;

      if (this._dragMode === "cam-pos") {
        // Drag-and-drop camera position on map (Shift was pressed on mousedown)
        const percentX = Math.min(Math.max(0.5, (svgP.x / 2112) * 100), 99.5);
        const percentY = Math.min(Math.max(0.5, (svgP.y / 2016) * 100), 99.5);
        this._dragCam.x = Math.round(percentX * 10) / 10;
        this._dragCam.y = Math.round(percentY * 10) / 10;

        const valX = this.shadowRoot.getElementById("val-x");
        const valY = this.shadowRoot.getElementById("val-y");
        const sliderX = this.shadowRoot.getElementById("slider-x");
        const sliderY = this.shadowRoot.getElementById("slider-y");
        if (valX) valX.textContent = `${this._dragCam.x.toFixed(1)}%`;
        if (valY) valY.textContent = `${this._dragCam.y.toFixed(1)}%`;
        if (sliderX) sliderX.value = this._dragCam.x;
        if (sliderY) sliderY.value = this._dragCam.y;

        this._updateSvgOnly();
      } else if (this._dragMode === "rotate") {
        // Drag rotation handle around camera
        const angleRad = Math.atan2(svgP.y - cy, svgP.x - cx);
        let angleDeg = Math.round((angleRad * 180) / Math.PI);
        if (angleDeg < 0) angleDeg += 360;
        this._dragCam.angle = angleDeg;

        const valAngle = this.shadowRoot.getElementById("val-angle");
        const sliderAngle = this.shadowRoot.getElementById("slider-angle");
        const badge = this.shadowRoot.getElementById("inspector-angle-badge");
        if (valAngle) valAngle.textContent = `${angleDeg}°`;
        if (sliderAngle) sliderAngle.value = angleDeg;
        if (badge) badge.textContent = `🧭 ${angleDeg}°`;

        this._updateSvgOnly();
      } else if (this._dragMode === "dist") {
        // Drag distance handle to change reach
        const distPx = Math.hypot(svgP.x - cx, svgP.y - cy);
        const distPercent = Math.min(Math.max(6, (distPx / 2112) * 100), 35);
        this._dragCam.distance = Math.round(distPercent * 10) / 10;

        const valDist = this.shadowRoot.getElementById("val-dist");
        const sliderDist = this.shadowRoot.getElementById("slider-dist");
        if (valDist) valDist.textContent = `${this._dragCam.distance}%`;
        if (sliderDist) sliderDist.value = this._dragCam.distance;

        this._updateSvgOnly();
      } else if (this._dragMode === "fov") {
        // Drag FOV handles to adjust cone angle
        const handleAngleRad = Math.atan2(svgP.y - cy, svgP.x - cx);
        let diff = Math.abs((handleAngleRad * 180) / Math.PI - this._dragCam.angle);
        if (diff > 180) diff = 360 - diff;
        const newFov = Math.min(Math.max(30, Math.round(diff * 2)), 130);
        this._dragCam.fov = newFov;

        const valFov = this.shadowRoot.getElementById("val-fov");
        const sliderFov = this.shadowRoot.getElementById("slider-fov");
        if (valFov) valFov.textContent = `${newFov}°`;
        if (sliderFov) sliderFov.value = newFov;

        this._updateSvgOnly();
      }
    }

    _onGlobalMouseUp() {
      if (this._dragMode) {
        const vp = this.shadowRoot.getElementById("viewport");
        if (vp) vp.classList.remove("grabbing");
        this._dragMode = null;
        this._dragCam = null;

        // Auto-save progress to local cache
        try {
          localStorage.setItem("cctv_map_cameras_v1", JSON.stringify(this._cameras));
        } catch (e) {}
      }
    }

    // ==========================================
    // FAST SVG ONLY LIVE UPDATE (60 FPS)
    // ==========================================
    _updateSvgOnly() {
      const svg = this.shadowRoot.getElementById("svg-layer");
      if (!svg) return;
      const filteredCams = this._filterCameras();

      // Update vision sectors
      svg.querySelectorAll(".sector-group").forEach((g) => {
        const camId = g.dataset.camId;
        const cam = filteredCams.find((c) => c.id === camId);
        if (!cam) return;
        const cx = (cam.x * 2112) / 100;
        const cy = (cam.y * 2016) / 100;
        const r = ((cam.distance || 14) * 2112) / 100;
        const path = g.querySelector(".sector-path");
        const arc = g.querySelector(".sector-arc");
        if (path) path.setAttribute("d", this._getSectorPath(cx, cy, r, cam.angle || 0, cam.fov || 70));
        if (arc) arc.setAttribute("d", this._getSectorArc(cx, cy, r, cam.angle || 0, cam.fov || 70));
      });

      // Update camera markers
      svg.querySelectorAll(".cam-marker").forEach((m) => {
        const camId = m.dataset.camId;
        const cam = filteredCams.find((c) => c.id === camId);
        if (!cam) return;
        const cx = (cam.x * 2112) / 100;
        const cy = (cam.y * 2016) / 100;
        m.setAttribute("transform", `translate(${cx}, ${cy})`);
        const pointer = m.querySelector(".cam-pointer");
        if (pointer) pointer.setAttribute("transform", `rotate(${cam.angle + 90})`);
      });

      // Update Edit Handles for selected camera
      if (this._editMode && this._editingCam) {
        const c = this._editingCam;
        const cx = (c.x * 2112) / 100;
        const cy = (c.y * 2016) / 100;
        const r = ((c.distance || 14) * 2112) / 100;
        const angleRad = (c.angle * Math.PI) / 180;
        const a1Rad = ((c.angle - c.fov / 2) * Math.PI) / 180;
        const a2Rad = ((c.angle + c.fov / 2) * Math.PI) / 180;

        const rotDist = r + 45;
        const rx = cx + rotDist * Math.cos(angleRad);
        const ry = cy + rotDist * Math.sin(angleRad);
        const dx = cx + r * Math.cos(angleRad);
        const dy = cy + r * Math.sin(angleRad);
        const fov1x = cx + r * Math.cos(a1Rad);
        const fov1y = cy + r * Math.sin(a1Rad);
        const fov2x = cx + r * Math.cos(a2Rad);
        const fov2y = cy + r * Math.sin(a2Rad);

        const hRot = svg.getElementById("handle-rotate");
        const hDist = svg.getElementById("handle-dist");
        const hFov1 = svg.getElementById("handle-fov-1");
        const hFov2 = svg.getElementById("handle-fov-2");
        const guide = svg.querySelector("line");

        if (hRot) hRot.setAttribute("transform", `translate(${rx}, ${ry})`);
        if (hDist) hDist.setAttribute("transform", `translate(${dx}, ${dy})`);
        if (hFov1) hFov1.setAttribute("transform", `translate(${fov1x}, ${fov1y})`);
        if (hFov2) hFov2.setAttribute("transform", `translate(${fov2x}, ${fov2y})`);
        if (guide) {
          guide.setAttribute("x1", cx);
          guide.setAttribute("y1", cy);
          guide.setAttribute("x2", rx);
          guide.setAttribute("y2", ry);
        }
      }
    }

    _zoom(delta) {
      this._zoomLevel = Math.min(Math.max(0.7, this._zoomLevel + delta), 3.5);
      this._updateTransform();
    }

    _resetZoom() {
      this._zoomLevel = 1.0;
      this._panX = 0;
      this._panY = 0;
      this._updateTransform();
    }

    _updateTransform() {
      const container = this.shadowRoot.getElementById("map-container");
      if (container) {
        container.style.transform = `translate(${this._panX}px, ${this._panY}px) scale(${this._zoomLevel})`;
      }
    }

    // ==========================================
    // ADD CAMERA LOGIC
    // ==========================================
    _getUnplacedCameras() {
      if (!this._hass) return [];
      const placedIds = new Set(this._cameras.map((c) => c.id));
      const cams = [];
      for (const eid of Object.keys(this._hass.states)) {
        if (eid.startsWith("camera.")) {
          const s = this._hass.states[eid];
          cams.push({
            id: eid,
            name: s?.attributes?.friendly_name || eid.replace("camera.", ""),
            isPlaced: placedIds.has(eid),
          });
        }
      }
      return cams.sort((a, b) => a.name.localeCompare(b.name, "ru"));
    }

    _getAvailableGateButtons() {
      if (!this._hass) return [];
      const btns = [];
      for (const eid of Object.keys(this._hass.states)) {
        if (eid.startsWith("button.")) {
          const s = this._hass.states[eid];
          btns.push({
            id: eid,
            name: s?.attributes?.friendly_name || eid,
          });
        }
      }
      return btns.sort((a, b) => a.name.localeCompare(b.name, "ru"));
    }

    _handleAddCameraToMap(entityId, chosenType = "camera") {
      const stateObj = this._hass?.states[entityId];
      const friendlyName = stateObj?.attributes?.friendly_name || entityId.replace("camera.", "");

      // Check if there is an automatic gate button match
      let linkedBtn = null;
      for (const btnId of Object.keys(this._hass?.states || {})) {
        if (btnId.startsWith("button.otkryt_")) {
          const btnNum = btnId.match(/\d+/)?.[0];
          const camNum = entityId.match(/\d+/)?.[0];
          if (btnNum && camNum && btnNum === camNum) {
            linkedBtn = btnId;
            break;
          }
        }
      }

      let devType = chosenType;
      if (!devType || devType === "camera") {
        if (linkedBtn || entityId.includes("kalitka") || friendlyName.toLowerCase().includes("калитк")) {
          devType = "gate";
        } else if (entityId.includes("paradnaia") || entityId.includes("podezd") || entityId.includes("domofon") || friendlyName.toLowerCase().includes("парадн") || friendlyName.toLowerCase().includes("подъезд")) {
          devType = "intercom";
        }
      }

      const newCam = {
        id: entityId,
        name: friendlyName,
        building: "Двор",
        category: devType === "gate" ? "gate" : devType === "intercom" ? "intercom" : "yard",
        device_type: devType,
        x: 50.0,
        y: 50.0,
        angle: 90,
        fov: 70,
        distance: 14,
        gate_button: linkedBtn,
      };

      this._cameras.push(newCam);
      this._editingCam = newCam;
      this._showAddDialog = false;
      const typeLabel = devType === "gate" ? "Калитка" : devType === "intercom" ? "Домофон" : "Камера";
      this._showToast(`${typeLabel} "${friendlyName}" добавлена на карту. Зажмите Shift и перетащите её!`);
      this._render();
    }

    // ==========================================
    // PERSISTENCE (SAVE TO HOME ASSISTANT)
    // ==========================================
    async _saveDashboardConfig() {
      try {
        localStorage.setItem("cctv_map_cameras_v1", JSON.stringify(this._cameras));

        const pathSegments = window.location.pathname.split("/").filter(Boolean);
        let urlPath = pathSegments[0] || "dashboard-testovaia";
        if (urlPath === "lovelace") urlPath = null;

        const callWS = (msg) => {
          if (this._hass && this._hass.callWS) {
            return this._hass.callWS(msg);
          }
          if (this._hass && this._hass.connection && this._hass.connection.sendMessagePromise) {
            return this._hass.connection.sendMessagePromise(msg);
          }
          return Promise.reject(new Error("No WebSocket connection available"));
        };

        if (this._hass) {
          let dash = null;
          let activeUrlPath = urlPath;
          try {
            dash = await callWS({
              type: "lovelace/config",
              url_path: activeUrlPath,
            });
          } catch (e) {
            if (activeUrlPath !== null) {
              try {
                dash = await callWS({
                  type: "lovelace/config",
                  url_path: null,
                });
                activeUrlPath = null;
              } catch (e2) {}
            }
          }

          if (dash && dash.views) {
            const updateCard = (card) => {
              if (
                card &&
                card.type &&
                (card.type.includes(CARD_TAG) || card.type.includes(CARD_ALIAS))
              ) {
                card.cameras = JSON.parse(JSON.stringify(this._cameras));
                return true;
              }
              return false;
            };

            let found = false;
            for (const view of dash.views) {
              if (view.cards && Array.isArray(view.cards)) {
                for (const card of view.cards) {
                  if (updateCard(card)) {
                    found = true;
                    break;
                  }
                }
              }
              if (!found && view.sections && Array.isArray(view.sections)) {
                for (const section of view.sections) {
                  if (section.cards && Array.isArray(section.cards)) {
                    for (const card of section.cards) {
                      if (updateCard(card)) {
                        found = true;
                        break;
                      }
                    }
                  }
                  if (found) break;
                }
              }
              if (found) break;
            }

            if (found) {
              await callWS({
                type: "lovelace/config/save",
                url_path: activeUrlPath,
                config: dash,
              });
              this._showToast("✅ Изменения успешно сохранены в Home Assistant!");
              return;
            }
          }
        }

        this._showToast("💾 Сохранено локально в памяти браузера!");
      } catch (err) {
        console.error("Save config error:", err);
        this._showToast("💾 Сохранено в локальной памяти (WS: " + err.message + ")");
      }
    }

    // ==========================================
    // VIEW MODE MODAL & GATE OPEN
    // ==========================================
    _openViewModal(cam) {
      this._viewCam = cam;
      window.dispatchEvent(
        new CustomEvent("akvilon-live-modal-state", {
          detail: { active: true, entityId: cam.id },
        })
      );
      this._render();
    }

    _closeViewModal() {
      this._stopLiveStream();
      this._viewCam = null;
      window.dispatchEvent(
        new CustomEvent("akvilon-live-modal-state", {
          detail: { active: false },
        })
      );
      this._render();
    }

    _startLiveStream(camId) {
      this._stopLiveStream();
      const img = this.shadowRoot.getElementById("modal-live-img");
      const osd = this.shadowRoot.getElementById("modal-osd-time");
      if (!img) return;

      try {
        const cached = localStorage.getItem("akvilon_cam_cache_" + camId);
        if (cached) img.src = cached;
      } catch (e) {}

      const updateFrame = () => {
        if (!this._hass || !camId) return;
        const stateObj = this._hass.states[camId];
        const token = (stateObj?.attributes && stateObj.attributes.access_token) || "";
        const ts = Date.now();
        const url = token
          ? `/api/camera_proxy/${camId}?token=${token}&time=${ts}&live=1`
          : `/api/camera_proxy/${camId}?time=${ts}&live=1`;

        const preloader = new Image();
        preloader.onload = () => {
          if (img) img.src = url;
          if (osd) {
            const now = new Date();
            const timeStr = now.toLocaleTimeString("ru-RU", { hour12: false });
            osd.textContent = `${camId} · ${timeStr} · 25 FPS`;
          }
          try {
            localStorage.setItem("akvilon_cam_cache_" + camId, url);
          } catch (e) {}
        };
        preloader.src = url;
      };

      updateFrame();
      this._liveTimer = setInterval(updateFrame, 800);
    }

    _stopLiveStream() {
      if (this._liveTimer) {
        clearInterval(this._liveTimer);
        this._liveTimer = null;
      }
    }

    _startInspectorLiveStream(camId) {
      this._stopInspectorLiveStream();
      const img = this.shadowRoot.getElementById("inspector-live-img");
      const osd = this.shadowRoot.getElementById("inspector-osd-time");
      if (!img) return;

      try {
        const cached = localStorage.getItem("akvilon_cam_cache_" + camId);
        if (cached) img.src = cached;
      } catch (e) {}

      const updateFrame = () => {
        if (!this._hass || !camId || !this._editMode || !this._editingCam || this._editingCam.id !== camId) {
          this._stopInspectorLiveStream();
          return;
        }
        const stateObj = this._hass.states[camId];
        const token = (stateObj?.attributes && stateObj.attributes.access_token) || "";
        const ts = Date.now();
        const url = token
          ? `/api/camera_proxy/${camId}?token=${token}&time=${ts}&live=1`
          : `/api/camera_proxy/${camId}?time=${ts}&live=1`;

        const preloader = new Image();
        preloader.onload = () => {
          const curImg = this.shadowRoot?.getElementById("inspector-live-img");
          if (curImg) curImg.src = url;
          const curOsd = this.shadowRoot?.getElementById("inspector-osd-time");
          if (curOsd) {
            const now = new Date();
            const timeStr = now.toLocaleTimeString("ru-RU", { hour12: false });
            curOsd.textContent = `${camId} · ${timeStr} · LIVE`;
          }
          try {
            localStorage.setItem("akvilon_cam_cache_" + camId, url);
          } catch (e) {}
        };
        preloader.onerror = () => {
          const curOsd = this.shadowRoot?.getElementById("inspector-osd-time");
          if (curOsd) {
            curOsd.textContent = `${camId} · Сигнал отсутствует`;
          }
        };
        preloader.src = url;
      };

      updateFrame();
      this._inspectorLiveTimer = setInterval(updateFrame, 800);
    }

    _stopInspectorLiveStream() {
      if (this._inspectorLiveTimer) {
        clearInterval(this._inspectorLiveTimer);
        this._inspectorLiveTimer = null;
      }
    }

    _handleGateOpen() {
      if (this._isOpeningGate || !this._viewCam || !this._hass) return;

      const camState = this._hass.states[this._viewCam.id];
      const gateId = camState?.attributes?.gate_id;
      let gateButton = this._viewCam.gate_button;

      if (!gateButton && gateId) {
        for (const eid of Object.keys(this._hass.states)) {
          if (eid.startsWith("button.otkryt_") && this._hass.states[eid]?.attributes?.gate_id === gateId) {
            gateButton = eid;
            break;
          }
        }
      }

      this._isOpeningGate = true;
      this._gateCountdown = 5;

      if (navigator.vibrate) navigator.vibrate([40, 60, 40]);

      if (gateButton) {
        this._hass.callService("button", "press", { entity_id: gateButton });
      }
      if (gateId) {
        this._hass.callService("akvilon_home", "open_gate", { gate_id: String(gateId) });
      }

      const isIntercom = this._viewCam.device_type === "intercom";
      this._showToast(isIntercom ? "📞 Команда на открытие домофона отправлена!" : "🚪 Команда на открытие отправлена! Замок разблокирован");
      this._render();

      if (this._countdownInterval) clearInterval(this._countdownInterval);
      this._countdownInterval = setInterval(() => {
        this._gateCountdown -= 1;
        if (this._gateCountdown <= 0) {
          clearInterval(this._countdownInterval);
          this._isOpeningGate = false;
          this._render();
        } else {
          const btn = this.shadowRoot.getElementById("btn-open-door");
          if (btn) {
            const span = btn.querySelector("span");
            if (span) span.textContent = `⏳ Открывается... (${this._gateCountdown}с)`;
            const bar = btn.querySelector(".gate-progress-bar");
            if (bar) bar.style.width = `${(this._gateCountdown / 5) * 100}%`;
          }
        }
      }, 1000);
    }

    _showToast(msg) {
      const toast = this.shadowRoot.getElementById("toast");
      if (toast) {
        toast.textContent = msg;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 3000);
      }
    }
  }

  // Register Custom Elements (with prototype hot-patching for instant live reload)
  if (customElements.get(CARD_TAG)) {
    const existing = customElements.get(CARD_TAG);
    Object.getOwnPropertyNames(AkvilonCctvMapCard.prototype).forEach((p) => {
      if (p !== "constructor") {
        try {
          existing.prototype[p] = AkvilonCctvMapCard.prototype[p];
        } catch (e) {}
      }
    });
  } else {
    customElements.define(CARD_TAG, AkvilonCctvMapCard);
  }

  if (customElements.get(CARD_ALIAS)) {
    const existingAlias = customElements.get(CARD_ALIAS);
    Object.getOwnPropertyNames(AkvilonCctvMapCard.prototype).forEach((p) => {
      if (p !== "constructor") {
        try {
          existingAlias.prototype[p] = AkvilonCctvMapCard.prototype[p];
        } catch (e) {}
      }
    });
  } else {
    class AkvilonCctvMapCardAlias extends AkvilonCctvMapCard {}
    customElements.define(CARD_ALIAS, AkvilonCctvMapCardAlias);
  }

  // Force re-render of any existing instances in the DOM
  try {
    const cards = document.querySelectorAll(`${CARD_TAG}, ${CARD_ALIAS}`);
    cards.forEach((card) => {
      if (typeof card._render === "function") {
        card._render();
      }
    });
  } catch (e) {}

  // Register in Lovelace custom cards
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TAG,
    name: "Akvilon CCTV Interactive Campus Map & Live Editor",
    description: "Интерактивная карта камер ЖК с редактором перетаскивания по Shift, поворота и секторов обзора",
    preview: true,
  });
})();

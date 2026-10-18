/**
 * Akvilon Energy Patch: замена системного раздела «Газ» на «Тепло» на панели /energy Home Assistant.
 */
(function () {
  console.log("[Akvilon] Energy Heat Patch starting...");

  const TEXT_REPLACEMENTS = [
    { regex: /^Газ$/i, repl: "Тепло" },
    { regex: /^Природный газ$/i, repl: "Теплоснабжение" },
    { regex: /^Потребление природного газа$/i, repl: "Теплоснабжение (Отопление)" },
    { regex: /^Потребление газа$/i, repl: "Теплоснабжение" },
    { regex: /^Газовый счетчик$/i, repl: "Теплосчётчик" },
    { regex: /^Счётчик газа$/i, repl: "Счётчик тепла" },
    { regex: /^Газовая сеть$/i, repl: "Теплосеть" },
  ];

  function patchText(str) {
    if (!str) return str;
    let res = str;
    const trimmed = res.trim();
    for (const item of TEXT_REPLACEMENTS) {
      if (item.regex.test(trimmed)) {
        res = res.replace(item.regex, item.repl);
      }
    }
    return res;
  }

  function patchElement(node) {
    if (!node) return;

    // 1. Text node
    if (node.nodeType === Node.TEXT_NODE) {
      const val = node.nodeValue;
      if (val && val.trim()) {
        const patched = patchText(val);
        if (patched !== val) {
          node.nodeValue = patched;
        }
      }
      return;
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return;

    // 2. Attributes (label, title, aria-label)
    for (const attr of ["label", "title", "aria-label"]) {
      const val = node.getAttribute(attr);
      if (val) {
        const patched = patchText(val);
        if (patched !== val) {
          node.setAttribute(attr, patched);
        }
      }
    }

    // 3. Icons (mdi:fire -> mdi:radiator)
    const icon = node.getAttribute && node.getAttribute("icon");
    if (icon === "mdi:fire" || icon === "hass:fire") {
      node.setAttribute("icon", "mdi:radiator");
    }

    // 4. Traverse children & shadowRoot
    if (node.shadowRoot) {
      observeNode(node.shadowRoot);
      for (const child of node.shadowRoot.childNodes) {
        patchElement(child);
      }
    }

    for (const child of node.childNodes) {
      patchElement(child);
    }
  }

  const observedNodes = new WeakSet();

  function observeNode(root) {
    if (!root || observedNodes.has(root)) return;
    observedNodes.add(root);

    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const added of m.addedNodes) {
          patchElement(added);
        }
        if (m.type === "characterData") {
          patchElement(m.target);
        }
      }
    });

    observer.observe(root, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  function runPatch() {
    patchElement(document.body);
    observeNode(document.body);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", runPatch);
  } else {
    runPatch();
  }

  // Периодический прогон для SPA-навигации и ленивой загрузки карточек
  setInterval(runPatch, 800);
  console.log("[Akvilon] Energy Heat Patch initialized successfully");
})();

const FORMAT_STORAGE_KEY = "cookie_mgr_export_format";
const MUSE_SESSION_COOKIES = ["hatch_sess", "hatch_vml", "__Host-hatch_one_tap"];

const {
  getBaseDomain,
  normalizeTargetInput,
  dedupeCookies,
  formatCookiesHeader,
  formatCookiesJson,
  formatCookiesNetscape,
  makeExportFilename,
  parseCookiesInput,
  buildCookieSetDetails,
  buildClearPlan,
} = window.CookieUtils;

let activeTabUrl = "";
let activeStoreId = undefined;
let exportFormat = "header";

const siteInputEl = document.getElementById("siteInput");
const useCurrentBtnEl = document.getElementById("useCurrentBtn");
const includeSubdomainsEl = document.getElementById("includeSubdomains");
const subdomainsLabelEl = document.getElementById("subdomainsLabel");
const cookieCountEl = document.getElementById("cookieCount");
const copyBtnEl = document.getElementById("copyBtn");
const downloadBtnEl = document.getElementById("downloadBtn");
const loadFileBtnEl = document.getElementById("loadFileBtn");
const importFileEl = document.getElementById("importFile");
const importInputEl = document.getElementById("importInput");
const importHintEl = document.getElementById("importHint");
const clearBeforeImportEl = document.getElementById("clearBeforeImport");
const importBtnEl = document.getElementById("importBtn");
const clearBtnEl = document.getElementById("clearBtn");
const clearConfirmEl = document.getElementById("clearConfirm");
const clearTargetNameEl = document.getElementById("clearTargetName");
const cancelClearBtnEl = document.getElementById("cancelClearBtn");
const confirmClearBtnEl = document.getElementById("confirmClearBtn");
const statusEl = document.getElementById("status");
const formatBtns = Array.from(document.querySelectorAll(".seg-btn[data-format]"));

function setStatus(msg, type = "") {
  statusEl.className = type;
  statusEl.textContent = msg;
}

function hideClearConfirm() {
  clearConfirmEl.classList.remove("visible");
  clearBtnEl.style.display = "";
}

function getCurrentTarget() {
  return normalizeTargetInput(siteInputEl.value, activeTabUrl);
}

function setExportFormat(fmt) {
  if (!["header", "json", "netscape"].includes(fmt)) return;
  exportFormat = fmt;
  try {
    localStorage.setItem(FORMAT_STORAGE_KEY, fmt);
  } catch (_) {
    // Ignore storage errors
  }
  for (const btn of formatBtns) {
    btn.classList.toggle("active", btn.dataset.format === fmt);
  }
}

async function copyToClipboard(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (_) {
      // Fallback below
    }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(ta);
  if (!ok) {
    throw new Error("Clipboard write failed");
  }
}

async function getCookiesForTarget(target, includeSubdomains, storeId, format = exportFormat) {
  const storeOpt = storeId ? { storeId } : {};
  const urlCookies = await chrome.cookies.getAll({ url: target.url, ...storeOpt });

  if (includeSubdomains && !target.isIpOrLocalhost) {
    const domainCookies = await chrome.cookies.getAll({
      domain: target.baseDomain,
      ...storeOpt,
    });
    return dedupeCookies([...urlCookies, ...domainCookies]);
  }

  if (format === "json" || format === "netscape") {
    const hostCookies = await chrome.cookies.getAll({
      domain: target.hostname,
      ...storeOpt,
    });
    const exactHostCookies = hostCookies.filter(
      (c) => (c.domain || "").replace(/^\./, "").toLowerCase() === target.hostname,
    );
    return dedupeCookies([...urlCookies, ...exactHostCookies]);
  }

  return dedupeCookies(urlCookies);
}

function formatCookiesByType(cookies, format) {
  if (format === "json") return formatCookiesJson(cookies);
  if (format === "netscape") return formatCookiesNetscape(cookies);
  return formatCookiesHeader(cookies);
}

function formatDisplayName(format) {
  if (format === "json") return "JSON";
  if (format === "netscape") return "Netscape";
  return "Header";
}

async function refreshSitePreview() {
  const target = getCurrentTarget();
  if (!target.valid) {
    subdomainsLabelEl.textContent = "Include subdomains";
    cookieCountEl.textContent = "—";
    cookieCountEl.classList.remove("has-cookies");
    return;
  }

  if (!target.isIpOrLocalhost && target.hostname !== target.baseDomain) {
    subdomainsLabelEl.textContent = `Include subdomains (*.${target.baseDomain})`;
  } else if (!target.isIpOrLocalhost) {
    subdomainsLabelEl.textContent = `Include subdomains (*.${target.baseDomain})`;
  } else {
    subdomainsLabelEl.textContent = "Include subdomains (N/A for IP/localhost)";
  }

  try {
    const cookies = await getCookiesForTarget(
      target,
      includeSubdomainsEl.checked,
      activeStoreId,
      exportFormat,
    );
    const n = cookies.length;
    cookieCountEl.textContent = `${n} ${n === 1 ? "cookie" : "cookies"}`;
    cookieCountEl.classList.toggle("has-cookies", n > 0);
  } catch (_) {
    cookieCountEl.textContent = "—";
    cookieCountEl.classList.remove("has-cookies");
  }
}

function updateImportHint() {
  const raw = importInputEl.value;
  if (!raw.trim()) {
    importHintEl.textContent = "";
    return;
  }
  const { format, cookies } = parseCookiesInput(raw);
  if (cookies.length === 0) {
    importHintEl.textContent = "No valid cookies detected.";
    return;
  }
  const labelMap = {
    "json-array": "JSON",
    "json-object": "JSON Object",
    netscape: "Netscape",
    header: "Header",
  };
  const domains = new Set(
    cookies.map((c) => (c.domain || "").replace(/^\./, "").toLowerCase()).filter(Boolean),
  );
  const countText = `${cookies.length} ${cookies.length === 1 ? "cookie" : "cookies"}`;
  const domainText =
    domains.size > 0 ? ` · ${domains.size} ${domains.size === 1 ? "domain" : "domains"}` : "";
  importHintEl.textContent = `Detected: ${labelMap[format] || format} (${countText}${domainText})`;
}

async function removeCookieList(cookies, fallbackUrl) {
  let removed = 0;
  for (const c of cookies) {
    const protocol = c.secure ? "https" : "http";
    const domain = c.domain ? c.domain.replace(/^\./, "") : new URL(fallbackUrl).hostname;
    const path = c.path || "/";
    const url = `${protocol}://${domain}${path}`;
    const details = {
      url,
      name: c.name,
      storeId: c.storeId,
    };
    if (c.partitionKey && typeof c.partitionKey === "object") {
      details.partitionKey = c.partitionKey;
    }
    try {
      const res = await chrome.cookies.remove(details);
      if (res) removed += 1;
    } catch (_) {
      if (details.partitionKey) {
        try {
          delete details.partitionKey;
          const res = await chrome.cookies.remove(details);
          if (res) removed += 1;
        } catch (_) {
          // Ignore cookie removal failure
        }
      }
    }
  }
  return removed;
}

async function reloadTabs(tabs) {
  let reloaded = 0;
  for (const tab of tabs) {
    if (tab.id == null) continue;
    try {
      await chrome.tabs.reload(tab.id, { bypassCache: true });
      reloaded += 1;
    } catch (_) {
      // Ignore closed/restricted tabs
    }
  }
  return reloaded;
}

async function clearSiteData(target, { includeSubdomains = false, reload = true, storeId } = {}) {
  const plan = buildClearPlan(target, includeSubdomains);

  let tabs = [];
  try {
    tabs = await chrome.tabs.query({ url: plan.tabPatterns });
  } catch (_) {
    tabs = [];
  }

  const storeOpt = storeId ? { storeId } : {};
  let cookiesToRemove = [];
  if (includeSubdomains && !target.isIpOrLocalhost) {
    const byUrl = await chrome.cookies.getAll({ url: target.url, ...storeOpt });
    const byDomain = await chrome.cookies.getAll({ domain: plan.matchDomain, ...storeOpt });
    cookiesToRemove = dedupeCookies([...byUrl, ...byDomain]);
  } else {
    const byUrl = await chrome.cookies.getAll({ url: target.url, ...storeOpt });
    const byHost = await chrome.cookies.getAll({ domain: target.hostname, ...storeOpt });
    const exactHost = byHost.filter(
      (c) => (c.domain || "").replace(/^\./, "").toLowerCase() === target.hostname,
    );
    cookiesToRemove = dedupeCookies([...byUrl, ...exactHost]);
  }

  const originSet = new Set(plan.baseOrigins);
  for (const tab of tabs) {
    if (!tab.url) continue;
    try {
      originSet.add(new URL(tab.url).origin);
    } catch (_) {
      // Ignore invalid tab URLs
    }
  }
  for (const c of cookiesToRemove) {
    const cleanDom = (c.domain || "").replace(/^\./, "");
    if (!cleanDom) continue;
    const proto = c.secure ? "https" : "http";
    try {
      originSet.add(new URL(`${proto}://${cleanDom}`).origin);
    } catch (_) {
      // Ignore invalid cookie domain
    }
  }

  for (const tab of tabs) {
    if (tab.id == null) continue;
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          try {
            window.sessionStorage.clear();
          } catch (_) {}
          try {
            window.localStorage.clear();
          } catch (_) {}
        },
      });
    } catch (_) {
      // Ignore discarded/restricted tabs
    }
  }

  const origins = Array.from(originSet);
  if (origins.length > 0) {
    try {
      await chrome.browsingData.remove(
        { origins },
        {
          cache: true,
          cacheStorage: true,
          cookies: true,
          fileSystems: true,
          indexedDB: true,
          localStorage: true,
          serviceWorkers: true,
        },
      );
    } catch (_) {
      // Continue to explicit cookie removal even if browsingData rejects an origin
    }
  }

  await removeCookieList(cookiesToRemove, target.url);

  const reloadedTabs = reload ? await reloadTabs(tabs) : 0;
  return { tabs, reloadedTabs };
}

async function clearCookiesForExtraDomains(domains, excludeBaseDomain, storeId) {
  const storeOpt = storeId ? { storeId } : {};
  for (const dom of domains) {
    const clean = dom.replace(/^\./, "").toLowerCase();
    if (!clean) continue;
    if (
      excludeBaseDomain &&
      (clean === excludeBaseDomain || clean.endsWith(`.${excludeBaseDomain}`))
    ) {
      continue;
    }
    try {
      const existing = await chrome.cookies.getAll({ domain: clean, ...storeOpt });
      await removeCookieList(existing, `https://${clean}/`);
    } catch (_) {
      // Ignore domain removal errors
    }
  }
}

async function findTabsForDomains(domains) {
  const patterns = new Set();
  for (const dom of domains) {
    const clean = dom.replace(/^\./, "").toLowerCase();
    if (!clean) continue;
    const base = getBaseDomain(clean);
    patterns.add(`*://${clean}/*`);
    if (base && base !== clean) {
      patterns.add(`*://${base}/*`);
      patterns.add(`*://*.${base}/*`);
    } else {
      patterns.add(`*://*.${clean}/*`);
    }
  }
  if (patterns.size === 0) return [];
  try {
    return await chrome.tabs.query({ url: Array.from(patterns) });
  } catch (_) {
    return [];
  }
}

async function initPopup() {
  try {
    const savedFmt = localStorage.getItem(FORMAT_STORAGE_KEY);
    if (savedFmt && ["header", "json", "netscape"].includes(savedFmt)) {
      setExportFormat(savedFmt);
    }
  } catch (_) {
    // Ignore storage errors
  }

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      try {
        const stores = await chrome.cookies.getAllCookieStores();
        const store = stores.find((s) => Array.isArray(s.tabIds) && s.tabIds.includes(tab.id));
        if (store) activeStoreId = store.id;
      } catch (_) {
        // Ignore store lookup failure
      }

      if (tab.url && /^https?:\/\//i.test(tab.url)) {
        activeTabUrl = tab.url;
        siteInputEl.value = new URL(tab.url).origin;
        useCurrentBtnEl.disabled = false;
      } else {
        activeTabUrl = "";
        useCurrentBtnEl.disabled = true;
        setStatus(
          "Current tab is restricted. Enter a site URL/domain or import JSON/Netscape cookies.",
        );
      }
    }
  } catch (err) {
    useCurrentBtnEl.disabled = true;
    setStatus("Unable to read active tab: " + (err?.message || String(err)), "err");
  }

  await refreshSitePreview();
}

for (const btn of formatBtns) {
  btn.addEventListener("click", () => {
    setExportFormat(btn.dataset.format);
    refreshSitePreview();
  });
}

siteInputEl.addEventListener("input", () => {
  hideClearConfirm();
  refreshSitePreview();
});

includeSubdomainsEl.addEventListener("change", () => {
  hideClearConfirm();
  refreshSitePreview();
});

useCurrentBtnEl.addEventListener("click", async () => {
  hideClearConfirm();
  if (!activeTabUrl) return;
  try {
    siteInputEl.value = new URL(activeTabUrl).origin;
    setStatus("");
    await refreshSitePreview();
  } catch (_) {
    // Ignore invalid activeTabUrl
  }
});

copyBtnEl.addEventListener("click", async () => {
  hideClearConfirm();
  const target = getCurrentTarget();
  if (!target.valid) {
    setStatus("Please enter a valid target site URL or domain.", "err");
    return;
  }

  setStatus(`Reading cookies for ${target.displayHost}...`);
  try {
    const cookies = await getCookiesForTarget(
      target,
      includeSubdomainsEl.checked,
      activeStoreId,
      exportFormat,
    );
    if (!cookies || cookies.length === 0) {
      setStatus(`No cookies found for ${target.displayHost}.`, "err");
      return;
    }

    const output = formatCookiesByType(cookies, exportFormat);
    await copyToClipboard(output);

    if (
      target.baseDomain === "muse.ai" &&
      exportFormat === "header" &&
      !cookies.some((c) => MUSE_SESSION_COOKIES.includes(c.name))
    ) {
      setStatus(
        `Copied ${cookies.length} cookies (Header) for ${target.displayHost}, but muse.ai session cookies are missing — please verify login.`,
        "warn",
      );
      return;
    }

    setStatus(
      `Copied ${cookies.length} ${cookies.length === 1 ? "cookie" : "cookies"} (${formatDisplayName(exportFormat)}) for ${target.displayHost}!`,
      "ok",
    );
  } catch (err) {
    setStatus("Copy failed: " + (err?.message || String(err)), "err");
  }
});

downloadBtnEl.addEventListener("click", async () => {
  hideClearConfirm();
  const target = getCurrentTarget();
  if (!target.valid) {
    setStatus("Please enter a valid target site URL or domain.", "err");
    return;
  }

  setStatus(`Exporting cookies for ${target.displayHost}...`);
  try {
    const cookies = await getCookiesForTarget(
      target,
      includeSubdomainsEl.checked,
      activeStoreId,
      exportFormat,
    );
    if (!cookies || cookies.length === 0) {
      setStatus(`No cookies found for ${target.displayHost}.`, "err");
      return;
    }

    const content = formatCookiesByType(cookies, exportFormat);
    const filename = makeExportFilename(target.hostname, exportFormat);
    const mime = exportFormat === "json" ? "application/json" : "text/plain";
    const blob = new Blob([content], { type: `${mime};charset=utf-8` });
    const blobUrl = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);

    setStatus(
      `Downloaded ${filename} (${cookies.length} ${cookies.length === 1 ? "cookie" : "cookies"}).`,
      "ok",
    );
  } catch (err) {
    setStatus("Download failed: " + (err?.message || String(err)), "err");
  }
});

loadFileBtnEl.addEventListener("click", () => {
  importFileEl.click();
});

importFileEl.addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    importInputEl.value = text;
    updateImportHint();
    setStatus(`Loaded ${file.name}. Click Import Cookies to apply.`);
  } catch (err) {
    setStatus("Failed to read file: " + (err?.message || String(err)), "err");
  } finally {
    importFileEl.value = "";
  }
});

importInputEl.addEventListener("input", updateImportHint);

importBtnEl.addEventListener("click", async () => {
  hideClearConfirm();
  const { cookies: parsed } = parseCookiesInput(importInputEl.value);
  if (parsed.length === 0) {
    setStatus("Please paste or load valid cookies (Header, JSON, or Netscape).", "err");
    return;
  }

  const target = getCurrentTarget();
  const needsFallbackTarget = parsed.some((c) => {
    if (c.domain && c.domain.trim()) return false;
    if (c.url && c.url.trim()) {
      try {
        new URL(c.url.trim());
        return false;
      } catch (_) {
        return true;
      }
    }
    return true;
  });

  if (needsFallbackTarget && !target.valid) {
    setStatus(
      "Please enter a target site URL/domain before importing cookies without a domain.",
      "err",
    );
    return;
  }

  importBtnEl.disabled = true;
  setStatus(
    clearBeforeImportEl.checked
      ? "Clearing site data & importing cookies..."
      : "Importing cookies...",
  );

  try {
    const touchedDomains = new Set();
    const prepared = [];
    let failedCount = 0;
    let firstError = "";

    for (const item of parsed) {
      try {
        const built = buildCookieSetDetails(item, target.valid ? target : null, activeStoreId);
        prepared.push(built);
        touchedDomains.add(built.host);
      } catch (err) {
        failedCount += 1;
        if (!firstError) firstError = err?.message || String(err);
      }
    }

    let tabsToReload = [];
    if (clearBeforeImportEl.checked) {
      if (target.valid) {
        const { tabs } = await clearSiteData(target, {
          includeSubdomains: includeSubdomainsEl.checked,
          reload: false,
          storeId: activeStoreId,
        });
        tabsToReload = tabs;
      }
      await clearCookiesForExtraDomains(
        touchedDomains,
        target.valid ? target.baseDomain : "",
        activeStoreId,
      );
    }

    let importedCount = 0;
    for (const { details } of prepared) {
      try {
        await chrome.cookies.set(details);
        importedCount += 1;
      } catch (err) {
        if (details.partitionKey) {
          try {
            const retryDetails = { ...details };
            delete retryDetails.partitionKey;
            await chrome.cookies.set(retryDetails);
            importedCount += 1;
            continue;
          } catch (retryErr) {
            failedCount += 1;
            if (!firstError) firstError = retryErr?.message || String(retryErr);
            continue;
          }
        }
        failedCount += 1;
        if (!firstError) firstError = err?.message || String(err);
      }
    }

    const extraTabs = await findTabsForDomains(touchedDomains);
    const mergedTabsMap = new Map();
    for (const t of [...tabsToReload, ...extraTabs]) {
      if (t && t.id != null) mergedTabsMap.set(t.id, t);
    }
    const reloadedTabs = await reloadTabs(Array.from(mergedTabsMap.values()));

    await refreshSitePreview();

    if (importedCount === 0) {
      setStatus(`Import failed: ${firstError || "No cookies could be written."}`, "err");
      return;
    }

    const tabSuffix =
      reloadedTabs > 0 ? ` & reloaded ${reloadedTabs} ${reloadedTabs === 1 ? "tab" : "tabs"}` : "";
    if (failedCount > 0) {
      setStatus(
        `Imported ${importedCount} cookies (${failedCount} failed: ${firstError})${tabSuffix}.`,
        "warn",
      );
    } else {
      setStatus(`Imported ${importedCount} cookies${tabSuffix}!`, "ok");
    }
  } catch (err) {
    setStatus("Import failed: " + (err?.message || String(err)), "err");
  } finally {
    importBtnEl.disabled = false;
  }
});

clearBtnEl.addEventListener("click", () => {
  const target = getCurrentTarget();
  if (!target.valid) {
    setStatus("Please enter a valid target site URL or domain to clear.", "err");
    return;
  }
  setStatus("");
  const scope =
    includeSubdomainsEl.checked && !target.isIpOrLocalhost
      ? `${target.baseDomain} (+ subdomains)`
      : target.displayHost;
  clearTargetNameEl.textContent = scope;
  clearBtnEl.style.display = "none";
  clearConfirmEl.classList.add("visible");
});

cancelClearBtnEl.addEventListener("click", () => {
  hideClearConfirm();
  setStatus("");
});

confirmClearBtnEl.addEventListener("click", async () => {
  const target = getCurrentTarget();
  if (!target.valid) {
    hideClearConfirm();
    setStatus("Please enter a valid target site URL or domain.", "err");
    return;
  }

  confirmClearBtnEl.disabled = true;
  cancelClearBtnEl.disabled = true;
  setStatus(`Clearing site data for ${target.displayHost}...`);

  try {
    const { reloadedTabs } = await clearSiteData(target, {
      includeSubdomains: includeSubdomainsEl.checked,
      reload: true,
      storeId: activeStoreId,
    });
    await refreshSitePreview();

    if (reloadedTabs > 0) {
      setStatus(
        `Cleared site data & reloaded ${reloadedTabs} ${target.displayHost} ${reloadedTabs === 1 ? "tab" : "tabs"}.`,
        "ok",
      );
    } else {
      setStatus(`Cleared site data for ${target.displayHost}!`, "ok");
    }
  } catch (err) {
    setStatus("Clear failed: " + (err?.message || String(err)), "err");
  } finally {
    confirmClearBtnEl.disabled = false;
    cancelClearBtnEl.disabled = false;
    hideClearConfirm();
  }
});

initPopup();

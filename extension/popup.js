const MUSE_URL = "https://muse.ai";

function setStatus(msg, type = "") {
  const statusEl = document.getElementById("status");
  statusEl.className = type;
  statusEl.textContent = msg;
}

function hideClearConfirm() {
  document.getElementById("clearConfirm").classList.remove("visible");
  document.getElementById("clearBtn").style.display = "";
}

async function clearMuseCookies() {
  const existing = await chrome.cookies.getAll({ domain: "muse.ai" });
  let removed = 0;
  for (const c of existing) {
    const protocol = c.secure ? "https" : "http";
    const domain = c.domain ? c.domain.replace(/^\./, "") : "muse.ai";
    const path = c.path || "/";
    const url = `${protocol}://${domain}${path}`;
    const res = await chrome.cookies.remove({
      url,
      name: c.name,
      storeId: c.storeId,
    });
    if (res) removed += 1;
  }
  return { total: existing.length, removed };
}

async function clearMuseSiteData() {
  let tabs = [];
  try {
    tabs = await chrome.tabs.query({
      url: ["https://muse.ai/*", "https://*.muse.ai/*"],
    });
  } catch (_) {
    tabs = [];
  }

  const originSet = new Set([
    "https://muse.ai",
    "https://www.muse.ai",
    "http://muse.ai",
    "http://www.muse.ai",
  ]);
  for (const tab of tabs) {
    if (!tab.url) continue;
    try {
      originSet.add(new URL(tab.url).origin);
    } catch (_) {
      // Ignore invalid or restricted tab URLs
    }
  }
  const origins = Array.from(originSet);

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
      // Ignore discarded/restricted tabs so site data removal continues
    }
  }

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

  await clearMuseCookies();

  let reloadedTabs = 0;
  for (const tab of tabs) {
    if (tab.id == null) continue;
    try {
      await chrome.tabs.reload(tab.id, { bypassCache: true });
      reloadedTabs += 1;
    } catch (_) {
      // Ignore tabs that were closed or cannot be reloaded
    }
  }
  return { reloadedTabs };
}

function parseCookiesInput(raw) {
  const text = (raw || "").trim();
  if (!text) return [];

  // Try JSON (array of {name, value} or plain object {name: value})
  if (text.startsWith("{") || text.startsWith("[")) {
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed
          .filter((item) => item && typeof item.name === "string" && item.value !== undefined)
          .map((item) => ({ name: item.name.trim(), value: String(item.value) }))
          .filter((item) => item.name);
      }
      if (parsed && typeof parsed === "object") {
        return Object.entries(parsed)
          .filter(([k, v]) => k && v !== undefined && v !== null)
          .map(([k, v]) => ({ name: String(k).trim(), value: String(v) }));
      }
    } catch (_) {
      // Fallback to header string parser
    }
  }

  // Cookie header string: strip optional "Cookie:" prefix
  const cleaned = text.replace(/^cookie:\s*/i, "");
  const out = [];
  for (const part of cleaned.split(";")) {
    const idx = part.indexOf("=");
    if (idx <= 0) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (name) out.push({ name, value });
  }
  return out;
}

document.getElementById("copyBtn").addEventListener("click", async () => {
  hideClearConfirm();
  setStatus("Reading cookies...");
  try {
    const cookies = await chrome.cookies.getAll({ url: MUSE_URL });
    if (!cookies || cookies.length === 0) {
      setStatus("No cookies found for muse.ai. Please log in first.", "err");
      return;
    }
    const hasSess = cookies.some((c) =>
      ["hatch_sess", "hatch_vml", "__Host-hatch_one_tap"].includes(c.name),
    );
    if (!hasSess) {
      setStatus("Missing session cookies. Please log in to muse.ai.", "err");
      return;
    }
    const headerStr = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    await navigator.clipboard.writeText(headerStr);
    setStatus(`Copied ${cookies.length} cookies to clipboard!`, "ok");
  } catch (err) {
    setStatus("Error: " + (err?.message || String(err)), "err");
  }
});

document.getElementById("importBtn").addEventListener("click", async () => {
  hideClearConfirm();
  const raw = document.getElementById("importInput").value;
  const parsed = parseCookiesInput(raw);
  if (parsed.length === 0) {
    setStatus("Please paste a valid Cookie header string or JSON.", "err");
    return;
  }

  setStatus("Importing cookies...");
  try {
    await clearMuseCookies();

    const expirationDate = Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 365;
    let count = 0;
    for (const { name, value } of parsed) {
      const details = {
        url: MUSE_URL,
        name,
        value,
        path: "/",
        secure: true,
        sameSite: "lax",
        expirationDate,
      };
      // __Host- cookies must NOT specify a domain attribute
      if (!name.startsWith("__Host-") && !name.startsWith("__Secure-")) {
        details.domain = "muse.ai";
      }
      await chrome.cookies.set(details);
      count += 1;
    }

    setStatus(`Imported ${count} cookies for muse.ai! Refresh muse.ai tab to apply.`, "ok");
  } catch (err) {
    setStatus("Import failed: " + (err?.message || String(err)), "err");
  }
});

document.getElementById("clearBtn").addEventListener("click", () => {
  setStatus("");
  document.getElementById("clearBtn").style.display = "none";
  document.getElementById("clearConfirm").classList.add("visible");
});

document.getElementById("cancelClearBtn").addEventListener("click", () => {
  hideClearConfirm();
  setStatus("");
});

document.getElementById("confirmClearBtn").addEventListener("click", async () => {
  const confirmBtn = document.getElementById("confirmClearBtn");
  const cancelBtn = document.getElementById("cancelClearBtn");
  confirmBtn.disabled = true;
  cancelBtn.disabled = true;
  setStatus("Clearing site data...");

  try {
    const { reloadedTabs } = await clearMuseSiteData();
    if (reloadedTabs > 0) {
      setStatus(
        `Cleared site data & reloaded ${reloadedTabs} muse.ai ${reloadedTabs === 1 ? "tab" : "tabs"}.`,
        "ok",
      );
    } else {
      setStatus("Cleared site data for muse.ai!", "ok");
    }
  } catch (err) {
    setStatus("Clear failed: " + (err?.message || String(err)), "err");
  } finally {
    confirmBtn.disabled = false;
    cancelBtn.disabled = false;
    hideClearConfirm();
  }
});

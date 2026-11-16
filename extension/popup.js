document.getElementById("copyBtn").addEventListener("click", async () => {
  const statusEl = document.getElementById("status");
  statusEl.className = "";
  statusEl.textContent = "Reading cookies...";
  try {
    const cookies = await chrome.cookies.getAll({ url: "https://muse.ai" });
    if (!cookies || cookies.length === 0) {
      statusEl.className = "err";
      statusEl.textContent = "No cookies found for muse.ai. Please log in first.";
      return;
    }
    const hasSess = cookies.some((c) =>
      ["hatch_sess", "hatch_vml", "__Host-hatch_one_tap"].includes(c.name)
    );
    if (!hasSess) {
      statusEl.className = "err";
      statusEl.textContent = "Missing session cookies. Please log in to muse.ai.";
      return;
    }
    const headerStr = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    await navigator.clipboard.writeText(headerStr);
    statusEl.className = "ok";
    statusEl.textContent = `Copied ${cookies.length} cookies to clipboard!`;
  } catch (err) {
    statusEl.className = "err";
    statusEl.textContent = "Error: " + (err?.message || String(err));
  }
});

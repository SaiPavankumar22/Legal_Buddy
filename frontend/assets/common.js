const configuredApiBase = window.LEGAL_BUDDY_CONFIG?.apiBaseUrl;
const LEGAL_BUDDY_API_BASE = configuredApiBase !== undefined && configuredApiBase !== null
  ? configuredApiBase
  : (window.location.origin?.startsWith("http") ? window.location.origin : "http://127.0.0.1:4000");

async function fetchJson(path, options = {}) {
  const url = `${LEGAL_BUDDY_API_BASE}${path}`;
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail?.details || data.detail?.error || data.error || "Request failed.");
  }
  return data;
}

async function renderHealthStatus() {
  const healthDot = document.getElementById("health-dot");
  const healthText = document.getElementById("health-text");
  if (!healthDot || !healthText) {
    return;
  }

  try {
    const data = await fetchJson("/api/health");
    const ollama = data.ollama || {};
    const ok = Boolean(ollama.modelLoaded);
    healthDot.classList.toggle("ok", ok);
    healthText.textContent = ok
      ? `Connected to ${ollama.chatModel} at ${ollama.baseUrl}.`
      : ollama.warning || `Backend is up, but ${ollama.chatModel} is not loaded yet.`;
  } catch (error) {
    healthText.textContent = `Backend check failed: ${error.message}`;
  }
}

renderHealthStatus();

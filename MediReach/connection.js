(function (root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MediReachConnection = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  const copy = {
    en: {
      checking: "Checking API and database readiness…",
      ready: "API and database are ready. Availability records can be requested.",
      unavailable: "API or database is not ready. No inventory was substituted. Retry the connection check.",
      retry: "Check connection"
    },
    ta: {
      checking: "API மற்றும் தரவுத்தளத் தயார்நிலை சரிபார்க்கப்படுகிறது…",
      ready: "API மற்றும் தரவுத்தளம் தயாராக உள்ளன. இருப்புப் பதிவுகளைக் கோரலாம்.",
      unavailable: "API அல்லது தரவுத்தளம் தயாராக இல்லை. மாற்றாக மாதிரித் தரவு காட்டப்படவில்லை. மீண்டும் இணைப்பைச் சரிபார்க்கவும்.",
      retry: "இணைப்பைச் சரிபார்க்கவும்"
    }
  };

  function getCopy(language, state) {
    const dictionary = copy[language] || copy.en;
    return dictionary[state] || dictionary.unavailable;
  }

  async function checkApiReadiness({
    baseUrl,
    api = root && root.MediReachApi,
    fetchImpl = root && root.fetch,
    timeoutMs = 8000,
    AbortControllerImpl = root && root.AbortController,
    setTimeoutImpl = root && root.setTimeout,
    clearTimeoutImpl = root && root.clearTimeout
  } = {}) {
    if (!api || typeof api.normalizeApiBase !== "function") {
      throw new Error("MediReach API client is unavailable.");
    }
    const normalized = api.normalizeApiBase(baseUrl);
    if (!normalized.configured || !normalized.url) {
      throw new Error(normalized.error || "MediReach API URL is not configured correctly.");
    }
    if (typeof fetchImpl !== "function" || typeof AbortControllerImpl !== "function") {
      throw new Error("Connection checks are unavailable in this browser.");
    }

    const controller = new AbortControllerImpl();
    const duration = Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : 8000;
    let timedOut = false;
    const timer = setTimeoutImpl(() => {
      timedOut = true;
      controller.abort();
    }, duration);

    try {
      let response;
      try {
        response = await fetchImpl(normalized.url + "/health/ready", {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "omit",
          cache: "no-store",
          signal: controller.signal
        });
      } catch (_error) {
        throw new Error(timedOut ? "Readiness check timed out." : "Readiness check failed.");
      }

      if (!response || !response.ok) {
        throw new Error("Readiness check failed.");
      }

      let payload;
      try {
        payload = await response.json();
      } catch (_error) {
        throw new Error("Readiness response was invalid.");
      }

      if (timedOut) throw new Error("Readiness check timed out.");
      if (!payload || payload.status !== "ready") {
        throw new Error("API database is not ready.");
      }
      return { ready: true };
    } finally {
      clearTimeoutImpl(timer);
    }
  }

  function init(documentRef = root && root.document) {
    if (!documentRef || !documentRef.getElementById) return;
    const meta = documentRef.querySelector('meta[name="medireach-api-base"]');
    const rawBase = meta && typeof meta.content === "string" ? meta.content : "";
    const api = root && root.MediReachApi;
    if (!api || typeof api.normalizeApiBase !== "function") return;
    const config = api.normalizeApiBase(rawBase);
    if (!config.configured) return;

    const modeNote = documentRef.getElementById("mode-note");
    if (!modeNote || !modeNote.parentNode) return;
    const panel = documentRef.createElement("div");
    panel.className = "api-connection";
    panel.setAttribute("aria-live", "polite");
    panel.setAttribute("role", "status");
    const status = documentRef.createElement("p");
    status.className = "api-connection__status";
    const retry = documentRef.createElement("button");
    retry.type = "button";
    retry.className = "api-connection__retry";
    panel.appendChild(status);
    panel.appendChild(retry);
    modeNote.insertAdjacentElement("afterend", panel);

    let state = "checking";
    let busy = false;
    const render = () => {
      const language = documentRef.documentElement.lang === "ta" ? "ta" : "en";
      status.textContent = getCopy(language, state);
      retry.textContent = getCopy(language, "retry");
      retry.disabled = busy;
      retry.hidden = state === "ready";
    };

    const runCheck = async () => {
      if (busy) return;
      busy = true;
      state = "checking";
      render();
      try {
        await checkApiReadiness({ baseUrl: config.url, api });
        state = "ready";
      } catch (_error) {
        state = "unavailable";
      } finally {
        busy = false;
        render();
      }
    };

    retry.addEventListener("click", runCheck);
    if (typeof root.MutationObserver === "function") {
      const observer = new root.MutationObserver(render);
      observer.observe(documentRef.documentElement, { attributes: true, attributeFilter: ["lang"] });
    }
    render();
    runCheck();
  }

  return { getCopy, checkApiReadiness, init };
});

(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MediReachApi = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const ALLOWED_STATUSES = new Set(["available", "low_stock", "unavailable", "not_reported"]);
  const ALLOWED_CONFIDENCE = new Set(["Recently Verified", "Needs Confirmation", "Outdated"]);

  function normalizeApiBase(rawValue) {
    const value = typeof rawValue === "string" ? rawValue.trim() : "";
    if (!value) return { configured: false, url: null, error: null };

    try {
      const parsed = new URL(value);
      const localHttp = parsed.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
      if (parsed.protocol !== "https:" && !localHttp) {
        throw new Error("Use HTTPS for a remote API.");
      }
      if (parsed.username || parsed.password || parsed.search || parsed.hash) {
        throw new Error("The API base URL must not contain credentials, a query, or a fragment.");
      }
      return {
        configured: true,
        url: parsed.href.replace(/\/+$/, ""),
        error: null
      };
    } catch (error) {
      return {
        configured: true,
        url: null,
        error: error instanceof Error ? error.message : "Invalid API URL."
      };
    }
  }

  function getApiBaseFromDocument(documentRef) {
    const meta = documentRef && documentRef.querySelector
      ? documentRef.querySelector('meta[name="medireach-api-base"]')
      : null;
    return meta && typeof meta.content === "string" ? meta.content : "";
  }

  function buildAvailabilityUrl(baseValue, medicine, district = "") {
    const normalized = normalizeApiBase(baseValue);
    if (!normalized.configured || !normalized.url) {
      throw new Error(normalized.error || "API base URL is not configured.");
    }
    const url = new URL(normalized.url + "/api/v1/availability");
    url.searchParams.set("medicine", String(medicine || "").trim());
    if (String(district || "").trim()) {
      url.searchParams.set("district", String(district).trim());
    }
    return url.toString();
  }

  function validateAvailabilityRecords(payload) {
    if (!Array.isArray(payload)) {
      throw new Error("The availability API returned an unexpected response.");
    }

    for (const record of payload) {
      if (!record || typeof record !== "object" ||
          !record.facility || typeof record.facility.name !== "string" ||
          typeof record.facility.address !== "string" ||
          !record.medicine || typeof record.medicine.name !== "string" ||
          !ALLOWED_STATUSES.has(record.status) ||
          typeof record.verified_at !== "string" ||
          !ALLOWED_CONFIDENCE.has(record.confidence) ||
          typeof record.is_demo !== "boolean" ||
          !(record.quantity === null ||
            (Number.isInteger(record.quantity) && record.quantity >= 0))) {
        throw new Error("The availability API returned an invalid record.");
      }
    }
    return payload;
  }

  async function fetchAvailability({
    baseUrl,
    medicine,
    district = "",
    fetchImpl = typeof fetch === "function" ? fetch : null
  }) {
    if (typeof fetchImpl !== "function") {
      throw new Error("Fetch is not available in this browser.");
    }

    const url = buildAvailabilityUrl(baseUrl, medicine, district);
    let response;
    try {
      response = await fetchImpl(url, {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "omit",
        cache: "no-store"
      });
    } catch (_error) {
      throw new Error("Unable to reach the MediReach API.");
    }

    if (!response || !response.ok) {
      const code = response && Number.isInteger(response.status) ? response.status : "unknown";
      throw new Error("MediReach API request failed (HTTP " + code + ").");
    }

    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("MediReach API returned invalid JSON.");
    }
    return validateAvailabilityRecords(payload);
  }

  return {
    normalizeApiBase,
    getApiBaseFromDocument,
    buildAvailabilityUrl,
    validateAvailabilityRecords,
    fetchAvailability
  };
});

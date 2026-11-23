(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MediReachFreshness = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const HOUR_MS = 60 * 60 * 1000;
  const CLOCK_SKEW_MS = 5 * 60 * 1000;

  function parseVerifiedAt(value) {
    if (typeof value !== "string" || !/(Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
    const timestamp = Date.parse(value);
    return Number.isFinite(timestamp) ? timestamp : null;
  }

  function getFreshness(verifiedAt, nowMs = Date.now()) {
    const timestamp = parseVerifiedAt(verifiedAt);
    if (timestamp === null || !Number.isFinite(nowMs)) {
      return { key: "confirm", ageMs: null };
    }

    const delta = nowMs - timestamp;
    if (delta < -CLOCK_SKEW_MS) {
      return { key: "confirm", ageMs: null };
    }

    const ageMs = Math.max(0, delta);
    if (ageMs <= 24 * HOUR_MS) return { key: "recent", ageMs };
    if (ageMs <= 72 * HOUR_MS) return { key: "confirm", ageMs };
    return { key: "outdated", ageMs };
  }

  function formatVerifiedAt(value, locale = "en-IN") {
    const timestamp = parseVerifiedAt(value);
    if (timestamp === null) return null;
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short"
    }).format(new Date(timestamp));
  }

  return { parseVerifiedAt, getFreshness, formatVerifiedAt };
});

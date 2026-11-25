const test = require("node:test");
const assert = require("node:assert/strict");

const freshness = require("../freshness.js");
const api = require("../api.js");
const locales = require("../locales.js");

const HOUR = 60 * 60 * 1000;
const now = Date.parse("2026-11-23T06:30:00.000Z");

test("freshness is recently verified through the 24-hour boundary", () => {
  assert.equal(freshness.getFreshness(new Date(now - 24 * HOUR).toISOString(), now).key, "recent");
  assert.equal(freshness.getFreshness(new Date(now - 24 * HOUR - 1).toISOString(), now).key, "confirm");
});

test("freshness needs confirmation through the 72-hour boundary", () => {
  assert.equal(freshness.getFreshness(new Date(now - 72 * HOUR).toISOString(), now).key, "confirm");
  assert.equal(freshness.getFreshness(new Date(now - 72 * HOUR - 1).toISOString(), now).key, "outdated");
});

test("invalid, timezone-less and materially future timestamps are never called recent", () => {
  assert.equal(freshness.getFreshness("not-a-date", now).key, "confirm");
  assert.equal(freshness.getFreshness("2026-11-23T06:00:00", now).key, "confirm");
  assert.equal(freshness.getFreshness("2026-11-23T07:00:00.000Z", now).key, "confirm");
});

test("a small clock skew does not make a record look stale", () => {
  assert.equal(freshness.getFreshness("2026-11-23T06:32:00.000Z", now).key, "recent");
});

test("verification timestamps are formatted safely", () => {
  assert.equal(freshness.formatVerifiedAt("bad-date"), null);
  assert.equal(typeof freshness.formatVerifiedAt("2026-11-23T06:00:00.000Z", "en-IN"), "string");
});

test("blank API configuration selects demo mode", () => {
  assert.deepEqual(api.normalizeApiBase("   "), { configured: false, url: null, error: null });
});

test("remote API URLs require HTTPS and must not contain credentials", () => {
  assert.equal(api.normalizeApiBase("https://api.example.org/").url, "https://api.example.org");
  assert.equal(api.normalizeApiBase("http://localhost:8000").url, "http://localhost:8000");
  assert.ok(api.normalizeApiBase("http://api.example.org").error);
  assert.ok(api.normalizeApiBase("https://user:pass@api.example.org").error);
  assert.ok(api.normalizeApiBase("https://api.example.org/v1").error);
});

test("availability URL safely encodes medicine and district parameters", () => {
  const url = new URL(api.buildAvailabilityUrl(
    "https://api.example.org/",
    "Paracetamol 500 mg",
    "Coimbatore & North"
  ));
  assert.equal(url.pathname, "/api/v1/availability");
  assert.equal(url.searchParams.get("medicine"), "Paracetamol 500 mg");
  assert.equal(url.searchParams.get("district"), "Coimbatore & North");
  assert.equal(url.searchParams.get("include_demo"), null);
});

test("availability API rejects malformed and unexpected records", () => {
  assert.deepEqual(api.validateAvailabilityRecords([]), []);
  assert.throws(() => api.validateAvailabilityRecords({}), /unexpected response/);
  assert.throws(() => api.validateAvailabilityRecords([{
    facility: { name: "Test", address: "Test address" },
    medicine: { name: "Test medicine" },
    status: "available",
    quantity: 2,
    verified_at: "2026-11-23T06:00:00Z",
    confidence: "Recently Verified"
  }]), /invalid record/);
});

test("availability fetch sends a read-only request without credentials", async () => {
  let captured;
  const records = [{
    facility: { id: 1, name: "Test facility", district: "Test", address: "Sample address" },
    medicine: { id: 1, name: "Paracetamol", strength: "500 mg", form: "tablet" },
    status: "available",
    quantity: 4,
    verified_at: "2026-11-23T06:00:00Z",
    confidence: "Recently Verified",
    is_demo: false
  }];
  const result = await api.fetchAvailability({
    baseUrl: "https://api.example.org",
    medicine: "Paracetamol",
    fetchImpl: async (url, options) => {
      captured = { url, options };
      return { ok: true, status: 200, json: async () => records };
    }
  });
  assert.equal(result.length, 1);
  assert.equal(captured.options.method, "GET");
  assert.equal(captured.options.credentials, "omit");
  assert.equal(captured.options.cache, "no-store");
  assert.equal(new URL(captured.url).searchParams.get("medicine"), "Paracetamol");
});

test("API failures are surfaced instead of silently falling back to demo data", async () => {
  await assert.rejects(
    api.fetchAvailability({
      baseUrl: "https://api.example.org",
      medicine: "Paracetamol",
      fetchImpl: async () => ({ ok: false, status: 503 })
    }),
    /HTTP 503/
  );
  await assert.rejects(
    api.fetchAvailability({
      baseUrl: "https://api.example.org",
      medicine: "Paracetamol",
      fetchImpl: async () => { throw new Error("network down"); }
    }),
    /Unable to reach/
  );
});

test("English and Tamil translations contain the required interface labels", () => {
  const required = [
    "heroTitle", "medicineLabel", "districtLabel", "searchButton",
    "loading", "searchError", "noResults", "lastVerified",
    "freshnessRecent", "freshnessConfirm", "freshnessOutdated",
    "disclaimerText", "switchLanguage"
  ];
  for (const language of ["en", "ta"]) {
    const dictionary = locales.getLocale(language);
    for (const key of required) {
      assert.equal(typeof dictionary[key], "string", language + " missing " + key);
      assert.ok(dictionary[key].length > 0, language + " empty " + key);
    }
  }
  assert.equal(locales.getLocale("unknown").heroTitle, locales.getLocale("en").heroTitle);
});


test("availability request aborts after its timeout and reports a retryable message", async () => {
  await assert.rejects(
    api.fetchAvailability({
      baseUrl: "https://api.example.org",
      medicine: "Paracetamol",
      timeoutMs: 10,
      fetchImpl: (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("aborted")), {
          once: true
        });
      })
    }),
    /request timed out/
  );
});


test("availability timeout remains active while response JSON is being read", async () => {
  await assert.rejects(
    api.fetchAvailability({
      baseUrl: "https://api.example.org",
      medicine: "Paracetamol",
      timeoutMs: 10,
      fetchImpl: async (_url, options) => ({
        ok: true,
        status: 200,
        json: () => new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () => reject(new Error("body aborted")), {
            once: true
          });
        })
      })
    }),
    /request timed out/
  );
});

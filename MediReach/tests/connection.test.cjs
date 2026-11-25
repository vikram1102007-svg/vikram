const test = require("node:test");
const assert = require("node:assert/strict");
const connection = require("../connection.js");
const api = require("../api.js");

test("readiness check requests the database-ready endpoint without credentials or cache", async () => {
  let captured;
  const result = await connection.checkApiReadiness({
    baseUrl: "https://api.example.org",
    api,
    fetchImpl: async (url, options) => {
      captured = { url, options };
      return { ok: true, status: 200, json: async () => ({ status: "ready" }) };
    }
  });
  assert.deepEqual(result, { ready: true });
  assert.equal(captured.url, "https://api.example.org/health/ready");
  assert.equal(captured.options.method, "GET");
  assert.equal(captured.options.credentials, "omit");
  assert.equal(captured.options.cache, "no-store");
});

test("readiness check fails closed for unhealthy, malformed and non-OK responses", async () => {
  await assert.rejects(connection.checkApiReadiness({
    baseUrl: "https://api.example.org",
    api,
    fetchImpl: async () => ({ ok: true, json: async () => ({ status: "starting" }) })
  }), /not ready/);
  await assert.rejects(connection.checkApiReadiness({
    baseUrl: "https://api.example.org",
    api,
    fetchImpl: async () => ({ ok: false, status: 503 })
  }), /failed/);
  await assert.rejects(connection.checkApiReadiness({
    baseUrl: "https://api.example.org",
    api,
    fetchImpl: async () => ({ ok: true, json: async () => { throw new Error("invalid"); } })
  }), /invalid/);
});

test("readiness check rejects invalid API configuration", async () => {
  await assert.rejects(connection.checkApiReadiness({
    baseUrl: "http://api.example.org",
    api,
    fetchImpl: async () => { throw new Error("should not run"); }
  }), /HTTPS/);
});

test("readiness check aborts on timeout", async () => {
  await assert.rejects(connection.checkApiReadiness({
    baseUrl: "https://api.example.org",
    api,
    timeoutMs: 10,
    fetchImpl: (_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    })
  }), /timed out/);
});

test("connection messages are available in English and Tamil", () => {
  for (const language of ["en", "ta"]) {
    assert.ok(connection.getCopy(language, "checking").length > 0);
    assert.ok(connection.getCopy(language, "ready").length > 0);
    assert.ok(connection.getCopy(language, "unavailable").length > 0);
    assert.ok(connection.getCopy(language, "retry").length > 0);
  }
  assert.equal(connection.getCopy("unknown", "ready"), connection.getCopy("en", "ready"));
});

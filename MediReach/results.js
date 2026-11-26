(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MediReachResults = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function freshnessKey(record, freshnessApi, nowMs) {
    if (!freshnessApi || typeof freshnessApi.getFreshness !== "function") return "confirm";
    return freshnessApi.getFreshness(record && record.verified_at, nowMs).key;
  }

  function timestamp(record, freshnessApi) {
    if (!freshnessApi || typeof freshnessApi.parseVerifiedAt !== "function") return null;
    return freshnessApi.parseVerifiedAt(record && record.verified_at);
  }

  function filterAndSort(records, filters = {}, freshnessApi) {
    if (!Array.isArray(records)) return [];
    const status = filters.status || "all";
    const freshness = filters.freshness || "all";
    const sort = filters.sort || "newest";
    const nowMs = Number.isFinite(filters.nowMs) ? filters.nowMs : undefined;

    return records
      .map((record, index) => ({ record, index }))
      .filter(({ record }) => {
        if (status !== "all" && record.status !== status) return false;
        if (freshness !== "all" && freshnessKey(record, freshnessApi, nowMs) !== freshness) return false;
        return true;
      })
      .sort((left, right) => {
        const leftTime = timestamp(left.record, freshnessApi);
        const rightTime = timestamp(right.record, freshnessApi);
        if (leftTime === null && rightTime !== null) return 1;
        if (rightTime === null && leftTime !== null) return -1;
        if (leftTime === null && rightTime === null) return left.index - right.index;
        const delta = sort === "oldest" ? leftTime - rightTime : rightTime - leftTime;
        return delta || left.index - right.index;
      })
      .map(({ record }) => record);
  }

  return { filterAndSort };
});

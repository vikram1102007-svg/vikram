(function () {
  "use strict";

  const demoFacilities = [
    {
      name: "Sample Primary Health Centre — Lakeview",
      district: "Demo District",
      address: "12 Sample Road, Demo Nagar, Demo District, Tamil Nadu",
      verifiedAt: "2026-11-23T05:30:00.000Z",
      stock: {
        "paracetamol 500 mg": "available",
        "ors sachet": "available",
        "cetirizine 10 mg": "low_stock",
        "metformin 500 mg": "not_reported"
      }
    },
    {
      name: "Sample Urban Health Centre — Central",
      district: "Demo District",
      address: "4 Example Street, Demo Ward, Demo District, Tamil Nadu",
      verifiedAt: "2026-11-22T08:00:00.000Z",
      stock: {
        "paracetamol 500 mg": "available",
        "ors sachet": "low_stock",
        "cetirizine 10 mg": "available",
        "metformin 500 mg": "available"
      }
    },
    {
      name: "Sample Community Health Centre — Riverside",
      district: "Demo District",
      address: "8 Fictional Avenue, Demo District, Tamil Nadu",
      verifiedAt: "2026-11-20T05:30:00.000Z",
      stock: {
        "paracetamol 500 mg": "not_reported",
        "ors sachet": "available",
        "cetirizine 10 mg": "not_reported",
        "metformin 500 mg": "low_stock"
      }
    }
  ];

  const medicineDetails = {
    "paracetamol 500 mg": { name: "Paracetamol", strength: "500 mg" },
    "ors sachet": { name: "ORS", strength: "sachet" },
    "cetirizine 10 mg": { name: "Cetirizine", strength: "10 mg" },
    "metformin 500 mg": { name: "Metformin", strength: "500 mg" }
  };

  const elements = {
    form: document.getElementById("search-form"),
    medicine: document.getElementById("medicine"),
    district: document.getElementById("district"),
    searchButton: document.getElementById("search-button"),
    languageToggle: document.getElementById("language-toggle"),
    modeNote: document.getElementById("mode-note"),
    safetyTitle: document.getElementById("safety-title"),
    safetyText: document.getElementById("safety-text"),
    footer: document.getElementById("app-footer"),
    searchStatus: document.getElementById("search-status"),
    results: document.getElementById("results")
  };

  const apiConfig = window.MediReachApi.normalizeApiBase(
    window.MediReachApi.getApiBaseFromDocument(document)
  );
  let language = "en";
  let lastRecords = null;
  let lastErrorKey = null;
  let searched = false;

  function messages() {
    return window.MediReachLocales.getLocale(language);
  }

  function applyTranslations() {
    const dictionary = messages();
    document.documentElement.lang = language;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.getAttribute("data-i18n");
      if (dictionary[key]) element.textContent = dictionary[key];
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      const key = element.getAttribute("data-i18n-placeholder");
      if (dictionary[key]) element.setAttribute("placeholder", dictionary[key]);
    });
    elements.medicine.placeholder = dictionary.medicinePlaceholder;
    elements.district.placeholder = dictionary.districtPlaceholder;
    elements.languageToggle.textContent = dictionary.switchLanguage;
    elements.languageToggle.setAttribute(
      "aria-label",
      language === "en" ? "Switch to Tamil" : "ஆங்கிலத்திற்கு மாற்றவும்"
    );
    updateModeNote();
  }

  function updateModeNote() {
    const dictionary = messages();
    if (apiConfig.error) {
      elements.modeNote.textContent = dictionary.modeConfigError;
      elements.modeNote.className = "mode-note mode-note--warning";
    } else if (apiConfig.configured) {
      elements.modeNote.textContent = dictionary.modeApi;
      elements.modeNote.className = "mode-note mode-note--info";
    } else {
      elements.modeNote.textContent = dictionary.modeDemo;
      elements.modeNote.className = "mode-note mode-note--warning";
    }

    const mode = apiConfig.error ? "configError" : apiConfig.configured ? "api" : "demo";
    const safety = window.MediReachSafety.getSafetyNotice(language, mode);
    elements.safetyTitle.textContent = safety.title;
    elements.safetyText.textContent = safety.text;
    elements.footer.textContent = safety.footer;
  }

  function setBusy(isBusy) {
    elements.results.setAttribute("aria-busy", String(isBusy));
    elements.searchButton.disabled = isBusy;
  }

  function addTextElement(parent, tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  function showMessage(message, className = "empty-message") {
    elements.results.replaceChildren();
    addTextElement(elements.results, "p", className, message);
  }

  function freshnessText(key) {
    const dictionary = messages();
    const labels = {
      recent: dictionary.freshnessRecent,
      confirm: dictionary.freshnessConfirm,
      outdated: dictionary.freshnessOutdated
    };
    return labels[key] || dictionary.freshnessConfirm;
  }

  function stockText(status) {
    const dictionary = messages();
    const labels = {
      available: dictionary.stockAvailable,
      low_stock: dictionary.stockLow,
      unavailable: dictionary.stockUnavailable,
      not_reported: dictionary.stockNotReported
    };
    return labels[status] || dictionary.stockNotReported;
  }

  function renderRecord(record) {
    const dictionary = messages();
    const card = document.createElement("article");
    card.className = "facility-card";

    const headingRow = document.createElement("div");
    headingRow.className = "card-heading";
    addTextElement(headingRow, "h3", "facility-name", record.facility.name);
    if (record.is_demo) {
      addTextElement(headingRow, "span", "demo-tag", dictionary.demoTag);
    }
    card.appendChild(headingRow);

    addTextElement(card, "p", "facility-address", record.facility.address);

    const medicineName = record.medicine.name +
      (record.medicine.strength ? " · " + record.medicine.strength : "");
    addTextElement(card, "p", "record-medicine", dictionary.medicine + ": " + medicineName);
    addTextElement(
      card,
      "p",
      "record-stock",
      dictionary.stockStatus + ": " + stockText(record.status)
    );

    if (Number.isInteger(record.quantity)) {
      addTextElement(
        card,
        "p",
        "record-quantity",
        dictionary.quantity + ": " + String(record.quantity)
      );
    }

    const freshness = window.MediReachFreshness.getFreshness(record.verified_at);
    const freshnessRow = document.createElement("p");
    freshnessRow.className = "freshness-row";
    const badge = document.createElement("span");
    badge.className = "freshness-badge freshness-badge--" + freshness.key;
    badge.textContent = freshnessText(freshness.key);
    freshnessRow.appendChild(badge);
    card.appendChild(freshnessRow);

    const verifiedText = window.MediReachFreshness.formatVerifiedAt(
      record.verified_at,
      language === "ta" ? "ta-IN" : "en-IN"
    );
    const verifiedRow = document.createElement("p");
    verifiedRow.className = "verified-at";
    verifiedRow.appendChild(document.createTextNode(dictionary.lastVerified + ": "));
    if (verifiedText) {
      const time = document.createElement("time");
      time.dateTime = record.verified_at;
      time.textContent = verifiedText;
      verifiedRow.appendChild(time);
    } else {
      verifiedRow.appendChild(document.createTextNode(dictionary.timeUnavailable));
    }
    card.appendChild(verifiedRow);

    elements.results.appendChild(card);
  }

  function renderRecords(records) {
    const dictionary = messages();
    elements.results.replaceChildren();
    if (!records.length) {
      elements.searchStatus.textContent = "";
      showMessage(dictionary.noResults);
      return;
    }
    elements.searchStatus.textContent = dictionary.resultsCount.replace("{count}", String(records.length));
    records.forEach(renderRecord);
  }

  function searchDemo(medicineQuery, districtQuery) {
    const medicineNeedle = medicineQuery.trim().toLowerCase();
    const districtNeedle = districtQuery.trim().toLowerCase();
    return demoFacilities.flatMap((facility) => {
      if (districtNeedle && !facility.district.toLowerCase().includes(districtNeedle)) {
        return [];
      }
      return Object.entries(facility.stock)
        .filter(([medicineKey]) => medicineKey.includes(medicineNeedle))
        .map(([medicineKey, status]) => ({
          facility: {
            name: facility.name,
            district: facility.district,
            address: facility.address
          },
          medicine: medicineDetails[medicineKey],
          status,
          quantity: null,
          verified_at: facility.verifiedAt,
          confidence: "Needs Confirmation",
          is_demo: true
        }));
    });
  }

  async function runSearch() {
    const dictionary = messages();
    const medicine = elements.medicine.value.trim();
    const district = elements.district.value.trim();

    if (medicine.length < 2) {
      elements.medicine.setCustomValidity("Enter at least two characters.");
      elements.medicine.reportValidity();
      return;
    }
    elements.medicine.setCustomValidity("");

    if (apiConfig.error) {
      showError("apiConfigError");
      return;
    }

    searched = true;
    lastErrorKey = null;
    elements.searchStatus.textContent = dictionary.loading;
    elements.results.replaceChildren();
    setBusy(true);

    try {
      const records = apiConfig.configured
        ? await window.MediReachApi.fetchAvailability({
            baseUrl: apiConfig.url,
            medicine,
            district
          })
        : searchDemo(medicine, district);
      lastRecords = records;
      renderRecords(records);
    } catch (_error) {
      showError("searchError");
    } finally {
      setBusy(false);
    }
  }

  function showError(messageKey) {
    const message = messages()[messageKey];
    lastErrorKey = messageKey;
    lastRecords = null;
    searched = true;
    elements.searchStatus.textContent = message;
    showMessage(message, "error-message");
  }

  function renderInitialState() {
    if (!searched) {
      elements.searchStatus.textContent = "";
      showMessage(messages().emptyInitial);
    }
  }

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    runSearch();
  });

  document.querySelectorAll("[data-q]").forEach((button) => {
    button.addEventListener("click", () => {
      elements.medicine.value = button.getAttribute("data-q");
      elements.form.requestSubmit();
    });
  });

  elements.languageToggle.addEventListener("click", () => {
    language = language === "en" ? "ta" : "en";
    applyTranslations();
    if (lastErrorKey) {
      showError(lastErrorKey);
    } else if (searched && lastRecords) {
      renderRecords(lastRecords);
    } else {
      renderInitialState();
    }
  });

  applyTranslations();
  renderInitialState();
})();

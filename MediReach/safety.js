(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MediReachSafety = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const copy = {
    en: {
      demo: {
        title: "Important safety notice",
        text: "This demo uses fictional facilities, addresses, medicine stock and verification times. It is not connected to government inventory systems or live facility records. Do not rely on sample data for healthcare or travel decisions. Availability can change. MediReach does not diagnose, prescribe or recommend medicine substitutions. Do not enter personal health information.",
        footer: "MediReach · Public-health information demo"
      },
      api: {
        title: "Important safety notice",
        text: "Availability records are requested from the configured API. Records may be incomplete or outdated; check each last-verified time and contact the facility before travelling. An API response does not guarantee stock. MediReach does not diagnose, prescribe or recommend medicine substitutions. Do not enter personal health information.",
        footer: "MediReach · Availability information"
      },
      configError: {
        title: "API configuration required",
        text: "The configured API address is invalid. No inventory is displayed until the configuration is corrected. Fictional demo data is not substituted for a configured API. Do not enter personal health information.",
        footer: "MediReach · API setup required"
      }
    },
    ta: {
      demo: {
        title: "முக்கிய பாதுகாப்பு அறிவிப்பு",
        text: "இந்தச் செயல்விளக்கத்தில் கற்பனையான மையங்கள், முகவரிகள், மருந்து இருப்பு மற்றும் சரிபார்ப்பு நேரங்கள் மட்டுமே உள்ளன. இது அரசு இருப்பு அமைப்புகளுடனோ நேரடி மையப் பதிவுகளுடனோ இணைக்கப்படவில்லை. மருத்துவ அல்லது பயண முடிவுகளுக்கு மாதிரித் தரவை நம்ப வேண்டாம். இருப்பு மாறக்கூடும். MediReach நோயறிதல், மருந்து பரிந்துரை அல்லது மாற்று மருந்து பரிந்துரை வழங்காது. தனிப்பட்ட சுகாதாரத் தகவல்களை உள்ளிட வேண்டாம்.",
        footer: "MediReach · பொது சுகாதாரத் தகவல் செயல்விளக்கம்"
      },
      api: {
        title: "முக்கிய பாதுகாப்பு அறிவிப்பு",
        text: "அமைக்கப்பட்ட API-யிலிருந்து இருப்புப் பதிவுகள் பெறப்படுகின்றன. பதிவுகள் முழுமையற்றதாகவோ பழையதாகவோ இருக்கலாம்; கடைசியாகச் சரிபார்த்த நேரத்தைப் பார்த்து, பயணத்திற்கு முன் மையத்தைத் தொடர்புகொள்ளுங்கள். API பதில் இருப்பை உறுதிப்படுத்தாது. MediReach நோயறிதல், மருந்து பரிந்துரை அல்லது மாற்று மருந்து பரிந்துரை வழங்காது. தனிப்பட்ட சுகாதாரத் தகவல்களை உள்ளிட வேண்டாம்.",
        footer: "MediReach · இருப்புத் தகவல்"
      },
      configError: {
        title: "API அமைப்பு தேவை",
        text: "அமைக்கப்பட்ட API முகவரி தவறானது. அமைப்பைச் சரிசெய்யும் வரை இருப்புத் தகவல் காட்டப்படாது. அமைக்கப்பட்ட API-க்கு பதிலாக கற்பனை மாதிரித் தரவு காட்டப்படாது. தனிப்பட்ட சுகாதாரத் தகவல்களை உள்ளிட வேண்டாம்.",
        footer: "MediReach · API அமைப்பு தேவை"
      }
    }
  };

  function getSafetyNotice(language, mode) {
    const dictionary = copy[language] || copy.en;
    return dictionary[mode] || dictionary.demo;
  }

  return { getSafetyNotice };
});

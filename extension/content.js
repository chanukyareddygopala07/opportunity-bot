/* Aawara Autofill — content script.
 * Matches resume fields to form fields via name/placeholder/label/text
 * heuristics. Fills ONLY empty fields; never overwrites typed answers.
 * No data is sent anywhere from the page.
 */
(() => {
  const FLAG = "__aawaraAutofillActive";
  if (window[FLAG]) return;
  window[FLAG] = true;

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== "AAWARA_FILL") return;
    const filled = fillForm(msg.resume || {});
    const el = document.createElement("div");
    el.textContent = `Aawara Autofill: ${filled.count} field(s) filled.`;
    el.style.cssText = [
      "position:fixed;bottom:16px;right:16px;z-index:99999;",
      "background:#10131a;color:#e6e9ef;padding:10px 14px;border-radius:8px;",
      "font:13px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.35);",
    ].join("");
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
    sendResponse(filled);
  });

  function valueFor(resume, keys) {
    for (const key of keys) {
      const v = resume[key];
      if (v !== undefined && v !== null && String(v).trim() !== "") {
        return String(v);
      }
    }
    return null;
  }

  function contactValue(resume, key) {
    const contact = resume.contact || {};
    const v = contact[key];
    return v ? String(v) : null;
  }

  function buildMap(resume) {
    return {
      name: valueFor(resume, ["name"]),
      email: contactValue(resume, "email") || valueFor(resume, ["email"]),
      phone: contactValue(resume, "phone"),
      linkedin: contactValue(resume, "linkedin"),
      github: contactValue(resume, "github"),
      website: contactValue(resume, "website"),
      education: valueFor(resume, ["education"]),
      skills: (resume.skills || []).join(", "),
      interests: (resume.interests || []).join(", "),
    };
  }

  function fillForm(resume) {
    const map = buildMap(resume);
    const fields = Array.from(document.querySelectorAll("input, textarea, select"));
    let filled = 0;

    const setField = (field, value) => {
      if (!field || !value) return false;
      if (field.type === "checkbox" || field.type === "radio") return false;
      if (field.value && field.value.trim() !== "") return false;
      const proto = field instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) {
        desc.set.call(field, value);
      } else {
        field.value = value;
      }
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    };

    for (const field of fields) {
      const ctx = context(field);
      const value = pick(map, ctx);
      if (value && setField(field, value)) {
        filled += 1;
      }
    }
    return { count: filled };
  }

  function context(field) {
    const bits = [];
    const add = (s) => { if (s) bits.push(String(s).toLowerCase()); };
    add(field.getAttribute("name"));
    add(field.getAttribute("id"));
    add(field.getAttribute("placeholder"));
    add(field.getAttribute("aria-label"));
    add(field.getAttribute("autocomplete"));
    const label = field.closest("label");
    if (label) add(label.textContent);
    const wrap = field.closest("div");
    if (wrap && wrap.textContent && wrap.textContent.length < 80) add(wrap.textContent);
    add(field.getAttribute("data-testid"));
    return bits.join(" ");
  }

  function pick(map, ctx) {
    const has = (...keys) => keys.some((k) => ctx.includes(k));
    if (has("email", "e-mail", "e-mail address", "email address")) return map.email;
    if (has("first name", "firstname", "given-name")) return first(map.name);
    if (has("last name", "lastname", "family-name")) return last(map.name);
    if (has("full name", "your name", "name", "applicant name")) return map.name;
    if (has("phone", "mobile", "tel")) return map.phone;
    if (has("linkedin", "linked-in")) return map.linkedin;
    if (has("github", "git hub", "github url", "github profile")) return map.github;
    if (has("portfolio", "website", "personal website", "personal site", "url", "profile url")) {
      return map.github || map.linkedin || map.website;
    }
    if (has("education", "degree", "school", "university", "college", "institution")) {
      return educationText(map.education);
    }
    if (has("skills", "technologies", "tech stack", "programming languages")) return map.skills;
    if (has("interest", "areas of interest")) return map.interests;
    return null;
  }

  function first(name) {
    return name ? name.trim().split(/\s+/)[0] : null;
  }

  function last(name) {
    const parts = name ? name.trim().split(/\s+/) : [];
    return parts.length > 1 ? parts.slice(1).join(" ") : null;
  }

  function educationText(edu) {
    if (!edu) return null;
    if (typeof edu === "string") return edu;
    if (Array.isArray(edu)) {
      const text = edu
        .map((e) => (typeof e === "string" ? e : (e.title || e.school || "")))
        .filter(Boolean)
        .join("; ");
      return text || null;
    }
    return edu.title || null;
  }
})();
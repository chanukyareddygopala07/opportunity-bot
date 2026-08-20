/* Aawara Autofill — background service worker.
 * Fetches the student's resume from their own Aawara server using the
 * per-user API token, then asks the content script to fill the form.
 */
const STORAGE_KEY = "aawaraAutofill";

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get([STORAGE_KEY]).then((stored) => {
    if (!stored[STORAGE_KEY]) {
      chrome.storage.local.set({ [STORAGE_KEY]: { serverUrl: "", token: "" } });
    }
  });
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "AAWARA_FILL_TAB") {
    fillTab(msg.tabId).then(sendResponse);
    return true;
  }
  return false;
});

async function fillTab(tabId) {
  const stored = await chrome.storage.local.get([STORAGE_KEY]);
  const config = stored[STORAGE_KEY] || {};
  if (!config.serverUrl || !config.token) {
    return { error: "not configured" };
  }
  const resume = await fetchResume(config);
  if (!resume) {
    return { error: "could not reach Aawara server (check server URL + token)" };
  }
  try {
    const resp = await chrome.tabs.sendMessage(tabId, { type: "AAWARA_FILL", resume });
    return resp || { count: 0 };
  } catch (e) {
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
      const resp = await chrome.tabs.sendMessage(tabId, { type: "AAWARA_FILL", resume });
      return resp || { count: 0 };
    } catch (e2) {
      return { error: "cannot run on this page" };
    }
  }
}

async function fetchResume(config) {
  const base = String(config.serverUrl || "").replace(/\/+$/, "");
  try {
    const res = await fetch(`${base}/api/autofill/resume`, {
      headers: { Authorization: `Bearer ${config.token}` },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}
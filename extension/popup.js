/* Aawara Autofill — popup. */
const STORAGE_KEY = "aawaraAutofill";

const status = document.getElementById("status");
const fillBtn = document.getElementById("fill");

chrome.storage.local.get([STORAGE_KEY]).then((stored) => {
  const config = stored[STORAGE_KEY] || {};
  if (config.serverUrl && config.token) {
    status.textContent = `Server: ${config.serverUrl}`;
    status.classList.add("ok");
    fillBtn.style.display = "block";
  } else {
    status.textContent = "Not configured — open options and add your Aawara server URL + API token.";
    fillBtn.style.display = "none";
  }
});

fillBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return;
  const resp = await chrome.runtime.sendMessage({ type: "AAWARA_FILL_TAB", tabId: tab.id });
  status.textContent = resp && resp.error
    ? `Failed: ${resp.error}`
    : resp
      ? `Filled ${resp.count || 0} field(s).`
      : "No form fields matched.";
  setTimeout(() => window.close(), 1500);
});

document.getElementById("options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});
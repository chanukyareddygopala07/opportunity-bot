/* Aawara Autofill — options page. */
const STORAGE_KEY = "aawaraAutofill";

const serverInput = document.getElementById("server");
const tokenInput = document.getElementById("token");
const saveBtn = document.getElementById("save");
const msg = document.getElementById("msg");

chrome.storage.local.get([STORAGE_KEY]).then((stored) => {
  const config = stored[STORAGE_KEY] || {};
  serverInput.value = config.serverUrl || "";
  tokenInput.value = config.token || "";
});

saveBtn.addEventListener("click", async () => {
  const serverUrl = serverInput.value.trim().replace(/\/+$/, "");
  const token = tokenInput.value.trim();
  if (!serverUrl || !token) {
    msg.textContent = "Both fields are required.";
    msg.className = "err";
    return;
  }
  await chrome.storage.local.set({ [STORAGE_KEY]: { serverUrl, token } });
  msg.textContent = "Saved. Open an application form and click the Aawara icon to fill it.";
  msg.className = "ok";
  setTimeout(() => { msg.textContent = ""; }, 4000);
});
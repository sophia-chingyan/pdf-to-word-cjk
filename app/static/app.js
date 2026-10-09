"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = {
  uploading: "上傳中", uploaded: "等待開始", queued: "排隊中", converting: "轉換中", paused: "已暫停",
  stopped: "已停止", done: "完成", failed: "失敗", needs_password: "需要密碼",
};
const LANG = { "zh-TW": "繁中", "zh-CN": "簡中", "ja-JP": "日文", "ko-KR": "韓文" };
const DIR = { h: "橫排", v: "直排" };

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (res.status === 401) { location.href = "/login"; throw new Error("401"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { toast(data.detail || "發生錯誤，請再試一次。"); throw new Error(data.detail || res.status); }
  return data;
}
const post = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
});

function fmtDate(ts) { return ts ? new Date(ts * 1000).toLocaleString("zh-TW", { hour12: false }) : ""; }
function fmtSize(b) {
  if (b >= 1073741824) return (b / 1073741824).toFixed(1) + " GB";
  return b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
}

function progressText(j) {
  if (j.status === "converting" || j.status === "paused") {
    return j.pages ? `第 ${j.progress_page} / ${j.pages} 頁` : "";
  }
  return "";
}

function passwordForm(j) {
  return `<div class="pw"><input type="password" id="pw-${j.id}" placeholder="PDF 密碼" autocomplete="off">
    <button class="btn small" data-act="password" data-id="${j.id}">解鎖</button></div>
    <p class="muted small">密碼只用於這次轉換，不會被儲存。</p>`;
}

async function jobAction(act, id) {
  if (act === "password") {
    const pw = $("pw-" + id).value;
    if (!pw) return;
    await post(`/api/jobs/${id}/password`, { password: pw });
    toast("已解鎖。");
  } else if (act === "delete") {
    await api(`/api/jobs/${id}`, { method: "DELETE" });
  } else if (act === "start") {
    await post(`/api/jobs/${id}/start`, currentSettings());
  } else if (act === "backup") {
    await post(`/api/jobs/${id}/backup`);
    toast("已送出到商業服務轉換。");
  } else {
    await post(`/api/jobs/${id}/${act}`);
    if (act === "retry") toast("已回到「轉換」頁，可以變更內容設定後重新開始。");
  }
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  e.preventDefault();
  b.disabled = true;
  jobAction(b.dataset.act, b.dataset.id).catch(() => {}).finally(() => { b.disabled = false; refresh(); });
});

let refresh = () => {};

/* ── Convert page ─────────────────────────────────────────────── */

function currentSettings() {
  const picker = $("lang-picker");
  if (!picker) return {};
  const choices = [...picker.querySelectorAll("input:checked")].map((i) => i.value);
  const fur = document.querySelector('input[name="furigana"]:checked');
  return { choices: choices.length ? choices : ["auto"], furigana: fur ? fur.value : "brackets" };
}

function syncPicker(changed) {
  const boxes = [...$("lang-picker").querySelectorAll("input")];
  const auto = boxes.find((b) => b.value === "auto");
  if (changed === auto && auto.checked) boxes.forEach((b) => { if (b !== auto) b.checked = false; });
  else if (changed && changed !== auto && changed.checked) auto.checked = false;
  if (!boxes.some((b) => b.checked)) auto.checked = true;
  const ja = boxes.some((b) => b.checked && (b.value.startsWith("ja_") || b.value === "auto"));
  $("furigana-picker").hidden = !ja;
}

function renderWaiting(list) {
  $("settings-card").hidden = list.length === 0;
  $("waiting").innerHTML = list.map((j) => `
    <div class="job">
      <div class="job-head"><span class="job-name">${esc(j.file_name)}</span>
        <span class="status">${STATUS[j.status]}${j.pages ? ` · ${j.pages} 頁` : ""} · ${fmtSize(j.size_bytes)}</span></div>
      ${j.status === "needs_password" ? passwordForm(j) : ""}
      <div class="actions">
        ${j.status === "uploaded" ? `<button class="btn small primary" data-act="start" data-id="${j.id}">開始轉換</button>` : ""}
        <button class="btn small danger" data-act="delete" data-id="${j.id}">刪除</button>
      </div>
    </div>`).join("");
}

function renderJobs(list) {
  if (!list.length) { $("jobs").innerHTML = '<p class="muted">目前沒有轉換中的檔案。</p>'; return; }
  $("jobs").innerHTML = list.map((j) => {
    const pct = j.status === "done" ? 100 : j.pages ? Math.round((100 * j.progress_page) / j.pages) : 0;
    const btn = (act, label, cls = "") => `<button class="btn small ${cls}" data-act="${act}" data-id="${j.id}">${label}</button>`;
    let actions = "";
    if (j.status === "queued" || j.status === "converting") actions = btn("pause", "暫停") + btn("stop", "停止");
    else if (j.status === "paused") actions = btn("start", "繼續", "primary") + btn("stop", "停止");
    else if (j.status === "stopped" || j.status === "failed") actions = btn("start", "重新開始", "primary") + btn("retry", "變更設定");
    else if (j.status === "done") actions = `<a class="btn small primary" href="/api/download/${j.id}/docx">下載 Word</a>` + btn("retry", "重試");
    actions += btn("delete", "刪除", "danger");
    return `<div class="job">
      <div class="job-head"><span class="job-name">${esc(j.file_name)}</span>
        <span class="status ${j.status}">${STATUS[j.status]} ${progressText(j)}</span></div>
      <div class="bar"><div style="width:${pct}%"></div></div>
      <div class="meta">${esc(j.settings_label || "")}</div>
      ${j.error ? `<div class="error">${esc(j.error)}</div>` : ""}
      ${j.status === "needs_password" ? passwordForm(j) : ""}
      <div class="actions">${actions}</div>
    </div>`;
  }).join("");
}

function initConvertPage() {
  const picker = $("lang-picker");
  picker.addEventListener("change", (e) => syncPicker(e.target));
  api("/api/settings/last").then((s) => {
    picker.querySelectorAll("input").forEach((b) => { b.checked = (s.choices || ["auto"]).includes(b.value); });
    const f = document.querySelector(`input[name="furigana"][value="${s.furigana || "brackets"}"]`);
    if (f) f.checked = true;
    syncPicker(null);
  }).catch(() => syncPicker(null));

  const drop = $("drop"), input = $("file-input");
  const send = (fileList) => [...fileList].forEach(uploadOne);
  input.addEventListener("change", () => { send(input.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => send(e.dataTransfer.files));

  $("start-all").addEventListener("click", async () => {
    const jobs = (await api("/api/jobs")).jobs.filter((j) => j.status === "uploaded");
    for (const j of jobs) await post(`/api/jobs/${j.id}/start`, currentSettings()).catch(() => {});
    refresh();
  });

  const recent = (j) => j.status !== "done" || Date.now() / 1000 - (j.finished_at || 0) < 3600;
  refresh = async () => {
    const { jobs } = await api("/api/jobs");
    renderWaiting(jobs.filter((j) => j.status === "uploaded" || (j.status === "needs_password" && !j.settings)));
    renderJobs(jobs.filter((j) => !["uploaded", "uploading"].includes(j.status)
      && !(j.status === "needs_password" && !j.settings) && recent(j)));
  };
  refresh();
  setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 2000);
}

/* The server only creates a job once the whole file has arrived, so while a file is
   on its way it exists only here. Show a row per upload, with progress and any error. */
let uploadsInFlight = 0;
window.addEventListener("beforeunload", (e) => { if (uploadsInFlight) e.preventDefault(); });

function uploadRow(file) {
  const el = document.createElement("div");
  el.className = "job";
  el.innerHTML = `<div class="job-head"><span class="job-name">${esc(file.name)}</span><span class="status"></span></div>
    <div class="bar"><div style="width:0%"></div></div>
    <div class="error" hidden></div>
    <div class="actions"><button type="button" class="btn small">取消</button></div>`;
  $("uploads").append(el);
  const status = el.querySelector(".status"), bar = el.querySelector(".bar"), fill = bar.firstElementChild;
  const err = el.querySelector(".error"), btn = el.querySelector("button");
  return {
    button: btn,
    remove: () => el.remove(),
    progress(loaded, total) {
      const pct = total ? Math.min(100, Math.floor((100 * loaded) / total)) : 0;
      fill.style.width = pct + "%";
      status.textContent = `上傳中 ${pct}% · ${fmtSize(loaded)} / ${fmtSize(total)}`;
    },
    processing() { fill.style.width = "100%"; status.textContent = "處理中…"; btn.hidden = true; },
    fail(msg) {
      status.textContent = "上傳失敗"; status.classList.add("failed");
      bar.hidden = true; err.textContent = msg; err.hidden = false;
      btn.hidden = false; btn.textContent = "關閉";
    },
  };
}

function uploadOne(file) {
  const row = uploadRow(file);
  let xhr = null;
  row.progress(0, file.size);
  row.button.addEventListener("click", () => (xhr && xhr.readyState !== 4 ? xhr.abort() : row.remove()));
  const maxBytes = Number($("drop").dataset.maxBytes) || 40 * 1024 * 1024;
  if (!file.name.toLowerCase().endsWith(".pdf")) return row.fail("只接受 PDF 檔案。");
  if (file.size > maxBytes) return row.fail(`檔案超過 ${Math.round(maxBytes / 1048576)} MB 上限。`);

  xhr = new XMLHttpRequest();
  uploadsInFlight++;
  const finish = () => { uploadsInFlight--; };
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) row.progress(e.loaded, e.total); };
  xhr.upload.onload = () => row.processing();
  xhr.onload = async () => {
    finish();
    if (xhr.status === 401) { location.href = "/login"; return; }
    if (xhr.status >= 200 && xhr.status < 300) {
      await refresh().catch(() => {});  // the file is listed before its progress row goes away
      row.remove();
      return;
    }
    let detail = "";
    try { detail = JSON.parse(xhr.responseText).detail; } catch (e) { /* not JSON */ }
    row.fail(typeof detail === "string" && detail ? detail : "發生錯誤，請再試一次。");
  };
  xhr.onerror = () => { finish(); row.fail("網路中斷，請再試一次。"); };
  xhr.onabort = () => { finish(); row.remove(); };
  const fd = new FormData();
  fd.append("file", file);
  xhr.open("POST", "/api/upload");
  xhr.send(fd);
}

/* ── Library page ─────────────────────────────────────────────── */

function confirmDelete(text) {
  return new Promise((resolve) => {
    const dlg = $("confirm");
    $("confirm-text").textContent = text;
    dlg.onclose = () => resolve(dlg.returnValue === "ok");
    dlg.showModal();
  });
}

function initLibraryPage(backup) {
  const selected = new Set();
  const openNotes = new Set();  // keep "轉換備註" open across refreshes
  $("library").addEventListener("toggle", (e) => {
    const d = e.target;
    if (d.tagName !== "DETAILS") return;
    d.open ? openNotes.add(d.dataset.id) : openNotes.delete(d.dataset.id);
  }, true);
  const updateSelection = () => {
    $("selection").textContent = `已選 ${selected.size} 個`;
    $("delete-selected").hidden = selected.size === 0;
  };
  refresh = async () => {
    const { jobs } = await api("/api/jobs");
    const list = jobs.filter((j) => j.status !== "uploading");
    [...selected].forEach((id) => { if (!list.some((j) => j.id === id)) selected.delete(id); });
    updateSelection();
    if (!list.length) { $("library").innerHTML = '<p class="muted">還沒有轉換紀錄。</p>'; return; }
    $("library").innerHTML = list.map((j) => {
      const langs = (j.languages || []).map((l) => LANG[l] || l).join("、");
      const dirs = (j.directions || []).map((d) => DIR[d] || d).join("、");
      const warn = (j.warnings || []);
      const a = [];
      if (j.has_result) a.push(`<a class="btn small primary" href="/api/download/${j.id}/docx">下載 Word</a>`);
      a.push(`<a class="btn small" href="/api/download/${j.id}/pdf">下載原始 PDF</a>`);
      if (j.has_api_result) a.push(`<a class="btn small" href="/api/download/${j.id}/api">下載商業服務版本</a>`);
      if (backup && ["done", "failed"].includes(j.status) && j.api_status !== "converting") {
        a.push(`<button class="btn small" data-act="backup" data-id="${j.id}">用商業服務轉換</button>`);
      }
      if (["done", "failed", "stopped"].includes(j.status)) a.push(`<button class="btn small" data-act="retry" data-id="${j.id}">重試</button>`);
      a.push(`<button class="btn small danger" data-del="${j.id}" data-name="${esc(j.file_name)}">刪除</button>`);
      const api = j.api_status === "converting" ? "商業服務轉換中…" : j.api_status === "failed" ? `商業服務失敗：${esc(j.api_error)}` : "";
      return `<div class="lib-row ${selected.has(j.id) ? "selected" : ""}">
        <input type="checkbox" class="pick" value="${j.id}" ${selected.has(j.id) ? "checked" : ""}>
        <div>
          <div class="job-head"><span class="job-name">${esc(j.file_name)}</span>
            <span class="status ${j.status}">${STATUS[j.status] || j.status} ${progressText(j)}</span></div>
          <div class="meta">${j.pages ? j.pages + " 頁 · " : ""}${fmtSize(j.size_bytes)} · ${fmtDate(j.created_at)}
            ${langs ? " · " + langs : ""}${dirs ? " · " + dirs : ""}</div>
          ${j.settings_label ? `<div class="meta">設定：${esc(j.settings_label)}</div>` : ""}
          ${j.error ? `<div class="error">${esc(j.error)}</div>` : ""}
          ${api ? `<div class="meta">${api}</div>` : ""}
          ${warn.length ? `<details data-id="${j.id}" ${openNotes.has(j.id) ? "open" : ""}><summary>轉換備註（${warn.length}）</summary><ul>${warn.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}
          <div class="actions">${a.join("")}</div>
        </div></div>`;
    }).join("");
    api("/api/storage").then((s) => {
      $("storage").textContent = `已使用 ${fmtSize(s.used_bytes)} · 剩餘 ${fmtSize(s.free_bytes)}`;
    }).catch(() => {});
  };
  $("library").addEventListener("change", (e) => {
    if (!e.target.classList.contains("pick")) return;
    e.target.checked ? selected.add(e.target.value) : selected.delete(e.target.value);
    e.target.closest(".lib-row").classList.toggle("selected", e.target.checked);
    updateSelection();
  });
  $("select-all").addEventListener("change", (e) => {
    document.querySelectorAll(".pick").forEach((cb) => {
      cb.checked = e.target.checked;
      e.target.checked ? selected.add(cb.value) : selected.delete(cb.value);
      cb.closest(".lib-row").classList.toggle("selected", cb.checked);
    });
    updateSelection();
  });
  $("library").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del]");
    if (!b) return;
    if (await confirmDelete(`確定刪除「${b.dataset.name}」？Word 檔與原始 PDF 都會被刪除。`)) {
      await api(`/api/jobs/${b.dataset.del}`, { method: "DELETE" }).catch(() => {});
      refresh();
    }
  });
  $("delete-selected").addEventListener("click", async () => {
    if (await confirmDelete(`確定刪除所選的 ${selected.size} 個檔案？`)) {
      await post("/api/jobs/delete", { ids: [...selected] }).catch(() => {});
      selected.clear();
      refresh();
    }
  });
  $("delete-all").addEventListener("click", async () => {
    if (await confirmDelete("確定刪除檔案庫中的所有檔案？這個動作無法復原。")) {
      await post("/api/jobs/delete-all").catch(() => {});
      selected.clear();
      refresh();
    }
  });
  refresh();
  setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 4000);
}

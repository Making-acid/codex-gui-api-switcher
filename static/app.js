"use strict";

/* ---------------- 基础 ---------------- */

const AUTH_TOKEN = new URLSearchParams(location.search).get("token") || "";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path, options = {}) {
  const opts = { method: options.method || "GET", headers: {} };
  if (AUTH_TOKEN) opts.headers["X-Auth-Token"] = AUTH_TOKEN;
  if (options.body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(options.body);
  }
  const resp = await fetch(path, opts);
  let data = null;
  try { data = await resp.json(); } catch (_) { data = {}; }
  if (!resp.ok && !data.message) data.message = `HTTP ${resp.status}`;
  if (!data.ok && data.message) throw new Error(data.message);
  return data;
}

let toastTimer = null;
function toast(message, kind = "") {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}

function modalConfirm(title, bodyHtml, okText = "确定") {
  return new Promise((resolve) => {
    $("#modal-title").textContent = title;
    $("#modal-body").innerHTML = bodyHtml;
    $("#modal-ok").textContent = okText;
    $("#modal").classList.remove("hidden");
    const done = (val) => {
      $("#modal").classList.add("hidden");
      $("#modal-ok").onclick = null;
      $("#modal-cancel").onclick = null;
      resolve(val);
    };
    $("#modal-ok").onclick = () => done(true);
    $("#modal-cancel").onclick = () => done(false);
  });
}

/* ---------------- 状态 ---------------- */

let STATE = {
  config: null,        // /api/config
  templates: [],       // /api/templates
  backups: [],         // /api/backups
  defaults: [],        // /api/defaults
  env: null,           // /api/env
  currentTemplate: null,
};

async function refreshAll() {
  const [cfg, templates, backups, defaults, env] = await Promise.all([
    api("/api/config"),
    api("/api/templates"),
    api("/api/backups"),
    api("/api/defaults"),
    api("/api/env?scope=all"),
  ]);
  STATE.config = cfg.config;
  STATE.templates = templates.templates;
  STATE.backups = backups.backups;
  STATE.defaults = defaults.defaults;
  STATE.env = env.env;
  renderStatus();
  renderTemplateGrid();
  renderProviders();
  renderBackups();
  renderDefaults();
  renderEnv();
  fillTestFromConfig();
}

function renderStatus() {
  const c = STATE.config;
  const active = c.model_provider || (c.openai_base_url ? "openai (openai_base_url)" : "未设置");
  $("#status-config").textContent =
    `config: ${c.path}${c.exists ? "" : "（不存在）"} ｜ 当前 provider: ${active} ｜ 模型: ${c.model || "未设置"}`;
}

/* ---------------- Tab 切换 ---------------- */

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".tab-view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
  });
});

/* ---------------- 快速切换 ---------------- */

function renderTemplateGrid() {
  const grid = $("#template-grid");
  grid.innerHTML = "";
  STATE.templates.forEach((t) => {
    const isActive = isTemplateActive(t);
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="c-name">${esc(t.name)}${isActive ? '<span class="c-active">当前</span>' : ""}</div>
      <div class="c-desc">${esc(t.base_url || "需填写地址")}</div>
      <span class="c-tag">${t.kind === "oss" ? "本地" : "远程"} ｜ ${esc(t.default_env_key || "无需 key")}</span>`;
    card.addEventListener("click", () => selectTemplate(t));
    grid.appendChild(card);
  });
}

function isTemplateActive(t) {
  const c = STATE.config;
  if (t.kind === "oss") return c.oss_provider === (t.oss_id || t.id);
  if (t.kind === "custom") {
    const pid = t.provider_id || t.id;
    return c.model_provider === pid && c.model_providers && !!c.model_providers[pid];
  }
  return false;
}

function selectTemplate(t) {
  STATE.currentTemplate = t;
  $("#quick-form").classList.remove("hidden");
  $("#quick-form-title").textContent = `${t.name} — 一键应用`;
  $("#qf-notes").textContent = t.notes || "";

  const datalist = $("#qf-models");
  datalist.innerHTML = "";
  (t.models || []).forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    datalist.appendChild(opt);
  });
  $("#qf-model").value = t.default_model || "";

  $("#qf-provider-row").classList.toggle("hidden", !(t.kind === "custom" && !t.provider_id));
  $("#qf-provider").value = t.provider_id || "my-provider";

  $("#qf-url-row").classList.toggle("hidden", !!t.base_url || t.kind === "oss");
  $("#qf-url").value = t.base_url || "";

  $("#qf-key-row").classList.toggle("hidden", t.kind === "oss");
  $("#qf-key").value = "";
  $("#qf-scope-row").classList.toggle("hidden", t.kind === "oss");

  $("#qf-result").classList.add("hidden");
  $("#quick-form").scrollIntoView({ behavior: "smooth" });
}

$("#qf-key-toggle").addEventListener("click", () => {
  const el = $("#qf-key");
  el.type = el.type === "password" ? "text" : "password";
});

$("#qf-cancel").addEventListener("click", () => {
  $("#quick-form").classList.add("hidden");
  STATE.currentTemplate = null;
});

$("#qf-apply").addEventListener("click", async () => {
  const t = STATE.currentTemplate;
  if (!t) return;
  const btn = $("#qf-apply");
  btn.disabled = true;
  try {
    const payload = {
      template_id: t.id,
      model: $("#qf-model").value || t.default_model || null,
    };
    if (t.kind === "custom") {
      payload.provider_id = $("#qf-provider").value.trim() || t.provider_id || "my-provider";
      if (!$("#qf-url-row").classList.contains("hidden")) {
        payload.base_url = $("#qf-url").value.trim();
      }
      payload.api_key = $("#qf-key").value.trim() || null;
      payload.env_scope = $("#qf-scope").value;
    }
    const res = await api("/api/templates/apply", { method: "POST", body: payload });
    showResult($("#qf-result"), res.message, "ok");
    toast("切换成功，已自动备份", "ok");
    await refreshAll();
  } catch (err) {
    showResult($("#qf-result"), err.message, "err");
  } finally {
    btn.disabled = false;
  }
});

/* ---------------- Provider 管理 ---------------- */

function renderProviders() {
  const list = $("#provider-list");
  list.innerHTML = "";
  const providers = STATE.config.model_providers || {};
  const ids = Object.keys(providers);
  if (!ids.length) {
    list.innerHTML = '<p class="hint">暂无自定义 provider。可在「快速切换」页应用模板，或点击下方「新增」。</p>';
  }
  ids.forEach((pid) => {
    const p = providers[pid];
    const row = document.createElement("div");
    row.className = "prow";
    row.innerHTML = `
      <div class="p-info">
        <div class="p-id">${esc(pid)}${STATE.config.model_provider === pid ? ' <span class="tag" style="color:var(--green)">生效中</span>' : ""}</div>
        <div class="p-url">${esc(p.name || "")} ｜ ${esc(p.base_url || "")} ｜ env_key: ${esc(p.env_key || "无")}</div>
      </div>
      <div class="p-actions">
        <button class="ghost" data-edit="${esc(pid)}">编辑</button>
        <button class="ghost" data-del="${esc(pid)}">删除</button>
      </div>`;
    row.querySelector(`[data-edit]`).addEventListener("click", () => editProvider(pid));
    row.querySelector(`[data-del]`).addEventListener("click", () => deleteProvider(pid));
    list.appendChild(row);
  });

  const addBtn = document.createElement("button");
  addBtn.className = "ghost";
  addBtn.textContent = "新增 Provider";
  addBtn.addEventListener("click", () => editProvider(null));
  list.appendChild(addBtn);

  $("#g-model").value = STATE.config.model || "";
  $("#g-provider").value = STATE.config.model_provider || "";
  $("#g-openai-url").value = STATE.config.openai_base_url || "";
  $("#g-oss").value = STATE.config.oss_provider || "";
}

let editingProviderId = null;

function editProvider(pid) {
  editingProviderId = pid;
  const form = $("#provider-form");
  form.classList.remove("hidden");
  $("#pf-title").textContent = pid ? `编辑 Provider：${pid}` : "新增 Provider";
  if (pid) {
    const p = STATE.config.model_providers[pid];
    $("#pf-id").disabled = true;
    $("#pf-id").value = pid;
    $("#pf-name").value = p.name || "";
    $("#pf-url").value = p.base_url || "";
    $("#pf-envkey").value = p.env_key || "";
    $("#pf-qp").value = JSON.stringify(p.query_params || {});
    $("#pf-headers").value = JSON.stringify(p.http_headers || {});
    $("#pf-auth").value = p.requires_openai_auth ? "true" : "false";
  } else {
    $("#pf-id").disabled = false;
    $("#pf-id").value = "";
    $("#pf-name").value = "";
    $("#pf-url").value = "";
    $("#pf-envkey").value = "";
    $("#pf-qp").value = "";
    $("#pf-headers").value = "";
    $("#pf-auth").value = "false";
  }
  form.scrollIntoView({ behavior: "smooth" });
}

$("#pf-cancel").addEventListener("click", () => $("#provider-form").classList.add("hidden"));

$("#pf-save").addEventListener("click", async () => {
  try {
    const id = $("#pf-id").value.trim();
    if (!id) throw new Error("Provider ID 不能为空");
    const spec = {
      name: $("#pf-name").value.trim() || id,
      wire_api: "responses",
      requires_openai_auth: $("#pf-auth").value === "true",
    };
    const url = $("#pf-url").value.trim();
    if (url) spec.base_url = url;
    const envkey = $("#pf-envkey").value.trim();
    if (envkey) spec.env_key = envkey;
    let qp = null, headers = null;
    try { qp = JSON.parse($("#pf-qp").value || "{}"); } catch (_) { throw new Error("query_params 不是合法 JSON"); }
    try { headers = JSON.parse($("#pf-headers").value || "{}"); } catch (_) { throw new Error("http_headers 不是合法 JSON"); }
    if (Object.keys(qp).length) spec.query_params = qp;
    if (Object.keys(headers).length) spec.http_headers = headers;

    await api("/api/config", { method: "PUT", body: { config: { model_providers: { [id]: spec } } } });
    if (editingProviderId !== id) {
      const c = STATE.config;
      const changed = c.model_provider !== id || (c.model_providers || {})[id] === undefined;
      if (changed && !c.model_provider && !c.oss_provider && !c.openai_base_url) {
        // 新 provider 且当前没有生效 provider → 顺带设为生效
        await api("/api/config", { method: "PUT", body: { config: { model_provider: id } } });
      }
    }
    toast("已保存", "ok");
    $("#provider-form").classList.add("hidden");
    await refreshAll();
  } catch (err) {
    toast(err.message, "err");
  }
});

async function deleteProvider(pid) {
  const ok = await modalConfirm("删除 Provider", `<p>确认删除 provider <b>${esc(pid)}</b>？此操作会自动备份。</p>`);
  if (!ok) return;
  try {
    await api("/api/config", { method: "PUT", body: { config: { model_providers: { [pid]: null } } } });
    toast("已删除", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
}

$("#g-save").addEventListener("click", async () => {
  try {
    const body = {
      config: {
        model: $("#g-model").value.trim() || null,
        model_provider: $("#g-provider").value.trim() || null,
        openai_base_url: $("#g-openai-url").value.trim() || null,
        oss_provider: $("#g-oss").value || null,
      },
    };
    await api("/api/config", { method: "PUT", body });
    toast("全局设置已保存", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

/* ---------------- 连接测试 ---------------- */

function fillTestFromConfig() {
  const c = STATE.config;
  if (!c) return;
  if (!c.model_provider && c.oss_provider && !$("#ct-url").value) {
    $("#ct-url").value = c.oss_provider === "ollama" ? "http://localhost:11434/v1" : "http://localhost:1234/v1";
  }
  const pid = c.model_provider;
  if (pid && c.model_providers && c.model_providers[pid] && !$("#ct-url").value) {
    $("#ct-url").value = c.model_providers[pid].base_url || "";
  }
  if (c.model && !$("#ct-model").value) $("#ct-model").value = c.model;
}

$("#ct-key-toggle").addEventListener("click", () => {
  const el = $("#ct-key");
  el.type = el.type === "password" ? "text" : "password";
});

$("#ct-run").addEventListener("click", async () => {
  const btn = $("#ct-run");
  btn.disabled = true;
  try {
    const body = {
      base_url: $("#ct-url").value.trim(),
      model: $("#ct-model").value.trim(),
      api_key: $("#ct-key").value.trim() || null,
      headers: null,
    };
    if (!body.base_url || !body.model) throw new Error("需要填写 base_url 与模型");
    const res = await api("/api/test-connection", { method: "POST", body });
    renderTestResult(res);
  } catch (err) {
    showResult($("#ct-result"), err.message, "err");
  } finally {
    btn.disabled = false;
  }
});

function renderTestResult(res) {
  const el = $("#ct-result");
  const smoke = res.smoke;
  const status = res.passed ? "连接正常" : "连接失败";
  const detail = [
    `POST /responses → HTTP ${smoke.status ?? "-"}（${smoke.ms}ms）${smoke.error ? "：" + smoke.error : ""}`,
    `GET /models → HTTP ${res.models.status ?? "-"}（${res.models.ms}ms）`,
    res.models.models.length ? `探测到模型: ${res.models.models.slice(0, 8).join(", ")}${res.models.models.length > 8 ? "…" : ""}` : "",
  ].filter(Boolean).join("\n");
  el.className = `result ${res.passed ? "ok" : "err"}`;
  el.innerHTML = `<div class="big-status">${status}</div><div class="r-detail">${esc(detail)}</div>`;
  el.classList.remove("hidden");
}

/* ---------------- 环境变量 ---------------- */

let envDraft = { user: [], file: [] };

function renderEnv() {
  envDraft.user = (STATE.env.user || []).map((e) => ({ name: e.name, _origName: e.name, value: e.masked, masked: true, real: null, dirty: false, deleted: false }));
  envDraft.file = STATE.env.file.map((e) => ({ name: e.name, _origName: e.name, value: e.masked, masked: true, real: e.value, dirty: false, deleted: false }));
  renderEnvRows("user");
  renderEnvRows("file");
  $("#env-file-path").textContent = `(${esc(STATE.env.env_file)})`;
}

function renderEnvRows(scope) {
  const list = $(`#env-${scope}-list`);
  const rows = envDraft[scope];
  list.innerHTML = "";
  rows.forEach((row, idx) => list.appendChild(envRowEl(scope, idx)));
  if (!rows.length) list.innerHTML = '<p class="hint">（空）</p>';
}

function envRowEl(scope, idx) {
  const row = envDraft[scope][idx];
  if (row.deleted) return document.createDocumentFragment();
  const el = document.createElement("div");
  el.className = "env-row";
  el.innerHTML = `
    <input class="env-name" value="${esc(row.name)}" placeholder="变量名">
    <input class="env-val" type="password" value="${esc(row.masked ? row.value : (row.real ?? ""))}" placeholder="值">
    <button class="ghost env-toggle">显示</button>
    <button class="ghost env-del">删除</button>`;
  const nameIn = el.querySelector(".env-name");
  const valIn = el.querySelector(".env-val");

  el.querySelector(".env-toggle").addEventListener("click", () => {
    const showing = valIn.type === "text";
    valIn.type = showing ? "password" : "text";
    if (!showing && row.masked && !row.dirty) {
      // 后端不返回明文；未修改的隐藏值保持脱敏显示
      valIn.value = row.value;
    }
    el.querySelector(".env-toggle").textContent = showing ? "显示" : "隐藏";
  });
  el.querySelector(".env-del").addEventListener("click", () => {
    if (row.isNew) {
      envDraft[scope].splice(idx, 1);
    } else {
      row.deleted = true;   // 删除既有行：保存时发送 value=null
    }
    renderEnvRows(scope);
  });
  nameIn.addEventListener("input", () => {
    row.name = nameIn.value;
    if (!row.isNew && nameIn.value !== row._origName) row.dirty = true;
  });
  valIn.addEventListener("input", () => {
    row.real = valIn.value;
    row.masked = false;
    row.dirty = true;
  });
  return el;
}

function envDirtyEntries(scope) {
  // 只发送修改过的行：改值 → {name, value}；删除 → {name, value: null}；未动 → 不发送
  const out = [];
  envDraft[scope].forEach((r) => {
    const name = r.name.trim();
    if (!name) return;
    if (r.deleted) {
      out.push({ name, value: null });
      return;
    }
    if (r.dirty) {
      out.push({ name, value: r.masked ? null : (r.real !== null ? r.real : "") });
    }
  });
  return out;
}

$("#env-user-add").addEventListener("click", () => {
  envDraft.user.push({ name: "", value: "", masked: false, real: null, dirty: true, isNew: true });
  renderEnvRows("user");
});
$("#env-file-add").addEventListener("click", () => {
  envDraft.file.push({ name: "", value: "", masked: false, real: null, dirty: true, isNew: true });
  renderEnvRows("file");
});

$("#env-user-save").addEventListener("click", async () => {
  try {
    const entries = envDirtyEntries("user");
    if (!entries.length) { toast("没有需要保存的修改", "ok"); return; }
    await api("/api/env?scope=user", { method: "PUT", body: { entries } });
    toast("用户环境变量已保存。请重启 Codex Desktop 后生效。", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

$("#env-file-save").addEventListener("click", async () => {
  try {
    const entries = envDirtyEntries("file");
    if (!entries.length) { toast("没有需要保存的修改", "ok"); return; }
    await api("/api/env?scope=file", { method: "PUT", body: { entries } });
    toast(".env 已保存", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

$("#env-file-to-user").addEventListener("click", async () => {
  try {
    await api("/api/env/import", { method: "POST", body: { direction: "file_to_user" } });
    toast("已导入。请重启 Codex Desktop 后生效。", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

$("#env-user-to-file").addEventListener("click", async () => {
  try {
    await api("/api/env/import", { method: "POST", body: { direction: "user_to_file" } });
    toast("已导出到 .env", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

/* ---------------- 备份与恢复 ---------------- */

const SRC_LABEL = { manual: "手动", auto: "自动", pre_restore: "恢复前" };

function renderBackups() {
  const list = $("#bk-list");
  list.innerHTML = "";
  if (!STATE.backups.length) {
    list.innerHTML = '<p class="hint">暂无备份。</p>';
    return;
  }
  STATE.backups.forEach((b) => {
    const row = document.createElement("div");
    row.className = "brow";
    row.innerHTML = `
      <span class="b-src ${esc(b.source)}">${SRC_LABEL[b.source] || esc(b.source)}</span>
      <div class="b-info">${esc(b.note || "")}</div>
      <div class="b-time">${esc(b.created_at)}</div>
      <button class="ghost" data-restore="${esc(b.id)}">恢复</button>`;
    row.querySelector("[data-restore]").addEventListener("click", () => restoreBackup(b));
    list.appendChild(row);
  });
}

$("#bk-create").addEventListener("click", async () => {
  try {
    await api("/api/backups", { method: "POST", body: {} });
    toast("备份已创建", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

async function restoreBackup(b) {
  const ok = await modalConfirm("恢复备份",
    `<p>恢复到备份 <b>${esc(b.created_at)}</b>（${esc(SRC_LABEL[b.source] || b.source)}）？<br>当前配置会先自动备份，恢复后本工具的覆盖记录将被清空。</p>`);
  if (!ok) return;
  try {
    const res = await api("/api/backups/restore", { method: "POST", body: { id: b.id } });
    toast(res.message || "已恢复", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
}

$("#bk-reset").addEventListener("click", async () => {
  try {
    const { overrides } = await api("/api/overrides");
    if (!overrides.length) {
      toast("当前没有本工具管理的覆盖，无需恢复", "ok");
      return;
    }
    const rows = overrides.map((o) => `
      <label class="ov-row">
        <input type="checkbox" class="ov-check" data-key="${esc(o.key)}" checked>
        <span class="ov-key">${esc(o.key)}</span>
        <span class="hint" style="min-width:200px">原值: ${esc(o.before === null ? "（不存在）" : JSON.stringify(o.before))}</span>
      </label>`).join("");
    const ok = await modalConfirm("恢复默认 — 确认将移除的覆盖",
      `<p>以下为本工具修改过的键，勾选后将被移除（恢复为原值）。插件/MCP 等配置不受影响。操作前会自动备份。</p>${rows}`,
      "移除所选");
    if (!ok) return;
    const keys = Array.from($$(".ov-check")).filter((c) => c.checked).map((c) => c.dataset.key);
    if (!keys.length) return;
    const res = await api("/api/reset", { method: "POST", body: { keys } });
    toast(res.message || "已恢复默认", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

function renderDefaults() {
  const list = $("#bk-defaults-list");
  list.innerHTML = "";
  if (!STATE.defaults.length) {
    list.innerHTML = '<p class="hint">暂无保存的默认模板。</p>';
    return;
  }
  STATE.defaults.forEach((d) => {
    const row = document.createElement("div");
    row.className = "prow";
    row.innerHTML = `
      <div class="p-info"><div class="p-id">${esc(d.name)}</div>
      <div class="p-url">保存于 ${esc(d.saved_at)}</div></div>
      <div class="p-actions">
        <button class="ghost" data-apply="${esc(d.id)}">应用</button>
        <button class="ghost" data-del="${esc(d.id)}">删除</button>
      </div>`;
    row.querySelector("[data-apply]").addEventListener("click", async () => {
      try {
        await api("/api/defaults/apply", { method: "POST", body: { id: d.id } });
        toast("已应用我的默认", "ok");
        await refreshAll();
      } catch (err) { toast(err.message, "err"); }
    });
    row.querySelector("[data-del]").addEventListener("click", async () => {
      await api("/api/defaults/delete", { method: "POST", body: { id: d.id } });
      await refreshAll();
    });
    list.appendChild(row);
  });
}

$("#bk-save-default").addEventListener("click", async () => {
  try {
    const name = $("#bk-default-name").value.trim() || "我的默认";
    await api("/api/defaults/save-as-mine", { method: "POST", body: { name } });
    toast("已保存为「我的默认」", "ok");
    await refreshAll();
  } catch (err) { toast(err.message, "err"); }
});

/* ---------------- 工具 ---------------- */

function showResult(el, message, kind) {
  el.className = `result ${kind}`;
  el.innerHTML = `<div>${esc(message)}</div>`;
  el.classList.remove("hidden");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------------- 启动 ---------------- */

refreshAll().catch((err) => {
  toast(`加载失败: ${err.message}`, "err");
});

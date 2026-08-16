/* AI 短剧流水线前端 —— 端到端：剧本分段 / 分镜管理 / 抽卡 / 拼接 */
"use strict";

const $ = (s) => document.querySelector(s);

const state = {
  project: null,
  episode: null,
  acts: [],
  episodes: [],
  rows: [],
  header: [],
  assets: {},
  frames: [],
  cameras: [],
  selected: -1,
  dirty: false,
  finals: new Set(),   // 已规范化选中的 shot_XX.mp4
  job: null,
  taste: null,         // 品味档案（/api/taste）
  wizard: null,        // 创作向导状态
  novelLoaded: false,  // 剧本面板已载入过小说内容
};

/* ---------- API ---------- */
async function api(path, opts = {}) {
  const resp = await fetch(path, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
  return data;
}

/* ---------- 状态提示 ---------- */
function setStatus(msg, cls) {
  const el = $("#status");
  el.textContent = msg;
  el.className = "status " + (cls || "");
}
function markDirty() {
  state.dirty = true;
  $("#saveBtn").disabled = false;
  setStatus("有未保存修改", "dirty");
}

/* ---------- 初始化 ---------- */
async function init() {
  try {
    const [proj, assets, vocab, taste] = await Promise.all([
      api("/api/projects"), api("/api/assets"), api("/api/vocab"), api("/api/taste"),
    ]);
    state.taste = taste;
    state.assets = Object.fromEntries((assets.assets || []).map(a => [a.code, a]));
    state.frames = vocab.frames || [];
    state.cameras = vocab.cameras || [];
    const refSel = $("#refSel");
    const withImg = (assets.assets || []).filter(a => a.image);
    refSel.innerHTML = '<option value="">无参考图（T2VA）</option>' +
      withImg.map(a => `<option value="${a.code}">${a.code} ${a.name}（Ref2VA 一致性）</option>`).join("");
    const sel = $("#projectSel");
    sel.innerHTML = proj.projects.map(p => `<option>${p}</option>`).join("");
    sel.onchange = () => { state.project = sel.value; loadProject(); };
    if (proj.projects.length) {
      state.project = proj.projects[0];
      sel.value = state.project;
      await loadProject();
      loadWizard();
    } else {
      setStatus("output/ 下没有项目，先运行 pipeline.py init", "err");
    }
  } catch (e) {
    setStatus("加载失败: " + e.message, "err");
  }
}

/* ---------- 项目 ---------- */
async function loadProject() {
  try {
    const p = await api(`/api/project/${enc(state.project)}`);
    state.acts = p.acts;
    state.episodes = p.episodes;
    const sel = $("#episodeSel");
    sel.innerHTML = state.episodes.map(n => `<option value="${n}">E${String(n).padStart(2, "0")}</option>`).join("");
    sel.onchange = () => { state.episode = +sel.value; loadBoard(); };
    renderTree();
    if (state.episodes.length) {
      state.episode = state.episodes[0];
      sel.value = state.episode;
      await loadBoard();
    } else {
      setStatus("项目没有集，先运行 pipeline.py init", "err");
    }
  } catch (e) {
    setStatus("加载项目失败: " + e.message, "err");
  }
}

function renderTree() {
  const root = $("#actsTree");
  root.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "node";
  wrap.appendChild(nodeTitle(state.project, true, null));
  const children = document.createElement("div");
  children.className = "node-children";
  for (const act of state.acts) {
    const actNode = document.createElement("div");
    actNode.className = "node";
    const title = nodeTitle(act.title, true, () => showActText(act));
    title.querySelector(".toggle").textContent = "▾";
    actNode.appendChild(title);
    const body = document.createElement("div");
    body.className = "node-children";
    const txt = document.createElement("div");
    txt.className = "act-text";
    txt.innerHTML = `<div class="act-title">${esc(act.title)}</div>${esc(act.text)}`;
    body.appendChild(txt);
    actNode.appendChild(body);
    children.appendChild(actNode);
  }
  for (const n of state.episodes) {
    const ep = document.createElement("div");
    ep.className = "ep" + (n === state.episode ? " active" : "");
    ep.textContent = "E" + String(n).padStart(2, "0");
    ep.onclick = () => {
      state.episode = n;
      $("#episodeSel").value = n;
      loadBoard();
    };
    children.appendChild(ep);
  }
  wrap.appendChild(children);
  root.appendChild(wrap);
}

function nodeTitle(text, hasChildren, onClick) {
  const div = document.createElement("div");
  div.className = "node-title";
  div.innerHTML = `<span class="toggle">${hasChildren ? "▸" : ""}</span><span>${esc(text)}</span>`;
  if (onClick) div.onclick = onClick;
  return div;
}

function showActText(act) {
  const box = $("#actText");
  box.innerHTML = `<div class="act-title">${esc(act.title)}</div>${esc(act.text)}`;
  box.classList.add("show");
}

/* ---------- 分镜表 ---------- */
async function loadBoard() {
  try {
    const [sb, st] = await Promise.all([
      api(`/api/project/${enc(state.project)}/episode/${state.episode}/storyboard`),
      api(`/api/episode-status/${enc(state.project)}/${state.episode}`),
    ]);
    state.rows = sb.rows;
    state.header = sb.header || [];
    state.finals = new Set(st.selected || []);
    state.selected = -1;
    state.job = null;
    state.dirty = false;
    $("#saveBtn").disabled = true;
    $("#renderStatus").textContent = "";
    $("#gallery").innerHTML = "";
    setStatus(`已载入 ${state.rows.length} 镜`);
    renderBoard();
    renderTree();
    renderFinal();
  } catch (e) {
    setStatus("加载分镜失败: " + e.message, "err");
  }
}

function renderBoard() {
  const tbody = $("#board tbody");
  tbody.innerHTML = "";
  state.rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    const shotNo = i + 1;
    const finalName = `shot_${String(shotNo).padStart(2, "0")}.mp4`;
    const hasFinal = state.finals.has(finalName);
    tr.className = "row" + (i === state.selected ? " selected" : "") + (hasFinal ? " has-final" : "");
    if (badCodes(row.chars).length) tr.classList.add("bad-code");
    tr.onclick = () => selectRow(i);
    const cells = [
      ["shot", textInput(i, "shot", row.shot), "text"],
      ["frame", inputWithList(i, "frame", row.frame, state.frames), "text"],
      ["camera", inputWithList(i, "camera", row.camera, state.cameras), "text"],
      ["dur", textInput(i, "dur", row.dur), "text"],
      ["chars", textInput(i, "chars", row.chars), "col-chars"],
      ["scene", textInput(i, "scene", row.scene), "text"],
      ["light", textInput(i, "light", row.light), "text"],
      ["dialogue", textInput(i, "dialogue", row.dialogue), "text"],
      ["note", textInput(i, "note", row.note), "text"],
    ];
    for (const [key, el, cls] of cells) {
      const td = document.createElement("td");
      td.className = cls;
      td.appendChild(el);
      tr.appendChild(td);
    }
    const tdSel = document.createElement("td");
    tdSel.className = "col-final";
    tdSel.textContent = hasFinal ? "✓" : "";
    tr.appendChild(tdSel);
    tbody.appendChild(tr);
  });
  updateRowButtons();
}

function textInput(i, key, value) {
  const inp = document.createElement("input");
  inp.value = value ?? "";
  inp.oninput = () => { state.rows[i][key] = inp.value; markDirty(); };
  return inp;
}

function inputWithList(i, key, value, list) {
  const wrap = document.createElement("span");
  wrap.style.display = "contents";
  const inp = document.createElement("input");
  inp.setAttribute("list", "datalist-" + key);
  inp.value = value ?? "";
  inp.oninput = () => { state.rows[i][key] = inp.value; markDirty(); };
  let dl = document.getElementById("datalist-" + key);
  if (!dl) {
    dl = document.createElement("datalist");
    dl.id = "datalist-" + key;
    document.body.appendChild(dl);
  }
  dl.innerHTML = list.map(v => `<option value="${esc(v)}"></option>`).join("");
  wrap.appendChild(inp);
  return wrap;
}

function badCodes(chars) {
  const out = [];
  for (const c of (chars || "").split(",")) {
    const code = c.trim();
    if (/^[CSPR]\d{2}$/.test(code) && !state.assets[code]) out.push(code);
  }
  return out;
}

/* ---------- 行操作 ---------- */
function selectRow(i) {
  state.selected = i;
  renderBoard();
  renderDetail();
  loadPrompt();
  loadGallery();
}

function updateRowButtons() {
  const n = state.rows.length;
  $("#delRowBtn").disabled = state.selected < 0;
  $("#upRowBtn").disabled = state.selected <= 0;
  $("#downRowBtn").disabled = state.selected < 0 || state.selected >= n - 1;
  $("#renderBtn").disabled = state.selected < 0;
}

$("#addRowBtn").onclick = () => {
  const i = state.selected >= 0 ? state.selected : state.rows.length - 1;
  const base = state.rows[i] || {};
  const d = (state.taste && state.taste.defaults) || {};
  const row = { shot: "", frame: d.frame || "medium", camera: d.camera || "static",
                dur: d.dur || "5", chars: "", scene: "S01", light: "", dialogue: "", note: "" };
  Object.assign(row, base);
  state.rows.splice(i + 1, 0, row);
  markDirty(); selectRow(i + 1);
};
$("#delRowBtn").onclick = () => {
  if (state.selected < 0) return;
  state.rows.splice(state.selected, 1);
  state.selected = Math.min(state.selected, state.rows.length - 1);
  markDirty(); renderBoard(); renderDetail();
};
$("#upRowBtn").onclick = () => moveRow(-1);
$("#downRowBtn").onclick = () => moveRow(1);
function moveRow(d) {
  const i = state.selected;
  const j = i + d;
  if (i < 0 || j < 0 || j >= state.rows.length) return;
  [state.rows[i], state.rows[j]] = [state.rows[j], state.rows[i]];
  state.selected = j;
  markDirty(); renderBoard();
}

/* ---------- 详情 + 提示词 ---------- */
function renderDetail() {
  const box = $("#detail");
  if (state.selected < 0) { box.innerHTML = '<p class="hint">点击分镜行查看详情</p>'; return; }
  const r = state.rows[state.selected];
  const bad = badCodes(r.chars);
  const fields = [
    ["frame", "景别", inputWithList(state.selected, "frame", r.frame, state.frames)],
    ["camera", "机位运动", inputWithList(state.selected, "camera", r.camera, state.cameras)],
    ["dur", "时长(秒)", textInput(state.selected, "dur", r.dur)],
    ["chars", "角色", textInput(state.selected, "chars", r.chars)],
    ["scene", "场景", textInput(state.selected, "scene", r.scene)],
    ["light", "灯光", textInput(state.selected, "light", r.light)],
    ["dialogue", "对白/音效", textInput(state.selected, "dialogue", r.dialogue)],
    ["note", "备注", textInput(state.selected, "note", r.note)],
  ];
  box.innerHTML = "";
  for (const [key, label, el] of fields) {
    const f = document.createElement("div");
    f.className = "field";
    const l = document.createElement("label");
    l.textContent = label;
    f.appendChild(l);
    if (key === "chars") {
      const badge = document.createElement("span");
      badge.className = "badge " + (bad.length ? "bad" : "ok");
      badge.textContent = bad.length ? ("未登记: " + bad.join(",")) : "资产校验通过";
      f.appendChild(badge);
    }
    f.appendChild(el);
    box.appendChild(f);
  }
}

async function loadPrompt() {
  const pre = $("#promptPreview");
  pre.textContent = "加载中…";
  try {
    const d = await api(`/api/prompt/${enc(state.project)}/${state.episode}/${state.selected + 1}`);
    pre.textContent = d.prompt;
  } catch (e) {
    pre.textContent = "提示词生成失败: " + e.message;
  }
}

/* ---------- 抽卡 ---------- */
$("#renderBtn").onclick = () => startRender();

async function startRender() {
  if (state.selected < 0) return;
  const shotNo = state.selected + 1;
  const btn = $("#renderBtn"), st = $("#renderStatus");
  const shots = +$("#shotsSel").value;
  const mode = $("#modeSel").value;
  const ref = $("#refSel").value;
  btn.disabled = true;
  st.textContent = "提交中…";
  try {
    const body = { project: state.project, episode: state.episode,
                   only: [shotNo], shots, ref };
    if (mode === "quick") {
      Object.assign(body, { width: 512, height: 288, frames: 22,
                            steps: ref ? 8 : 2 });   // Ref2VA 无 turbo LoRA，步数放宽
    } else {
      Object.assign(body, { steps: ref ? 20 : 4 });
    }
    const r = await api("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.job = r.job;
    st.textContent = `任务 ${r.job} 生成中…`;
    pollRender();
  } catch (e) {
    st.textContent = "提交失败: " + e.message;
    btn.disabled = false;
  }
}

function pollRender() {
  const st = $("#renderStatus");
  const timer = setInterval(async () => {
    if (!state.job) { clearInterval(timer); return; }
    try {
      const s = await api(`/api/render/status/${state.job}`);
      if (s.status === "done") {
        clearInterval(timer);
        st.textContent = "生成完成 ✓";
        state.job = null;
        $("#renderBtn").disabled = false;
        loadGallery();
      } else if (s.status === "error") {
        clearInterval(timer);
        st.textContent = "生成失败: " + (s.message || "");
        $("#renderBtn").disabled = false;
        state.job = null;
      } else {
        st.textContent = s.message || "生成中…";
      }
    } catch (e) {
      /* 桥暂不可达时继续轮询 */
    }
  }, 4000);
}

async function loadGallery() {
  const box = $("#gallery");
  if (state.selected < 0) { box.innerHTML = ""; return; }
  const shotNo = state.selected + 1;
  try {
    const { files } = await api(`/api/candidates/${enc(state.project)}/${state.episode}/${shotNo}`);
    if (!files.length) { box.innerHTML = '<p class="hint">暂无候选，点“为本镜抽 3 个候选”生成。</p>'; return; }
    box.innerHTML = "";
    for (const f of files) {
      const item = document.createElement("div");
      item.className = "cand";
      const vid = document.createElement("video");
      vid.src = `/video/${enc(state.project)}/${state.episode}/${f.name}`;
      vid.muted = true; vid.loop = true; vid.preload = "metadata";
      vid.onclick = async () => {
        try {
          await api("/api/select", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project: state.project, episode: state.episode,
                                   shot: shotNo, file: f.name }),
          });
          setStatus(`已选中 镜${shotNo} → ${f.name}`, "ok");
          await refreshFinals();
        } catch (e) {
          setStatus("选中失败: " + e.message, "err");
        }
      };
      const label = document.createElement("div");
      label.className = "cand-label";
      label.textContent = f.name.replace(/\.mp4$/, "");
      item.appendChild(vid); item.appendChild(label);
      box.appendChild(item);
    }
  } catch (e) {
    box.innerHTML = '<p class="hint">候选加载失败</p>';
  }
}

async function refreshFinals() {
  const st = await api(`/api/episode-status/${enc(state.project)}/${state.episode}`);
  state.finals = new Set(st.selected || []);
  renderBoard();
  renderFinal();
}

/* ---------- 拼接成片 ---------- */
$("#composeBtn").onclick = async () => {
  const btn = $("#composeBtn");
  btn.disabled = true;
  setStatus("拼接中…（ffmpeg）", "dirty");
  try {
    const r = await api("/api/compose", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: state.project, episode: state.episode }),
    });
    if (r.ok) {
      setStatus(`成片已生成（${(r.size / 1e6).toFixed(1)}MB）`, "ok");
      renderFinal();
    } else {
      setStatus("拼接失败：请检查 shots/ 是否每镜已选中", "err");
    }
  } catch (e) {
    setStatus("拼接失败: " + e.message, "err");
  }
  btn.disabled = false;
};

function renderFinal() {
  const box = $("#finalArea");
  if (state.finals.size === 0) {
    box.innerHTML = '<p class="hint">先为每镜选中一个候选，再点“拼接成片”。</p>';
    return;
  }
  const vid = document.createElement("video");
  vid.controls = true;
  vid.style.width = "100%";
  vid.src = `/video/${enc(state.project)}/${state.episode}/成片.mp4?t=${Date.now()}`;
  box.innerHTML = "";
  box.appendChild(vid);
}

/* ---------- 保存 ---------- */
$("#saveBtn").onclick = async () => {
  const rows = state.rows.map((r, i) => Object.assign({}, r, { shot: String(i + 1) }));
  try {
    const r = await api(`/api/project/${enc(state.project)}/episode/${state.episode}/storyboard`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows, header: state.header }),
    });
    state.dirty = false;
    $("#saveBtn").disabled = true;
    setStatus(`已保存 ${r.rows} 镜 → ${r.path}`, "ok");
  } catch (e) {
    setStatus("保存失败: " + e.message, "err");
  }
};

window.addEventListener("beforeunload", (e) => {
  if (state.dirty) { e.preventDefault(); e.returnValue = ""; }
});

function enc(s) { return encodeURIComponent(s); }
/* ---------- 创作向导（借鉴 Toonflow 引导式流程：7 步状态 + 导航） ---------- */
async function loadWizard() {
  try {
    state.wizard = await api(`/api/wizard/${enc(state.project)}`);
    renderWizard();
  } catch (e) { /* 桥版本无向导 API 时忽略 */ }
}
function renderWizard() {
  const bar = $("#wizardBar");
  const w = state.wizard;
  if (!w || !w.steps) return;
  bar.innerHTML = w.steps.map((s, i) =>
    `<button class="wz-step${s.done ? " done" : ""}" data-key="${s.key}" title="${esc(s.hint || "")}">
      <b>${i + 1}</b> ${esc(s.label)}${s.done ? " ✓" : ""}</button>`).join("");
  bar.querySelectorAll(".wz-step").forEach(b => {
    b.onclick = () => {
      if (b.dataset.key === "script") showScriptPanel();
      else {
        hideScriptPanel();
        if (b.dataset.key === "compose") $("#composeBtn").click();
      }
    };
  });
}
function showScriptPanel() {
  $("#scriptPanel").classList.remove("hidden");
  $("#layout").classList.add("hidden");
  loadCreative();
}
function hideScriptPanel() {
  $("#scriptPanel").classList.add("hidden");
  $("#layout").classList.remove("hidden");
}
async function loadCreative() {
  try {
    const c = await api(`/api/creative/${enc(state.project)}`);
    if (!state.novelLoaded && c.novel) { $("#novelBox").value = c.novel; state.novelLoaded = true; }
    $("#aiStatus").textContent = c.script ? "已有 剧本.md（可到项目目录查看/编辑，或重跑 AI 编剧）"
                                          : "尚未生成 剧本.md";
    renderEvents(c.events || "");
  } catch (e) { /* 忽略 */ }
}
function renderEvents(eventsText) {
  const box = $("#eventsArea");
  if (!eventsText) { box.innerHTML = '<p class="hint">尚未提取事件图谱。点“提取事件图谱”：有 LLM 一键提取，无 LLM 输出 Agent 指令（Agent 写入 小说事件.md），之后 AI 编剧按事件改编剧本。</p>'; return; }
  box.innerHTML = `<h4>事件图谱（小说事件.md）</h4><pre class="prompt">${esc(eventsText)}</pre>`;
}
$("#extractEventsBtn").onclick = async () => {
  const btn = $("#extractEventsBtn");
  btn.disabled = true;
  $("#aiStatus").textContent = "提取事件图谱中…";
  $("#eventsArea").innerHTML = "";
  try {
    const r = await api(`/api/ai-write/${enc(state.project)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ novel: $("#novelBox").value, title: state.project, mode: "events" }),
    });
    if (r.kind === "events" && r.mode === "llm") {
      renderEvents(r.events || "");
      $("#aiStatus").textContent = "事件图谱已生成并写入 小说事件.md";
    } else {
      const txt = r.instruction || "";
      $("#eventsArea").innerHTML =
        `<h4>本地无 LLM → 输出事件提取 Agent 指令</h4>
         <p class="hint">复制指令发给任意 AI Agent，它会写入 <code>output/${esc(state.project)}/小说事件.md</code>，随后 AI 编剧按事件改编。</p>
         <button id="copyEventsBtn">复制指令</button>
         <pre class="prompt">${esc(txt)}</pre>`;
      $("#copyEventsBtn").onclick = async () => {
        try { await navigator.clipboard.writeText(txt); $("#aiStatus").textContent = "指令已复制"; }
        catch (e) { $("#aiStatus").textContent = "复制失败，请手动全选复制"; }
      };
    }
  } catch (e) {
    $("#eventsArea").innerHTML = `<p class="err">提取失败: ${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
};
$("#saveNovelBtn").onclick = async () => {
  try {
    const r = await api(`/api/novel/${enc(state.project)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ novel: $("#novelBox").value }),
    });
    $("#aiStatus").textContent = "小说已保存（" + r.chars + " 字）";
  } catch (e) { $("#aiStatus").textContent = "保存失败: " + e.message; }
};
$("#aiWriteBtn").onclick = async () => {
  const btn = $("#aiWriteBtn");
  btn.disabled = true;
  $("#aiStatus").textContent = "AI 编剧执行中…";
  $("#aiResult").innerHTML = "";
  try {
    const r = await api(`/api/ai-write/${enc(state.project)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ novel: $("#novelBox").value, title: state.project }),
    });
    if (r.mode === "llm") {
      $("#aiResult").innerHTML =
        `<h4>剧本草稿已生成并写入 剧本.md</h4><pre class="prompt">${esc(r.script || "")}</pre>`;
      $("#aiStatus").textContent = "LLM 生成完成，请审改 剧本.md（向导第 2 步自动分段）";
    } else {
      const txt = r.instruction || "";
      $("#aiResult").innerHTML =
        `<h4>本地无 LLM → 输出 Agent 编剧指令</h4>
         <p class="hint">复制指令发给任意 AI Agent（Reasonix / Codex / Claude），它会按四幕结构把剧本写入
         <code>output/${esc(state.project)}/剧本.md</code>。</p>
         <button id="copyInstBtn">复制指令</button>
         <pre class="prompt">${esc(txt)}</pre>`;
      $("#copyInstBtn").onclick = async () => {
        try {
          await navigator.clipboard.writeText(txt);
          $("#aiStatus").textContent = "指令已复制";
        } catch (e) { $("#aiStatus").textContent = "复制失败，请手动全选复制"; }
      };
    }
  } catch (e) {
    $("#aiResult").innerHTML = `<p class="err">AI 编剧失败: ${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init();

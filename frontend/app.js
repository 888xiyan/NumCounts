const state = { token: sessionStorage.getItem("numcounts_token") || "", role: null, plugins: [] };
const $ = (id) => document.getElementById(id);

function notice(message, error = false) {
  const target = $("notice");
  target.textContent = message;
  target.classList.toggle("error", error);
}

function apiBase() {
  return $("api-base").value.replace(/\/$/, "");
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (typeof options.body === "string" && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${apiBase()}${path}`, { ...options, headers });
  const payload = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(payload?.error?.message || "请求失败");
  return payload;
}

function parseJson(id) {
  try { return JSON.parse($(id).value); }
  catch { throw new Error("请检查 JSON 格式"); }
}

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

function actionButton(label, callback, className = "ghost") {
  const button = element("button", className, label);
  button.type = "button";
  button.onclick = () => callback().catch((error) => notice(error.message, true));
  return button;
}

function pluginCard(plugin) {
  const item = element("article", "record");
  item.append(element("strong", "", `${plugin.name} · ${plugin.version} · ${plugin.status}`));
  item.append(element("code", "", plugin.id));
  item.append(element("span", "", `${plugin.purpose || "general"} · ${plugin.function.kind}: ${plugin.function.name || plugin.function.executor_id}`));
  const actions = element("div", "actions");
  const button = actionButton(plugin.status === "enabled" ? "停用" : "启用", async () => {
    const action = plugin.status === "enabled" ? "disable" : "enable";
    await request(`/rule-plugins/${plugin.id}/${action}`, { method: "POST" });
    await Promise.all([loadPlugins(), loadAdminCases()]);
  });
  actions.append(button); item.append(actions); return item;
}

function workflowCard(workflow) {
  const item = element("article", "record");
  item.append(element("strong", "", `${workflow.name} · ${workflow.version} · ${workflow.status}`));
  item.append(element("code", "", workflow.id));
  item.append(element("span", "", `${workflow.nodes.length} 个节点：${workflow.nodes.map((node) => node.node_key).join(" → ")}`));
  const actions = element("div", "actions");
  actions.append(actionButton(workflow.status === "active" ? "停用" : "启用", async () => {
    const endpoint = workflow.status === "active" ? "disable" : "activate";
    await request(`/workflows/${workflow.id}/${endpoint}`, { method: "POST" });
    await loadWorkflows();
  }));
  actions.append(actionButton("用于运行", async () => {
    $("run-workflow-id").value = workflow.id;
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }));
  item.append(actions); return item;
}

async function loadPlugins() {
  const response = await request("/rule-plugins");
  state.plugins = response.data;
  $("plugins").replaceChildren(...response.data.map(pluginCard));
}

async function loadWorkflows() {
  const response = await request("/workflows");
  $("workflows").replaceChildren(...response.data.map(workflowCard));
}

async function downloadMaterial(caseId, material) {
  const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
  const response = await fetch(`${apiBase()}/special-performance-cases/${caseId}/materials/${material.id}/content`, { headers });
  if (!response.ok) throw new Error("材料下载失败");
  const url = URL.createObjectURL(await response.blob());
  const link = element("a");
  link.href = url; link.download = material.filename; link.click();
  URL.revokeObjectURL(url);
}

function appendMaterials(parent, item) {
  const list = element("div", "material-list");
  for (const material of item.materials) {
    const row = element("div", "material-row");
    row.append(element("span", "", `${material.filename} · v${material.version} · ${material.is_current ? "当前" : "历史"}`));
    row.append(actionButton("下载", () => downloadMaterial(item.id, material)));
    if (state.role === "USER" && item.status === "draft" && material.is_current) {
      row.append(actionButton("撤下", async () => {
        await request(`/special-performance-cases/${item.id}/materials/${material.id}`, { method: "DELETE" });
        await loadMyCases();
      }));
    }
    list.append(row);
  }
  parent.append(list);
}

function memberCaseCard(item) {
  const card = element("article", "record case-record");
  card.append(element("strong", "", `${item.title} · ${item.case_type === "appeal" ? "申诉" : "特殊绩效"} · ${item.status}`));
  card.append(element("code", "", item.id));
  card.append(element("span", "", `考核周期：${item.period_id} · 提交版本：${item.submission_version}${item.overdue ? " · 已逾期" : ""}`));
  card.append(element("pre", "case-json", JSON.stringify({ form_data: item.form_data, processing_error: item.processing_error, events: item.events }, null, 2)));
  appendMaterials(card, item);
  if (item.status === "draft") {
    const edit = document.createElement("details");
    const summary = element("summary", "", "编辑草稿信息");
    const label = element("label", "", "申报信息 JSON");
    const textarea = document.createElement("textarea"); textarea.rows = 5; textarea.value = JSON.stringify(item.form_data, null, 2);
    label.append(textarea); edit.append(summary, label);
    edit.append(actionButton("保存草稿修改", async () => {
      await request(`/special-performance-cases/${item.id}`, { method: "PATCH", body: JSON.stringify({ form_data: JSON.parse(textarea.value) }) });
      await loadMyCases(); notice("草稿已保存。");
    }, ""));
    const uploadLabel = element("label", "", "新增 / 更新材料");
    const file = document.createElement("input"); file.type = "file"; uploadLabel.append(file); edit.append(uploadLabel);
    const keyLabel = element("label", "", "材料标识（相同标识将产生新版本）");
    const key = document.createElement("input"); key.value = "proof"; key.pattern = "[a-zA-Z][a-zA-Z0-9_-]{0,63}"; keyLabel.append(key); edit.append(keyLabel);
    edit.append(actionButton("上传材料", async () => {
      if (!file.files[0]) throw new Error("请选择要上传的材料");
      const selected = file.files[0];
      await request(`/special-performance-cases/${item.id}/materials/${encodeURIComponent(key.value)}?filename=${encodeURIComponent(selected.name)}`, {
        method: "POST", body: selected, headers: { "Content-Type": selected.type || "application/octet-stream" },
      });
      await loadMyCases(); notice("材料已上传。");
    }, ""));
    edit.append(actionButton("提交审核（提交后不可修改）", async () => {
      await request(`/special-performance-cases/${item.id}/submit`, { method: "POST" });
      await loadMyCases(); notice("已提交审核。");
    }, ""));
    card.append(edit);
  }
  return card;
}

async function loadMyCases() {
  const response = await request("/special-performance-cases/mine");
  $("my-cases").replaceChildren(...response.data.map(memberCaseCard));
}

function adminCaseCard(item) {
  const card = element("article", "record case-record");
  card.append(element("strong", "", `${item.title} · ${item.case_type === "appeal" ? "申诉" : "特殊绩效"} · ${item.status}`));
  card.append(element("code", "", item.id));
  card.append(element("span", "", `${item.teacher_name} · ${item.department_id} · ${item.period_id}${item.overdue ? " · 已逾期" : ""}`));
  card.append(element("pre", "case-json", JSON.stringify({ teacher_id: item.teacher_id, form_data: item.form_data, submitted_snapshot: item.submitted_snapshot, processing_error: item.processing_error }, null, 2)));
  appendMaterials(card, item);
  const actions = element("div", "actions");
  if (item.status === "submitted") {
    actions.append(actionButton("开始处理", async () => {
      await request(`/special-performance-cases/${item.id}/handle`, { method: "POST", body: JSON.stringify({ action: "start_review" }) });
      await loadAdminCases();
    }));
    actions.append(actionButton("打回草稿", async () => {
      const comment = window.prompt("请填写打回原因："); if (!comment) return;
      await request(`/special-performance-cases/${item.id}/handle`, { method: "POST", body: JSON.stringify({ action: "return_to_draft", comment }) });
      await loadAdminCases();
    }));
  }
  if (item.status === "reviewing") {
    const select = document.createElement("select");
    select.append(new Option("选择特殊事项插件", ""));
    for (const plugin of state.plugins.filter((entry) => entry.status === "enabled" && entry.purpose === "special_case")) {
      select.append(new Option(`${plugin.name} · ${plugin.version}`, plugin.id));
    }
    actions.append(select);
    actions.append(actionButton("复核通过并运行插件", async () => {
      if (!select.value) throw new Error("请先配置并启用 purpose=special_case 的插件");
      await request(`/special-performance-cases/${item.id}/review`, { method: "POST", body: JSON.stringify({ action: "approve", plugin_id: select.value }) });
      await loadAdminCases();
    }));
    actions.append(actionButton("复核打回", async () => {
      const comment = window.prompt("请填写打回原因："); if (!comment) return;
      await request(`/special-performance-cases/${item.id}/review`, { method: "POST", body: JSON.stringify({ action: "return_to_draft", comment }) });
      await loadAdminCases();
    }));
  }
  if (item.status === "approved") {
    actions.append(actionButton("运行 / 重试专用插件", async () => {
      await request(`/special-performance-cases/${item.id}/process-plugin`, { method: "POST" });
      await loadAdminCases();
    }));
  }
  if (["submitted", "reviewing"].includes(item.status)) {
    actions.append(actionButton("调整三天时限", async () => {
      const value = window.prompt("输入新的截止时间（ISO 8601，含时区）：", item.review_due_at || ""); if (!value) return;
      const reason = window.prompt("请填写调整原因："); if (!reason) return;
      await request(`/special-performance-cases/${item.id}/deadline`, { method: "PATCH", body: JSON.stringify({ review_due_at: value, reason }) });
      await loadAdminCases();
    }));
  }
  if (actions.childElementCount) card.append(actions);
  return card;
}

async function loadAdminCases() {
  const response = await request("/special-performance-cases");
  $("admin-cases").replaceChildren(...response.data.map(adminCaseCard));
}

async function openConsole() {
  const me = await request("/auth/me");
  state.role = me.role;
  $("login-card").hidden = true; $("console").hidden = false; $("logout").hidden = false;
  $("admin-console").hidden = state.role !== "ADMIN";
  $("member-console").hidden = state.role !== "USER";
  if (state.role === "ADMIN") {
    await Promise.all([loadPlugins(), loadWorkflows()]);
    await loadAdminCases();
  } else await loadMyCases();
  notice(state.role === "ADMIN" ? "已加载管理操作台与特殊事项审核队列。" : "已加载个人申报入口和事项记录。");
}

$("login").onclick = async () => {
  try {
    const data = await request("/auth/login", { method: "POST", body: JSON.stringify({ username: $("username").value, password: $("password").value }) });
    state.token = data.access_token; sessionStorage.setItem("numcounts_token", state.token); await openConsole();
  } catch (error) { notice(error.message, true); }
};
$("logout").onclick = () => { state.token = ""; sessionStorage.removeItem("numcounts_token"); location.reload(); };
$("refresh-plugins").onclick = () => Promise.all([loadPlugins(), loadAdminCases()]).catch((error) => notice(error.message, true));
$("refresh-workflows").onclick = () => loadWorkflows().catch((error) => notice(error.message, true));
$("refresh-my-cases").onclick = () => loadMyCases().catch((error) => notice(error.message, true));
$("refresh-admin-cases").onclick = () => loadAdminCases().catch((error) => notice(error.message, true));
$("case-type").onchange = () => {
  const appeal = $("case-type").value === "appeal";
  $("special-case-fields").hidden = appeal;
  $("appeal-result-field").hidden = !appeal;
};
$("create-case").onclick = async () => {
  try {
    const appeal = $("case-type").value === "appeal";
    const payload = {
      case_type: appeal ? "appeal" : "special_performance",
      title: $("case-title").value,
      form_data: parseJson("case-form-data"),
    };
    if (appeal) payload.original_result_id = $("appeal-result-id").value;
    else Object.assign(payload, {
      period_id: $("case-period").value,
      teacher_name: $("case-teacher-name").value,
      department_id: $("case-department").value,
    });
    await request("/special-performance-cases", { method: "POST", body: JSON.stringify(payload) });
    await loadMyCases(); notice("草稿已创建，请在草稿卡片中补充证明材料后提交。");
  } catch (error) { notice(error.message, true); }
};
$("create-plugin").onclick = async () => { try { await request("/rule-plugins", { method: "POST", body: JSON.stringify(parseJson("plugin-json")) }); await Promise.all([loadPlugins(), loadAdminCases()]); notice("插件版本已创建，请在列表中启用。"); } catch (error) { notice(error.message, true); } };
$("create-workflow").onclick = async () => { try { await request("/workflows", { method: "POST", body: JSON.stringify(parseJson("workflow-json")) }); await loadWorkflows(); notice("工作流草稿已创建，请在列表中启用。"); } catch (error) { notice(error.message, true); } };
$("run-workflow").onclick = async () => { try { const data = await request(`/workflows/${$("run-workflow-id").value}/runs`, { method: "POST", body: JSON.stringify({ period_id: $("run-period").value || null, context: parseJson("run-context") }) }); $("run-result").hidden = false; $("run-result").textContent = JSON.stringify(data, null, 2); notice(`工作流运行结束：${data.status}`); } catch (error) { notice(error.message, true); } };

if (state.token) openConsole().catch((error) => { state.token = ""; sessionStorage.removeItem("numcounts_token"); $("login-card").hidden = false; notice(error.message, true); });

const state = { token: sessionStorage.getItem("numcounts_token") || "" };
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
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
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

function pluginCard(plugin) {
  const item = document.createElement("article");
  item.className = "record";
  item.innerHTML = `<strong>${plugin.name} · ${plugin.version} · ${plugin.status}</strong><code>${plugin.id}</code><span>${plugin.function.kind}: ${plugin.function.name || plugin.function.executor_id}</span>`;
  const actions = document.createElement("div");
  actions.className = "actions";
  const button = document.createElement("button");
  button.textContent = plugin.status === "enabled" ? "停用" : "启用";
  button.className = "ghost";
  button.onclick = async () => {
    try {
      const action = plugin.status === "enabled" ? "disable" : "enable";
      await request(`/rule-plugins/${plugin.id}/${action}`, { method: "POST" });
      await loadPlugins();
    } catch (error) { notice(error.message, true); }
  };
  actions.append(button); item.append(actions); return item;
}

function workflowCard(workflow) {
  const item = document.createElement("article");
  item.className = "record";
  item.innerHTML = `<strong>${workflow.name} · ${workflow.version} · ${workflow.status}</strong><code>${workflow.id}</code><span>${workflow.nodes.length} 个节点：${workflow.nodes.map((node) => node.node_key).join(" → ")}</span>`;
  const actions = document.createElement("div"); actions.className = "actions";
  const action = document.createElement("button");
  action.textContent = workflow.status === "active" ? "停用" : "启用";
  action.className = "ghost";
  action.onclick = async () => {
    try {
      const endpoint = workflow.status === "active" ? "disable" : "activate";
      await request(`/workflows/${workflow.id}/${endpoint}`, { method: "POST" });
      await loadWorkflows();
    } catch (error) { notice(error.message, true); }
  };
  const select = document.createElement("button"); select.textContent = "用于运行"; select.className = "ghost";
  select.onclick = () => { $("run-workflow-id").value = workflow.id; window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); };
  actions.append(action, select); item.append(actions); return item;
}

async function loadPlugins() {
  const plugins = await request("/rule-plugins");
  $("plugins").replaceChildren(...plugins.data.map(pluginCard));
}

async function loadWorkflows() {
  const workflows = await request("/workflows");
  $("workflows").replaceChildren(...workflows.data.map(workflowCard));
}

async function openConsole() {
  $("login-card").hidden = true; $("console").hidden = false; $("logout").hidden = false;
  await Promise.all([loadPlugins(), loadWorkflows()]); notice("已加载插件和工作流。");
}

$("login").onclick = async () => {
  try {
    const data = await request("/auth/login", { method: "POST", body: JSON.stringify({ username: $("username").value, password: $("password").value }) });
    state.token = data.access_token; sessionStorage.setItem("numcounts_token", state.token); await openConsole();
  } catch (error) { notice(error.message, true); }
};
$("logout").onclick = () => { state.token = ""; sessionStorage.removeItem("numcounts_token"); location.reload(); };
$("refresh-plugins").onclick = () => loadPlugins().catch((error) => notice(error.message, true));
$("refresh-workflows").onclick = () => loadWorkflows().catch((error) => notice(error.message, true));
$("create-plugin").onclick = async () => { try { await request("/rule-plugins", { method: "POST", body: JSON.stringify(parseJson("plugin-json")) }); await loadPlugins(); notice("插件版本已创建，请在列表中启用。"); } catch (error) { notice(error.message, true); } };
$("create-workflow").onclick = async () => { try { await request("/workflows", { method: "POST", body: JSON.stringify(parseJson("workflow-json")) }); await loadWorkflows(); notice("工作流草稿已创建，请在列表中启用。"); } catch (error) { notice(error.message, true); } };
$("run-workflow").onclick = async () => { try { const data = await request(`/workflows/${$("run-workflow-id").value}/runs`, { method: "POST", body: JSON.stringify({ period_id: $("run-period").value || null, context: parseJson("run-context") }) }); $("run-result").hidden = false; $("run-result").textContent = JSON.stringify(data, null, 2); notice(`工作流运行结束：${data.status}`); } catch (error) { notice(error.message, true); } };

if (state.token) openConsole().catch((error) => { state.token = ""; sessionStorage.removeItem("numcounts_token"); notice(error.message, true); });

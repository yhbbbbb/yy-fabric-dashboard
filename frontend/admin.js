const permissionLabels = { overview: "总览看板", chain: "链路分析", analytics: "经营分析", orders: "订单查询", quality: "数据质量", admin: "系统管理" };
const $ = (id) => document.getElementById(id);
let users = [];
let roles = [];
let currentUser = null;

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const payload = await response.json();
  if (response.status === 401) { window.location.href = "/login.html"; throw new Error("登录已过期"); }
  if (!response.ok) throw new Error(payload.error || "请求失败");
  return payload;
}

function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); }
function tags(items, system = false) { return items.map((item) => `<span class="tag ${system ? "system" : ""}">${escapeHtml(item)}</span>`).join(""); }

function render() {
  const activeUsers = users.filter((user) => user.active).length;
  const superAdmins = users.filter((user) => user.roles.includes("super_admin")).length;
  const canManage = currentUser?.roles?.includes("super_admin");
  $("new-user").hidden = !canManage;
  $("new-role").hidden = !canManage;
  $("stats").innerHTML = `<div class="stat"><span class="eyebrow">USERS</span><strong>${users.length}</strong><span>平台账号总数</span></div><div class="stat"><span class="eyebrow">ACTIVE</span><strong>${activeUsers}</strong><span>已启用账号</span></div><div class="stat"><span class="eyebrow">SUPER ADMINS</span><strong>${superAdmins}</strong><span>超级管理员</span></div>`;
  $("users").innerHTML = users.map((user) => `<tr><td><strong>${escapeHtml(user.username)}</strong></td><td>${tags(user.role_names || user.roles, user.roles.includes("super_admin")) || "<span class=\"muted\">未分配</span>"}</td><td>${tags(user.permissions.map((permission) => permissionLabels[permission] || permission)) || "<span class=\"muted\">无业务页面</span>"}</td><td><span class="tag ${user.active ? "" : "off"}">${user.active ? "启用" : "停用"}</span></td><td>${user.last_login_at ? new Date(user.last_login_at).toLocaleString("zh-CN") : "未登录"}</td><td>${canManage ? `<div class="row-actions"><button data-edit-user="${user.id}" type="button">编辑</button>${user.username === "admin" ? "" : `<button class="danger" data-delete-user="${user.id}" type="button">删除</button>`}</div>` : ""}</td></tr>`).join("");
  $("roles").innerHTML = roles.map((role) => `<tr><td><strong>${escapeHtml(role.name)}</strong><br><small>${escapeHtml(role.description)}</small></td><td><code>${escapeHtml(role.code)}</code></td><td>${tags(role.permissions.map((permission) => permissionLabels[permission] || permission)) || "<span class=\"muted\">无页面权限</span>"}</td><td>${role.user_count}</td><td><span class="tag ${role.active ? "" : "off"}">${role.active ? "启用" : "停用"}</span></td><td>${canManage ? `<div class="row-actions"><button data-edit-role="${role.id}" type="button">编辑</button>${role.system_role ? "" : `<button class="danger" data-delete-role="${role.id}" type="button">删除</button>`}</div>` : ""}</td></tr>`).join("");
  document.querySelectorAll("[data-edit-user]").forEach((button) => button.addEventListener("click", () => openUser(Number(button.dataset.editUser))));
  document.querySelectorAll("[data-delete-user]").forEach((button) => button.addEventListener("click", () => removeUser(Number(button.dataset.deleteUser))));
  document.querySelectorAll("[data-edit-role]").forEach((button) => button.addEventListener("click", () => openRole(Number(button.dataset.editRole))));
  document.querySelectorAll("[data-delete-role]").forEach((button) => button.addEventListener("click", () => removeRole(Number(button.dataset.deleteRole))));
}

function renderRoleChoices(selected = []) {
  $("role-list").innerHTML = roles.map((role) => `<label class="check"><input type="checkbox" value="${role.id}" ${selected.includes(role.id) ? "checked" : ""} ${role.active ? "" : "disabled"} /> ${escapeHtml(role.name)}</label>`).join("");
}

function renderPermissionChoices(selected = [], locked = false) {
  $("permission-list").innerHTML = Object.entries(permissionLabels).map(([code, label]) => `<label class="check"><input type="checkbox" value="${code}" ${selected.includes(code) ? "checked" : ""} ${locked ? "disabled" : ""} /> ${label}</label>`).join("");
}

function openUser(id = null) {
  const user = users.find((item) => item.id === id);
  $("user-dialog-title").textContent = user ? "编辑用户" : "新增用户";
  $("user-id").value = user?.id || "";
  $("user-name").value = user?.username || "";
  $("user-name").disabled = Boolean(user);
  $("user-password").value = "";
  $("user-active").checked = user?.active ?? true;
  renderRoleChoices(user?.role_ids || []);
  $("user-error").textContent = "";
  $("user-dialog").showModal();
}

function openRole(id = null) {
  const role = roles.find((item) => item.id === id);
  $("role-dialog-title").textContent = role ? "编辑角色" : "新增角色";
  $("role-id").value = role?.id || "";
  $("role-name").value = role?.name || "";
  $("role-code").value = role?.code || "";
  $("role-code").disabled = Boolean(role?.system_role);
  $("role-description").value = role?.description || "";
  $("role-active").checked = role?.active ?? true;
  renderPermissionChoices(role?.permissions || [], role?.code === "super_admin");
  $("role-error").textContent = "";
  $("role-dialog").showModal();
}

async function load() {
  const [session, usersPayload, rolesPayload] = await Promise.all([
    request("/api/auth/me"),
    request("/api/admin/users"),
    request("/api/admin/roles"),
  ]);
  currentUser = session.user;
  users = usersPayload.users;
  roles = rolesPayload.roles;
  $("current-user").textContent = `当前账号：${currentUser.username}`;
  render();
}

async function removeUser(id) {
  if (!window.confirm("确定删除这个账号吗？")) return;
  try { await request("/api/admin/users/delete", { method: "POST", body: JSON.stringify({ id }) }); await load(); } catch (error) { window.alert(error.message); }
}

async function removeRole(id) {
  if (!window.confirm("确定删除这个角色吗？")) return;
  try { await request("/api/admin/roles/delete", { method: "POST", body: JSON.stringify({ id }) }); await load(); } catch (error) { window.alert(error.message); }
}

document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
$("new-user").addEventListener("click", () => openUser());
$("new-role").addEventListener("click", () => openRole());
$("logout").addEventListener("click", async () => { await request("/api/auth/logout", { method: "POST" }); window.location.href = "/login.html"; });
$("user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("user-id").value;
  const role_ids = [...document.querySelectorAll("#role-list input:checked")].map((input) => Number(input.value));
  const body = { username: $("user-name").value, password: $("user-password").value, active: $("user-active").checked, role_ids };
  try {
    await request(id ? "/api/admin/users/update" : "/api/admin/users/create", { method: "POST", body: JSON.stringify(id ? { ...body, id: Number(id) } : body) });
    $("user-dialog").close();
    await load();
  } catch (error) { $("user-error").textContent = error.message; }
});
$("role-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("role-id").value;
  const permissions = [...document.querySelectorAll("#permission-list input:checked")].map((input) => input.value);
  const body = { name: $("role-name").value, code: $("role-code").value, description: $("role-description").value, active: $("role-active").checked, permissions };
  try {
    await request(id ? "/api/admin/roles/update" : "/api/admin/roles/create", { method: "POST", body: JSON.stringify(id ? { ...body, id: Number(id) } : body) });
    $("role-dialog").close();
    await load();
  } catch (error) { $("role-error").textContent = error.message; }
});
load().catch((error) => { if (!error.message.includes("登录已过期")) window.alert(error.message); });

const state = {
  view: "overview",
  page: 1,
  pageSize: 25,
  pageFilters: {},
  trendData: null,
  trendGranularity: "year",
  trendFrom: "",
  trendTo: "",
  trendPeriods: [],
  trendStart: 0,
  trendEnd: 0,
  entityRank: "factory",
  customerRankView: "donut",
};

const $ = (id) => document.getElementById(id);
let currentUser = null;
const VIEW_PERMISSIONS = {
  overview: "overview",
  chain: "chain",
  analytics: "analytics",
  orders: "orders",
  quality: "quality",
};
const FILTER_IDS = {
  buyer: "buyer-filter",
  fabric_source: "fabric-filter",
  chain_state: "state-filter",
  factory: "factory-filter",
  style: "style-filter",
  garment_feature: "garment-feature-filter",
  creator: "creator-filter",
  creator_dept: "creator-dept-filter",
  from: "from-filter",
  to: "to-filter",
};
const PAGE_FILTER_KEYS = {
  overview: ["buyer", "factory", "from", "to"],
  chain: ["buyer", "factory", "from", "to"],
  analytics: ["buyer", "factory", "style", "garment_feature", "creator", "creator_dept", "from", "to"],
  orders: ["buyer", "fabric_source", "chain_state", "factory", "style", "garment_feature", "from", "to"],
  quality: [],
};
let loadingCount = 0;
const viewCache = new Map();
const pendingViewLoads = new Map();
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const number = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
const pct = (value) => `${Number(value || 0).toFixed(2)}%`;
const yyValue = (value) => value == null ? "--" : Number(value).toFixed(4);
const labelState = (value) => ({ full_chain: "Full chain", partial_chain: "Partial", ppo_only: "PPO only", no_ppo: "No PPO" }[value] || value || "未分类");

async function api(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== "" && value != null) query.set(key, value); });
  const response = await fetch(`${path}?${query}`);
  if (response.status === 401) {
    window.location.href = "/login.html";
    throw new Error("登录已过期");
  }
  if (response.status === 403) {
    const error = new Error("forbidden");
    error.status = 403;
    throw error;
  }
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function canView(view) {
  return Boolean(currentUser?.permissions?.includes(VIEW_PERMISSIONS[view]));
}

function firstPermittedView() {
  return Object.keys(VIEW_PERMISSIONS).find((view) => canView(view)) || null;
}

function applyPermissions() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    const allowed = canView(item.dataset.view);
    item.hidden = !allowed;
    item.style.display = allowed ? "" : "none";
  });
  document.querySelectorAll(".view").forEach((item) => {
    const view = item.id.replace("view-", "");
    const allowed = canView(view);
    item.hidden = !allowed;
    item.style.display = allowed ? "" : "none";
  });
  document.querySelectorAll("[data-go-view]").forEach((item) => {
    const allowed = canView(item.dataset.goView);
    item.hidden = !allowed;
    item.style.display = allowed ? "" : "none";
  });
  document.querySelectorAll("[data-analytics-target]").forEach((item) => {
    const allowed = canView("analytics");
    item.hidden = !allowed;
    item.style.display = allowed ? "" : "none";
  });

  const adminEntry = $("admin-entry");
  const isSuperAdmin = currentUser?.roles?.includes("super_admin") === true;
  if (adminEntry) {
    adminEntry.hidden = !isSuperAdmin;
    adminEntry.style.display = isSuperAdmin ? "" : "none";
  }
}

async function loadSession() {
  const response = await fetch("/api/auth/me");
  if (response.status === 401) {
    window.location.href = "/login.html";
    throw new Error("登录已过期");
  }
  if (!response.ok) throw new Error("无法读取登录状态");
  const payload = await response.json();
  currentUser = payload.user;
  applyPermissions();
  return currentUser;
}

function emptyPageFilters() {
  return { ...Object.fromEntries(Object.keys(FILTER_IDS).map((key) => [key, ""])), search: "" };
}

function normalizeDateValue(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const match = text.match(/^(\d{4})\D+(\d{1,2})\D+(\d{1,2})$/);
  if (!match) return "";
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return "";
  return `${year.toString().padStart(4, "0")}-${month.toString().padStart(2, "0")}-${day.toString().padStart(2, "0")}`;
}

function displayDateValue(value) {
  const normalized = normalizeDateValue(value);
  return normalized ? normalized.replaceAll("-", "/") : "";
}

function syncDateInput(id) {
  const input = $(id);
  const raw = input.value.trim();
  const normalized = normalizeDateValue(raw);
  input.classList.toggle("invalid", Boolean(raw) && !normalized);
  if (normalized) input.value = displayDateValue(normalized);
  return !raw || Boolean(normalized);
}

function readPageFilters(view = state.view) {
  const values = state.pageFilters[view] || (state.pageFilters[view] = emptyPageFilters());
  (PAGE_FILTER_KEYS[view] || []).forEach((key) => {
    const input = $(FILTER_IDS[key]);
    values[key] = key === "from" || key === "to" ? normalizeDateValue(input.value) : input.value;
  });
  return values;
}

function writePageFilters(view) {
  const values = state.pageFilters[view] || (state.pageFilters[view] = emptyPageFilters());
  const allowed = PAGE_FILTER_KEYS[view] || [];
  document.querySelectorAll("[data-filter-key]").forEach((field) => {
    field.hidden = !allowed.includes(field.dataset.filterKey);
  });
  $("filters-panel").classList.toggle("is-empty", allowed.length === 0);
  Object.entries(FILTER_IDS).forEach(([key, id]) => {
    const input = $(id);
    input.value = key === "from" || key === "to" ? displayDateValue(values[key]) : values[key] || "";
    input.classList.remove("invalid");
  });
  if ($("order-search")) $("order-search").value = values.search || "";
}

function currentFilters(view = state.view) {
  const values = readPageFilters(view);
  return {
    ...values,
    customer: values.buyer,
    granularity: state.trendGranularity,
    search: values.search || "",
    scope: "main",
  };
}

function setLoading(active) {
  const overlay = $("loading-overlay");
  if (!overlay) return;
  loadingCount = Math.max(0, loadingCount + (active ? 1 : -1));
  const visible = loadingCount > 0;
  overlay.hidden = !visible;
  overlay.setAttribute("aria-busy", String(visible));
}

async function withLoading(task) {
  setLoading(true);
  try {
    return await task();
  } finally {
    setLoading(false);
  }
}

function renderMetrics(data) {
  const items = [
    ["Bulk 订单", number(data.bulk_orders), "Garment Order 去重"],
    ["Bulk → PPO", pct(data.bulk_ppo_rate), `${number(data.bulk_ppo_matched)} 个订单已关联`],
    ["Full chain", pct(data.full_chain_rate), `${number(data.full_chain)} 个完整链路`],
    ["QUO 提交 / 完成", `${number(data.quo_submitted)} / ${number(data.quo_completed)}`, "Completed 数据集"],
    ["PPO 提交 / 完成", `${number(data.ppo_submitted)} / ${number(data.ppo_completed)}`, "Completed 数据集"],
    ["交付日期有效", pct(data.delivery_quality_rate), `${number(data.delivery_dq)} 个异常订单`],
  ];
  $("metric-grid").innerHTML = items.map(([label, value, sub]) => `<article class="metric-card"><div class="metric-label">${label}</div><div class="metric-value">${value}</div><div class="metric-sub">${sub}</div></article>`).join("");
  $("updated-at").textContent = data.latest_available_date ? `数据截至 ${data.latest_available_date}` : "数据更新时间未知";
  const notice = $("yy-notice");
  notice.textContent = data.yy_metrics_note;
  notice.classList.add("show");
}

function renderStateRows(id, states) {
  const target = $(id);
  if (!target) return;
  const total = states.reduce((sum, item) => sum + Number(item.count), 0) || 1;
  target.innerHTML = states.map((item) => {
    const value = Number(item.count);
    const cls = item.state === "full_chain" ? "" : item.state === "no_ppo" ? "danger" : "warning";
    return `<div class="state-row"><div class="state-top"><span>${esc(labelState(item.state))}</span><b>${number(value)} · ${pct(value / total * 100)}</b></div><div class="bar-track"><div class="bar-fill ${cls}" style="width:${value / total * 100}%"></div></div></div>`;
  }).join("");
}

function renderStates(states) {
  renderStateRows("state-list", states);
  const bars = $("chain-state-bars");
  if (!bars) return;
  const total = states.reduce((sum, item) => sum + Number(item.count), 0) || 1;
  bars.innerHTML = states.map((item) => {
    const value = Number(item.count);
    const cls = item.state.replace("_", " ").split(" ")[0];
    return `<div class="state-bar-row"><span>${esc(labelState(item.state))}</span><div class="state-bar-track"><div class="state-bar-fill ${cls}" style="width:${value / total * 100}%"></div></div><b>${number(value)}</b></div>`;
  }).join("");
}

function renderRanking(id, items) {
  const max = Math.max(...items.map((item) => Number(item.count)), 1);
  $(id).innerHTML = items.slice(0, 7).map((item) => `<div class="rank-row"><div class="rank-top"><span title="${esc(item.name)}">${esc(item.name)}</span><b>${number(item.count)}</b></div><div class="rank-track"><div class="rank-fill" style="width:${Number(item.count) / max * 100}%"></div></div></div>`).join("");
}

function donutShortName(name) {
  const text = String(name || "未填写").trim();
  if (/[\u4e00-\u9fff]/.test(text)) return text.replace(/\s+/g, "").slice(0, 2);
  return text.split(/\s+/)[0].slice(0, 12);
}

function polarPoint(cx, cy, radius, angle) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

function donutArcPath(cx, cy, outer, inner, start, end) {
  const [x1, y1] = polarPoint(cx, cy, outer, start);
  const [x2, y2] = polarPoint(cx, cy, outer, end);
  const [x3, y3] = polarPoint(cx, cy, inner, end);
  const [x4, y4] = polarPoint(cx, cy, inner, start);
  const large = end - start > Math.PI ? 1 : 0;
  return `M ${x1} ${y1} A ${outer} ${outer} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${inner} ${inner} 0 ${large} 0 ${x4} ${y4} Z`;
}

function renderCustomerRanking(items) {
  if (state.customerRankView !== "donut") {
    renderRanking("buyer-ranking", items);
    return;
  }
  const top = items.slice(0, 6).map((item) => ({ name: item.name, count: Number(item.count || 0) }));
  const topTotal = top.reduce((sum, item) => sum + item.count, 0);
  const fullTotal = items.reduce((sum, item) => sum + Number(item.count || 0), 0) || 1;
  if (fullTotal > topTotal) top.push({ name: "其他客户", count: fullTotal - topTotal });
  const colors = ["#0096bf", "#00627f", "#33bfd3", "#1b9a78", "#d58b26", "#718094", "#dfe6ed"];
  const cx = 140;
  const cy = 110;
  const outer = 70;
  const inner = 45;
  const labelRadius = 94;
  let angle = -Math.PI / 2;
  const segments = [];
  const labels = [];
  top.forEach((item, index) => {
    const percent = item.count / fullTotal * 100;
    const end = angle + Math.max(percent / 100 * Math.PI * 2, 0.002);
    const mid = (angle + end) / 2;
    const [lx, ly] = polarPoint(cx, cy, labelRadius, mid);
    segments.push(`<path class="donut-segment" d="${donutArcPath(cx, cy, outer, inner, angle, end)}" fill="${colors[index % colors.length]}" data-name="${esc(item.name)}" data-percent="${percent.toFixed(2)}"><title>${esc(item.name)} ${pct(percent)}</title></path>`);
    labels.push(`<text class="donut-label-text" x="${lx}" y="${ly}" text-anchor="${lx < cx - 8 ? "end" : lx > cx + 8 ? "start" : "middle"}">${esc(donutShortName(item.name))}</text>`);
    angle = end;
  });
  $("buyer-ranking").innerHTML = `<div class="donut-wrap">
    <svg class="donut-chart" viewBox="0 0 280 220" role="img" aria-label="客户订单占比圆环图">
      <circle cx="${cx}" cy="${cy}" r="${outer}" fill="none" stroke="#edf3f6" stroke-width="${outer - inner}" />
      ${segments.join("")}
      ${labels.join("")}
      <text x="${cx}" y="${cy - 2}" text-anchor="middle" class="donut-total">${number(fullTotal)}</text>
      <text x="${cx}" y="${cy + 18}" text-anchor="middle" class="donut-label">订单</text>
    </svg>
    <div class="donut-tooltip" id="donut-tooltip"></div>
  </div>`;
  document.querySelectorAll(".donut-segment").forEach((segment) => {
    const show = (event) => {
      const tooltip = $("donut-tooltip");
      const wrap = segment.closest(".donut-wrap");
      const rect = wrap.getBoundingClientRect();
      tooltip.innerHTML = `<strong>${esc(segment.dataset.name)}</strong><span>${segment.dataset.percent}% · ${number(top.find((item) => item.name === segment.dataset.name)?.count || 0)} 单</span>`;
      tooltip.classList.add("show");
      tooltip.style.left = `${Math.min(rect.width - 156, Math.max(8, event.clientX - rect.left + 8))}px`;
      tooltip.style.top = `${Math.max(8, event.clientY - rect.top - 18)}px`;
    };
    segment.addEventListener("mouseenter", show);
    segment.addEventListener("mousemove", show);
    segment.addEventListener("mouseleave", () => $("donut-tooltip").classList.remove("show"));
  });
}

function trendLabel(period, granularity, index, periods) {
  if (!period) return "";
  if (granularity === "year") return period.slice(0, 4);
  if (granularity === "month") {
    return period.endsWith("-01") || index === 0 ? period.slice(0, 4) : "";
  }
  const month = period.slice(0, 7);
  const previous = periods[index - 1] ? periods[index - 1].slice(0, 7) : "";
  return index === 0 || month !== previous ? month : "";
}

function renderTrend(data) {
  state.trendData = data;
  const stage = new Map(data.stage.map((item) => [item.period, item]));
  const bulk = new Map(data.bulk.map((item) => [item.period, item]));
  const periods = [...new Set([...stage.keys(), ...bulk.keys()])].sort();
  state.trendPeriods = periods;
  if (!periods.length) {
    $("trend-chart").innerHTML = `<div class="empty-state"><strong>暂无趋势数据</strong></div>`;
    return;
  }
  const maxIndex = periods.length - 1;
  const windowSize = data.granularity === "month" ? 15 : data.granularity === "day" ? 30 : maxIndex + 1;
  state.trendEnd = maxIndex;
  state.trendStart = Math.max(0, maxIndex - windowSize + 1);
  document.querySelectorAll("[data-trend-granularity]").forEach((button) => button.classList.toggle("active", button.dataset.trendGranularity === data.granularity));
  renderTrendWindow();
}

function renderTrendWindow() {
  const data = state.trendData;
  if (!data) return;
  const stage = new Map(data.stage.map((item) => [item.period, item]));
  const bulk = new Map(data.bulk.map((item) => [item.period, item]));
  const allPeriods = [...new Set([...stage.keys(), ...bulk.keys()])].sort();
  const start = Math.max(0, Math.min(Number(state.trendStart), allPeriods.length - 1));
  const end = Math.max(start, Math.min(Number(state.trendEnd), allPeriods.length - 1));
  const periods = allPeriods.slice(start, end + 1);
  const rows = periods.map((period) => {
    const s = stage.get(period) || {};
    const b = bulk.get(period) || {};
    return {
      period,
      submitted: Number(s.quo_submitted || 0) + Number(s.ppo_submitted || 0),
      completed: Number(s.quo_completed || 0) + Number(s.ppo_completed || 0),
      bulk: Number(b.bulk_orders || 0),
    };
  });
  const max = Math.max(...rows.flatMap((row) => [row.submitted, row.completed, row.bulk]), 1);
  const width = Math.max(760, rows.length * 58);
  const height = 240;
  const left = 42;
  const right = 22;
  const top = 18;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const x = (index) => left + (rows.length === 1 ? plotWidth / 2 : index / (rows.length - 1) * plotWidth);
  const y = (value) => top + plotHeight - value / max * plotHeight;
  const line = (key) => rows.map((row, index) => `${x(index)},${y(row[key])}`).join(" ");
  const area = (key) => `${left},${top + plotHeight} ${line(key)} ${left + plotWidth},${top + plotHeight}`;
  const grid = [0, .25, .5, .75, 1].map((ratio) => {
    const yy = top + plotHeight * ratio;
    return `<line x1="${left}" y1="${yy}" x2="${left + plotWidth}" y2="${yy}" class="chart-grid-line"/><text x="${left - 8}" y="${yy + 4}" text-anchor="end" class="chart-axis-label">${number(Math.round(max * (1 - ratio)))}</text>`;
  }).join("");
  const points = (key, cls) => rows.map((row, index) => `<circle class="trend-point ${cls}" cx="${x(index)}" cy="${y(row[key])}" r="4" data-index="${index}" data-key="${key}"><title>${esc(row.period)} · ${number(row[key])}</title></circle>`).join("");
  const labels = rows.map((row, index) => {
    const label = trendLabel(row.period, data.granularity, index, periods);
    return label ? `<text x="${x(index)}" y="${height - 8}" text-anchor="middle" class="chart-axis-label">${esc(label)}</text>` : "";
  }).join("");
  $("trend-chart").innerHTML = `<div class="line-chart-scroll"><svg class="trend-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="订单趋势曲线">
    ${grid}
    <polygon points="${area("submitted")}" class="trend-area submitted-area"/>
    <polygon points="${area("completed")}" class="trend-area completed-area"/>
    <polygon points="${area("bulk")}" class="trend-area bulk-area"/>
    <polyline points="${line("submitted")}" class="trend-line submitted-line"/>
    <polyline points="${line("completed")}" class="trend-line completed-line"/>
    <polyline points="${line("bulk")}" class="trend-line bulk-line"/>
    ${points("submitted", "submitted-point")}${points("completed", "completed-point")}${points("bulk", "bulk-point")}${labels}
  </svg><div class="trend-tooltip" id="trend-tooltip"></div></div>`;
  $("trend-window-label").textContent = `${rows[0].period} 至 ${rows[rows.length - 1].period} · ${number(rows.length)} 个时间点`;
  document.querySelectorAll(".trend-point").forEach((point) => {
    point.addEventListener("mouseenter", (event) => {
      const index = Number(event.currentTarget.dataset.index);
      const row = rows[index];
      const tooltip = $("trend-tooltip");
      tooltip.innerHTML = `<strong>${esc(row.period)}</strong><span>提交 ${number(row.submitted)}</span><span>完成 ${number(row.completed)}</span><span>Bulk ${number(row.bulk)}</span>`;
      tooltip.classList.add("show");
      tooltip.style.left = `${Math.min(82, Math.max(8, x(index) / width * 100))}%`;
    });
    point.addEventListener("mouseleave", () => $("trend-tooltip").classList.remove("show"));
  });
  attachTrendInteractions(rows.length);
}

function setTrendWindow(start, end) {
  const total = state.trendPeriods.length;
  if (!total) return;
  const nextStart = Math.max(0, Math.min(Number(start), total - 1));
  const nextEnd = Math.max(nextStart, Math.min(Number(end), total - 1));
  state.trendStart = nextStart;
  state.trendEnd = nextEnd;
  renderTrendWindow();
}

function zoomTrend(factor) {
  const total = state.trendPeriods.length;
  if (!total) return;
  const currentSize = Math.max(1, state.trendEnd - state.trendStart + 1);
  const nextSize = Math.max(2, Math.min(total, Math.round(currentSize * factor)));
  if (nextSize === currentSize) return;
  const center = (state.trendStart + state.trendEnd) / 2;
  let nextStart = Math.round(center - (nextSize - 1) / 2);
  nextStart = Math.max(0, Math.min(nextStart, total - nextSize));
  setTrendWindow(nextStart, nextStart + nextSize - 1);
}

function panTrend(direction) {
  const total = state.trendPeriods.length;
  if (!total) return;
  const size = Math.max(1, state.trendEnd - state.trendStart + 1);
  const step = Math.max(1, Math.round(size * 0.6));
  const nextStart = Math.max(0, Math.min(state.trendStart + direction * step, total - size));
  setTrendWindow(nextStart, nextStart + size - 1);
}

function attachTrendInteractions(rowCount) {
  const container = document.querySelector(".line-chart-scroll");
  const svg = container?.querySelector(".trend-svg");
  if (!container || !svg) return;
  let pointerStart = null;
  let pointerId = null;
  let initialStart = 0;
  let initialEnd = 0;
  let moved = false;

  container.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomTrend(event.deltaY < 0 ? 0.75 : 1.35);
  }, { passive: false });

  container.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    pointerStart = event.clientX;
    initialStart = state.trendStart;
    initialEnd = state.trendEnd;
    moved = false;
    pointerId = event.pointerId;
    container.classList.add("dragging");
    const moveDrag = (moveEvent) => {
      if (pointerStart == null || moveEvent.pointerId !== pointerId) return;
      const distance = moveEvent.clientX - pointerStart;
      if (Math.abs(distance) < 4 && !moved) return;
      moved = true;
      const pixelsPerPoint = Math.max(18, svg.getBoundingClientRect().width / Math.max(rowCount - 1, 1));
      const shift = Math.round(-distance / pixelsPerPoint);
      setTrendWindow(initialStart + shift, initialEnd + shift);
    };
    const finishDrag = (finishEvent) => {
      if (pointerStart == null || finishEvent.pointerId !== pointerId) return;
      container.classList.remove("dragging");
      pointerStart = null;
      pointerId = null;
      document.removeEventListener("pointermove", moveDrag);
      document.removeEventListener("pointerup", finishDrag);
      document.removeEventListener("pointercancel", finishDrag);
    };
    document.addEventListener("pointermove", moveDrag);
    document.addEventListener("pointerup", finishDrag);
    document.addEventListener("pointercancel", finishDrag);
  });
}

async function loadOverview(view = state.view) {
  return withLoading(async () => {
    const filters = currentFilters(view);
    const trendFilters = { ...filters, from: state.trendFrom, to: state.trendTo, granularity: state.trendGranularity };
    const [summary, trend, rankings] = await Promise.all([api("/api/summary", filters), api("/api/trend", trendFilters), api("/api/rankings", filters)]);
    renderMetrics(summary);
    renderStates(summary.states);
    renderTrend(trend);
    renderCustomerRanking(rankings.buyers);
    renderRanking("factory-ranking", rankings.factories);
    renderRanking("style-ranking", rankings.styles);
    $("chain-bulk-rate").textContent = pct(summary.bulk_ppo_rate);
    $("chain-full-rate").textContent = pct(summary.full_chain_rate);
    $("chain-bulk-progress").style.width = `${summary.bulk_ppo_rate}%`;
    $("chain-full-progress").style.width = `${summary.full_chain_rate}%`;
    $("chain-bulk-count").textContent = number(summary.bulk_ppo_matched);
    $("chain-total-count").textContent = number(summary.bulk_orders);
    $("chain-full-count").textContent = number(summary.full_chain);
  });
}

function renderSelect(id, values, first) {
  $(id).innerHTML = `<option value="">${first}</option>` + values.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
}

async function loadFilters() {
  const data = await api("/api/filters");
  renderSelect("buyer-filter", data.buyers, "全部客户");
  renderSelect("fabric-filter", data.fabric_sources, "全部来源");
  renderSelect("state-filter", data.chain_states, "全部状态");
  renderSelect("factory-filter", data.factories, "全部工厂");
  renderSelect("style-filter", data.styles, "全部款式");
  renderSelect("garment-feature-filter", data.garment_features, "全部 Garment Feature");
  renderSelect("creator-filter", data.creators, "全部 Creator");
  renderSelect("creator-dept-filter", data.creator_depts, "全部部门");
}

function renderAnalytics(data) {
  const bulk = data.bulk_yy || {};
  const chain = data.chain_yy || {};
  const stageMap = Object.fromEntries((data.yy_stage || []).map((item) => [item.stage, item]));
  const cards = [
    ["QUO 平均完成", `${data.durations.quo.avg_hours ?? "--"} h`, `中位数 ${data.durations.quo.median_hours ?? "--"} h · P90 ${data.durations.quo.p90_hours ?? "--"} h`],
    ["PPO 平均完成", `${data.durations.ppo.avg_hours ?? "--"} h`, `中位数 ${data.durations.ppo.median_hours ?? "--"} h · P90 ${data.durations.ppo.p90_hours ?? "--"} h`],
    ["QUO 平均 YY", stageMap.QUO?.avg_yy ?? "--", `${number(stageMap.QUO?.sample_count)} 条有效样本`],
    ["PPO 平均 YY", stageMap.PPO?.avg_yy ?? "--", `${number(stageMap.PPO?.sample_count)} 条有效样本`],
    ["Bulk 平均 YY", bulk.avg_yy ?? "--", `${number(bulk.sample_count)} 条有效样本`],
    ["估算节省码数", number(chain.estimated_saved_yds), "正数节省，负数超耗"],
  ];
  $("analytics-metrics").innerHTML = cards.map(([label, value, sub]) => `<article class="metric-card"><div class="metric-label">${label}</div><div class="metric-value">${value}</div><div class="metric-sub">${sub}</div></article>`).join("");
  $("customer-analytics-body").innerHTML = data.customers.map((item) => `<tr>
    <td title="${esc(item.name)}">${esc(item.name)}</td><td>${number(item.order_count)}</td><td>${number(item.order_pieces)}</td>
    <td>${item.deal_rate == null ? "--" : pct(item.deal_rate)}</td><td>${item.rebuy_rate == null ? "--" : pct(item.rebuy_rate)}</td>
    <td class="${Number(item.yy_delta) >= 0 ? "positive" : "negative"}">${item.yy_delta == null ? "--" : Number(item.yy_delta).toFixed(4)}</td>
    <td class="${Number(item.estimated_saved_yds) >= 0 ? "positive" : "negative"}">${number(item.estimated_saved_yds)}</td>
    <td>${number(item.wastage_yds)}</td>
  </tr>`).join("") || `<tr><td colspan="8">暂无客户分析数据</td></tr>`;
  $("yy-stage-list").innerHTML = [
    ["QUO YY - PPO YY", chain.quo_minus_ppo],
    ["PPO YY - Bulk YY", chain.ppo_minus_bulk],
    ["QUO YY - Bulk YY", chain.quo_minus_bulk],
    ["加权 YY 减少", chain.ppo_minus_bulk],
    ["估算节省码数", chain.estimated_saved_yds],
  ].map(([label, value]) => `<div class="yy-stage-row"><span>${label}</span><b class="${Number(value) >= 0 ? "positive" : "negative"}">${value == null ? "--" : number(value)}</b></div>`).join("");
  $("duration-grid").innerHTML = [data.durations.quo, data.durations.ppo].map((item) => `<div class="duration-card"><span>${item.stage === "QUO" ? "QUO" : "PPO"}</span><b>${item.avg_hours ?? "--"}h</b><small>中位数 ${item.median_hours ?? "--"}h</small><small>P90 ${item.p90_hours ?? "--"}h</small></div>`).join("");
  renderEntityRanking(data.rankings[state.entityRank] || []);
  $("timeout-body").innerHTML = data.timeouts.map((item) => `<tr><td>${esc(item.workflow_no)}</td><td><span class="state-pill">${esc(item.stage)}</span></td><td>${esc(item.customer_name)}</td><td>${esc(item.factory_cd)}</td><td>${esc(item.creator)}</td><td>${esc(item.style_no)}</td><td class="negative">${number(item.duration_hours)} h</td></tr>`).join("") || `<tr><td colspan="7">暂无超时 Workflow</td></tr>`;
  const workflowVolume = data.volume?.workflow || [];
  const bulkVolume = data.volume?.bulk || {};
  $("volume-summary").innerHTML = workflowVolume.map((item) => `<div class="volume-row"><span>${esc(item.stage)}</span><b>${number(item.order_count)}</b><small>接收 ${number(item.submitted_count)} · 完成 ${number(item.completed_count)}</small></div>`).join("") + `<div class="volume-row"><span>Bulk</span><b>${number(bulkVolume.order_count)}</b><small>有效交付日期 ${number(bulkVolume.valid_delivery_count)} · 异常 ${number(bulkVolume.invalid_delivery_count)}</small></div>`;
  $("validity-summary").innerHTML = [
    ["Bulk YY", bulk.sample_count],
    ["QUO YY", stageMap.QUO?.sample_count],
    ["PPO YY", stageMap.PPO?.sample_count],
    ["Full chain YY", chain.sample_count],
    ["有效损耗码数", bulk.cutting_wastage_yds == null ? "--" : number(bulk.cutting_wastage_yds)],
  ].map(([label, value]) => `<div class="validity-row"><span>${label}</span><b>${value === "--" ? value : number(value)}</b></div>`).join("");
  const definitionLabels = [
    ["deal_rate", "成交率"],
    ["rebuy_rate", "复购率"],
    ["yy_saving_overuse", "YY 节省 / 超耗"],
    ["wastage_yds", "损耗码数"],
    ["avg_duration", "平均完成时长"],
    ["median_p90", "中位数 / P90"],
  ];
  $("definition-list").innerHTML = definitionLabels.map(([key, label]) => `<div class="definition-item"><strong>${label}</strong><span>${esc(data.definitions?.[key] || "暂无口径说明")}</span></div>`).join("");
}

function renderEntityRanking(items) {
  const max = Math.max(...items.map((item) => Number(item.workflow_count)), 1);
  $("entity-ranking").innerHTML = items.map((item) => `<div class="entity-row"><div class="entity-main"><strong title="${esc(item.name)}">${esc(item.name)}</strong><span>${number(item.workflow_count)} Workflow · 平均 ${item.avg_duration_hours ?? "--"}h · YY ${item.avg_yy ?? "--"}</span></div><div class="rank-track"><div class="rank-fill" style="width:${Number(item.workflow_count) / max * 100}%"></div></div></div>`).join("");
}

async function loadAnalytics() {
  return withLoading(async () => {
    const data = await api("/api/analytics", currentFilters("analytics"));
    renderAnalytics(data);
  });
}

function highlightPanel(panel) {
  if (!panel) return;
  panel.classList.remove("focus-highlight");
  void panel.offsetWidth;
  panel.classList.add("focus-highlight");
  window.setTimeout(() => panel.classList.remove("focus-highlight"), 1400);
}

async function goAnalyticsTarget(target) {
  if (target === "factory") {
    state.entityRank = "factory";
    document.querySelectorAll("[data-rank]").forEach((item) => item.classList.toggle("active", item.dataset.rank === "factory"));
  }
  await setView("analytics");
  const panel = target === "customer" ? $("customer-analysis-panel") : $("entity-analysis-panel");
  panel?.scrollIntoView({ behavior: "smooth", block: "start" });
  highlightPanel(panel);
}

async function loadOrders() {
  return withLoading(async () => {
    const filters = { ...currentFilters("orders"), page: state.page, page_size: state.pageSize };
    const data = await api("/api/orders", filters);
    $("order-count").textContent = `共 ${number(data.total)} 个订单`;
    $("page-info").textContent = `${data.page} / ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
    $("prev-page").disabled = data.page <= 1;
    $("next-page").disabled = data.page >= Math.ceil(data.total / data.page_size);
    $("orders-body").innerHTML = data.items.map((item) => `<tr>
    <td><button class="link-btn trace-btn" data-go="${esc(item.garment_order)}">${esc(item.garment_order)}</button></td>
    <td title="${esc(item.buyer)}">${esc(item.buyer || "未填写")}</td>
    <td>${esc(item.delivery_date || "未填写")}<br><small class="muted">${esc(item.delivery_date_status)}</small></td>
    <td>${esc(item.fabric_source || "未填写")}${Number(item.is_outside) ? '<br><small class="outside-label">Outside</small>' : ""}</td>
    <td><span class="state-pill ${esc(item.chain_state)}">${esc(labelState(item.chain_state))}</span></td>
    <td>${yyValue(item.quo_marker_yy)}</td><td>${yyValue(item.ppo_marker_yy)}</td><td>${yyValue(item.bulk_marker_yy)}</td>
    <td class="${Number(item.quo_minus_ppo_marker_yy) >= 0 ? "positive" : "negative"}">${yyValue(item.quo_minus_ppo_marker_yy)}</td>
    <td class="${Number(item.ppo_minus_bulk_marker_yy) >= 0 ? "positive" : "negative"}">${yyValue(item.ppo_minus_bulk_marker_yy)}</td>
    <td class="${Number(item.quo_minus_bulk_marker_yy) >= 0 ? "positive" : "negative"}">${yyValue(item.quo_minus_bulk_marker_yy)}</td>
    <td><button class="link-btn trace-btn" data-go="${esc(item.garment_order)}">查看链路及信息</button></td>
    </tr>`).join("") || `<tr><td colspan="12"><div class="empty-state compact"><strong>没有符合条件的订单</strong></div></td></tr>`;
    document.querySelectorAll(".trace-btn").forEach((button) => button.addEventListener("click", () => openTrace(button.dataset.go)));
  });
}

async function openTrace(go) {
  return withLoading(async () => {
    const data = await api("/api/chain", { garment_order: go });
    $("drawer-title").textContent = go;
    if (!data.bulk) {
      $("drawer-content").innerHTML = `<div class="empty-state"><strong>未找到订单</strong></div>`;
    } else {
      const bulk = data.bulk;
      $("drawer-content").innerHTML = `
      <section class="trace-section"><h3>Bulk 订单</h3><div class="trace-grid">
        <div class="trace-item"><span>客户</span><strong>${esc(bulk.buyer)}</strong></div>
        <div class="trace-item"><span>交付日期</span><strong>${esc(bulk.delivery_date || "未填写")}</strong></div>
        <div class="trace-item"><span>面料来源</span><strong>${esc(bulk.fabric_source || "未填写")}</strong></div>
        <div class="trace-item"><span>链路状态</span><strong>${esc(labelState(bulk.chain_state))}</strong></div>
        <div class="trace-item"><span>Order Quantity</span><strong>${esc(bulk.order_quantity ?? "不可计算")}</strong></div>
        <div class="trace-item"><span>Cut Quantity</span><strong>${esc(bulk.cut_quantity ?? "不可计算")}</strong></div>
      </div></section>
      <section class="trace-section"><h3>关联链路</h3>${data.details.length ? data.details.map((item) => `<div class="trace-section">
        <div class="trace-grid">
          <div class="trace-item"><span>PPO WorkflowNo</span><strong>${esc(item.ppo_workflow_no || "未关联")}</strong></div>
          <div class="trace-item"><span>QUO WorkflowNo</span><strong>${esc(item.quo_workflow_no || "未关联")}</strong></div>
          <div class="trace-item"><span>StyleNo</span><strong>${esc(item.style_no || "未填写")}</strong></div>
          <div class="trace-item"><span>QUO / PPO / Bulk Marker YY</span><strong>${yyValue(item.quo_marker_yy)} / ${yyValue(item.ppo_marker_yy_workflow)} / ${yyValue(item.bulk_marker_yy)}</strong></div>
          <div class="trace-item"><span>YY 差异（QUO-PPO / PPO-Bulk / QUO-Bulk）</span><strong>${yyValue(item.yy_variance_quo_ppo)} / ${yyValue(item.yy_variance_ppo_bulk)} / ${yyValue(item.yy_variance_quo_bulk)}</strong></div>
          <div class="trace-item"><span>匹配规则</span><strong>${esc(item.match_method || "未填写")}</strong></div>
        </div>
      </div>`).join("") : `<div class="empty-state compact"><strong>暂未找到 PPO</strong><p>该订单保留在数据集中，可在数据质量或业务复核工作台继续处理。</p></div>`}</section>`;
    }
    $("drawer-backdrop").classList.add("open");
    $("chain-drawer").classList.add("open");
    document.body.classList.add("drawer-open");
  });
}

function closeDrawer() {
  $("drawer-backdrop").classList.remove("open");
  $("chain-drawer").classList.remove("open");
  document.body.classList.remove("drawer-open");
}

async function loadQuality() {
  return withLoading(async () => {
    const data = await api("/api/data-quality", currentFilters("quality"));
    $("quality-summary").innerHTML = data.summary.map((item) => `<div class="quality-card"><span>${esc(item.issue_type)}</span><strong>${number(item.count)}</strong><small>${esc(item.severity)}</small></div>`).join("") || `<div class="empty-state compact"><strong>暂无质量问题记录</strong></div>`;
    $("quality-body").innerHTML = data.items.map((item) => `<tr><td>${esc(item.entity_type)}</td><td>${esc(item.entity_id)}</td><td>${esc(item.issue_type)}</td><td>${esc(item.severity)}</td><td>${esc(item.field_name)}</td><td>${esc(item.raw_value)}</td><td>${esc(item.description)}</td><td>${esc(item.suggestion)}</td></tr>`).join("");
    renderStateRows("quality-chain-state-list", data.states || []);
  });
}

function viewDataKey(view) {
  const dataView = view === "chain" ? "overview" : view;
  return JSON.stringify({
    view: dataView,
    filters: currentFilters(view),
    trendFrom: state.trendFrom,
    trendTo: state.trendTo,
    trendGranularity: state.trendGranularity,
    page: dataView === "orders" ? state.page : null,
  });
}

async function loadView(view, force = false) {
  const key = viewDataKey(view);
  if (!force && viewCache.has(key)) return viewCache.get(key);
  if (!force && pendingViewLoads.has(key)) return pendingViewLoads.get(key);
  const request = (async () => {
    if (view === "overview" || view === "chain") await loadOverview(view);
    if (view === "analytics") await loadAnalytics();
    if (view === "orders") await loadOrders();
    if (view === "quality") await loadQuality();
    viewCache.set(key, true);
    return true;
  })();
  pendingViewLoads.set(key, request);
  try {
    return await request;
  } finally {
    pendingViewLoads.delete(key);
  }
}

async function setView(view) {
  if (!canView(view)) {
    const fallback = firstPermittedView();
    if (fallback && fallback !== view) return setView(fallback);
    return;
  }
  closeDrawer();
  readPageFilters(state.view);
  state.view = view;
  writePageFilters(view);
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  document.querySelectorAll(".view").forEach((item) => item.classList.toggle("active", item.id === `view-${view}`));
  $("page-title").textContent = ({ overview: "总览看板", chain: "链路分析", analytics: "经营分析", orders: "订单查询", quality: "数据质量" })[view];
  $("sidebar").classList.remove("open");
  await loadView(view).catch((error) => console.error(error));
}

function bind() {
  document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
  document.querySelectorAll("[data-analytics-target]").forEach((panel) => {
    panel.addEventListener("click", () => goAnalyticsTarget(panel.dataset.analyticsTarget));
    panel.addEventListener("keydown", (event) => {
      if (event.target.closest("[data-customer-view]")) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        goAnalyticsTarget(panel.dataset.analyticsTarget);
      }
    });
  });
  document.querySelectorAll("[data-customer-view]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    state.customerRankView = button.dataset.customerView;
    document.querySelectorAll("[data-customer-view]").forEach((item) => item.classList.toggle("active", item === button));
    loadOverview();
  }));
  Object.entries(FILTER_IDS).forEach(([key, id]) => {
    const input = $(id);
    if (key === "from" || key === "to") {
      input.addEventListener("blur", () => syncDateInput(id));
    }
    input.addEventListener("change", () => {
      if ((key === "from" || key === "to") && !syncDateInput(id)) return;
      readPageFilters(state.view);
      state.page = 1;
      state.trendStart = 0;
      state.trendEnd = 0;
      loadView(state.view, true);
    });
  });
  $("reset-filters").addEventListener("click", () => {
    state.pageFilters[state.view] = emptyPageFilters();
    writePageFilters(state.view);
    state.page = 1;
    loadView(state.view, true);
  });
  $("refresh").addEventListener("click", () => loadView(state.view, true));
  $("load-orders").addEventListener("click", () => loadOrders());
  $("prev-page").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; loadOrders(); } });
  $("next-page").addEventListener("click", () => { state.page += 1; loadOrders(); });
  let searchTimer;
  $("order-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const values = state.pageFilters.orders || (state.pageFilters.orders = emptyPageFilters());
      values.search = event.target.value.trim();
      state.page = 1;
      loadOrders();
    }, 250);
  });
  $("mobile-menu").addEventListener("click", () => $("sidebar").classList.toggle("open"));
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-back").addEventListener("click", closeDrawer);
  $("drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawer();
  });
  ["trend-from-filter", "trend-to-filter"].forEach((id) => {
    $(id).addEventListener("blur", () => syncDateInput(id));
    $(id).addEventListener("change", () => {
    if (!syncDateInput(id)) return;
    state.trendFrom = normalizeDateValue($("trend-from-filter").value);
    state.trendTo = normalizeDateValue($("trend-to-filter").value);
    state.trendStart = 0;
    state.trendEnd = 0;
    loadOverview();
    });
  });
  document.querySelectorAll("[data-trend-granularity]").forEach((button) => button.addEventListener("click", () => {
    state.trendGranularity = button.dataset.trendGranularity;
    state.trendStart = 0;
    state.trendEnd = 0;
    loadOverview();
  }));
  $("trend-zoom-in").addEventListener("click", () => zoomTrend(0.7));
  $("trend-zoom-out").addEventListener("click", () => zoomTrend(1.4));
  $("trend-pan-left").addEventListener("click", () => panTrend(-1));
  $("trend-pan-right").addEventListener("click", () => panTrend(1));
  document.querySelectorAll("[data-go-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.goView)));
  document.querySelectorAll("[data-rank]").forEach((button) => button.addEventListener("click", () => {
    state.entityRank = button.dataset.rank;
    document.querySelectorAll("[data-rank]").forEach((item) => item.classList.toggle("active", item === button));
    loadAnalytics();
  }));
}

async function init() {
  bind();
  await loadSession();
  const initialView = firstPermittedView();
  if (!initialView) {
    document.querySelectorAll(".view").forEach((item) => { item.hidden = true; });
    $("filters-panel").hidden = true;
    $("metric-grid").innerHTML = `<div class="empty-state"><strong>暂无可用工作台</strong></div>`;
    return;
  }
  state.view = initialView;
  await withLoading(async () => {
    await loadFilters();
  });
  writePageFilters(initialView);
  await setView(initialView);
}

init().catch((error) => {
  console.error(error);
  $("metric-grid").innerHTML = `<div class="notice show">页面加载失败：${esc(error.message)}。请确认数据库已构建且后端服务已启动。</div>`;
});

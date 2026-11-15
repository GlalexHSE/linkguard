const $ = (id) => document.getElementById(id);
const STATUS = { clean: "безопасна", malicious: "опасна", pending: "проверяется" };

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || res.status);
  return data;
}

function cell(text, cls) {
  const td = document.createElement("td");
  if (cls) td.className = cls;
  td.textContent = text;
  return td;
}

function renderLinks(links) {
  const body = $("links");
  body.replaceChildren();
  for (const l of links) {
    const tr = document.createElement("tr");

    const code = document.createElement("td");
    const a = document.createElement("a");
    a.href = "/s/" + l.code; a.target = "_blank"; a.textContent = "/s/" + l.code;
    code.append(a);

    const status = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "badge " + l.status; badge.textContent = STATUS[l.status];
    status.append(badge);
    if (l.verdict) {
      const v = document.createElement("div");
      v.className = "verdict"; v.textContent = l.verdict;
      status.append(v);
    }

    const actions = document.createElement("td");
    const edit = document.createElement("button");
    edit.className = "ghost"; edit.textContent = "Изменить";
    edit.onclick = async () => {
      const url = window.prompt("Новый адрес", l.target_url);
      if (url) { await safe(() => api("/api/links/" + l.code, { method: "PATCH", body: JSON.stringify({ url }) })); refresh(); }
    };
    const del = document.createElement("button");
    del.className = "danger"; del.textContent = "Удалить";
    del.onclick = async () => { await safe(() => api("/api/links/" + l.code, { method: "DELETE" })); refresh(); };
    actions.append(edit, " ", del);

    tr.append(code, cell(l.target_url, "url"), status, cell(l.clicks), actions);
    body.append(tr);
  }
}

function renderStats(s) {
  const items = [
    [s.links_by_status.clean || 0, "безопасных"],
    [s.links_by_status.malicious || 0, "опасных"],
    [s.links_by_status.pending || 0, "в проверке"],
    [s.cache_hit, "попаданий в кеш"],
    [s.cache_miss, "промахов кеша"],
  ];
  $("stats").replaceChildren(...items.map(([n, label]) => {
    const d = document.createElement("div");
    d.className = "stat";
    const b = document.createElement("b"); b.textContent = n;
    const sp = document.createElement("span"); sp.textContent = label;
    d.append(b, sp);
    return d;
  }));
}

async function safe(fn) {
  try { return await fn(); } catch (e) { $("msg").textContent = "Ошибка: " + e.message; }
}

async function refresh() {
  await safe(async () => {
    const [links, stats] = await Promise.all([api("/api/links"), api("/api/stats")]);
    renderLinks(links); renderStats(stats);
  });
}

$("form").onsubmit = async (e) => {
  e.preventDefault();
  const link = await safe(() => api("/api/links", { method: "POST", body: JSON.stringify({ url: $("url").value }) }));
  if (link) {
    $("msg").textContent = `Короткая ссылка: ${location.origin}/s/${link.code}`;
    $("url").value = "";
    refresh();
  }
};

safe(async () => { $("hello").textContent = (await api("/api/hello")).message; });
refresh();
setInterval(refresh, 2000);

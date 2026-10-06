// Masking service — SPA без зависимостей. Хеш-роутер, несколько экранов.

const $ = (sel, root = document) => root.querySelector(sel);
const h = (tag, attrs = {}, ...children) => {
  const el = Object.assign(document.createElement(tag), attrs);
  if (attrs.class) el.className = attrs.class;
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(c));
  }
  return el;
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));
const fmt = {
  date: (iso) => iso ? new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—",
  size: (n) => n < 1024 ? n + " Б" : n < 1024 * 1024 ? (n / 1024).toFixed(1) + " КБ" : (n / 1024 / 1024).toFixed(1) + " МБ",
  kindRu: (k) => ({ FIO: "ФИО", ADDR: "Адрес" }[k] || k),
};

async function api(path, opts = {}) {
  const r = await fetch("/api" + path, opts);
  if (!r.ok) {
    let msg;
    try { msg = (await r.json()).detail; } catch { msg = r.statusText; }
    throw new Error(msg || `HTTP ${r.status}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

function toast(message, type = "ok", ms = 3500) {
  const t = h("div", { class: `toast ${type}` }, message);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), ms);
}

function dialog({ title, body, okLabel = "OK", okDisabled = false }) {
  return new Promise((resolve) => {
    const dlg = $("#dialog");
    $("#dialog-title").textContent = title;
    const b = $("#dialog-body"); b.replaceChildren();
    b.append(body);
    $("#dialog-ok").textContent = okLabel;
    $("#dialog-ok").disabled = okDisabled;
    const form = $("#dialog-form");
    const onClose = () => {
      form.removeEventListener("submit", onSubmit);
      resolve(dlg.returnValue);
    };
    const onSubmit = () => {};
    form.addEventListener("submit", onSubmit);
    dlg.addEventListener("close", onClose, { once: true });
    dlg.showModal();
  });
}

// --- Роутер -----------------------------------------------------------------

const routes = [
  { pattern: /^#?\/?$/, render: viewProjects },
  { pattern: /^#\/p\/(\d+)\/?$/, render: viewProjectOverview },
  { pattern: /^#\/p\/(\d+)\/mask$/, render: (m) => viewOperation(m, "mask") },
  { pattern: /^#\/p\/(\d+)\/unmask$/, render: (m) => viewOperation(m, "unmask") },
  { pattern: /^#\/p\/(\d+)\/entities$/, render: viewEntities },
  { pattern: /^#\/p\/(\d+)\/settings$/, render: viewSettings },
];

async function route() {
  const hash = location.hash || "#/";
  for (const r of routes) {
    const m = hash.match(r.pattern);
    if (m) {
      try {
        await r.render(m);
      } catch (e) {
        toast(e.message || "Ошибка", "err");
        renderCrumbs([{ label: "Проекты", href: "#/" }, { label: "Ошибка" }]);
        $("#view").replaceChildren(
          h("div", { class: "card" }, h("div", { class: "callout err" }, e.message || String(e)))
        );
      }
      return;
    }
  }
  location.hash = "#/";
}

// --- Шапка и сайдбар --------------------------------------------------------

async function renderNav(pid = null) {
  const nav = $("#nav"); nav.replaceChildren();
  nav.append(mkLink("#/", "Проекты"));
  if (pid != null) {
    let p;
    try { p = await api(`/projects/${pid}`); } catch { return; }
    const items = [
      ["", `Обзор`],
      ["mask", "Маскирование"],
      ["unmask", "Демаскирование"],
      ["entities", "Сущности", String(p.entities ?? 0)],
      ["settings", "Настройки"],
    ];
    for (const [sub, label, count] of items) {
      nav.append(mkLink(`#/p/${pid}${sub ? "/" + sub : ""}`, label, count));
    }
  }
}
function mkLink(href, label, count) {
  const a = h("a", { href }, label);
  if (count != null) a.append(h("span", { class: "count" }, count));
  if (location.hash === href || (href === "#/" && location.hash === "")) a.setAttribute("aria-current", "page");
  return a;
}

function renderCrumbs(items) {
  const c = $("#crumbs"); c.replaceChildren();
  items.forEach((it, i) => {
    if (i) c.append(h("span", { class: "sep" }, "/"));
    c.append(it.href ? h("a", { href: it.href }, it.label) : h("span", { class: "here" }, it.label));
  });
}

// --- Экраны -----------------------------------------------------------------

async function viewProjects() {
  await renderNav(null);
  renderCrumbs([{ label: "Проекты" }]);
  const list = await api("/projects");
  const view = $("#view"); view.replaceChildren();
  view.append(
    h("div", { class: "row between" },
      h("h1", {}, "Проекты"),
      h("button", { class: "btn primary", onclick: () => createProjectDialog() }, "+ Новый проект")
    ),
    h("div", { class: "callout" },
      `Оригиналы ФИО и адресов сохраняются на этом компьютере в открытом виде, в папке данных программы. Кто имеет доступ к папке — увидит их. Это нужно для демаскирования.`
    ),
  );
  if (!list.length) {
    view.append(h("div", { class: "card empty" },
      h("div", { class: "icon" }, "📁"),
      h("h2", {}, "Проектов пока нет"),
      h("p", {}, "Проект объединяет документы с общим реестром сущностей: один человек получает один и тот же токен во всех документах."),
      h("button", { class: "btn primary", onclick: () => createProjectDialog() }, "Создать первый проект"),
    ));
    return;
  }
  const grid = h("div", { class: "grid cards" });
  for (const p of list) {
    const card = h("a", { class: "card", href: `#/p/${p.id}`, style: "display:block;color:inherit;" },
      h("h2", {}, p.name),
      h("div", { class: "muted" },
        `${p.entities} сущностей · ${p.documents} документов · изменён ${fmt.date(p.last_activity || p.created_at)}`
      ),
    );
    grid.append(card);
  }
  view.append(grid);
}

async function createProjectDialog() {
  const input = h("input", { type: "text", placeholder: "Например: Договоры 2026", required: true, maxLength: 120 });
  const body = h("div", {},
    h("label", {},
      h("div", { class: "muted" }, "Название"),
      input,
    ),
    h("p", { class: "muted", style: "margin-top:1rem" },
      "Будет создана папка проекта в data/files/. Для демаскирования нужны оригиналы, они будут храниться там же."),
  );
  input.addEventListener("input", () => $("#dialog-ok").disabled = !input.value.trim());
  setTimeout(() => input.focus(), 50);
  const r = await dialog({ title: "Новый проект", body, okLabel: "Создать", okDisabled: true });
  if (r !== "ok") return;
  try {
    const p = await api("/projects", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: input.value.trim() }),
    });
    toast("Проект создан");
    location.hash = `#/p/${p.id}`;
  } catch (e) { toast(e.message, "err"); }
}

async function viewProjectOverview([, pid]) {
  const p = await api(`/projects/${pid}`);
  await renderNav(pid);
  renderCrumbs([{ label: "Проекты", href: "#/" }, { label: p.name }]);
  const view = $("#view"); view.replaceChildren();
  view.append(
    h("div", { class: "row between" }, h("h1", {}, p.name)),
    h("div", { class: "summary" },
      tile(p.entities, "Сущностей"),
      tile(p.documents, "Документов"),
      tile(p.occurrences, "Вхождений замаскировано"),
    ),
    h("div", { class: "row", style: "margin-top:1rem" },
      h("a", { href: `#/p/${pid}/mask`, class: "btn primary" }, "Замаскировать документ"),
      h("a", { href: `#/p/${pid}/unmask`, class: "btn" }, "Демаскировать документ"),
    ),
  );
}

function tile(num, label) {
  return h("div", { class: "tile" },
    h("span", { class: "num" }, String(num)),
    h("span", { class: "label" }, label),
  );
}

async function viewOperation([, pid], op) {
  const p = await api(`/projects/${pid}`);
  await renderNav(pid);
  const title = op === "mask" ? "Маскирование" : "Демаскирование";
  renderCrumbs([
    { label: "Проекты", href: "#/" },
    { label: p.name, href: `#/p/${pid}` },
    { label: title },
  ]);
  const view = $("#view"); view.replaceChildren();

  const summary = h("div");
  const dropzone = mkDropzone(async (file) => uploadAndRender(pid, op, file, summary, refresh));
  view.append(
    h("div", { class: "card" },
      h("h2", {}, title),
      h("p", { class: "muted" },
        op === "mask"
          ? "Загрузите .docx или .xlsx. ФИО и адреса будут заменены на токены вида [ФИО_1], [АДРЕС_1]."
          : "Загрузите замаскированный документ, чтобы восстановить оригинальные значения из реестра проекта."),
      dropzone, summary,
    ),
    h("div", { class: "card" },
      h("h2", {}, "История"),
      h("div", { id: "history" }),
    ),
  );
  async function refresh() {
    const hist = await api(`/projects/${pid}/history/${op}`);
    const el = $("#history"); el.replaceChildren();
    if (!hist.length) {
      el.append(h("div", { class: "empty muted" }, "Пока ничего не обрабатывалось."));
      return;
    }
    const table = h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "Дата"),
        h("th", {}, "Исходный"),
        h("th", {}, "Результат"),
        h("th", {}, "Найдено"),
      )),
      h("tbody", {}),
    );
    const tbody = table.querySelector("tbody");
    for (const row of hist) {
      const stats = row.stats || {};
      const foundTotal = stats.total ?? stats.restored ?? 0;
      const warn = (row.warnings && row.warnings.unknown && row.warnings.unknown.length) || 0;
      tbody.append(h("tr", {},
        h("td", {}, fmt.date(row.created_at)),
        h("td", {},
          h("a", { href: `/api/documents/${row.id}/download` }, row.filename),
          h("div", { class: "muted" }, fmt.size(row.size)),
        ),
        row.output
          ? h("td", {},
              h("a", { href: `/api/documents/${row.output.id}/download` }, row.output.filename),
              h("div", { class: "muted" }, fmt.size(row.output.size)),
            )
          : h("td", { class: "muted" }, "—"),
        h("td", {},
          h("span", {}, String(foundTotal)),
          warn ? h("div", {}, h("span", { class: "badge warn" }, `не найдено токенов: ${warn}`)) : null,
        ),
      ));
    }
    el.append(table);
  }
  await refresh();
}

function mkDropzone(onFile) {
  const input = h("input", { type: "file", accept: ".docx,.xlsx" });
  const label = h("label", { class: "dropzone" },
    h("div", { class: "big" }, "Перетащите файл или нажмите для выбора"),
    h("div", { class: "muted" }, ".docx или .xlsx, до 50 МБ"),
    input,
  );
  input.addEventListener("change", () => input.files[0] && onFile(input.files[0]));
  ["dragenter", "dragover"].forEach(e => label.addEventListener(e, (ev) => {
    ev.preventDefault(); label.classList.add("over");
  }));
  ["dragleave", "drop"].forEach(e => label.addEventListener(e, () => label.classList.remove("over")));
  label.addEventListener("drop", (ev) => {
    ev.preventDefault();
    if (ev.dataTransfer.files[0]) onFile(ev.dataTransfer.files[0]);
  });
  return label;
}

async function uploadAndRender(pid, op, file, summary, refresh) {
  summary.replaceChildren(h("div", { class: "callout" }, "Обработка..."));
  const fd = new FormData();
  fd.append("file", file);
  let resp;
  try {
    resp = await fetch(`/api/projects/${pid}/${op}`, { method: "POST", body: fd });
  } catch (e) {
    summary.replaceChildren(h("div", { class: "callout err" }, "Нет связи с сервисом"));
    return;
  }
  if (!resp.ok) {
    let msg = resp.statusText;
    try { msg = (await resp.json()).detail || msg; } catch {}
    summary.replaceChildren(h("div", { class: "callout err" }, msg));
    return;
  }
  const stats = JSON.parse(resp.headers.get(op === "mask" ? "X-Masking-Stats" : "X-Unmasking-Stats") || "{}");
  const cd = resp.headers.get("Content-Disposition") || "";
  const nameMatch = cd.match(/filename\*=UTF-8''([^;]+)/);
  const outName = nameMatch ? decodeURIComponent(nameMatch[1]) : (op === "mask" ? "result" : "restored");
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: outName, class: "btn primary" }, "Скачать результат");
  const tiles = [];
  if (op === "mask") {
    tiles.push(tile(stats.total || 0, "Всего"));
    for (const [k, n] of Object.entries(stats.found || {})) tiles.push(tile(n, fmt.kindRu(k)));
    tiles.push(tile(Object.values(stats.new || {}).reduce((a, b) => a + b, 0), "Новых"));
    tiles.push(tile(Object.values(stats.reused || {}).reduce((a, b) => a + b, 0), "Уже известных"));
  } else {
    tiles.push(tile(stats.restored || 0, "Восстановлено"));
    tiles.push(tile((stats.unknown || []).length, "Не найдено токенов"));
    if (stats.inflected) tiles.push(tile(stats.inflected, "Склонено"));
  }
  summary.replaceChildren(
    h("div", { class: "callout ok" },
      op === "mask" ? `Готово. Найдено сущностей: ${stats.total || 0}` : `Готово. Восстановлено: ${stats.restored || 0}`
    ),
    h("div", { class: "summary" }, ...tiles),
    h("div", { class: "row", style: "margin-top:1rem" }, a),
  );
  if ((stats.unknown || []).length) {
    summary.append(h("div", { class: "callout warn", style: "margin-top:1rem" },
      "Не удалось распознать токены: " + stats.unknown.join(", ")));
  }
  await refresh();
}

async function viewEntities([, pid]) {
  const p = await api(`/projects/${pid}`);
  await renderNav(pid);
  renderCrumbs([
    { label: "Проекты", href: "#/" }, { label: p.name, href: `#/p/${pid}` }, { label: "Сущности" },
  ]);
  const view = $("#view"); view.replaceChildren();

  let kind = null;
  let query = "";
  let revealed = false;
  const tbody = h("tbody", {});
  const q = h("input", { type: "search", placeholder: "Поиск по оригиналу...", style: "max-width:280px" });
  const chips = h("div", { class: "chip-row" },
    chip("Все", () => kind = null),
    chip("ФИО", () => kind = "FIO"),
    chip("Адреса", () => kind = "ADDR"),
  );
  const revealBtn = h("button", { class: "btn ghost sm" }, "Показать оригиналы");
  revealBtn.onclick = () => { revealed = !revealed; revealBtn.textContent = revealed ? "Скрыть оригиналы" : "Показать оригиналы"; refresh(); };
  q.addEventListener("input", debounce(() => { query = q.value.trim(); refresh(); }, 150));
  chips.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
    chips.querySelectorAll(".chip").forEach(x => x.setAttribute("aria-pressed", "false"));
    c.setAttribute("aria-pressed", "true");
    refresh();
  }));
  chips.querySelector(".chip").setAttribute("aria-pressed", "true");

  view.append(
    h("div", { class: "card" },
      h("h2", {}, "Реестр сущностей"),
      h("div", { class: "callout" }, "Это и есть карта соответствий «токен ↔ оригинал». Храните папку data/ в надёжном месте."),
      h("div", { class: "row", style: "margin-top:1rem" }, chips, q, revealBtn),
      h("div", { id: "ent-table", style: "margin-top:1rem" }),
    )
  );

  async function refresh() {
    const list = await api(`/projects/${pid}/entities${kind ? "?kind=" + kind : ""}${query ? (kind ? "&" : "?") + "q=" + encodeURIComponent(query) : ""}`);
    const table = h("table", {}, h("thead", {}, h("tr", {},
      h("th", {}, "Тип"), h("th", {}, "Токен"), h("th", {}, "Оригинал"),
      h("th", {}, "Вхождений"), h("th", {}, "Документов"),
    )), h("tbody", {}));
    const tb = table.querySelector("tbody");
    if (!list.length) tb.append(h("tr", {}, h("td", { colSpan: 5, class: "muted" }, "Ничего не найдено")));
    for (const e of list) {
      const token = `[${fmt.kindRu(e.kind)}_${e.seq}]`;
      const value = revealed ? e.canonical : "•".repeat(Math.min(e.canonical.length, 24));
      tb.append(h("tr", {},
        h("td", {}, h("span", { class: `badge ${e.kind === "FIO" ? "fio" : "addr"}` }, fmt.kindRu(e.kind))),
        h("td", {}, h("span", { class: "mono" }, token)),
        h("td", {}, h("span", { class: revealed ? "mono" : "secret" }, value)),
        h("td", {}, String(e.occurrences)),
        h("td", {}, String(e.documents)),
      ));
    }
    $("#ent-table").replaceChildren(table);
  }
  await refresh();
}

async function viewSettings([, pid]) {
  const p = await api(`/projects/${pid}`);
  await renderNav(pid);
  renderCrumbs([
    { label: "Проекты", href: "#/" }, { label: p.name, href: `#/p/${pid}` }, { label: "Настройки" },
  ]);
  const nameInput = h("input", { type: "text", value: p.name, maxLength: 120 });
  const view = $("#view"); view.replaceChildren(
    h("div", { class: "card" },
      h("h2", {}, "Общие"),
      h("label", {}, h("div", { class: "muted" }, "Название"), nameInput),
      h("div", { class: "row", style: "margin-top:1rem" },
        h("button", { class: "btn primary", onclick: renameProject }, "Сохранить")),
    ),
    h("div", { class: "card" },
      h("h2", {}, "Опасная зона"),
      h("p", {}, "Удаление проекта убирает всю карту соответствий и загруженные файлы. Ранее замаскированные документы станет невозможно демаскировать."),
      h("button", { class: "btn danger", onclick: () => deleteProjectDialog(p) }, "Удалить проект"),
    ),
  );
  async function renameProject() {
    try {
      await api(`/projects/${pid}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nameInput.value.trim() }),
      });
      toast("Сохранено");
      await renderNav(pid);
    } catch (e) { toast(e.message, "err"); }
  }
}

async function deleteProjectDialog(p) {
  const input = h("input", { type: "text", placeholder: "Введите название проекта" });
  const ok = () => input.value.trim() === p.name;
  input.addEventListener("input", () => $("#dialog-ok").disabled = !ok());
  const r = await dialog({
    title: "Удалить проект?",
    body: h("div", {},
      h("p", {}, `Будут удалены ${p.entities} сущностей и ${p.documents} документов. Это необратимо.`),
      h("p", {}, "Для подтверждения введите точное название проекта:"),
      input,
    ),
    okLabel: "Удалить", okDisabled: true,
  });
  if (r !== "ok" || !ok()) return;
  try {
    await api(`/projects/${p.id}`, { method: "DELETE" });
    toast("Проект удалён");
    location.hash = "#/";
  } catch (e) { toast(e.message, "err"); }
}

// --- Утилиты ---------------------------------------------------------------

function chip(label, onPress) {
  const c = h("button", { class: "chip", type: "button" }, label);
  c.setAttribute("aria-pressed", "false");
  c.addEventListener("click", onPress);
  return c;
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// --- Переключатель темы ----------------------------------------------------

const THEMES = ["auto", "light", "dark"];
const LABELS = { auto: "Тема: авто", light: "Тема: светлая", dark: "Тема: тёмная" };
function applyTheme() {
  const t = localStorage.getItem("theme") || "auto";
  document.documentElement.dataset.theme = t === "auto" ? "" : t;
  $("#theme-btn").textContent = LABELS[t];
}
$("#theme-btn").addEventListener("click", () => {
  const cur = localStorage.getItem("theme") || "auto";
  localStorage.setItem("theme", THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length]);
  applyTheme();
});
applyTheme();

// --- Старт -----------------------------------------------------------------

window.addEventListener("hashchange", route);
api("/health").then(h => {
  $("#version").textContent = "v" + h.version;
  if (h.error) toast(h.error, "err", 10000);
}).catch(() => $("#status").textContent = "нет связи с сервисом");
route();

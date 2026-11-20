const byId = id => document.getElementById(id);
const scenario = byId("scenario");
const drill = byId("drill");
const input = byId("input");
const message = byId("message");
const canvas = byId("map");
const context = canvas.getContext("2d");
let config;
let report;
let selected = 0;
let side = "after";
let pending = 0;

function element(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

async function json(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Request failed.");
  return body;
}

async function update(loadScenario) {
  const token = ++pending;
  const showError = error => {
    message.textContent = error.message;
    message.dataset.error = "true";
  };
  message.textContent = "Comparing snapshots…";
  message.dataset.error = "false";
  try {
    const next = loadScenario ? await json("/api/scenarios/" + scenario.value) : JSON.parse(input.value);
    const result = await json("/api/compare", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...next, drill: drill.checked}),
    });
    if (token !== pending) return;
    if (loadScenario) input.value = JSON.stringify(next, null, 2);
    config = next;
    report = result;
    if (loadScenario || selected >= result.policies.length) {
      selected = Math.max(0, result.policies.findIndex(row => row.outcome !== "unchanged"));
    }
    byId("results").hidden = false;
    byId("download").disabled = false;
    message.textContent = "Compared " + result.policies.length + " traffic policies.";
    render();
  } catch (error) {
    if (token === pending) showError(error);
  }
}

function render() {
  const failures = report.policies.filter(row => !row.after.pass).length;
  const verdict = byId("verdict");
  verdict.textContent = failures ? failures + " failing" : "All policies pass";
  verdict.dataset.failed = Boolean(failures);
  const policies = byId("policies");
  const focusedIndex = Array.from(policies.children).indexOf(document.activeElement);
  policies.replaceChildren();
  report.policies.forEach((row, index) => {
    const button = element("button", "", "policy");
    button.type = "button";
    button.setAttribute("aria-pressed", index === selected);
    const state = row.outcome === "regression" ? "regression" : row.after.pass ? row.outcome : "violation";
    const chip = element("span", state === "unchanged" ? "PASS" : state.toUpperCase(), "chip");
    chip.dataset.state = state;
    button.append(element("strong", row.name), chip, element("span", row.after.source + " → " + row.after.target, "endpoint"));
    button.addEventListener("click", () => { selected = index; render(); });
    policies.append(button);
  });
  if (focusedIndex >= 0) policies.children[focusedIndex]?.focus();
  const changes = report.link_changes.map(change => change.link.join(" ↔ ") + " · " + (change.before ?? "absent") + " → " + (change.after ?? "absent"));
  changes.push(...report.prefix_changes.map(change => change.router + " · " + (change.before.join(", ") || "no prefixes") + " → " + (change.after.join(", ") || "no prefixes")));
  byId("changes").replaceChildren(...(changes.length ? changes : ["No link or prefix changes."]).map(value => element("li", value)));
  const outcomes = report.failures.map(item => item.link.join(" ↔ ") + " · " + (item.violations.join(", ") || "no new violations"));
  byId("failures").replaceChildren(...(outcomes.length ? outcomes : ["No link failures evaluated."]).map(value => element("li", value)));
  renderRoute();
}

function renderRoute() {
  const route = report.policies[selected][side];
  const tail = route.path_count === 1 ? " path" : " paths";
  const summary = route.prefix ? route.prefix + " · cost " + route.cost + " · " + route.path_count + tail : "No route to " + route.target;
  byId("map-caption").textContent = (side === "before" ? "Baseline" : "Candidate") + " · " + summary;
  canvas.setAttribute("aria-label", summary + ". " + route.paths.map(path => path.join(" to ")).join(". "));
  const detail = byId("route");
  detail.replaceChildren(element("h3", route.pass ? "Policy satisfied" : "Policy violation"), element("p", route.reason || summary));
  if (route.paths.length) {
    const list = element("ul", "");
    list.append(...route.paths.map(path => element("li", path.join(" → "))));
    if (route.path_count > route.paths.length) list.append(element("li", (route.path_count - route.paths.length) + " more equal-cost paths"));
    detail.append(list);
  }
  for (const id of ["before", "after"]) byId(id).setAttribute("aria-pressed", String(id === side));
  draw();
}

const examplePositions = {
  Access: [.15, .42], East: [.44, .18], West: [.44, .62],
  Core: [.79, .42], Guest: [.20, .85], Lab: [.70, .85],
};
const linkKey = (a, b) => [a, b].sort().join("|");

function draw() {
  if (!report || !context) return;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  context.scale(scale, scale);
  context.fillStyle = "#71628f";
  for (let x = 4; x < width; x += 15) {
    for (let y = 5; y < height; y += 15) context.fillRect(x, y, 1, 1);
  }
  const snapshot = config[side === "before" ? "baseline" : "candidate"];
  const route = report.policies[selected][side];
  const highlighted = new Set(route.paths.flatMap(path => path.slice(1).map((router, i) => linkKey(path[i], router))));
  const routed = new Set(route.paths.flat());
  const changed = new Set(report.link_changes.map(change => linkKey(...change.link)));
  const custom = !snapshot.routers.every(router => Object.hasOwn(examplePositions, router));
  const map = new Map(snapshot.routers.map((router, index) => {
    const angle = 2 * Math.PI * index / snapshot.routers.length - Math.PI / 2;
    const [x, y] = custom ? [.5 + .36 * Math.cos(angle), .5 + .33 * Math.sin(angle)] : examplePositions[router];
    return [router, [x * width, y * height]];
  }));
  const links = snapshot.links.map(link => ({...link, key: linkKey(link.a, link.b)}));
  const drawLink = ({a, b, key, cost}) => {
    const from = map.get(a);
    const end = map.get(b);
    const active = highlighted.has(key);
    context.strokeStyle = active ? "#93f0ce" : changed.has(key) ? "#ffd162" : "#9e8fbd";
    context.lineWidth = active ? 3 : 1.5;
    context.setLineDash(changed.has(key) && !active ? [6, 4] : []);
    context.beginPath();
    context.moveTo(...from);
    context.lineTo(...end);
    context.stroke();
    const x = (from[0] + end[0]) / 2;
    const y = (from[1] + end[1]) / 2;
    context.font = "600 11px monospace";
    const labelWidth = context.measureText(String(cost)).width + 10;
    context.fillStyle = "#291e48";
    context.fillRect(x - labelWidth / 2, y - 8, labelWidth, 16);
    context.fillStyle = active ? "#93f0ce" : changed.has(key) ? "#ffd162" : "#f0e6ff";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(cost, x, y);
  };
  links.filter(link => !highlighted.has(link.key)).forEach(drawLink);
  links.filter(link => highlighted.has(link.key)).forEach(drawLink);
  context.setLineDash([]);
  context.textAlign = "center";
  for (const [router, [x, y]] of map) {
    const active = routed.has(router);
    context.fillStyle = active ? "#93f0ce" : "#423366";
    context.strokeStyle = active ? "#93f0ce" : "#bcaee6";
    context.lineWidth = 1.5;
    context.fillRect(x - 9, y - 9, 18, 18);
    context.strokeRect(x - 9, y - 9, 18, 18);
    context.font = "700 11px monospace";
    context.fillStyle = active ? "#93f0ce" : "#fff9ef";
    context.textBaseline = "top";
    context.fillText(router, x, y + 15, 96);
  }
}

for (const id of ["before", "after"]) {
  byId(id).addEventListener("click", () => { side = id; renderRoute(); });
}
scenario.addEventListener("change", () => update(true));
drill.addEventListener("change", () => update(false));
byId("run").addEventListener("click", () => update(false));
byId("download").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "nettwin-report.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
new ResizeObserver(draw).observe(canvas);
update(true);

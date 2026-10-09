// 画面制御。実行時に読むのは同一オリジンの静的JSON（site-config.json / model.json）だけ。
// 外部へのリクエストは GA4（測定IDを設定した場合のみ）に限られる。
import { estimate, toSqm, toWesternYear, formatManYen, formatQuarter } from "./estimator.js";

const UNKNOWN_TOWN = "__unknown__";
const $ = (id) => document.getElementById(id);

let site = {};
let model = null;
let currentStep = 1;
let started = false;

// ---- 計測（GA4） ---------------------------------------------------------------
function setupAnalytics(id) {
  if (!id) return;
  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`;
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag("js", new Date());
  window.gtag("config", id);
}
function track(event, params = {}) {
  if (typeof window.gtag === "function") window.gtag("event", event, params);
}

// ---- 読み込み ------------------------------------------------------------------
async function getJson(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function loadModel() {
  try {
    return await getJson("model.json");
  } catch (e) {
    if (!site.allow_sample_preview) throw e;
    const sample = await getJson("sample/model.sample.json");
    if (!sample.is_sample) throw new Error("sample model must be flagged is_sample");
    return sample;
  }
}

function renderCredit() {
  const c = site.credit || {};
  $("credit-api-notice").textContent = c.api_notice || "";
  $("credit-source").textContent = c.source || "";
  $("credit-source-url").textContent = c.source_url || "";
  $("credit-source-url").href = c.source_url || "#";
  $("credit-processed").textContent = c.processed_by || "";
}

// ---- 入力 ----------------------------------------------------------------------
function fillCities() {
  const sel = $("city");
  for (const [code, city] of Object.entries(model.cities)) {
    sel.add(new Option(city.name, code));
  }
}

function fillTowns(code) {
  const sel = $("town");
  sel.innerHTML = "";
  if (!code) {
    sel.add(new Option("先に市区を選んでください", ""));
    sel.disabled = true;
    return;
  }
  sel.add(new Option("選択してください", ""));
  const towns = Object.keys(model.cities[code].towns || {}).sort((a, b) => a.localeCompare(b, "ja"));
  for (const t of towns) sel.add(new Option(t, t));
  sel.add(new Option("わからない／一覧にない", UNKNOWN_TOWN));
  sel.disabled = false;
}

function readInput() {
  const town = $("town").value;
  return {
    cityCode: $("city").value,
    town: town && town !== UNKNOWN_TOWN ? town : null,
    townChoice: town,
    buildYear: toWesternYear($("era").value, $("build-year").value),
    landArea: toSqm($("land-area").value, $("land-unit").value),
    floorArea: toSqm($("floor-area").value, $("floor-unit").value),
  };
}

function validate(step, input, currentYear) {
  if (step === 1) {
    if (!input.cityCode) return "市区を選んでください。";
    if (!input.townChoice) return "町名を選んでください（わからない場合は「わからない／一覧にない」）。";
  }
  if (step === 2) {
    if (input.buildYear == null || input.buildYear < 1900 || input.buildYear > currentYear) {
      return "築年を正しく入力してください（例：西暦 2005、平成 17）。";
    }
  }
  if (step === 3) {
    for (const [id, label] of [["land-area", "土地面積"], ["floor-area", "延床面積"], ["walk", "徒歩分数"]]) {
      const v = $(id).value;
      if (v !== "" && !(Number(v) >= 0)) return `${label}は0以上の数値で入力してください。`;
    }
    if (input.landArea != null && input.landArea > 10000) return "土地面積が大きすぎます。単位（㎡／坪）をご確認ください。";
    if (input.floorArea != null && input.floorArea > 3000) return "延床面積が大きすぎます。単位（㎡／坪）をご確認ください。";
  }
  return null;
}

function showStep(n) {
  currentStep = n;
  document.querySelectorAll(".step").forEach((s) => { s.hidden = Number(s.dataset.step) !== n; });
  document.querySelectorAll(".progress li").forEach((li) => {
    if (Number(li.dataset.step) === n) li.setAttribute("aria-current", "step");
    else li.removeAttribute("aria-current");
  });
}

function setError(step, msg) {
  const el = document.querySelector(`[data-error-for="${step}"]`);
  el.textContent = msg || "";
  el.hidden = !msg;
}

// ---- 結果 ----------------------------------------------------------------------
const DEFAULT_LABELS = { land_area: "土地面積", floor_area: "延床面積" };

function ctaUrl(input) {
  const base = site.satei_form_url || "dummy-form.html";
  const url = new URL(base, location.href);
  // 物件情報のみを引き継ぐ（個人情報は扱わない）
  const p = {
    city_code: input.cityCode,
    city: model.cities[input.cityCode]?.name,
    town: input.town || "",
    build_year: input.buildYear,
    land_area: input.landArea != null ? input.landArea.toFixed(1) : "",
    floor_area: input.floorArea != null ? input.floorArea.toFixed(1) : "",
    // 駅徒歩は査定には使わず（公開データに項目がない）、精密査定の参考として引き継ぐ（D-03）
    walk_minutes: $("walk").value,
  };
  for (const [k, v] of Object.entries(p)) if (v !== "" && v != null) url.searchParams.set(k, v);
  return url.toString();
}

function renderResult(input, r) {
  $("satei-form").hidden = true;
  $("result").hidden = false;
  const hasPrice = r.confidence !== "none";
  $("result-price").hidden = !hasPrice;
  $("result-none").hidden = hasPrice;
  if (hasPrice) {
    $("price-low").textContent = formatManYen(r.low);
    $("price-high").textContent = formatManYen(r.high);
    const where = r.level === "town" ? `${r.cityName}${r.townName}周辺` : `${r.cityName}全体`;
    const period = `${formatQuarter(r.basis.period.from)}〜${formatQuarter(r.basis.period.to)}`;
    $("result-basis").textContent =
      `${where}の中古戸建ての取引データ${r.basis.count.toLocaleString("ja-JP")}件（${period}）をもとに推定しました。`;
    const lowNote = $("result-low-note");
    lowNote.hidden = r.confidence !== "low";
    lowNote.textContent = input.town
      ? "この町名のデータが少ないため、市区全体のデータで試算しています。そのぶん幅を広くしています。"
      : "町名を指定していないため、市区全体のデータで試算しています。そのぶん幅を広くしています。";
    const ul = $("result-defaults");
    ul.innerHTML = "";
    for (const d of r.defaults) {
      const li = document.createElement("li");
      li.textContent = `${DEFAULT_LABELS[d]}は標準値（約${Math.round(r.used[d === "land_area" ? "landArea" : "floorArea"])}㎡）で計算しています。`;
      ul.appendChild(li);
    }
  }
  $("cta").href = ctaUrl(input);
  track("satei_result", { confidence: r.confidence, city_code: input.cityCode });
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---- 初期化 --------------------------------------------------------------------
async function init() {
  try {
    site = await getJson("site-config.json");
  } catch {
    site = {};
  }
  if (site.tool_name) {
    $("tool-name").textContent = site.tool_name;
    document.title = `${site.tool_name}｜中古戸建て`;
  }
  renderCredit();
  setupAnalytics(site.ga4_measurement_id);

  try {
    model = await loadModel();
  } catch {
    $("load-error").hidden = false;
    return;
  }
  $("sample-banner").hidden = !model.is_sample;
  fillCities();
  $("satei-form").hidden = false;

  const currentYear = new Date().getFullYear();
  const form = $("satei-form");

  form.addEventListener("focusin", () => {
    if (!started) { started = true; track("satei_start"); }
  });
  $("city").addEventListener("change", (e) => fillTowns(e.target.value));

  form.querySelectorAll("[data-next]").forEach((b) => b.addEventListener("click", () => {
    const msg = validate(currentStep, readInput(), currentYear);
    setError(currentStep, msg);
    if (msg) return;
    showStep(currentStep + 1);
    track("satei_step", { step: currentStep });
  }));
  form.querySelectorAll("[data-prev]").forEach((b) => b.addEventListener("click", () => showStep(currentStep - 1)));

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = readInput();
    for (const s of [1, 2, 3]) {
      const msg = validate(s, input, currentYear);
      if (msg) { showStep(s); setError(s, msg); return; }
    }
    renderResult(input, estimate(model, input, { currentYear }));
  });

  $("cta").addEventListener("click", () => {
    track("satei_cta_click", { city_code: $("city").value });
  });
  $("restart").addEventListener("click", () => {
    $("result").hidden = true;
    form.hidden = false;
    showStep(1);
  });
}

init();

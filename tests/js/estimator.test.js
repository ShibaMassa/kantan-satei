// 査定ロジック（v1.1）のテスト。使うのは tests/fixtures/ の架空データのみ。
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  predictLog, estimate, toSqm, toWesternYear, SQM_PER_TSUBO, formatManYen, formatQuarter,
} from "../../public/js/estimator.js";

const load = (name) => JSON.parse(readFileSync(new URL(`../fixtures/${name}`, import.meta.url), "utf-8"));
const model = load("fixture_model.json");
const shared = load("fixture_shared_cases.json");
const opts = { currentYear: 2026 };
const city = model.cities["99901"];
const P = model.params;
const clamp = (v, [lo, hi]) => Math.min(Math.max(v, lo), hi);
const expected = (alpha, land, floor, age, [lo, hi], c) => {
  const base = Math.exp(predictLog(alpha, P.coef, clamp(land, P.clamp.land_area), clamp(floor, P.clamp.floor_area),
    clamp(age, P.clamp.age)));
  return [Math.floor((base * c[`p${lo}`]) / 1e5) * 1e5, Math.ceil((base * c[`p${hi}`]) / 1e5) * 1e5];
};

test("予測式が Python 実装と一致する（共有ケース）", () => {
  for (const c of shared.cases) {
    const got = predictLog(c.alpha, shared.coef, c.land_area, c.floor_area, c.age, c.time);
    assert.ok(Math.abs(got - c.expected_log) < 1e-9, JSON.stringify(c));
  }
});

test("坪→㎡、和暦→西暦", () => {
  assert.equal(toSqm(100, "sqm"), 100);
  assert.ok(Math.abs(toSqm(30, "tsubo") - 99.1735537) < 1e-6);
  assert.ok(Math.abs(SQM_PER_TSUBO - 3.305785) < 1e-6);
  assert.equal(toSqm("", "sqm"), null);
  assert.equal(toSqm(-1, "sqm"), null);
  assert.equal(toWesternYear("western", 2005), 2005);
  assert.equal(toWesternYear("heisei", 17), 2005);
  assert.equal(toWesternYear("showa", 64), 1989);
  assert.equal(toWesternYear("reiwa", 1), 2019);
  assert.equal(toWesternYear("heisei", 32), null);
  assert.equal(toWesternYear("showa", 0), null);
});

test("町名の効果あり → confidence=normal、町名の残差で25〜75パーセンタイル", () => {
  const r = estimate(model, { cityCode: "99901", town: "テスト町A", buildYear: 2006, landArea: 120, floorArea: 100 }, opts);
  assert.equal(r.confidence, "normal");
  assert.equal(r.level, "town");
  assert.deepEqual(r.defaults, []);
  assert.deepEqual([r.low, r.high], expected(city.towns["テスト町A"].alpha, 120, 100, 20, [25, 75], city.correction_town));
  assert.equal(r.low % 100000, 0);
  assert.equal(r.high % 100000, 0);
  assert.equal(r.basis.count, city.towns["テスト町A"].count);
});

test("町名の件数不足 → 市区の効果で low、市区の残差で10〜90パーセンタイル", () => {
  const r = estimate(model, { cityCode: "99901", town: "テスト町B", buildYear: 2006, landArea: 120, floorArea: 100 }, opts);
  assert.equal(r.confidence, "low");
  assert.equal(r.level, "city");
  assert.deepEqual([r.low, r.high], expected(city.alpha, 120, 100, 20, [10, 90], city.correction_city));
  assert.equal(r.basis.count, city.count);
});

test("町名なし（わからない）でも市区単位で結果が出る", () => {
  const r = estimate(model, { cityCode: "99901", town: null, buildYear: 2000 }, opts);
  assert.equal(r.confidence, "low");
  assert.ok(r.high > r.low && r.low > 0);
});

test("面積未入力 → 町名の標準値で計算し、レンジを広げる", () => {
  const t = city.towns["テスト町A"];
  const withArea = estimate(model, { cityCode: "99901", town: "テスト町A", buildYear: 2006,
    landArea: t.default_land_area, floorArea: t.default_floor_area }, opts);
  const r = estimate(model, { cityCode: "99901", town: "テスト町A", buildYear: 2006 }, opts);
  assert.deepEqual(r.defaults, ["land_area", "floor_area"]);
  assert.equal(r.used.landArea, t.default_land_area);
  assert.ok(r.high - r.low > withArea.high - withArea.low);
});

test("市区の件数不足 → 価格を出さない（confidence=none）", () => {
  const r = estimate(model, { cityCode: "99902", town: "テスト町Z", buildYear: 2000, landArea: 100, floorArea: 90 }, opts);
  assert.equal(r.confidence, "none");
  assert.equal(r.low, undefined);
  assert.equal(r.high, undefined);
});

test("未知の市区 → none", () => {
  assert.equal(estimate(model, { cityCode: "00000", buildYear: 2000 }, opts).confidence, "none");
});

test("入力は学習データの範囲に収めて計算する（外挿しない）", () => {
  const inRange = estimate(model, { cityCode: "99901", town: "テスト町A", buildYear: 2026 - P.clamp.age[1], landArea: P.clamp.land_area[1], floorArea: 100 }, opts);
  const extreme = estimate(model, { cityCode: "99901", town: "テスト町A", buildYear: 1800, landArea: 99999, floorArea: 100 }, opts);
  assert.deepEqual([extreme.low, extreme.high], [inRange.low, inRange.high]);
  const future = estimate(model, { cityCode: "99901", town: "テスト町A", buildYear: 2030, landArea: 120, floorArea: 100 }, opts);
  assert.equal(future.used.age, P.clamp.age[0]);
});

test("表示用フォーマット", () => {
  assert.equal(formatManYen(23500000), "2,350万円");
  assert.equal(formatQuarter("2026Q2"), "2026年第2四半期");
});

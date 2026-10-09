// 査定ロジック v1.1（対数線形回帰。docs/decisions.md D-40〜D-42）。DOM に依存しない純粋関数だけを置く。
// 予測式は batch/model.py と同一。一致は tests/fixtures/fixture_shared_cases.json で検証する。
//   log(価格) = α[町名 or 市区] + b1·log(土地面積) + b2·log(延床面積) + b3·(築年数/10) + b4·(築年数/10)² （時点は基準時点=0）

export const SQM_PER_TSUBO = 400 / 121; // 1坪 = 400/121 ㎡

const ERA_OFFSET = { western: 0, reiwa: 2018, heisei: 1988, showa: 1925 };

export function toSqm(value, unit) {
  const v = Number(value);
  if (!Number.isFinite(v) || v <= 0) return null;
  return unit === "tsubo" ? v * SQM_PER_TSUBO : v;
}

// era: "western" | "reiwa" | "heisei" | "showa"
export function toWesternYear(era, year) {
  const y = Number(year);
  if (!Number.isInteger(y) || !(era in ERA_OFFSET)) return null;
  if (era !== "western" && y < 1) return null;
  if (era === "showa" && y > 64) return null;
  if (era === "heisei" && y > 31) return null;
  return ERA_OFFSET[era] + y;
}

const clampTo = (v, [lo, hi]) => Math.min(Math.max(v, lo), hi);

export function predictLog(alpha, coef, landArea, floorArea, age, time = 0) {
  const a = age / 10;
  return alpha
    + coef.log_land * Math.log(landArea)
    + coef.log_floor * Math.log(floorArea)
    + coef.age10 * a
    + coef.age10_sq * a * a
    + coef.time * time;
}

const none = (reason, extra = {}) => ({ confidence: "none", reason, ...extra });

/**
 * @param {object} model  public/model.json（schema_version 2）
 * @param {{cityCode:string, town?:string|null, buildYear:number, landArea?:number|null, floorArea?:number|null}} input
 * @param {{currentYear:number}} opts
 */
export function estimate(model, input, { currentYear }) {
  const params = model.params;
  const city = model.cities?.[input.cityCode];
  if (!city) return none("unknown_city");
  const period = model.data_period;
  if (!city.available) return none("insufficient_city_data", { cityName: city.name, period });

  const town = input.town ? city.towns?.[input.town] : null;
  const townUsable = town && town.alpha != null;
  const level = townUsable ? "town" : "city";
  const confidence = townUsable ? "normal" : "low";
  const alpha = townUsable ? town.alpha : city.alpha;
  const c = townUsable ? city.correction_town : city.correction_city;

  const defaults = [];
  let landArea = input.landArea;
  if (!(landArea > 0)) {
    landArea = town?.default_land_area ?? city.default_land_area;
    defaults.push("land_area");
  }
  let floorArea = input.floorArea;
  if (!(floorArea > 0)) {
    floorArea = town?.default_floor_area ?? city.default_floor_area;
    defaults.push("floor_area");
  }
  if (!(landArea > 0) || !(floorArea > 0) || alpha == null) {
    return none("no_default_area", { cityName: city.name, period });
  }

  // 回帰式の外挿を防ぐため、学習データの範囲に収めてから計算する
  const age = clampTo(currentYear - input.buildYear, params.clamp.age);
  const base = Math.exp(predictLog(alpha, params.coef,
    clampTo(landArea, params.clamp.land_area), clampTo(floorArea, params.clamp.floor_area), age));

  // 町名なし・町名の件数不足（low）または面積を標準値で補った場合はレンジを広げる
  const wide = confidence === "low" || defaults.length > 0;
  const [pLo, pHi] = params.range_percentiles[wide ? "wide" : "normal"];
  const step = params.rounding_yen;
  const low = Math.floor((base * c[`p${pLo}`]) / step) * step;
  const high = Math.ceil((base * c[`p${pHi}`]) / step) * step;
  if (!(low > 0) || !(high > low)) return none("invalid_range", { cityName: city.name, period });

  return {
    confidence,
    level,
    low,
    high,
    // バックテストの誤差指標（MAPEなど）専用。画面には単一の価格を表示しない（要件 9章）。
    mid: base * c.p50,
    cityName: city.name,
    townName: townUsable ? input.town : null,
    defaults,
    used: { landArea, floorArea, age },
    basis: {
      count: townUsable ? town.count : city.count,
      period,
    },
  };
}

export function formatManYen(yen) {
  return `${Math.round(yen / 10000).toLocaleString("ja-JP")}万円`;
}

export function formatQuarter(q) {
  const m = /^(\d{4})Q([1-4])$/.exec(q || "");
  return m ? `${m[1]}年第${m[2]}四半期` : "";
}

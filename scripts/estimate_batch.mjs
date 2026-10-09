// バックテスト用：画面と同じ public/js/estimator.js で一括査定する。
// 使い方: node scripts/estimate_batch.mjs < input.json > output.json
//   input:  { "model": {...}, "cases": [{ "cityCode", "town", "buildYear", "landArea", "floorArea", "currentYear" }, ...] }
//   output: [ estimate() の戻り値, ... ]（cases と同じ順）
import { estimate } from "../public/js/estimator.js";

let text = "";
process.stdin.setEncoding("utf-8");
for await (const chunk of process.stdin) text += chunk;
const { model, cases } = JSON.parse(text);
const results = cases.map(({ currentYear, ...input }) => estimate(model, input, { currentYear }));
process.stdout.write(JSON.stringify(results));

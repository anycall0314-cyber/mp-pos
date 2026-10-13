// 叫貨廠商「誰看得到」:平台那一頁怎麼顯示、怎麼送。跑法:npm test。
// owner 2026-10-13:kcimos 只有手機玩家看得到(價目是那個帳號的進價)。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { audienceLabel, audienceProblem, toggleCompany } from "./vendorAudience.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("清單上:只給哪幾家;名單空的講清楚沒有人看得到;全部公司不多寫", () => {
  assert.equal(audienceLabel({ is_private: false, only_for: ["JB"] }), "");
  assert.equal(audienceLabel({ is_private: true, only_for: ["JB"] }), "只給 JB");
  assert.equal(audienceLabel({ is_private: true, only_for: ["JB", "CS"] }), "只給 JB、CS");
  assert.equal(audienceLabel({ is_private: true, only_for: [] }), "沒有公司看得到");
});

test("表單:選了指定公司卻一家都沒勾要提醒", () => {
  assert.equal(audienceProblem(true, []), "一家都沒勾:沒有公司看得到");
  assert.equal(audienceProblem(true, ["JB"]), "");
  assert.equal(audienceProblem(false, []), "");
});

test("勾 / 取消一家公司:不重複、照勾的順序", () => {
  assert.deepEqual(toggleCompany([], "JB", true), ["JB"]);
  assert.deepEqual(toggleCompany(["JB"], "CS", true), ["JB", "CS"]);
  assert.deepEqual(toggleCompany(["JB", "CS"], "JB", true), ["CS", "JB"]);
  assert.deepEqual(toggleCompany(["JB", "CS"], "JB", false), ["CS"]);
  assert.deepEqual(toggleCompany(["JB"], "XX", false), ["JB"]);
});

test("平台的廠商表單:兩格都送(關掉開關不清名單);勾的是公司代碼;兩個選項字數一樣", () => {
  const page = read("../pages/platform-admin/PlatformVendorsTab.tsx");
  assert.match(page, /is_private: isPrivate,\s*only_for: companies,/);
  assert.match(page, /checked=\{companies\.includes\(t\.code\)\}\s*onChange=\{\(e\) => setCompanies\(toggleCompany\(companies, t\.code, e\.target\.checked\)\)\}/);
  assert.match(page, /useState\(vendor\?\.is_private \?\? false\)/);          // 新的廠商預設全部公司(跟以前一樣)
  assert.match(page, /useState<string\[\]>\(vendor\?\.only_for \?\? \[\]\)/);
  assert.match(page, /\{isPrivate && \(\s*<Field label="給哪幾家">/);
  assert.match(page, /<Field label="誰看得到" error=\{audienceWarn \|\| undefined\}>/);
  const options = [...page.matchAll(/<option value="(?:all|some)">([^<]+)<\/option>/g)].map((m) => m[1]);
  assert.deepEqual(options, ["全部公司", "指定公司"]);
  assert.match(page, /\{v\.is_private && <span className="pv-audience">\{audienceLabel\(v\)\}<\/span>\}/);
});

// 全站控制項的自動檢查(docs/ui-controls.md §7;規則在 controlsPolicy.mjs)。跑法:npm test。
// 新寫的頁面另外造按鈕 / 分頁 / 開關外觀會變紅;現有的記在 controlsBaseline.json,只能減少。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { readAllCss } from "./cssText.mjs";
import test from "node:test";

import { BASELINE, parseCss, scanAll, scanCss, scanSource, tally } from "./controlsPolicy.mjs";

const rules = (vs) => vs.map((v) => v.rule).sort();

test("會攔:頁面自製藍按鈕(inline 外觀)、沒有名稱的 ×、用主要按鈕藍底表示選中、舊分頁樣式、可點的 div、複製開關", () => {
  const bad = `
    export function P({ tab, setTab }) {
      return (
        <div>
          <button style={{ background: "#2563eb", color: "#fff", padding: 12 }}>送出</button>
          <button onClick={() => setTab(null)}>×</button>
          <button className={tab === "a" ? "btn primary" : "btn"} onClick={() => setTab("a")}>甲</button>
          <div className="tab-switcher"><button className="tab-switcher-item">乙</button></div>
          <div onClick={() => setTab("b")}>丙</div>
          <label className="toggle-switch"><input type="checkbox" /></label>
          <button><CloseIcon /></button>
        </div>
      );
    }`;
  const found = rules(scanSource("pages/x/P.tsx", bad));
  for (const r of ["inline-look", "icon-no-name", "primary-as-state", "legacy-tab", "clickable-noninteractive", "copied-switch"]) {
    assert.ok(found.includes(r), `應該攔到 ${r}(攔到的:${found.join(", ")})`);
  }
  assert.equal(found.filter((r) => r === "icon-no-name").length, 2, "× 與只有圖示的按鈕都要攔");
});

test("也會攔(淡色複查找到的漏網寫法):variant 依狀態切 primary、「選中 && primary」、同一排兩顆主要按鈕、膠囊鈕依狀態變色", () => {
  const bad = `
    export function P({ sel, setSel }) {
      return (
        <div>
          <Button variant={sel === "a" ? "primary" : "default"} onClick={() => setSel("a")}>甲</Button>
          <button className={cx("btn", sel === "b" && "primary")} onClick={() => setSel("b")}>乙</button>
          <div className="row">
            <button className="btn primary">儲存</button>
            <Button variant="primary">送出</Button>
          </div>
          <button className={\`wb-chip\${sel === "c" ? " on" : ""}\`} onClick={() => setSel("c")}>丙</button>
        </div>
      );
    }`;
  const found = rules(scanSource("pages/x/Q.tsx", bad));
  assert.equal(found.filter((r) => r === "primary-as-state").length, 2, `variant 與 && 各一(攔到的:${found.join(", ")})`);
  assert.ok(found.includes("multiple-primary"), "同一排兩顆主要按鈕");
  assert.ok(found.includes("chip-as-state"), "wb-chip on");
  // 反例:一排只有一顆主要按鈕、選中用 SegmentedControl,不攔
  const ok = `
    export function P({ sel, setSel }) {
      return (
        <div className="row">
          <Button>取消</Button>
          <Button variant="primary">儲存</Button>
          <SegmentedControl label="方式" value={sel} onChange={setSel} options={[]} />
        </div>
      );
    }`;
  assert.deepEqual(scanSource("pages/x/Q.tsx", ok), []);
});

test("共用外觀契約(淡色):主要按鈕不是鮮藍實心白字、單選列選中不借表格選取色、工具列欄位跟頁面同底", () => {
  const css = readAllCss();
  const rule = (sel) => parseCss(css).filter((r) => r.selector.split(",").map((x) => x.trim()).includes(sel));
  const decl = (sel, prop) => rule(sel).flatMap((r) => r.decls).filter(([p]) => p === prop).map(([, v]) => v);
  for (const sel of [".btn.primary", ':root[data-theme="light"] .btn.primary']) {
    const bg = decl(sel, "background");
    const color = decl(sel, "color");
    assert.ok(bg.length > 0 && bg.every((v) => v === "var(--primary-bg)"), `${sel} 的底是 --primary-bg(現在:${bg})`);
    assert.ok(color.every((v) => v === "var(--primary-text)" && !/#fff/i.test(v)), `${sel} 的字是 --primary-text(現在:${color})`);
  }
  assert.ok(!decl('.ui-seg-item[aria-checked="true"]', "background").some((v) => /row-selected|accent/.test(v)), "單選列選中用控制項自己的中性色");
  assert.deepEqual(decl(".ui-toolbar .ui-tf select", "background"), ["var(--ctl-bg)"]);
  assert.match(css, /--ctl-bg: transparent;/);
});

test("不攔:用共用元件、有名稱的圖示按鈕、純排版的 style、有角色與 tabIndex 的可點容器;共用層自己不算", () => {
  const good = `
    export function P({ tab, setTab }) {
      return (
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="primary">送出</Button>
          <IconButton label="關閉維修歷史">×</IconButton>
          <button aria-label="移除第 2 筆商品">×</button>
          <button style={{ width: 120 }}>寬一點</button>
          <Tabs id="t" label="叫貨" items={[]} value="a" onChange={setTab} />
          <tr role="button" tabIndex={0} onClick={() => setTab("x")}><td>列</td></tr>
        </div>
      );
    }`;
  assert.deepEqual(scanSource("pages/x/P.tsx", good), []);
  assert.deepEqual(scanSource("components/ui/Button.tsx", `<button style={{ background: "red" }}>x</button>`), [], "共用層定義外觀是對的");
});

test("CSS:頁面另外改控制項外觀、拿掉焦點框會攔;純排版、共用層、focus-visible 不攔", () => {
  const css = `
    .page-x .btn { border-radius: 12px; }
    .vo-chip-btn { background: #333; padding: 2px; }
    .x-input:focus { outline: none; }
    .layout { display: flex; gap: 8px; }
    .btn.primary { background: var(--accent-fill); }
    .ui-tab[aria-selected="true"] { color: var(--text); }
    .ui-tab:focus-visible { outline: 2px solid var(--accent); }
    @media (pointer: coarse) { .other-btn { min-height: 44px; } }`;
  const found = scanCss("x.css", css);
  assert.deepEqual(rules(found), ["css-control-look", "css-control-look", "css-control-look", "css-outline-none"]);
  assert.ok(found.some((v) => v.fp.includes(".other-btn")), "@media 裡的也看");
  assert.equal(parseCss(".a{color:red}\n/* .b{color:blue} */\n.c{gap:1px}").length, 2, "註解裡的不算");
});

test("現在的程式:沒有比基線多出來的違規(新寫法用共用元件;搬掉舊寫法後重產基線,diff 只能是刪除)", () => {
  const now = tally(scanAll());
  const base = JSON.parse(readFileSync(BASELINE, "utf8"));
  const extra = Object.entries(now).filter(([fp, n]) => n > (base[fp] ?? 0)).map(([fp, n]) => `${fp}(現在 ${n},基線 ${base[fp] ?? 0})`);
  assert.deepEqual(extra, [], `新的控制項違規(照 docs/ui-controls.md 改用 components/ui):\n${extra.join("\n")}`);
  assert.ok(!Object.keys(base).some((fp) => /\|components\/ui\/|\|pages\/dev\//.test(fp)), "共用層不放進基線");
});

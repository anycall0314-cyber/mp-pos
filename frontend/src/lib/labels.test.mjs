// 商品標籤:條碼的每一條線要剛好是印表機的整數個點(不然熱感印出來刷不到);張數不能亂。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { code128Bits } from "./code128.ts";
import {
  LABEL,
  MAX_SHEETS,
  MAX_TOTAL_SHEETS,
  NUDGE,
  barAreaDots,
  barTopMm,
  copiesOf,
  dotsToMm,
  expandSheets,
  foldMm,
  halfText,
  layoutBars,
  leftPadDots,
  moveNudge,
  nudgeText,
  printableCode,
  readNudge,
  rocDay,
  shouldAutoPrint,
  splitTail,
  squeezeFor,
  totalSheets,
} from "./labels.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("45 mm 的標籤扣掉左右留白,條碼可以用 336 個點", () => {
  assert.equal(barAreaDots(), 336);
  assert.equal(dotsToMm(336), 42);
  assert.equal(dotsToMm(1), 0.125);
});

test("上下兩聯:撕線在正中間,條碼跨在撕線上、上下各一半", () => {
  assert.equal(LABEL.widthMm, 45);
  assert.equal(LABEL.heightMm, 25);
  assert.equal(foldMm(), 12.5);
  assert.ok(Math.abs(barTopMm() - 8.9) < 1e-9);
  // 條碼的正中間就是撕線
  assert.ok(Math.abs(barTopMm() + LABEL.barHeightMm / 2 - foldMm()) < 1e-9);
  // 一聯留得下的條碼至少 3 mm 高(再矮槍很難對)
  assert.ok(LABEL.barHeightMm / 2 >= 3);
});

test("樣式裡的尺寸跟 LABEL 是同一組數字", () => {
  const css = read("../styles.css");
  assert.ok(css.includes(`@page label { size: ${LABEL.widthMm}mm ${LABEL.heightMm}mm; margin: 0; }`));
  const tile = css.match(/\.label-tile \{[^}]*\}/)[0];
  assert.match(tile, new RegExp(`width: ${LABEL.widthMm}mm;`));
  // 比紙矮一點(剛好一樣高會每張多吐一張空白的),但不能矮到下半那一聯放不下
  const height = Number(tile.match(/height: ([\d.]+)mm;/)[1]);
  assert.ok(height < LABEL.heightMm && height >= LABEL.heightMm - 0.5, String(height));
  const half = css.match(/\.label-half \{[^}]*\}/)[0];
  assert.match(half, new RegExp(`left: ${LABEL.sideMarginMm}mm; right: ${LABEL.sideMarginMm}mm;`));
  const halfHeight = Number(half.match(/height: ([\d.]+)mm;/)[1]);
  const top = Number(css.match(/\.label-half\.top \{ top: ([\d.]+)mm; \}/)[1]);
  const bottom = Number(css.match(/\.label-half\.bottom \{ top: ([\d.]+)mm;/)[1]);
  // 上半那一聯不能印過撕線,下半那一聯不能從撕線上面開始、也不能超出那一張
  assert.ok(top + halfHeight < foldMm(), "上半超過撕線");
  assert.ok(bottom > foldMm(), "下半從撕線上面開始");
  assert.ok(bottom + halfHeight <= height, "下半超出標籤");
  // 兩聯對稱:離撕線一樣遠
  assert.ok(Math.abs((foldMm() - (top + halfHeight)) - (bottom - foldMm())) < 1e-9);
  // 每一聯留給條碼的那一半,要蓋得住條碼伸進來的那一截
  const slot = Number(css.match(/\.label-slot \{[^}]*height: ([\d.]+)mm;/)[1]);
  assert.ok(slot + (foldMm() - (top + halfHeight)) >= LABEL.barHeightMm / 2 - 1e-9, "條碼會蓋到碼的字");
  // 測試標籤對撕線的短線:線的正中間在撕線上
  const fold = css.match(/\.label-fold \{ position: absolute; top: ([\d.]+)mm; width: [\d.]+mm; border-top: ([\d.]+)mm solid #000; \}/);
  assert.ok(Math.abs(Number(fold[1]) + Number(fold[2]) / 2 - foldMm()) < 1e-9);
});

test("品名放不下才壓扁,最多壓到下限", () => {
  assert.equal(squeezeFor(100, 200), 1);
  assert.equal(squeezeFor(197, 200), 1);                       // 留的那一點點以內:不壓
  // 剛好一樣寬也要壓一點:螢幕上量的跟印出來的會差一點,不留的話最後一個字的邊會被切到
  assert.ok(squeezeFor(200, 200) < 1 && squeezeFor(200, 200) > 0.98);
  assert.ok(Math.abs(squeezeFor(250, 200) - 200 * LABEL.nameRoom / 250) < 1e-12);
  assert.ok(250 * squeezeFor(250, 200) < 200);                 // 壓完一定進得去
  assert.equal(squeezeFor(1000, 200), LABEL.minSqueeze);      // 再長就切掉尾巴,不壓到看不懂
  assert.equal(squeezeFor(0, 200), 1);                         // 量不到寬度:不壓
  assert.equal(squeezeFor(200, 0), 1);
  assert.equal(squeezeFor(NaN, 200), 1);
});

test("日期印中華民國年月日、不分隔", () => {
  assert.equal(rocDay("2026-10-06"), "1151006");
  assert.equal(rocDay("2025-02-04"), "1140204");                // 舊標籤上的那一種
  assert.equal(rocDay("2011-01-01"), "1000101");
  assert.equal(rocDay("2010-12-31"), "991231");                 // 民國兩位數的年不補 0
  assert.equal(rocDay("2026-10-06T08:00:00+08:00"), "1151006");
  assert.equal(rocDay(""), "");
  assert.equal(rocDay("1151006"), "");                          // 看不懂的不印,不猜
  assert.equal(rocDay("1900-01-01"), "");                       // 民國前
});

test("一聯上面印什麼:有序號的只印末 5 碼,配件印整串", () => {
  const phone = { code_kind: "serial", sku: "PH-000001", last5: "45671", doc_no: "PO-000001", doc_date: "2026-10-06" };
  // 有序號、條碼印得出來:字只有末 5 碼(整支序號不印成字)
  assert.deepEqual(halfText(phone, "356789012345671", true),
    { source: "PO-000001 · 1151006", mode: "tail", head: "", tail: "45671", sku: "PH-000001" });
  // 印不出條碼的序號:只剩字可以對,整串都印(末 5 碼另外給,畫面標粗)
  assert.deepEqual(halfText({ ...phone, last5: "XYZ77" }, "R58M12345ABXYZ77", false),
    { source: "PO-000001 · 1151006", mode: "full", head: "R58M12345AB", tail: "XYZ77", sku: "PH-000001" });
  // 序號比 5 碼還短:就印它
  assert.equal(halfText({ ...phone, last5: "A12" }, "A12", true).tail, "A12");
  // 配件:原廠條碼整串印,右邊是品號
  const part = { code_kind: "barcode", sku: "G03-000330", last5: "", doc_no: "PO-000002", doc_date: "2025-02-04" };
  assert.deepEqual(halfText(part, "4710007836224", true),
    { source: "PO-000002 · 1140204", mode: "full", head: "4710007836224", tail: "", sku: "G03-000330" });
  // 條碼印的就是品號(沒有原廠條碼、或原廠條碼太長改印品號):右邊不重複印品號
  assert.equal(halfText({ ...part, code_kind: "sku" }, "G03-000330", true).sku, "");
  assert.equal(halfText({ ...part, sku: " G03-000330 " }, "G03-000330", true).sku, "");
  // 配件補印沒有哪一張單:那一格是空的;只有單號或只有日期就只印有的
  assert.equal(halfText({ ...part, doc_no: "", doc_date: "" }, "4710007836224", true).source, "");
  assert.equal(halfText({ ...part, doc_date: "" }, "4710007836224", true).source, "PO-000002");
  assert.equal(halfText({ ...part, doc_no: "" }, "4710007836224", true).source, "1140204");
});

test("標籤的畫面:上下兩聯都畫、印什麼照 halfText", () => {
  const tile = read("../components/labels/LabelTile.tsx");
  assert.match(tile, /\{half\("top"\)\}/);
  assert.match(tile, /\{half\("bottom"\)\}/);
  assert.match(tile, /const text = halfText\(label, code, bars\);/);
  // 畫面不自己決定印哪個日期、哪幾碼
  assert.doesNotMatch(tile, /label\.doc_date|label\.doc_no|label\.last5|\.slice\(/);
  // 條碼的位置從 LABEL 算(不寫死)
  assert.match(tile, /top: `\$\{barTopMm\(\)\}mm`/);
  assert.match(tile, /left: `\$\{LABEL\.sideMarginMm \+ dotsToMm\(leftPadDots\(layout\.widthDots\)\)\}mm`/);
});

test("位置微調:一次一格、不超過上限、壞掉的設定收回來", () => {
  const zero = { x: 0, y: 0 };
  // 一格是印表機的整數個點:條碼的線推完還在點上
  assert.equal((NUDGE.stepMm * LABEL.dotsPerMm) % 1, 0);
  for (const raw of [null, undefined, "", "不是 JSON", "null", "12", '{"x":"1","y":[]}', '{"x":null}', '{"x":1e999}']) {
    assert.deepEqual(readNudge(raw), zero, String(raw));
  }
  assert.deepEqual(readNudge('{"x":-0.5,"y":-0.75}'), { x: -0.5, y: -0.75 });
  assert.deepEqual(readNudge('{"x":0.3,"y":-0.6}'), { x: 0.25, y: -0.5 });      // 不在格子上的收到最近的一格
  assert.deepEqual(readNudge('{"x":99,"y":-99}'), { x: NUDGE.maxMm, y: -NUDGE.maxMm });   // 推到紙外面的設定收回來
  // 印出來偏下按「往上」:往上、往左是負的
  assert.deepEqual(moveNudge(zero, "up"), { x: 0, y: -0.25 });
  assert.deepEqual(moveNudge(zero, "down"), { x: 0, y: 0.25 });
  assert.deepEqual(moveNudge(zero, "left"), { x: -0.25, y: 0 });
  assert.deepEqual(moveNudge(zero, "right"), { x: 0.25, y: 0 });
  assert.deepEqual(moveNudge({ x: 0.5, y: -0.75 }, "up"), { x: 0.5, y: -1 });  // 只動那一個方向
  // 到上限就不再動
  assert.deepEqual(moveNudge({ x: 0, y: -NUDGE.maxMm }, "up"), { x: 0, y: -NUDGE.maxMm });
  assert.deepEqual(moveNudge({ x: NUDGE.maxMm, y: 0 }, "right"), { x: NUDGE.maxMm, y: 0 });
  // 推回來是 0,不是 −0(畫面會把 −0 印成「上 0」);存的數字比半格還小也是
  assert.ok(Object.is(readNudge('{"x":-0.1,"y":-0.1}').x, 0));
  assert.ok(Object.is(readNudge('{"x":-0.1,"y":-0.1}').y, 0));
  assert.ok(Object.is(moveNudge({ x: 0, y: -0.25 }, "down").y, 0));
  assert.ok(Object.is(moveNudge({ x: 0.25, y: 0 }, "left").x, 0));
  // 連按十二下往上再十二下往下:回到原點(一格一格加不會累積出小數的誤差)
  let at = zero;
  for (let i = 0; i < 12; i += 1) at = moveNudge(at, "up");
  assert.deepEqual(at, { x: 0, y: -3 });
  for (let i = 0; i < 12; i += 1) at = moveNudge(at, "down");
  assert.deepEqual(at, zero);
});

test("位置微調:畫面上寫現在推了多少", () => {
  assert.equal(nudgeText({ x: 0, y: 0 }), "");
  assert.equal(nudgeText({ x: 0, y: -0.75 }), "上 0.75 mm");
  assert.equal(nudgeText({ x: 0, y: 1 }), "下 1 mm");
  assert.equal(nudgeText({ x: -0.25, y: 0 }), "左 0.25 mm");
  assert.equal(nudgeText({ x: 1.5, y: -0.5 }), "上 0.5 · 右 1.5 mm");
});

test("位置微調:推的是整張的內容,外框與紙不動;只有測試標籤那一頁能調", () => {
  const css = read("../styles.css");
  assert.ok(css.includes(".label-inner { position: absolute; inset: 0; transform: translate(var(--label-dx, 0mm), var(--label-dy, 0mm)); }"));
  const tile = read("../components/labels/LabelTile.tsx");
  // 兩聯、條碼、對撕線的短線都在會被推的那一層裡面;外框是標籤自己的(留在紙的四邊)
  const from = tile.indexOf('<div className="label-inner">');
  // 那一層收尾之後緊接著就是標籤自己收尾:中間沒有別的東西(放在這裡的不會跟著推)
  const to = tile.indexOf("      </div>\n    </div>\n  );\n});");
  assert.ok(from > 0 && to > from, "找不到會被推的那一層,或它後面還有別的東西");
  const inner = tile.slice(from, to);
  for (const piece of ['{half("top")}', '{half("bottom")}', 'className="label-bars"', 'className="label-fold l"', 'className="label-fold r"']) {
    assert.ok(inner.includes(piece), piece);
  }
  assert.match(css, /\.label-frame::before \{[^}]*inset: 0;[^}]*\}/);
  const page = read("../pages/labels/LabelPrintPage.tsx");
  // 數字帶著單位填進樣式;讀與存都用同一把鑰匙、讀回來的一律先收過
  assert.ok(page.includes('style={{ "--label-dx": `${nudge.x}mm`, "--label-dy": `${nudge.y}mm` } as React.CSSProperties}'));
  assert.ok(page.includes("readNudge(window.localStorage.getItem(NUDGE.storageKey))"));
  assert.ok(page.includes("window.localStorage.setItem(NUDGE.storageKey, JSON.stringify(nudge))"));
  // 每按一下都接在上一下後面(不是從這一次畫面抓到的那個算)
  assert.ok(page.includes("const next = change(nudgeNow.current);"));
  assert.ok(page.includes("onClick={() => changeNudge((now) => moveNudge(now, move))}"));
  // 四顆按鈕只在測試標籤那一頁;平常的列印頁只寫現在推了多少
  assert.match(page, /\{test \? \(\s*<div className="label-bar-nudge">/);
  assert.match(page, /nudged && <div>位置 \{nudged\}<\/div>/);
  // 位置微調不算「要先讓人看到的提醒」:不會擋住自己跳出來的列印視窗
  assert.doesNotMatch(page.match(/const hasWarning = [^;]*;/)[0], /nudge/);
});

test("標籤上的小字都是粗體(熱感印表機細的筆畫印不出來)", () => {
  const css = read("../styles.css");
  for (const cls of ["label-name", "label-src", "label-grade", "label-price", "label-code", "label-last5", "label-sku", "label-nobars"]) {
    const rule = css.match(new RegExp(`\\.${cls} \\{[^}]*\\}`));
    assert.ok(rule, cls);
    assert.match(rule[0], /font-weight: (700|900);/, cls);
  }
});

test("序號拆出末 5 碼;紙上印的不是那一串就拆不出來", () => {
  assert.deepEqual(splitTail("356789012345671", "45671"), ["3567890123", "45671"]);
  assert.deepEqual(splitTail("CH-000007", "45671"), ["CH-000007", ""]);       // 改印品號:末 5 碼是別的碼的
  assert.deepEqual(splitTail("4710000123456", ""), ["4710000123456", ""]);    // 配件沒有末 5 碼
  assert.deepEqual(splitTail("45671", "45671"), ["45671", ""]);               // 整串就那幾碼:不用標
});

test("Code 128:開頭、結尾與長度", () => {
  const imei = code128Bits("356789012345671");
  // 15 位數字:起始 + 7 組兩位數 + 換碼 + 最後一位 + 檢查碼,各 11 個單位,結尾 13 個單位
  assert.equal(imei.length, 11 * 11 + 13);
  assert.ok(imei.startsWith("11010011100"));          // 起始碼 C
  assert.ok(imei.endsWith("1100011101011"));          // 結尾
  assert.equal(code128Bits("LC-000001").slice(0, 11), "11010010000");   // 起始碼 B
  assert.equal(code128Bits(""), null);
  assert.equal(code128Bits("中文品號"), null);         // Code 128 沒有的字:不編
  assert.equal(code128Bits("１２３"), null);            // 全形數字
  assert.equal(code128Bits("AB\tCD"), null);          // Tab / 換行:編得進去、紙上卻看不出來,不收
  assert.equal(code128Bits("AB\nCD"), null);
  // 給什麼就編什麼:頭尾的空白不偷偷去掉(去不去由 printableCode 決定,條碼跟字才會是同一個字串)
  assert.equal(code128Bits("AB").length + 11, code128Bits("AB ").length);
});

test("每一條線都是整數個點、而且是同一個倍數", () => {
  for (const value of ["356789012345671", "LC-000001", "4710000123456", "F2LXK1ABCD", "A1"]) {
    const bits = code128Bits(value);
    const layout = layoutBars(bits);
    assert.ok(layout, value);
    assert.ok([2, 3].includes(layout.moduleDots), value);
    for (const bar of layout.bars) {
      assert.equal(bar.x % layout.moduleDots, 0, value);
      assert.equal(bar.w % layout.moduleDots, 0, value);
      assert.ok(bar.w > 0);
    }
    // 黑線的總寬 = 樣式裡 1 的個數 × 倍數(沒有少畫、沒有多畫)
    const black = [...bits].filter((b) => b === "1").length;
    assert.equal(layout.bars.reduce((sum, b) => sum + b.w, 0), black * layout.moduleDots, value);
    // 兩邊各留 10 個單位的空白,整個放得進可用寬度
    assert.equal(layout.bars[0].x, LABEL.quietModules * layout.moduleDots, value);
    assert.equal(layout.widthDots, (bits.length + 20) * layout.moduleDots, value);
    assert.ok(layout.widthDots <= barAreaDots(), value);
  }
});

test("放得下用 3 點,放不下用 2 點", () => {
  assert.equal(layoutBars(code128Bits("A1")).moduleDots, 3);                 // 短的:線粗一點比較好刷
  assert.equal(layoutBars(code128Bits("356789012345671")).moduleDots, 2);    // IMEI:3 點放不下
  assert.equal(layoutBars(code128Bits("F2LXK1ABCD")).moduleDots, 2);         // 10 碼英數的序號:剛好放得下
});

test("不用細線(一個單位 1 點):2 點放不下的序號沒有條碼、整串印成字", () => {
  // owner 2026-10-13:「不要用細線，熱感紙粉久會掉墨變淡掃不到」
  assert.deepEqual([...LABEL.moduleDots], [3, 2]);
  const bits = code128Bits("F2LXK1ABCDEF");
  assert.equal(layoutBars(bits), null);                                      // 12 碼英數:印不下,不印條碼
  assert.equal(layoutBars(code128Bits("F2LXK1ABCD")).moduleDots, 2);         // 10 碼:2 點剛好放得下
  const printed = printableCode({ code: "F2LXK1ABCDEF", code_kind: "serial", sku: "PH-0001" }, (c) => layoutBars(code128Bits(c)) !== null);
  assert.deepEqual(printed, { code: "F2LXK1ABCDEF", bars: false, swapped: false });   // 有序號的不會改印品號:就是沒有條碼
  const text = halfText({ doc_no: "PO-1", doc_date: "", sku: "PH-0001", code_kind: "serial", last5: "BCDEF" }, printed.code, printed.bars);
  assert.deepEqual([text.mode, text.head, text.tail], ["full", "F2LXK1A", "BCDEF"]);  // 整串印出來,末 5 碼另外一段(標粗)
  // 畫面不另外給線寬、也沒有細線的開關
  const tile = readFileSync(new URL("../components/labels/LabelTile.tsx", import.meta.url), "utf8");
  assert.match(tile, /function barsFor\(code: string\): BarLayout \| null \{\s*const bits = code128Bits\(code\);\s*if \(!bits\) return null;\s*return layoutBars\(bits\);/);
  const page = readFileSync(new URL("../pages/labels/LabelPrintPage.tsx", import.meta.url), "utf8");
  for (const src of [tile, page, readFileSync(new URL("../api/labels.ts", import.meta.url), "utf8")]) {
    assert.doesNotMatch(src, /thin_bars|moduleDotsFor|serialModuleDots/);
  }
});

test("太長的碼不印條碼(不印糊的)", () => {
  assert.equal(layoutBars(code128Bits("ABCDEFGHJKLMNP")), null);             // 14 碼英數:2 點也放不下
  assert.equal(layoutBars(code128Bits("F2LXK1ABCDE")), null);                // 45 mm 的紙:11 碼英數就放不下了
  assert.equal(layoutBars("1101", 40), null);                                // 寬度根本不夠
  assert.equal(layoutBars(""), null);
  assert.equal(layoutBars("11x1"), null);
});

test("原廠條碼太長就改印品號;序號太長不能換", () => {
  const fits = (code) => layoutBars(code128Bits(code) ?? "") !== null;
  const long = "T03OPPOAK779VOOC";                                           // 16 碼英數:印不下
  assert.equal(fits(long), false);
  assert.deepEqual(printableCode({ code: "4710000123456", code_kind: "barcode", sku: "CH-000007" }, fits),
    { code: "4710000123456", bars: true, swapped: false });
  assert.deepEqual(printableCode({ code: long, code_kind: "barcode", sku: "CH-000007" }, fits),
    { code: "CH-000007", bars: true, swapped: true });
  // 這一台的序號太長:不能拿品號頂替(刷不到這一台),只印文字
  assert.deepEqual(printableCode({ code: long, code_kind: "serial", sku: "CH-000007" }, fits),
    { code: long, bars: false, swapped: false });
  // 品號自己也印不下(有條碼沒有的字):只印文字
  assert.deepEqual(printableCode({ code: long, code_kind: "barcode", sku: "中文品號" }, fits),
    { code: long, bars: false, swapped: false });
  assert.deepEqual(printableCode({ code: "中文品號", code_kind: "sku", sku: "中文品號" }, fits),
    { code: "中文品號", bars: false, swapped: false });
});

test("頭尾有空白的碼:條碼跟下面的字用同一個去掉空白的字串", () => {
  const fits = (code) => layoutBars(code128Bits(code) ?? "") !== null;
  const printed = printableCode({ code: " 4710000123456 ", code_kind: "barcode", sku: "CH-000007" }, fits);
  assert.deepEqual(printed, { code: "4710000123456", bars: true, swapped: false });
  // 真正拿去編條碼的就是回傳的那個字串(沒有多一個空白的單位)
  assert.equal(code128Bits(printed.code), code128Bits("4710000123456"));
  assert.deepEqual(printableCode({ code: "356789012345671\n", code_kind: "serial", sku: "PH-1" }, fits),
    { code: "356789012345671", bars: true, swapped: false });
  // 換成品號時,品號也去空白
  assert.deepEqual(printableCode({ code: "T03OPPOAK779VOOC", code_kind: "barcode", sku: " CH-000007 " }, fits),
    { code: "CH-000007", bars: true, swapped: true });
  // 中間的連續空白是碼的一部分:原樣留著(條碼編的、字印的都是這一串;樣式用 white-space: pre 才不會被併成一個)
  assert.deepEqual(printableCode({ code: "AB  CD", code_kind: "serial", sku: "PH-1" }, fits),
    { code: "AB  CD", bars: true, swapped: false });
  assert.notEqual(code128Bits("AB  CD"), code128Bits("AB CD"));
  // 中間夾著 Tab:不印條碼(字照印)
  assert.deepEqual(printableCode({ code: "AB\tCD", code_kind: "serial", sku: "PH-1" }, fits),
    { code: "AB\tCD", bars: false, swapped: false });
});

test("置中時左邊空的也是整數個點", () => {
  assert.equal(leftPadDots(308), 14);
  assert.equal(leftPadDots(335), 0);
  assert.equal(leftPadDots(336), 0);
  assert.equal(leftPadDots(400), 0);       // 不會是負的
});

test("張數:某一台固定 1 張;配件照改過的張數", () => {
  const unit = { key: "s1", serial_id: 7, copies: 1 };
  const acc = { key: "i2", serial_id: null, copies: 12 };
  assert.equal(copiesOf(unit, { s1: 9 }), 1);
  assert.equal(copiesOf(acc, {}), 12);
  assert.equal(copiesOf(acc, { i2: 3 }), 3);
  assert.equal(copiesOf(acc, { i2: 0 }), 0);                 // 0 = 這一筆不印
  assert.equal(copiesOf(acc, { i2: -4 }), 0);
  assert.equal(copiesOf(acc, { i2: 2.5 }), 0);
  assert.equal(copiesOf(acc, { i2: 99999 }), MAX_SHEETS);
});

test("什麼時候自己跳出列印視窗", () => {
  const ok = { auto: true, total: 12, hasWarning: false };
  assert.equal(shouldAutoPrint(ok), true);
  assert.equal(shouldAutoPrint({ ...ok, total: 100 }), true);
  assert.equal(shouldAutoPrint({ ...ok, total: 101 }), false);       // 張數很多:先讓人看一眼
  assert.equal(shouldAutoPrint({ ...ok, total: 0 }), false);         // 沒有東西要印
  assert.equal(shouldAutoPrint({ ...ok, hasWarning: true }), false); // 有提醒要先看(列印視窗會把它蓋住)
  assert.equal(shouldAutoPrint({ ...ok, auto: false }), false);
});

test("整批超過上限就不展開(請人把張數改少)", () => {
  const lines = [1, 2, 3].map((n) => ({ key: `i${n}`, serial_id: null, copies: 400 }));
  assert.equal(totalSheets(lines, {}), 1200);
  assert.ok(1200 > MAX_TOTAL_SHEETS);
  assert.deepEqual(expandSheets(lines, {}), []);
  // 把其中一行改少,落在上限以內就照常展開
  assert.equal(totalSheets(lines, { i3: 200 }), 1000);
  assert.equal(expandSheets(lines, { i3: 200 }).length, 1000);
  assert.equal(totalSheets([{ key: "s1", serial_id: 5, copies: 1 }], { s1: 50 }), 1);
});

test("照張數展開成一張一張,順序不變、每一張有自己的編號", () => {
  const entries = [
    { key: "s1", serial_id: 7, copies: 1 },
    { key: "i2", serial_id: null, copies: 2 },
    { key: "i3", serial_id: null, copies: 5 },
  ];
  const sheets = expandSheets(entries, { i3: 0 });
  assert.deepEqual(sheets.map((s) => s.key), ["s1-0", "i2-0", "i2-1"]);
  assert.equal(sheets[1].entry, entries[1]);
  assert.equal(new Set(sheets.map((s) => s.key)).size, sheets.length);
});

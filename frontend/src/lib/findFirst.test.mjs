// 「新增商品先找一次」:沒查成功不能當成沒有、舊的結果不能拿來選用或往下建。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  ask,
  askable,
  barcodeIn,
  createPrefill,
  fail,
  hasEveryWord,
  IDLE,
  looksLikeBarcode,
  mergeRows,
  queryWords,
  rememberNote,
  rememberTone,
  reset,
  rowFacts,
  rowWhy,
  searchText,
  settle,
  stillUsable,
  stockScope,
  viewOf,
  WHY_ALIKE,
  WHY_WORDS,
} from "./findFirst.ts";

const product = (id, extra = {}) => ({
  id,
  sku: `P${id}`,
  name: `商品${id}`,
  spec: "",
  category_name: "",
  stock_qty: 0,
  is_active: true,
  ...extra,
});
const row = (id, extra = {}) => ({ product: product(id, extra), reasons: [], differences: [] });

test("還沒找過:沒有候選,也不能往下建", () => {
  const v = viewOf(IDLE, "11PM 玻璃貼");
  assert.deepEqual(v, { rows: [], stale: false, canUse: false, canCreate: false, note: "" });
});

test("框裡沒字不找", () => {
  assert.equal(askable("   "), false);
  assert.equal(askable(" 11PM "), true);
  assert.equal(ask(IDLE, "   "), IDLE);
});

test("還在找:不能顯示成沒有商品,不能往下建", () => {
  const s = ask(IDLE, " 11PM 玻璃貼 ");
  assert.deepEqual(s, { phase: "loading", seq: 1, asked: "11PM 玻璃貼" });
  const v = viewOf(s, "11PM 玻璃貼");
  assert.equal(v.canCreate, false);
  assert.equal(v.canUse, false);
  assert.equal(v.note, "尋找中…");
});

test("沒查成功:不是「沒有找到」,不能往下建", () => {
  const s = fail(ask(IDLE, "11PM"), 1, "連線逾時");
  assert.equal(s.phase, "error");
  const v = viewOf(s, "11PM");
  assert.equal(v.canCreate, false);
  assert.equal(v.canUse, false);
  assert.equal(v.note, "沒有查成功,請再找一次");
  assert.notEqual(v.note, "沒有找到");
});

test("查成功、真的沒有:寫沒有找到,可以往下建", () => {
  const s = settle(ask(IDLE, "11PM"), 1, []);
  const v = viewOf(s, "11PM");
  assert.deepEqual(v, { rows: [], stale: false, canUse: true, canCreate: true, note: "沒有找到" });
});

test("查成功、有候選:可以選用,也可以往下建", () => {
  const s = settle(ask(IDLE, "11PM"), 1, [row(7)]);
  const v = viewOf(s, " 11PM ");   // 頭尾空白不算改過
  assert.equal(v.rows.length, 1);
  assert.equal(v.stale, false);
  assert.equal(v.canUse, true);
  assert.equal(v.canCreate, true);
  assert.equal(v.note, "");
});

test("字改過了:先前的候選只能看,不能選用、不能往下建", () => {
  const s = settle(ask(IDLE, "11PM"), 1, [row(7)]);
  const v = viewOf(s, "12PM");
  assert.equal(v.rows.length, 1);
  assert.equal(v.stale, true);
  assert.equal(v.canUse, false);
  assert.equal(v.canCreate, false);
  assert.equal(v.note, "內容改了,請再找一次");
});

test("先前沒找到、字改過了:也不能拿先前那一次當找過", () => {
  const s = settle(ask(IDLE, "11PM"), 1, []);
  const v = viewOf(s, "11PM 玻璃貼");
  assert.equal(v.canCreate, false);
  assert.equal(v.note, "內容改了,請再找一次");
});

test("比較晚回來的舊回應不算數", () => {
  const first = ask(IDLE, "11PM");
  const second = ask(first, "12PM");
  assert.equal(second.seq, 2);
  // 第一次的回應晚到:不能蓋掉第二次
  assert.equal(settle(second, 1, [row(7)]), second);
  assert.equal(fail(second, 1, "逾時"), second);
  const done = settle(second, 2, [row(8)]);
  assert.equal(done.phase, "done");
  assert.equal(done.asked, "12PM");
  assert.equal(done.rows[0].product.id, 8);
  // 已經有結果之後,同一個號碼再回來一次也不動它
  assert.equal(settle(done, 2, []), done);
  assert.equal(fail(done, 2, "逾時"), done);
});

test("關掉再開:清掉重來,關掉之前送出去的回應回來也不算", () => {
  const loading = ask(IDLE, "11PM");
  const closed = reset(loading);
  assert.deepEqual(closed, { phase: "idle", seq: 2 });
  assert.equal(settle(closed, 1, [row(7)]), closed);
  // 再開之後找的那一次用新的號碼
  assert.equal(ask(closed, "11PM").seq, 3);
});

const hit = (id, level, extra = {}) => ({
  product: product(id, extra),
  level,
  reasons: [`${level}的原因`],
  differences: level === "related" ? ["有差異"] : [],
});

test("品名裡是不是真的有打的每一段字:不分大小寫,空白與斜線分段,規格 / 類別 / 品號 / 條碼也算", () => {
  const phone = product(1, { name: "iPhone 15 512GB 黑色 台版 全新", sku: "PH-000199", barcode: "4710000000017" });
  assert.equal(hasEveryWord(phone, "iphone 15 512"), true);
  assert.equal(hasEveryWord(phone, "IPHONE/15"), true);
  assert.equal(hasEveryWord(phone, "ph-000199"), true);
  assert.equal(hasEveryWord(phone, "4710000000017"), true);
  assert.equal(hasEveryWord(phone, "iphone 15 保護貼"), false);   // 少一段就不算
  assert.equal(hasEveryWord(phone, "iphone 99 ultra"), false);
  assert.equal(hasEveryWord(product(2, { name: "滿版", spec: "霧面 防窺" }), "滿版 防窺"), true);
  assert.equal(hasEveryWord(product(3, { name: "IP15", category_name: "空壓殼" }), "ip15 殼"), true);
  assert.equal(hasEveryWord(phone, "   "), false);                // 沒有字不算「都有」
});

test("黏在一起打的對得上分開寫的(英文與數字之間可以隔著空白 / 斜線 / 連字號)", () => {
  const phone = product(1, { name: "iPhone 15 512GB 黑色" });
  assert.equal(hasEveryWord(phone, "iphone15"), true);
  assert.equal(hasEveryWord(phone, "iphone15 512gb"), true);
  assert.equal(hasEveryWord(product(2, { name: "皮套/SAM/NOTE-5/黑" }), "note5"), true);
  assert.equal(hasEveryWord(product(3, { name: "IMOS/IP15/2.5D" }), "ip 15 2.5d"), true);
  assert.equal(hasEveryWord(product(4, { name: "三星/NOTE/5/皮套" }), "note5"), true);   // 隔著斜線
  assert.equal(hasEveryWord(phone, "iphone16"), false);
  assert.equal(hasEveryWord(phone, "iphone1"), false);              // 15 不是 1
});

test("打的字裡有符號(. + 括號)照字面比,不會被當成別的意思、也不會壞掉", () => {
  assert.equal(hasEveryWord(product(1, { name: "IMOS/IP15/2.5D" }), "2.5d"), true);
  assert.equal(hasEveryWord(product(2, { name: "IMOS/IP15/215D" }), "2.5d"), false);   // 「.」不是「任何一個字」
  assert.equal(hasEveryWord(product(3, { name: "IP16+ 空壓殼" }), "ip16+"), true);
  assert.equal(hasEveryWord(product(4, { name: "空壓殼(黑)" }), "空壓殼(黑)"), true);
  assert.equal(hasEveryWord(product(5, { name: "空壓殼" }), "殼[黑]*?"), false);
});

test("連字號在打的那一邊、品名那一邊都只是分隔", () => {
  assert.equal(hasEveryWord(product(1, { name: "皮套/SAM NOTE5/黑" }), "皮套 SAM-NOTE5 黑"), true);
  assert.equal(hasEveryWord(product(2, { name: "皮套/SAM-NOTE5-黑" }), "皮套 sam note5 黑"), true);
  assert.equal(hasEveryWord(product(3, { name: "iPhone 15 512GB 黑色 台版 全新" }), "iPhone-15 512GB 黑色 台版 全新"), true);
  assert.equal(hasEveryWord(product(4, { name: "x", sku: "PH-000199" }), "ph-000199"), true);
  assert.equal(hasEveryWord(product(4, { name: "x", sku: "PH-000199" }), "ph-00019"), false);
  assert.equal(hasEveryWord(product(5, { name: "x" }), " - / "), false);   // 只有分隔符號 = 沒有字
});

test("純數字的那一段要是一整段數字才算:條碼、品號中間剛好有那幾個數字不算", () => {
  const caseA = product(1, { name: "iPhone 15 保護殼", sku: "G03-000512", barcode: "4719512345678" });
  assert.equal(hasEveryWord(caseA, "iphone 15 512"), false);       // 512 只在條碼中間、品號尾巴(000512 是一整段)
  assert.equal(hasEveryWord(caseA, "15"), true);
  assert.equal(hasEveryWord(product(2, { name: "iPhone 15 512GB" }), "512"), true);   // 後面接英文算
  assert.equal(hasEveryWord(product(3, { name: "犀牛盾/IP11PM/淺灰" }), "11"), true); // 前面接英文算
  assert.equal(hasEveryWord(product(4, { name: "2015 年曆" }), "15"), false);
  assert.equal(hasEveryWord(product(5, { name: "151 支架" }), "15"), false);
  assert.equal(hasEveryWord(product(6, { name: "A15 B151" }), "15"), true);           // 後面還有一個不合的,前面那個合就算
  assert.equal(hasEveryWord(product(7, { name: "B151 A15" }), "15"), true);           // 前面那個不合,要繼續往後看
  assert.equal(hasEveryWord(caseA, "4719512345678"), true);        // 整串條碼
  assert.equal(hasEveryWord(caseA, "471951234567"), false);        // 少一碼不是它
});

test("帶單位的數字也要是一整段:20W 不是 120W,12GB 不是 512GB", () => {
  assert.equal(hasEveryWord(product(1, { name: "充電器/120W" }), "充電器 20W"), false);
  assert.equal(hasEveryWord(product(2, { name: "充電器/20W" }), "充電器 20W"), true);
  assert.equal(hasEveryWord(product(3, { name: "充電器/PD20W" }), "充電器 20W"), true);   // 前面是英文算
  const phone = product(4, { name: "iPhone 15 512GB 黑色" });
  assert.equal(hasEveryWord(phone, "iphone15 12gb"), false);
  assert.equal(hasEveryWord(phone, "iphone15 512gb"), true);
  assert.equal(hasEveryWord(phone, "iphone15 512g"), true);        // 英文結尾可以只打前幾個字
  assert.equal(hasEveryWord(product(5, { name: "IP15/256G" }), "ip1 256g"), false);       // IP15 不是 IP1
});

test("小數是同一個數字:2.5D 裡沒有 5D,也沒有單獨的 2", () => {
  const film = product(1, { name: "IMOS/IP15/2.5D" });
  assert.equal(hasEveryWord(film, "imos ip15 5d"), false);
  assert.equal(hasEveryWord(film, "imos ip15 2.5d"), true);
  assert.equal(hasEveryWord(film, "imos ip15 2"), false);          // 2 後面接著 .5
  assert.equal(hasEveryWord(film, "imos ip15 2.5"), true);
  assert.equal(hasEveryWord(product(2, { name: "充電器2.5W" }), "5w"), false);
  assert.equal(hasEveryWord(product(3, { name: "充電器 5W" }), "5w"), true);
  assert.equal(hasEveryWord(product(4, { name: "螢幕 6.7吋" }), "7吋"), false);
  assert.equal(hasEveryWord(product(4, { name: "螢幕 6.7吋" }), "6.7吋"), true);
  // 不是小數的點不算:點前面不是數字、或點後面不是數字,兩邊就是各自的數字
  assert.equal(hasEveryWord(product(5, { name: "版本 v.5 殼" }), "5"), true);
  assert.equal(hasEveryWord(product(6, { name: "IP15. 殼" }), "15"), true);
  assert.equal(hasEveryWord(product(7, { name: ".5 折" }), "5"), true);
});

test("數字後面接的英文(單位、機型後綴)要是完整的:1.2M 不是 1.2MM,13P 不是 13PM", () => {
  assert.equal(hasEveryWord(product(1, { name: "主動式觸控筆 1.2MM 細筆尖" }), "1.2M"), false);
  assert.equal(hasEveryWord(product(2, { name: "Type-C 充電線 1.2M" }), "1.2M"), true);
  assert.equal(hasEveryWord(product(3, { name: "IP13PM/殼" }), "13p"), false);
  assert.equal(hasEveryWord(product(4, { name: "IP13PRO/殼" }), "13p"), false);
  assert.equal(hasEveryWord(product(5, { name: "IP13P/皮套" }), "13p"), true);
  assert.equal(hasEveryWord(product(6, { name: "IP15PM/殼" }), "ip15p"), false);
  assert.equal(hasEveryWord(product(7, { name: "IP15P/殼" }), "ip15p"), true);
  assert.equal(hasEveryWord(product(8, { name: "犀牛盾/IP11PM/淺灰" }), "11pm"), true);
  assert.equal(hasEveryWord(product(9, { name: "20W快充頭" }), "20w"), true);            // 後面是中文算完整
  // 不是接在數字後面的英文照舊可以只打前面:pro 對 promax
  assert.equal(hasEveryWord(product(10, { name: "IP13 PROMAX 殼" }), "13 pro"), true);
  assert.equal(hasEveryWord(product(11, { name: "iPhone 15" }), "iph 15"), true);
});

test("同一個單位的兩種寫法互相對得上:256G = 256GB、1T = 1TB;別的不行", () => {
  assert.equal(hasEveryWord(product(1, { name: "iPhone 15 256GB 黑" }), "256g"), true);
  assert.equal(hasEveryWord(product(2, { name: "IP15/256G/黑" }), "256gb"), true);
  assert.equal(hasEveryWord(product(3, { name: "iPhone 17 Pro 1TB" }), "1t"), true);
  assert.equal(hasEveryWord(product(4, { name: "IP17P/1T/藍" }), "1tb"), true);
  assert.equal(hasEveryWord(product(5, { name: "行動電源 5000MAH" }), "5000m"), false);   // m 不是 mah 的另一種寫法
  assert.equal(hasEveryWord(product(6, { name: "IP15/256GBX" }), "256g"), false);
});

test("數字跟單位分開打也是同一段:20 W 不會拿 20V 的 20 配 65W 的 W", () => {
  assert.deepEqual(queryWords("PD 20 W"), ["pd", "20w"]);
  assert.deepEqual(queryWords("1.2 M 充電線"), ["1.2m", "充電線"]);
  assert.deepEqual(queryWords("ip15 256 G 黑"), ["ip15", "256g", "黑"]);
  assert.deepEqual(queryWords("6.7 吋"), ["6.7吋"]);
  assert.deepEqual(queryWords("20 w 5 v"), ["20w", "5v"]);
  assert.deepEqual(queryWords("13 Pro"), ["13", "pro"]);            // pro 不是單位,不併
  assert.deepEqual(queryWords("w 20"), ["w", "20"]);                // 單位在前面不併
  assert.deepEqual(queryWords("ip15 w"), ["ip15", "w"]);            // 前面不是純數字不併
  assert.deepEqual(queryWords("SAM-NOTE5/黑"), ["sam", "note5", "黑"]);
  const charger = product(1, { name: "PD 充電器 20V 65W" });
  assert.equal(hasEveryWord(charger, "20 W"), false);
  assert.equal(hasEveryWord(charger, "65 W"), true);
  assert.equal(hasEveryWord(charger, "20 V"), true);
  assert.equal(hasEveryWord(charger, "20"), true);                  // 只打數字:有 20 就算
  assert.equal(hasEveryWord(product(2, { name: "PD 20 W 充電器" }), "20W"), true);       // 品名那一邊分開寫
  assert.equal(hasEveryWord(product(3, { name: "螢幕 6.1吋 7 色" }), "6.7 吋"), false);
});

test("英文要從一個字的開頭對起:S25 不算在 Plus 25W 裡;後面可以還有", () => {
  assert.equal(hasEveryWord(product(1, { name: "IP15 Plus 25W 充電器" }), "s25"), false);
  assert.equal(hasEveryWord(product(2, { name: "SAM/S25/殼" }), "s25"), true);
  assert.equal(hasEveryWord(product(3, { name: "SAM/S25U/殼" }), "s25"), true);
  assert.equal(hasEveryWord(product(4, { name: "犀牛盾/IP11PM/淺灰" }), "11pm"), true);  // 英文前面是數字可以
  assert.equal(hasEveryWord(product(5, { name: "IP15PROMAX/殼" }), "pro"), true);        // pro 對 promax
  assert.equal(hasEveryWord(product(6, { name: "滿版玻璃貼" }), "玻璃貼"), true);        // 中文沒有「字的開頭」這回事
  assert.equal(hasEveryWord(product(7, { name: "iPhone 15" }), "phone"), false);
});

test("候選的順序:強的 → 真的有那些字的 → 只是相關的 → 只是長得像的", () => {
  const resolved = [hit(1, "identifier"), hit(2, "exact"), hit(3, "covers"), hit(4, "related"), hit(5, "related")];
  const plain = [
    product(8, { name: "別的 東西" }),            // 只是長得像
    product(9, { name: "IMOS 11PM 玻璃貼" }),      // 真的有那些字
    product(5, { name: "11PM 玻璃貼 霧" }),        // 真的有那些字,共用比對說它只是相關
  ];
  const rows = mergeRows(resolved, plain, "11pm 玻璃貼");
  assert.deepEqual(rows.map((r) => r.product.id), [1, 2, 3, 9, 5, 4, 8]);
});

test("只是相關的再多,也不能把真正叫這個名字的擠到後面", () => {
  // 打「iphone 15 512」:同機型的保護貼二十個(相關),真正的手機只有片段搜尋找到
  const resolved = Array.from({ length: 20 }, (_, i) => hit(100 + i, "related"));
  const plain = [product(7, { name: "iPhone 15 512GB 黑色" }), product(8, { name: "iPhone 15 512GB 藍色" })];
  const rows = mergeRows(resolved, plain, "iphone 15 512");
  assert.deepEqual(rows.slice(0, 2).map((r) => r.product.id), [7, 8]);
  assert.equal(rows.length, 22);
});

test("只是長得像的再多,也不能把同機型的擠到後面", () => {
  // 打「iPhone 15 保護貼」:片段搜尋回來幾十支 iPhone(沒有「保護貼」三個字),店裡寫成 IP15 的保護貼是相關
  const plain = Array.from({ length: 50 }, (_, i) => product(200 + i, { name: `iPhone 15 ${i} 台版` }));
  const rows = mergeRows([hit(4, "related", { name: "滿/IP15/IP16/霧" })], plain, "iPhone 15 保護貼");
  assert.equal(rows[0].product.id, 4);
  assert.equal(rows.length, 51);
});

test("同一個商品只出現一次;兩邊都找到的,原因與差異照樣帶著", () => {
  const resolved = [hit(3, "related"), hit(1, "exact"), hit(1, "related")];
  const plain = [product(1), product(3, { name: "商品3 藍" }), product(9, { name: "商品9 藍" }), product(9)];
  const rows = mergeRows(resolved, plain, "藍");
  assert.deepEqual(rows.map((r) => r.product.id), [1, 3, 9]);
  assert.deepEqual(rows[0].reasons, ["exact的原因"]);
  // 3 號共用比對說只是相關、品名裡又真的有那個字:排在前面那一段,原因與差異用共用比對的
  assert.deepEqual(rows[1].reasons, ["related的原因"]);
  assert.deepEqual(rows[1].differences, ["有差異"]);
  // 9 號只有片段搜尋找到、字都有
  assert.deepEqual(rows[2].reasons, [WHY_WORDS]);
  assert.deepEqual(rows[2].differences, []);
});

test("只有片段搜尋找到的列要講它是哪一種:字都對得上 / 只是相似", () => {
  const rows = mergeRows([], [product(1, { name: "IMOS 11PM 玻璃貼" }), product(2, { name: "IMOS 12PM 玻璃貼" })], "11pm 玻璃貼");
  assert.deepEqual(rows.map((r) => [r.product.id, r.reasons, r.differences]), [
    [1, [WHY_WORDS], []],
    [2, [], [WHY_ALIKE]],
  ]);
  assert.equal(WHY_WORDS, "字都對得上");
  assert.equal(WHY_ALIKE, "只是相似");
});

test("打一長串數字時不寫「只是相似」:片段搜尋還會對每一台的序號,那一筆可能正是它", () => {
  for (const asked of ["356789012345678", "123456", "3567-8901 2345678"]) {
    const rows = mergeRows([], [product(1, { name: "iPhone 15 128GB 黑" })], asked);
    assert.deepEqual(rows[0].differences, [], asked);
    assert.deepEqual(rows[0].reasons, [], asked);
  }
  // 5 碼的數字不是序號那一類
  assert.deepEqual(mergeRows([], [product(1)], "12345")[0].differences, [WHY_ALIKE]);
});

test("兩邊都找到的:用共用比對回的那一份商品資料(庫存是照門市算好的)", () => {
  for (const asked of ["商品3", "別的字"]) {
    const rows = mergeRows([hit(3, "related", { stock_qty: 2 })], [product(3, { stock_qty: 40 })], asked);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].product.stock_qty, 2);
  }
});

test("零庫存、已停用的都留在候選裡", () => {
  const rows = mergeRows(
    [hit(1, "covers", { is_active: false }), hit(4, "related", { is_active: false, stock_qty: 0 })],
    [product(2, { stock_qty: 0 }), product(6, { name: "殼 黑", is_active: false })],
    "殼",
  );
  assert.deepEqual(rows.map((r) => r.product.id), [1, 6, 4, 2]);
});

test("候選的說明:庫存 0 也寫出來;沒有的欄位不留空的分隔", () => {
  const r = {
    product: product(5, { sku: "A001", category_name: "保護貼", spec: "亮面", stock_qty: 0 }),
    reasons: ["機型相符", "品牌相符"],
    differences: ["顏色不同"],
  };
  assert.equal(rowFacts(r), "A001 / 保護貼 / 亮面");
  assert.equal(rowWhy(r), "庫存 0 / 機型相符、品牌相符 / 顏色不同");
  assert.equal(rowFacts(row(6)), "P6");
  assert.equal(rowWhy(row(6, { stock_qty: null })), "庫存 0");
  assert.equal(rowWhy(row(6, { stock_qty: 12 })), "庫存 12");
});

test("打的是條碼就帶進條碼,不然帶進品名", () => {
  assert.equal(looksLikeBarcode("4710007834930"), true);
  assert.equal(looksLikeBarcode(" 12345678 "), true);
  assert.equal(looksLikeBarcode("1234567"), false);      // 不到 8 碼
  assert.equal(looksLikeBarcode("T4710007834930"), false); // 有英文字
  assert.equal(looksLikeBarcode("11PM"), false);
  assert.deepEqual(createPrefill(" 4710007834930 "), { name: "", barcode: "4710007834930" });
  assert.deepEqual(createPrefill(" IMOS 11PM 玻璃貼 "), { name: "IMOS 11PM 玻璃貼", barcode: "" });
});

test("照包裝上印的打(有空白、連字號)也是條碼:找的時候與帶進表單都用那一串數字", () => {
  assert.equal(barcodeIn("4712-3456-7890"), "471234567890");
  assert.equal(barcodeIn(" 4712 3456 7890 "), "471234567890");
  assert.equal(barcodeIn("12-256"), null);                 // 去掉符號不到 8 碼
  assert.equal(barcodeIn("IP15-256-黑"), null);
  assert.equal(barcodeIn("4712_3456_7890"), null);         // 只認空白與連字號
  assert.equal(searchText(" 4712-3456-7890 "), "471234567890");
  assert.equal(searchText(" IMOS 11PM 玻璃貼 "), "IMOS 11PM 玻璃貼");
  assert.equal(searchText("12-256"), "12-256");
  assert.deepEqual(createPrefill("4712-3456-7890"), { name: "", barcode: "471234567890" });
});

test("刷到的是手機的 IMEI:哪一格都不帶(那是一台的序號,不是商品的條碼)", () => {
  const imei = "356789012345672";                          // 15 碼、檢查碼正確
  assert.equal(barcodeIn(imei), imei);                     // 找的時候照樣拿整串去找
  assert.deepEqual(createPrefill(imei), { name: "", barcode: "" });
  assert.deepEqual(createPrefill("3567-8901-2345-672"), { name: "", barcode: "" });
  // 15 碼但檢查碼不對的不是 IMEI:照條碼帶
  assert.deepEqual(createPrefill("356789012345678"), { name: "", barcode: "356789012345678" });
});

test("記住叫法的結果:直接對到、只幫助搜尋、沒記住,三種說法不一樣", () => {
  const direct = "叫法已記住:以後直接對到這一款";
  const keyword = "叫法已記下:只幫助搜尋,不會直接對到";
  assert.equal(rememberNote("created", true), direct);
  assert.equal(rememberNote("kept", true), direct);
  assert.equal(rememberNote("repointed", true), direct);
  assert.equal(rememberNote("keyword", false), keyword);
  assert.equal(rememberNote("skipped", null), "叫法沒有記住");
  // 沒看過的結果不能說成「記住了」
  assert.equal(rememberNote("something_new", true), "叫法沒有記住");
});

test("「原本就記著」的那一筆如果只是搜尋用的字,不能說成以後直接對到", () => {
  const keyword = "叫法已記下:只幫助搜尋,不會直接對到";
  // 後端:那句話以前記成關鍵字,再記一次回 kept、verified 是 false
  assert.equal(rememberNote("kept", false), keyword);
  assert.equal(rememberTone("kept", false), "");
  // 回應裡沒有那一筆(看不出是不是已確認的)也不能說會直接對到
  assert.equal(rememberNote("kept", undefined), keyword);
  assert.equal(rememberNote("created", null), keyword);
  assert.equal(rememberTone("created", undefined), "");
  // keyword 就是 keyword,就算帶著 verified
  assert.equal(rememberNote("keyword", true), keyword);
  assert.equal(rememberTone("keyword", true), "");
});

test("記住叫法的結果用什麼顏色講:沒記住不能是成功的顏色", () => {
  assert.equal(rememberTone("created", true), "ok");
  assert.equal(rememberTone("kept", true), "ok");
  assert.equal(rememberTone("repointed", true), "ok");
  assert.equal(rememberTone("keyword", false), "");
  assert.equal(rememberTone("skipped", null), "err");
  assert.equal(rememberTone("something_new", true), "err");
});

test("從照片面板按「使用此商品」那一刻再核對:框關了、又找了別的、字改過,都不能用", () => {
  const done = settle(ask(IDLE, "11PM"), 1, [row(7)]);
  assert.equal(stillUsable(done, " 11PM ", { seq: 1, open: true }), true);
  assert.equal(stillUsable(done, "11PM", { seq: 1, open: false }), false);       // 框關掉了
  assert.equal(stillUsable(done, "12PM", { seq: 1, open: true }), false);        // 字改過
  const again = ask(done, "12PM");
  assert.equal(stillUsable(again, "12PM", { seq: 1, open: true }), false);       // 又找了別的(還在找)
  const done2 = settle(again, 2, [row(8)]);
  assert.equal(stillUsable(done2, "12PM", { seq: 1, open: true }), false);       // 又找了別的(找到了,但不是當初那一次)
  assert.equal(stillUsable(done2, "12PM", { seq: 2, open: true }), true);
  // 關掉再開:號碼換了,當初那一顆不算
  const reopened = reset(done);
  assert.equal(stillUsable(reopened, "", { seq: 1, open: true }), false);
  assert.equal(stillUsable(reopened, "", { seq: reopened.seq, open: true }), false);   // 還沒找過
});

test("庫存算哪一家:鎖倉的店員只算自己那一家,沒鎖的不限", () => {
  assert.equal(stockScope({ is_warehouse_locked: true, default_warehouse_id: 3 }), 3);
  assert.equal(stockScope({ is_warehouse_locked: true, default_warehouse_id: null }), 0); // 沒設門市:庫存一律 0
  assert.equal(stockScope({ is_warehouse_locked: false, default_warehouse_id: 3 }), undefined);
  assert.equal(stockScope(null), undefined);
  assert.equal(stockScope(undefined), undefined);
});

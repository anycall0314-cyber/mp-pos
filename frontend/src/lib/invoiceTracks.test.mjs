// 發票字軌:期別怎麼選、跳號視窗按確定之前講什麼、清單上的狀態;以及這幾頁有沒有照著接。跑法:npm test。
// owner 2026-10-13:要能設定字軌、故障之後指定從幾號開始印;字軌要指定年月,換期沒設定要自動提示。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  PERIOD_MONTHS,
  invoiceNo,
  jumpPreview,
  jumpSummary,
  monthsLabel,
  parseJumpInput,
  periodOf,
  periodParts,
  periodStart,
  trackStateLabel,
  trackUsable,
} from "./invoiceTracks.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const TRACK = { prefix: "AB", range_start: 100, range_end: 149, next_number: 110 };

test("期別:兩個月一期,用民國年與第一個月選,存的是那一期的第一天", () => {
  assert.deepEqual([...PERIOD_MONTHS], [1, 3, 5, 7, 9, 11]);
  assert.equal(periodStart(115, 11), "2026-11-01");
  assert.equal(periodStart(116, 1), "2027-01-01");
  // 年或月不對:不猜,回空字串(畫面就存不了)
  for (const [year, month] of [[115, 10], [115, 0], [115, 13], [0, 1], [115.5, 1], [NaN, 1], [115, NaN], [1000, 1]]) {
    assert.equal(periodStart(year, month), "", `${year}/${month}`);
  }
  assert.deepEqual(periodParts("2026-11-01"), { rocYear: 115, firstMonth: 11 });
  assert.deepEqual(periodParts("2027-01-01"), { rocYear: 116, firstMonth: 1 });
  // 沒登記期別的舊字軌、怪日期:讀不出來
  for (const odd of [null, undefined, "", "2026-10-01", "2026-11-02", "1911-01-01", "115年11-12月"]) {
    assert.equal(periodParts(odd), null, String(odd));
  }
  // 選了再讀回來是同一期
  for (const m of PERIOD_MONTHS) assert.deepEqual(periodParts(periodStart(115, m)), { rocYear: 115, firstMonth: m });
  assert.deepEqual(PERIOD_MONTHS.map(monthsLabel), ["1-2月", "3-4月", "5-6月", "7-8月", "9-10月", "11-12月"]);
});

test("新增字軌預設選今天那一期", () => {
  assert.deepEqual(periodOf(new Date(2026, 9, 13)), { rocYear: 115, firstMonth: 9 });   // 10 月 → 9-10 月
  assert.deepEqual(periodOf(new Date(2026, 10, 1)), { rocYear: 115, firstMonth: 11 });
  assert.deepEqual(periodOf(new Date(2026, 11, 31)), { rocYear: 115, firstMonth: 11 });
  assert.deepEqual(periodOf(new Date(2027, 0, 1)), { rocYear: 116, firstMonth: 1 });
  assert.deepEqual(periodOf(new Date(2027, 1, 28)), { rocYear: 116, firstMonth: 1 });
});

test("發票號碼:字軌 + 8 位數", () => {
  assert.equal(invoiceNo("AB", 100), "AB00000100");
  assert.equal(invoiceNo("QA", 12345678), "QA12345678");
});

test("跳號打的字:只打數字、或連字軌一起打都收", () => {
  assert.equal(parseJumpInput(TRACK, "115"), 115);
  assert.equal(parseJumpInput(TRACK, "00000115"), 115);
  assert.equal(parseJumpInput(TRACK, " ab 0000 0115 "), 115);
  assert.equal(parseJumpInput(TRACK, "AB00000115"), 115);
  // 別條字軌的號碼、不是數字、太長、空的:讀不出來
  for (const odd of ["CD00000115", "11a", "123456789", "", "  ", "-5", "1.5", "AB"]) {
    assert.equal(parseJumpInput(TRACK, odd), null, odd);
  }
});

test("跳號:按確定之前先講會發生什麼事", () => {
  assert.deepEqual(jumpPreview(TRACK, ""), { ok: false, kind: "none", text: "" });
  assert.deepEqual(jumpPreview(TRACK, "   "), { ok: false, kind: "none", text: "" });
  assert.deepEqual(jumpPreview(TRACK, "abc"), { ok: false, kind: "none", text: "請輸入號碼" });
  // 往後:寫出跳過哪幾號、共幾張
  assert.deepEqual(jumpPreview(TRACK, "113"), { ok: true, kind: "forward", text: "跳過 3 張:AB00000110 ~ AB00000112" });
  assert.deepEqual(jumpPreview(TRACK, "111"), { ok: true, kind: "forward", text: "跳過 1 張:AB00000110" });
  assert.deepEqual(jumpPreview(TRACK, "AB00000149"), { ok: true, kind: "forward", text: "跳過 39 張:AB00000110 ~ AB00000148" });
  // 跳到迄號的下一號 = 這一捲剩下的都不用了
  assert.deepEqual(jumpPreview(TRACK, "150"), { ok: true, kind: "forward", text: "跳過 40 張:AB00000110 ~ AB00000149;這條字軌用完" });
  // 往回:系統倒回去、紙不會 —— 要人先對紙
  assert.deepEqual(jumpPreview(TRACK, "107"), { ok: true, kind: "back", text: "往回 3 張,下一張開 AB00000107;先確認紙上是這一號" });
  assert.deepEqual(jumpPreview(TRACK, "100"), { ok: true, kind: "back", text: "往回 10 張,下一張開 AB00000100;先確認紙上是這一號" });
  // 一樣、超出這一捲:不能送
  assert.deepEqual(jumpPreview(TRACK, "110"), { ok: false, kind: "none", text: "跟系統一樣,不用跳" });
  for (const out of ["99", "151", "0", "99999999"]) {
    assert.deepEqual(jumpPreview(TRACK, out), { ok: false, kind: "none", text: "要在 AB00000100 ~ AB00000149 之間" }, out);
  }
  // 已經用完的字軌(下一張 = 迄號 + 1):只能往回
  const done = { ...TRACK, next_number: 150 };
  assert.equal(jumpPreview(done, "150").ok, false);
  assert.equal(jumpPreview(done, "149").kind, "back");
});

test("跳號紀錄的一列:往後幾張、往回幾張", () => {
  assert.equal(jumpSummary({ from_number: 101, to_number: 105 }), "跳過 4 張");
  assert.equal(jumpSummary({ from_number: 110, to_number: 103 }), "往回 7 張");
});

test("清單的狀態:先看停用、再看過期、再看用完、再看還沒到;每一種字數一樣", () => {
  const t = (over) => ({ is_active: true, is_depleted: false, period_state: "now", ...over });
  assert.equal(trackStateLabel(t({})), "使用中");
  assert.equal(trackStateLabel(t({ period_state: "" })), "使用中");            // 沒登記期別的舊字軌
  assert.equal(trackStateLabel(t({ is_active: false, period_state: "past", is_depleted: true })), "已停用");
  assert.equal(trackStateLabel(t({ period_state: "past", is_depleted: true })), "已過期");
  assert.equal(trackStateLabel(t({ period_state: "past" })), "已過期");        // 還有號碼,但換期了不能再開
  assert.equal(trackStateLabel(t({ is_depleted: true })), "已用完");
  assert.equal(trackStateLabel(t({ period_state: "future", is_depleted: true })), "已用完");
  assert.equal(trackStateLabel(t({ period_state: "future" })), "未開始");
  const all = [{}, { is_active: false }, { period_state: "past" }, { is_depleted: true }, { period_state: "future" }];
  assert.deepEqual([...new Set(all.map((o) => trackStateLabel(t(o)).length))], [3]);
  assert.deepEqual(all.map((o) => trackUsable(t(o))), [true, false, false, false, false]);
});

test("系統設定:字軌要選門市與期別;下一張不能直接改、要用跳號", () => {
  const page = read("../pages/settings/SettingsPage.tsx");
  const tracks = page.slice(page.indexOf("發票字軌</h3>"), page.indexOf("付款方式</h3>"));
  // 期別用年 + 月份選,送出去的是那一期的第一天
  assert.match(page, /const pickedPeriod = periodStart\(Number\(periodYear\), Number\(periodMonth\)\)/);
  assert.match(page, /if \(pickedPeriod\) body\.period_start = pickedPeriod;/);
  assert.match(tracks, /PERIOD_MONTHS\.map\(\(m\) => \(\s*<option key=\{m\} value=\{m\}>\s*\{monthsLabel\(m\)\}/);
  // 新增:沒選門市、沒選期別存不了
  assert.match(tracks, /disabled=\{\s*saveTrack\.isPending \|\|\s*!editing\.prefix \|\|\s*periodMissing \|\|\s*\(!editing\.id && \(editing\.warehouse \?\? null\) === null\)\s*\}/);
  // 「下一張」那一格只有新增時有;存檔也只有新增時送
  assert.match(tracks, /\{!editing\.id && \(\s*<label>\s*下一張/);
  assert.match(page, /if \(!editing\.id && editing\.next_number !== undefined\) body\.next_number = editing\.next_number;/);
  assert.doesNotMatch(page, /saveTrack\.mutateAsync\(editing/);         // 不再把整筆(含下一張)送回去
  // 清單:跳號開同一個視窗;沒有「發票字軌」那一項的帳號按鈕都收起來
  assert.match(tracks, /\{canTracks && \(\s*<>\s*<button onClick=\{\(\) => setJumping\(t\)\}>跳號<\/button>/);
  assert.match(page, /\{jumping && <InvoiceJumpDialog track=\{jumping\} onClose=\{\(\) => setJumping\(null\)\} \/>\}/);
  assert.match(page, /const canTracks = can\(useAuth\(\)\.user, "invoice_tracks"\);/);
  assert.match(tracks, /\{canTracks && \(\s*<div style=\{\{ marginBottom: 8 \}\}>\s*<button className="btn primary" onClick=\{startNew\}>/);
  // 狀態照規則寫(過期的不會寫成使用中)
  assert.match(tracks, /\{trackStateLabel\(t\)\}/);
  // 同一排的動作字數一樣
  const actions = [...tracks.matchAll(/>\s*(跳號|編輯|刪除|刪)\s*<\/button>|<ArmButton\s+label="(刪除)"/g)].map((m) => m[1] ?? m[2]);
  assert.deepEqual(actions, ["跳號", "編輯", "刪除"]);      // 刪除按兩下(全站檢視 G1)
});

test("跳號視窗:打的是紙上的下一張,預覽照規則,送出去的是讀出來的號碼", () => {
  const dialog = read("../components/invoice/InvoiceJumpDialog.tsx");
  assert.match(dialog, /const preview = jumpPreview\(track, text\);/);
  assert.match(dialog, /const n = parseJumpInput\(track, text\);\s*if \(!preview\.ok \|\| n === null \|\| jump\.isPending\) return;/);
  assert.match(dialog, /jump\.mutateAsync\(\{ id: track\.id, next_number: n, reason: reason\.trim\(\) \}\)/);
  assert.match(dialog, /disabled=\{!preview\.ok \|\| jump\.isPending\}/);
  // 三格的名稱字數一樣;往回與不能送的用紅字
  const labels = [...dialog.matchAll(/<span>(系統下一張|紙上下一張|為什麼跳號)<\/span>/g)].map((m) => m[1]);
  assert.deepEqual(labels, ["系統下一張", "紙上下一張", "為什麼跳號"]);
  assert.match(dialog, /className=\{`invoice-jump-note\$\{preview\.kind === "forward" \? "" : " err"\}`\}/);
  // 伺服器擋下來的原因要看得到(那一號之後開過發票)
  assert.match(dialog, /catch \(e\) \{\s*setError\(apiErrorText\(e\)\);/);
  const hooks = read("../api/hooks.ts");
  assert.match(hooks, /api<InvoiceTrack>\(`\/invoice-tracks\/\$\{p\.id\}\/jump\/`, \{\s*method: "POST",\s*body: JSON\.stringify\(\{ next_number: p\.next_number, reason: p\.reason \}\)/);
});

test("開單頁:預覽帶門市去問;換期沒設定講是哪一期;發票號碼旁邊可以跳號", () => {
  const page = read("../pages/sales/SalesWorkbenchPage.tsx");
  assert.match(page, /`\/invoice-tracks\/peek\/\?invoice_type_code=\$\{encodeURIComponent\(invoiceForm\)\}&warehouse=\$\{warehouse\}`/);
  assert.match(page, /\}, \[invoiceForm, noInvoice, peekTick, warehouse\]\);/);        // 換門市要重問
  assert.match(page, /: \{ state: "none", no: null, why: res\.detail \?\? "" \}/);
  // 取不到號的兩條提醒(單據資訊、結帳抽屜)都講伺服器給的原因
  assert.equal(page.match(/\{peek\.why \|\| "這種發票沒有可用的字軌"\},結帳會被擋。/g).length, 2);
  // 快換期了先提醒(不擋)
  assert.match(page, /\{!noInvoice && peek\.state === "ok" && peek\.upcoming && \(\s*<div className="wb-warn">下一期 \{peek\.upcoming\} 的字軌還沒設定<\/div>/);
  // **主動提醒**(owner:「單數月一號遇到發票尚未更新字軌，主動提醒需更換，並且不得打印發票」):
  // 一進開單頁就在最上面(工具列上面、不在抽屜裡),講是哪一期、不能開發票、去哪裡新增;快換期的那一條也在最上面
  const top = page.slice(0, page.indexOf('<div className="ws-tools">'));
  assert.match(top, /\{trackMissing && \(\s*<div className="wb-warn err ws-track-alert" role="alert">\s*\{peek\.why \|\| "這種發票沒有可用的字軌"\},不能開發票。/);
  assert.match(top, /<a className="wb-link" href="\/settings" target="_blank" rel="noreferrer">\s*新增字軌\s*<\/a>/);
  assert.match(top, /\{!trackMissing && !noInvoice && peek\.state === "ok" && peek\.upcoming && \(\s*<div className="wb-warn ws-track-alert">下一期 \{peek\.upcoming\} 的字軌還沒設定<\/div>/);
  assert.ok(top.indexOf("ws-track-alert") > top.indexOf("</header>"));       // 在頁首下面、不是藏在選單裡
  // 跳號:要有那一項權限;跳完重新問下一張
  assert.match(page, /const canJump = useCan\("invoice_tracks"\);/);
  assert.match(page, /peek\.state === "ok" && peek\.track && canJump && !locked && \(/);
  assert.match(page, /<InvoiceJumpDialog\s+track=\{peek\.track\}\s+onClose=\{\(\) => setJumpOpen\(false\)\}\s+onDone=\{\(\) => setPeekTick\(\(n\) => n \+ 1\)\}/);
});

test("權限清單有「發票字軌」這一項", () => {
  assert.match(read("./abilities.ts"), /\| "invoice_tracks"/);
});

test("開單選了這種發票帶什麼課稅別:照業務設定,空的 / 找不到 = 不動(全站檢視 A1)", async () => {
  const { taxMethodFor } = await import("./invoiceTracks.ts");
  const types = [{ code: "none", tax_method: "taxable_included" }, { code: "e_invoice", tax_method: "" }];
  assert.equal(taxMethodFor(types, "none"), "taxable_included");
  assert.equal(taxMethodFor(types, "e_invoice"), null);
  assert.equal(taxMethodFor(types, "hand_tri"), null);
  assert.equal(taxMethodFor([{ code: "none" }], "none"), null);
});

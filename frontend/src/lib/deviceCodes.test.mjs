// 刷條碼分格的規則(routeCodes)。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
// 這段決定「刷到的碼算哪一台」;錯了會把一支手機拆成兩筆庫存,而且存得進去。
import assert from "node:assert/strict";
import test from "node:test";

import {
  codesLabel,
  looksLikeImei,
  mainCode,
  normalizeCode,
  routeCodes,
  splitCode,
} from "./deviceCodes.ts";

const A1 = "490154203237518"; // 手機 A 的 IMEI
const A2 = "356938035643809"; // 手機 A 的 IMEI2(也是檢查碼正確的 15 碼)
const B1 = "352099001761481";
const SN_A = "F2LXK1ABCD";
const SN_B = "G6TZN0QWER";
const blank = () => ({ imei: "", sn: "" });
const rows = (n) => Array.from({ length: n }, blank);
const codes = (entries) => entries.map((e) => [e.imei, e.sn]);

/** 模擬條碼槍:每一刷都打在「上一刷之後游標停的那一格」,回傳最後的樣子。 */
function scan(qty, pair, list, start = { idx: 0, field: "imei" }) {
  let entries = rows(qty);
  let focus = start;
  const log = [];
  for (const code of list) {
    if (!focus) {
      log.push({ code, lost: true }); // 游標已經離開輸入格:這一刷不會進任何一格
      continue;
    }
    const before = entries[focus.idx][focus.field];
    entries[focus.idx] = { ...entries[focus.idx], [focus.field]: before + code };
    const r = routeCodes(entries, qty, focus.idx, { field: focus.field, before }, [code], blank, pair);
    entries = r.entries;
    log.push({ code, dropped: r.dropped, refused: r.refused });
    focus = r.focus;
  }
  return { entries, focus, log };
}

test("跟後端同一套:怎樣算 IMEI、怎麼正規化", () => {
  for (const c of [A1, A2, B1, "49 015420 323751 8", "490154-203237-518"]) assert.ok(looksLikeImei(c), c);
  for (const c of ["490154203237519", "49015420323751", SN_A, "", null]) assert.ok(!looksLikeImei(c), String(c));
  assert.equal(normalizeCode(" f2l-xk1.ab_cd "), "F2LXK1ABCD");
  assert.deepEqual(splitCode(A1), { imei: A1, sn: "" });
  assert.deepEqual(splitCode(SN_A), { imei: "", sn: SN_A });
  assert.equal(mainCode({ imei: A1, sn: SN_A }), A1);
  assert.equal(mainCode({ imei: "", sn: SN_A }), SN_A);
  assert.equal(codesLabel({ imei: A1, sn: SN_A }), `IMEI ${A1} / SN ${SN_A}`);
  assert.equal(codesLabel({ imei: "", sn: "", serial_no: "X" }), "X");
});

test("每台刷一個碼:只刷 IMEI,一台一台往下排", () => {
  const r = scan(3, false, [A1, A2, B1]);
  assert.deepEqual(codes(r.entries), [[A1, ""], [A2, ""], [B1, ""]]);
  assert.equal(r.focus, null); // 刷滿了,游標離開
});

test("每台刷一個碼:只刷 SN(游標在 IMEI 格也會搬到 SN 格)", () => {
  const r = scan(2, false, [SN_A, SN_B]);
  assert.deepEqual(codes(r.entries), [["", SN_A], ["", SN_B]]);
});

test("每台刷一個碼:刷超過數量的不放,並回報", () => {
  const r = scan(1, false, [A1]);
  assert.equal(r.focus, null);
  const more = routeCodes(r.entries, 1, 0, null, [A2], blank, false);
  assert.equal(more.dropped, 1);
  assert.deepEqual(codes(more.entries), [[A1, ""]]);
});

test("每台刷兩個碼:IMEI、SN 一對一對排", () => {
  const r = scan(2, true, [A1, SN_A, B1, SN_B]);
  assert.deepEqual(codes(r.entries), [[A1, SN_A], [B1, SN_B]]);
  assert.equal(r.focus, null);
  // 先刷 SN 再刷 IMEI 也是同一台
  assert.deepEqual(codes(scan(2, true, [SN_A, A1, SN_B, B1]).entries), [[A1, SN_A], [B1, SN_B]]);
});

test("每台刷兩個碼:盒上的 IMEI2 不會變成下一台", () => {
  // 手機 A 連刷 IMEI、IMEI2、SN,再刷手機 B 的 IMEI、SN
  const r = scan(2, true, [A1, A2, SN_A, B1, SN_B]);
  assert.deepEqual(codes(r.entries), [[A1, SN_A], [B1, SN_B]]);
  const second = r.log[1];
  assert.deepEqual(second.refused, { code: A2, missing: "sn" }); // 沒放,而且講得出是哪個碼、還缺哪一格
  assert.ok(r.log.every((x) => !x.lost)); // 沒有任何一刷掉在輸入格外面
});

test("每台刷兩個碼:IMEI2 被擋下時,游標留在這一台的 SN 格", () => {
  let entries = rows(2);
  entries[0] = { imei: A1, sn: A2 }; // IMEI2 刷在第 1 台的 SN 格
  const r = routeCodes(entries, 2, 0, { field: "sn", before: "" }, [A2], blank, true);
  assert.deepEqual(codes(r.entries), [[A1, ""], ["", ""]]);
  assert.deepEqual(r.focus, { idx: 0, field: "sn" });
  assert.deepEqual(r.refused, { code: A2, missing: "sn" });
});

test("每台刷兩個碼:這一台沒有 SN 時,把游標移到下一台再刷就是下一台", () => {
  let entries = rows(2);
  entries[0] = { imei: A1, sn: "" };
  entries[1] = { imei: B1, sn: "" }; // 游標已經在第 2 台的 IMEI 格,刷 B 的 IMEI
  const r = routeCodes(entries, 2, 1, { field: "imei", before: "" }, [B1], blank, true);
  assert.deepEqual(codes(r.entries), [[A1, ""], [B1, ""]]);
  assert.deepEqual(r.focus, { idx: 1, field: "sn" });
});

test("刷錯格不會把原本的碼蓋掉", () => {
  // 游標在第 1 台的 IMEI 格(已經有 IMEI,整格被選取),刷到的是 SN:IMEI 要還原,SN 放到 SN 格
  let entries = rows(2);
  entries[0] = { imei: SN_A, sn: "" }; // 選取狀態下被新刷的字取代後的樣子
  const r = routeCodes(entries, 2, 0, { field: "imei", before: A1 }, [SN_A], blank, true);
  assert.deepEqual(codes(r.entries), [[A1, SN_A], ["", ""]]);
});

test("打在對的那一格就是改那一格(重刷)", () => {
  let entries = rows(2);
  entries[0] = { imei: B1, sn: SN_A };
  const r = routeCodes(entries, 2, 0, { field: "imei", before: A1 }, [B1], blank, true);
  assert.deepEqual(codes(r.entries), [[B1, SN_A], ["", ""]]);
});

test("IMEI 格裡打錯的 15 碼(檢查碼不對)留在 IMEI 格,不搬去 SN", () => {
  let entries = rows(1);
  entries[0] = { imei: "490154203237519", sn: "" };
  const r = routeCodes(entries, 1, 0, { field: "imei", before: "" }, ["490154203237519"], blank, false);
  assert.deepEqual(codes(r.entries), [["490154203237519", ""]]);
});

test("一次貼上一串", () => {
  assert.deepEqual(
    codes(routeCodes(rows(3), 3, 0, null, [A1, A2, B1], blank, false).entries),
    [[A1, ""], [A2, ""], [B1, ""]]);
  assert.deepEqual(
    codes(routeCodes(rows(2), 2, 0, null, [A1, SN_A, B1, SN_B], blank, true).entries),
    [[A1, SN_A], [B1, SN_B]]);
  // 每台刷兩個碼時貼進 IMEI、IMEI2:第二個不放
  const r = routeCodes(rows(2), 2, 0, null, [A1, A2], blank, true);
  assert.deepEqual(codes(r.entries), [[A1, ""], ["", ""]]);
  assert.deepEqual(r.refused, { code: A2, missing: "sn" });
});

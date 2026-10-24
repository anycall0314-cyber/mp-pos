// 銷退 / 個人收購最下面固定一條(全站檢視 V05)。跑法:npm test。
// 以前:銷退的「整張退」在最上面、按一下就退,退款額在明細最下面(明細一長整頁捲不下去、看不到);
// 個人收購的「儲存收購」在表單最後面、要捲到底。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("銷退:中間捲、最下面一條放退回哪裡 / 退款方式 / 作廢原發票 / 金額;整張退按兩下(第一下寫退多少)", () => {
  const src = read("../pages/sales/SalesReturnEntryPage.tsx");
  assert.match(src, /<div className="entry-body sr-body">/);
  assert.match(src, /<div className="entry-footer sr-footer">/);
  // 整張退不在上面那一排、不是一般按鈕
  const toolbar = src.slice(src.indexOf("<Toolbar"), src.indexOf("/>", src.indexOf("actions={")) + 2);
  assert.ok(!toolbar.includes("整張退"));
  assert.match(src, /key=\{`\$\{originalSOId\}-\$\{paymentMethod\}-\$\{voidInvoice\}`\}\s+label="整張退"\s+armedLabel=\{`確認退款 \$\$\{money\(rd\.total\)\}`\}/);
  assert.ok(!/onClick=\{handleSubmit\}/.test(src));
  // 退款額只有一處、退款方式只有一個下拉
  assert.equal(src.match(/退款額<b>/g)?.length, 1);
  assert.equal(src.match(/value=\{paymentMethod\} onChange/g)?.length, 1);
  assert.ok(!src.includes('<label style={labelStyle}>退款方式'));
});

test("個人收購:最下面一條放收購金額 / 付款方式 / 儲存收購(按一下),缺金額、付款方式、IMEI 與 SN 不能按;表單裡不再有這兩格與舊的儲存鈕", () => {
  const src = read("../pages/secondhand-acquisition/SecondhandPersonalEntry.tsx");
  assert.match(src, /<div className="entry-footer sh-footer">/);
  assert.match(src, /const readyToSave = amountOk && !!paymentMethod && !!\(imei\.trim\(\) \|\| sn\.trim\(\)\);/);
  assert.match(src, /disabled=\{acquire\.isPending \|\| !readyToSave\}/);
  assert.equal(src.match(/儲存收購/g)?.length, 2); // 註解一次 + 按鈕一次
  assert.ok(!src.includes('label="收購金額(付給會員)"'));
  assert.ok(!src.includes('<Field label="付款方式" required>'));
  assert.match(src, /收購價高於預計售價/); // 只提醒、照樣可以存
  // 預計售價(打算賣多少)不顯示在朝客人的那一條,只拿來比較
  const footer = src.slice(src.indexOf('<div className="entry-footer sh-footer">'));
  assert.ok(!footer.includes("{customPrice}") && !footer.includes("money(expectedSale"));
});

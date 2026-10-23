// 錯誤訊息一律中文一句(全站檢視 G2)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { BUSY_TEXT, errorText, httpErrorText, OFFLINE_TEXT } from "./errorText.ts";

class FakeHttp extends Error {
  constructor(status, body) {
    super("x");
    this.status = status;
    this.body = body;
  }
}

test("伺服器講了原因就用那一句;欄位錯誤不留英文欄位名", () => {
  assert.equal(httpErrorText(400, { detail: "這張單已經作廢" }), "這張單已經作廢");
  assert.equal(httpErrorText(400, { phone: ["這個電話已經有人用了"], name: ["必填"] }), "這個電話已經有人用了;名稱:必填");   // 句子裡已經有「電話」就不加
  assert.equal(httpErrorText(400, { items: [{ qty: ["數量要大於 0"] }] }), "數量要大於 0");      // 已經寫了是哪一格就不重複
  assert.equal(httpErrorText(400, { some_field: ["這個欄位是必須的。"] }), "這個欄位是必須的。"); // 不認得的欄位不寫英文
  assert.equal(httpErrorText(400, { non_field_errors: ["期間不能顛倒"] }), "期間不能顛倒");
  assert.equal(httpErrorText(400, { code: ["已經有人用了"] }), "代碼:已經有人用了");     // 欄位叫 code 的錯誤照樣給人看
});

test("伺服器出錯、連不上:固定兩句", () => {
  assert.equal(httpErrorText(500, "<html>Server Error</html>"), BUSY_TEXT);
  assert.equal(httpErrorText(502, null), BUSY_TEXT);
  assert.equal(errorText(new TypeError("Failed to fetch")), OFFLINE_TEXT);
  assert.equal(errorText(new TypeError("Load failed")), OFFLINE_TEXT);
  assert.equal(errorText(new TypeError("NetworkError when attempting to fetch resource.")), OFFLINE_TEXT);
});

test("沒講原因的:照狀況一句中文,不寫 Bad Request", () => {
  assert.equal(httpErrorText(400, null), "沒有成功,請再試一次");
  assert.equal(httpErrorText(403, {}), "沒有權限");
  assert.equal(httpErrorText(404, null), "找不到這一筆");
  assert.equal(errorText(new FakeHttp(400, { qty: ["重複"] })), "數量:重複");
  assert.equal(httpErrorText(409, { code: "trade_hold" }), "沒有成功,請再試一次");   // 程式認的代碼不給人看
});

test("自己丟的錯誤照原樣", () => {
  assert.equal(errorText(new Error("先打數量")), "先打數量");
  assert.equal(errorText("timeout"), "timeout");
});

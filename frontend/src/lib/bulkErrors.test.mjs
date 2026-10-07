// 批次修改被退回時要講「哪一個商品、為什麼」。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
// 只講「部分商品失敗」的話,人不知道是哪幾個、也不知道要怎麼辦(用過的商品不能改屬性那一句有寫出路)。
import assert from "node:assert/strict";
import test from "node:test";

import { bulkFailureLines, reasonText } from "./bulkErrors.ts";

const LOCKED =
  "「需追蹤序號」不能改:這個商品已經用過(1 張進貨單、庫存 5 件)。先把這些單作廢、庫存歸零再改,或停用這個品號另外建一個。";

test("一個商品的原因:一句話、detail、欄位驗證都講得出來", () => {
  assert.equal(reasonText("條碼重複"), "條碼重複");
  assert.equal(reasonText({ detail: LOCKED }), LOCKED);
  assert.equal(reasonText({ detail: [LOCKED] }), LOCKED);
  // 欄位名稱不拿給人看,只講原因
  assert.equal(reasonText({ list_price: ["請輸入數字"] }), "請輸入數字");
  assert.equal(
    reasonText({ list_price: ["請輸入數字"], brand: ["找不到這個品牌"] }),
    "請輸入數字;找不到這個品牌",
  );
});

test("同一句不講兩次;看不懂的回空字串", () => {
  assert.equal(reasonText({ a: ["不能是空的"], b: ["不能是空的"] }), "不能是空的");
  assert.equal(reasonText(null), "");
  assert.equal(reasonText(undefined), "");
  assert.equal(reasonText(404), "");
  assert.equal(reasonText({}), "");
  assert.equal(reasonText("   "), "");
  // 空的那一格不佔位(不會多出一個分號)
  assert.equal(reasonText({ a: [], b: ["不能是空的"] }), "不能是空的");
  assert.equal(reasonText(["", "條碼重複", null]), "條碼重複");
});

test("一個商品一行:品名與原因", () => {
  const body = {
    detail: "部分商品失敗,已全部復原",
    errors: [
      { id: 1, name: "透明殼", errors: { detail: LOCKED } },
      { id: 2, name: " 充電線 ", errors: "條碼重複" },
    ],
  };
  assert.deepEqual(bulkFailureLines(body), [`透明殼:${LOCKED}`, "充電線:條碼重複"]);
});

test("只有品名或只有原因的也留著;兩個都沒有的不佔一行", () => {
  const body = {
    errors: [
      { id: 1, name: "透明殼", errors: {} },
      { id: 2, name: "", errors: "條碼重複" },
      { id: 3 },
      null,
      "亂七八糟",
    ],
  };
  assert.deepEqual(bulkFailureLines(body), ["透明殼", "條碼重複"]);
});

test("太多個只列前幾個,最後一行講還有幾個", () => {
  const errors = Array.from({ length: 8 }, (_, i) => ({ id: i, name: `商品 ${i}`, errors: "不行" }));
  const lines = bulkFailureLines({ errors });
  assert.equal(lines.length, 6);
  assert.equal(lines[4], "商品 4:不行");
  assert.equal(lines[5], "另外 3 個");
  // 剛好到上限:全部列出來,沒有「另外」那一行
  assert.deepEqual(bulkFailureLines({ errors: errors.slice(0, 5) }).length, 5);
  assert.equal(bulkFailureLines({ errors }, 2)[2], "另外 6 個");
});

test("不是這種回應(沒有 errors、斷線):沒有可講的", () => {
  assert.deepEqual(bulkFailureLines(null), []);
  assert.deepEqual(bulkFailureLines("Internal Server Error"), []);
  assert.deepEqual(bulkFailureLines({ detail: "ids 為空" }), []);
  assert.deepEqual(bulkFailureLines({ errors: "壞掉" }), []);
  assert.deepEqual(bulkFailureLines({ errors: { a: 1 } }), []);
  assert.deepEqual(bulkFailureLines({ errors: 7 }), []);
});

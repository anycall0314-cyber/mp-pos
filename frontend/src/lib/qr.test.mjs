// QR Code 畫得出來、四周有留白。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { qrMatrix, qrPath } from "./qr.ts";

test("畫得出方陣,四周留白,左上角是定位圖形", () => {
  const m = qrMatrix("https://pos.example.com/m/photo#abcDEF123_-abcDEF123_-abcDEF123_-abcDEF12");
  assert.equal(m.length, m[0].length);
  // 四周 4 格都是白的
  for (let i = 0; i < m.length; i++) {
    for (let q = 0; q < 4; q++) {
      assert.equal(m[q][i], false);
      assert.equal(m[i][q], false);
      assert.equal(m[m.length - 1 - q][i], false);
      assert.equal(m[i][m.length - 1 - q], false);
    }
  }
  // 定位圖形:左上角 7×7 的外框是黑的
  for (let i = 0; i < 7; i++) {
    assert.equal(m[4][4 + i], true);
    assert.equal(m[4 + i][4], true);
  }
  assert.ok(qrPath(m).startsWith("M"));
});

test("內容不一樣,畫出來就不一樣", () => {
  assert.notEqual(qrPath(qrMatrix("a")), qrPath(qrMatrix("b")));
});

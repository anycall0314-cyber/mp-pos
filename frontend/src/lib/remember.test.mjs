// 記在這台電腦的小設定(全站檢視 E8:代收話費記住上次選的電信業者)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { pickRemembered } from "./remember.ts";

test("記著的還在清單上才帶;看不懂或已經沒有的當沒記", () => {
  assert.equal(pickRemembered("3", [1, 3]), 3);
  assert.equal(pickRemembered("4", [1, 3]), null);
  assert.equal(pickRemembered(null, [1, 3]), null);
  assert.equal(pickRemembered("abc", [1, 3]), null);
  assert.equal(pickRemembered("0", [0, 1]), null);
});

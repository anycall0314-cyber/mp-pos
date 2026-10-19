// 自己改密碼那一頁的檢查。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { changeProblem, passwordProblem } from "./password.ts";

test("目前的、新的、再一次都對才能送", () => {
  assert.equal(changeProblem("", "abcd", "abcd"), "請輸入目前的密碼");
  assert.equal(changeProblem("old1", "abc", "abc"), "新密碼至少 4 碼");
  assert.equal(changeProblem("old1", "old1", "old1"), "新密碼跟目前的一樣");
  assert.equal(changeProblem("old1", "abcd", "abce"), "兩次輸入的新密碼不一樣");
  assert.equal(changeProblem("old1", "abcd", "abcd"), "");
  assert.equal(changeProblem("old1", " abcd", " abcd"), "密碼前後不能有空白");
});

test("前後有空白的不收(登入會去掉空白,存了就登不進去)", () => {
  assert.equal(passwordProblem("abcd "), "密碼前後不能有空白");
  assert.equal(passwordProblem("ab cd"), "");
  assert.equal(passwordProblem("abc"), "新密碼至少 4 碼");
});

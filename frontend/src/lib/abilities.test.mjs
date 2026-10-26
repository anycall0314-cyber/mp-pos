// 員工帳號的權限在畫面這一側:按鈕要不要出現、員工帳號頁怎麼排。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { can, groupAbilities } from "./abilities.ts";

test("只有明講不可以才收起來;沒有資料當成可以(伺服器會擋)", () => {
  assert.equal(can({ abilities: { void_sales: false, sales_return: true } }, "void_sales"), false);
  assert.equal(can({ abilities: { void_sales: false, sales_return: true } }, "sales_return"), true);
  assert.equal(can({ abilities: { void_sales: false } }, "void_purchase"), true); // 這一項伺服器沒講
  assert.equal(can({ abilities: {} }, "void_sales"), true);
  assert.equal(can({}, "void_sales"), true); // 伺服器比較舊,沒有這一格
  assert.equal(can(null, "void_sales"), true); // 還沒載入
  assert.equal(can(undefined, "void_others"), true);
});

test("員工帳號頁照分類排,順序照伺服器給的", () => {
  const list = [
    { key: "a", label: "甲", group: "作廢與銷退", note: "" },
    { key: "b", label: "乙", group: "作廢與銷退", note: "含丙" },
    { key: "c", label: "丙", group: "報表", note: "" },
    { key: "d", label: "丁", group: "作廢與銷退", note: "" },
  ];
  assert.deepEqual(
    groupAbilities(list).map((g) => [g.group, g.items.map((i) => i.key)]),
    [
      ["作廢與銷退", ["a", "b", "d"]],
      ["報表", ["c"]],
    ],
  );
  assert.deepEqual(groupAbilities([]), []);
});

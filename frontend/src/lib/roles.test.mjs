// 誰算管理員(電信方案只有管理員能改)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { MANAGER_ROLES, isManager } from "./roles.ts";

test("公司管理員與平台管理員是管理員", () => {
  assert.equal(isManager("tenant_admin"), true);
  assert.equal(isManager("platform_admin"), true);
  assert.deepEqual([...MANAGER_ROLES].sort(), ["platform_admin", "tenant_admin"]);
});

test("店員、還不知道是誰、亂七八糟的值都不是", () => {
  for (const role of ["tenant_user", "", "admin", "TENANT_ADMIN", " tenant_admin", null, undefined]) {
    assert.equal(isManager(role), false, String(role));
  }
});

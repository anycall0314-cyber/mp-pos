// 同一個帳號同一時間只能在一個位置登入(owner 2026-10-24)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { attachSignInCheck, CHECK_MS, DEVICE_KEY, elsewhereNotice, readDeviceId } from "./signInPlace.ts";

function memory(initial = {}) {
  const data = { ...initial };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => (data[k] = v) };
}

const ID = "0f8e2c1a-5b6d-4e7f-9a0b-1c2d3e4f5a6b";

test("同一個瀏覽器一直是同一個記號;沒有或不像才產生並記住", () => {
  const kept = memory({ [DEVICE_KEY]: ID });
  assert.equal(readDeviceId(kept, () => "should-not-be-used-123"), ID);

  const empty = memory();
  assert.equal(readDeviceId(empty, () => ID), ID);
  assert.equal(empty.data[DEVICE_KEY], ID);
  assert.equal(readDeviceId(empty, () => "another-one-0000-1111"), ID); // 第二個分頁拿到同一個

  const odd = memory({ [DEVICE_KEY]: "abc" });
  assert.equal(readDeviceId(odd, () => ID), ID);
  assert.equal(odd.data[DEVICE_KEY], ID);
});

test("瀏覽器不給存、產生不出像樣的記號:回空字串(伺服器當成每次都是新位置)", () => {
  assert.equal(readDeviceId(null, () => ID), "");
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => {} };
  assert.equal(readDeviceId(broken, () => ID), "");
  assert.equal(readDeviceId(memory(), () => { throw new Error("no crypto"); }), "");
  const bad = memory();
  assert.equal(readDeviceId(bad, () => "short"), "");
  assert.equal(bad.data[DEVICE_KEY], undefined);
});

test("只有伺服器明講「在別處登入」才講原因;其他的 401 照舊不講", () => {
  assert.equal(elsewhereNotice({ detail: "帳號已在別處登入", code: "signed_in_elsewhere" }), "帳號已在別處登入");
  assert.equal(elsewhereNotice({ detail: "Invalid token." }), null);
  assert.equal(elsewhereNotice({ detail: "", code: "signed_in_elsewhere" }), null);
  assert.equal(elsewhereNotice(null), null);
  assert.equal(elsewhereNotice("text"), null);
});

function fakes(state = "visible") {
  const doc = {
    visibilityState: state,
    listeners: new Set(),
    addEventListener: (_t, fn) => doc.listeners.add(fn),
    removeEventListener: (_t, fn) => doc.listeners.delete(fn),
    fire: () => doc.listeners.forEach((fn) => fn()),
  };
  const timers = {
    tick: null,
    ms: null,
    cleared: false,
    setInterval: (fn, ms) => ((timers.tick = fn), (timers.ms = ms), 7),
    clearInterval: (h) => (timers.cleared = h === 7),
  };
  return { doc, timers };
}

test("畫面開著每分鐘問一次、切回這個分頁馬上問;分頁在背後不問", () => {
  const { doc, timers } = fakes("visible");
  let asked = 0;
  const stop = attachSignInCheck(timers, doc, () => asked++);
  assert.equal(timers.ms, CHECK_MS);
  assert.equal(CHECK_MS, 60 * 1000);
  timers.tick();
  assert.equal(asked, 1);
  doc.visibilityState = "hidden";
  timers.tick();
  doc.fire();
  assert.equal(asked, 1);
  doc.visibilityState = "visible";
  doc.fire();
  assert.equal(asked, 2);
  stop();
  assert.equal(timers.cleared, true);
  assert.equal(doc.listeners.size, 0);
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("登入帶這一台的記號;401 把伺服器講的原因交給登入頁;登入後畫面開著會自己問", () => {
  const auth = read("../auth/AuthContext.tsx");
  assert.match(auth, /device: deviceId\(\)/);
  assert.match(auth, /attachSignInCheck\(window, document,/);
  assert.match(auth, /setNotice\(null\)/); // 登入成功就收掉
  const client = read("../api/client.ts");
  assert.match(client, /elsewhereNotice\(body\)/);
  assert.match(client, /readDeviceId\(/);
  assert.match(read("../pages/login/LoginPage.tsx"), /notice && !error && <Banner kind="info" message=\{notice\} \/>/);
});

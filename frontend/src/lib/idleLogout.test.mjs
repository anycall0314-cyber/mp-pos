// 多久沒有操作就自動登出(2 小時)。用假的時鐘,不真的等。跑法:npm test。
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

import { ACTIVITY_EVENTS, attachIdleLogout, IDLE_MS, TICK_MS, watchIdle } from "./idleLogout.ts";

const SEC = 1000;
const MIN = 60 * SEC;

/** 假時鐘:advance = 時間照常走(到期的計時器照順序跑);sleep = 電腦睡著(時鐘走、計時器不走)。 */
function fakeClock(start = 1_700_000_000_000) {
  let now = start;
  let seq = 0;
  const timers = new Map();
  return {
    now: () => now,
    setTimer(fn, ms) {
      seq += 1;
      timers.set(seq, { at: now + ms, fn });
      return seq;
    },
    clearTimer: (id) => void timers.delete(id),
    advance(ms) {
      const end = now + ms;
      for (;;) {
        let next = null;
        for (const [id, t] of timers) {
          if (t.at <= end && (next === null || t.at < timers.get(next).at)) next = id;
        }
        if (next === null) break;
        const t = timers.get(next);
        timers.delete(next);
        now = t.at;
        t.fn();
      }
      now = end;
    },
    sleep(ms) {
      now += ms;
      for (const t of timers.values()) t.at += ms;
    },
    /** 時鐘被調(往回是負的);計時器照原本剩下的時間 */
    shift(ms) {
      now += ms;
      for (const t of timers.values()) t.at += ms;
    },
    pending: () => timers.size,
  };
}

function watched(limit) {
  const clock = fakeClock();
  let fired = 0;
  const watch = watchIdle(() => (fired += 1), clock, limit);
  return { clock, watch, fired: () => fired };
}

test("門檻是兩小時", () => {
  assert.equal(IDLE_MS, 7_200_000);
});

test("10 分鐘、119 分 59 秒沒操作都還在;滿 120 分鐘才登出,只登出一次", () => {
  const { clock, fired } = watched();
  clock.advance(10 * MIN);
  assert.equal(fired(), 0);
  clock.advance(109 * MIN + 59 * SEC); // 合計 119 分 59 秒
  assert.equal(fired(), 0);
  clock.advance(1 * SEC); // 滿 120 分鐘
  assert.equal(fired(), 1);
  clock.advance(5 * 60 * MIN);
  assert.equal(fired(), 1);
  assert.equal(clock.pending(), 0); // 登出之後不留計時器
});

test("中間有操作:從那一次重新算完整的 120 分鐘", () => {
  const { clock, watch, fired } = watched();
  clock.advance(119 * MIN);
  assert.equal(watch.touch(), true);
  clock.advance(119 * MIN + 59 * SEC); // 離登入已經快四小時,離上次操作 119 分 59 秒
  assert.equal(fired(), 0);
  clock.advance(1 * SEC);
  assert.equal(fired(), 1);
});

test("一直有在操作就一直不登出", () => {
  const { clock, watch, fired } = watched();
  for (let i = 0; i < 40; i += 1) {
    clock.advance(30 * MIN);
    assert.equal(watch.touch(), true);
  }
  assert.equal(fired(), 0); // 二十個小時
});

test("電腦睡著超過兩小時:醒來的第一下不算數(不續命),當場登出", () => {
  const { clock, watch, fired } = watched();
  clock.advance(5 * MIN);
  clock.sleep(3 * 60 * MIN);
  assert.equal(fired(), 0); // 睡著的時候計時器沒在走
  assert.equal(watch.touch(), false);
  assert.equal(fired(), 1);
  assert.equal(clock.pending(), 0); // 被那一下登出的,也不留計時器
  assert.equal(watch.touch(), false); // 登出之後再點也一樣不算
  assert.equal(fired(), 1);
});

test("電腦睡著超過兩小時、醒來沒人碰:一分鐘內自己登出", () => {
  const { clock, fired } = watched();
  clock.advance(5 * MIN + 20 * SEC);
  clock.sleep(3 * 60 * MIN);
  clock.advance(TICK_MS - 1);
  assert.equal(fired(), 1);
  assert.ok(TICK_MS <= MIN);
});

test("睡著的時間也算在沒操作裡:先閒置 30 分、睡 60 分,醒來再 30 分就登出", () => {
  const { clock, fired } = watched();
  clock.advance(30 * MIN);
  clock.sleep(60 * MIN);
  clock.advance(29 * MIN + 59 * SEC);
  assert.equal(fired(), 0);
  clock.advance(1 * SEC);
  assert.equal(fired(), 1);
});

test("回到前景只看一次時鐘,不算操作", () => {
  const { clock, watch, fired } = watched();
  clock.advance(119 * MIN);
  assert.equal(watch.check(), true);
  clock.advance(59 * SEC);
  assert.equal(fired(), 0);
  clock.advance(1 * SEC); // check 沒有重新算:照樣在滿 120 分鐘時登出
  assert.equal(fired(), 1);
  assert.equal(watch.check(), false);

  const late = watched();
  late.clock.sleep(121 * MIN);
  assert.equal(late.watch.check(), false); // 回到前景時已經超過
  assert.equal(late.fired(), 1);
});

test("手動登出 / 換人之後(stop)不會再登出,也不留計時器", () => {
  const { clock, watch, fired } = watched();
  clock.advance(60 * MIN);
  watch.stop();
  assert.equal(clock.pending(), 0);
  clock.advance(10 * 60 * MIN);
  assert.equal(fired(), 0);
  assert.equal(watch.touch(), true); // 已經不歸它管:不擋別人的動作
  assert.equal(watch.check(), true);
  assert.equal(fired(), 0);
});

test("時鐘被往回調:從調的那一刻重新算,不會提早、也不會多等調回去的那一段", () => {
  const { clock, watch, fired } = watched();
  clock.advance(60 * MIN);
  clock.shift(-90 * MIN); // 時鐘往回調一個半小時
  assert.equal(watch.check(), true);
  assert.equal(fired(), 0);
  clock.advance(119 * MIN + 59 * SEC);
  assert.equal(fired(), 0);
  clock.advance(1 * SEC); // 沒有這個處理的話要到 150 分鐘才登出
  assert.equal(fired(), 1);
});

/**
 * 假的視窗,照瀏覽器的順序送一個動作:
 * 1. 先跑掛在 window 上「搶在前面」(capture)的,照掛上去的先後;有人叫 stopImmediatePropagation,後面掛的就不跑。
 * 2. 沒有人攔(stopPropagation / stopImmediatePropagation)才往下到畫面上的按鈕(onButton)。
 * 用不能擋的方式(passive)聽的,叫 preventDefault 沒有用。
 */
function fakePage() {
  const listeners = [];
  const win = {
    document: { visibilityState: "visible" },
    addEventListener(type, fn, options = {}) {
      listeners.push({ type, fn, capture: !!options.capture, passive: !!options.passive });
    },
    removeEventListener(type, fn, options = {}) {
      const at = listeners.findIndex((l) => l.type === type && l.fn === fn && l.capture === !!options.capture);
      if (at >= 0) listeners.splice(at, 1);
    },
  };
  return {
    win,
    listeners,
    send(type, { cancelable = true, onButton = () => {} } = {}) {
      let passiveNow = false;
      const ev = {
        cancelable,
        stopped: false,
        immediate: false,
        prevented: false,
        stopPropagation() {
          this.stopped = true;
        },
        stopImmediatePropagation() {
          this.stopped = true;
          this.immediate = true;
        },
        preventDefault() {
          if (this.cancelable && !passiveNow) this.prevented = true;
        },
      };
      for (const l of listeners.filter((x) => x.type === type && x.capture)) {
        if (ev.immediate) break;
        passiveNow = l.passive;
        l.fn(ev);
      }
      passiveNow = false;
      if (!ev.stopped) onButton(ev);
      return ev;
    },
  };
}

test("接到視窗上:六種動作都掛在 window、搶在前面聽", () => {
  const page = fakePage();
  attachIdleLogout(page.win, () => {}, fakeClock());
  assert.deepEqual([...ACTIVITY_EVENTS].sort(), ["click", "keydown", "mousedown", "mousemove", "scroll", "touchstart"]);
  for (const type of [...ACTIVITY_EVENTS, "visibilitychange"]) {
    const mine = page.listeners.filter((l) => l.type === type);
    assert.equal(mine.length, 1, type);
    assert.equal(mine[0].capture, true, type);
  }
});

test("接到視窗上:每一種動作都重新算;時間內的動作照常送到畫面上的按鈕", () => {
  for (const type of ACTIVITY_EVENTS) {
    const page = fakePage();
    const clock = fakeClock();
    let fired = 0;
    let pressed = 0;
    attachIdleLogout(page.win, () => (fired += 1), clock);
    clock.advance(119 * MIN);
    const ev = page.send(type, { onButton: () => (pressed += 1) });
    assert.equal(pressed, 1, type);
    assert.equal(ev.prevented, false, type);
    clock.advance(119 * MIN + 59 * SEC);
    assert.equal(fired, 0, type);
    clock.advance(1 * SEC);
    assert.equal(fired, 1, type);
  }
});

test("接到視窗上:背景自己問伺服器(沒有人的動作)不算操作", () => {
  const page = fakePage();
  const clock = fakeClock();
  let fired = 0;
  attachIdleLogout(page.win, () => (fired += 1), clock);
  // 只有上面六種動作會被聽;其他的(例如網路回應)根本沒有接
  assert.deepEqual(
    [...new Set(page.listeners.map((l) => l.type))].sort(),
    [...ACTIVITY_EVENTS, "visibilitychange"].sort(),
  );
  clock.advance(120 * MIN);
  assert.equal(fired, 1);
});

test("時間內:別的元件把按鍵攔下來(看大圖的左右鍵),照樣算一次操作 —— 不會明明在按卻被登出", () => {
  // 先掛的、後掛的都試:都攔不住「有在操作」
  for (const when of ["登入前就掛著", "登入後才掛(看大圖)"]) {
    const page = fakePage();
    const clock = fakeClock();
    let fired = 0;
    let lightbox = 0;
    const grab = (ev) => {
      lightbox += 1;
      ev.stopPropagation();
      ev.preventDefault();
    };
    if (when === "登入前就掛著") page.win.addEventListener("keydown", grab, { capture: true });
    attachIdleLogout(page.win, () => (fired += 1), clock);
    if (when !== "登入前就掛著") page.win.addEventListener("keydown", grab, { capture: true });

    clock.advance(119 * MIN);
    page.send("keydown");
    assert.equal(lightbox, 1, when); // 大圖照常收到
    clock.advance(119 * MIN + 59 * SEC);
    assert.equal(fired, 0, when);
    clock.advance(1 * SEC);
    assert.equal(fired, 1, when);
  }
});

test("超過時間之後的那一下:憑證先清掉,後面掛的(看大圖)與畫面上的按鈕都收不到", () => {
  for (const type of ["click", "keydown", "mousedown"]) {
    const page = fakePage();
    const clock = fakeClock();
    let token = "有憑證";
    const got = [];
    attachIdleLogout(page.win, () => (token = null), clock);
    // 登入之後才打開的大圖:也掛在 window 上搶,而且會把事件攔下來
    page.win.addEventListener(type, () => got.push(`大圖看到憑證:${token}`), { capture: true });
    clock.sleep(121 * MIN);
    const ev = page.send(type, { onButton: () => got.push(`按鈕看到憑證:${token}`) });
    assert.equal(token, null, type);
    assert.deepEqual(got, [], type);
    assert.equal(ev.prevented, true, type); // 表單的 Enter 送出、連結的跳頁這類預設動作也取消
  }
});

test("超過時間之後:不能取消的動作(捲動)照樣不往下送,不硬去取消", () => {
  const page = fakePage();
  const clock = fakeClock();
  let reached = 0;
  attachIdleLogout(page.win, () => {}, clock);
  clock.sleep(121 * MIN);
  const ev = page.send("scroll", { cancelable: false, onButton: () => (reached += 1) });
  assert.equal(reached, 0);
  assert.equal(ev.prevented, false);
  // 很密的三種用不擋捲動的方式聽;會按到東西的三種要擋得住
  const passive = page.listeners.filter((l) => l.passive).map((l) => l.type).sort();
  assert.deepEqual(passive, ["mousemove", "scroll", "touchstart"]);
});

test("接到視窗上:分頁回到前景就看一次時鐘;還在背景不看", () => {
  const page = fakePage();
  const clock = fakeClock();
  let fired = 0;
  attachIdleLogout(page.win, () => (fired += 1), clock);
  clock.sleep(121 * MIN);
  page.win.document.visibilityState = "hidden";
  page.send("visibilitychange");
  assert.equal(fired, 0);
  page.win.document.visibilityState = "visible";
  page.send("visibilitychange");
  assert.equal(fired, 1);
});

test("接到視窗上:拆掉之後什麼都不留(不聽、不計時、不登出)", () => {
  const page = fakePage();
  const clock = fakeClock();
  let fired = 0;
  const detach = attachIdleLogout(page.win, () => (fired += 1), clock);
  assert.equal(page.listeners.length, ACTIVITY_EVENTS.length + 1);
  detach();
  assert.equal(page.listeners.length, 0);
  assert.equal(clock.pending(), 0);
  clock.advance(10 * 60 * MIN);
  assert.equal(fired, 0);
});

test("登入那一頁用的是這一支:掛在 window、到期先清憑證,沒有自己另外寫一個時間", () => {
  const page = readFileSync(new URL("../auth/AuthContext.tsx", import.meta.url), "utf8");
  assert.match(page, /attachIdleLogout\(window, \(\) => \{[^}]*setToken\(null\);[^}]*setUser\(null\);[^}]*qc\.clear\(\);[^}]*\}\);/);
  assert.doesNotMatch(page, /IDLE_MS|setTimeout|60 \* 1000/);
});

test("沒有別人用 stopImmediatePropagation 插隊(看大圖攔按鍵用的是 stopPropagation)", () => {
  // 這一支靠「登入時先掛上去」排在 window 的最前面。別的元件在 window 上搶著聽沒關係(看大圖就是),
  // 但不能把同一層後面的人整個擋掉 —— 不然它先掛的話,這一支就收不到動作了。
  const root = new URL("../", import.meta.url);
  const users = readdirSync(root, { recursive: true })
    .filter((f) => /\.tsx?$/.test(f))
    .filter((f) => readFileSync(new URL(f, root), "utf8").includes("stopImmediatePropagation"))
    .map((f) => f.replaceAll("\\", "/"));
  assert.deepEqual(users, ["lib/idleLogout.ts"]);
  const lightbox = readFileSync(new URL("components/photos/PhotoLightbox.tsx", root), "utf8");
  assert.match(lightbox, /window\.addEventListener\("keydown", onKey, true\)/);
});

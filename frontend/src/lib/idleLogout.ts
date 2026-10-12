// 多久沒有操作就自動登出。跑法:npm test。
// owner 2026-10-12:「兩個小時後再登出,十分鐘太短」→ 從最後一次操作起,連續 2 小時沒有操作才登出。
//
// 算的是「離最後一次操作過了多久」(看時鐘),不是單純倒數:電腦睡眠、螢幕蓋上、分頁被瀏覽器凍住的時候
// 計時器會停,回來照實際經過的時間算 —— 超過就登出,不會因為回來動一下滑鼠就續命。
// 超過時間之後的第一下(點擊 / 按鍵)不算數,而且**不讓它按到畫面上的按鈕**(紅隊:被人點一下才登出,那一下不能順便把單送出去)。

/** 連續這麼久沒有操作就登出(毫秒)= 2 小時 */
export const IDLE_MS = 2 * 60 * 60 * 1000;

/** 最久隔這麼久就看一次時鐘(毫秒)。電腦睡醒之後不用等人碰,一分鐘內自己登出。 */
export const TICK_MS = 60 * 1000;

/** 算「有在操作」的動作。背景自己去問伺服器的不算。 */
export const ACTIVITY_EVENTS = ["mousedown", "mousemove", "keydown", "touchstart", "scroll", "click"] as const;

/** 這幾種很密(一秒幾十次)、又不會按到東西:交給瀏覽器用不擋捲動的方式聽。 */
const PASSIVE = new Set<string>(["mousemove", "touchstart", "scroll"]);

export interface IdleClock {
  now: () => number;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
}

const REAL_CLOCK: IdleClock = {
  now: () => Date.now(),
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export interface IdleWatch {
  /** 有人操作了。false = 已經超過時間:這一下不算數,已經登出,呼叫的人要把這個動作擋下來。 */
  touch: () => boolean;
  /** 只看一次時鐘、不算操作(分頁回到前景時用)。false = 已經超過時間、登出了。 */
  check: () => boolean;
  /** 不看了(登出、換人登入時)。之後不會再叫 onIdle。 */
  stop: () => void;
}

/** 開始看「多久沒操作」。超過 limit 叫一次 onIdle,之後就不再看。 */
export function watchIdle(onIdle: () => void, clock: IdleClock = REAL_CLOCK, limit: number = IDLE_MS): IdleWatch {
  let last = clock.now();
  let state: "watching" | "stopped" | "expired" = "watching";
  let timer: unknown = null;

  // 時鐘被往回調(現在比最後一次操作還早):從現在重新算,不然要多等調回去的那一段才登出
  const idleFor = () => {
    const now = clock.now();
    if (now < last) last = now;
    return now - last;
  };
  const disarm = () => {
    if (timer !== null) clock.clearTimer(timer);
    timer = null;
  };
  const arm = () => {
    timer = clock.setTimer(onTimer, Math.min(TICK_MS, Math.max(1, limit - idleFor())));
  };
  /** 還在時間內 = true;超過 = 登出並回 false */
  const stillIn = () => {
    if (idleFor() < limit) return true;
    state = "expired";
    disarm();
    onIdle();
    return false;
  };
  function onTimer() {
    timer = null;
    if (state === "watching" && stillIn()) arm();
  }

  arm();
  return {
    touch() {
      if (state !== "watching") return state === "stopped";
      if (!stillIn()) return false;
      last = clock.now();
      return true;
    },
    check() {
      if (state !== "watching") return state === "stopped";
      return stillIn();
    },
    stop() {
      if (state === "watching") state = "stopped";
      disarm();
    },
  };
}

interface EventLike {
  stopImmediatePropagation: () => void;
  preventDefault: () => void;
}

/** 視窗(window)裡這一支用得到的部分。 */
export interface IdleTarget {
  document: { visibilityState: string };
  addEventListener: (type: string, fn: (ev: EventLike) => void, options?: { capture?: boolean; passive?: boolean }) => void;
  removeEventListener: (type: string, fn: (ev: EventLike) => void, options?: { capture?: boolean }) => void;
}

/**
 * 接到視窗上:登入之後叫一次,回傳的函式在登出 / 換人時叫(把聽的東西全部拆掉)。
 *
 * 聽在**最外層的 window、而且搶在前面(capture)**:一個動作最先經過的就是這裡,畫面上任何一個按鈕、
 * 任何一個自己攔按鍵的元件(看大圖的左右鍵 / Esc 也掛在 window 上搶,但它是登入之後才掛的,排在這一支後面)都在後面。
 * - 時間內:先記一次操作,別人後面要不要攔都不影響「有在操作」。
 * - 超過時間:先登出(清憑證),再把這一下整個吃掉 —— 後面掛在 window 上的、畫面上的按鈕都收不到。
 */
export function attachIdleLogout(target: IdleTarget, onIdle: () => void, clock: IdleClock = REAL_CLOCK): () => void {
  const watch = watchIdle(onIdle, clock);
  const onActivity = (ev: EventLike) => {
    if (watch.touch()) return;
    ev.stopImmediatePropagation();
    ev.preventDefault();
  };
  const onVisibility = () => {
    if (target.document.visibilityState === "visible") watch.check();
  };
  for (const type of ACTIVITY_EVENTS) {
    target.addEventListener(type, onActivity, { capture: true, passive: PASSIVE.has(type) });
  }
  target.addEventListener("visibilitychange", onVisibility, { capture: true });
  return () => {
    watch.stop();
    for (const type of ACTIVITY_EVENTS) target.removeEventListener(type, onActivity, { capture: true });
    target.removeEventListener("visibilitychange", onVisibility, { capture: true });
  };
}

// 同一個帳號同一時間只能在一個位置登入(owner 2026-10-24:「同一時間只允許同一帳號登入一個位置,登入新位置,自動踢掉舊位置」)。跑法:npm test。
//
// 位置 = 一個瀏覽器:第一次打開時產生一個記號存在 localStorage(分頁之間共用、關掉再開還在、登出不清),登入時帶著。
// 同一個瀏覽器另開分頁再登入不會把自己踢掉;換一台電腦 / 換瀏覽器 / 換手機登入,舊的那一台下一次問伺服器就拿到
// 401 + signed_in_elsewhere,跳回登入頁寫伺服器給的那一句。伺服器的規則在 backend/apps/tenants/sign_in.py。

export const DEVICE_KEY = "mp_pos_device";
/** 跟伺服器收的一樣(sign_in.py 的 _DEVICE);不像的當成沒有、重新產生 */
const DEVICE_SHAPE = /^[A-Za-z0-9_-]{16,64}$/;
export const ELSEWHERE_CODE = "signed_in_elsewhere";
/** 畫面開著、這個分頁在前面時,多久問一次「這一把還能不能用」(被踢的那一台不用等人按就跳回登入頁) */
export const CHECK_MS = 60 * 1000;

interface KeyStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** 這個瀏覽器的位置記號;沒有或不像就產生一個存起來。瀏覽器不給存回空字串(伺服器當成每次都是新位置)。 */
export function readDeviceId(store: KeyStore | null, make: () => string): string {
  if (!store) return "";
  try {
    const kept = store.getItem(DEVICE_KEY);
    if (kept && DEVICE_SHAPE.test(kept)) return kept;
    const fresh = make();
    if (!DEVICE_SHAPE.test(fresh)) return "";
    store.setItem(DEVICE_KEY, fresh);
    return fresh;
  } catch {
    return "";
  }
}

/** 401 的內容是不是「帳號已在別處登入」;是的話回伺服器給的那一句,不是回 null */
export function elsewhereNotice(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const { code, detail } = body as { code?: unknown; detail?: unknown };
  if (code !== ELSEWHERE_CODE) return null;
  return typeof detail === "string" && detail ? detail : null;
}

interface Timers {
  setInterval: (fn: () => void, ms: number) => number;
  clearInterval: (handle: number) => void;
}

interface Visibility {
  visibilityState: string;
  addEventListener: (type: "visibilitychange", fn: () => void) => void;
  removeEventListener: (type: "visibilitychange", fn: () => void) => void;
}

/** 分頁在前面時每 `ms` 問一次,切回這個分頁馬上問一次;分頁在背後不問。回傳拆掉的函式。 */
export function attachSignInCheck(timers: Timers, doc: Visibility, check: () => void, ms = CHECK_MS): () => void {
  const ask = () => {
    if (doc.visibilityState === "visible") check();
  };
  const handle = timers.setInterval(ask, ms);
  doc.addEventListener("visibilitychange", ask);
  return () => {
    timers.clearInterval(handle);
    doc.removeEventListener("visibilitychange", ask);
  };
}

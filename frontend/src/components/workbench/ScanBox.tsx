import {
  KeyboardEvent,
  MutableRefObject,
  RefObject,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  addMissed,
  Missed,
  resolveMissed,
  retryTarget,
  scanBlocker,
} from "@/lib/scanMissed";

import { apiErrorText as errText } from "./errors";
import { toast } from "./toast";

export interface ScanOption<T> {
  key: string | number;
  /** 品號(灰色小字,排在品名前面) */
  code?: string;
  label: string;
  badge?: string;
  /** 靠右的灰色小字(例如在庫幾個) */
  hint?: string;
  /** 有就在這一筆最右邊多一顆小按鈕(例如「照片 3」):點了只是看,不會加入 */
  peek?: string;
  payload: T;
}

/** 頁面在送出單據之前要問掃碼框的兩件事 */
export interface ScanBoxApi {
  /** 已經按了 Enter / 點了下拉、還在處理的全部做完(加進去了,或記到「沒加入」)才會結束 */
  idle: () => Promise<void>;
  /**
   * 還有沒有「刷了 / 打了、卻沒進明細」的東西:「沒加入」那一排還有碼,或輸入框裡還留著字。
   * 有的話回一句話(為什麼現在不能送),沒有回 null。
   */
  blocker: () => string | null;
  /** 看完照片回來:游標回到輸入框,原本的搜尋結果還在 */
  resume: () => void;
}

/** 回一句話 = 沒加成(原因);其他 = 加好了 */
type PickResult = void | string | null;

interface Props<T> {
  placeholder: string;
  /** 打字時的商品搜尋 */
  search: (q: string) => Promise<ScanOption<T>[]>;
  /** 把選到的商品加進明細。回一句話 = 沒加成,那句話會留在「沒加入」 */
  onPick: (
    opt: ScanOption<T>,
    via: "enter" | "mouse",
  ) => PickResult | Promise<PickResult>;
  /**
   * 按 Enter(或條碼槍刷完)先問這裡,例如這串字是不是某一台設備的碼。
   * - true:已經處理好了
   * - 一句話:認得這個碼,但不能加(例如那一台在別的分店)。這句話會留在「沒加入」
   * - false:不是它的事,接著當商品找
   */
  onScan?: (code: string) => Promise<boolean | string>;
  /** 這個選項的品號 / 條碼跟輸入的字完全相同 */
  isExact?: (opt: ScanOption<T>, q: string) => boolean;
  /**
   * 這個值一變(例如換了調出分店),輸入框、下拉、「沒加入」、還在查的碼全部作廢:
   * 它們都是照舊的那個值查的。
   */
  resetKey?: string | number;
  /**
   * 點了某一筆的小按鈕(`peek`):頁面開它自己的面板給人看(照片與規格)。
   * `use` = 人看完決定用這一筆:照平常點下拉那樣加入。不用就呼叫 `apiRef.resume()` 回到搜尋。
   */
  onPeek?: (opt: ScanOption<T>, use: () => void) => void;
  /** 頁面拿來問「還有沒有碼在處理」「有沒有碼沒加進去」 */
  apiRef?: MutableRefObject<ScanBoxApi | null>;
  disabled?: boolean;
  autoFocus?: boolean;
  inputRef?: RefObject<HTMLInputElement>;
}

/** 下拉出現多久之後按 Enter,才算「人看到了才按的」 */
const SEEN_MS = 350;
let missSeq = 0;

/**
 * 工作台的掃碼框:一格同時收「條碼槍刷的碼」與「手打的品名」。
 *
 * - 打字 → 下拉列出商品,上下鍵選、Enter 或點一下加入。
 * - 條碼槍(打得比搜尋快,下拉還沒出來就 Enter)→ 輸入框立刻清空,
 *   下一個碼可以接著刷;刷進來的碼排隊照順序一個一個處理,不會漏。
 * - 自動加入只收兩種:品號 / 條碼完全相同剛好一筆;或下拉已經出現一下子、人看著它按 Enter(取反白那一筆)。
 *   其他情況不替人猜。
 * - **按了 Enter 卻沒加進明細的碼,一律記在輸入框下面的「沒加入」**(找不到、相似的太多、那一台不能用、數量不夠…)。
 *   方便的話會順便把字放回輸入框(整段反白)給人改或挑,但「記下來」不靠輸入框:
 *   下一個碼刷進來把輸入框蓋掉,那一筆還是留在「沒加入」。
 *   一筆「沒加入」只有兩種方式會消失:同一個碼後來加成功了,或人按「清掉」。
 *   同一個碼失敗幾次就記幾筆(刷了 5 個同樣的配件都沒加進去,要補 5 次)。
 */
export function ScanBox<T>({
  placeholder,
  search,
  onPick,
  onScan,
  isExact,
  resetKey,
  onPeek,
  apiRef,
  disabled,
  autoFocus,
  inputRef,
}: Props<T>) {
  /** 人正在看某一筆的照片:游標離開輸入框,下拉先不要收(回來要接著找) */
  const peeking = useRef(false);
  const [text, setText] = useState("");
  const [items, setItems] = useState<ScanOption<T>[]>([]);
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const [missed, setMissedState] = useState<Missed[]>([]);
  // 「沒加入」另外留一份當下的:頁面在送出前會馬上來問,不能等畫面重畫
  const missedNow = useRef<Missed[]>([]);
  function setMissed(next: Missed[] | ((cur: Missed[]) => Missed[])) {
    missedNow.current =
      typeof next === "function" ? next(missedNow.current) : next;
    setMissedState(missedNow.current);
  }
  const own = useRef<HTMLInputElement>(null);
  const ref = inputRef ?? own;
  const textRef = useRef("");
  /** 下拉現在列的是哪一串字的結果、什麼時候出現的 */
  const shownFor = useRef<string | null>(null);
  const shownAt = useRef(0);
  /** 人有沒有用上下鍵動過反白 */
  const moved = useRef(false);
  const seq = useRef(0);
  /** resetKey 每變一次加一;排隊中的碼發現自己是舊的就不做了 */
  const epoch = useRef(0);
  /** 人點了「沒加入」的哪一筆放回輸入框重查(重查的結果要算在那一筆上,不是多一筆) */
  const retrying = useRef<Missed | null>(null);
  /**
   * 程式放回輸入框、人還沒碰過的那串字。下一個進來的字要「取代」它,不是接在後面:
   * 正常靠整段反白;反白萬一沒生效(視窗在背景、條碼槍的第一個字搶在前面),就用這個把前面那一段拿掉。
   */
  const untouched = useRef<string | null>(null);
  const timer = useRef<number>();
  const blurTimer = useRef<number>();
  const queue = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);

  useEffect(
    () => () => {
      window.clearTimeout(timer.current);
      window.clearTimeout(blurTimer.current);
    },
    [],
  );

  function setValue(v: string) {
    textRef.current = v;
    untouched.current = null;
    setText(v);
  }

  /** 程式把一串字放進輸入框:當下就放、當下就整段反白(不等下一個畫面,視窗在背景時那個不會來) */
  function place(kw: string) {
    setValue(kw);
    untouched.current = kw;
    const el = ref.current;
    if (el) {
      el.value = kw;
      el.focus();
      el.select();
    }
  }

  function closeMenu() {
    setOpen(false);
    setItems([]);
    shownFor.current = null;
    moved.current = false;
  }

  function showList(kw: string, list: ScanOption<T>[]) {
    setItems(list);
    setSel(0);
    shownFor.current = kw;
    shownAt.current = Date.now();
    moved.current = false;
    setOpen(true);
  }

  useEffect(() => {
    epoch.current++;
    seq.current++;
    retrying.current = null;
    window.clearTimeout(timer.current);
    closeMenu();
    setValue("");
    setMissed([]);
    // 只看 resetKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  useEffect(() => {
    if (!apiRef) return;
    apiRef.current = {
      // 佇列是一條接一條串起來的,等到「現在的最後一個」不再變,就是全部做完
      idle: async () => {
        let tail: Promise<void>;
        do {
          tail = queue.current;
          await tail;
        } while (tail !== queue.current);
      },
      blocker: () => scanBlocker(missedNow.current, textRef.current),
      resume: () => {
        peeking.current = false;
        ref.current?.focus();
      },
    };
    return () => {
      apiRef.current = null;
    };
  }, [apiRef]);

  /**
   * 這個碼沒加進去:記到「沒加入」。
   * retryOf = 這次是人點了某一筆「沒加入」重查的:結果算在那一筆上(換原因),不另外多一筆。
   */
  function miss(kw: string, reason: string, retryOf: Missed | null = null) {
    toast(`${kw}:${reason}`, "err");
    setMissed((cur) =>
      addMissed(cur, { id: ++missSeq, kw, reason }, retryOf),
    );
  }

  /** 這個碼加成功了:如果它之前記在「沒加入」,劃掉一筆(重查的就是劃掉那一筆) */
  function resolved(kw: string, retryOf: Missed | null = null) {
    setMissed((cur) => resolveMissed(cur, kw, retryOf));
  }

  /** 輸入框現在的字,是不是人點「沒加入」放回來重查的那一筆 */
  function takeRetry(kw: string): Missed | null {
    const r = retryTarget(retrying.current, kw);
    retrying.current = null;
    return r;
  }

  function runSearch(kw: string) {
    window.clearTimeout(timer.current);
    const my = ++seq.current;
    timer.current = window.setTimeout(async () => {
      try {
        const list = await search(kw);
        // 等結果的時候又打了字 / 已經按了 Enter / 換了分店:這份結果不要了
        if (my !== seq.current || textRef.current.trim() !== kw) return;
        showList(kw, list);
      } catch (e) {
        if (my === seq.current) toast(errText(e), "err");
      }
    }, 180);
  }

  function onType(raw: string) {
    let v = raw;
    const stale = untouched.current;
    untouched.current = null;
    // 放回來的字沒有被取代、新的字接在它後面了(反白沒生效):把前面那一段拿掉,只留新打的
    if (stale && v.length > stale.length && v.startsWith(stale)) {
      v = v.slice(stale.length);
    }
    setValue(v);
    // 有打字(包含條碼槍把放回來的字蓋掉)就是新的一次輸入,不是「重查那一筆」:
    // 同一個碼再刷一次又失敗,要多記一筆,不是算在上一筆上
    retrying.current = null;
    moved.current = false;
    const kw = v.trim();
    if (kw.length < 2) {
      window.clearTimeout(timer.current);
      seq.current++;
      closeMenu();
      return;
    }
    runSearch(kw);
  }

  /** 排進佇列(頁面送出前會等佇列做完) */
  function enqueue(job: () => Promise<void>) {
    waiting.current++;
    queue.current = queue.current
      .then(job)
      .catch((e) => toast(errText(e), "err"))
      .finally(() => {
        waiting.current--;
      });
  }

  /** 人從下拉挑了一筆(滑鼠點,或用上下鍵挑好按 Enter) */
  function pick(opt: ScanOption<T>, via: "enter" | "mouse") {
    const kw = textRef.current.trim();
    const retryOf = takeRetry(kw);
    const born = epoch.current;
    seq.current++;
    window.clearTimeout(timer.current);
    closeMenu();
    setValue("");
    enqueue(async () => {
      if (born !== epoch.current) return;
      let problem: PickResult;
      try {
        problem = await onPick(opt, via);
      } catch (e) {
        problem = errText(e);
      }
      if (born !== epoch.current) return;
      if (typeof problem === "string") miss(kw || opt.label, problem, retryOf);
      else if (kw) resolved(kw, retryOf);
    });
    ref.current?.focus();
  }

  /**
   * 順便把字放回輸入框(整段反白)給人改或挑。只是方便:後面還有碼在排隊、
   * 或輸入框已經又有字,就不放 —— 那個碼已經記在「沒加入」,不會因為沒放回來就不見。
   */
  function putBack(kw: string, list: ScanOption<T>[], entry: Missed | null) {
    if (waiting.current > 1 || textRef.current !== "") return;
    place(kw);
    // 接著按 Enter / 從下拉挑,算在「沒加入」的這一筆上
    retrying.current = entry;
    if (list.length > 0) showList(kw, list);
  }

  /** 沒加成:記下來,方便的話放回輸入框 */
  function fail(
    kw: string,
    reason: string,
    list: ScanOption<T>[],
    retryOf: Missed | null,
  ) {
    miss(kw, reason, retryOf);
    const entry =
      (retryOf && missedNow.current.find((m) => m.id === retryOf.id)) ||
      missedNow.current[missedNow.current.length - 1] ||
      null;
    putBack(kw, list, entry);
  }

  async function handle(
    kw: string,
    seen: boolean,
    born: number,
    retryOf: Missed | null,
  ) {
    const stale = () => born !== epoch.current;
    if (onScan) {
      let result: boolean | string;
      try {
        result = await onScan(kw);
      } catch (e) {
        result = errText(e);
      }
      if (stale()) return;
      if (typeof result === "string") {
        // 認得這個碼、但不能加:放回輸入框也沒有東西可以挑,只記下來
        miss(kw, result, retryOf);
        return;
      }
      if (result) {
        resolved(kw, retryOf);
        return;
      }
    }
    if (kw.length < 2) {
      fail(kw, "太短", [], retryOf);
      return;
    }
    let list: ScanOption<T>[];
    try {
      list = await search(kw);
    } catch (e) {
      if (!stale()) miss(kw, errText(e), retryOf);
      return;
    }
    if (stale()) return;
    if (list.length === 0) {
      fail(kw, "找不到", [], retryOf);
      return;
    }
    const exact = isExact ? list.filter((o) => isExact(o, kw)) : [];
    // 只有一筆但不是完全相同(例如刷的是某一台 IMEI 的一部分):沒看到下拉就不自動加
    const chosen = exact.length === 1 ? exact[0] : seen ? list[0] : null;
    if (!chosen) {
      fail(
        kw,
        list.length === 1 ? "不是完全相同" : `有 ${list.length} 個相似`,
        list,
        retryOf,
      );
      return;
    }
    let problem: PickResult;
    try {
      problem = await onPick(chosen, "enter");
    } catch (e) {
      problem = errText(e);
    }
    if (stale()) return;
    if (typeof problem === "string") miss(kw, problem, retryOf);
    else resolved(kw, retryOf);
  }

  function submit() {
    const kw = textRef.current.trim();
    if (!kw) return;
    window.clearTimeout(timer.current);
    const listed = open && shownFor.current === kw && items.length > 0;
    // 人用上下鍵挑好了 → 就是反白那一筆
    if (listed && moved.current && items[sel]) {
      pick(items[sel], "enter");
      return;
    }
    // 下拉剛出現就 Enter 的是條碼槍(慢一點的藍牙槍也是),不是人看了才按的
    const seen = listed && Date.now() - shownAt.current >= SEEN_MS;
    const retryOf = takeRetry(kw);
    const born = epoch.current;
    seq.current++;
    closeMenu();
    setValue("");
    enqueue(() => handle(kw, seen, born, retryOf));
  }

  /** 點「沒加入」的某一筆:放回輸入框重查。那一筆留著,等真的加成功(或按清掉)才消失 */
  function retry(m: Missed) {
    place(m.kw);
    retrying.current = m;
    if (m.kw.trim().length >= 2) runSearch(m.kw.trim());
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // 注音 / 倉頡選字中的 Enter 不算
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (
      e.key === "Enter" ||
      (e.key === "Tab" && !e.shiftKey && textRef.current.trim())
    ) {
      // 有些條碼槍結尾送 Tab
      e.preventDefault();
      submit();
      return;
    }
    if (
      ["ArrowLeft", "ArrowRight", "Home", "End", "Backspace", "Delete"].includes(
        e.key,
      )
    ) {
      untouched.current = null;
    }
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moved.current = true;
      setSel((s) => Math.min(items.length - 1, s + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moved.current = true;
      setSel((s) => Math.max(0, s - 1));
    } else if (e.key === "Escape") {
      e.stopPropagation();
      closeMenu();
    }
  }

  return (
    <div className="wb-scan">
      <div className="wb-scan-in">
        <input
          ref={ref}
          type="text"
          value={text}
          placeholder={placeholder}
          disabled={disabled}
          autoFocus={autoFocus}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => onType(e.target.value)}
          onKeyDown={onKeyDown}
          onMouseDown={() => {
            untouched.current = null;
          }}
          onFocus={() => window.clearTimeout(blurTimer.current)}
          onBlur={() => {
            if (peeking.current) return;
            blurTimer.current = window.setTimeout(() => setOpen(false), 150);
          }}
        />
        {open && (
          <div className="wb-scan-menu">
            {items.length === 0 && (
              <div className="wb-scan-item none">找不到商品</div>
            )}
            {items.map((o, i) => (
              <div
                key={o.key}
                className={`wb-scan-item${i === sel ? " sel" : ""}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(o, "mouse");
                }}
              >
                {o.code && <span className="code">{o.code}</span>}
                <span>{o.label}</span>
                {o.badge && <span className="wb-badge">{o.badge}</span>}
                {o.hint && <span className="hint">{o.hint}</span>}
                {o.peek && onPeek && (
                  <button
                    type="button"
                    className={`ph-peek${o.hint ? "" : " alone"}`}
                    tabIndex={-1}
                    onMouseDown={(e) => {
                      // 只是看:不加入、輸入框的字與下拉都留著
                      e.preventDefault();
                      e.stopPropagation();
                      peeking.current = true;
                      window.clearTimeout(blurTimer.current);
                      onPeek(o, () => {
                        peeking.current = false;
                        pick(o, "mouse");
                      });
                    }}
                  >
                    {o.peek}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      {missed.length > 0 && (
        <div className="wb-scan-missed">
          <span className="wb-label">沒加入</span>
          {missed.map((m) => (
            <button
              key={m.id}
              type="button"
              className="wb-badge bad"
              title="點一下放回輸入框重查"
              disabled={disabled}
              onClick={() => retry(m)}
            >
              {m.kw} · {m.reason}
            </button>
          ))}
          <button
            type="button"
            className="wb-link"
            disabled={disabled}
            onClick={() => {
              // 明講不要了:連輸入框裡還沒加進去的字一起清
              setMissed([]);
              retrying.current = null;
              seq.current++;
              window.clearTimeout(timer.current);
              closeMenu();
              setValue("");
              ref.current?.focus();
            }}
          >
            清掉
          </button>
        </div>
      )}
    </div>
  );
}

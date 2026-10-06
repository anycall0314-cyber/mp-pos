import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, ApiHttpError } from "@/api/client";
import {
  useConfirmTransferOrder,
  useCreateTransferOrder,
  useTransferOrder,
  useTransferOrders,
  useVoidTransferOrder,
  useWarehouses,
} from "@/api/hooks";
import {
  fetchInStockSerials,
  findDevicesByCode,
  searchProducts,
} from "@/api/search";
import type {
  Paginated,
  Product,
  ProductSerial,
  PurchaseTransferable,
  TransferOrder,
} from "@/api/types";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import {
  ScanBox,
  ScanBoxApi,
  ScanOption,
} from "@/components/workbench/ScanBox";
import { toast } from "@/components/workbench/toast";
import { useIsMobile } from "@/hooks/useIsMobile";
import { codesLabel, normalizeCode } from "@/lib/deviceCodes";

/**
 * 調撥(工作台版型):一個畫面做完。
 *
 * 上面一張卡:調出 / 調入分店、日期、備註、掃碼框、確認。
 * 掃一下(品號 / 條碼 / IMEI / SN)或打品名就加一行,新的一行排最上面;
 * 序號商品把調出分店在庫的每一台列成小標籤(後 6 碼),點一下或再掃那一台的碼就選起來。
 * 下面是最近的調撥單:點一列展開明細,待入庫的直接在列上按「入庫」。
 *
 * 規則沒有變:確認 = 派發(東西離開調出分店,變成調撥中),調入分店按入庫才進庫存;
 * 能不能調由後端存檔時鎖住庫存再檢查。
 *
 * 選哪一台只有三條路:刷到那一台的碼(完全相同)、人點小標籤、人從下拉用滑鼠點了商品而那家分店只剩一台。
 * 其他情況一律不替人選 —— 刷的可能是別台的碼的一部分,自動選起來的卻是這家分店剩下的那一台。
 */

interface Unit {
  id: number;
  serial_no: string;
  imei: string;
  sn: string;
}

interface Line {
  key: string;
  /** 這一行是照哪一家調出分店的庫存建的(換了分店就不能再用) */
  warehouse: number;
  product: number;
  sku: string;
  name: string;
  requiresSerial: boolean;
  /** 序號商品:調出分店在庫的每一台;null = 還在載入 */
  units: Unit[] | null;
  /** 選起來要調的那幾台 */
  picked: number[];
  /** 配件:調出分店現有幾個;null = 不知道(交給後端檢查) */
  avail: number | null;
  /** 配件數量(序號商品的數量 = 選了幾台) */
  qty: number;
  error: string | null;
  /** 每加一 → 這一列閃一下 */
  flash: number;
}

interface NewProduct {
  id: number;
  sku: string;
  name: string;
  requiresSerial: boolean;
  avail?: number;
}

/** 一次掃碼 / 選商品是照哪一家調出分店做的;中途換了分店(gen 不一樣)就整個不算 */
interface Ctx {
  warehouse: number;
  gen: number;
}

const K_FROM = "mp_pos_xfer_from";
const K_TO = "mp_pos_xfer_to";
const K_DIRECT = "mp_pos_xfer_direct";

function readNum(key: string): number | null {
  try {
    const n = Number(localStorage.getItem(key));
    return n > 0 ? n : null;
  } catch {
    return null;
  }
}
function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 存不了就算了,不影響調撥 */
  }
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
/** 今天(電腦所在地的日期;不用 toISOString,凌晨會變成前一天) */
function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function clock(iso: string): string {
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function daysSince(iso: string): number {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
}

function toUnit(s: {
  id: number;
  serial_no: string;
  imei: string;
  sn: string;
}): Unit {
  return { id: s.id, serial_no: s.serial_no, imei: s.imei, sn: s.sn };
}
function mainOf(u: Unit): string {
  return u.imei || u.sn || u.serial_no;
}
/**
 * 小標籤上的字:主碼(IMEI 優先)的後 6 碼。
 * 同一行裡後 6 碼撞在一起的那幾台,多顯示幾碼到分得出來為止(不然點到的跟以為的不是同一台)。
 */
function tailsOf(units: Unit[]): Map<number, string> {
  const out = new Map<number, string>();
  let pending = units;
  for (let len = 6; pending.length > 0; len += 2) {
    const groups = new Map<string, Unit[]>();
    for (const u of pending) {
      const t = mainOf(u).slice(-len);
      groups.set(t, [...(groups.get(t) ?? []), u]);
    }
    const next: Unit[] = [];
    for (const [t, group] of groups) {
      // 只有一台是這幾碼,或已經把整個碼都列出來了
      if (group.length === 1 || group.every((u) => mainOf(u).length <= len)) {
        for (const u of group) out.set(u.id, t);
      } else {
        next.push(...group);
      }
    }
    pending = next;
  }
  return out;
}
function lineQty(l: Line): number {
  return l.requiresSerial ? l.picked.length : l.qty;
}
/**
 * 伺服器有沒有「明講不行」(4xx:檢查沒過,單一定沒成立)。
 * 連線中斷、或中間那一層回 5xx / 逾時,都算「不知道結果」:伺服器可能其實已經做完了。
 */
function refused(e: unknown): boolean {
  return e instanceof ApiHttpError && e.status >= 400 && e.status < 500;
}
/**
 * 這一張已經成立的調撥單,是不是剛剛送出去的那一份(同樣的分店、同樣的商品 / 數量 / 那幾台,而且是剛剛才建的)。
 * 連線在送出途中斷掉時,用它回頭認「其實有沒有成立」,免得同一份再送一次變成兩張。
 */
function sameOrder(
  t: TransferOrder,
  sentFrom: number,
  sentTo: number,
  sentLines: Line[],
  startedAt: number,
): boolean {
  if (t.is_void) return false;
  if (t.from_warehouse !== sentFrom || t.to_warehouse !== sentTo) return false;
  const created = new Date(t.created_at).getTime();
  // 兩台電腦的時鐘可能差一點,往前放寬一分鐘
  if (!Number.isFinite(created) || created < startedAt - 60_000) return false;
  if (t.items.length !== sentLines.length) return false;
  const sig = (product: number, qty: number, serials: number[]) =>
    `${product}:${qty}:${[...serials].sort((a, b) => a - b).join(",")}`;
  const want = sentLines
    .map((l) => sig(l.product, lineQty(l), l.requiresSerial ? l.picked : []))
    .sort();
  const got = t.items
    .map((it) => sig(it.product, it.qty, it.serials.map((s) => s.serial)))
    .sort();
  return want.every((w, i) => w === got[i]);
}

export function TransferWorkbenchPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { id } = useParams<{ id?: string }>();
  /** 從別頁點一張調撥單過來(/transfers/123):清單裡把它展開 */
  const focusId = id && id !== "new" && Number(id) > 0 ? Number(id) : null;
  const [searchParams] = useSearchParams();
  const fromPo = focusId ? null : Number(searchParams.get("from_po")) || null;

  const me = useDefaultWarehouse();
  const warehousesQ = useWarehouses();
  const stores = useMemo(
    () => (warehousesQ.data ?? []).filter((w) => w.is_active),
    [warehousesQ.data],
  );
  const storeName = (wid: number | null | "") =>
    stores.find((w) => w.id === wid)?.name ?? "";

  const createMutation = useCreateTransferOrder();
  const confirmMutation = useConfirmTransferOrder();
  const voidMutation = useVoidTransferOrder();

  const [from, setFrom] = useState<number | "">(() =>
    me.locked && me.id ? me.id : (readNum(K_FROM) ?? me.id ?? ""),
  );
  const [to, setTo] = useState<number | "">(() => readNum(K_TO) ?? "");
  const [docDate, setDocDate] = useState(today);
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  /** 整張調撥時被略過的東西(已經不在進貨門市) */
  const [skipped, setSkipped] = useState<string | null>(null);
  const [poLoading, setPoLoading] = useState(!!fromPo);
  const [direct, setDirect] = useState(() => {
    try {
      return localStorage.getItem(K_DIRECT) === "1";
    } catch {
      return false;
    }
  });
  const [busy, setBusy] = useState(false);
  /** 上一次送出時連線中斷,不確定有沒有成立:再送要多按一次 */
  const [unsure, setUnsure] = useState(false);
  // 最近調撥那一塊的狀態
  const [onlyPending, setOnlyPending] = useState(false);
  const [day, setDay] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(focusId);
  /** 剛送出的那一張(清單裡閃一下) */
  const [newId, setNewId] = useState<number | null>(null);
  /**
   * 「單已經送出、入庫沒成功」的說明,一張單一則。跟一般的錯誤訊息分開放:
   * 做下一張、按取消、送出失敗都不能把它清掉(不然會被當成那一張沒成立再做一次),
   * 只有那一張入庫 / 作廢了,或人按「知道了」才收。
   */
  const [notices, setNotices] = useState<{ id: number; text: string }[]>([]);
  /** 一定要出現在最近調撥裡的那一張(入庫沒成功的新單;不管清單現在篩什麼日期) */
  const [pinnedId, setPinnedId] = useState<number | null>(null);

  const scanRef = useRef<HTMLInputElement>(null);
  /**
   * 按下確認之後分兩段,各記一份「當下的」(按鈕變灰要等畫面重畫,不能只靠畫面):
   * submitting = 已經按了確認(人不能再動這張單;但剛刷的碼還在查的,要讓它們做完、算進這張單);
   * sending    = 要送的內容已經定了(這之後才處理到的碼一律不加)。
   */
  const submitting = useRef(false);
  const sending = useRef(false);
  const scanApi = useRef<ScanBoxApi | null>(null);
  // 掃碼是一個接一個排隊處理的:下一個碼要馬上看得到上一個碼加的那一行,
  // 所以明細、調出分店都另外留一份「當下最新」的,不等畫面重畫。
  const linesRef = useRef<Line[]>([]);
  const fromRef = useRef<number | "">(from);
  /** 調出分店每換一次加一;還在查的碼、還在載的序號發現自己是舊的就不做了 */
  const genRef = useRef(0);

  function switchFrom(next: number | "") {
    if (fromRef.current === next) return;
    fromRef.current = next;
    genRef.current++;
    setFrom(next);
  }
  function ctxNow(): Ctx | null {
    const warehouse = fromRef.current;
    return warehouse === "" ? null : { warehouse, gen: genRef.current };
  }
  const live = (ctx: Ctx) => ctx.gen === genRef.current;

  function commit(fn: (ls: Line[]) => Line[]) {
    const next = fn(linesRef.current);
    linesRef.current = next;
    setLines(next);
  }
  function patch(key: string, fn: (l: Line) => Line) {
    commit((ls) => ls.map((l) => (l.key === key ? fn(l) : l)));
  }
  /** 這一行移到最上面並閃一下 */
  function bump(key: string, fn: (l: Line) => Line = (l) => l) {
    commit((ls) => {
      const hit = ls.find((l) => l.key === key);
      if (!hit) return ls;
      return [
        { ...fn(hit), flash: hit.flash + 1 },
        ...ls.filter((l) => l.key !== key),
      ];
    });
  }

  // 門市清單回來之後,把調出 / 調入補成可用的值(記住的門市可能已停用)
  useEffect(() => {
    if (stores.length === 0) return;
    const ids = stores.map((s) => s.id);
    let f = fromRef.current;
    let t = to;
    if (f === "" || !ids.includes(f)) {
      f = me.id && ids.includes(me.id) ? me.id : ids[0];
    }
    if (t === "" || !ids.includes(t) || t === f) {
      t = ids.find((x) => x !== f) ?? "";
    }
    switchFrom(f);
    if (t !== to) setTo(t);
    // 只在門市清單載入時跑一次;之後由人選
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stores]);

  function clearLines(why: string, undo: () => void) {
    const kept = linesRef.current;
    if (kept.length === 0) return;
    commit(() => []);
    toast(why, "", {
      action: {
        label: "復原",
        fn: () => {
          if (submitting.current) {
            toast("正在送出,不能復原", "err");
            return;
          }
          // 清空之後又掃了新的:不能拿舊的蓋掉(換過調出分店的話,兩邊的東西也不能混在一張單)
          if (linesRef.current.length > 0) {
            toast("已經有新的明細,沒有復原", "err");
            return;
          }
          undo();
          // 分店沒有回到這些明細當初的那一家(中間又換過)就不放回來
          if (kept.some((l) => l.warehouse !== fromRef.current)) {
            toast("調出分店已經不一樣,沒有復原", "err");
            return;
          }
          commit(() => kept);
          reloadUnloaded(kept);
        },
      },
    });
  }

  /** 被放回來的行如果當初還沒載到序號(或載失敗),重新載一次,不然會一直停在「載入中」 */
  function reloadUnloaded(restored: Line[]) {
    const ctx = ctxNow();
    if (!ctx) return;
    for (const l of restored) {
      if (l.requiresSerial && (l.units === null || l.error)) {
        void loadUnits(l.key, l.product, ctx, false);
      }
    }
  }

  function changeFrom(next: number) {
    if (submitting.current) return;
    const prev = { from: fromRef.current, to };
    if (prev.from === next) return;
    switchFrom(next);
    // 選到跟調入同一家 → 兩家對調
    if (next === to) setTo(prev.from);
    remember(K_FROM, String(next));
    if (next === to && prev.from !== "") remember(K_TO, String(prev.from));
    clearLines("已換調出分店,明細已清空", () => {
      // 中間又換過別家就不動分店(下面會因為分店對不上而不放回明細)
      if (fromRef.current !== next) return;
      switchFrom(prev.from);
      setTo(prev.to);
      if (prev.from !== "") remember(K_FROM, String(prev.from));
      if (prev.to !== "") remember(K_TO, String(prev.to));
    });
    scanRef.current?.focus();
  }
  function changeTo(next: number) {
    if (submitting.current) return;
    setTo(next);
    remember(K_TO, String(next));
    scanRef.current?.focus();
  }
  function swap() {
    if (fromRef.current === "" || to === "") return;
    changeFrom(to);
  }

  /**
   * 序號商品:把調出分店在庫的每一台載進來當小標籤。
   * autoPick:那家分店只剩一台時要不要直接選起來(只有人用滑鼠從下拉點商品時才會是 true)。
   * optional:這一行本來就有可用的序號(整張調撥帶進來的),這次只是多列幾台給人換;載不到就照原樣,不算錯。
   */
  async function loadUnits(
    key: string,
    product: number,
    ctx: Ctx,
    autoPick: boolean,
    optional = false,
  ) {
    let dropped = 0;
    try {
      const all = await fetchInStockSerials(product, ctx.warehouse);
      if (!live(ctx)) return;
      const units = all
        .map(toUnit)
        .sort((a, b) => a.serial_no.localeCompare(b.serial_no));
      patch(key, (l) => {
        // 整張調撥先帶進來的那幾台也留著(萬一這次沒列到)
        const known = new Set(units.map((u) => u.id));
        const merged = [
          ...units,
          ...(l.units ?? []).filter((u) => !known.has(u.id)),
        ];
        const has = new Set(merged.map((u) => u.id));
        let picked = l.picked.filter((sid) => has.has(sid));
        dropped = l.picked.length - picked.length;
        if (
          autoPick &&
          l.picked.length === 0 &&
          picked.length === 0 &&
          merged.length === 1
        ) {
          picked = [merged[0].id];
        }
        return { ...l, units: merged, picked, error: null };
      });
    } catch (e) {
      if (!live(ctx) || optional) return;
      // 這一次沒載到就是沒載到(上一次有沒有成功都一樣):留著錯誤,送出前會擋
      patch(key, (l) => ({
        ...l,
        units: l.units ?? [],
        error: apiErrorText(e),
      }));
    }
    return dropped;
  }

  /** 選起某一台。回一句話 = 沒選成(原因) */
  function pickUnit(key: string, serialId: number): string | null {
    if (sending.current) return "正在送出,沒有加";
    const line = linesRef.current.find((l) => l.key === key);
    if (!line) return null;
    if (line.units && !line.units.some((u) => u.id === serialId)) {
      bump(key);
      return `「${line.name}」這一台不在調出分店的在庫裡`;
    }
    bump(key, (l) =>
      l.picked.includes(serialId)
        ? l
        : { ...l, picked: [...l.picked, serialId] },
    );
    return null;
  }

  /** 加一個商品到明細。回一句話 = 沒加成 / 加了但有狀況(原因) */
  async function addProduct(
    p: NewProduct,
    ctx: Ctx,
    opts: { via: "enter" | "mouse"; pickSerial?: number },
  ): Promise<string | null> {
    if (!live(ctx)) return null;
    // 送出去的內容已經定了:這時候才處理到的碼不能再改明細
    if (sending.current) return "正在送出,沒有加";
    const existing = linesRef.current.find((l) => l.product === p.id);
    if (existing) {
      if (existing.requiresSerial) {
        if (opts.pickSerial) return pickUnit(existing.key, opts.pickSerial);
        bump(existing.key);
        return "已在明細,點序號或掃它的 IMEI";
      }
      if (existing.avail != null && existing.qty + 1 > existing.avail) {
        bump(existing.key);
        return `可調數量只有 ${existing.avail}`;
      }
      bump(existing.key, (l) => ({ ...l, qty: l.qty + 1 }));
      return null;
    }
    const key = crypto.randomUUID();
    const line: Line = {
      key,
      warehouse: ctx.warehouse,
      product: p.id,
      sku: p.sku,
      name: p.name,
      requiresSerial: p.requiresSerial,
      units: p.requiresSerial ? null : [],
      picked: opts.pickSerial ? [opts.pickSerial] : [],
      avail: p.requiresSerial ? null : (p.avail ?? null),
      qty: 1,
      error: null,
      flash: 0,
    };
    // 新加的放最上面:品項多的時候不用一路往下找
    commit((ls) => [line, ...ls]);
    if (!p.requiresSerial) {
      return p.avail != null && p.avail <= 0 ? "調出分店沒有可調庫存" : null;
    }
    const dropped = await loadUnits(
      key,
      p.id,
      ctx,
      opts.via === "mouse" && !opts.pickSerial,
    );
    if (!live(ctx)) return null;
    if (dropped) return `已加入 ${p.name},但這一台不在可調的清單裡`;
    return null;
  }

  function toggleUnit(key: string, serialId: number) {
    if (submitting.current) return;
    patch(key, (l) => ({
      ...l,
      picked: l.picked.includes(serialId)
        ? l.picked.filter((x) => x !== serialId)
        : [...l.picked, serialId],
    }));
    // 點完標籤游標回掃碼框,條碼槍可以接著刷
    scanRef.current?.focus();
  }

  function removeLine(key: string) {
    if (submitting.current) return;
    const all = linesRef.current;
    const idx = all.findIndex((l) => l.key === key);
    if (idx < 0) return;
    const gone = all[idx];
    commit((ls) => ls.filter((l) => l.key !== key));
    toast(`已移除 ${gone.name}`, "", {
      action: {
        label: "復原",
        fn: () => {
          if (submitting.current) {
            toast("正在送出,不能復原", "err");
            return;
          }
          // 移除之後換了調出分店:這一行的序號與可調數量都是舊分店的,不能放回來
          if (fromRef.current !== gone.warehouse) {
            toast("已經換了調出分店,沒有復原", "err");
            return;
          }
          commit((ls) => {
            if (ls.some((l) => l.key === key || l.product === gone.product)) {
              return ls;
            }
            const next = [...ls];
            next.splice(Math.min(idx, next.length), 0, gone);
            return next;
          });
          if (linesRef.current.some((l) => l.key === key)) {
            reloadUnloaded([gone]);
          }
        },
      },
    });
    scanRef.current?.focus();
  }

  /** 刷到 / 打完 Enter 的那串字,先看是不是某一台設備的碼 */
  async function onScan(code: string): Promise<boolean | string> {
    const ctx = ctxNow();
    if (!ctx) return "先選調出分店";
    if (!normalizeCode(code)) return true;
    // 不管多短、畫面上有沒有這一台,一律先問整家公司「這個碼是哪一台」(完全相同才算):
    // 舊資料裡兩台的碼撞在一起時,不能因為其中一台剛好已經在畫面上就選它。
    const devices: ProductSerial[] = await findDevicesByCode(code);
    // 查的這段時間換了調出分店:這個碼是照舊分店刷的,不要了
    if (!live(ctx)) return true;
    if (devices.length === 0) return false;
    if (devices.length > 1) {
      return `對到 ${devices.length} 台,先到庫存查清楚是哪一台`;
    }
    const d = devices[0];
    if (d.status !== "in_stock" || d.warehouse !== ctx.warehouse) {
      const where =
        d.status === "in_stock"
          ? `在${storeName(d.warehouse) || d.warehouse_code || "別的分店"}`
          : d.status_label;
      return `${d.product_name} ${where},不在調出分店`;
    }
    // 畫面上已經有這一台 → 直接選起來
    const shown = linesRef.current.find((l) =>
      l.units?.some((u) => u.id === d.id),
    );
    if (shown) return pickUnit(shown.key, d.id) ?? true;
    const problem = await addProduct(
      {
        id: d.product,
        sku: d.product_sku,
        name: d.product_name,
        requiresSerial: true,
      },
      ctx,
      { via: "enter", pickSerial: d.id },
    );
    return problem ?? true;
  }

  async function search(q: string): Promise<ScanOption<Product>[]> {
    const ctx = ctxNow();
    if (!ctx) return [];
    const found = await searchProducts(q, {
      activeOnly: true,
      inStockOnly: true,
      warehouseId: ctx.warehouse,
    });
    // 查的時候換了調出分店:這份結果是舊分店的庫存
    if (!live(ctx)) return [];
    const out: ScanOption<Product>[] = [];
    for (const o of found) {
      const p = o.payload;
      if (!p || p.is_virtual) continue;
      out.push({
        key: p.id,
        code: p.sku,
        label: p.name,
        hint: `可調 ${p.stock_qty}`,
        payload: p,
      });
    }
    return out;
  }

  /** 把下拉 / 掃碼選到的商品加進明細。回一句話 = 沒加成(會留在「沒加入」) */
  async function onPick(
    o: ScanOption<Product>,
    via: "enter" | "mouse",
  ): Promise<string | null> {
    const ctx = ctxNow();
    if (!ctx) return "先選調出分店";
    return addProduct(
      {
        id: o.payload.id,
        sku: o.payload.sku,
        name: o.payload.name,
        requiresSerial: o.payload.requires_serial,
        avail: o.payload.stock_qty,
      },
      ctx,
      { via },
    );
  }

  // 整張調撥:從進貨單頁按過來(?from_po=編號),把那張單還留在進貨門市的東西一次帶好,
  // 選好調入分店就能確認。已經賣掉 / 調走的自動略過,並講出來。
  useEffect(() => {
    if (!fromPo) return;
    let alive = true;
    setPoLoading(true);
    api<PurchaseTransferable>(`/purchase-orders/${fromPo}/transferable/`)
      .then((d) => {
        if (!alive) return;
        switchFrom(d.warehouse);
        const ctx: Ctx = { warehouse: d.warehouse, gen: genRef.current };
        setTo((cur) => (cur === d.warehouse ? "" : cur));
        setNote(`進貨單 ${d.no} 整張調撥`);
        const prefilled: Line[] = d.lines
          .filter((l) => l.qty > 0)
          .map((l) => ({
            key: crypto.randomUUID(),
            warehouse: d.warehouse,
            product: l.product,
            sku: l.product_sku,
            name: l.product_name,
            requiresSerial: l.requires_serial,
            units: l.requires_serial ? l.serials.map(toUnit) : [],
            picked: l.requires_serial ? l.serials.map((s) => s.id) : [],
            avail: null,
            qty: l.requires_serial ? l.serials.length : l.qty,
            error: null,
            flash: 0,
          }));
        commit(() => prefilled);
        const notes: string[] = [];
        for (const l of d.lines) {
          if (l.requires_serial && l.gone.length > 0) {
            notes.push(
              `${l.product_name} ${l.gone.length} 台(${l.gone
                .map((g) => `${g.serial_no} ${g.status_label}`)
                .join("、")})`,
            );
          } else if (!l.requires_serial && l.qty < l.purchased) {
            notes.push(`${l.product_name} 進 ${l.purchased} 現有 ${l.qty}`);
          }
        }
        setSkipped(
          prefilled.length === 0
            ? "這張進貨單的東西都不在進貨門市了"
            : notes.length > 0
              ? `已略過:${notes.join(";")}`
              : null,
        );
        setPoLoading(false);
        // 同一個商品在進貨門市的其他台也列出來,要換一台可以直接點;
        // 配件補上進貨門市現在有幾個(查不到就不顯示,能不能調由存檔時檢查)
        for (const l of prefilled) {
          if (l.requiresSerial) {
            void loadUnits(l.key, l.product, ctx, false, true);
          } else {
            api<Product>(`/products/${l.product}/?warehouse=${d.warehouse}`)
              .then((prod) => {
                if (!live(ctx)) return;
                patch(l.key, (x) => ({ ...x, avail: prod.stock_qty }));
              })
              .catch(() => undefined);
          }
        }
      })
      .catch((e) => {
        if (!alive) return;
        setError(apiErrorText(e));
        setPoLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromPo]);

  // 調入分店被整張調撥清掉時(剛好等於進貨門市),補另一家
  useEffect(() => {
    if (to !== "" || from === "" || stores.length === 0) return;
    const other = stores.find((s) => s.id !== from);
    if (other) setTo(other.id);
  }, [to, from, stores]);

  function validate(): string | null {
    const warehouse = fromRef.current;
    if (warehouse === "" || to === "") return "請選調出與調入分店";
    if (warehouse === to) return "調出與調入分店不能相同";
    const ls = linesRef.current;
    if (ls.length === 0) return "請至少掃一筆商品";
    for (const l of ls) {
      if (l.warehouse !== warehouse) {
        return `「${l.name}」不是這家調出分店的明細,請移除重掃`;
      }
      if (l.error) return `「${l.name}」${l.error}`;
      if (l.requiresSerial) {
        if (l.units === null) return "序號還在載入,稍等一下再按";
        if (l.picked.length === 0) return `「${l.name}」請選要調的序號`;
      } else {
        if (!(l.qty > 0)) return `「${l.name}」數量要大於 0`;
        if (l.avail != null && l.qty > l.avail) {
          return `「${l.name}」可調數量只有 ${l.avail}`;
        }
      }
    }
    return null;
  }

  /** 單已經成立之後畫面該做的事(正常成功、或連線中斷後回頭認出來,都走這裡) */
  async function afterCreated(
    created: TransferOrder,
    sent: Set<string>,
    wantConfirm: boolean,
  ) {
    // 只拿掉送出去的那幾行:送出這段時間才處理完的碼還留著
    commit((ls) => ls.filter((l) => !sent.has(l.key)));
    setNote("");
    setDocDate(today());
    setSkipped(null);
    setUnsure(false);
    setNewId(created.id);
    setExpanded(null);
    const alreadyIn = created.status === "confirmed";
    if (wantConfirm && !alreadyIn) {
      try {
        await confirmMutation.mutateAsync(created.id);
        toast(`${created.no} 已調撥並入庫`, "ok", { ms: 4000 });
      } catch (e) {
        let landed = false;
        const offline = !refused(e);
        if (offline) {
          // 連線中斷:入庫可能其實成功了,回頭看一次這張單現在的狀態
          try {
            const now = await api<TransferOrder>(
              `/transfer-orders/${created.id}/`,
            );
            landed = now.status === "confirmed" && !now.is_void;
          } catch {
            /* 還是連不上 */
          }
          void recentQ.refetch();
          void pendingQ.refetch();
        }
        if (landed) {
          toast(`${created.no} 已調撥並入庫`, "ok", { ms: 4000 });
        } else {
          // 單已經成立、東西已經離開調出分店:要留在畫面上講清楚,不然會被當成整筆沒成功再做一次
          const text = offline
            ? `${created.no} 已送出;入庫那一步連線中斷,不確定有沒有入庫。不用重做,看下面那一列:還是待入庫就按「入庫」。`
            : `${created.no} 已送出、還沒入庫(${apiErrorText(e)})。不用重做,到下面那一列按「入庫」。`;
          setNotices((cur) => [
            ...cur.filter((n) => n.id !== created.id),
            { id: created.id, text },
          ]);
          // 不管清單現在篩哪一天,這一張都要看得到
          setPinnedId(created.id);
          setExpanded(created.id);
        }
      }
    } else {
      toast(
        alreadyIn
          ? `${created.no} 已調撥並入庫`
          : `${created.no} 已送出,等${storeName(created.to_warehouse)}入庫`,
        "ok",
        { ms: 4000 },
      );
    }
    if (linesRef.current.length > 0) {
      toast(`送出時才加進來的 ${linesRef.current.length} 筆還留在明細`, "");
    }
    if (fromPo || focusId) navigate("/transfers", { replace: true });
  }

  async function submit() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      // 剛刷的碼可能還在查。等它們全部處理完(加進明細,或記到「沒加入」)才定要送的內容:
      // 不然那個碼會在這張單送出去之後才冒出來,單上少一筆,人還不知道。
      await scanApi.current?.idle();
      // 刷了 / 打了卻沒進明細的東西還在(沒加入那一排、或還留在輸入框裡):不能就這樣送
      const blocker = scanApi.current?.blocker();
      if (blocker) {
        toast(blocker, "err", { ms: 6000 });
        return;
      }
      const problem = validate();
      if (problem) {
        toast(problem, "err");
        return;
      }
      // 畫面上新的在最上面;單據照加入的先後排
      const ordered = [...linesRef.current].reverse();
      const sent = new Set(ordered.map((l) => l.key));
      const sentFrom = fromRef.current as number;
      const sentTo = to as number;
      const wantConfirm = direct && !me.locked;
      const startedAt = Date.now();
      sending.current = true;
      let created: TransferOrder;
      try {
        created = await createMutation.mutateAsync({
          from_warehouse: sentFrom,
          to_warehouse: sentTo,
          doc_date: docDate,
          note,
          items: ordered.map((l, idx) => ({
            line_no: idx + 1,
            product: l.product,
            qty: lineQty(l),
            note: "",
            serial_ids: l.requiresSerial ? l.picked : [],
          })),
        } as Parameters<typeof createMutation.mutateAsync>[0]);
      } catch (e) {
        if (refused(e)) {
          // 伺服器明講不行:單沒有成立,可以改一改再送
          setUnsure(false);
          setError(apiErrorText(e));
          return;
        }
        // 連線在途中斷掉:單可能其實已經成立。回頭找找看有沒有一模一樣、剛剛才建的那一張。
        let found: TransferOrder | undefined;
        let looked = false;
        try {
          const recent = await api<Paginated<TransferOrder>>(
            `/transfer-orders/?from_warehouse=${sentFrom}&to_warehouse=${sentTo}&ordering=-created_at`,
          );
          looked = true;
          found = recent.results.find((t) =>
            sameOrder(t, sentFrom, sentTo, ordered, startedAt),
          );
        } catch {
          /* 還是連不上 */
        }
        void recentQ.refetch();
        void pendingQ.refetch();
        if (found) {
          await afterCreated(found, sent, wantConfirm);
          return;
        }
        setUnsure(true);
        setError(
          looked
            ? "連線中斷。下面的最近調撥沒有看到這一張,多半沒送出去;確定沒有再送一次。"
            : "連線中斷,不確定這一張有沒有送出去。等連線恢復先看下面的最近調撥:有這一張就按取消,不要再送。",
        );
        return;
      }
      await afterCreated(created, sent, wantConfirm);
    } catch (e) {
      setError(apiErrorText(e));
    } finally {
      sending.current = false;
      submitting.current = false;
      setBusy(false);
      scanRef.current?.focus();
    }
  }

  function cancel() {
    if (submitting.current) return;
    const keptNote = note;
    setNote("");
    clearLines("已清空明細", () => setNote(keptNote));
    setError(null);
    setSkipped(null);
    setUnsure(false);
    scanRef.current?.focus();
  }

  // ── 最近調撥 ─────────────────────────────────────────
  const recentQ = useTransferOrders({
    status: onlyPending ? "dispatched" : undefined,
    doc_date_gte: day || undefined,
    doc_date_lte: day || undefined,
  });
  // 待入庫的張數不受上面的篩選影響
  const pendingQ = useTransferOrders({ status: "dispatched" });
  const pendingCount = (pendingQ.data ?? []).filter((t) => !t.is_void).length;
  // 從別頁指定的那一張,或剛才入庫沒成功的那一張:不在清單裡也要列出來
  const focusQ = useTransferOrder(focusId ?? pinnedId);

  useEffect(() => {
    if (focusId) setExpanded(focusId);
  }, [focusId]);

  const allRows = useMemo(() => {
    let rows: TransferOrder[] = recentQ.data ?? [];
    if (onlyPending) rows = rows.filter((t) => !t.is_void);
    const focused = focusQ.data;
    if (focused && !rows.some((t) => t.id === focused.id)) {
      rows = [focused, ...rows];
    }
    return rows;
  }, [recentQ.data, focusQ.data, onlyPending]);
  const SHORT = 12;
  const rows =
    showAll || onlyPending || day ? allRows : allRows.slice(0, SHORT);

  const focusShown = !!focusId && allRows.some((t) => t.id === focusId);
  useEffect(() => {
    if (!focusShown) return;
    document
      .getElementById(`xfer-${focusId}`)
      ?.scrollIntoView({ block: "center" });
    // 只在那一張第一次出現時捲過去
  }, [focusId, focusShown]);

  /** 說明講的那一張已經處理掉了(入庫 / 作廢),或人按了知道了:把那一則收掉 */
  function settle(orderId: number) {
    setNotices((cur) => cur.filter((n) => n.id !== orderId));
    setPinnedId((cur) => (cur === orderId ? null : cur));
  }
  // 那一張在別的地方被入庫 / 作廢了(清單重新整理後看得出來)也一樣收掉
  const settledIds = notices
    .map((n) => allRows.find((t) => t.id === n.id))
    .filter((t) => !!t && (t.is_void || t.status === "confirmed"))
    .map((t) => (t as TransferOrder).id)
    .join(",");
  useEffect(() => {
    if (!settledIds) return;
    for (const sid of settledIds.split(",")) settle(Number(sid));
  }, [settledIds]);

  async function confirmOrder(t: TransferOrder) {
    try {
      await confirmMutation.mutateAsync(t.id);
      settle(t.id);
      toast(`${t.no} 已入庫`, "ok");
    } catch (e) {
      toast(apiErrorText(e), "err", { ms: 8000 });
    }
  }
  async function voidOrder(t: TransferOrder) {
    try {
      await voidMutation.mutateAsync(t.id);
      settle(t.id);
      toast(`${t.no} 已作廢`, "ok");
    } catch (e) {
      toast(apiErrorText(e), "err", { ms: 8000 });
    }
  }

  const totalQty = lines.reduce((sum, l) => sum + lineQty(l), 0);
  const toStores = stores.filter((s) => s.id !== from);
  const willConfirm = direct && !me.locked;
  /** 送出中、整張調撥還在帶入:會改到這張單的東西全部鎖住 */
  const locked = busy || poLoading;

  function statusBadge(t: TransferOrder) {
    if (t.is_void) return <span className="wb-badge">已作廢</span>;
    if (t.status === "dispatched") {
      const waited = daysSince(t.created_at);
      return (
        <span className="wb-badge warn">
          待入庫{waited >= 1 ? ` · ${waited} 天` : ""}
        </span>
      );
    }
    return <span className="wb-badge ok">已入庫</span>;
  }
  function rowActions(t: TransferOrder) {
    const pending = t.status === "dispatched" && !t.is_void;
    if (!pending) return null;
    const canConfirm = !me.locked || t.to_warehouse === me.id;
    return (
      <>
        {canConfirm && (
          <ArmButton
            label="入庫"
            className="wb-btn go small"
            onConfirm={() => confirmOrder(t)}
          />
        )}{" "}
        <ArmButton
          label="作廢"
          className="wb-btn danger small"
          onConfirm={() => voidOrder(t)}
        />
      </>
    );
  }
  function orderDetail(t: TransferOrder) {
    const pending = t.status === "dispatched" && !t.is_void;
    return (
      <>
        <table className="wb-detail-lines">
          <tbody>
            {t.items.map((it) => (
              <tr key={it.id}>
                <td className="wb-dim">{it.product_sku}</td>
                <td>{it.product_name}</td>
                <td className="num">×{it.qty}</td>
                <td className="wb-mono wb-small wb-dim">
                  {it.serials.map((s) => s.serial_no).join("  ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!t.is_void && !pending && (
          <div className="wb-detail-actions">
            <ArmButton
              label="作廢"
              className="wb-btn danger small"
              title="把已經調過去的東西退回調出分店"
              onConfirm={() => voidOrder(t)}
            />
          </div>
        )}
      </>
    );
  }

  return (
    <div className="wb">
      <div className="wb-card">
        <div className="wb-row">
          <div className="wb-field">
            <label>調出分店</label>
            <select
              value={from}
              disabled={me.locked || stores.length === 0 || locked}
              title={me.locked ? "這個帳號只能從自己的分店調出" : undefined}
              onChange={(e) => changeFrom(Number(e.target.value))}
            >
              {from === "" && <option value="">請選擇</option>}
              {stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          {!me.locked && (
            <button
              type="button"
              className="wb-btn icon"
              title="調出、調入對調"
              disabled={locked}
              onClick={swap}
            >
              ⇄
            </button>
          )}
          <div className="wb-field">
            <label>調入分店</label>
            <select
              value={to}
              disabled={stores.length === 0 || locked}
              onChange={(e) => changeTo(Number(e.target.value))}
            >
              {to === "" && <option value="">請選擇</option>}
              {toStores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="wb-field">
            <label>調撥日期</label>
            <input
              type="date"
              value={docDate}
              disabled={locked}
              onChange={(e) => setDocDate(e.target.value)}
            />
          </div>
          <div className="wb-field grow">
            <label>備註</label>
            <input
              value={note}
              maxLength={200}
              disabled={locked}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
        </div>
        <div className="wb-row scanrow">
          <div className="wb-field grow">
            <label>連續掃描</label>
            <ScanBox<Product>
              inputRef={scanRef}
              autoFocus
              placeholder="掃品號 / 條碼 / IMEI,或打品名"
              disabled={from === "" || poLoading || busy}
              resetKey={from === "" ? 0 : from}
              apiRef={scanApi}
              search={search}
              onScan={onScan}
              isExact={(o, q) => {
                const nv = normalizeCode(q);
                return (
                  normalizeCode(o.payload.sku) === nv ||
                  (!!o.payload.barcode && normalizeCode(o.payload.barcode) === nv)
                );
              }}
              onPick={onPick}
            />
          </div>
          <div className="wb-total">
            <span className="wb-label">合計 {lines.length} 項</span>
            <b>{totalQty}</b>
          </div>
          {!me.locked && (
            <label
              className="wb-check"
              title="打勾:確認後直接進調入分店的庫存,不用對方再按入庫"
            >
              <input
                type="checkbox"
                checked={direct}
                disabled={locked}
                onChange={(e) => {
                  setDirect(e.target.checked);
                  remember(K_DIRECT, e.target.checked ? "1" : "0");
                }}
              />
              直接入庫
            </label>
          )}
          <button
            type="button"
            className="wb-btn"
            onClick={cancel}
            disabled={locked}
          >
            取消
          </button>
          {unsure ? (
            <ArmButton
              label="再送一次"
              armedLabel="確定再送"
              className="wb-btn go"
              disabled={locked}
              onConfirm={submit}
            />
          ) : (
            <button
              type="button"
              className="wb-btn go"
              onClick={submit}
              disabled={locked}
            >
              {willConfirm ? "確認並入庫" : "確認"}
            </button>
          )}
        </div>
        {notices.map((n) => (
          <div key={n.id} className="wb-warn err wb-inv-hit">
            <span>{n.text}</span>
            <button
              type="button"
              className="wb-link"
              onClick={() => settle(n.id)}
            >
              知道了
            </button>
          </div>
        ))}
        {error && <div className="wb-warn err">{error}</div>}
        {skipped && <div className="wb-warn">{skipped}</div>}
      </div>

      <table className="wb-table wb-lines" style={{ marginTop: 12 }}>
        <thead>
          <tr>
            <th className="prod">商品</th>
            <th className="num" style={{ width: 90 }}>
              數量
            </th>
            <th style={{ width: 44 }}></th>
            <th className="fill">序號(後 6 碼,點選或掃 IMEI)</th>
          </tr>
        </thead>
        <tbody>
          {lines.length === 0 && (
            <tr>
              <td colSpan={4} className="empty">
                {poLoading ? "載入中…" : "掃條碼,或打品名加入商品"}
              </td>
            </tr>
          )}
          {lines.map((l) => {
            const over = !l.requiresSerial && l.avail != null && l.qty > l.avail;
            const tails = l.units ? tailsOf(l.units) : null;
            return (
              <tr key={`${l.key}:${l.flash}`} className="flash">
                <td className="prod">
                  <span className="pname">{l.name}</span>
                  <span className="pcode">{l.sku}</span>
                </td>
                <td className="num">
                  {l.requiresSerial ? (
                    <input
                      className="qty num"
                      value={l.picked.length}
                      readOnly
                      tabIndex={-1}
                    />
                  ) : (
                    <input
                      type="number"
                      className={`qty num${over ? " bad" : ""}`}
                      min={1}
                      max={l.avail ?? undefined}
                      disabled={busy}
                      value={l.qty || ""}
                      onChange={(e) =>
                        patch(l.key, (x) => ({
                          ...x,
                          qty: Math.max(0, Math.floor(Number(e.target.value) || 0)),
                        }))
                      }
                    />
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    className="wb-x"
                    title="移除"
                    disabled={busy}
                    onClick={() => removeLine(l.key)}
                  >
                    ✕
                  </button>
                </td>
                <td className="fill">
                  {l.error ? (
                    <span className="wb-badge bad">{l.error}</span>
                  ) : !l.requiresSerial ? (
                    <span className="wb-dim wb-small">
                      無序號{l.avail != null ? ` · 可調 ${l.avail}` : ""}
                    </span>
                  ) : l.units === null || tails === null ? (
                    <span className="wb-dim wb-small">載入中…</span>
                  ) : l.units.length === 0 ? (
                    <span className="wb-badge bad">調出分店沒有在庫</span>
                  ) : (
                    <div className="wb-chips">
                      {l.units.map((u) => (
                        <button
                          type="button"
                          key={u.id}
                          className={`wb-chip${l.picked.includes(u.id) ? " on" : ""}`}
                          title={codesLabel(u)}
                          disabled={busy}
                          onClick={() => toggleUnit(l.key, u.id)}
                        >
                          {tails.get(u.id)}
                        </button>
                      ))}
                      <span className="wb-chip-count">
                        {l.picked.length}/{l.units.length}
                      </span>
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="wb-section">
        <h3>最近調撥</h3>
        <label className="wb-check" style={{ paddingBottom: 0 }}>
          <input
            type="checkbox"
            checked={onlyPending}
            onChange={(e) => setOnlyPending(e.target.checked)}
          />
          只看待入庫
          {pendingCount > 0 && (
            <span className="wb-badge warn">{pendingCount}</span>
          )}
        </label>
        <input
          type="date"
          value={day}
          title="只看這一天"
          onChange={(e) => setDay(e.target.value)}
        />
        {day && (
          <button
            type="button"
            className="wb-btn small"
            onClick={() => setDay("")}
          >
            全部日期
          </button>
        )}
      </div>

      {recentQ.isError && (
        <div className="wb-warn err">
          載入失敗:{apiErrorText(recentQ.error)}
        </div>
      )}

      {/* 手機:一張單一張卡,入庫 / 作廢直接在卡上(表格要橫向捲才按得到) */}
      {isMobile && !recentQ.isError && (
        <div className="wb-inv-cards">
          {recentQ.isLoading && <div className="wb-card wb-dim">載入中…</div>}
          {!recentQ.isLoading && rows.length === 0 && (
            <div className="wb-card wb-dim">
              {onlyPending ? "沒有待入庫的調撥單" : "還沒有調撥單"}
            </div>
          )}
          {rows.map((t) => {
            const open = expanded === t.id;
            return (
              <div
                key={t.id}
                id={`xfer-${t.id}`}
                className="wb-card wb-inv-card"
                onClick={() => setExpanded(open ? null : t.id)}
              >
                <div className="wb-xfer-card-head">
                  <span className={t.is_void ? "wb-dim" : "pname"}>{t.no}</span>
                  {statusBadge(t)}
                  <span className="wb-dim wb-small">
                    {t.doc_date.slice(5)} {clock(t.created_at)}
                  </span>
                </div>
                <div>
                  {t.from_warehouse_name} → {t.to_warehouse_name}
                  <span className="wb-dim"> · {t.items.length} 項</span>
                </div>
                {t.note && <div className="wb-dim wb-small">{t.note}</div>}
                {rowActions(t) && (
                  <div className="wb-detail-actions">{rowActions(t)}</div>
                )}
                {open && (
                  <div className="wb-inv-card-detail">{orderDetail(t)}</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!isMobile && !recentQ.isError && (
        <table className="wb-table">
          <thead>
            <tr>
              <th>單號</th>
              <th>時間</th>
              <th>調出</th>
              <th>調入</th>
              <th className="num">項數</th>
              <th>狀態</th>
              <th>備註</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {recentQ.isLoading && (
              <tr>
                <td colSpan={8} className="empty">
                  載入中…
                </td>
              </tr>
            )}
            {!recentQ.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">
                  {onlyPending ? "沒有待入庫的調撥單" : "還沒有調撥單"}
                </td>
              </tr>
            )}
            {rows.map((t) => {
              const open = expanded === t.id;
              return (
                <Fragment key={t.id}>
                  <tr
                    id={`xfer-${t.id}`}
                    className={`clickable${t.is_void ? " void" : ""}${
                      newId === t.id ? " flash" : ""
                    }`}
                    onClick={() => setExpanded(open ? null : t.id)}
                  >
                    <td>{t.no}</td>
                    <td className="wb-small">
                      {t.doc_date.slice(5)} {clock(t.created_at)}
                    </td>
                    <td>{t.from_warehouse_name}</td>
                    <td>{t.to_warehouse_name}</td>
                    <td className="num">{t.items.length}</td>
                    <td className="keep">{statusBadge(t)}</td>
                    <td className="wb-dim wb-small">{t.note}</td>
                    <td
                      className="keep"
                      style={{ whiteSpace: "nowrap", textAlign: "right" }}
                    >
                      {rowActions(t)}
                    </td>
                  </tr>
                  {open && (
                    <tr className="detail">
                      <td colSpan={8}>{orderDetail(t)}</td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {!showAll && !onlyPending && !day && allRows.length > SHORT && (
        <div style={{ marginTop: 8, textAlign: "center" }}>
          <button
            type="button"
            className="wb-btn small"
            onClick={() => setShowAll(true)}
          >
            看更多
          </button>
        </div>
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { useStockCount, useStockCountDo } from "@/api/hooks";
import type { Product } from "@/api/types";
import { searchProducts } from "@/api/search";
import { useCan } from "@/auth/AuthContext";
import { Banner, errorMessageOf } from "@/components/Banner";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { MoneyInput } from "@/components/MoneyInput";
import { usePhotoPeek } from "@/components/photos/PhotoName";
import { Toolbar } from "@/components/Toolbar";
import { GroupCheckbox, Tabs } from "@/components/ui";
import { ArmButton } from "@/components/workbench/ArmButton";
import { ScanBox, type ScanBoxApi, type ScanOption, type ScanVerdict } from "@/components/workbench/ScanBox";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { rememberCode } from "@/components/rememberBarcode";
import { isNegative } from "@/lib/fixedReports";
import { tripBox, tripSettles } from "@/lib/purchasePrefill";
import type { Missed } from "@/lib/scanMissed";
import { FindFirstPanel } from "@/pages/products/FindFirstPanel";
import { ProductForm } from "@/pages/products/ProductForm";
import { qrMatrix, qrPath } from "@/lib/qr";
import { money } from "@/lib/money";
import {
  amountCards,
  approveBody,
  assignProduct,
  countedQty,
  countTabs,
  currentTab,
  extraText,
  missingText,
  movedHint,
  newEditOf,
  newGroups,
  newestFirst,
  newResult,
  notCountable,
  phoneCountUrl,
  pairedText,
  PHONE_STALE_MS,
  phoneStatusText,
  phonesDoneText,
  phonesLive,
  pickProblem,
  progressText,
  recordedQty,
  sameCode,
  scopeText,
  signed,
  type CountTab,
  type CountUnknown,
  type LineEdit,
  type MissingEdit,
  type NewEdit,
} from "@/lib/stockCount";

/** 手機盤點的 QR Code(手機相機一掃就開 /m/count#憑證) */
function PairQr({ text }: { text: string }) {
  const m = qrMatrix(text);
  return (
    <svg className="ph-qr" viewBox={`0 0 ${m.length} ${m.length}`} role="img" aria-label="手機盤點 QR Code" shapeRendering="crispEdges">
      <rect width={m.length} height={m.length} fill="#fff" />
      <path d={qrPath(m)} fill="#000" />
    </svg>
  );
}

/**
 * 一張盤點單。盤點中:配件輸入數到的數量、手機逐台刷,送出。
 * 配件那一格是工作台的掃碼框:條碼槍刷舊貼紙(舊品號 = 條碼)完全相同才直接選,選好游標跳到數量;刷了沒選到的記在「沒加入」,送出前要處理掉。
 * 手機走動盤點(2026-10-15):「手機盤點」寫稱呼、產生 QR Code(一支手機一個);手機刷進來的數量每 4 秒重抓。
 * 打「數到幾個」存的時候一起送選到那一刻看到的數字,手機在那之後又加過就擋下來、照最新的重新帶(紅隊:不能默默蓋掉手機加的)。
 * 手機刷到、系統不認得的碼列在「沒對到的碼」:指定配件(刷了幾次就加幾個)或寫原因不入,處理好才能送出。
 * 待核准:管理員看差異(帳上、數到、差多少、金額),每一列可以改調整量或先不調,核准才動庫存。
 * 帳上數量、差異、金額只有管理員的回應裡有;盤的人的畫面沒有那幾欄(伺服器沒給)。
 * 系統不認得的碼(第一次盤點入庫):管理員照舊品名分組勾、指定品號,填成本(舊系統的先帶出來)才入庫;沒指定的不入。
 */
export function StockCountPage() {
  const id = Number(useParams().id);
  const { data: detail, isLoading, error, refetch, dataUpdatedAt } = useStockCount(id);
  const run = useStockCountDo(id);
  /** 配件那一格選到、還沒記下的商品。另外留一份當下的(`accessoryNow`):掃碼框排隊處理完、送出前要馬上讀,不能等畫面重畫(複審 P1) */
  const [accessory, setAccessoryState] = useState<Product | null>(null);
  const accessoryNow = useRef<Product | null>(null);
  const setAccessory = (p: Product | null) => {
    accessoryNow.current = p;
    setAccessoryState(p);
  };
  const [qty, setQty] = useState("");
  /** 選到配件那一刻,這張單上它數到幾個(null = 還沒有這一列):存的時候一起送,手機在那之後又加過就擋下來(紅隊) */
  const seenQty = useRef<number | null>(null);
  const [phonesDone, setPhonesDone] = useState(false);
  // 手機走動盤點:發 QR Code 的那一塊
  const [phoneOpen, setPhoneOpen] = useState(false);
  const [phoneLabel, setPhoneLabel] = useState("");
  const [pair, setPair] = useState<{ id: number; label: string; token: string } | null>(null);
  // 剛發的 QR Code 被手機掃了 → 收起來,只留「已配對 N 台」(全站檢視 V06b,紅隊:沒配上之前 QR 照開)
  const pairStatus = pair ? detail?.phones?.find((p) => p.id === pair.id)?.status : undefined;
  useEffect(() => {
    if (pairStatus !== "connected") return;
    setPhoneOpen(false);
    setPair(null);
  }, [pairStatus]);
  // 有手機在盤:每 5 秒看一次上次抓到盤點單是多久以前,抓不到了就不沿用舊的「已配對 N 台」(紅隊)
  const live = phonesLive(detail);
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => setClock(Date.now()), 5000);
    return () => window.clearInterval(t);
  }, [live]);
  const stale = live && clock - dataUpdatedAt > PHONE_STALE_MS;
  const paired = pairedText(detail?.phones, stale);
  // 沒對到的碼:每一筆要指定的配件、不入的原因
  const [unknownPick, setUnknownPick] = useState<Record<number, ComboOption<Product> | undefined>>({});
  const [unknownReason, setUnknownReason] = useState<Record<number, string>>({});
  const [lineEdits, setLineEdits] = useState<Record<number, LineEdit | undefined>>({});
  const [missingEdits, setMissingEdits] = useState<Record<number, MissingEdit | undefined>>({});
  const [newEdits, setNewEdits] = useState<Record<number, NewEdit | undefined>>({});
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [assignTo, setAssignTo] = useState<{ id: number | ""; option: ComboOption<Product> | null }>({ id: "", option: null });
  const [note, setNote] = useState("");
  /** 看哪一張表(一次只顯示一張;人沒選過 = 第一個有東西的) */
  const [tab, setTab] = useState<CountTab | null>(null);
  const scanRef = useRef<HTMLInputElement>(null);
  const qtyRef = useRef<HTMLInputElement>(null);
  const scanApi = useRef<ScanBoxApi | null>(null);
  /** 手機那一格的掃碼框(只收碼;見下面 scanPhone) */
  const phoneApi = useRef<ScanBoxApi | null>(null);
  /**
   * 刷到系統還沒有的配件(全站檢視 B3;10-14 owner「盤點時多出來的當場建」):
   * 有商品建檔權限的 → 「建立」:先找有沒有建過 → 用那一款 / 建新的 → 選起來、游標到數量(跟進貨單同一套)。
   * 沒有的 → 「先記下」:打數量記成沒對到的碼,有權限的人在「沒對到碼」指定 / 建立(紅隊:不讓現場店員建主檔,也不讓那個碼卡住整張單)。
   */
  const canBuild = useCan("edit_products");
  const canRemember = useCan("remember_barcode");
  const trip = useRef(tripBox<Missed>()).current;
  /** 從「沒對到碼」那一列按的「建立」:找到 / 建好的指定給那一筆(不是選起來打數量) */
  const unknownTarget = useRef<number | null>(null);
  const [finding, setFinding] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [formUsed, setFormUsed] = useState(false);
  const [formPrefill, setFormPrefill] = useState<{ name: string; barcode: string } | null>(null);
  const [noting, setNotingState] = useState<{ kw: string; entry: Missed | null } | null>(null);
  const notingNow = useRef<{ kw: string; entry: Missed | null } | null>(null);
  const setNoting = (n: { kw: string; entry: Missed | null } | null) => {
    notingNow.current = n;
    setNotingState(n);
  };
  /** 同一次記錄只送一次(複審 P0:先記下是累加的,回應回來之前連按兩次 Enter 會記兩次) */
  const saving = useRef(false);
  const overlay = useRef(false);
  overlay.current = finding !== null || formOpen;
  const peek = usePhotoPeek(() => {
    if (!overlay.current) scanApi.current?.resume();
  });
  // 選到配件(或先記下的碼):游標到數量、整格反白(這張單記過的話先放原本的數量,直接打就換掉)
  useEffect(() => {
    if (!accessory && !noting) return;
    qtyRef.current?.focus();
    qtyRef.current?.select();
  }, [accessory, noting]);

  if (isLoading) return <div className="page"><div className="md-empty">載入中…</div></div>;
  // 重抓失敗(手機在盤時每 4 秒抓一次,斷一下網路就會)不換成整頁錯誤:畫面、打到一半的、沒加入的碼都留著,右上寫「連線中斷」(全站檢視 V06b)
  if (!detail) return <div className="page"><Banner kind="error" message={errorMessageOf(error)} /></div>;

  const counting = detail.status === "counting";
  const submitted = detail.status === "submitted";
  const approved = detail.status === "approved";
  const reviewing = detail.manager && submitted;
  const call = (path: string, body?: object, method: "POST" | "DELETE" = "POST") => {
    setNote("");
    return run.mutateAsync({ path, body, method }).catch(() => undefined);
  };

  /**
   * 手機那一格(全站檢視 B6):用工作台的掃碼框、只收碼 —— 刷完立刻清空、連刷照順序排隊;
   * 沒刷進去的(斷線、伺服器擋下)記在那一格底下的「沒加入」,不會留在框裡被下一槍接在後面。
   */
  async function scanPhone(kw: string): Promise<ScanVerdict> {
    try {
      await run.mutateAsync({ path: "scans/", body: { code: kw }, method: "POST" });
      // 剛刷的那一台在手機那一頁的最上面
      setTab("scans");
      return true;
    } catch (e) {
      return apiErrorText(e);
    }
  }

  async function saveLine() {
    if (saving.current) return;
    saving.current = true;
    try {
      await saveLineOnce();
    } finally {
      saving.current = false;
    }
  }
  async function saveLineOnce() {
    const noted = notingNow.current;
    if (noted) {
      const n = countedQty(qty);
      if (n === null || n < 1) {
        setNote("先打數量");
        return;
      }
      const done = await call("unknowns/", { code: noted.kw, qty: n });
      if (done) {
        scanApi.current?.added(noted.kw, noted.entry);
        setNoting(null);
        setQty("");
        setTab("unknowns");
        scanRef.current?.focus();
      }
      return;
    }
    const item = accessoryNow.current;
    if (!item) return;
    const n = countedQty(qty);
    if (n === null) {
      // 沒打數量就刷了下一張貼紙:那一串字進了數量這一格,沒有刷進去
      if (qty.trim()) {
        setNote(`先打數量,「${qty.trim()}」要再刷一次`);
        setQty("");
      }
      return;
    }
    const done = await call("lines/", { product: item.id, counted_qty: n, seen: seenQty.current });
    if (done) {
      setAccessory(null);
      setQty("");
      setTab("lines");
      scanRef.current?.focus();
      return;
    }
    // 沒存成(多半是手機剛加過):照最新的數字重新帶,人看過再按一次
    const fresh = (await refetch()).data;
    if (fresh && accessoryNow.current?.id === item.id) {
      seenQty.current = fresh.line_rows.find((r) => r.product.id === item.id)?.counted_qty ?? null;
      setQty(recordedQty(fresh.line_rows, item.id));
    }
  }

  async function newPhone() {
    const label = phoneLabel.trim();
    if (!label) {
      setNote("請寫這支手機是誰在用");
      return;
    }
    const done = await call("phones/", { label });
    if (done?.pair) {
      setPair({ id: done.pair.id, label: done.pair.label, token: done.pair.token });
      setPhoneLabel("");
    }
  }

  async function resolveUnknown(row: CountUnknown, skip: boolean) {
    const product = unknownPick[row.id]?.payload;
    const reason = (unknownReason[row.id] ?? "").trim();
    if (!skip && !product) return;
    if (skip && !reason) {
      setNote("不入要寫原因");
      return;
    }
    await call(`unknowns/${row.id}/`, skip ? { skip: true, reason } : { product: product!.id });
  }

  async function searchAccessories(q: string): Promise<ScanOption<Product>[]> {
    const found = await searchProducts(q, { activeOnly: true });
    return found.flatMap((o) => (o.payload ? [{ key: o.id, code: o.payload.sku, label: o.label, payload: o.payload }] : []));
  }

  function pickAccessory(o: ScanOption<Product>): string | null {
    const why = pickProblem(accessoryNow.current, o.payload);
    if (why) return why;
    setNote("");
    setAccessory(o.payload);
    seenQty.current = detail?.line_rows.find((r) => r.product.id === o.payload.id)?.counted_qty ?? null;
    setQty(detail ? recordedQty(detail.line_rows, o.payload.id) : "");
    return null;
  }

  /** 游標回刷碼格(選著配件 / 先記下的碼時留在數量那一格) */
  function focusScan() {
    window.setTimeout(() => {
      if (!accessoryNow.current && !notingNow.current) scanRef.current?.focus();
    }, 0);
  }

  /** 等掃碼框還在處理的碼做完;那一筆「沒加入」已經不在了(被加進去了)就不用做 */
  async function settled(entry: Missed | null): Promise<boolean> {
    await scanApi.current?.idle();
    return !entry || (scanApi.current?.missed() ?? []).some((m) => m.id === entry.id);
  }

  async function startCreate(kw: string, entry: Missed | null) {
    if (!(await settled(entry))) return;
    unknownTarget.current = null;
    trip.start(kw, entry);
    setFinding(kw);
  }

  async function startNote(kw: string, entry: Missed | null) {
    if (!(await settled(entry))) return;
    const pending = accessoryNow.current;
    if (pending) {
      setNote(`「${pending.name}」還沒記下`);
      return;
    }
    setNoting({ kw, entry });
    setQty("");
  }

  function createForUnknown(u: CountUnknown) {
    trip.drop();
    unknownTarget.current = u.id;
    setFinding(u.code);
  }

  /** 這一趟是誰開始的:在人按下去的那一刻就拿走(晚回來的查詢不能算到下一趟上;表單關掉時會清掉) */
  function capture() {
    const target = unknownTarget.current;
    unknownTarget.current = null;
    return { target, from: target === null ? trip.take() : null };
  }

  /** 找到 / 建好的配件:從「沒對到碼」來的指定給那一筆;從刷碼來的選起來打數量(跟從下拉挑到它一樣) */
  async function bring(p: Product, ctx = capture()) {
    const { target, from } = ctx;
    const why = notCountable(p);
    if (target !== null) {
      if (why) {
        toast(why, "err", { ms: 6000 });
        return;
      }
      await call(`unknowns/${target}/`, { product: p.id });
      setTab("unknowns");
      return;
    }
    if (!from) return;
    const problem = why ?? pickAccessory({ key: p.id, code: p.sku, label: p.name, payload: p });
    if (problem) {
      toast(problem, "err", { ms: 6000 });
      return;
    }
    if (tripSettles(from, p)) scanApi.current?.added(from.kw, from.entry);
  }

  async function submit() {
    // 等掃碼框排隊的碼處理完,再讀「現在」選著的(不是按下去那一刻畫面上的)
    await scanApi.current?.idle();
    await phoneApi.current?.idle();
    const pending = accessoryNow.current;
    const phoneLeft = phoneApi.current?.blocker();
    const blocked =
      scanApi.current?.blocker() ??
      (phoneLeft ? `手機那一格:${phoneLeft}` : null) ??
      (pending ? `「${pending.name}」還沒記下` : null);
    if (blocked) {
      setNote(blocked);
      return;
    }
    await call("submit/", { phones_done: phonesDone });
  }

  async function approve() {
    if (!detail) return;
    const body = approveBody(detail, lineEdits, missingEdits, newEdits);
    if ("error" in body) {
      setNote(body.error);
      return;
    }
    await call("approve/", body);
  }

  const tabs = countTabs(detail);
  const shown = currentTab(tabs, tab);
  const lineEdit = (rowId: number, diff: number): LineEdit => lineEdits[rowId] ?? { adjust: String(diff), skipped: false, reason: "" };
  const missingEdit = (rowId: number): MissingEdit => missingEdits[rowId] ?? { skipped: false, reason: "" };
  const newRows = detail.new_rows ?? [];
  const togglePick = (ids: number[], on: boolean) =>
    setPicked((old) => {
      const next = new Set(old);
      for (const one of ids) {
        if (on) next.add(one);
        else next.delete(one);
      }
      return next;
    });
  function assign() {
    const p = assignTo.option?.payload;
    if (!p) return;
    setNewEdits((all) => assignProduct(newRows, picked, { id: p.id, sku: p.sku, name: p.name, unit: !!p.tracks_unit_condition }, all));
    setPicked(new Set());
    setAssignTo({ id: "", option: null });
  }

  return (
    <div className="page sr-page">
      <Toolbar
        title={`盤點 ${detail.no}`}
        actions={
          <>
            <Link className="btn" to="/inventory/stocktake">
              返回
            </Link>
            {(counting || reviewing) && <ArmButton label="作廢" className="btn danger" onConfirm={() => call("void/")} />}
            {reviewing && <ArmButton label="退回" className="btn" onConfirm={() => call("return/")} />}
            {/* 送出時沒表明手機刷完:沒刷到的手機不算少。核准前再確認一次(紅隊) */}
            {reviewing && (
              <ArmButton label="核准" armedLabel={detail.phones_done ? undefined : "手機沒表明,再按一次核准"} className="btn primary" onConfirm={approve} />
            )}
          </>
        }
      />
      <div className="ex-period">
        {detail.warehouse.name}　{scopeText(detail)}　{detail.status_label}　{progressText(detail)}　{phonesDoneText(detail)}
      </div>
      {run.isError && <Banner kind="error" message={errorMessageOf(run.error)} />}
      {note && <Banner kind="error" message={note} />}

      {counting && (
        <div className="list-filterbar sr-filter">
          <label className="sc-phone-scan">
            手機
            <ScanBox<never>
              apiRef={phoneApi}
              menu={false}
              placeholder="刷序號"
              search={async () => []}
              onPick={() => undefined}
              onScan={scanPhone}
            />
          </label>
          <label>
            <input type="checkbox" checked={phonesDone} onChange={(e) => setPhonesDone(e.target.checked)} />
            手機全部刷完
          </label>
          {paired && <span className={stale ? "sc-paired stale" : "sc-paired"}>{paired}</span>}
          <button className="btn sc-phone-btn" type="button" aria-expanded={phoneOpen} onClick={() => setPhoneOpen((v) => !v)}>
            手機盤點
          </button>
        </div>
      )}
      {counting && phoneOpen && (
        <div className="list-filterbar sr-filter sc-phones">
          <label>
            稱呼
            <input type="text" value={phoneLabel} maxLength={20} placeholder="小王、櫃2" onChange={(e) => setPhoneLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void newPhone();
              }} />
          </label>
          <button className="btn" type="button" disabled={!phoneLabel.trim() || run.isPending} onClick={() => void newPhone()}>
            產生 QR Code
          </button>
          {pair && (detail.phones ?? []).some((p) => p.id === pair.id && p.status === "waiting") && (
            <div className="sc-qr">
              <PairQr text={phoneCountUrl(window.location.origin, pair.token)} />
              <span>{pair.label}</span>
            </div>
          )}
          {(detail.phones ?? []).map((p) => (
            <span key={p.id} className="sc-phone">
              {p.label} {phoneStatusText(p.status)}
              <button type="button" className="wb-link" onClick={() => void call(`phones/${p.id}/`, undefined, "DELETE")}>
                結束
              </button>
            </span>
          ))}
        </div>
      )}
      {counting && (
        <div className="list-filterbar sr-filter sc-scanrow">
          <label className="sc-scan">
            配件
            <ScanBox<Product>
              inputRef={scanRef}
              apiRef={scanApi}
              placeholder="品名 / 條碼"
              search={searchAccessories}
              isExact={(o, q) => sameCode(o.payload, q)}
              onPick={pickAccessory}
              onCreate={canBuild ? startCreate : startNote}
              createLabel={canBuild ? "建立" : "先記下"}
              createRowLabel={canBuild ? "建立商品" : "先記下這個碼"}
            />
          </label>
          {accessory && (
            <span className="sr-only-one">
              {accessory.sku} {accessory.name}
              <button type="button" aria-label="清掉" onClick={() => setAccessory(null)}>
                ×
              </button>
            </span>
          )}
          {noting && (
            <span className="sr-only-one">
              {noting.kw} 先記下
              <button type="button" aria-label="清掉" onClick={() => setNoting(null)}>
                ×
              </button>
            </span>
          )}
          <label>
            數量
            <input
              ref={qtyRef}
              type="text"
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void saveLine();
              }}
            />
          </label>
          <button className="btn" type="button" disabled={(!accessory && !noting) || countedQty(qty) === null || run.isPending} onClick={() => void saveLine()}>
            記下
          </button>
          <span className="sc-submit">
            {/* 沒勾「手機全部刷完」:沒刷到的手機不會算少(是沒盤)。只提醒、不擋 */}
            <ArmButton label="送出" armedLabel={phonesDone ? undefined : "手機沒勾刷完,仍可送出"} className="btn primary" onConfirm={submit} />
          </span>
        </div>
      )}

      {detail.manager && detail.amounts && (submitted || approved) && (
        <div className="sd-summary">
          {amountCards(detail.amounts).map((card) => (
            <div key={card.label} className="sd-summary-card">
              <div className="sd-summary-card-label">{card.label}</div>
              <div className="sd-summary-card-value">{card.value}</div>
            </div>
          ))}
        </div>
      )}

      {tabs.length > 0 && (
        <Tabs
          id="sc"
          label="盤點內容"
          className="sc-tabs"
          items={tabs.map((t) => ({ key: t.key, label: t.label, note: t.count > 0 ? t.count : undefined, noteTone: t.alert ? "alert" : undefined }))}
          value={shown ?? tabs[0].key}
          onChange={setTab}
        />
      )}
      <div
        className="report-table sr-table"
        role={shown ? "tabpanel" : undefined}
        id={shown ? `sc-panel-${shown}` : undefined}
        aria-labelledby={shown ? `sc-tab-${shown}` : undefined}
      >
        {shown === null && <div className="md-empty">還沒有盤任何東西</div>}
        {shown === "unknowns" && (
          <table className="report-grid sc-unknowns">
            <thead>
              <tr>
                <th>沒對到的碼</th>
                <th className="num">次數</th>
                <th>刷的人</th>
                <th>處理</th>
              </tr>
            </thead>
            <tbody>
              {(detail.unknown_rows ?? []).map((u) => (
                <tr key={u.id} className="report-row">
                  <td className="id-code">{u.code}</td>
                  <td className="num">{u.times}</td>
                  <td>{u.label}</td>
                  <td>
                    {u.resolved ? (
                      u.product ? `${u.product.sku} ${u.product.name}` : `不入:${u.reason}`
                    ) : counting ? (
                      <div className="sc-unknown-do">
                        <ComboBox<Product>
                          value={unknownPick[u.id]?.id ?? ""}
                          selectedOption={unknownPick[u.id] ?? null}
                          onChange={(_pid, opt) => setUnknownPick((all) => ({ ...all, [u.id]: opt ?? undefined }))}
                          fetchOptions={async (q) => (await searchProducts(q, { activeOnly: true })).filter((o) => o.payload && !o.payload.requires_serial && !o.payload.is_virtual)}
                          placeholder="品名 / 條碼"
                        />
                        <button className="btn" type="button" disabled={!unknownPick[u.id] || run.isPending} onClick={() => void resolveUnknown(u, false)}>
                          指定
                        </button>
                        {canBuild && (
                          <button className="btn" type="button" disabled={run.isPending} onClick={() => createForUnknown(u)}>
                            建立
                          </button>
                        )}
                        <input type="text" maxLength={100} placeholder="原因" value={unknownReason[u.id] ?? ""}
                          onChange={(e) => setUnknownReason((all) => ({ ...all, [u.id]: e.target.value }))} />
                        <button className="btn" type="button" disabled={!(unknownReason[u.id] ?? "").trim() || run.isPending} onClick={() => void resolveUnknown(u, true)}>
                          不入
                        </button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {shown === "lines" && (detail.line_rows.length === 0 ? (
          <div className="md-empty">還沒有記任何配件</div>
        ) : (
          <table className="report-grid">
            <thead>
              <tr>
                <th>品號</th>
                <th>品名</th>
                {detail.manager && <th className="num">帳上</th>}
                <th className="num">數到</th>
                {detail.manager && <th className="num">差異</th>}
                <th>異動</th>
                {detail.manager && <th className="num">金額</th>}
                {detail.manager && (submitted || approved) && <th className="num">調整</th>}
                {detail.manager && (submitted || approved) && <th>不調</th>}
                {detail.manager && (submitted || approved) && <th>原因</th>}
                {counting && <th />}
              </tr>
            </thead>
            <tbody>
              {newestFirst(detail.line_rows).map((r) => {
                const edit = lineEdit(r.id, r.diff ?? 0);
                const change = (next: Partial<LineEdit>) => setLineEdits((all) => ({ ...all, [r.id]: { ...edit, ...next } }));
                return (
                  <tr key={r.id} className="report-row">
                    <td className="id-code">{r.product.sku}</td>
                    <td>{r.product.name}</td>
                    {detail.manager && <td className="num">{r.book_qty}</td>}
                    <td className="num">{r.counted_qty}</td>
                    {detail.manager && <td className={(r.diff ?? 0) < 0 ? "num report-neg" : "num"}>{signed(r.diff ?? 0)}</td>}
                    <td>{movedHint(r)}</td>
                    {detail.manager && <td className={isNegative(r.amount) ? "num report-neg" : "num"}>{money(r.amount ?? 0)}</td>}
                    {reviewing && (
                      <>
                        <td className="num">
                          <input type="text" inputMode="numeric" className="sc-adjust" value={edit.adjust} disabled={edit.skipped} onChange={(e) => change({ adjust: e.target.value })} />
                        </td>
                        <td>
                          <input type="checkbox" checked={edit.skipped} onChange={(e) => change({ skipped: e.target.checked })} />
                        </td>
                        <td>
                          <input type="text" value={edit.reason} maxLength={100} onChange={(e) => change({ reason: e.target.value })} />
                        </td>
                      </>
                    )}
                    {detail.manager && approved && (
                      <>
                        <td className="num">{signed(r.adjust_qty ?? 0)}</td>
                        <td>{r.skipped ? "不調" : ""}</td>
                        <td>{r.reason}</td>
                      </>
                    )}
                    {counting && (
                      <td>
                        <button className="btn" type="button" disabled={run.isPending} onClick={() => void call(`lines/${r.id}/`, undefined, "DELETE")}>
                          移除
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        ))}
        {shown === "scans" && (detail.scan_rows.length === 0 ? (
          <div className="md-empty">還沒有刷任何手機</div>
        ) : (
          <table className="report-grid">
            <thead>
              <tr>
                <th>刷到的碼</th>
                <th>品名</th>
                {counting && <th />}
              </tr>
            </thead>
            <tbody>
              {newestFirst(detail.scan_rows).map((s) => (
                <tr key={s.id} className="report-row">
                  <td className="id-code">{s.code}</td>
                  <td>{s.known ? s.name : s.name || "不認得"}</td>
                  {counting && (
                    <td>
                      <button className="btn" type="button" disabled={run.isPending} onClick={() => void call(`scans/${s.id}/`, undefined, "DELETE")}>
                        移除
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ))}
        {shown === "vendor" && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>換貨中的序號</th>
                <th>品名</th>
                <th>廠商</th>
                <th className="num">送出天數</th>
              </tr>
            </thead>
            <tbody>
              {(detail.vendor_rows ?? []).map((v) => (
                <tr key={v.id} className="report-row">
                  <td>{v.serial_no}</td>
                  <td>{v.name}</td>
                  <td>{v.supplier || "—"}</td>
                  <td className="num">{v.days}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {shown === "missing" && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>少的序號</th>
                <th>品名</th>
                <th className="num">成本</th>
                <th>現況</th>
                {reviewing && <th>不調</th>}
                <th>原因</th>
                {approved && <th />}
              </tr>
            </thead>
            <tbody>
              {(detail.missing_rows ?? []).map((m) => {
                const edit = missingEdit(m.id);
                const change = (next: Partial<MissingEdit>) => setMissingEdits((all) => ({ ...all, [m.id]: { ...edit, ...next } }));
                return (
                  <tr key={m.id} className="report-row">
                    <td>{m.serial_no}</td>
                    <td>{m.name}</td>
                    <td className="num">{money(m.cost)}</td>
                    <td>{missingText(m, approved)}</td>
                    {reviewing && (
                      <td>
                        <input type="checkbox" checked={edit.skipped} onChange={(e) => change({ skipped: e.target.checked })} />
                      </td>
                    )}
                    <td>
                      {reviewing ? (
                        <input type="text" value={edit.reason} maxLength={100} onChange={(e) => change({ reason: e.target.value })} />
                      ) : (
                        m.reason
                      )}
                    </td>
                    {approved && <td>{m.applied && !m.found && <ArmButton label="找回" className="btn" onConfirm={() => call(`missing/${m.id}/found/`)} />}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {shown === "new" && (
          <>
            {reviewing && (
              <div className="list-filterbar sr-filter">
                <label>
                  品號
                  <ComboBox<Product>
                    value={assignTo.id}
                    selectedOption={assignTo.option}
                    onChange={(pid, opt) => setAssignTo({ id: pid, option: opt ?? null })}
                    fetchOptions={async (q) => (await searchProducts(q, { activeOnly: true })).filter((o) => o.payload?.requires_serial)}
                    placeholder="品名"
                  />
                </label>
                <button className="btn" type="button" disabled={!assignTo.option || picked.size === 0} onClick={assign}>
                  指定 {picked.size || ""}
                </button>
              </div>
            )}
            <table className="report-grid">
              <thead>
                <tr>
                  {reviewing && <th />}
                  <th>新入庫</th>
                  <th>舊品名</th>
                  <th>品號</th>
                  <th className="num">成本</th>
                  <th className="num">售價</th>
                  <th>{reviewing ? "不入" : "結果"}</th>
                </tr>
              </thead>
              <tbody>
                {newGroups(newRows).map((g) => {
                  const ids = g.rows.map((r) => r.id);
                  const pickedHere = ids.filter((one) => picked.has(one)).length;
                  const all = ids.length > 0 && pickedHere === ids.length;
                  return [
                    <tr key={`g-${g.key}`} className="report-row sc-group">
                      {reviewing && (
                        <td>
                          <GroupCheckbox picked={pickedHere} total={ids.length} aria-label={`全選 ${g.label}`} onChange={() => togglePick(ids, !all)} />
                        </td>
                      )}
                      <td colSpan={6}>
                        {g.label} {g.rows.length}
                      </td>
                    </tr>,
                    ...g.rows.map((r) => {
                      const edit = newEditOf(r, newEdits);
                      const change = (next: Partial<NewEdit>) => setNewEdits((all2) => ({ ...all2, [r.id]: { ...edit, ...next } }));
                      return (
                        <tr key={r.id} className={picked.has(r.id) ? "report-row vo-picked" : "report-row"}>
                          {reviewing && (
                            <td>
                              <input type="checkbox" checked={picked.has(r.id)} aria-label={r.code} onChange={(e) => togglePick([r.id], e.target.checked)} />
                            </td>
                          )}
                          <td className="id-code">{r.code}</td>
                          <td>{r.old_name}</td>
                          <td>{(reviewing ? edit.product : r.product)?.name ?? "—"}</td>
                          <td className="num">
                            {reviewing ? (
                              <input type="text" inputMode="decimal" className="sc-adjust" value={edit.cost} disabled={edit.skipped || !edit.product}
                                onChange={(e) => change({ cost: e.target.value })} />
                            ) : r.unit_cost !== null ? money(r.unit_cost) : ""}
                          </td>
                          <td className="num">
                            {reviewing ? (
                              edit.product?.unit && (
                                <MoneyInput min={0} className="sc-adjust" value={edit.price} disabled={edit.skipped}
                                  onChange={(v) => change({ price: v })} />
                              )
                            ) : r.unit_price !== null ? money(r.unit_price) : ""}
                          </td>
                          <td>
                            {reviewing ? (
                              <input type="checkbox" checked={edit.skipped || !edit.product} disabled={!edit.product}
                                onChange={(e) => change({ skipped: e.target.checked })} />
                            ) : (
                              newResult(r)
                            )}
                          </td>
                        </tr>
                      );
                    }),
                  ];
                })}
              </tbody>
            </table>
          </>
        )}
        {shown === "extra" && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>多的碼</th>
                <th>帳上</th>
              </tr>
            </thead>
            <tbody>
              {(detail.extra_rows ?? []).map((e) => (
                <tr key={e.id} className="report-row">
                  <td className="id-code">{e.code}</td>
                  <td>{extraText(e)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {shown === "uncounted" && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>品號</th>
                <th>品名</th>
                <th className="num">帳上</th>
              </tr>
            </thead>
            <tbody>
              {(detail.uncounted_rows ?? []).map((u) => (
                <tr key={u.product.id} className="report-row">
                  <td className="id-code">{u.product.sku}</td>
                  <td>{u.product.name}</td>
                  <td className="num">{u.book_qty}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <FindFirstPanel
        open={finding !== null}
        initialText={finding ?? ""}
        // 盤點單裡沒有地方「過去看」:停用的也是「使用這款」,按了由這一頁講
        inactiveLabel="就用這個"
        // 盲盤:候選不寫帳上數量(複審 P1)
        hideStock
        peeking={peek.isOpen}
        onPeek={peek.open}
        onClose={() => {
          trip.drop();
          unknownTarget.current = null;
          setFinding(null);
          focusScan();
        }}
        rememberable={canRemember}
        onUse={(p, code) => {
          setFinding(null);
          if (code) void rememberCode(p, code);
          void bring(p);
          focusScan();
        }}
        onCreate={(kind, prefill) => {
          if (kind === "phone") {
            toast("手機在「手機」那一格刷序號", "err", { ms: 6000 });
            return;
          }
          setFinding(null);
          setFormPrefill(prefill);
          setFormUsed(true);
          setFormOpen(true);
        }}
      />
      {formUsed && (
        <ProductForm
          open={formOpen}
          initial={null}
          prefill={formPrefill}
          // 這一頁的草稿自己一格,不跟商品管理、進貨共用
          draftKey="modal-draft:product-form-stocktake"
          hideStock
          onDraftLoaded={() => trip.detach()}
          onPhoneWizard={() => toast("手機在「手機」那一格刷序號", "err", { ms: 6000 })}
          onPeek={peek.open}
          peeking={peek.isOpen}
          onClose={() => {
            // 存好 / 選了既有的:那一趟在前面已經拿走了;人按取消:這一趟不算了
            trip.drop();
            unknownTarget.current = null;
            setFormOpen(false);
            focusScan();
          }}
          onSaved={(p) => void bring(p)}
          onUseExisting={(id, remembered) => {
            if (remembered) toast(remembered.text, remembered.tone, { ms: 6000 });
            // 表單接著就關掉(會清掉這一趟):現在就拿走,查回來再用
            const ctx = capture();
            api<Product>(`/products/${id}/`).then(
              (p) => bring(p, ctx),
              (e) => toast(errorMessageOf(e), "err", { ms: 6000 }),
            );
          }}
        />
      )}
      {peek.panel}
    </div>
  );
}

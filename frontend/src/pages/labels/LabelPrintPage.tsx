import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import { fetchLabels, type LabelData } from "@/api/labels";
import { LabelTile, codeToPrint } from "@/components/labels/LabelTile";
import { apiErrorText } from "@/components/workbench/errors";
import { QtyInput } from "@/components/workbench/QtyInput";
import {
  MAX_SHEETS,
  MAX_TOTAL_SHEETS,
  copiesOf,
  expandSheets,
  shouldAutoPrint,
  totalSheets,
} from "@/lib/labels";

/**
 * 商品標籤列印頁(50 × 30 mm,一張標籤一頁;用瀏覽器的列印送到條碼機)。
 *
 * 要印什麼看網址:
 * - `/purchases/:id/print/labels` = 那張進貨單整張(序號商品每一台一張,配件照進貨數量)
 * - `/labels/print?serials=1,2,3` = 那幾台各一張
 * - `/labels/print?product=5&copies=3` = 那個配件印 3 張
 * - `/labels/print?test=1` = 測試標籤(裝好印表機先印這個:看邊框有沒有被切、條碼刷不刷得到)
 * `auto=0` = 不要自己跳出列印視窗。
 *
 * 配件的張數可以在上面那一排改(0 = 不印);某一台固定一張。
 */

const TEST_LABELS: LabelData[] = [
  {
    key: "test-frame",
    product_id: 0,
    serial_id: 0,
    name: "測試標籤:四邊的框線要完整",
    sku: "50 × 30 mm",
    code: "TEST1234",
    code_kind: "sku",
    last5: "",
    price: null,
    grade: "",
    doc_no: "條碼槍刷得到 TEST1234",
    doc_date: "",
    copies: 1,
  },
  {
    key: "test-sample",
    product_id: 0,
    serial_id: 0,
    name: "測試標籤 iPhone 15 128GB 黑(真的標籤長這樣)",
    sku: "PH-000001",
    code: "356789012345671",
    code_kind: "serial",
    last5: "45671",
    price: 25000,
    grade: "A",
    doc_no: "PO-000001",
    doc_date: "2026-10-06",
    copies: 1,
  },
];

export function LabelPrintPage() {
  const { id } = useParams<{ id: string }>();
  const [sp] = useSearchParams();
  const test = sp.get("test") === "1";
  const auto = sp.get("auto") !== "0";
  const serials = sp.get("serials");
  const product = sp.get("product");
  const query = id
    ? `po=${encodeURIComponent(id)}`
    : serials
      ? `serials=${encodeURIComponent(serials)}`
      : product
        ? `product=${encodeURIComponent(product)}&copies=${encodeURIComponent(sp.get("copies") ?? "1")}`
        : null;
  // 換一張單(同一個分頁換了網址)就是全新的一頁:改過的張數、「跳過列印視窗了沒」都不帶過去
  return <LabelSheet key={test ? "test" : (query ?? "none")} query={query} test={test} auto={auto} />;
}

function LabelSheet({ query, test, auto }: { query: string | null; test: boolean; auto: boolean }) {
  const dataQ = useQuery({
    queryKey: ["labels", query],
    queryFn: () => fetchLabels(query as string),
    enabled: !test && query !== null,
    // 要印的是「現在」的東西(售價剛改、剛入庫):不拿留著的舊資料
    gcTime: 0,
    staleTime: 0,
    // 被擋下來的(4xx:作廢的單、找不到的設備、格式不對)再試也一樣:馬上講原因,不要讓人看著「載入中」等好幾秒
    retry: (count, err) =>
      !(err instanceof ApiHttpError && err.status >= 400 && err.status < 500) && count < 2,
    // 這一頁載入之後內容就固定(人看到什麼就印什麼):不因為網路斷了又連上就在背後換一份
    refetchOnReconnect: false,
  });
  const entries = useMemo(
    () => (test ? TEST_LABELS : (dataQ.data?.labels ?? [])),
    [test, dataQ.data],
  );

  /** 配件改過的張數(key → 張數) */
  const [edited, setEdited] = useState<Record<string, number>>({});
  const total = totalSheets(entries, edited);
  /** 整批太多張:不畫、不印,請人把配件的張數改少 */
  const tooMany = total > MAX_TOTAL_SHEETS;
  const sheets = useMemo(() => expandSheets(entries, edited), [entries, edited]);
  const notes = test ? [] : (dataQ.data?.notes ?? []);
  const adjustable = entries.filter((e) => e.serial_id === null);
  const units = entries.length - adjustable.length;
  // 條碼印不下的(太長、或有條碼沒有的字):原廠條碼改印品號;連品號也不行、或是序號,就只印文字
  const printing = entries.filter((e) => copiesOf(e, edited) > 0);
  const swapped = printing.filter((e) => codeToPrint(e).swapped);
  const noBars = printing.filter((e) => !codeToPrint(e).bars);
  const hasWarning = notes.length > 0 || swapped.length > 0 || noBars.length > 0;

  // 自己跳出列印視窗:**只在資料第一次到的那一刻決定一次**(規則在 `shouldAutoPrint`)。
  // 那一刻沒跳(有提醒、張數很多),之後人把提醒弄不見、把張數改小,都不會突然自己印起來 —— 他已經在看這一頁了,由他按「列印」。
  const ready = entries.length > 0;
  const latest = useRef({ total, hasWarning });
  latest.current = { total, hasWarning };
  const decided = useRef(false);
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (!ready || decided.current) return;
    decided.current = true;
    if (!shouldAutoPrint({ auto, ...latest.current })) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      // 等的這一下裡張數被改過:照現在的再看一次
      if (shouldAutoPrint({ auto, ...latest.current })) window.print();
    }, 300);
    return () => {
      // 還沒跳就被收掉(開發模式會把這一段多跑一輪):計時器收掉,下一輪重新決定
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
        decided.current = false;
      }
    };
  }, [ready, auto]);

  /** 人自己按「列印」:還在等的那一次自動列印取消掉(不然印完又跳一次、同一批印兩份) */
  function printNow() {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    window.print();
  }

  if (!test && query === null) return <div className="label-msg">沒有指定要印什麼</div>;
  // 還沒拿到資料(isPending):連不上網路時請求是「暫停」不是「失敗」,不能當成「這張單沒有東西要印」
  if (!test && dataQ.isPending) {
    return (
      <div className="label-msg">
        {dataQ.fetchStatus === "paused" ? "還沒拿到標籤:網路連不上或暫時沒回應,會自己再試" : "載入中…"}
      </div>
    );
  }
  if (!test && dataQ.isError) {
    return (
      <div className="label-msg">
        <div>{apiErrorText(dataQ.error)}</div>
        <div className="label-msg-actions">
          <button type="button" onClick={() => void dataQ.refetch()}>
            重試
          </button>
          <button type="button" onClick={() => window.close()}>
            關閉
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="label-page">
      <div className="label-bar no-print">
        {/* 第一排:幾張、列印、關閉 —— 配件再多行,這一排都看得到 */}
        <div className="label-bar-main">
          <b>共 {total} 張</b>
          {!test && units > 0 && <span>序號商品 {units} 台</span>}
          <span className="label-bar-grow" />
          <button type="button" disabled={sheets.length === 0} onClick={printNow}>
            列印
          </button>
          <button type="button" onClick={() => window.close()}>
            關閉
          </button>
        </div>
        {tooMany && (
          <div className="label-bar-warn">
            一次最多印 {MAX_TOTAL_SHEETS} 張:請把下面配件的張數改少(0 = 這一筆不印)
          </div>
        )}
        {notes.map((n) => (
          <div key={n} className="label-bar-warn">
            {n}
          </div>
        ))}
        {swapped.length > 0 && (
          <div className="label-bar-warn">
            {swapped.length} 筆的原廠條碼太長,改印品號的條碼:
            {swapped
              .slice(0, 5)
              .map((e) => e.name)
              .join("、")}
            {swapped.length > 5 ? " …" : ""}
          </div>
        )}
        {noBars.length > 0 && (
          <div className="label-bar-warn">
            仍可列印。{noBars.length} 筆的條碼印不下(只印文字):
            {noBars
              .slice(0, 5)
              .map((e) => e.code)
              .join("、")}
            {noBars.length > 5 ? " …" : ""}
          </div>
        )}
        {ready && total === 0 && <div className="label-bar-warn">張數都是 0,沒有東西要印</div>}
        {!ready && <div className="label-bar-warn">這張單沒有要貼標籤的商品</div>}
        {adjustable.length > 0 && (
          <div className="label-bar-lines">
            {adjustable.map((e) => (
              <label key={e.key} className="label-bar-qty">
                <span className="label-bar-name">{e.name}</span>
                <QtyInput
                  value={copiesOf(e, edited)}
                  min={0}
                  max={MAX_SHEETS}
                  aria-label={`${e.name} 張數`}
                  onCommit={(n) => setEdited((cur) => ({ ...cur, [e.key]: n }))}
                />
                張
              </label>
            ))}
          </div>
        )}
      </div>
      <div className="label-sheet">
        {sheets.map((s) => (
          <LabelTile key={s.key} label={s.entry} frame={s.entry.key === "test-frame"} />
        ))}
      </div>
    </div>
  );
}

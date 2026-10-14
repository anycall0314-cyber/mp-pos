import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { useRememberPhrase } from "@/api/hooks";
import { searchProducts } from "@/api/search";
import type { Product } from "@/api/types";
import { Banner, errorMessageOf } from "@/components/Banner";
import { ComboBox } from "@/components/ComboBox";
import { money } from "@/lib/money";
import {
  costIn,
  groupForPurchase,
  productOf,
  sheetCounts,
  sheetHeader,
  templateBlob,
  type SheetEntry,
  type SheetPreview,
} from "@/lib/secondhandSheet";

interface Props {
  open: boolean;
  onClose: () => void;
  /** 加進進貨單:一個品號一組,每一台自己的機況與成本 */
  onConfirm: (groups: { product: Product; entries: SheetEntry[] }[]) => void;
  supplier: number | "";
  supplierName: string;
  warehouse: number | "";
  warehouseName: string;
  taxMethod: string;
  taxLabel: string;
}

/**
 * 中古機大量進貨的 Excel(owner 2026-10-14)。廠商收購那一頁的工作台裡,跟「批次貼上」放在同一個位置。
 * 下載範本 → 填好 → 選檔 → 預覽(伺服器讀、對品號、查碼;不寫東西)→ 加進這張進貨單(按儲存才成立)。
 * 對不到的品名不先帶,一個品名人自己挑一次(可以記住,下次直接對到)。
 * **換了廠商,讀過的整份作廢**(複審 P0:品名照那家廠商的叫法對的,換了廠商還用舊的對法,機器會入到錯的品號);
 * 讀檔途中換了廠商,晚回來的那一份也不要。
 */
export function SecondhandSheetImport(props: Props) {
  const { open, onClose, onConfirm, supplier, supplierName, warehouse, warehouseName, taxMethod, taxLabel } = props;
  const [preview, setPreview] = useState<SheetPreview<Product> | null>(null);
  const [picks, setPicks] = useState<Record<string, Product | undefined>>({});
  const [keep, setKeep] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const remember = useRememberPhrase();
  /** 第幾次讀檔:換廠商、再讀一次都換號,舊號回來的不用 */
  const asked = useRef(0);
  const [readFor, setReadFor] = useState<number | "">("");
  useEffect(() => {
    asked.current += 1;
    setPreview(null);
    setPicks({});
    setKeep({});
  }, [supplier]);
  const products = useMemo(() => new Map((preview?.products ?? []).map((p) => [p.id, p])), [preview]);
  const ready = supplier !== "" && warehouse !== "";

  if (!open) return null;

  async function download() {
    setError("");
    try {
      const r = await api<{ filename: string; file: string }>("/secondhand-purchase-sheet/");
      const url = URL.createObjectURL(templateBlob(r.file));
      const a = document.createElement("a");
      a.href = url;
      a.download = r.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessageOf(e));
    }
  }

  async function read(file: File) {
    setError("");
    setBusy(true);
    const ticket = ++asked.current;
    const forSupplier = supplier;
    const body = new FormData();
    body.append("file", file);
    if (forSupplier !== "") body.append("supplier", String(forSupplier));
    try {
      const got = await api<SheetPreview<Product>>("/secondhand-purchase-sheet/", { method: "POST", body });
      if (ticket !== asked.current) return;
      setPreview(got);
      setReadFor(forSupplier);
      setPicks({});
      setKeep({});
    } catch (e) {
      if (ticket !== asked.current) return;
      setPreview(null);
      setError(errorMessageOf(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function add() {
    if (!preview || readFor !== supplier) return;
    const groups = groupForPurchase(preview.rows, products, picks);
    if (!groups.length) return;
    for (const name of Object.keys(keep)) {
      const p = picks[name];
      if (keep[name] && p) remember.mutate({ product: p.id, value: name, supplier: supplier === "" ? null : supplier });
    }
    onConfirm(groups);
    setPreview(null);
  }

  const counts = preview ? sheetCounts(preview.rows, products, picks) : null;
  return (
    <div className="wb-tool">
      <div className="wb-card batch-paste-modal inline">
        <div className="modal-title">匯入中古機</div>
        {error && <Banner kind="error" message={error} />}
        <div className="list-filterbar sr-filter">
          <button className="btn" type="button" onClick={() => void download()}>
            下載範本
          </button>
          <button className="btn" type="button" disabled={!ready || busy} onClick={() => fileRef.current?.click()}>
            選擇檔案
          </button>
          <input ref={fileRef} type="file" accept=".xlsx" hidden onChange={(e) => e.target.files?.[0] && void read(e.target.files[0])} />
          <button className="btn" type="button" onClick={onClose}>
            關閉
          </button>
        </div>
        {preview && counts && (
          <>
            <div className="ex-period">{sheetHeader(warehouseName, supplierName, taxLabel)}</div>
            {preview.names.length > 0 && (
              <table className="report-grid">
                <thead>
                  <tr>
                    <th>對不到的品名</th>
                    <th className="num">台</th>
                    <th>品號</th>
                    <th>記住</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.names.map((n) => (
                    <tr key={n.name} className="report-row">
                      <td>{n.name}</td>
                      <td className="num">{n.count}</td>
                      <td>
                        <ComboBox<Product>
                          value={picks[n.name]?.id ?? ""}
                          selectedOption={picks[n.name] ? { id: picks[n.name]!.id, label: picks[n.name]!.name, payload: picks[n.name] } : null}
                          onChange={(_id, opt) => setPicks((all) => ({ ...all, [n.name]: opt?.payload }))}
                          fetchOptions={(q) => searchProducts(q, { secondhandOnly: true, activeOnly: true })}
                          placeholder="品名"
                        />
                      </td>
                      <td>
                        <input type="checkbox" checked={!!keep[n.name]} aria-label={`記住 ${n.name}`}
                          onChange={(e) => setKeep((all) => ({ ...all, [n.name]: e.target.checked }))} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="report-table sr-table">
              <table className="report-grid">
                <thead>
                  <tr>
                    <th className="num">列</th>
                    <th>品名</th>
                    <th>品號</th>
                    <th>IMEI</th>
                    <th>序號</th>
                    <th>成色</th>
                    <th className="num">電池</th>
                    <th className="num">成本</th>
                    <th className="num">售價</th>
                    <th>問題</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => {
                    const p = productOf(r, products, picks);
                    return (
                      <tr key={r.row} className={r.problems.length ? "report-row report-neg" : "report-row"}>
                        <td className="num">{r.row}</td>
                        <td>{r.name}</td>
                        <td>{p?.name ?? "—"}</td>
                        <td>{r.imei}</td>
                        <td>{r.sn}</td>
                        <td>{r.grade}</td>
                        <td className="num">{r.battery ?? ""}</td>
                        <td className="num">{r.cost === null ? "" : money(costIn(r.cost, taxMethod))}</td>
                        <td className="num">{r.price ? money(r.price) : ""}</td>
                        <td>{r.problems.join("、")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="list-filterbar sr-filter">
              <button className="btn primary" type="button" disabled={counts.ready === 0} onClick={add}>
                加入 {counts.ready} 台
              </button>
              {counts.bad > 0 && <span className="tr-dim">問題 {counts.bad}</span>}
              {counts.unpicked > 0 && <span className="tr-dim">未選品號 {counts.unpicked}</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

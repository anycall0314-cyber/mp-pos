import JsBarcode from "jsbarcode";
import { useEffect, useMemo, useRef } from "react";
import { useParams } from "react-router-dom";

import { usePurchaseOrder } from "@/api/hooks";
import type { PurchaseOrderItem } from "@/api/types";

/**
 * 50 × 30mm 熱感標籤;每件商品數量印對應張數。
 * - 追序號商品:每個序號一張;條碼 = 序號全碼,文字顯示末 5 碼
 * - 不追序號:每張條碼 = SKU
 */
export function PurchaseLabelsPrintPage() {
  const { id } = useParams<{ id: string }>();
  const poId = id ? Number(id) : null;
  const { data, isLoading } = usePurchaseOrder(poId);

  // 把每張標籤展開成 flat 陣列
  const tiles = useMemo(() => {
    if (!data) return [];
    const out: Array<{
      key: string;
      item: PurchaseOrderItem;
      serial: string | null;
    }> = [];
    for (const it of data.items) {
      if (it.serial_numbers && it.serial_numbers.length > 0) {
        // 追序號:每個序號一張(可能是字串或物件)
        it.serial_numbers.forEach((entry, i) => {
          const sn =
            typeof entry === "string" ? entry : (entry?.sn ?? "");
          out.push({ key: `${it.id}-${i}-${sn}`, item: it, serial: sn });
        });
      } else {
        // 不追序號:依進貨數量印 qty 張
        for (let i = 0; i < it.qty; i++) {
          out.push({ key: `${it.id}-${i}`, item: it, serial: null });
        }
      }
    }
    return out;
  }, [data]);

  useEffect(() => {
    if (!isLoading && data) {
      const handle = setTimeout(() => window.print(), 150);
      return () => clearTimeout(handle);
    }
  }, [isLoading, data]);

  if (isLoading) return <div style={{ padding: 20 }}>載入中…</div>;
  if (!data) return <div style={{ padding: 20 }}>找不到進貨單</div>;

  return (
    <div className="label-sheet">
      {tiles.map((t) => (
        <LabelTile
          key={t.key}
          name={t.item.product_name}
          sku={t.item.product_sku}
          serial={t.serial}
          listPrice={t.item.product_list_price}
          poNo={data.no}
          docDate={data.doc_date}
        />
      ))}
      <div className="no-print" style={{ position: "fixed", bottom: 12, right: 12, display: "flex", gap: 8, padding: 8, background: "white", border: "1px solid #ccc", borderRadius: 4 }}>
        <span style={{ alignSelf: "center", color: "#333" }}>共 {tiles.length} 張</span>
        <button onClick={() => window.print()}>列印</button>
        <button onClick={() => window.close()}>關閉</button>
      </div>
    </div>
  );
}

interface TileProps {
  name: string;
  sku: string;
  serial: string | null;
  listPrice: string | undefined;
  poNo: string;
  docDate: string;
}

function LabelTile({ name, sku, serial, listPrice, poNo, docDate }: TileProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  // 條碼內容:有序號用序號全碼,沒有就用 SKU
  const barcodeValue = serial || sku || "—";
  const last5 = serial ? serial.slice(-5) : null;

  useEffect(() => {
    if (svgRef.current) {
      try {
        JsBarcode(svgRef.current, barcodeValue, {
          format: "CODE128",
          width: 1.1,
          height: 28,
          fontSize: 9,
          textMargin: 0,
          margin: 0,
          displayValue: false,
        });
      } catch {
        // value 不合法時略過
      }
    }
  }, [barcodeValue]);

  return (
    <div className="label-tile">
      <div className="label-name">{name}</div>
      <div className="label-sku">{sku}</div>
      <svg ref={svgRef} className="label-barcode" />
      <div className="label-row">
        {last5 && <span className="label-last5">序末 {last5}</span>}
        {listPrice != null && (
          <span className="label-price">$ {Number(listPrice).toLocaleString()}</span>
        )}
      </div>
      <div className="label-footer">
        {poNo} · {docDate.slice(5)}
      </div>
    </div>
  );
}

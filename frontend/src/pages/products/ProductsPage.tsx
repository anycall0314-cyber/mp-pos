import { useState } from "react";

import { useProducts } from "@/api/hooks";
import type { Product } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import {
  MasterDetail,
  MasterColumn,
  DetailTab,
} from "@/components/master-detail/MasterDetail";

import { BulkAddProductsModal } from "./BulkAddProductsModal";
import { ProductForm } from "./ProductForm";

function formatMoney(value: string | number) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString() : "—";
}

function flagText(p: Product) {
  const flags: string[] = [];
  if (p.requires_serial) flags.push("追序號");
  if (p.allows_telecom_line) flags.push("可綁約");
  if (p.allows_commission) flags.push("可佣金");
  return flags.length > 0 ? flags.join(" / ") : "純商品";
}

const columns: MasterColumn<Product>[] = [
  { key: "name", header: "品名", render: (r) => r.name },
  { key: "category", header: "類別", render: (r) => r.category_name },
  {
    key: "stock_qty",
    header: "在庫",
    render: (r) => <span className="num">{r.stock_qty}</span>,
  },
  {
    key: "is_active",
    header: "啟用",
    render: (r) => (r.is_active ? "✓" : "—"),
  },
];

export function ProductsPage() {
  const { data, isLoading, isError, error } = useProducts();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitial, setDrawerInitial] = useState<Product | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  const tabs: DetailTab<Product>[] = [
    {
      key: "basic",
      label: "基本",
      render: (r) => (
        <div>
          <dl>
            <dt>品名</dt>
            <dd>{r.name}</dd>
            <dt>規格</dt>
            <dd>{r.spec || "—"}</dd>
            <dt>條碼</dt>
            <dd>{r.barcode || "—"}</dd>
            <dt>類別</dt>
            <dd>
              {r.category_code} {r.category_name}
            </dd>
            <dt>建議零售價</dt>
            <dd>{formatMoney(r.list_price)}</dd>
            <dt>加權平均成本</dt>
            <dd>{formatMoney(r.weighted_avg_cost)}</dd>
            <dt>屬性</dt>
            <dd>{flagText(r)}</dd>
            <dt>狀態</dt>
            <dd>{r.is_active ? "啟用" : "停用"}</dd>
          </dl>
          <div style={{ marginTop: 12, display: "flex", gap: 6 }}>
            <button
              className="btn primary"
              onClick={() => {
                setDrawerInitial(r);
                setDrawerOpen(true);
              }}
            >
              編輯
            </button>
          </div>
        </div>
      ),
    },
    {
      key: "serials",
      label: "序號清單",
      render: () => <div className="md-empty">下階段串接</div>,
    },
    {
      key: "history",
      label: "進銷歷史",
      render: () => <div className="md-empty">下階段串接</div>,
    },
  ];

  return (
    <div className="page">
      <Toolbar
        title="商品"
        actions={
          <>
            <button
              className="btn"
              onClick={() => setBulkOpen(true)}
            >
              批次新增
            </button>
            <button
              className="btn primary"
              onClick={() => {
                setDrawerInitial(null);
                setDrawerOpen(true);
              }}
            >
              + 新增商品
            </button>
          </>
        }
      />
      {bulkResult && (
        <div
          style={{
            padding: "6px 16px",
            background: "rgba(128,208,144,0.15)",
            color: "#80d090",
            fontSize: 12,
          }}
        >
          {bulkResult}
        </div>
      )}
      {isLoading && <div className="md-empty">載入中…</div>}
      {isError && <div className="md-empty">載入失敗:{String(error)}</div>}
      {!isLoading && !isError && (
        <MasterDetail
          rows={data ?? []}
          columns={columns}
          rowKey={(r) => r.id}
          tabs={tabs}
          searchPlaceholder=""
          emptyDetailHint={
            (data ?? []).length === 0
              ? "尚無商品,點右上「+ 新增商品」開始建立"
              : "從左側選擇商品檢視詳細"
          }
        />
      )}
      <ProductForm
        open={drawerOpen}
        initial={drawerInitial}
        onClose={() => setDrawerOpen(false)}
      />
      <BulkAddProductsModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onSuccess={(count) => {
          setBulkOpen(false);
          setBulkResult(`成功建立 ${count} 筆商品`);
          setTimeout(() => setBulkResult(null), 4000);
        }}
      />
    </div>
  );
}

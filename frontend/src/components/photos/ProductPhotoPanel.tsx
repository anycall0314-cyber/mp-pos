import { useEffect, useRef, useState } from "react";

import { useProduct, useProductPhotos } from "@/api/hooks";
import { Drawer } from "@/components/Drawer";
import { money } from "@/lib/money";

import { PhotoLightbox } from "./PhotoLightbox";

export interface PeekTarget {
  id: number;
  /** 還沒載到商品資料之前先顯示的 */
  name: string;
  sku?: string;
  /** 選品的情境才給:按「使用此商品」要做的事(加入的是這個既有商品,不會另建) */
  onUse?: () => void;
}

interface Props {
  target: PeekTarget | null;
  onClose: () => void;
}

/**
 * 點品名看照片與規格:確認「就是這一件」再用。
 * 只是看 —— 不會把商品加進單據、不會改商品;選品的情境另外有「使用此商品」。
 */
export function ProductPhotoPanel({ target, onClose }: Props) {
  const id = target?.id ?? null;
  const productQ = useProduct(id);
  const photosQ = useProductPhotos(id);
  const [at, setAt] = useState(0);
  const [big, setBig] = useState<number | null>(null);

  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setAt(0);
    setBig(null);
    // 游標移進面板(放在面板本身,不放在任何一顆按鈕上):
    // 人在看照片時條碼槍刷進來,不會跑進背後的掃碼框變成多加一行,結尾的 Enter 也不會按到「使用此商品」
    if (id != null) box.current?.focus();
  }, [id]);

  if (!target) return null;
  const p = productQ.data;
  const photos = photosQ.data ?? [];
  const shown = photos[Math.min(at, photos.length - 1)];
  const rows: [string, string | undefined | null][] = [
    ["品號", p?.sku ?? target.sku],
    ["規格", p?.spec],
    ["類別", p?.category_name],
    // 機型只有主機(手機、平板…)才有意義;配件那一欄是從品名推出來的,不列
    ["機型", p && p.accessory_type === "none" && p.phone_model_name !== p.name ? p.phone_model_name : undefined],
    ["適用機型", p?.related_hosts?.map((h) => h.model_name).join("、")],
    ["容量", p?.capacity],
    ["顏色", p?.color],
    ["版本", p?.region_version],
    ["品況", p?.condition_name],
    ["條碼", p?.barcode],
    ["建議售價", p && p.warehouse_type !== "parts" ? money(p.list_price) : undefined],
  ];

  return (
    <Drawer
      open
      title="商品照片與規格"
      width={520}
      onClose={onClose}
      footer={
        target.onUse ? (
          <>
            <button type="button" className="btn" onClick={onClose}>
              返回繼續找
            </button>
            <button
              type="button"
              className="btn primary"
              onClick={() => {
                const use = target.onUse!;
                onClose();
                use();
              }}
            >
              使用此商品
            </button>
          </>
        ) : (
          <button type="button" className="btn" onClick={onClose}>
            關閉
          </button>
        )
      }
    >
      <div className="ph-panel" ref={box} tabIndex={-1}>
        {photosQ.isLoading && <div className="ph-empty">載入中…</div>}
        {photosQ.isError && <div className="ph-note err">照片載入失敗</div>}
        {!photosQ.isLoading && !photosQ.isError && photos.length === 0 && (
          <div className="ph-empty">這個商品還沒有照片</div>
        )}
        {shown && (
          <>
            <button
              type="button"
              className="ph-panel-main"
              title="看大圖"
              onClick={() => setBig(Math.min(at, photos.length - 1))}
            >
              <img src={shown.image_url} alt={shown.caption || "商品照片"} />
            </button>
            {shown.caption && <div className="ph-panel-caption">{shown.caption}</div>}
            {photos.length > 1 && (
              <div className="ph-panel-strip">
                {photos.map((ph, i) => (
                  <button
                    key={ph.id}
                    type="button"
                    className={`ph-panel-thumb${i === at ? " on" : ""}`}
                    title={ph.caption || undefined}
                    onClick={() => setAt(i)}
                  >
                    <img src={ph.thumb_url} alt={ph.caption || "商品照片"} />
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        <div className="ph-panel-name">
          {p?.name ?? target.name}
          {p && !p.is_active && <span className="ph-panel-off">已停用</span>}
        </div>
        <dl className="ph-panel-spec">
          {rows
            .filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== "")
            .map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
        </dl>
        {productQ.isError && <div className="ph-note err">商品資料載入失敗</div>}
      </div>

      {big !== null && photos.length > 0 && (
        <PhotoLightbox
          items={photos.map((ph) => ({ src: ph.image_url, caption: ph.caption }))}
          index={big}
          onIndex={(i) => {
            setBig(i);
            setAt(i);
          }}
          onClose={() => setBig(null)}
        />
      )}
    </Drawer>
  );
}

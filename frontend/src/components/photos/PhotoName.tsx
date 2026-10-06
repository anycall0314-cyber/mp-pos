import { useEffect, useRef, useState } from "react";

import { useProductPhotos } from "@/api/hooks";

import { PhotoLightbox } from "./PhotoLightbox";
import { PeekTarget, ProductPhotoPanel } from "./ProductPhotoPanel";

/** 頁面上放一個「點品名看照片與規格」的面板:`open(商品)` 打開,`panel` 放在頁面最外層 */
export function usePhotoPeek(onClosed?: () => void) {
  const [target, setTarget] = useState<PeekTarget | null>(null);
  const wasOpen = useRef(false);
  const after = useRef(onClosed);
  after.current = onClosed;
  // 面板關掉、畫面更新完之後才回頭做事(例如把游標放回掃碼框):
  // 面板開著時背後那一塊是停用的,太早去放游標放不上去
  useEffect(() => {
    if (target) wasOpen.current = true;
    else if (wasOpen.current) {
      wasOpen.current = false;
      after.current?.();
    }
  }, [target]);
  const panel = <ProductPhotoPanel target={target} onClose={() => setTarget(null)} />;
  return { open: setTarget, isOpen: target !== null, panel };
}

interface NameProps {
  id: number;
  name: string;
  sku?: string;
  /** 主圖的縮圖網址;有才多放一個小縮圖(放得進既有的列高) */
  thumb?: string;
  onPeek: (t: PeekTarget) => void;
  className?: string;
}

/** 可以點的品名:點了看照片與規格。只是看,不會加進單據、不會展開那一列 */
export function PhotoName({ id, name, sku, thumb, onPeek, className }: NameProps) {
  /** 縮圖網址失效了(帶簽章、過幾天會過期;留在草稿裡的那種):不顯示破圖 */
  const [broken, setBroken] = useState<string | null>(null);
  const peek = (e: { stopPropagation: () => void }) => {
    e.stopPropagation();
    onPeek({ id, name, sku });
  };
  // 兩顆都不進 Tab 的順序:開單時 Tab 是在數量、單價之間走的,不能停在品名上
  return (
    <>
      {thumb && broken !== thumb && (
        <button type="button" className="ph-mini" title="看照片" onClick={peek} tabIndex={-1}>
          <img src={thumb} alt="" loading="lazy" onError={() => setBroken(thumb)} />
        </button>
      )}
      <button
        type="button"
        className={`ph-name${className ? ` ${className}` : ""}`}
        title="看照片與規格"
        tabIndex={-1}
        onClick={peek}
      >
        {name}
      </button>
    </>
  );
}

/** 清單上的小縮圖:點了看照片與規格。縮圖網址失效(簽章過期)就不顯示,不留破圖 */
export function MiniThumb({ src, onClick }: { src?: string; onClick: () => void }) {
  const [broken, setBroken] = useState<string | null>(null);
  if (!src || broken === src) return null;
  return (
    <button
      type="button"
      className="ph-mini"
      title="看照片"
      tabIndex={-1}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
    >
      <img src={src} alt="" loading="lazy" onError={() => setBroken(src)} />
    </button>
  );
}

/** 商品詳情裡的一排照片(主圖在前),點了看大圖 */
export function ProductPhotoStrip({ productId }: { productId: number }) {
  const q = useProductPhotos(productId);
  const [big, setBig] = useState<number | null>(null);
  const photos = q.data ?? [];
  if (q.isLoading) return null;
  // 載入失敗跟「沒有照片」要分得出來:不然會以為剛才沒存成功
  if (q.isError) {
    return (
      <div className="ph-empty">
        照片載入失敗
        <button type="button" className="ph-link" onClick={() => void q.refetch()}>
          重試
        </button>
      </div>
    );
  }
  if (photos.length === 0) return <div className="ph-empty">還沒有照片</div>;
  return (
    <>
      <div className="ph-panel-strip">
        {photos.map((ph, i) => (
          <button
            key={ph.id}
            type="button"
            className="ph-panel-thumb"
            title={ph.caption || "看大圖"}
            onClick={() => setBig(i)}
          >
            <img src={ph.thumb_url} alt={ph.caption || "商品照片"} loading="lazy" />
          </button>
        ))}
      </div>
      {big !== null && (
        <PhotoLightbox
          items={photos.map((ph) => ({ src: ph.image_url, caption: ph.caption }))}
          index={big}
          onIndex={setBig}
          onClose={() => setBig(null)}
        />
      )}
    </>
  );
}

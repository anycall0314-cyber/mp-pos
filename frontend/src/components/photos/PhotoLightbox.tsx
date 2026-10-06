import { useEffect, useState } from "react";

export interface LightboxItem {
  src: string;
  caption?: string;
}

interface Props {
  items: LightboxItem[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
}

/**
 * 看大圖:保留完整比例;點圖片放大到原始大小(看標籤上的小字),再點一下縮回來。
 * 左右鍵 / 兩側按鈕換下一張,Esc 或點旁邊關掉。
 */
export function PhotoLightbox({ items, index, onIndex, onClose }: Props) {
  const [zoomed, setZoomed] = useState(false);
  const count = items.length;
  const at = Math.min(Math.max(index, 0), count - 1);

  useEffect(() => setZoomed(false), [at]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && count > 1) onIndex((at + 1) % count);
      else if (e.key === "ArrowLeft" && count > 1) onIndex((at - 1 + count) % count);
      else return;
      // 底下的抽屜也在聽 Esc:這一下只關大圖
      e.stopPropagation();
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [at, count, onIndex, onClose]);

  if (count === 0) return null;
  const item = items[at];
  return (
    <div className="ph-lightbox" onClick={onClose} role="dialog" aria-label="照片">
      <div className="ph-lightbox-bar" onClick={(e) => e.stopPropagation()}>
        <span>
          {count > 1 ? `${at + 1} / ${count}` : ""}
          {item.caption ? `${count > 1 ? " · " : ""}${item.caption}` : ""}
        </span>
        <button type="button" className="ph-lightbox-btn" onClick={onClose}>
          關閉
        </button>
      </div>
      <div
        className={`ph-lightbox-stage${zoomed ? " zoomed" : ""}`}
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={item.src}
          alt={item.caption || "商品照片"}
          onClick={() => setZoomed((z) => !z)}
        />
      </div>
      {count > 1 && (
        <>
          <button
            type="button"
            className="ph-lightbox-nav prev"
            aria-label="上一張"
            onClick={(e) => {
              e.stopPropagation();
              onIndex((at - 1 + count) % count);
            }}
          >
            ‹
          </button>
          <button
            type="button"
            className="ph-lightbox-nav next"
            aria-label="下一張"
            onClick={(e) => {
              e.stopPropagation();
              onIndex((at + 1) % count);
            }}
          >
            ›
          </button>
        </>
      )}
    </div>
  );
}

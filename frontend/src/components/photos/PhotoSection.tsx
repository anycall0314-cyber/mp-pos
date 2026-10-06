import { useMemo, useRef, useState } from "react";

import { qrMatrix, qrPath } from "@/lib/qr";

import { PhotoLightbox } from "./PhotoLightbox";
import type { PhotoDraftHandle } from "./usePhotoDraft";

interface Props {
  photos: PhotoDraftHandle;
  /** 給配對畫面顯示:照片會放到哪一筆 */
  productName: string;
  /** 既有商品的品號;新增還沒有 */
  sku?: string;
  disabled?: boolean;
}

/** 手機掃了會開的網址。憑證放在 # 後面:不會進伺服器紀錄,也不會被帶到別的網站 */
function pairUrl(token: string): string {
  return `${window.location.origin}/m/photo#${token}`;
}

const LOCAL = /^(localhost|127\.0\.0\.1|\[::1\])$/;

/**
 * 商品表單裡的「商品照片」區:從電腦選(可多選、可拖進來)或用手機掃 QR Code 拍。
 * 照片先放在這一次編輯上,商品按儲存才真的存;移除已經存好的照片也是儲存才生效。
 */
export function PhotoSection({ photos, productName, sku, disabled }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState<string | null>(null);
  const [view, setView] = useState<number | null>(null);
  const [qrOpen, setQrOpen] = useState(true);
  const [pairing, setPairing] = useState(false);
  const [over, setOver] = useState(false);

  const { tiles, primaryKey, pair } = photos;
  const viewable = tiles.filter((t) => !t.removed && t.status !== "failed" && t.image);
  const full = photos.count >= photos.max;

  function add(list: FileList | File[] | null) {
    if (!list || disabled || !photos.ready) return;
    const files = Array.from(list).filter(
      (f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name),
    );
    if (files.length === 0) {
      setNote("只能加照片");
      return;
    }
    setNote(photos.addFiles(files));
  }

  async function startPair() {
    setPairing(true);
    const problem = await photos.startPair();
    setPairing(false);
    setNote(problem);
    if (!problem) setQrOpen(true);
  }

  const qr = useMemo(() => {
    if (!pair.token) return null;
    const m = qrMatrix(pairUrl(pair.token));
    return { size: m.length, d: qrPath(m) };
  }, [pair.token]);

  const active = pair.status === "waiting" || pair.status === "connected";
  const pairText =
    pair.status === "waiting"
      ? "等待手機連線"
      : pair.status === "connected"
        ? `手機已連線 · 收到 ${pair.received} 張`
        : pair.status === "expired"
          ? "QR Code 過期了"
          : pair.status === "idle"
            ? "手機太久沒動作,已結束"
            : "";

  return (
    <section
      className={`ph-section${over ? " over" : ""}`}
      onDragOver={(e) => {
        if (disabled) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        add(e.dataTransfer.files);
      }}
    >
      <div className="ph-head">
        <span className="ph-title">商品照片</span>
        <span className="ph-count">
          {photos.count} / {photos.max} 張
        </span>
      </div>

      <div className="ph-actions">
        <input
          ref={fileRef}
          type="file"
          accept="image/*,.heic,.heif"
          multiple
          hidden
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="btn"
          disabled={disabled || full || !photos.ready}
          onClick={() => fileRef.current?.click()}
        >
          從電腦選照片
        </button>
        <button
          type="button"
          className="btn"
          disabled={disabled || full || pairing || active || !photos.ready}
          onClick={startPair}
        >
          用手機拍照片
        </button>
      </div>

      {photos.loadError && (
        <div className="ph-note err">
          原本的照片載入失敗
          <button type="button" className="ph-link" disabled={disabled} onClick={photos.reload}>
            重試
          </button>
        </div>
      )}
      {photos.resumeFailed && (
        <div className="ph-note err">
          上次的照片沒有接回來
          <button type="button" className="ph-link" disabled={disabled} onClick={photos.retryResume}>
            重試
          </button>
          <button type="button" className="ph-link" disabled={disabled} onClick={photos.giveUpResume}>
            不要了
          </button>
        </div>
      )}
      {note && <div className="ph-note err">{note}</div>}

      {pair.status !== "none" && (
        <div className="ph-pair">
          <div className="ph-pair-head">
            <span className={`ph-pair-status ${pair.status}`}>{pairText}</span>
            {pair.status === "waiting" && qr && (
              <button type="button" className="ph-link" onClick={() => setQrOpen((o) => !o)}>
                {qrOpen ? "收起" : "展開"}
              </button>
            )}
          </div>
          {pair.status === "waiting" && qr && qrOpen && (
            <div className="ph-pair-body">
              <svg
                className="ph-qr"
                viewBox={`0 0 ${qr.size} ${qr.size}`}
                role="img"
                aria-label="手機拍照 QR Code"
                shapeRendering="crispEdges"
              >
                <rect width={qr.size} height={qr.size} fill="#fff" />
                <path d={qr.d} fill="#000" />
              </svg>
              <div className="ph-pair-info">
                <div className="ph-pair-name">{productName.trim() || "新增商品(尚未命名)"}</div>
                <div className="ph-pair-sku">品號:{sku || "尚未建立"}</div>
                <div className="ph-pair-hint">用手機相機掃描</div>
                {LOCAL.test(window.location.hostname) && (
                  <div className="ph-note err">這個網址手機連不到(本機測試)</div>
                )}
              </div>
            </div>
          )}
          <div className="ph-actions">
            <button type="button" className="btn" disabled={disabled || pairing} onClick={startPair}>
              重新產生
            </button>
            {active && (
              <button
                type="button"
                className="btn"
                disabled={disabled}
                onClick={() => void photos.endPair()}
              >
                結束拍照
              </button>
            )}
          </div>
        </div>
      )}

      {tiles.length === 0 ? (
        <div className="ph-empty">還沒有照片</div>
      ) : (
        <div className="ph-grid">
          {tiles.map((t, i) => {
            const main = t.key === primaryKey && !t.removed;
            const at = viewable.findIndex((v) => v.key === t.key);
            return (
              <div
                key={t.key}
                className={`ph-tile${t.removed ? " removed" : ""}${t.status === "failed" ? " failed" : ""}`}
              >
                <button
                  type="button"
                  className="ph-thumb"
                  disabled={at < 0}
                  onClick={() => setView(at)}
                  title="看大圖"
                >
                  {t.thumb ? <img src={t.thumb} alt={t.caption || "商品照片"} /> : <span>處理中</span>}
                  {main && <span className="ph-flag">主圖</span>}
                  {t.status === "uploading" && <span className="ph-state">上傳中…</span>}
                  {t.status === "failed" && <span className="ph-state bad">沒傳成功</span>}
                  {t.removed && <span className="ph-state">儲存後移除</span>}
                </button>
                {t.status === "failed" && t.error && <div className="ph-err">{t.error}</div>}
                <input
                  className="ph-caption"
                  value={t.caption}
                  maxLength={40}
                  placeholder="說明"
                  aria-label="照片說明"
                  disabled={disabled || t.removed}
                  onChange={(e) => photos.setCaption(t.key, e.target.value)}
                />
                <div className="ph-tile-actions">
                  {t.removed ? (
                    <button
                      type="button"
                      className="ph-link"
                      disabled={disabled}
                      onClick={() => photos.restore(t.key)}
                    >
                      還原
                    </button>
                  ) : (
                    <>
                      {t.status === "ready" && (
                        <button
                          type="button"
                          className={`ph-link${main ? " on" : ""}`}
                          disabled={disabled || main}
                          onClick={() => photos.setPrimary(t.key)}
                        >
                          主圖
                        </button>
                      )}
                      {t.status === "failed" && t.file && (
                        <button
                          type="button"
                          className="ph-link"
                          disabled={disabled}
                          onClick={() => photos.retry(t.key)}
                        >
                          重試
                        </button>
                      )}
                      <button
                        type="button"
                        className="ph-link"
                        aria-label="往前移"
                        disabled={disabled || i === 0}
                        onClick={() => photos.move(t.key, -1)}
                      >
                        ←
                      </button>
                      <button
                        type="button"
                        className="ph-link"
                        aria-label="往後移"
                        disabled={disabled || i === tiles.length - 1}
                        onClick={() => photos.move(t.key, 1)}
                      >
                        →
                      </button>
                      <button
                        type="button"
                        className="ph-link"
                        disabled={disabled}
                        onClick={() => photos.remove(t.key)}
                      >
                        移除
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {view !== null && viewable.length > 0 && (
        <PhotoLightbox
          items={viewable.map((t) => ({ src: t.image!, caption: t.caption }))}
          index={view}
          onIndex={setView}
          onClose={() => setView(null)}
        />
      )}
    </section>
  );
}

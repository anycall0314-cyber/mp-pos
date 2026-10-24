import type { ReactNode } from "react";

import { Banner } from "@/components/Banner";
import { LEAVE_TEXT } from "@/lib/draftGuard";

/**
 * 主檔的新增 / 編輯整頁(owner 2026-10-25:「電信方案與 SIM 卡用了我最不喜歡的 modal 設計」;跟代收話費同一套):
 * 清單整頁換成表單 —— 上面「回清單」+ 標題,中間欄位,最下面一條放儲存。不蓋在清單上、不擋住別的東西。
 * 改過沒存按「回清單」要按兩次(`leaveArmed` 時按鈕換字、上面出現一句);送出中回不去。
 */
export function PaneForm({
  title,
  onBack,
  leaveArmed = false,
  busy = false,
  footer,
  wide = false,
  backLabel = "回清單",
  children,
}: {
  title: ReactNode;
  onBack: () => void;
  /** 改過沒存、已經按了第一下「回清單」 */
  leaveArmed?: boolean;
  busy?: boolean;
  /** 最下面那一條(儲存);只是看的頁(價目表)給 null 就不畫 */
  footer: ReactNode;
  /** 表格類的頁(價目表、收貨明細)不限寬度 */
  wide?: boolean;
  /** 回上一步的字(預設「回清單」;叫貨確認是「返回」回購物車) */
  backLabel?: string;
  children: ReactNode;
}) {
  return (
    <>
      <div className="entry-body pane-form">
        <div className="pane-form-head">
          <button type="button" className={leaveArmed ? "btn armed" : "btn"} onClick={onBack} disabled={busy}>
            {leaveArmed ? `再按一次${backLabel}` : backLabel}
          </button>
          <h3 className="pane-form-title">{title}</h3>
        </div>
        {leaveArmed && <Banner kind="info" message={LEAVE_TEXT} />}
        <div className={wide ? "pane-form-body wide" : "pane-form-body"}>{children}</div>
      </div>
      {footer && <div className="entry-footer pane-form-footer">{footer}</div>}
    </>
  );
}

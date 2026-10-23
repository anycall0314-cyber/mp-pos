// 批次貼上(進貨):把貼上的一行切成「商品 數量 單價 序號」。跑法:npm test。

/** 解析後尚未經過商品比對的原始一行 */
export interface RawRow {
  raw: string; // 使用者貼進來的原文,用於提示
  rawProductText: string;
  qty: number;
  unit_price: string;
  serials: string[];
}

/**
 * 切割「商品 數量 單價 序號」一行(支援 Tab、多個空白、逗號)。
 * 從 Excel 複製的(Tab 分隔)只認第四格是序號:後面還有別的欄(成色、售價…)時不能被當成序號
 * (2026-10-14 修:中古機的範例寫了成色、售價、電池、備註,貼進來全變成序號)。
 */
export function parseLine(line: string): RawRow | null {
  const t = line.trim();
  if (!t) return null;
  // 優先用 Tab,再用 ; 等切;最後 fallback 多空白
  let parts: string[];
  const tabbed = t.includes("\t");
  if (tabbed) {
    parts = t.split("\t");
  } else if (t.split(/\s{2,}/).length >= 2) {
    parts = t.split(/\s{2,}/);
  } else {
    parts = t.split(/[, ]+/);
  }
  parts = parts.map((p) => p.trim());

  // 至少要有商品 + 數量
  if (parts.length < 2) return null;

  const productText = parts[0];
  let qty = Number(parts[1] ?? "1");
  const unit_price = parts[2] ?? "0";
  const serialsText = tabbed ? (parts[3] ?? "") : parts.slice(3).join(" ");

  if (!Number.isFinite(qty) || qty < 1) qty = 1;

  const serials = serialsText
    .split(/[;、，,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  return {
    raw: t,
    rawProductText: productText,
    qty,
    unit_price: String(unit_price),
    serials,
  };
}

/**
 * 批次貼上對不到商品的那幾列(全站檢視 C8):按「加入」之後不能直接不見(容易少進貨),
 * 一列一筆放進掃碼框的「沒加入」—— 要逐筆加進去或明講清掉,沒處理不能存(紅隊:一顆「知道了」換不到存檔)。
 */
export function pasteLeftovers(
  rows: { rawProductText: string; productOption: unknown; qty: number; serials: string[] }[],
): { kw: string; reason: string }[] {
  return rows.flatMap((r, i) => {
    if (r.productOption) return [];
    const serials = r.serials.length > 0 ? `、序號 ${r.serials.length} 個` : "";
    return [{ kw: r.rawProductText.trim() || `第 ${i + 1} 列`, reason: `批次貼上第 ${i + 1} 列,${r.qty} 件${serials},對不到` }];
  });
}

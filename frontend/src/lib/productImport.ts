/**
 * 匯入表格(全站檢視 D7 / D8;「批次貼上」併進來)。後端規則在 backend/apps/catalog/import_service.py。
 * 這裡只管:貼上的字怎麼拆成一列一列、範例檔、什麼時候可以預覽。
 */

/** 貼上時沒有標題列的欄位順序(前四欄跟以前「批次貼上」一樣) */
export const PASTE_COLUMNS = ["品名", "規格", "建議售價", "類別", "條碼", "品號", "安全庫存"] as const;

export interface PastedTable {
  rows: Record<string, string>[];
  /** 第一列在畫面上是第幾列(有標題列 = 2) */
  firstRow: number;
}

/**
 * 從 Excel 複製(Tab 分隔)或一行一個品名。第一行有一格就叫「品名」= 那一行是標題,照標題對欄位;
 * 不然照 `PASTE_COLUMNS` 的順序。空白行不算。
 */
export function parsePaste(text: string): PastedTable {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  if (lines.length === 0) return { rows: [], firstRow: 1 };
  const cells = (line: string) => line.split("\t").map((c) => c.trim());
  const first = cells(lines[0]);
  const headed = first.includes("品名");
  const header: readonly string[] = headed ? first : PASTE_COLUMNS;
  const body = headed ? lines.slice(1) : lines;
  const rows = body.map((line) => {
    const row: Record<string, string> = {};
    cells(line).forEach((v, i) => {
      const key = header[i];
      if (key && v !== "") row[key] = v;
    });
    return row;
  });
  return { rows, firstRow: headed ? 2 : 1 };
}

/** 範例檔只有一份:標題列 + 兩列例子(配件) */
export function templateCsv(): string {
  return (
    "﻿" +
    [
      PASTE_COLUMNS.join(","),
      "犀牛盾 iPhone 17 防摔殼 黑,iPhone 17,1290,,,,",
      "Type-C 快充線 1M,1M,390,,,,",
    ].join("\n") +
    "\n"
  );
}

export type SerialChoice = "" | "qty" | "serial";

/** 哪一個條件還沒好(都好了 = null)。主機類別、中古機類別不收 */
export function previewBlocker(s: {
  category: { holds_devices: boolean; is_secondhand_default: boolean } | null;
  serial: SerialChoice;
  hasRows: boolean;
}): string | null {
  if (!s.category) return "請先選類別";
  if (s.category.holds_devices || s.category.is_secondhand_default) return "手機、平板、穿戴請用「手機型號」建";
  if (!s.serial) return "請選按數量或逐件記序號";
  if (!s.hasRows) return "請貼上表格或選擇檔案";
  return null;
}

import { CSV_BOM, toCsv } from "@/lib/csv";

/** 把一張表存成試算表開得了的檔。內容怎麼寫(長數字、開頭是 0 的號碼)在 `lib/csv.ts`。 */
export function downloadCsv(filename: string, table: unknown[][]) {
  const blob = new Blob([CSV_BOM + toCsv(table)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

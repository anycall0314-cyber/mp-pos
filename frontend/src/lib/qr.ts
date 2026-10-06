import qrcode from "qrcode-generator";

/** 把一段文字畫成 QR Code:回每一格是黑是白(含四周留白),給 <svg> 畫 */
export function qrMatrix(text: string): boolean[][] {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const quiet = 4; // 四周要留白,相機才認得出來
  const size = n + quiet * 2;
  return Array.from({ length: size }, (_, y) =>
    Array.from({ length: size }, (_, x) => {
      const r = y - quiet;
      const c = x - quiet;
      return r >= 0 && c >= 0 && r < n && c < n && qr.isDark(r, c);
    }),
  );
}

/** <path d> 用的字串:每個黑格一個 1×1 的方塊 */
export function qrPath(matrix: boolean[][]): string {
  const parts: string[] = [];
  matrix.forEach((row, y) =>
    row.forEach((dark, x) => {
      if (dark) parts.push(`M${x} ${y}h1v1h-1z`);
    }),
  );
  return parts.join("");
}

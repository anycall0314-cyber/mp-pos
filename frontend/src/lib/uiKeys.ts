/**
 * 分頁、單選列共用的方向鍵規則(docs/ui-controls.md §4):左右鍵換到前 / 後一個(到頭繞回另一頭)、Home / End 到第一個 / 最後一個;
 * 其他鍵 = null(不處理)。停用的那幾個跳過。
 */
export function nextIndex(len: number, current: number, key: string, disabled: (i: number) => boolean = () => false): number | null {
  if (len === 0) return null;
  const step = key === "ArrowRight" || key === "ArrowDown" ? 1 : key === "ArrowLeft" || key === "ArrowUp" ? -1 : 0;
  if (key === "Home" || key === "End") {
    const order = Array.from({ length: len }, (_, i) => (key === "Home" ? i : len - 1 - i));
    return order.find((i) => !disabled(i)) ?? null;
  }
  if (step === 0) return null;
  for (let n = 1; n <= len; n++) {
    const i = (((current + step * n) % len) + len) % len;
    if (!disabled(i)) return i;
  }
  return null;
}

/** 串 className:假的拿掉 */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

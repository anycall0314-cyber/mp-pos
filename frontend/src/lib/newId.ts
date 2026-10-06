/** 隨機的識別(每張照片、每支手機各一個)。舊一點的瀏覽器、非 https 的頁面沒有 `crypto.randomUUID` */
export function newId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

export function maskIdNo(idNo: string): string {
  const v = (idNo || "").trim();
  if (!v) return "—";
  if (v.length <= 4) return v[0] + "*".repeat(Math.max(0, v.length - 1));
  return `${v.slice(0, 3)}${"*".repeat(Math.max(1, v.length - 4))}${v.slice(-1)}`;
}

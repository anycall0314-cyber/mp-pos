/** 商品建檔整頁的網址(SPEC-005):商品頁「先找有沒有建過」找的那一句帶到新分頁,新分頁再讀回來。 */
export function newProductUrl(prefill?: { name?: string; barcode?: string } | null): string {
  const q = new URLSearchParams();
  if (prefill?.name?.trim()) q.set("name", prefill.name.trim());
  if (prefill?.barcode?.trim()) q.set("barcode", prefill.barcode.trim());
  const s = q.toString();
  return s ? `/products/new?${s}` : "/products/new";
}

export function prefillFromParams(params: URLSearchParams): { name: string; barcode: string } {
  return { name: params.get("name") ?? "", barcode: params.get("barcode") ?? "" };
}

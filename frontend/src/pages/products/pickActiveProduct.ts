import { restoreProduct } from "@/api/search";
import type { Product } from "@/api/types";

/**
 * 選到已停用的商品時,先問一次再恢復。
 *
 * 已停用的商品在候選裡看得到(讓人知道它建過檔、不要重建),但不會因為
 * 被選到就悄悄恢復。一般店員的選項本來就點不下去;走到這裡的是管理員。
 *
 * 回傳可以用的商品;使用者取消回 null。恢復失敗會丟錯,由呼叫端顯示。
 */
export async function pickActiveProduct(
  product: Product,
  action = "入庫",
): Promise<Product | null> {
  if (product.is_active !== false) return product;
  if (!confirm(`「${product.name}」已停用,要恢復並${action}嗎?`)) return null;
  return restoreProduct(product.id);
}

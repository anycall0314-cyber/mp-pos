import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { useProduct } from "@/api/hooks";
import type { Product } from "@/api/types";
import { Toolbar } from "@/components/Toolbar";
import { usePhotoPeek } from "@/components/photos/PhotoName";
import { toast } from "@/components/workbench/toast";
import { prefillFromParams } from "@/lib/productFormUrl";
import { returnTarget } from "@/lib/productListReturn";
import { backToOpener, tellOpener } from "@/lib/productTabs";
import { purchaseLinkFor } from "@/lib/purchasePrefill";
import { ProductForm } from "./ProductForm";

/**
 * 商品建檔整頁:`/products/new`(新增,通常是商品頁另開的分頁)、`/products/:id/edit`(編輯)。
 * SPEC-005,owner 2026-10-18:「目前卡在一個小小的 modal 視窗裡，卡著變成當下只能做一件事，做完才能離開做其他」。
 * 新增時先帶的字從網址來(`?name=…&barcode=…`,商品頁「先找有沒有建過」找的那一句)。
 */
export function ProductFormPage() {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const [params] = useSearchParams();
  const nav = useNavigate();
  const product = useProduct(editId != null && Number.isFinite(editId) ? editId : null);
  const peek = usePhotoPeek();
  // 編輯:讀到的那一份固定下來(表單只在打開那一刻照它填;之後重新讀到新的一份不能把打到一半的洗掉)
  const [initial, setInitial] = useState<Product | null>(null);
  useEffect(() => {
    if (product.data && !initial) setInitial(product.data);
  }, [product.data, initial]);
  const [saved, setSaved] = useState<Product | null>(null);
  // 「再建一個」:表單重新開一次(沿用上一筆的類別)
  const [round, setRound] = useState(0);
  // 「再建一個」沿用上一筆的類別、商品性質、廠牌(紅隊:一天建幾十個配件,這幾格要留;品名、條碼、售價、相容機型清掉)
  const [nextCategory, setNextCategory] = useState<{
    category: { id: number; label: string; secondary?: string };
    accessory_type: Product["accessory_type"];
    brand: number | "";
  } | null>(null);
  const prefill = useMemo(
    () =>
      editId
        ? null
        : round === 0
          ? prefillFromParams(params)
          : nextCategory
            ? {
                category: nextCategory.category,
                accessory_type: nextCategory.accessory_type ?? undefined,
                brand: nextCategory.brand,
              }
            : null,
    [editId, round, params, nextCategory],
  );

  // 表單存好(或改用既有的)之後還會叫一次「關閉」:那一次不算人按取消,不能把分頁關掉
  const done = useRef(false);
  // 從商品管理點「編輯」進來的(帶著那一頁的鑰匙):存好 / 取消回上一頁,清單照原樣(全站檢視 R07);直接打網址進來的去商品頁選到這一筆
  const location = useLocation();
  const backToList = (selected?: number) => {
    const to = returnTarget(
      (location.state as { listKey?: unknown } | null)?.listKey,
      (window.history.state as { idx?: unknown } | null)?.idx,
      selected,
    );
    if (to === -1) nav(-1);
    else nav(to);
  };
  // 從商品頁另開的分頁:取消就關掉這一頁(回到原本那一頁);直接打網址進來的回商品頁
  const leave = () => {
    if (done.current) {
      done.current = false;
      return;
    }
    if (!editId && window.opener) {
      window.close();
      return;
    }
    backToList(editId ?? undefined);
  };

  if (editId != null) {
    if (product.isLoading || (product.data && !initial)) {
      return (
        <div className="page">
          <Toolbar title="編輯商品" />
          <div className="md-empty">載入中…</div>
        </div>
      );
    }
    if (!initial) {
      return (
        <div className="page">
          <Toolbar title="編輯商品" />
          <div className="md-empty">找不到商品</div>
        </div>
      );
    }
  }

  if (saved) {
    const to = purchaseLinkFor([saved]);
    return (
      <div className="page">
        <Toolbar title="新增商品" />
        <div className="entry-body">
          <div className="pf-saved">
            <div className="pf-saved-title">
              已建立 {saved.sku} {saved.name}
            </div>
            <div className="pf-saved-actions">
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  setNextCategory(
                    saved.category
                      ? {
                          category: { id: saved.category, label: saved.category_name, secondary: "" },
                          accessory_type: saved.accessory_type,
                          brand: saved.brand ?? "",
                        }
                      : null,
                  );
                  setSaved(null);
                  setRound((r) => r + 1);
                }}
              >
                再建一個
              </button>
              {to && (
                <button type="button" className="btn" onClick={() => nav(to)}>
                  去開進貨
                </button>
              )}
              <button
                type="button"
                className="btn"
                onClick={() => {
                  if (!backToOpener(saved.id)) backToList(saved.id);
                }}
              >
                回商品頁
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <ProductForm
        key={`${editId ?? "new"}-${round}`}
        asPage
        open
        initial={editId ? initial : null}
        prefill={prefill}
        onPeek={peek.open}
        peeking={peek.isOpen}
        onClose={leave}
        onSaved={(p) => {
          done.current = true;
          if (editId) {
            backToList(p.id);
            return;
          }
          // 原本那一頁(商品管理)的清單同時更新、選到這一筆;這一頁留著「再建一個 / 去開進貨 / 回商品頁」
          tellOpener(p.id);
          setSaved(p);
        }}
        onUseExisting={(existing, note) => {
          done.current = true;
          if (note) toast(note.text, note.tone, { ms: 6000 });
          // 改用另一個既有商品:去商品頁選到那一個(不是回原本的清單)
          nav(`/products?selected=${existing}`);
        }}
      />
      {peek.panel}
    </>
  );
}

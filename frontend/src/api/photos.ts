/**
 * 商品照片(圖片備註)的 API。規則在後端 `apps/photos/services.py`。
 *
 * - 電腦:照片先放在一份「照片作業」(draft)上,商品儲存時把定下來的清單一起送(`photos` 欄位),
 *   同一個交易掛到商品。取消 = 作業丟掉,商品原本的照片不動。
 * - 手機:掃 QR Code 拿到一把只能「對這一份作業傳照片」的憑證,不用登入。
 */
import { api } from "./client";

export interface ProductPhoto {
  id: number;
  caption: string;
  is_primary: boolean;
  sort: number;
  width: number;
  height: number;
  image_url: string;
  thumb_url: string;
}

export type UploadStatus = "uploading" | "ready" | "failed" | "cancelled";

export interface DraftUpload {
  uid: string;
  status: UploadStatus;
  source: "desktop" | "phone";
  error: string;
  width: number;
  height: number;
  image_url?: string;
  thumb_url?: string;
}

/** none 沒在配對 / waiting 等手機掃 / expired QR 過期沒人掃 / connected 手機連著 / idle 手機太久沒動作 */
export type PairStatus = "none" | "waiting" | "expired" | "connected" | "idle";

export interface PhotoDraft {
  uid: string;
  state: "open" | "committed" | "cancelled";
  frozen: boolean;
  label: string;
  spec: string;
  product: number | null;
  max_photos: number;
  pair: { status: PairStatus; expires_at: string | null; received: number };
  uploads: DraftUpload[];
  /** 只有剛按「用手機拍照 / 更新 QR Code」那一次回來才有 */
  pair_token?: string;
}

/** 商品儲存時一起送的照片清單:順序就是顯示順序;商品原本有、這裡沒列的 = 移除 */
export type PhotoItem = ({ photo: number } | { upload: string }) & {
  caption: string;
  is_primary: boolean;
};
export interface PhotosPayload {
  draft: string;
  /** 開表單時這個商品有哪幾張照片(編號)。這段時間別人改過照片,伺服器會擋下、請人重開表單 */
  seen: number[];
  items: PhotoItem[];
}

export const listProductPhotos = (productId: number) =>
  api<ProductPhoto[]>(`/product-photos/?product=${productId}`);

export const createPhotoDraft = (body: {
  product?: number;
  label: string;
  spec: string;
}) => api<PhotoDraft>("/photo-drafts/", { method: "POST", body: JSON.stringify(body) });

export const getPhotoDraft = (uid: string) => api<PhotoDraft>(`/photo-drafts/${uid}/`);

export const renamePhotoDraft = (uid: string, label: string, spec: string) =>
  api<PhotoDraft>(`/photo-drafts/${uid}/`, {
    method: "PATCH",
    body: JSON.stringify({ label, spec }),
  });

export type DraftAction =
  | "pair"
  | "unpair"
  | "freeze"
  | "unfreeze"
  | "cancel"
  | "cancel-upload";

export const photoDraftAction = (uid: string, action: DraftAction, body?: object) =>
  api<PhotoDraft>(`/photo-drafts/${uid}/${action}/`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });

export function uploadDraftPhoto(draftUid: string, uploadUid: string, file: Blob) {
  const form = new FormData();
  form.append("uid", uploadUid);
  form.append("file", file, "photo.jpg");
  return api<DraftUpload>(`/photo-drafts/${draftUid}/uploads/`, {
    method: "POST",
    body: form,
  });
}

// ── 手機這一端(不用登入:帶 QR Code 的憑證與這支手機自己的識別) ──
export interface PhoneState {
  label: string;
  spec: string;
  sku: string;
  frozen: boolean;
  uploads: { uid: string; status: UploadStatus; error: string; thumb_url?: string }[];
}

export class PhonePairError extends Error {
  /** gone / expired = 這次配對已經不能用了;taken = 別支手機連著;frozen = 電腦正在儲存 */
  code: string;
  constructor(message: string, code: string) {
    super(message);
    this.code = code;
  }
}

const BASE = import.meta.env.VITE_API_BASE || "/api/v1";

export async function phoneCall(
  token: string,
  device: string,
  action: "claim" | "state" | "announce" | "upload" | "cancel" | "finish",
  body?: { uid?: string; file?: Blob },
): Promise<PhoneState> {
  const headers: Record<string, string> = {
    "X-Pair-Token": token,
    "X-Pair-Device": device,
  };
  let payload: BodyInit | undefined;
  if (body?.file) {
    const form = new FormData();
    form.append("uid", body.uid ?? "");
    form.append("file", body.file, "photo.jpg");
    payload = form;
  } else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify({ uid: body.uid });
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}/photo-pair/${action}/`, {
      method: action === "state" ? "GET" : "POST",
      headers,
      body: payload,
      // 這個網址每一次配對都一樣(憑證在標頭):絕不能拿瀏覽器留著的舊回應。
      // 瀏覽器會把「410 已經不在了」永久記住,上一次配對的「已結束」會被拿來回答這一次
      cache: "no-store",
    });
  } catch {
    throw new PhonePairError("連不上,請確認手機網路後再試", "network");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new PhonePairError(
      String(data?.detail ?? "沒有成功,請再試一次"),
      String(data?.code ?? (res.status >= 500 ? "network" : "invalid")),
    );
  }
  return data as PhoneState;
}

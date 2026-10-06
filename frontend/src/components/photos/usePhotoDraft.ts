import { useEffect, useRef, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  createPhotoDraft,
  getPhotoDraft,
  listProductPhotos,
  PairStatus,
  PhotoDraft,
  photoDraftAction,
  PhotosPayload,
  renamePhotoDraft,
  uploadDraftPhoto,
} from "@/api/photos";
import { shrinkImage } from "@/lib/imageShrink";
import { newId } from "@/lib/newId";

/** 照片區的一格 */
export interface PhotoTile {
  /** "p:編號" = 商品已經存好的照片;"u:識別" = 這次新加的 */
  key: string;
  id?: number;
  uid?: string;
  status: "ready" | "uploading" | "failed";
  source: "saved" | "desktop" | "phone";
  thumb?: string;
  image?: string;
  caption: string;
  /** 已經存好的照片標成「這次要移除」:儲存才生效,取消就還原 */
  removed: boolean;
  error?: string;
  /** 電腦選的檔案留著,失敗可以原地重試 */
  file?: Blob;
}

interface Options {
  /** 表單開著才動作 */
  active: boolean;
  /** 編輯既有商品;新增是 null */
  productId: number | null;
  /** 給手機看的品名 / 規格(改了會同步過去) */
  label: string;
  spec: string;
}

/**
 * 一份照片作業「記得住」的部分:哪一份作業、順序、說明、主圖(照片檔本身在伺服器)。
 * 新增商品的表單把它跟欄位**放在同一份草稿裡一起存**(「存成草稿先離開」再回來要一起接回來;
 * 分開記的話,兩個分頁會湊出「這一頁的欄位 + 那一頁的照片」)。
 */
export interface PhotoStored {
  uid: string;
  order: string[];
  captions: Record<string, string>;
  primary: string | null;
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * 商品表單裡的照片:一份「照片作業」。
 *
 * 照片先掛在作業上(不是掛在商品上):新增商品還沒有品號也能先加;商品儲存時把定下來的清單
 * (`payload()`)一起送,同一次存檔掛上去。取消表單 = `cancel()`,商品原本的照片不動。
 * 手機拍的照片由伺服器收,這裡每兩秒問一次有沒有新的(配對中才問)。
 */
export function usePhotoDraft({
  active,
  productId,
  label,
  spec,
}: Options) {
  const [tiles, setTiles] = useState<PhotoTile[]>([]);
  const [primaryKey, setPrimaryKey] = useState<string | null>(null);
  const [draft, setDraft] = useState<PhotoDraft | null>(null);
  const [pairToken, setPairToken] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  /** 商品原本的照片載入好了沒(新增商品沒有原本的照片,一開始就是好的) */
  const [loaded, setLoadedState] = useState(true);
  const loadedRef = useRef(true);
  function setLoaded(value: boolean) {
    loadedRef.current = value;   // 當下就改:存檔前的檢查是馬上讀的,不能等畫面更新
    setLoadedState(value);
  }
  const [reloadTick, setReloadTick] = useState(0);
  /** 正在把上次的照片作業接回來(這段時間不能存檔、也不要把「現在沒有作業」記進草稿) */
  const [resuming, setResuming] = useState(false);
  const resumeJob = useRef<Promise<unknown> | null>(null);
  /**
   * 上次的照片沒接回來(斷線之類,還可以再試)的那一份。有值的時候不能存檔、不能加照片:
   * 這時候存下去,草稿裡的照片就漏掉了。按「重試」再接一次,或按「不要了」明講不接。
   */
  const [resumeFailed, setResumeFailedState] = useState<PhotoStored | null>(null);
  /**
   * 跟上面那個 state 同一個值,但**當下就改**(state 要等下一次畫面更新才看得到)。
   * `beforeSave()` 是等接回的工作做完之後馬上判斷的,那一刻畫面還沒更新:只看 state 的話會看到舊的「沒有失敗」而放行。
   */
  const resumeFailedRef = useRef<PhotoStored | null>(null);
  function setResumeFailed(value: PhotoStored | null) {
    resumeFailedRef.current = value;
    setResumeFailedState(value);
  }
  /** 開表單時這個商品有哪幾張照片:存檔時一起送,伺服器拿來確認「這段時間沒有別人改過照片」 */
  const seenIds = useRef<number[]>([]);
  const [max, setMax] = useState(10);

  const tilesRef = useRef<PhotoTile[]>([]);
  tilesRef.current = tiles;
  const draftUid = useRef<string | null>(null);
  const creating = useRef<Promise<string> | null>(null);
  /** 這次被拿掉的(手機傳來的也算):伺服器再報它也不放回來 */
  const dropped = useRef(new Set<string>());
  const previews = useRef<string[]>([]);
  const alive = useRef(true);
  /**
   * 「這一次編輯」的編號。表單關掉 / 換商品 / 存好 / 取消都會換一號。
   * 表單元件一直掛在頁面上(關掉只是藏起來),上一次編輯還沒回來的請求(開作業、上傳、配對)回來時
   * 編號已經不一樣 → 整個丟掉,不能併進現在這一次(會變成上一筆商品的照片出現在下一筆)。
   */
  const gen = useRef(0);
  const labelRef = useRef({ label, spec });
  labelRef.current = { label, spec };

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      previews.current.forEach((u) => URL.revokeObjectURL(u));
    };
  }, []);

  function patchTile(key: string, fn: (t: PhotoTile) => PhotoTile) {
    setTiles((cur) => cur.map((t) => (t.key === key ? fn(t) : t)));
  }

  /** 伺服器那邊的作業狀態併進來:手機新傳的加一格,既有的更新狀態 */
  function merge(state: PhotoDraft) {
    if (!alive.current) return;
    setDraft(state);
    setMax(state.max_photos);
    setTiles((cur) => {
      const next = [...cur];
      for (const u of state.uploads) {
        const key = `u:${u.uid}`;
        let at = next.findIndex((t) => t.key === key);
        if (u.status === "cancelled") {
          // 手機那邊把這一張拿掉了:電腦這邊跟著拿掉(留著的話存檔會帶到一張已經不在的照片)
          if (at >= 0 && next[at].source === "phone") next.splice(at, 1);
          continue;
        }
        if (dropped.current.has(key)) continue;
        at = next.findIndex((t) => t.key === key);
        // 電腦自己傳的那幾格由這一頁自己管(傳到哪了、失敗原因);這裡只接手機傳的。
        // 畫面上沒有、又不是手機傳的(上一次開表單時沒傳完的):不是這一次的東西,不放進來
        if (at >= 0 ? next[at].source !== "phone" : u.source !== "phone") continue;
        const tile: PhotoTile = {
          key,
          uid: u.uid,
          status: u.status === "ready" ? "ready" : u.status === "failed" ? "failed" : "uploading",
          source: "phone",
          thumb: u.thumb_url,
          image: u.image_url,
          caption: at >= 0 ? next[at].caption : "",
          removed: false,
          error: u.error || undefined,
        };
        if (at >= 0) next[at] = tile;
        else next.push(tile);
      }
      return next;
    });
  }

  // 開表單:載入商品已經存好的照片
  useEffect(() => {
    // 關掉也要換一號:上一次編輯晚到的回應從這一刻起都不算數
    gen.current++;
    if (!active) return;
    let cancelled = false;
    setTiles([]);
    setPrimaryKey(null);
    setDraft(null);
    setPairToken(null);
    setTouched(false);
    setLoadError(null);
    setLoaded(!productId);
    setResuming(false);
    setResumeFailed(null);
    resumeJob.current = null;
    seenIds.current = [];
    draftUid.current = null;
    creating.current = null;
    dropped.current = new Set();
    (async () => {
      try {
        if (productId) {
          const saved = await listProductPhotos(productId);
          if (cancelled) return;
          setTiles(
            saved.map((p) => ({
              key: `p:${p.id}`,
              id: p.id,
              status: "ready" as const,
              source: "saved" as const,
              thumb: p.thumb_url,
              image: p.image_url,
              caption: p.caption,
              removed: false,
            })),
          );
          const main = saved.find((p) => p.is_primary);
          setPrimaryKey(main ? `p:${main.id}` : null);
          seenIds.current = saved.map((p) => p.id);
          setLoaded(true);
        }
      } catch (e) {
        if (!cancelled) setLoadError(errText(e));
      }
    })();
    return () => {
      cancelled = true;
    };
    // 只在開表單 / 換商品 / 按「重試」時重來
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, productId, reloadTick]);

  /** 現在這一份作業要記進草稿的樣子(還沒有作業就是 null) */
  function snapshot(): PhotoStored | null {
    if (!draftUid.current) return null;
    return {
      uid: draftUid.current,
      order: tiles.filter((t) => t.uid).map((t) => t.key),
      captions: Object.fromEntries(tiles.filter((t) => t.caption).map((t) => [t.key, t.caption])),
      primary: primaryKey,
    };
  }

  /** 「載入草稿」:把上次那份照片作業接回來。回一句話 = 接不回來的原因 */
  /**
   * 「載入草稿」:照片整個換成草稿裡記的那一份(草稿裡沒有照片就是清空)。
   * 載入之前如果已經在這張表單上加了別的照片,那一份丟掉 —— 不然會變成「草稿的欄位 + 剛才另外加的照片」存成同一個商品。
   */
  function switchTo(stored: PhotoStored | null): Promise<string | null> {
    const next = stored && typeof stored.uid === "string" ? stored : null;
    if (next && next.uid === draftUid.current) return Promise.resolve(null);
    // 換一號:現在這一份還在路上的請求(開作業、上傳、配對)從這一刻起都不算數
    gen.current++;
    const old = draftUid.current;
    draftUid.current = null;
    creating.current = null;
    dropped.current = new Set();
    setTiles([]);
    setPrimaryKey(null);
    setDraft(null);
    setPairToken(null);
    setTouched(false);
    setResumeFailed(null);
    if (old) void photoDraftAction(old, "cancel").catch(() => undefined);
    return next ? resumeFrom(next) : Promise.resolve(null);
  }

  /** 把一份記著的照片作業接回來(`switchTo`、「重試」用)。回一句話 = 沒接成的原因 */
  function resumeFrom(stored: PhotoStored): Promise<string | null> {
    const g = gen.current;
    setResuming(true);
    setResumeFailed(null);
    const job = resumeNow(stored, g).finally(() => {
      if (resumeJob.current === job) resumeJob.current = null;
      if (g === gen.current && alive.current) setResuming(false);
    });
    resumeJob.current = job;
    return job;
  }

  async function resumeNow(stored: PhotoStored, g: number): Promise<string | null> {
    const order = Array.isArray(stored.order) ? stored.order : [];
    const captions = stored.captions && typeof stored.captions === "object" ? stored.captions : {};
    try {
      const state = await getPhotoDraft(stored.uid);
      if (!alive.current || g !== gen.current) return null;
      if (state.state !== "open") {
        return "上次的照片已經不在了(只接回欄位)";
      }
      draftUid.current = state.uid;
      // 上一次從電腦傳到一半 / 沒傳成功的:檔案不在這一頁了,補不回來,直接取消(不然會卡住儲存)
      for (const u of state.uploads) {
        if (u.source === "desktop" && (u.status === "uploading" || u.status === "failed")) {
          void photoDraftAction(state.uid, "cancel-upload", { uid: u.uid }).catch(() => undefined);
        }
      }
      const ready = state.uploads.filter((u) => u.status === "ready");
      const rank = (key: string) => {
        const at = order.indexOf(key);
        return at < 0 ? order.length : at;
      };
      const back: PhotoTile[] = ready
        .map((u) => ({
          key: `u:${u.uid}`,
          uid: u.uid,
          status: "ready" as const,
          // 檔案已經在伺服器上:之後的狀態由伺服器那邊為準
          source: "phone" as const,
          thumb: u.thumb_url,
          image: u.image_url,
          caption: captions[`u:${u.uid}`] ?? "",
          removed: false,
        }))
        .sort((x, y) => rank(x.key) - rank(y.key));
      setTiles(back);
      setPrimaryKey(
        back.some((t) => t.key === stored.primary) ? stored.primary : (back[0]?.key ?? null),
      );
      setDraft(state);
      setMax(state.max_photos);
      setTouched(true);
      return null;
    } catch (e) {
      if (g !== gen.current) return null;
      // 過期被清掉了:照片真的不在了,當作沒有(欄位照樣可以用)
      if (e instanceof ApiHttpError && (e.status === 410 || e.status === 404)) {
        return "上次的照片已經過期(只接回欄位)";
      }
      // 連不上之類:照片還在伺服器上,記著是哪一份,等人按「重試」
      setResumeFailed(stored);
      return `上次的照片沒有接回來:${errText(e)}`;
    }
  }

  /** 沒接回來的那一份:再試一次 */
  function retryResume() {
    const stored = resumeFailedRef.current;
    if (stored) void resumeFrom(stored);
  }

  /** 沒接回來的那一份:明講不要了(之後存檔就是不帶那些照片) */
  function giveUpResume() {
    const stored = resumeFailedRef.current;
    setResumeFailed(null);
    dropStored(stored);
  }

  /** 「捨棄草稿」:草稿裡記著的那份照片作業也請伺服器丟掉(現在正在用的這一份不動) */
  function dropStored(stored: PhotoStored | null) {
    if (stored && typeof stored.uid === "string" && stored.uid !== draftUid.current) {
      void photoDraftAction(stored.uid, "cancel").catch(() => undefined);
    }
  }

  // 主圖一定指著一張還在的照片:原本那張被拿掉(包含手機那邊拿掉)、沒傳成功、或第一張是手機傳來的,
  // 就換成第一張好的。沒有照片就沒有主圖
  useEffect(() => {
    if (
      primaryKey &&
      tiles.some((t) => t.key === primaryKey && !t.removed && t.status !== "failed")
    ) {
      return;
    }
    const next = tiles.find((t) => !t.removed && t.status === "ready")?.key ?? null;
    if (next !== primaryKey) setPrimaryKey(next);
  }, [tiles, primaryKey]);

  /** 第一次要用到作業時才開(只是看看照片不會開) */
  function ensureDraft(): Promise<string> {
    if (draftUid.current) return Promise.resolve(draftUid.current);
    if (!creating.current) {
      const g = gen.current;
      const job = createPhotoDraft({
        ...(productId ? { product: productId } : {}),
        label: labelRef.current.label,
        spec: labelRef.current.spec,
      }).then((state) => {
        if (g !== gen.current) {
          // 作業開好之前表單已經關掉 / 換成別的商品:這一份沒有人要了,請伺服器丟掉
          void photoDraftAction(state.uid, "cancel").catch(() => undefined);
          throw new Error("表單已經關閉");
        }
        draftUid.current = state.uid;
        if (alive.current) {
          setDraft(state);
          setMax(state.max_photos);
        }
        return state.uid;
      });
      creating.current = job;
      job.catch(() => {
        if (creating.current === job) creating.current = null;
      });
    }
    return creating.current;
  }

  // 品名 / 規格改了:手機那邊顯示的名稱跟著改(還是同一份作業,不用重新掃)
  useEffect(() => {
    if (!active || !draftUid.current) return;
    const uid = draftUid.current;
    const handle = window.setTimeout(() => {
      renamePhotoDraft(uid, label, spec).catch(() => {
        /* 名稱沒同步到不影響拍照 */
      });
    }, 700);
    return () => window.clearTimeout(handle);
  }, [active, label, spec, draft?.uid]);

  // 手機配對中:每兩秒問一次有沒有新照片
  const pairStatus: PairStatus = draft?.pair.status ?? "none";
  const phoneBusy = tiles.some((t) => t.source === "phone" && t.status === "uploading");
  const watching =
    active && !!draft && (pairStatus === "waiting" || pairStatus === "connected" || phoneBusy);
  useEffect(() => {
    if (!watching || !draftUid.current) return;
    const uid = draftUid.current;
    let stopped = false;
    let handle = 0;
    const tick = async () => {
      try {
        const state = await getPhotoDraft(uid);
        if (!stopped) merge(state);
      } catch {
        /* 這一次沒問到,下一次再問 */
      }
      if (!stopped) handle = window.setTimeout(tick, 2000);
    };
    handle = window.setTimeout(tick, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(handle);
    };
    // merge 只用到 ref 與 setState
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watching]);

  // ── 電腦選照片 ──
  async function send(key: string, uploadUid: string, file: Blob) {
    const g = gen.current;
    try {
      const uid = await ensureDraft();
      const small = await shrinkImage(file);
      if (g !== gen.current) return;
      const saved = await uploadDraftPhoto(uid, uploadUid, small);
      // 傳的這段時間表單關了 / 換商品了:這一張是上一次編輯的,不能出現在現在的畫面上
      if (g !== gen.current || dropped.current.has(key)) return;
      patchTile(key, (t) => ({
        ...t,
        status: "ready",
        thumb: saved.thumb_url,
        image: saved.image_url,
        error: undefined,
      }));
    } catch (e) {
      if (g !== gen.current || dropped.current.has(key)) return;
      patchTile(key, (t) => ({ ...t, status: "failed", error: errText(e) }));
    }
  }

  function addFiles(files: File[]): string | null {
    // 原本的照片沒載到就不給加:這時候存檔,清單裡只有新加的,原本的會被當成「移除」
    if (!loadedRef.current) return "原本的照片還沒載入,先按重試";
    if (resumeJob.current || resumeFailedRef.current) return "上次的照片還沒接回來";
    const room = max - tilesRef.current.filter((t) => !t.removed).length;
    if (room <= 0) return `最多 ${max} 張`;
    const take = files.slice(0, room);
    const fresh: PhotoTile[] = take.map((file) => {
      const uid = newId();
      const preview = URL.createObjectURL(file);
      previews.current.push(preview);
      return {
        key: `u:${uid}`,
        uid,
        status: "uploading",
        source: "desktop",
        thumb: preview,
        image: preview,
        caption: "",
        removed: false,
        file,
      };
    });
    setTouched(true);
    setTiles((cur) => [...cur, ...fresh]);
    // 第一張成功加入的照片是預設的主圖(之後可以改)
    setPrimaryKey((cur) => cur ?? fresh[0]?.key ?? null);
    for (const t of fresh) void send(t.key, t.uid!, t.file!);
    return take.length < files.length ? `最多 ${max} 張,多的沒有加` : null;
  }

  function retry(key: string) {
    const t = tilesRef.current.find((x) => x.key === key);
    if (!t?.file || !t.uid) return;
    patchTile(key, (x) => ({ ...x, status: "uploading", error: undefined }));
    void send(key, t.uid, t.file);
  }

  /** 拿掉一格。已經存好的照片只是標記(儲存才生效);這次新加的直接取消 */
  function remove(key: string) {
    const t = tilesRef.current.find((x) => x.key === key);
    if (!t) return;
    setTouched(true);
    if (t.source === "saved") {
      patchTile(key, (x) => ({ ...x, removed: true }));
      void ensureDraft().catch(() => undefined);
    } else {
      dropped.current.add(key);
      setTiles((cur) => cur.filter((x) => x.key !== key));
      if (t.uid) {
        // 伺服器記下「這一張取消了」:晚到的上傳不會讓它又出現
        void ensureDraft()
          .then((uid) => photoDraftAction(uid, "cancel-upload", { uid: t.uid }))
          .catch(() => undefined);
      }
    }
    setPrimaryKey((cur) => {
      if (cur !== key) return cur;
      const next = tilesRef.current.find(
        (x) => x.key !== key && !x.removed && x.status === "ready",
      );
      return next?.key ?? null;
    });
  }

  function restore(key: string) {
    patchTile(key, (x) => ({ ...x, removed: false }));
    setPrimaryKey((cur) => cur ?? key);
  }

  function setCaption(key: string, caption: string) {
    setTouched(true);
    patchTile(key, (x) => ({ ...x, caption }));
    void ensureDraft().catch(() => undefined);
  }

  function setPrimary(key: string) {
    setTouched(true);
    setPrimaryKey(key);
    void ensureDraft().catch(() => undefined);
  }

  function move(key: string, step: -1 | 1) {
    setTouched(true);
    setTiles((cur) => {
      const at = cur.findIndex((t) => t.key === key);
      const to = at + step;
      if (at < 0 || to < 0 || to >= cur.length) return cur;
      const next = [...cur];
      [next[at], next[to]] = [next[to], next[at]];
      return next;
    });
    void ensureDraft().catch(() => undefined);
  }

  // ── 手機拍照 ──
  async function startPair(): Promise<string | null> {
    if (!loadedRef.current) return "原本的照片還沒載入,先按重試";
    if (resumeJob.current || resumeFailedRef.current) return "上次的照片還沒接回來";
    const g = gen.current;
    try {
      const uid = await ensureDraft();
      const state = await photoDraftAction(uid, "pair");
      if (g !== gen.current) return null;
      merge(state);
      setTouched(true);
      setPairToken(state.pair_token ?? null);
      return null;
    } catch (e) {
      return errText(e);
    }
  }

  async function endPair() {
    setPairToken(null);
    if (!draftUid.current) return;
    const g = gen.current;
    try {
      const state = await photoDraftAction(draftUid.current, "unpair");
      if (g === gen.current) merge(state);
    } catch {
      /* 結束不了就等它自己過期 */
    }
  }

  // ── 跟著商品存檔 ──
  const shown = tiles.filter((t) => !t.removed);
  const pending = shown.filter((t) => t.status === "uploading").length;
  const failed = shown.filter((t) => t.status === "failed").length;

  /** 存商品之前:照片都好了沒。回一句話 = 還不能存;回 null = 可以(作業已經先停收新照片) */
  async function beforeSave(): Promise<string | null> {
    if (pending > 0) return `還有 ${pending} 張照片尚未完成,等傳完或移除之後再儲存`;
    if (failed > 0) return `有 ${failed} 張照片沒有傳成功,請重試或移除之後再儲存`;
    if (shown.length > max) return `最多 ${max} 張照片,請移掉 ${shown.length - max} 張再儲存`;
    // 上次的照片還在接回來:等它(沒接完就存,草稿裡的照片會漏掉)
    if (resumeJob.current) await resumeJob.current.catch(() => undefined);
    if (resumeFailedRef.current) {
      return "上次的照片還沒接回來。請在照片區按「重試」,或按「不要了」之後再儲存";
    }
    // 動過照片(改主圖、說明、移除…)但作業還沒開好 / 剛才沒開成:這裡等它開好。
    // 開不成就不給存 —— 不然送出去的是「照片沒動」,剛才改的悄悄沒存
    if (touched && !draftUid.current) {
      try {
        await ensureDraft();
      } catch (e) {
        return `照片還沒準備好,請再按一次儲存(${errText(e)})`;
      }
    }
    if (!draftUid.current) return null;
    // 原本的照片沒載到卻動了照片:存下去原本的會被整批移除,不給存
    if (!loadedRef.current) return "原本的照片沒有載入成功,這次不能改照片;請關掉表單再開一次";
    const g = gen.current;
    try {
      const state = await photoDraftAction(draftUid.current, "freeze");
      if (g !== gen.current) return "表單已經關閉";
      merge(state);
      // 只看手機傳的、與這一頁自己傳的(畫面上有那一格);其他的不是這一次的東西
      const known = new Set(tilesRef.current.map((t) => t.key));
      const mine = (u: { uid: string; source: string }) =>
        (u.source === "phone" || known.has(`u:${u.uid}`)) && !dropped.current.has(`u:${u.uid}`);
      const late = state.uploads.filter((u) => u.status === "uploading" && mine(u)).length;
      if (late > 0) {
        await photoDraftAction(draftUid.current, "unfreeze").catch(() => undefined);
        return `手機還有 ${late} 張照片在傳,等傳完或移除之後再儲存`;
      }
      // 停收之前手機剛好傳完的:清單裡要看得到才送(畫面上沒有的不會悄悄跟著存)
      const unseen = state.uploads.filter(
        (u) => u.status === "ready" && u.source === "phone" && !known.has(`u:${u.uid}`) && mine(u),
      ).length;
      if (unseen > 0) {
        await photoDraftAction(draftUid.current, "unfreeze").catch(() => undefined);
        return `手機剛傳來 ${unseen} 張照片,看過之後再按一次儲存`;
      }
      return null;
    } catch (e) {
      if (e instanceof ApiHttpError && e.status === 410) {
        return "這次的照片已經過期,請關掉表單重新開一次";
      }
      return `照片沒準備好:${errText(e)}`;
    }
  }

  /** 商品儲存時一起送的照片清單。沒動過照片就是 undefined(商品的照片不動) */
  function payload(): PhotosPayload | undefined {
    if (!draftUid.current) return undefined;
    return {
      draft: draftUid.current,
      seen: seenIds.current,
      items: tilesRef.current
        .filter((t) => !t.removed && t.status === "ready")
        .map((t) => ({
          ...(t.id !== undefined ? { photo: t.id } : { upload: t.uid! }),
          caption: t.caption.trim(),
          is_primary: t.key === primaryKey,
        })),
    };
  }

  /** 存檔失敗:恢復編輯,手機又可以繼續傳 */
  async function saveFailed() {
    if (!draftUid.current) return;
    const g = gen.current;
    await photoDraftAction(draftUid.current, "unfreeze")
      .then((state) => {
        if (g === gen.current) merge(state);
      })
      .catch(() => undefined);
  }

  /** 存檔成功:這份作業結束了(伺服器已經把配對撤掉) */
  function saved() {
    gen.current++;
    draftUid.current = null;
    creating.current = null;
    setPairToken(null);
  }

  /** 表單不存了(取消新增 / 取消編輯 / 改用既有商品):作業丟掉,配對撤銷;商品原本的照片不動 */
  function cancel() {
    // 換一號:作業還沒開好(請求還在路上)的話,它回來時會發現編號不對、自己請伺服器丟掉
    gen.current++;
    const uid = draftUid.current;
    draftUid.current = null;
    creating.current = null;
    setPairToken(null);
    if (uid) void photoDraftAction(uid, "cancel").catch(() => undefined);
  }

  return {
    tiles,
    primaryKey,
    max,
    count: shown.length,
    pending,
    failed,
    dirty: touched,
    loadError,
    /** 可以加照片了:原本的照片載入好了,也沒有「上次的照片還在接 / 沒接回來」 */
    ready: loaded && !resuming && !resumeFailed,
    /** 載入失敗之後再試一次 */
    reload: () => setReloadTick((n) => n + 1),
    pair: {
      status: pairStatus,
      token: pairToken,
      received: draft?.pair.received ?? 0,
      expiresAt: draft?.pair.expires_at ?? null,
    },
    addFiles,
    retry,
    remove,
    restore,
    setCaption,
    setPrimary,
    move,
    startPair,
    endPair,
    beforeSave,
    payload,
    saveFailed,
    saved,
    cancel,
    switchTo,
    dropStored,
    snapshot,
    /** 上次的照片正在接、或沒接回來:這段時間「現在沒有照片作業」不是真的,不能記進草稿 */
    resumePending: resuming || resumeFailed !== null,
    resumeFailed: resumeFailed !== null,
    retryResume,
    giveUpResume,
  };
}

export type PhotoDraftHandle = ReturnType<typeof usePhotoDraft>;

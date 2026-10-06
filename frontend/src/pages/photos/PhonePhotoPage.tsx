import { useEffect, useRef, useState } from "react";

import { phoneCall, PhonePairError, PhoneState } from "@/api/photos";
import { PhotoLightbox } from "@/components/photos/PhotoLightbox";
import { shrinkImage } from "@/lib/imageShrink";
import { newId } from "@/lib/newId";

/**
 * 手機掃電腦上的 QR Code 開的拍照頁(`/m/photo#憑證`)。不用登入、不用裝 App。
 *
 * 這一頁只能做一件事:對「電腦上正在編輯的那一筆商品」傳照片。看不到別的商品、金額,也改不了品名。
 * 拍完就傳;「完成」只是結束手機這一端,商品要在電腦按儲存才算存好。
 */

interface Shot {
  uid: string;
  status: "uploading" | "ready" | "failed";
  preview: string;
  file?: Blob;
  error?: string;
}

const DEVICE_KEY = "mp-pos-photo-device";
/** 一次從相簿最多選幾張(一個商品最多 10 張) */
const PICK_LIMIT = 10;

/**
 * 這支手機自己的識別:同一支手機重新整理還是同一支(別支手機拿同一個 QR Code 連不進來)。
 * 先用長期的儲存;不能用(無痕模式等)就退到這個分頁自己的儲存,至少重新整理不會被當成另一支手機。
 */
function deviceId(): string {
  for (const store of [() => localStorage, () => sessionStorage]) {
    try {
      const box = store();
      const saved = box.getItem(DEVICE_KEY);
      if (saved) return saved;
      const fresh = newId();
      box.setItem(DEVICE_KEY, fresh);
      return fresh;
    } catch {
      /* 這一種儲存不能用,試下一種 */
    }
  }
  return newId();
}

export function PhonePhotoPage() {
  const token = useRef(window.location.hash.replace(/^#/, "")).current;
  const device = useRef(deviceId()).current;
  const [state, setState] = useState<PhoneState | null>(null);
  /** 連不上 / 失效的原因。gone = 這次配對不能用了,要回電腦重新產生 */
  const [problem, setProblem] = useState<{ text: string; gone: boolean } | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [done, setDone] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [big, setBig] = useState<number | null>(null);
  /** 這一頁按過「移除」的:伺服器下一次回報之前也不要再列出來 */
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const shotsRef = useRef<Shot[]>([]);
  shotsRef.current = shots;
  const stateRef = useRef<PhoneState | null>(null);
  stateRef.current = state;
  const endedRef = useRef(false);
  endedRef.current = !!problem && problem.gone;
  const cameraRef = useRef<HTMLInputElement>(null);
  const albumRef = useRef<HTMLInputElement>(null);

  function fail(e: unknown) {
    const err = e instanceof PhonePairError ? e : new PhonePairError("沒有成功,請再試一次", "network");
    const gone = err.code === "gone" || err.code === "expired" || err.code === "taken";
    setProblem({ text: err.message, gone });
    return err;
  }

  async function connect() {
    if (!token) {
      setProblem({ text: "請用手機相機掃電腦上的 QR Code", gone: true });
      return;
    }
    setProblem(null);
    try {
      setState(await phoneCall(token, device, "claim"));
    } catch (e) {
      fail(e);
    }
  }

  useEffect(() => {
    document.title = "商品拍照";
    void connect();
    // 只在開頁時連一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 每三秒看一次:品名有沒有改、電腦是不是正在儲存、這次配對還在不在
  const live = !!state && !done && !(problem && problem.gone);
  useEffect(() => {
    if (!live) return;
    let stopped = false;
    let handle = 0;
    const tick = async () => {
      try {
        const next = await phoneCall(token, device, "state");
        if (stopped) return;
        setState(next);
        setProblem((cur) => (cur && !cur.gone ? null : cur));
      } catch (e) {
        if (stopped) return;
        const err = e instanceof PhonePairError ? e : null;
        // 網路一時不通不算結束;配對沒了才停
        if (err && (err.code === "gone" || err.code === "expired" || err.code === "taken")) fail(err);
      }
      if (!stopped) handle = window.setTimeout(tick, 3000);
    };
    handle = window.setTimeout(tick, 3000);
    return () => {
      stopped = true;
      window.clearTimeout(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  function patchShot(uid: string, fn: (s: Shot) => Shot) {
    setShots((cur) => cur.map((s) => (s.uid === uid ? fn(s) : s)));
  }

  async function send(uid: string, file: Blob) {
    try {
      // 先登記「這一張要傳了」:電腦那邊馬上看得到有一張在路上,儲存會等它
      await phoneCall(token, device, "announce", { uid });
      const small = await shrinkImage(file);
      const next = await phoneCall(token, device, "upload", { uid, file: small });
      if (!shotsRef.current.some((s) => s.uid === uid)) return;
      setState(next);
      const mine = next.uploads.find((u) => u.uid === uid);
      if (mine && mine.status === "failed") {
        patchShot(uid, (s) => ({ ...s, status: "failed", error: mine.error || "這張照片處理不了" }));
      } else {
        patchShot(uid, (s) => ({ ...s, status: "ready", error: undefined }));
      }
    } catch (e) {
      const err = e instanceof PhonePairError ? e : new PhonePairError("沒有傳成功", "network");
      // 這一張已經在這一頁按過移除:晚到的結果(包含伺服器回「這一張取消了」)都不用理,
      // 更不能當成整次拍照結束了
      if (!shotsRef.current.some((s) => s.uid === uid)) return;
      if (err.code === "gone" || err.code === "expired" || err.code === "taken") fail(err);
      patchShot(uid, (s) => ({ ...s, status: "failed", error: err.message }));
    }
  }

  function add(list: FileList | null) {
    if (!list || list.length === 0) return;
    setNote(null);
    // 選檔的畫面打開之後電腦才開始儲存 / 這次配對才結束:這幾張不送
    if (stateRef.current?.frozen) {
      setNote("電腦正在儲存,這幾張沒有傳");
      return;
    }
    if (endedRef.current) return;
    const picked = Array.from(list);
    if (picked.length > PICK_LIMIT) setNote(`一次最多 ${PICK_LIMIT} 張,多的沒有傳`);
    const fresh: Shot[] = picked.slice(0, PICK_LIMIT).map((file) => ({
      uid: newId(),
      status: "uploading",
      preview: URL.createObjectURL(file),
      file,
    }));
    setShots((cur) => [...cur, ...fresh]);
    for (const s of fresh) void send(s.uid, s.file!);
  }

  function retry(uid: string) {
    const s = shotsRef.current.find((x) => x.uid === uid);
    if (!s?.file) return;
    patchShot(uid, (x) => ({ ...x, status: "uploading", error: undefined }));
    void send(uid, s.file);
  }

  function drop(uid: string) {
    setRemoved((cur) => new Set(cur).add(uid));
    setShots((cur) => cur.filter((s) => s.uid !== uid));
    // 伺服器記下「這一張不要了」:晚到的上傳不會讓它又出現在電腦上
    void phoneCall(token, device, "cancel", { uid }).catch(() => undefined);
  }

  const uploading = shots.filter((s) => s.status === "uploading").length;

  async function finish() {
    if (uploading > 0) {
      setNote(`還有 ${uploading} 張在傳,傳完或移除再按完成`);
      return;
    }
    try {
      await phoneCall(token, device, "finish");
    } catch {
      /* 電腦那邊已經結束也算完成 */
    }
    setDone(true);
  }

  if (done) {
    return (
      <div className="phone-photo">
        <div className="phone-card">
          <div className="phone-title">拍完了</div>
          <div className="phone-dim">商品要在電腦按儲存才算存好</div>
        </div>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="phone-photo">
        <div className="phone-card">
          {problem ? (
            <>
              <div className="phone-title">連不上</div>
              <div className="phone-dim">{problem.text}</div>
              {!problem.gone && (
                <button type="button" className="phone-btn" onClick={() => void connect()}>
                  再試一次
                </button>
              )}
            </>
          ) : (
            <div className="phone-dim">連線中…</div>
          )}
        </div>
      </div>
    );
  }

  const ended = !!problem && problem.gone;
  const locked = ended || state.frozen;
  // 這支手機先前傳好的(重新整理之後這一頁不記得):照伺服器講的補回清單,不然會以為沒傳到、再傳一次
  const mine = new Set(shots.map((s) => s.uid));
  const earlier: Shot[] = state.uploads
    .filter((u) => u.status === "ready" && !mine.has(u.uid) && !removed.has(u.uid) && u.thumb_url)
    .map((u) => ({ uid: u.uid, status: "ready" as const, preview: u.thumb_url! }));
  const list = [...earlier, ...shots];
  const viewable = list.filter((s) => s.status !== "failed");
  return (
    <div className="phone-photo">
      <div className="phone-card">
        <div className="phone-dim">正在為這個商品加照片</div>
        <div className="phone-title">{state.label.trim() || "新增商品(尚未命名)"}</div>
        {state.spec && <div className="phone-dim">{state.spec}</div>}
        <div className="phone-dim">品號:{state.sku || "尚未建立"}</div>
      </div>

      {ended && (
        <div className="phone-warn">
          這次拍照已經結束
          <div>{problem!.text}</div>
        </div>
      )}
      {!ended && state.frozen && <div className="phone-warn">電腦正在儲存,先等一下</div>}
      {!ended && problem && !problem.gone && <div className="phone-warn">{problem.text}</div>}

      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          add(e.target.files);
          e.target.value = "";
        }}
      />
      <input
        ref={albumRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => {
          add(e.target.files);
          e.target.value = "";
        }}
      />
      <div className="phone-row">
        <button
          type="button"
          className="phone-btn primary"
          disabled={locked}
          onClick={() => cameraRef.current?.click()}
        >
          拍照
        </button>
        <button
          type="button"
          className="phone-btn"
          disabled={locked}
          onClick={() => albumRef.current?.click()}
        >
          相簿
        </button>
      </div>

      {list.length > 0 && (
        <div className="phone-list">
          {list.map((s, i) => {
            const at = viewable.findIndex((v) => v.uid === s.uid);
            return (
              <div key={s.uid} className="phone-shot">
                <button
                  type="button"
                  className="phone-thumb"
                  disabled={at < 0}
                  onClick={() => setBig(at)}
                >
                  <img src={s.preview} alt={`照片 ${i + 1}`} />
                </button>
                <div className="phone-shot-text">
                  <div>照片 {i + 1}</div>
                  <div className={`phone-shot-state ${s.status}`}>
                    {s.status === "ready" ? "已上傳" : s.status === "uploading" ? "上傳中…" : "沒傳成功"}
                  </div>
                  {s.status === "failed" && s.error && <div className="phone-dim">{s.error}</div>}
                </div>
                <div className="phone-shot-actions">
                  {s.status === "failed" && !ended && (
                    <button type="button" className="phone-link" onClick={() => retry(s.uid)}>
                      重試
                    </button>
                  )}
                  {!ended && (
                    <button type="button" className="phone-link" onClick={() => drop(s.uid)}>
                      移除
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {note && <div className="phone-warn">{note}</div>}
      {!ended && (
        <button type="button" className="phone-btn wide" onClick={() => void finish()}>
          完成拍照
        </button>
      )}

      {big !== null && viewable.length > 0 && (
        <PhotoLightbox
          items={viewable.map((s) => ({ src: s.preview }))}
          index={big}
          onIndex={setBig}
          onClose={() => setBig(null)}
        />
      )}
    </div>
  );
}

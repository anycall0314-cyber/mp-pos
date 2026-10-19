/**
 * 維修單快速收件(owner 2026-10-19:「門市只是負責收件…要檢測才會有細項…最好是可以讓我快速開單」)。
 * 收件要填的只有這幾格;門市、收件人、收件日自動帶;檢測之後的內容在同一張單上再填。
 */
export interface IntakeInput {
  phone: string;
  name: string;
  modelKey: string;
  serial: string;
  serialUnavailable: boolean;
  defect: string;
  unlockMethod: string;
  unlockPassword: string;
  unlockPattern: string;
}

/** 收件哪裡還不能存;可以存就回空字串(照畫面由上到下的順序) */
export function intakeProblem(i: IntakeInput): string {
  if (!i.phone.trim()) return "請輸入聯絡電話";
  if (!i.name.trim()) return "請輸入姓名";
  if (!i.modelKey) return "請選擇機型(找不到可現場新增)";
  // 紅隊之後 owner 選「必填可註記」:開不了機勾「取不到」,跟忘了填分開
  if (!i.serial.trim() && !i.serialUnavailable) return "請輸入機身序號 / IMEI;開不了機請勾「取不到」";
  if (!i.defect.trim()) return "請輸入故障描述(客人怎麼說就怎麼寫)";
  if (!i.unlockMethod) return "請選擇手機解鎖方式";
  if (i.unlockMethod === "password" && !i.unlockPassword.trim()) return "已選擇『密碼』,請輸入密碼;若無密碼請改選『無』";
  if (i.unlockMethod === "pattern" && !i.unlockPattern.trim()) return "已選擇『圖形鎖』,請完成九宮格繪製;若無圖形鎖請改選『無』";
  return "";
}

/** 電話查不到會員、存檔時要拿它建新會員:只收像電話的(數字、連字號、空白、括號、+,至少 8 碼)。
 *  打錯多了字就建出一個假會員(紅隊提的),先擋下來 */
export function phoneForNewMember(phone: string): string {
  const p = phone.trim();
  if (!/^[\d\-\s()+]+$/.test(p) || p.replace(/\D/g, "").length < 8) return "電話格式不對(只能有數字,至少 8 碼)";
  return "";
}

/** 收件單上的「預估報價」:檢測後的報價優先;還沒有就印收件時講的預估並註明 */
export function receiptQuote(quoted: number, intakeEstimate: number): { amount: number | null; note: string } {
  if (quoted > 0) return { amount: quoted, note: "" };
  if (intakeEstimate > 0) return { amount: intakeEstimate, note: "預估,以檢測後報價為準" };
  return { amount: null, note: "待評估後通知" };
}

/** 存檔一次只跑一個:前一次還沒做完(例如正在建會員、還沒開始存單)又按一次,第二次直接不做。
 *  不然連按兩下會建出兩位同電話的會員、兩張維修單(複審抓到的)。做完或失敗才放開 */
export function makeSubmitGate() {
  let busy = false;
  return async function run<T>(task: () => Promise<T>): Promise<T | undefined> {
    if (busy) return undefined;
    busy = true;
    try {
      return await task();
    } finally {
      busy = false;
    }
  };
}

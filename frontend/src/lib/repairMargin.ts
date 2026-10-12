// 維修毛利在畫面這一側的算法:開單頁還沒存檔時要即時算(存了之後清單與月報用的是伺服器算好的)。
// 規則跟伺服器同一份(backend/apps/repairs/services.py 的 money_of / compute_personal_margin),兩邊各有測試釘住。跑法:npm test。
//
// owner 2026-10-12:「工資是分業績的」—— 工資、內部結算價只是收件人與維修人員之間怎麼分,不是公司付出去的錢,所以公司的毛利不扣:
//   自修、內部轉單 = 客戶實付 − 零件成本;委外給外面的維修廠 = 客戶實付 − 委外實際費用。
//   = 個人毛利分解兩個人加起來。

export type RepairSplitKind = "in_house_solo" | "in_house_split" | "external_vendor" | "internal_transfer";

export interface RepairNumbers {
  mode: "in_house" | "external";
  /** 收件人、維修人員(沒選 = 空的) */
  salesPerson: number | string | null | undefined;
  technician: number | string | null | undefined;
  paid: number;
  partsCost: number;
  labor: number;
  /** 內部結算價(委外模式、修的是自己公司另一位技師) */
  settle: number;
  /** 委外實際費用(付給外面的維修廠) */
  externalActual: number;
}

/** 個人毛利分解:這張單算給收件人與維修人員各多少。 */
export function personalSplit(n: RepairNumbers): { kind: RepairSplitKind; spAmt: number; techAmt: number } {
  const samePerson = !n.technician || n.technician === n.salesPerson;
  if (n.mode === "in_house") {
    if (samePerson) return { kind: "in_house_solo", spAmt: n.paid - n.partsCost, techAmt: 0 };
    return { kind: "in_house_split", spAmt: n.paid - n.labor - n.partsCost, techAmt: n.labor };
  }
  if (!samePerson) {
    return { kind: "internal_transfer", spAmt: n.paid - n.settle, techAmt: n.settle - n.partsCost };
  }
  return { kind: "external_vendor", spAmt: n.paid - n.externalActual, techAmt: 0 };
}

/** 委外給外面的維修廠(不是自修、也不是內部轉單)。 */
function toVendor(n: Pick<RepairNumbers, "mode" | "salesPerson" | "technician">): boolean {
  return n.mode !== "in_house" && (!n.technician || n.technician === n.salesPerson);
}

/** 公司的維修毛利(預估):工資、內部結算價不扣。 */
export function repairMargin(n: Pick<RepairNumbers, "mode" | "salesPerson" | "technician" | "paid" | "partsCost" | "externalActual">): number {
  return toVendor(n) ? n.paid - n.externalActual : n.paid - n.partsCost;
}

/** 預估毛利底下那一行算式。 */
export function marginFormula(n: Pick<RepairNumbers, "mode" | "salesPerson" | "technician">): string {
  return toVendor(n) ? "= 實付 − 委外實際費用" : "= 實付 − 零件成本";
}

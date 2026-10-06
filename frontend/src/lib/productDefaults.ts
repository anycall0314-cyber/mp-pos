/**
 * 新增商品時的預設(純函式,`productDefaults.test.mjs` 有測試)。
 *
 * 同一種商品不管從哪個入口建(一般新增、新增配件、型號展開),預設都要一樣 ——
 * 以前一般新增的機型配件預設勾著「需追蹤序號」,專用的「新增配件」同一種商品卻沒勾。
 * 規則只寫在這裡,各個入口都用它。
 */

/** 商品性質:主機 / 機型配件 / 通用配件(後端的 `accessory_type`) */
export type ProductNature = "none" | "phone_specific" | "universal";
/** 倉別:商品倉(銷貨用)/ 零件倉(維修用)。零件倉的東西沒有商品性質可選 */
export type ProductWarehouse = "product" | "parts";

/**
 * 這種商品預設怎麼記庫存。
 * 主機(手機、平板)逐件記序號;配件(機型配件、通用配件)按數量;**維修零件一律按數量**(不看商品性質:零件倉看不到那一排)。
 * 只是預設:少數要逐件追的配件(高價耳機)可以自己勾起來。
 */
export function defaultRequiresSerial(
  nature: ProductNature,
  warehouse: ProductWarehouse = "product",
): boolean {
  return warehouse === "product" && nature === "none";
}

/**
 * 一般新增 / 編輯表單換了商品性質(或倉別)之後,「需追蹤序號」那一格要變成什麼。
 * 跟著新的那一種的預設走,**除非**:
 * - 在編輯既有商品(它可能已經有庫存,不能因為換個分類就改記法);
 * - 人自己動過那一格(他是故意的);
 * - 被別的選項定住:虛擬商品一定不追、中古機一定追。
 */
export function requiresSerialAfterNatureChange(
  next: { nature: ProductNature; warehouse: ProductWarehouse },
  now: {
    requiresSerial: boolean;
    isEdit: boolean;
    touched: boolean;
    isVirtual: boolean;
    isSecondhand: boolean;
  },
): boolean {
  // 編輯既有商品:不替他改
  if (now.isEdit) return now.requiresSerial;
  // 被定住的照規則回(不是照那一格現在的值:它可能剛好是錯的那一邊)
  if (now.isVirtual) return false;
  if (now.isSecondhand) return true;
  if (now.touched) return now.requiresSerial;
  return defaultRequiresSerial(next.nature, next.warehouse);
}

/**
 * 取消「虛擬商品」或「中古機」之後,「需追蹤序號」要回到哪裡。
 * 勾那兩格的時候那一格被連動改掉了(虛擬 → 不追、中古 → 追);取消時不能就停在被改過的值上:
 * - 新增、人沒自己動過 → 回到這種商品的預設(主機取消虛擬之後要變回追序號);
 * - 編輯既有商品、或人自己動過 → 回到勾之前的值(`before`;不知道就不動)。
 */
export function requiresSerialAfterUnpin(
  kind: { nature: ProductNature; warehouse: ProductWarehouse },
  now: { requiresSerial: boolean; before: boolean | null; isEdit: boolean; touched: boolean },
): boolean {
  if (!now.isEdit && !now.touched) return defaultRequiresSerial(kind.nature, kind.warehouse);
  return now.before ?? now.requiresSerial;
}

/**
 * 商品表單裡跟「怎麼記庫存」有關的那幾格。名字跟表單的狀態一樣(表單直接把整份狀態丟進來)。
 * 後兩個只是表單自己記的:**跟著草稿一起存**、不送到後端 ——
 * 以前放在畫面元件自己的記憶裡,存草稿再載回來就沒了,只能拿「現在的值跟預設一不一樣」去猜,
 * 會猜錯(普通配件勾過中古機、存草稿、載回來取消中古機 → 那一格停在逐件)。
 */
export interface SerialFields {
  accessory_type: ProductNature;
  warehouse_type: ProductWarehouse;
  requires_serial: boolean;
  is_virtual: boolean;
  is_secondhand: boolean;
  /** 人自己把「需追蹤序號」改成跟當時不一樣的值(之後換商品性質不再替他改) */
  serial_touched: boolean;
  /** 勾「虛擬商品 / 中古機」之前那一格是什麼;沒有被定住的時候是 null */
  serial_before_pin: boolean | null;
}

function serialAfterKindChange(
  s: SerialFields,
  next: { nature: ProductNature; warehouse: ProductWarehouse },
  isEdit: boolean,
): boolean {
  return requiresSerialAfterNatureChange(next, {
    requiresSerial: s.requires_serial,
    isEdit,
    touched: s.serial_touched,
    isVirtual: s.is_virtual,
    isSecondhand: s.is_secondhand,
  });
}

/** 換商品性質 */
export function withNature<T extends SerialFields>(s: T, nature: ProductNature, isEdit: boolean): T {
  return {
    ...s,
    accessory_type: nature,
    requires_serial: serialAfterKindChange(s, { nature, warehouse: s.warehouse_type }, isEdit),
  };
}

/** 換倉別(商品倉 / 零件倉) */
export function withWarehouse<T extends SerialFields>(
  s: T,
  warehouse: ProductWarehouse,
  isEdit: boolean,
): T {
  return {
    ...s,
    warehouse_type: warehouse,
    requires_serial: serialAfterKindChange(s, { nature: s.accessory_type, warehouse }, isEdit),
  };
}

/**
 * 勾 / 取消「虛擬商品」「中古機」。這兩格會把「需追蹤序號」定住(虛擬一定不追、中古一定追、中古不會是虛擬)。
 * 勾的時候記下原本的值;兩格都取消之後回到該回的地方(`requiresSerialAfterUnpin`)。
 */
export function withPin<T extends SerialFields>(
  s: T,
  kind: "virtual" | "secondhand",
  on: boolean,
  isEdit: boolean,
): T {
  const out: T = { ...s };
  if (kind === "virtual") out.is_virtual = on;
  else out.is_secondhand = on;
  if (on) {
    if (!s.is_virtual && !s.is_secondhand) out.serial_before_pin = s.requires_serial;
    if (kind === "virtual") {
      out.requires_serial = false;
    } else {
      out.requires_serial = true;
      out.is_virtual = false;
    }
  } else if (out.is_virtual) {
    out.requires_serial = false;
  } else if (out.is_secondhand) {
    out.requires_serial = true;
  } else {
    out.requires_serial = requiresSerialAfterUnpin(
      { nature: s.accessory_type, warehouse: s.warehouse_type },
      {
        requiresSerial: s.requires_serial,
        before: s.serial_before_pin,
        isEdit,
        touched: s.serial_touched,
      },
    );
    out.serial_before_pin = null;
  }
  return out;
}

/** 人自己按「需追蹤序號」。被定住的時候按了不會變,也不算「人改過」 */
export function withSerialByHand<T extends SerialFields>(s: T, wanted: boolean): T {
  const next = s.is_virtual ? false : s.is_secondhand ? true : wanted;
  return {
    ...s,
    requires_serial: next,
    serial_touched: s.serial_touched || next !== s.requires_serial,
  };
}

/**
 * 載入草稿時補上這一版之前沒有存的那兩格(舊草稿只能猜):
 * - 被定住的(虛擬 / 中古):不知道勾之前是什麼、也不知道人有沒有動過 → 當成沒動過,取消時回這種商品的預設;
 * - 沒被定住的:那一格跟這種商品的預設不一樣,才當成人動過。
 * 新草稿兩格都有存,直接用。
 */
export function serialMemoryFromDraft(
  stored: Partial<SerialFields> &
    Pick<SerialFields, "accessory_type" | "warehouse_type" | "requires_serial" | "is_virtual" | "is_secondhand">,
): Pick<SerialFields, "serial_touched" | "serial_before_pin"> {
  const pinned = stored.is_virtual || stored.is_secondhand;
  return {
    serial_touched:
      stored.serial_touched ??
      (!pinned &&
        stored.requires_serial !== defaultRequiresSerial(stored.accessory_type, stored.warehouse_type)),
    serial_before_pin: stored.serial_before_pin ?? null,
  };
}

/**
 * 新增商品選了「主機」:手機 / 平板要走「新增手機型號」(一次建好容量、顏色、品況,結構才跟其他手機一樣),
 * 這張一般表單先不能存 —— 除非是編輯既有商品,或人已經按了「留在這裡建立」(沒有容量、顏色之分的機種)。
 * 只管商品倉:零件倉的東西不是手機,而且那裡看不到商品性質那一排(之前選過「主機」再切到零件倉,不能因此卡住存不了)。
 */
export function phoneNeedsWizard(s: {
  isEdit: boolean;
  nature: ProductNature;
  warehouse: ProductWarehouse;
  stayHere: boolean;
}): boolean {
  return !s.isEdit && s.warehouse === "product" && s.nature === "none" && !s.stayHere;
}

/** 庫存怎麼記,講給人看的那一句(跟「需追蹤序號」那一格同一件事) */
export function stockModeLabel(requiresSerial: boolean): string {
  return requiresSerial ? "逐件記序號" : "按數量";
}

interface ConditionLike {
  id: number;
  is_active: boolean;
  is_secondhand: boolean;
  tracks_unit_condition: boolean;
}

/**
 * 新增手機型號時預設勾哪些品況:只勾「全新」那一種。
 * 以前是全部勾起來,新手一按就建出 4 種品況 × 容量 × 顏色、一堆用不到的品項。
 * 「全新」= 啟用中、不是中古、也不用逐台記機況的第一個(照主檔的順序);找不到就都不勾,由人自己選。
 */
export function defaultConditionIds(conditions: ConditionLike[]): number[] {
  const fresh = conditions.find(
    (c) => c.is_active && !c.is_secondhand && !c.tracks_unit_condition,
  );
  return fresh ? [fresh.id] : [];
}

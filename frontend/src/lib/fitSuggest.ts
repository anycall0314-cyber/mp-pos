/**
 * 新增配件時照品名先勾好適用機型(V2;backend/apps/catalog/fit_suggest.py)。
 * 表單上那一排「相容機型」怎麼跟著建議變,規則只有這一份:
 * - 照品名讀到的、型號庫設了配件共用的新機,自動放上去(看得到、可以拿掉);
 * - 換品名時,上一次自動放的、這次不在建議裡的拿掉;人自己挑的不動;
 * - 人拿掉過的不再自動放;人自己再挑一次就算回來了。
 */

export interface FitChip {
  model_key: string;
  model_name: string;
  lifecycle_status?: string;
}

export interface FitModel {
  model_key: string;
  model_name: string;
}

export interface FitState {
  related_models: FitChip[];
  /** 自動放上去的(換品名時可以換掉) */
  fits_auto: string[];
  /** 人拿掉過的(不再自動放) */
  fits_removed: string[];
}

/** 人自己挑的那幾個(問伺服器「挑了這些還要一起帶哪幾支新機」用),排好、逗號接起來 */
export function manualKeys(s: FitState): string {
  const auto = new Set(s.fits_auto);
  return s.related_models
    .map((m) => m.model_key)
    .filter((k) => !auto.has(k))
    .sort()
    .join(",");
}

/** 把這一次的建議換上去。沒有變就回原本那一份(不重畫、不算改過) */
export function withSuggested<S extends FitState>(s: S, suggested: FitModel[]): S {
  const removed = new Set(s.fits_removed);
  const want = new Map<string, FitModel>();
  for (const m of suggested) if (!removed.has(m.model_key) && !want.has(m.model_key)) want.set(m.model_key, m);
  const auto = new Set(s.fits_auto);
  const kept = s.related_models.filter((m) => !auto.has(m.model_key) || want.has(m.model_key));
  const have = new Set(kept.map((m) => m.model_key));
  const added = [...want.values()]
    .filter((m) => !have.has(m.model_key))
    .map((m) => ({ model_key: m.model_key, model_name: m.model_name }));
  const fitsAuto = [...kept.filter((m) => auto.has(m.model_key)).map((m) => m.model_key), ...added.map((m) => m.model_key)];
  if (added.length === 0 && kept.length === s.related_models.length && fitsAuto.length === s.fits_auto.length) return s;
  return { ...s, related_models: [...kept, ...added], fits_auto: fitsAuto };
}

/** 人自己挑了一個:放上去(已經有就不動);拿掉過的算回來了 */
export function withPicked<S extends FitState>(s: S, chip: FitChip): S {
  const removed = s.fits_removed.filter((k) => k !== chip.model_key);
  if (s.related_models.some((m) => m.model_key === chip.model_key)) {
    return removed.length === s.fits_removed.length ? s : { ...s, fits_removed: removed };
  }
  return { ...s, related_models: [...s.related_models, chip], fits_removed: removed };
}

/** 人拿掉一個:之後不再自動放 */
export function withRemoved<S extends FitState>(s: S, key: string): S {
  return {
    ...s,
    related_models: s.related_models.filter((m) => m.model_key !== key),
    fits_auto: s.fits_auto.filter((k) => k !== key),
    fits_removed: s.fits_removed.includes(key) ? s.fits_removed : [...s.fits_removed, key],
  };
}

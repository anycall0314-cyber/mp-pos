import { errorText } from "@/lib/errorText";

interface BannerProps {
  kind: "error" | "info" | "success";
  message: string;
}

export function Banner({ kind, message }: BannerProps) {
  return <div className={`banner banner-${kind}`}>{message}</div>;
}

/** 錯誤 → 給人看的一句中文(規則只有 lib/errorText.ts 一份) */
export function errorMessageOf(err: unknown): string {
  return errorText(err);
}

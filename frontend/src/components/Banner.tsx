interface BannerProps {
  kind: "error" | "info" | "success";
  message: string;
}

export function Banner({ kind, message }: BannerProps) {
  return <div className={`banner banner-${kind}`}>{message}</div>;
}

export function errorMessageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

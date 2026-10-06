/**
 * 上傳前先在瀏覽器把照片縮小、轉正、轉成 JPEG:手機一張原圖十幾 MB,縮完多半不到 1MB,傳得快也省流量。
 * 瀏覽器打不開的格式(電腦上的 HEIC)就原檔送出,交給伺服器處理(伺服器會再檢查、再轉一次)。
 */
export async function shrinkImage(
  file: Blob,
  maxEdge = 2400,
  quality = 0.88,
): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    // 透明的地方鋪白底(JPEG 沒有透明)
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", quality),
    );
    // 縮完反而比較大(本來就很小的圖)就用原檔
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file;
  }
}

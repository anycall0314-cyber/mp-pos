/**
 * 分段算檔案的 SHA-256(驗證存到硬碟的備份檔用)。
 *
 * 不用瀏覽器內建的 crypto.subtle,原因有兩個:
 * 1. 它只在 https 或 localhost 才有;店裡用區網 IP(http)連線時整個物件不存在。
 * 2. 它只能一次算整包,要把整個備份檔讀進記憶體;檔案上 GB 時舊電腦撐不住。
 * 這裡一次只讀一小段,算完就丟。演算法是標準 SHA-256(FIPS 180-4),沒有自創的部分。
 */

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

export class Sha256 {
  private h = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
    0x1f83d9ab, 0x5be0cd19,
  ]);
  private block = new Uint8Array(64);
  private filled = 0;
  private bytes = 0;
  private w = new Uint32Array(64);

  update(data: Uint8Array): void {
    let pos = 0;
    this.bytes += data.length;
    if (this.filled) {
      const take = Math.min(64 - this.filled, data.length);
      this.block.set(data.subarray(0, take), this.filled);
      this.filled += take;
      pos = take;
      if (this.filled < 64) return;
      this.compress(this.block, 0);
      this.filled = 0;
    }
    for (; pos + 64 <= data.length; pos += 64) this.compress(data, pos);
    if (pos < data.length) {
      this.block.set(data.subarray(pos), 0);
      this.filled = data.length - pos;
    }
  }

  hex(): string {
    // 總長度(bit)分成高低各 32 位元;檔案超過 512MB 時高位才不是 0
    const hi = Math.floor(this.bytes / 0x20000000);
    const lo = (this.bytes % 0x20000000) * 8;
    const b = this.block;
    b[this.filled++] = 0x80;
    if (this.filled > 56) {
      b.fill(0, this.filled);
      this.compress(b, 0);
      this.filled = 0;
    }
    b.fill(0, this.filled, 56);
    const view = new DataView(b.buffer);
    view.setUint32(56, hi);
    view.setUint32(60, lo);
    this.compress(b, 0);
    return Array.from(this.h)
      .map((x) => x.toString(16).padStart(8, "0"))
      .join("");
  }

  private compress(buf: Uint8Array, off: number): void {
    const w = this.w;
    const h = this.h;
    for (let i = 0; i < 16; i++) {
      const j = off + i * 4;
      w[i] = (buf[j] << 24) | (buf[j + 1] << 16) | (buf[j + 2] << 8) | buf[j + 3];
    }
    for (let i = 16; i < 64; i++) {
      const x = w[i - 15];
      const y = w[i - 2];
      const s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
      const s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let a = h[0] | 0;
    let b = h[1] | 0;
    let c = h[2] | 0;
    let d = h[3] | 0;
    let e = h[4] | 0;
    let f = h[5] | 0;
    let g = h[6] | 0;
    let hh = h[7] | 0;
    for (let i = 0; i < 64; i++) {
      const s1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + s1 + ch + K[i] + w[i]) | 0;
      const s0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (s0 + maj) | 0;
      hh = g;
      g = f;
      f = e;
      e = (d + t1) | 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) | 0;
    }
    h[0] = (h[0] + a) | 0;
    h[1] = (h[1] + b) | 0;
    h[2] = (h[2] + c) | 0;
    h[3] = (h[3] + d) | 0;
    h[4] = (h[4] + e) | 0;
    h[5] = (h[5] + f) | 0;
    h[6] = (h[6] + g) | 0;
    h[7] = (h[7] + hh) | 0;
  }
}

const CHUNK = 4 * 1024 * 1024;

/** 一段一段讀檔案算 SHA-256。`onProgress` 收到 0–100。 */
export async function sha256File(
  file: Blob,
  onProgress?: (percent: number) => void,
): Promise<string> {
  const hash = new Sha256();
  for (let start = 0; start < file.size; start += CHUNK) {
    const piece = await file.slice(start, start + CHUNK).arrayBuffer();
    hash.update(new Uint8Array(piece));
    onProgress?.(Math.floor((Math.min(start + CHUNK, file.size) / file.size) * 100));
  }
  return hash.hex();
}

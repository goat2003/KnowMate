/**
 * Create a request identifier that also works when the app is opened over
 * plain HTTP on a local network address. `randomUUID` is restricted to
 * secure contexts, while `getRandomValues` remains available in browsers
 * that do not expose the UUID helper.
 */
export function createRequestId(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }

  if (typeof cryptoApi?.getRandomValues !== "function") {
    throw new Error("当前浏览器不支持安全随机数，请升级浏览器后重试");
  }

  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  // RFC 9562 UUID v4: set version 4 and the RFC 4122 variant bits.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
}

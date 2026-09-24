import { afterEach, describe, expect, it, vi } from "vitest";
import { createRequestId } from "./requestId";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createRequestId", () => {
  it("uses the native UUID implementation when available", () => {
    const randomUUID = vi.fn().mockReturnValue("native-id");
    vi.stubGlobal("crypto", { randomUUID });

    expect(createRequestId()).toBe("native-id");
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("creates an RFC UUID v4 when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {
      getRandomValues(bytes: Uint8Array) {
        bytes.fill(0x11);
        return bytes;
      }
    });

    expect(createRequestId()).toBe("11111111-1111-4111-9111-111111111111");
  });
});

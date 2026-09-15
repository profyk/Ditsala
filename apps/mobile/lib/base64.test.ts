import { base64ToBytes, bytesToBase64 } from "./base64";

function bytesFrom(...values: number[]): Uint8Array {
  return new Uint8Array(values);
}

describe("bytesToBase64", () => {
  it("encodes an empty array", () => {
    expect(bytesToBase64(bytesFrom())).toBe("");
  });

  it("encodes known values matching standard base64", () => {
    // "Man" -> "TWFu" is the textbook base64 example.
    expect(bytesToBase64(bytesFrom(77, 97, 110))).toBe("TWFu");
  });

  it("pads correctly for lengths not divisible by 3", () => {
    expect(bytesToBase64(bytesFrom(77))).toBe("TQ==");
    expect(bytesToBase64(bytesFrom(77, 97))).toBe("TWE=");
  });
});

describe("base64ToBytes", () => {
  it("decodes an empty string", () => {
    expect(base64ToBytes("")).toEqual(bytesFrom());
  });

  it("decodes known values matching standard base64", () => {
    expect(base64ToBytes("TWFu")).toEqual(bytesFrom(77, 97, 110));
  });

  it("decodes padded values", () => {
    expect(base64ToBytes("TQ==")).toEqual(bytesFrom(77));
    expect(base64ToBytes("TWE=")).toEqual(bytesFrom(77, 97));
  });
});

describe("round-trip", () => {
  it("recovers arbitrary byte sequences, including 0x00 and 0xff", () => {
    const original = bytesFrom(0, 1, 2, 254, 255, 128, 64, 32, 16, 8, 4, 2, 1);
    expect(base64ToBytes(bytesToBase64(original))).toEqual(original);
  });

  it("recovers random-ish longer sequences at every length mod 3", () => {
    for (const length of [1, 2, 3, 4, 5, 6, 7, 30, 31, 32]) {
      const original = new Uint8Array(length).map((_, i) => (i * 37 + 11) % 256);
      expect(base64ToBytes(bytesToBase64(original))).toEqual(original);
    }
  });
});

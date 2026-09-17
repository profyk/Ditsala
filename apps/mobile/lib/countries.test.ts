import { toE164 } from "./countries";

const ZA = { name: "South Africa", iso2: "ZA", dialCode: "+27", flag: "🇿🇦" };
const US = { name: "United States", iso2: "US", dialCode: "+1", flag: "🇺🇸" };

describe("toE164", () => {
  it("drops a leading trunk zero before prepending the country code", () => {
    expect(toE164(ZA, "0718880296")).toBe("+27718880296");
  });

  it("is a no-op when the local number has no leading zero", () => {
    expect(toE164(ZA, "718880296")).toBe("+27718880296");
  });

  it("strips non-digit formatting characters", () => {
    expect(toE164(ZA, "071 888 0296")).toBe("+27718880296");
    expect(toE164(US, "(212) 555-0192")).toBe("+12125550192");
  });
});

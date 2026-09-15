import { extractContactUserId } from "./circle-link";

describe("extractContactUserId", () => {
  it("extracts the userId query param from a ditsala:// link", () => {
    expect(extractContactUserId("ditsala://circle/add?userId=abc-123")).toBe("abc-123");
  });

  it("extracts the userId when it isn't the first query param", () => {
    expect(extractContactUserId("https://ditsala.app/add?ref=qr&userId=abc-123")).toBe(
      "abc-123"
    );
  });

  it("URL-decodes the value", () => {
    expect(extractContactUserId("ditsala://circle/add?userId=abc%20123")).toBe("abc 123");
  });

  it("returns null for text with no userId param", () => {
    expect(extractContactUserId("not a link at all")).toBeNull();
    expect(extractContactUserId("ditsala://circle/add?other=1")).toBeNull();
  });

  it("returns null instead of throwing on malformed percent-encoding", () => {
    expect(extractContactUserId("ditsala://circle/add?userId=%")).toBeNull();
  });
});

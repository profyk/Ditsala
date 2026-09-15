import {
  isStrongDitsalaCode,
  isValidDateOfBirth,
  isValidEmail,
  isValidPhone,
} from "./validation";

describe("isValidDateOfBirth", () => {
  it("accepts YYYY-MM-DD", () => {
    expect(isValidDateOfBirth("1990-01-01")).toBe(true);
  });

  it("rejects other formats", () => {
    expect(isValidDateOfBirth("01/01/1990")).toBe(false);
    expect(isValidDateOfBirth("1990-1-1")).toBe(false);
    expect(isValidDateOfBirth("")).toBe(false);
  });
});

describe("isStrongDitsalaCode", () => {
  it("requires at least 8 characters and a digit", () => {
    expect(isStrongDitsalaCode("short1")).toBe(false);
    expect(isStrongDitsalaCode("noDigitsHere")).toBe(false);
    expect(isStrongDitsalaCode("longEnough1")).toBe(true);
  });
});

describe("isValidEmail", () => {
  it("requires an @ and more than a couple characters", () => {
    expect(isValidEmail("a@b.com")).toBe(true);
    expect(isValidEmail("nope")).toBe(false);
    expect(isValidEmail("@")).toBe(false);
  });
});

describe("isValidPhone", () => {
  it("requires at least 8 characters", () => {
    expect(isValidPhone("+27821234567")).toBe(true);
    expect(isValidPhone("123")).toBe(false);
  });
});

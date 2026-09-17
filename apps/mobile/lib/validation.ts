const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function isValidDateOfBirth(value: string): boolean {
  return DATE_PATTERN.test(value);
}

/** Mirrors backend/app/core/security.py::validate_ditsala_code_strength —
 * keep these in sync; the backend is the source of truth and re-checks
 * this regardless of what the client allows through. */
export function isStrongDitsalaCode(code: string): boolean {
  return code.length >= 8 && /\d/.test(code);
}

export function isValidEmail(value: string): boolean {
  return value.includes("@") && value.trim().length > 2;
}

export function isValidPhone(value: string): boolean {
  return value.trim().length >= 8;
}

/** Mirrors backend/app/core/security.py::validate_pin_strength (ADR 0014) —
 * exactly 6 digits, nothing else. The backend re-checks this regardless. */
export function isValidPin(pin: string): boolean {
  return /^\d{6}$/.test(pin);
}

const COMMON_WEAK_PINS = new Set([
  "000000",
  "111111",
  "222222",
  "333333",
  "444444",
  "555555",
  "666666",
  "777777",
  "888888",
  "999999",
  "123456",
  "654321",
  "123123",
  "112233",
  "121212",
  "010203",
  "202020",
]);

/** Mirrors backend/app/core/security.py::is_weak_pin (ADR 0014) — rejects
 * a common blocklist plus purely ascending/descending sequential runs. */
export function isWeakPin(pin: string): boolean {
  if (COMMON_WEAK_PINS.has(pin)) return true;
  const digits = pin.split("").map(Number);
  const ascending = digits.every((d, i) => i === 0 || d === digits[i - 1] + 1);
  const descending = digits.every((d, i) => i === 0 || d === digits[i - 1] - 1);
  return ascending || descending;
}

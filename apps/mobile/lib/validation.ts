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

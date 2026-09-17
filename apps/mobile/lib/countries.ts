export interface Country {
  name: string;
  iso2: string;
  dialCode: string;
  flag: string;
}

/**
 * A curated, not-exhaustive list of countries for the signup phone-number
 * picker — covers every populated continent rather than all ~195 ISO
 * countries, to keep this a hand-reviewable constant instead of a bundled
 * i18n library. South Africa is first since it's Ditsala's current primary
 * market (see CLAUDE.md), everything else is alphabetical by country name.
 */
export const COUNTRIES: Country[] = [
  { name: "South Africa", iso2: "ZA", dialCode: "+27", flag: "🇿🇦" },
  { name: "Australia", iso2: "AU", dialCode: "+61", flag: "🇦🇺" },
  { name: "Botswana", iso2: "BW", dialCode: "+267", flag: "🇧🇼" },
  { name: "Brazil", iso2: "BR", dialCode: "+55", flag: "🇧🇷" },
  { name: "Canada", iso2: "CA", dialCode: "+1", flag: "🇨🇦" },
  { name: "China", iso2: "CN", dialCode: "+86", flag: "🇨🇳" },
  { name: "Egypt", iso2: "EG", dialCode: "+20", flag: "🇪🇬" },
  { name: "Eswatini", iso2: "SZ", dialCode: "+268", flag: "🇸🇿" },
  { name: "France", iso2: "FR", dialCode: "+33", flag: "🇫🇷" },
  { name: "Germany", iso2: "DE", dialCode: "+49", flag: "🇩🇪" },
  { name: "Ghana", iso2: "GH", dialCode: "+233", flag: "🇬🇭" },
  { name: "India", iso2: "IN", dialCode: "+91", flag: "🇮🇳" },
  { name: "Indonesia", iso2: "ID", dialCode: "+62", flag: "🇮🇩" },
  { name: "Ireland", iso2: "IE", dialCode: "+353", flag: "🇮🇪" },
  { name: "Italy", iso2: "IT", dialCode: "+39", flag: "🇮🇹" },
  { name: "Japan", iso2: "JP", dialCode: "+81", flag: "🇯🇵" },
  { name: "Kenya", iso2: "KE", dialCode: "+254", flag: "🇰🇪" },
  { name: "Lesotho", iso2: "LS", dialCode: "+266", flag: "🇱🇸" },
  { name: "Malawi", iso2: "MW", dialCode: "+265", flag: "🇲🇼" },
  { name: "Mexico", iso2: "MX", dialCode: "+52", flag: "🇲🇽" },
  { name: "Mozambique", iso2: "MZ", dialCode: "+258", flag: "🇲🇿" },
  { name: "Namibia", iso2: "NA", dialCode: "+264", flag: "🇳🇦" },
  { name: "Netherlands", iso2: "NL", dialCode: "+31", flag: "🇳🇱" },
  { name: "New Zealand", iso2: "NZ", dialCode: "+64", flag: "🇳🇿" },
  { name: "Nigeria", iso2: "NG", dialCode: "+234", flag: "🇳🇬" },
  { name: "Pakistan", iso2: "PK", dialCode: "+92", flag: "🇵🇰" },
  { name: "Philippines", iso2: "PH", dialCode: "+63", flag: "🇵🇭" },
  { name: "Portugal", iso2: "PT", dialCode: "+351", flag: "🇵🇹" },
  { name: "Saudi Arabia", iso2: "SA", dialCode: "+966", flag: "🇸🇦" },
  { name: "Singapore", iso2: "SG", dialCode: "+65", flag: "🇸🇬" },
  { name: "Spain", iso2: "ES", dialCode: "+34", flag: "🇪🇸" },
  { name: "Tanzania", iso2: "TZ", dialCode: "+255", flag: "🇹🇿" },
  { name: "Uganda", iso2: "UG", dialCode: "+256", flag: "🇺🇬" },
  { name: "United Arab Emirates", iso2: "AE", dialCode: "+971", flag: "🇦🇪" },
  { name: "United Kingdom", iso2: "GB", dialCode: "+44", flag: "🇬🇧" },
  { name: "United States", iso2: "US", dialCode: "+1", flag: "🇺🇸" },
  { name: "Zambia", iso2: "ZM", dialCode: "+260", flag: "🇿🇲" },
  { name: "Zimbabwe", iso2: "ZW", dialCode: "+263", flag: "🇿🇼" },
];

export const DEFAULT_COUNTRY: Country = COUNTRIES[0];

/**
 * Converts a country + a locally-typed number into E.164. Most countries'
 * local-format numbers start with a trunk "0" that's dropped once the
 * country code is prepended (South Africa "071 888 0296" -> "+27 71 888
 * 0296", same convention in the UK and many others) — naively
 * concatenating `dialCode + digits` without stripping it produces a
 * phone number that silently doesn't match what the user actually has
 * (an extra "0" right after the country code), which would fail to
 * match against the stored value on every subsequent login.
 */
export function toE164(country: Country, localNumber: string): string {
  const digits = localNumber.replace(/\D/g, "").replace(/^0+/, "");
  return `${country.dialCode}${digits}`;
}

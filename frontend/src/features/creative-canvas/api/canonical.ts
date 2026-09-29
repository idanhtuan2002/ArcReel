/**
 * Canonical JSON bytes and the M8 version-1 revision digest, byte-for-byte equal
 * to `r2/advanced_creative/digests.py` on the JSON a client sends.
 *
 * Canonical bytes are UTF-8 JSON with no whitespace, unescaped Unicode, object
 * keys sorted by code point and arrays in order. Numbers use fixed notation with
 * trailing fractional zeroes removed and negative zero written as `0`. A digest
 * is `sha256:` plus the lowercase hex of those bytes.
 *
 * Values the server cannot encode are rejected: non-finite numbers, lone
 * surrogates, and anything other than plain JSON values. Object keys outside the
 * Basic Multilingual Plane are rejected too, because UTF-16 order and code-point
 * order differ only for them.
 */

export const CONTRACT_VERSION = "1";

export class CanonicalJsonError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CanonicalJsonError";
  }
}

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
const SURROGATE = /[\uD800-\uDFFF]/;

function encodeString(value: string): string {
  if (LONE_SURROGATE.test(value)) throw new CanonicalJsonError("strings must be valid Unicode");
  return JSON.stringify(value);
}

/** Fixed notation of the shortest round-trip form, as Python's `Decimal(str(float))` normalizes it. */
export function canonicalNumber(value: number): string {
  if (!Number.isFinite(value)) throw new CanonicalJsonError("canonical JSON numbers must be finite");
  if (value === 0) return "0";
  const match = /^(\d+)(?:\.(\d+))?(?:e([+-]\d+))?$/.exec(String(Math.abs(value)));
  if (!match) throw new CanonicalJsonError(`unexpected number form: ${String(value)}`);
  const [, whole, fraction = "", exponent = "0"] = match;
  let digits = whole + fraction;
  // The decimal point sits `point` digits after the start of `digits`.
  let point = whole.length + Number(exponent);
  const leading = /^0*/.exec(digits)?.[0].length ?? 0;
  digits = digits.slice(leading).replace(/0+$/, "");
  point -= leading;
  let text: string;
  if (point <= 0) text = `0.${"0".repeat(-point)}${digits}`;
  else if (point >= digits.length) text = digits + "0".repeat(point - digits.length);
  else text = `${digits.slice(0, point)}.${digits.slice(point)}`;
  return (value < 0 ? "-" : "") + text;
}

function encode(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return encodeString(value);
  if (typeof value === "number") return canonicalNumber(value);
  if (Array.isArray(value)) return `[${value.map((item: unknown) => encode(item)).join(",")}]`;
  if (typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== undefined);
    for (const [key] of entries) {
      if (SURROGATE.test(key)) throw new CanonicalJsonError("object keys must lie in the Basic Multilingual Plane");
    }
    entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${encodeString(key)}:${encode(item)}`).join(",")}}`;
  }
  throw new CanonicalJsonError(`${typeof value} is outside the canonical JSON domain`);
}

export function canonicalJson(value: unknown): string {
  return encode(value);
}

export async function digestCanonical(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return `sha256:${Array.from(hash, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

/** The revision payload digest: exactly `{contract_version, kind, payload, lineage}`. */
export function digestPayload(payload: { kind: string }, lineage: unknown): Promise<string> {
  return digestCanonical({ contract_version: CONTRACT_VERSION, kind: payload.kind, payload, lineage });
}

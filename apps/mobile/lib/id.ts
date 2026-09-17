import nacl from "tweetnacl";

/** A random hex id for client-generated idempotency keys (e.g.
 * `client_message_id`) — not a UUID string, just unique and unguessable,
 * which is all that's required here. Uses the same CSPRNG as the E2EE
 * module (see lib/crypto/e2ee.ts) rather than Math.random(). */
export function randomId(): string {
  return Array.from(nacl.randomBytes(16))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

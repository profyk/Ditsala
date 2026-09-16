# DITSALA Account Recovery

*User-facing explanation of the §33 recovery flow — what to expect, and why each step exists.*

## When you'd use this

If you lose your device, or can no longer complete your normal login (DITSALA Code + liveness check) for any other reason, account recovery lets you regain access from a new device.

## Why recovery asks for so much re-verification

DITSALA doesn't have a "forgot password" email link, because that would be a weaker path into an account than the one we ask you to use every day. Recovery is deliberately at least as strong as ordinary login, because it's the path an attacker would try first if they somehow learned your email and phone number. Each step below exists to make sure the person recovering the account is really you.

## The recovery flow

1. **Confirm your email and phone number.** You'll receive a one-time code by email and by SMS to the address/number on file. This proves you still control both.
2. **Complete a liveness check.** Unlike your everyday login, this is matched **directly against your original identity verification** (Smile ID's SmartSelfie Authentication) — a 1:1 biometric match, not a fresh document capture. This is the strongest step in the flow: it confirms you are the same person who originally verified this account, not just someone who has your email and phone.
3. **A brief window for your next-of-kin to flag concerns.** If you've added a next-of-kin contact, they receive a text message noting that your account is being recovered, with a link they can use if this looks suspicious to them. This is a safety net, not a requirement you need their approval — recovery proceeds unless they actively flag it.
4. **Set a new DITSALA Code.** Once the above steps pass, you choose a new account secret and are logged in on your new device.

## What happens to your old device and existing conversations

Successfully completing recovery **signs out every other device** on your account and **revokes all previous sessions** — if someone else had gained access, this cuts them off immediately. Your existing Circle contacts will see that your device changed (a "safety number changed" notice, once mobile displays this — see `docs/SECURITY_GAPS.md`), the same way any messaging app built on the Signal Protocol behaves when your encryption keys change. This is expected and is not a sign anything went wrong — it's the same protection that stops someone else's device from silently impersonating you afterward.

## If recovery doesn't work

- **Wrong email/phone confirmation code**: you have a limited number of attempts before you need to restart the flow.
- **Liveness check fails**: this usually means lighting/camera conditions during the check, not a rejection of your identity — you can retry. Repeated failures may require reaching out through the in-app support channel (accessible without logging in) for a manual review, similar to KYC manual review (`KYC_POLICY.md`).
- **You no longer have access to your registered email or phone number**: contact support — this requires manual identity confirmation outside the automated flow.

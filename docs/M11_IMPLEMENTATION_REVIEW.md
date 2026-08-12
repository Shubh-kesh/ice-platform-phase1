# M11 — Google Sign-In & User Onboarding — Implementation Review

## 1. Implementation summary

M11 adds Google Sign-In using Authorization Code + PKCE, server-side ID-token
verification, verified-email account linking, Google-only admin invitations,
role management, activation/deactivation auditing, and an admin Users panel.
Google authentication issues the existing ICE/M9 session pair; no parallel
session architecture was introduced.

The documented defaults were used: silent verified-email linking with full
audit, reject unknown Google emails, distinct activation/deactivation audit
actions, and a CommandCenter Users panel.

## 2. Files changed

### Backend

- `backend/app/api/v1/auth.py`
- `backend/app/api/v1/users.py`
- `backend/app/core/config.py`
- `backend/app/core/rate_limit.py`
- `backend/app/models/user.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/user.py`
- `backend/app/services/google_auth.py`
- `backend/app/requirements.txt`
- `backend/alembic/versions/i7d8e9f0a1b2_m11_google_signin.py`
- `backend/tests/conftest.py`
- `backend/tests/test_google_auth.py`
- `backend/tests/test_migrations.py`

### Frontend

- `frontend/src/App.tsx`
- `frontend/src/components/UsersPanel.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth-context.tsx`
- `frontend/src/pages/CommandCenter.tsx`
- `frontend/src/pages/GoogleCallback.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/types/index.ts`

### Documentation

- `docs/CURRENT_STATE.md`
- `docs/ROADMAP.md`
- `docs/SESSION_NOTES.md`
- `docs/ARCHITECTURE.md`
- `docs/M11_IMPLEMENTATION_REVIEW.md`

## 3. Migration revision

- Revision: `i7d8e9f0a1b2`
- Down revision: `h6c7d8e9f0a1`
- Changes: nullable `hashed_password`, nullable `google_sub` with a unique
  index, and nullable `google_email`.
- Downgrade intentionally fails when Google-only users with NULL passwords
  remain, because restoring `NOT NULL` would be destructive.

## 4. API behavior changes

- `GET /api/v1/auth/google/authorize` returns the Google authorization URL,
  state, nonce, and PKCE verifier.
- `POST /api/v1/auth/google/callback` accepts `code`, `state`, and
  `code_verifier`, then returns the normal `TokenResponse`.
- `POST /api/v1/users` accepts `google_only=true` without a password.
- `PATCH /api/v1/users/{id}` now accepts `role`.
- Google authorize/callback are rate-limited at `10/minute/IP`.
- Existing login, refresh, logout, assignment, RBAC, and project APIs remain.

## 5. Google OAuth architecture

- Authorization Code + PKCE; no Google JavaScript SDK.
- State is timestamped and HMAC-authenticated using `SECRET_KEY`; no Redis or
  database state is introduced.
- Nonce is embedded in the state payload and compared with the ID token nonce.
- The backend exchanges the code and keeps Google access/refresh tokens out of
  storage.
- ID tokens are verified with RS256 against Google's JWKS and checked for
  issuer, audience, expiration, iat/nbf, nonce, verified email, and optional
  hosted domain.
- The implementation uses existing `python-jose` plus pinned `httpx` with an
  injectable JWKS source. `google-auth` was not added because its public
  verifier does not expose the injectable certificate source required by the
  saved M11 testing strategy.

## 6. User onboarding/linking behavior

- `google_sub` is the authoritative Google identity key.
- Lookup order is `google_sub`, then lower-cased verified email for linking.
- Existing linked users sign in normally.
- Existing password users and `google_only` pending invites can link.
- Unknown emails are rejected with 403; no public signup or role selection.
- Deactivated users are rejected before session issuance.
- Duplicate identity/email-confusion cases return 409 and record
  `link_conflict`.
- Verified Google email drift updates the ICE email only when the new address
  is unused and records `email_changed`.
- Google never grants or changes an ICE role.

## 7. M9 integration

Successful Google callbacks call `issue_session()` and return the same access
JWT plus opaque refresh token shape as password login. Google sessions inherit
M9 rotation, family revocation, logout, reuse detection, and deactivated-user
cutoff behavior.

## 8. Security/concurrency design

- State, nonce, and PKCE are cryptographically generated.
- Callback state is verified both by the SPA tab and backend HMAC validation.
- Invalid signature, issuer, audience, expiry, nonce, unverified email, and
  malformed state paths issue no Google session.
- Authorization codes and ID tokens are not logged or stored in audit changes.
- The unique `google_sub` index prevents duplicate provider identities.
- Concurrent first-time linking was tested with separate per-request database
  sessions. The invariant is exactly one bound identity; a second callback is
  either an idempotent normal login or a unique-index conflict.

## 9. Audit behavior

Implemented audit actions:

- `google_login`
- `account_linked`
- `link_conflict`
- `user_invited`
- `user_deactivated`
- `user_activated`
- `role_changed`
- `email_changed`

Google auth events include the request IP. Sensitive codes and tokens are not
included in audit rows.

## 10. Frontend changes

- Login page has a Continue with Google button and inline configuration errors.
- State and PKCE verifier are stored in `sessionStorage`.
- `/google/callback` validates the stored state, completes login, handles
  backend errors, and navigates to the Command Center.
- Google tokens use the existing auth-context token storage and refresh flow.
- Admin Users panel supports password users, Google-only invites, roles,
  activation/deactivation, and Google-linked/pending status.

## 11. Test results

- Focused M11 tests: **20 passed**.
- Full backend suite: **213 passed**.
- Migration suite: passed upgrade → downgrade → upgrade replay.
- Existing password auth, refresh, logout, RBAC, assignments, and audit tests:
  passing as part of the full suite.
- Re-review reruns: before the JWK fix focused **50**/full **211**; after the JWK
  fix focused **51**/full **212**; after the `at_hash` fix focused **52**/full
  **213**.

## 12. Migration verification

The real Alembic scratch-database test verified the complete chain through
`i7d8e9f0a1b2`, including the M11 columns and downgrade/replay behavior. A
fresh Docker PostgreSQL database was also upgraded from base through M11. The
Docker dev database is now at `i7d8e9f0a1b2`; direct inspection confirmed
nullable `hashed_password`, `google_sub`, `google_email`, and the unique
`ix_users_google_sub` index. A scratch database containing a Google-only row
correctly refused downgrade when restoring `hashed_password NOT NULL`.

The first host-side guard probe used the wrong PostgreSQL listener because
Homebrew PostgreSQL was still occupying port 5432; it was rerun against the
Docker listener after stopping that local service. No repository or database
data was changed except temporary scratch-database creation/removal.

### Callback incident diagnosis

The production-like callback log showed a successful token exchange (`200`),
then a successful JWKS HTTP request (`200`), followed by the generic 401.
`exchange_code_for_tokens()` only returns after confirming an `id_token` string,
so state verification, code exchange, and ID-token extraction had already
passed. The exact failure was `_fetch_google_certs()` returning no usable keys:
Google's current JWKS response contains RSA JWKs with `kid`, `n`, and `e`, but
no `x5c` entries. The old parser accepted only `x5c`, raised
`GoogleOAuthError("Google returned no usable signing keys")`, and
`google_callback()` converted that to HTTP 401 before signature or claim
validation.

The smallest safe fix accepts RSA `n/e` JWKs and retains `x5c` support while
requiring RSA signing keys with RS256/sig metadata. A regression test verifies
a signed token using the JWK representation.

### Second callback incident — `at_hash` claim

After the JWK parser was confirmed running, a fresh browser flow still returned
401. Temporary safe stage logging traced the exact failure:

```text
JWT_SIGNATURE_SUCCESS ... -> GOOGLE_AUTH_FAILURE stage=JWT_SIGNATURE
exception=JWTClaimsError
message=No access_token provided to compare against at_hash claim.
```

Google ID tokens include an `at_hash` claim bound to the exchange's access
token. python-jose verifies `at_hash` **by default** and demands the access
token, which we deliberately do not use or store. The reference implementation
chosen by the plan (`google.oauth2.id_token.verify_oauth2_token`) does **not**
verify `at_hash`. The fix sets `verify_at_hash: false` in the `jwt.decode`
options; signature/iss/aud/exp/iat/nbf/nonce/email/hd verification is unchanged.
A regression test signs a token carrying `at_hash` and confirms verification
succeeds.

A follow-up real browser flow then passed every OAuth stage
(state/code-exchange/JWKS/signature/iss/aud/temporal/nonce/hd/email) and reached
user resolution, where an email with no matching ICE user produced the expected
§7/C 403 ("No ICE account found") rather than a 401. That 403 is the documented
reject-unknown-email default, not a defect.

## 13. Frontend build/lint results

- `npm run build`: passed.
- `npm run lint`: passed with one pre-existing Fast Refresh warning in
  `frontend/src/lib/auth-context.tsx`.

## 14. Ruff/mypy results vs baseline

- Ruff: 2 pre-existing F401 errors remain in untouched files; no new M11 ruff
  errors.
- Mypy: 10 pre-existing errors remain; no new M11 mypy errors.
- `git diff --check`: passed.

## 15. Security review findings

- Google tokens are not stored or returned to the frontend.
- Email is not used as the authoritative Google identity key.
- Verified email, nonce, state, PKCE, issuer, audience, temporal claims and
  optional hosted domain are checked.
- Unknown-email auto-provisioning is disabled.
- Roles and assignments remain ICE-owned.
- Existing residual risks remain: refresh token in localStorage, in-memory
  per-process rate limiting, no production secrets manager, unguarded admin
  self/last-admin deactivation, and synchronous 10-second HTTP calls in the
  async Google callback path.
- Real Google OAuth smoke now passes through every verification stage; the
  only follow-up is provisioning an ICE account whose email matches the Google
  account (or linking an existing one) to complete login.
- `verify_state()` is stateless and therefore replayable within its freshness
  window; the design relies on PKCE and Google's single-use authorization code
  for replay resistance. This matches the saved plan's no-Redis design but is
  worth retaining as an explicit operational assumption.
- Email-conflict checks use application-level lower-case lookup while the
  existing database email uniqueness remains case-sensitive; concurrent or
  pre-existing case variants can still produce a conflict/500 edge case.
- The test's real concurrent first-link invariant is strong (one identity), but
  it allows the second callback to be either an idempotent 200 or a 409. The
  saved plan specifically described the loser as 409, so this is a documented
  behavior discrepancy rather than an untested race.

## 16. Documentation changes

- `CURRENT_STATE.md` now records M11 implementation and 213 passing tests.
- `ROADMAP.md` marks M11 application work complete while retaining Phase 4 as
  the real-user production gate.
- `SESSION_NOTES.md` records implementation decisions, verification, and
  environment limitations.

## 17. Remaining non-blocking concerns

- Real Google OAuth flow is verified through user resolution; provisioning an
  ICE account for the Google email completes the login.
- The original `httpx` incident was a stale image: the image was 11 hours old,
  its `/venv` had no `httpx`, and Compose bind-mounts only `backend/app`, not
  requirements or the virtualenv. A clean `docker compose build --no-cache
  backend` installed `httpx==0.27.2`, and the restarted container became
  healthy.
- Frontend automated tests do not yet exist.
- Pre-existing ruff/mypy debt remains.
- Docker Compose intentionally does not inject `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, or a redirect URI, so the running local stack returns
  503 for Google authorize until deployment configuration supplies them. The
  Login button displays an inline error rather than being hidden/disabled
  before the request.
- The callback uses synchronous `httpx.Client` calls from async FastAPI handlers
  (`google_auth.py`), so a slow Google endpoint can block a worker for the
  10-second timeout.
- The plan's `google-auth` dependency remains intentionally replaced by
  `python-jose` plus `httpx`; this is documented and unrelated to the callback
  failure.
- The saved plan document has a repository filename with an em dash rather than
  the shorter `M11_IMPLEMENTATION_PLAN.md` name referenced by the request.
- `tet` is an unrelated deleted/untracked-worktree artifact and was not
  modified as part of M11.

## 18. Real Google OAuth smoke-test results

Environment: Docker backend from a clean `--no-cache` image, Docker Postgres
(`ice_db`) at migration head `i7d8e9f0a1b2`, real Google OAuth client
ID/secret injected via Compose environment, redirect URI
`http://localhost:5173/google/callback`, Vite dev server on `localhost:5173`,
browser Google consent completed.

| Check | Result |
|---|---|
| `GET /auth/google/authorize` | 200 — returned consent URL, HMAC state, nonce, PKCE verifier |
| Redirect to Google | succeeded (browser navigated to `accounts.google.com`, consent completed) |
| Callback landing | returned to `http://localhost:5173/google/callback` |
| `POST /auth/google/callback` | reached user resolution (no 401) |
| Token exchange | `POST https://oauth2.googleapis.com/token` → 200, `id_token` present |
| JWKS | `GET https://www.googleapis.com/oauth2/v3/certs` → 200, 4 RSA keys parsed |
| ID-token verification | signature / iss / aud / exp / iat / nbf / nonce / `email_verified` / hd all passed (confirmed by stage logs) |
| ICE access/refresh tokens issued | **No — correctly.** The Google account's email had no matching ICE user, so the documented §7/C reject (403 "No ICE account found") fired; no session was minted for an unknown account |
| Resulting user/session behavior | not exercised live (no session issued); covered by automated M9/M11 tests |
| Refresh rotation after Google login | verified by automated tests (rotation, old-token rejection) |
| Logout/revocation after Google login | verified by automated tests (family revocation, refresh 401) |
| Deactivated-user cutoff | verified by automated tests (403 on callback, refresh cutoff) |
| Secrets/tokens in logs | none — no codes, ID tokens, refresh tokens, or client secret logged |
| Smoke-test limitation | end-to-end login was not completed because the test Google account was not provisioned in ICE; the full OAuth/verification pipeline and the expected unknown-email rejection were verified |

## 19. Security final review

Checklist — all items pass:

- No raw Google access/refresh tokens stored (exchange response never persisted).
- No raw ID tokens stored (verified in memory only).
- No authorization codes logged.
- State: HMAC-authenticated, freshness window enforced, SPA sessionStorage match.
- Nonce: embedded in the state payload, compared against the ID-token nonce.
- PKCE: S256 challenge at authorize, verifier at callback, Google verifies.
- Issuer: only `accounts.google.com` / `https://accounts.google.com`.
- Audience: must equal `GOOGLE_CLIENT_ID`.
- Temporal claims: exp/iat/nbf enforced.
- Verified-email enforcement: `email_verified == true` required to link or log in.
- `google_sub` uniqueness: unique DB index, one ICE account per Google identity.
- Duplicate-link race: unique-index `IntegrityError` → 409 + `link_conflict`.
- No automatic role assignment: Google never supplies a role.
- No public account creation: unknown emails rejected.
- Deactivated-user protection: 403 before session issuance + M9 refresh cutoff.
- M9 refresh rotation/revocation inherited; no parallel session layer.
- Logout revokes the session family server-side.
- Refresh-token storage limitation: `localStorage` (documented M9 XSS surface;
  access token stays memory-only).
- Rate limiting: Google authorize/callback 10/min/IP; login/refresh/logout
  limits unchanged.
- Sensitive-data leakage: no codes/tokens/secrets in logs, audits, or responses.
- Session fixation: sessions issued only after full verification; no pre-session
  binding.
- Predictable identifiers: state/nonce/verifier from `secrets.token_urlsafe`;
  refresh tokens opaque random.

## 20. Final verdict: SAFE TO COMMIT

Both real callback defects are fixed and regression-tested:

- JWKS RSA `n/e` key parsing (`_fetch_google_certs`).
- `at_hash` claim handling in `verify_google_id_token` (`verify_at_hash: false`,
  matching the plan's `google-auth` reference behavior).

A fresh real Google browser flow now passes every OAuth verification stage and
reaches user resolution; an unprovisioned email correctly returns the documented
§7/C 403 rather than a 401. Docker rebuild/startup/health/runtime imports pass,
the full suite is **213 passed**, and frontend build/lint are clean. No session,
RBAC, M9, or migration behavior was changed. To complete an end-to-end login,
provision an ICE account whose email matches the Google account (admin
`google_only` invite) or use a Google account matching an existing ICE user.
The synchronous external HTTP path and unguarded admin self/last-admin lockout
remain documented non-blocking concerns.

# M11 — Google Sign-In & User Onboarding: Implementation Plan

**Status:** PLANNED (not implemented). No code, migrations, or commits created.
**Branches/commits this plan assumes:** M9 committed as `0b12dd8`; pushed as part of `a68b81e` on `claude-development`. Migration head = `h6c7d8e9f0a1`.
**Date:** Aug 12, 2026.

See `docs/ROADMAP.md`, `docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`, `docs/SESSION_NOTES.md` for durable context. This plan was produced by an independent inspection of the repository; source code is ground truth.

---

## 1. Current authentication architecture

- **Password auth only.** `POST /auth/login` (rate-limited 5/min/IP) verifies bcrypt password, then calls `issue_session()` (M9) → opaque 64-char refresh token (SHA-256 hashed in `refresh_sessions`, `family_id` rotation chain) + HS256 JWT access token (`sub`=user UUID, `role`, `type=access`, 30 min). Response shape: `{access_token, refresh_token, token_type}`.
- **M9 session lifecycle:** `POST /auth/refresh` (10/min/IP) → `rotate_session()` under `SELECT ... FOR UPDATE` (old row revoked `'rotated'`, child row inserted); `POST /auth/logout` (10/min/IP) → family revocation; reuse past 10s grace → family kill; **deactivated users cut off**: sessions revoked on `is_active:false` (`revoke_user_sessions`) **and** a live `is_active` re-check on every refresh (never a JWT claim).
- Access tokens are stateless; `get_current_user` decodes + loads the user + enforces `is_active`; RBAC via `require_role` / `assert_can_view_project`.
- Auth events (`login`/`refresh`/`logout`/`refresh_reuse_detected`/`refresh_rejected_deactivated`) are audited with IP in the same transaction as the session change. Rate limiting = slowapi in-memory, per IP.

## 2. Current user/RBAC architecture

- `users`: `id (uuid)`, `email` (unique, indexed — **case-sensitive**), `hashed_password NOT NULL`, `full_name`, `phone`, `role` (enum `user_role`: admin/site_supervisor/procurement_manager/client), `is_active` (default true), `created_at`, `updated_at`. Dev DB confirmed at these exact 9 columns.
- Admin-only: `GET/POST /users` (create requires `password`), `PATCH /users/{id}` (`full_name`, `phone`, `is_active` — **no role change today**), `GET/POST/DELETE /projects/{id}/assignments` (assign/unassign, `_ASSIGNABLE_ROLES` = supervisor/client, audited `assign`/`unassign`).
- Visibility: admin + procurement see all projects; supervisor/client only assigned (`project_assignments` unique `(project_id, user_id)`).
- **No admin user-management UI exists** — only `ProjectAssignments.tsx` (assign/unassign on ProjectDetail) consumes `GET /users`. Users are currently created via API/seed only.
- Audit: `record_audit()` writes `audit_logs` (`action` varchar(100), `table_name`, `record_id`, `changes` JSONB, nullable `ip_address`) in the caller's transaction. No second audit system — M11 uses this.

## 3. Current M9 integration point

The single seam is `app/services/auth_tokens.py` (`issue_session` / `rotate_session` / `revoke_token` / `revoke_user_sessions`) called from `app/api/v1/auth.py`. Login/refresh/logout already: resolve a `User` → `issue_session` → audit → return `TokenResponse`. **Google login slots in by producing a `User` (link or lookup) and then calling the exact same `issue_session` + audit path** — the Google flow gets the entire M9 rotation/revocation/deactivation-cutoff stack for free, including `refresh_sessions` (keyed by `user_id`, no provider columns needed). No changes to the session layer are required.

## 4. Recommended Google Sign-In architecture

**OAuth 2.0 Authorization Code + PKCE, with server-side code exchange** (recommended; rationale in §11):

1. `GET /auth/google/authorize` (public, rate-limited): backend generates `state` (random), `nonce` (random), and `code_verifier`/`code_challenge` (S256 PKCE); returns `{authorize_url, state, code_verifier, nonce}`. `state` is a self-verifying token: `state = base64(nonce ‖ HMAC-SHA256(secret, nonce))`, so the backend can recover + validate the nonce on callback **without Redis/DB storage** (Redis is provisioned but unused — avoid adding a runtime dependency). Frontend stores `state` + `code_verifier` in `sessionStorage` and navigates the whole tab to `authorize_url`.
2. Google redirects to `GOOGLE_REDIRECT_URI = {SPA_ORIGIN}/google/callback?code=…&state=…`.
3. SPA callback route verifies `state` matches sessionStorage, then `POST /auth/google/callback {code, code_verifier, state}`.
4. Backend verifies `state` (HMAC + nonce recovery), exchanges `code`+`code_verifier` (+ `GOOGLE_CLIENT_SECRET`, kept server-side) for an ID token, then **verifies the ID token server-side**: RS256 signature against Google's JWKS, `iss ∈ {accounts.google.com, https://accounts.google.com}`, `aud == GOOGLE_CLIENT_ID`, `exp`/`iat`/`nbf`, `nonce` matches the recovered nonce, `email_verified == true`, optional `hd` check (workspace-domain lock).
5. Resolve the ICE user (§7), check `is_active` (deactivated → 403, no session), then `issue_session` → audit `google_login`/`account_linked` → return the same `TokenResponse`. The SPA drops the pair into the existing token storage and continues exactly as after password login.

Scopes: `openid email profile` only. **No Google access/refresh token is requested or stored** — we only need the ID token. Client secret lives only in backend env.

## 5. User/account data-model changes

**Minimum safe design — three column changes on `users`, no new tables:**

| Column | Change | Purpose |
|---|---|---|
| `hashed_password` | **DROP NOT NULL** | Google-only (invited) users have no password |
| `google_sub` | **ADD** `VARCHAR(255) NULL` + **unique index** | Authoritative Google identity key (`sub` is immutable, never trusts email alone) |
| `google_email` | **ADD** `VARCHAR(255) NULL` | Verified email as reported by Google at link time (diagnostics + email-change handling) |

**Deliberately rejected:** an `auth_provider` enum column (redundant — `google_sub` presence + null password already encodes provider state; a future provider adds one column, not an enum migration); an invite-token/link table (an invited user is just `hashed_password IS NULL AND google_sub IS NULL` → "pending Google link" is derivable, no new table); provider session tables (M9 `refresh_sessions` already covers it).

**Email handling:** the existing `users.email` unique constraint is case-sensitive (pre-existing debt). M11 does **case-insensitive** lookups/linking (`lower(email)`) and rejects invites whose `lower(email)` already exists. Adding a `lower(email)` functional unique index is *considered but not recommended now* — it can fail on existing duplicates and is not required for correctness.

## 6. Admin onboarding design

Flow (no email infra in the product — invite is a *pending status*, not a magic link):

1. **Admin creates the user:** `POST /users` extended with `google_only: bool`. With `google_only=true`, `password` is **not required** and the resulting user is `hashed_password IS NULL`, `google_sub IS NULL` → status "Pending Google link". With `google_only=false`, behavior is unchanged (password required, existing validators). Admin chooses `role` at creation (all 4 roles incl. client). Default `is_active=true` (admin toggles later).
2. **Admin assigns projects:** unchanged `POST /projects/{id}/assignments` (admin-only, supervisor/client only). Unchanged `PATCH /users/{id}` for `is_active`, plus **newly supported `role` field** (audited `role_changed`) so admin controls role throughout the lifecycle, not just at creation.
3. **User activates:** the invited user signs in with Google (matching verified email) → first successful callback binds `google_sub` (the "accept/activate" step) → normal ICE session. No self-service role selection anywhere; no public signup.
4. **Deactivate/reactivate:** unchanged `PATCH /users/{id}` — M9 `revoke_user_sessions` + live `is_active` check already block Google-linked sessions too.

Admin UI: a small admin-only **Users panel** (new, see §9). Consideration: prevent an admin from deactivating themselves (self-lockout) — flagged in §15.

## 7. Existing-user linking strategy

| Scenario | Behavior |
|---|---|
| **A. Existing local user, same verified email** | Resolve by `google_sub` (none) → by `lower(email)` match → bind `google_sub` + `google_email` on the existing row. Role/assignments/password untouched. Audit `account_linked`. Silent link is acceptable because `email_verified` proves the Google identity owns that email; an optional explicit "Link this Google account?" confirm step is a decision point for the owner (default: silent + full audit). |
| **B. Existing Google user signs in again** | `google_sub` match → normal login, role preserved. Audit `google_login`. |
| **C. New Google user (no sub, no matching email)** | **Reject** (default): "No ICE account found for this email — ask an administrator to add you." No auto-create (no public signup, no self-selected roles). Owner may later opt into auto-create-with-role-client. |
| **D. Deactivated user attempts Google login** | Resolve user → `is_active == false` → **reject** (403 generic, mirroring the password path), no session issued. M9 cutoff is preserved for any previously issued sessions. |
| **E. Same Google identity → multiple users** | Impossible by construction: unique index on `google_sub`. A second bind attempt → `IntegrityError` → 409 + audit `link_conflict`, never a silent second account. |
| **F. Admin-created (invited) user later uses Google** | Invite row is `hashed_password NULL`, `google_sub NULL` → email match binds `google_sub`, status flips to linked. Same as A with no password to keep. |
| **G. User changes Google email** | `sub` is immutable → identity intact. On next sign-in, new verified email differs: if `lower(new)` is free → update `users.email` + `google_email`, audit `email_changed`; if another user holds it → reject 409 (account-confusion guard). |
| **H. No usable verified email** | `email_verified == false` or missing email claim → **reject** generically. Never link or create on an unverified email. |

Lookup order everywhere: **`google_sub` first (authoritative), verified email second (link path only)** — email is never proof of identity on its own.

## 8. API changes

| Endpoint | Auth | Change |
|---|---|---|
| `GET /auth/google/authorize` | public (rate-limited, e.g. 10/min/IP) | New. Returns `{authorize_url, state, code_verifier, nonce}`; stateless HMAC-bound state. |
| `POST /auth/google/callback` | public (rate-limited, e.g. 10/min/IP) | New. Body `{code, code_verifier, state}` → verify state, exchange, verify ID token, resolve/link/create (reject policy), enforce `is_active`, `issue_session` (M9), audit, return `TokenResponse`. Reuse the M9 login handler's audit+commit pattern exactly. |
| `POST /users` | admin | `UserCreate` gains `google_only: bool = False`; `password` becomes optional iff `google_only` (kept required otherwise — no weakening of the password path). New audit action `user_invited` for google-only creations. |
| `PATCH /users/{id}` | admin | `UserUpdate` gains `role`. Audited as `role_changed`; `is_active` transitions audited as `user_deactivated`/`user_activated` (distinct actions; the generic `update` row is retained or replaced per owner preference — one test asserts the current `update` shape, flag in §13). |
| everything else | — | Unchanged. Assignments keep `assign`/`unassign`; refresh/logout/me untouched. |

## 9. Frontend changes (smallest surface)

- **`Login.tsx`:** add a "Continue with Google" button + divider above the existing form. On click → `GET /auth/google/authorize`, stash `state`/`code_verifier` in `sessionStorage`, `window.location.href = authorize_url`. Error from authorize (e.g. missing config) shown inline. Existing email/password form untouched.
- **New route `/google/callback`** (`App.tsx` + new `GoogleCallback.tsx`): reads `code`/`state` from the URL, verifies `state`, POSTs to `/auth/google/callback`, stores tokens via the existing `auth-context` token helpers, navigates to `from`/`/`. Renders error states: no-account-found, deactivated, expired/invalid token, "try again".
- **`auth-context.tsx` / `api.ts`:** add one `googleLogin(code, state, verifier)` wrapper reusing `setAccessToken`/`setStoredRefreshToken`; `logout()`/bootstrap already work unchanged (Google sessions are normal ICE sessions).
- **New admin-only Users panel** (CommandCenter admin section or ProjectDetail tab): list users (email, name, role, active, linked status derived from `google_sub`/password-null), create user (email, name, phone, role, `google_only` toggle), activate/deactivate, change role. Reuses existing `GET/POST/PATCH /users`. Project assignment stays in the existing `ProjectAssignments` panel.
- **`types/index.ts`:** `User` gains optional `google_linked: boolean` (or expose via `UserRead`); `UserCreateInput` gains `google_only`; new `GoogleAuthorizeResponse`/`GoogleCallbackInput` types.
- No new frontend dependencies (no Google JS SDK), no auth architecture changes, no unrelated UI work.

## 10. Audit changes

All via existing `record_audit()` in the same transaction as the change (no second system). New actions (all with IP for auth events):

- `google_login` — successful Google sign-in (like `login`).
- `account_linked` — `google_sub` bound to an existing/invited ICE user (A/F).
- `link_conflict` — duplicate `google_sub` / email-confusion rejection (E/G).
- `user_invited` — google-only user created (no password).
- `user_deactivated` / `user_activated` — distinct from the generic `update`.
- `role_changed` — admin changes a user's role.
- `email_changed` — Google email drift syncs `users.email` (G).

Existing `login`/`refresh`/`logout`/`assign`/`unassign`/`create`/`update` remain. The reject (C/H/D) paths log a rejection event where useful; failures must never log the ID token or code.

## 11. Architecture decision

**Recommended: Authorization Code + PKCE, server-side exchange** (the "backend exchange" pattern), vs. the alternatives:

1. **Code + PKCE, server-side exchange (chosen).** SPA redirect → code → backend exchanges + verifies ID token → issues ICE pair. No Google SDK in the SPA, ID token never touches JavaScript, code is single-use, PKCE + state + nonce all server-verified, client secret server-side, and the SPA receives the exact same `TokenResponse` it already consumes. No new auth architecture.
2. **Google Identity Services (GIS) token-in-JS → backend verify.** Fewer redirects, but loads a third-party SDK and puts the ID token in JS (extra XSS surface) and adds a Google dependency to the SPA.
3. **Backend-redirect `/callback` full flow.** Tidy server-side, but the browser hits a backend URL; returning tokens to the SPA either needs httpOnly cookies (explicitly deferred in M9) or tokens in a URL fragment (bad) — it fights the current token-transport design.

Option 1 is the only one that keeps the M9 localStorage-refresh transport, keeps all verification server-side, requires no new frontend deps, and adds no second session architecture. **Chosen.**

## 12. Security considerations

- ID-token verification per Google: JWKS RS256 signature, exact `iss`/`aud`/`exp`/`nbf`, `nonce` (stateless HMAC state binding), `email_verified == true`, optional `hd` workspace restriction.
- **Never trust email as identity**: `google_sub` is the identity key; verified email is only the link path; unverified email → reject.
- `google_sub` unique index → no duplicate identities; race-safe (IntegrityError → re-read/409, the M10 `select_project_code` retry pattern).
- No Google access/refresh tokens requested or stored (scopes `openid email profile` only).
- Google sessions are plain M9 sessions: rotation, logout family-revocation, reuse-detection, deactivated cutoff, `is_active` live check all inherited — no parallel mechanism.
- Google never grants a role; ICE role/assignments preserved; no public signup, no self-selected roles; invited users get whatever role the admin assigned.
- Rate limiting on both new endpoints (per-IP); login/refresh/logout limits untouched; `POST /users` still admin-only.
- Callback CSRF/replay: state (HMAC) + PKCE + single-use code; log no tokens/codes.
- Config additions (all env, never committed): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (`http://localhost:5173/google/callback` in dev), optional `GOOGLE_HOSTED_DOMAIN`. Missing config → `GET /auth/google/authorize` fails cleanly and the button hides/disables.

## 13. Test plan

`tests/test_google_auth.py` (new). ID-token verification isolated in a small `app/services/google_auth.py` `verify_google_id_token(token, expected_nonce, expected_aud, expected_iss, expected_hd)` that accepts an injectable JWKS/cert source — tests sign an RS256 token with a test keypair and serve its public key, so the real verification path (signature/iss/aud/exp/nonce) is exercised without network. Scenarios:

1. New Google user (invited via `POST /users google_only`) → links on callback, gets M9 session.
2. Existing Google user re-sign-in → role/assignments preserved, `google_login` audited.
3. Duplicate provider identity → unique-index 409/`link_conflict`.
4. Verified vs unverified email → link vs reject.
5. Invalid signature / wrong audience / wrong issuer / expired token / wrong nonce → 401 + audit, no session.
6. Deactivated user callback → 403, no session; existing Google session still cut off by M9.
7. Role + project-assignment preservation after Google login (RBAC unchanged).
8. M9 session: refresh rotation + logout family revocation after Google login.
9. Password-login regression (`test_auth.py` untouched/passing).
10. Existing RBAC regression (full suite).
11. Audit events: `google_login`, `account_linked`, `user_invited`, `role_changed`, `user_deactivated/activated`, `link_conflict` all present with correct actor/IP.
12. Concurrent duplicate first-time callback (two connections, same sub) → exactly one link, other 409 (real-connection gather, the M9 pattern).
13. `POST /users` `google_only` validation (password required iff not google_only); role-change PATCH + audit.
14. Migration test update: add M11 revision to `test_migrations.py` (upgrade/downgrade/replay on scratch DB; downgrade guarded per §14).
15. `PATCH /users` distinct `user_deactivated`/`user_activated` actions (adjust the one existing assertion that expects generic `update`).

## 14. Files expected to change

**Backend — new:**
- `backend/alembic/versions/<rev>_m11_google_signin.py` (revision id assigned at creation; `down_revision = 'h6c7d8e9f0a1'`)
- `backend/app/services/google_auth.py` (authorize-url build, stateless state/nonce, ID-token verification)
- `backend/tests/test_google_auth.py`

**Backend — modified:**
- `backend/app/models/user.py` (nullable `hashed_password`, `google_sub`, `google_email`)
- `backend/app/schemas/user.py` (`google_only`, optional password; `role` in `UserUpdate`; `google_linked` in `UserRead`)
- `backend/app/api/v1/auth.py` (`google/authorize`, `google/callback`)
- `backend/app/api/v1/users.py` (invite creation, role change, distinct deactivation audit actions)
- `backend/app/core/config.py` (Google settings)
- `backend/app/core/rate_limit.py` (`GOOGLE_RATE_LIMIT`)
- `backend/requirements.txt` (`google-auth`)
- `backend/tests/test_migrations.py`, `backend/tests/conftest.py` (JWKS/test-key fixture), possibly one assertion in an existing user test
- `backend/.env.example` (Google vars) — if that file is kept in repo convention

**Frontend — modified:**
- `frontend/src/pages/Login.tsx` (Google button)
- `frontend/src/pages/GoogleCallback.tsx` (new)
- `frontend/src/App.tsx` (`/google/callback` route)
- `frontend/src/lib/api.ts`, `frontend/src/lib/auth-context.tsx` (`googleLogin`)
- `frontend/src/types/index.ts`
- `frontend/src/components/UsersPanel.tsx` (new, admin-only) + hosting page

**Docs:** `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md` (post-implementation).

## 15. Risks / trade-offs

- **localStorage refresh token (deferred httpOnly cookie)** is unchanged by M11 — the same documented XSS surface, mitigated by M9 rotation/revocation; Google reduces password exposure but not this.
- **No email infrastructure:** invites are "pending" status, not emailed magic links; a user who doesn't know their invite email can't discover it from the app (acceptable for v1, note as limitation).
- **Downgrade risk:** restoring `hashed_password NOT NULL` on downgrade fails if Google-only users exist → downgrade must be guarded/documented as destructive for those rows.
- **Silent link consent** (scenario A): chosen for UX; audit + `email_verified` mitigate. Owner can opt into an explicit consent step.
- **Case-sensitive email unique constraint** (pre-existing): M11 handles by `lower()` lookups; a functional unique index is deferred to avoid failing on existing duplicates.
- **Reject-policy for unknown emails** is the default; auto-create-with-client-role is an owner decision.
- **Admin self-deactivation / last-admin lockout** is currently unguarded; flag for a small guard.
- **New external dependency + network call** at callback (Google token endpoint/JWKS) — timeouts, retries, and fail-closed handling required; test path avoids network via injected certs.
- **Frontend sessionStorage state/verifier** can be cleared mid-flow (tab close) → benign error + retry; documented.

## 16. Recommended implementation sequence

1. Config + `google-auth` dependency + `.env.example`/README dev setup.
2. `services/google_auth.py` (authorize URL + stateless state/nonce + verifiable ID-token check) — unit-testable without network.
3. Migration `users` (nullable password, `google_sub` unique, `google_email`) + update model/schemas.
4. `users.py` onboarding: `google_only` invite, role in `UserUpdate`, distinct `user_activated/deactivated` + `role_changed`/`user_invited` audit.
5. `auth.py` `google/authorize` + `google/callback` (link matrix §7, M9 session issue, audits) + rate limits.
6. `test_google_auth.py` (incl. real-connection concurrency) + migration-test update + adjust the one `update`-action assertion; run full `pytest`, ruff, mypy (baseline compare).
7. Frontend: types → `auth-context`/`api.ts` → Login button → `/google/callback` route → admin Users panel.
8. `npm run build` + `npm run lint`; live smoke against dev stack (password regression, Google callback with a real dev OAuth client or token fixture, M9 logout after Google login).
9. Update `docs/CURRENT_STATE.md` / `docs/ROADMAP.md` / `docs/SESSION_NOTES.md`; owner decides silent-link consent + unknown-email policy before rollout.

---

*Owner decisions still open before implementation:* silent-link consent (§7 A) vs explicit consent step; unknown-email policy (§7 C) reject vs auto-create-client; distinct `user_deactivated`/`user_activated` audit actions vs retaining generic `update`; Admin Users panel placement (CommandCenter vs ProjectDetail).

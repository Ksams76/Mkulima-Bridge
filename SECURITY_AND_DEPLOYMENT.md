# Security and deployment readiness

This build now includes **local prototype farmer registration, sign-in and per-account workspace isolation**. It is still not ready for public production deployment.

## Implemented in this prototype

- Farmer registration with normalized email addresses and unique-account enforcement.
- Passwords are hashed with PBKDF2-HMAC-SHA256 and a random per-password salt; plaintext passwords are not stored.
- Login creates an opaque, random, server-side session. The browser receives an HttpOnly, SameSite=Lax cookie; session tokens are stored as SHA-256 hashes in the accounts database.
- Sessions expire after a configurable period (`SESSION_DAYS`, 14 by default and clamped to 1–30 days). Logout revokes the current session.
- Private API routes require a valid session by default (`AUTH_REQUIRED=true`). Static assets, health/knowledge metadata, learning module definitions, and aggregated Community Pulse output are public. Category-only community report submission requires a signed-in account and explicit consent.
- Each account's private workspace uses a separate SQLite database file. Profile, cases, observations, assessments, reminders, history, learning progress, referrals and inventory therefore do not share a private workspace database between accounts in this single-instance prototype.
- The old shared demo database is left untouched and is not automatically claimed by the first new account.
- Farm Profile now returns an explicit saved state and timestamp. Farmer name, county and main crop are required; the frontend displays the saved details and an edit action.
- Community Pulse uses a separate shared database and stores only the farmer-consented crop or animal species, county, case type, category and timestamp fields; groups with fewer than three reports are suppressed. The total report count is shown immediately, while matching groups remain hidden until they meet the threshold.
- Account-scoped Settings save theme, compact layout, preferred response detail, AI history preference, language, regional and farm preferences, weather-location preferences, and in-app reminder/low-stock toggles. Weather preferences do not mean live weather is integrated; notification preferences do not send SMS, email or push alerts.
- Crop and livestock cases can include private video attachments. Supported types are MP4, MOV and WebM, with a 20 MB server limit and a 60-second browser-side duration check. Videos are stored under the local account upload directory and are not processed by AI. They are not yet stored in durable cloud object storage.
- Livestock support records species, group, age group, affected count and concern category. AI responses are cautious decision support, not veterinary diagnosis or treatment; serious or uncertain concerns require a qualified veterinary professional.
- ExpertConnect offers crop and livestock expertise categories and prepares a shareable case summary. It does not currently connect to a verified expert directory or send a referral automatically.

## Still required before public deployment

1. Migrate account data and the shared community reports into a managed PostgreSQL database with proper schema migrations, transactions, indexes and backup/restore procedures. Migrate case-media files to durable object storage such as Spaces; do not rely on App Platform instance-local storage for uploads. Separate SQLite files are a local prototype technique, not a scalable multi-instance tenancy design.
2. Enforce HTTPS and set `SESSION_COOKIE_SECURE=true`. Configure strict production CORS/origin settings and implement a complete CSRF/origin validation strategy for state-changing requests.
3. Add robust login/register rate limiting, abuse monitoring, email verification, password reset/recovery, session/device management and optional multi-factor authentication.
4. Add explicit roles and permissions for farmers, extension officers, supervisors and administrators. The current supervisor token is a local prototype gate and the overview reports only the signed-in account's workspace, not all farmers.
5. Define account export, account deletion, data retention and support processes. Review consent and the handling of AI-provider data sharing.
6. Complete independent security testing, dependency vulnerability review, logging/monitoring, backup restoration drills and real-device accessibility testing.
7. Have the agricultural knowledge corpus, advice and Kiswahili wording reviewed by qualified Kenya-based agricultural specialists. Have livestock content reviewed by a qualified veterinary professional before any public use.

## Local configuration

Copy `.env.example` to `.env`. For local HTTP development, `APP_ENV=development` and `SESSION_COOKIE_SECURE=false` are appropriate. On a hosted HTTPS environment, set `APP_ENV=production` and `SESSION_COOKIE_SECURE=true`; production defaults the cookie to secure if the setting is omitted. Keep `AUTH_REQUIRED=true`. Do not commit `.env`, account databases, farmer data or API credentials to GitHub.

## Database layout in this local build

- Base database: legacy single-user demo data, retained but not assigned to new accounts.
- Accounts database: `<base-name>_accounts.sqlite3`, containing account records and hashed session tokens.
- Account workspaces: `<base-name>_users/user_<id>.sqlite3`, one private local SQLite file per account.
- Community aggregate database: `<base-name>_community.sqlite3`, containing only category-only community report fields.

These files and the local `backend/uploads/` directory may contain private farmer information and video files. Protect them, back them up securely during local testing and never upload them to a public repository. This file-per-account approach is deliberately limited to one local application instance; migrate to PostgreSQL before a DigitalOcean multi-instance or public pilot deployment.

# ShambaSense AI / MkulimaBridge – Implementation Notes

Updated working copy of the uploaded project. The original uploaded ZIP was not modified.

## Latest extension – Settings, livestock, short videos and working module flows

- Added account-scoped Settings endpoints and screens for Account, Farm, Weather preferences, Notifications, AI response/history preferences, Language & Region, Appearance, Privacy & Security and About. Theme (light/dark/system) and compact layout are applied by the frontend. `response_style` now changes Ask AI and crop case prompts; `save_ai_history` is respected by normal Ask AI, demo Ask AI and photo diagnosis. Language selection applies to AI answer and speech controls; full interface translation is not yet implemented. Weather and notification toggles are preferences only, not live weather or outbound notifications.
- Added a Livestock Care case workflow for cattle, goats, sheep, poultry, pigs, rabbits, camels, fish and other animals. It records species, group/breed, age group, affected count, concern category, symptoms and onset. Livestock assessment prompts are cautious decision support, not veterinary diagnosis, and do not recommend medicines or dosages.
- Added case video attachments for MP4/MOV/WebM, max 20 MB; the browser checks for clips no longer than 60 seconds (15–30 seconds recommended). Files are private to the signed-in account in `MEDIA_ROOT/user_<id>/`, linked to the case and removable. Videos are not processed by AI. The frontend warns users against unnecessarily capturing people or precise identifying details. Local upload storage is not cloud-durable; migrate to object storage before DigitalOcean deployment.
- Community Pulse now accepts crop and livestock category-only reports, immediately confirms the saved report and displays the total report count. Similar groups remain hidden until at least three matching reports are aggregated; reports are not independently verified or deduplicated by farmer.
- ExpertConnect now loads suitable categories according to the selected crop or livestock case, recommends a professional role, records urgency and context, and prepares a farmer-controlled summary. There is no verified expert directory or automatic message delivery.
- Inventory now supports full-field edits, create/delete, a visible refresh control, animal feed and veterinary supplies categories, explicit operation feedback and dashboard refresh after changes.
- Fixed API fetch credentials for the VS Code Live Server `:5500` to FastAPI `:8000` setup; protected requests explicitly include the HttpOnly session cookie. Video previews also use the backend origin when Live Server is used.
- Added dark theme and compact-layout styles; fixed persistence of preferences and AI provider status presentation. Added a root `requirements.txt` include file for cloud-buildpack discovery.

## Validation after latest extension

- `python -m pytest backend/tests -q`: **53 passed, 1 skipped** in this build environment.
- `python -m py_compile backend/main.py`: passed.
- `node --check` for `app.js`, `extended.js`, `auth.js` and `ui.js`: passed.
- New tests cover account-scoped settings, livestock workflows, specialist categories, animal-safe assessments, local video upload/access isolation/deletion, inventory persistence and cross-account isolation, immediate Community Pulse counts/privacy threshold, and AI style/history preferences.
- A full interactive browser run is still required on the target device. The server-side tests do not validate live AI response quality, video decoding on all browsers, or a DigitalOcean deployment.


### Farmer accounts and saved profiles
- Added farmer registration and sign-in with normalized unique email addresses.
- Passwords are stored as PBKDF2-HMAC-SHA256 hashes with random salts; raw passwords are never persisted.
- Added opaque server-side sessions with hashed session tokens, an HttpOnly SameSite=Lax cookie, expiry and logout revocation.
- Private API routes require a valid account session by default. Test suite has an explicit test-only auth bypass; dedicated auth tests turn auth on.
- Each account receives its own SQLite workspace file for profile, cases, reminders, history, learning records, referrals and inventory. Community category-only reports use a separate shared aggregate database.
- Existing legacy demo database is preserved and is not automatically attached to new accounts.
- Farm Profile validates farmer name, county and main crop; save returns a clear success message and timestamp. Frontend shows the farmer's saved details and an Edit Details action.

### Phase 1–2 carried forward
- Farm Problem Case Management: case references, crop/problem details, status changes, observations, AI assessments, linked FarmActions.
- Existing legacy SQLite database and its profile/history/reminder records are preserved untouched. New accounts receive independent workspace files and do not automatically inherit legacy single-user demo records.

### Phase 3 – Farmer Workspace
- `/dashboard/summary` aggregates open cases, upcoming/pending/completed tasks, inventory alerts and learning sessions.
- Frontend workspace cards show upcoming tasks and recently updated cases.
- New `case_events` timeline records case creation, observations, status updates, AI assessments, FarmAction creation/update/deletion and referral-summary preparation.

### Phase 4 – Learning & Practice
- Three structured learning modules: field scouting, integrated pest management and farm records.
- English and Kiswahili lesson text and quizzes.
- Scores and session history are saved in SQLite. Scores are practice feedback, not certification.

### Phase 5 – Community Pulse
- Opt-in category-only reports store crop, county, issue category and timestamp.
- Aggregated results suppress groups below three reports.
- Results are explicitly labelled farmer-reported and not independently verified.
- Counts are submitted reports, not deduplicated unique farmers. The feature is not outbreak detection.

### Phase 6 – ExpertConnect
- Builds a structured summary from a selected case, including observations and the latest AI assessment.
- User can copy and share the summary themselves.
- Referral status can be recorded as prepared, shared by farmer, response received or closed.
- No automated email, SMS, WhatsApp or extension-officer integration is claimed.

### Phase 7 – Farm Inventory
- Add, update and delete stock records.
- User-defined reorder thresholds drive low-stock alerts and dashboard counts.
- Quantities are manually maintained; no supplier or shop stock integration exists.

### Phase 8 – Intelligence / Knowledge / Language
- Added a small starter knowledge corpus with excerpts paraphrased from KALRO and FAO references, with source URLs and review date metadata.
- Existing lexical retrieval now has material to retrieve; it remains local keyword matching, not live search or vector RAG.
- Existing Groq/Hugging Face options remain.
- Added configurable offline `DEMO_MODE=true` scripted responses for `/ask` and case assessment. The response explicitly identifies itself as demo content; this mode must not be used for real crop decisions.
- Added user-triggered spoken read-aloud using browser speech synthesis; existing speech input is retained.
- Photo analysis remains manual upload. Continuous background camera capture was deliberately not added.

### Phase 9 – Supervisor Overview
- Added `/supervisor/overview`, gated by `SUPERVISOR_ACCESS_TOKEN` and `X-Supervisor-Token`.
- Shows aggregate local prototype metrics and recent case summaries.
- This is not a true supervisor account or role-based access-control system. The overview summarizes only the signed-in account's workspace.

### Phase 10 – QA / demo readiness
- Updated README, `.env.example`, and this implementation note.
- Added endpoint regression tests for the new workflows.
- Kept existing tests for profile, Ask AI, diagnosis, reminders, knowledge status and case management.

## Validation completed in this environment

- `python -m pytest backend/tests -q`: **53 passed, 1 skipped** after the latest settings, livestock, media, inventory, community and expert-category additions.
- `python -m py_compile backend/main.py`: passed.
- `node --check frontend/js/auth.js`: passed.
- `node --check frontend/js/app.js`: passed.
- `node --check frontend/js/extended.js`: passed.
- `node --check frontend/js/ui.js`: passed.
- HTML structure check: 241 IDs, no duplicate IDs, no missing in-page anchors, and no missing local assets (latest build).
- Dedicated auth tests cover registration, login, logout, HttpOnly/SameSite cookie attributes, duplicate email rejection, password checks, profile save/view, required fields, and case/profile isolation between two accounts.
- Local FastAPI server checks: `/`, `/health`, `/docs`, `/js/app.js`, `/js/extended.js`, `/css/style.css` returned HTTP 200.
- Playwright/Chromium local-page navigation was blocked by the execution environment (`ERR_BLOCKED_BY_ADMINISTRATOR`), so a complete visual interaction test on the target Windows laptop remains required.

The ONNX classifier test module is skipped because ONNX Runtime is not installed in this build environment; the project requirements include ONNX Runtime for compatible local installation. A Playwright browser smoke test was attempted, but Chromium navigation to the local server was blocked by the execution environment (`ERR_BLOCKED_BY_ADMINISTRATOR`), so visual interaction still needs confirmation in the user's Windows browser. Fake LLM clients are used in tests; no live model-provider factual-quality test has been run.

## Important limits before public deployment

- Authentication and local per-account SQLite workspace isolation are implemented, but email verification, account recovery, login rate limiting, full CSRF/origin review, production PostgreSQL tenancy and true supervisor/extension-officer roles are not.
- The supervisor token is a local prototype gate only. Do not expose it publicly.
- No SMS/email/push notification delivery.
- No actual expert messaging or confirmation that a human has reviewed a case.
- Community reports can be repeated by the same submitter; counts are reports, not unique farmers.
- No live weather, market-price, logistics or supplier inventory feed.
- Photo classifier labels currently cover pepper, potato and tomato only; no independently measured field accuracy.
- Agricultural guidance and knowledge excerpts need review by a qualified Kenya-based agricultural extension specialist before use as operational advice.

## Database additions

- `cases`, `case_observations`, `case_assessments` (Phase 1–2)
- nullable `reminders.case_id` (Phase 1–2)
- `case_events`
- `learning_sessions`
- `users`, `sessions` in a separate accounts database; account-specific workspace SQLite files
- `community_reports`
- `expert_referrals`
- `farm_inventory`
- `users` and `sessions` in a separate accounts database; one private SQLite workspace file per registered account

All new tables are created with `CREATE TABLE IF NOT EXISTS`; the `reminders.case_id` field is added with a guarded migration. Existing records are not deleted by the migration.

### Account and profile API routes
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- Private workspace routes require the HttpOnly session cookie by default.
- `GET /profile` returns the signed-in account's saved state and timestamp; `PUT /profile` validates and saves the signed-in account's details.


## Frontend/backend integration audit (31 Oct 2026)

- There is no `scripts.js` by design: the frontend JavaScript is split into `js/auth.js`, `js/app.js`, `js/extended.js` and `js/ui.js`, loaded by `index.html` and served by FastAPI under `/js/`.
- Every API path called by those files maps to an existing FastAPI route, and every element ID the scripts look up exists in `index.html`.
- Fixed: `CORSMiddleware` was registered before the auth middleware, so preflight requests and 401 responses from `http://127.0.0.1:5500` (VS Code Live Server) had no CORS headers and JSON calls failed. CORS is now registered after the auth middleware, and `OPTIONS` requests skip auth. Regression test added in `backend/tests/test_auth.py`.
- Fixed: the photo-analysis request (`/diagnose`) did not send the session cookie in the Live Server setup, so it returned 401.
- Added the `.env.example` the README refers to. `/diagnose` needs `CLASSIFIER_MODEL_PATH` and `CLASSIFIER_LABELS_PATH` in `.env`; without them it returns 503.

# ShambaSense AI / MkulimaBridge

An agriculture decision-support prototype for Kenyan smallholder farmers. **ShambaSense AI** remains the existing advisory engine; the new workspace features extend it toward the wider **MkulimaBridge** vision. The app keeps its FastAPI + SQLite + HTML/CSS/vanilla JavaScript architecture, existing AI-provider switch, voice input, crop-photo analysis, farm profile, history and reminders. Farmer registration and sign-in are included in the local prototype, with separate account data stores, saved settings and an editable farm profile. Crop and livestock case workflows, short case-video attachments, and specialist-category recommendations are supported.

> Product principle: help farmers record a challenge, understand possible next steps, follow up and prepare useful information for a qualified human adviser. AI output is not a confirmed diagnosis.

## Run locally (Windows / VS Code)

1. Extract the ZIP to a new folder and open the `ShambaSenseAI` folder in VS Code. Keep your original project as a backup.
2. Open a PowerShell terminal in the project root and run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r backend\requirements.txt
   python -m pip install -r backend\requirements-dev.txt
   ```

3. Copy `.env.example` to `.env`. Add your own `GROQ_API_KEY`, or configure Hugging Face as described below. Never paste `.env` or API keys into chat, GitHub, screenshots or public repositories.
4. Start the application from the project root:

   ```powershell
   python -m uvicorn backend.main:app --reload
   ```

5. Open `http://127.0.0.1:8000/`. Create a farmer account with your name, email and a password (at least 10 characters, with a letter and a number), or sign in to an existing account. After signing in, open Farm Profile, save your farmer details and confirm them in the Saved Farm Details card. The profile can be edited later. Use `http://127.0.0.1:8000/health` for service status and `http://127.0.0.1:8000/docs` for API documentation.

If PowerShell blocks environment activation, run `.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt` and `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload`.

## Frontend dashboard and navigation

- The home screen is now a dedicated farm dashboard with a workspace overview, quick actions and current activity summaries.
- Desktop navigation uses a collapsible left sidebar grouped by Workspace, AI & Insights, Farm Management, Learning & Community and Administration.
- On smaller screens the sidebar becomes a slide-in navigation drawer with a backdrop.
- Selecting a navigation item opens its feature view while keeping all original forms, element IDs, API calls and feature scripts in place.
- Sidebar icons are inline SVGs, so the interface does not require an icon-font package or an external icon CDN. The menu button, navigation links, dashboard shortcuts and crop-guide shortcuts remain interactive.
- The redesigned interface is included alongside additive backend changes for account-scoped settings, livestock cases, private case-video attachments, expanded ExpertConnect categories, and improved Inventory and Community Pulse refresh behaviour. The moving slogan and original farming background image are retained.

## Included feature areas

### Existing ShambaSense AI features retained
- Farmer registration and sign-in using PBKDF2-HMAC-SHA256 password hashing and server-managed HttpOnly session cookies.
- Each local account receives a separate SQLite workspace database for its farm profile, cases, observations, assessments, actions, history, learning progress, referrals and inventory. The old shared demo database is preserved and is not automatically attached to a new account.
- Farm profile save confirmation, saved timestamp, a readable saved-details summary and an edit action. Farmer name, county and main crop are required; area and farm size are optional.
- English/Kiswahili Ask AI workflow and browser-based speech input.
- Manual crop-photo upload and analysis pipeline. The included ONNX labels cover pepper, potato and tomato only; they do not cover maize, beans or every crop. Real-field accuracy is not independently validated.
- Crop-guide prompt cards, question history and existing in-app reminders.
- Groq or Hugging Face/Gemma provider configuration.

### Case management and FarmAction
- Create crop cases with crop, observed problem, symptoms, date first noticed, crop stage and notes.
- Unique case reference, status, follow-up observations, AI assessments and chronological case activity timeline.
- Create farmer-approved tasks linked to a case and manage them in the existing reminder list.
- Case status values: `open`, `monitoring`, `resolved`, `referred`.
- Livestock Care supports cattle, goats, sheep, poultry, pigs, rabbits, camels, fish and other animals, with fields for animal group, age group, number affected and concern category. AI assessments are cautious animal-care information, not veterinary diagnosis or treatment.
- Attach MP4, MOV or WebM videos to a farm case (maximum 20 MB; the browser prevents clips over 60 seconds). A 15–30 second clip is usually sufficient. Videos are stored under the signed-in user local upload directory and are not analysed by AI. Avoid recording people, identity documents or precise home locations unless everyone recorded has agreed.

### Farmer workspace
- Dashboard counts for open cases, pending/completed actions, low-stock items and learning sessions.
- Upcoming FarmActions and recently updated cases.
- Summary refreshes on demand and when the page becomes visible again.

### Learning and practice
- Three short modules: field scouting, integrated pest management and farm records.
- English and Kiswahili lesson text and quizzes, scored practice sessions and local progress history.
- Practice scores are for learning feedback only. They are not an official qualification or proof of practical competence.

### Community Pulse
- Farmers can explicitly opt to share a crop or livestock report with county and issue category.
- No farmer name, phone number, case narrative or exact location is stored in the community report table. Livestock reports store species rather than animal case details.
- The submission is confirmed immediately and the total report count updates. Similar groups are hidden until at least three reports match the same crop or species, county and issue category.
- The count represents reports, not necessarily unique farmers. It is a farmer-reported trend, not a verified outbreak or disease alert. Hosting infrastructure may retain its own normal connection logs.

### ExpertConnect
- Choose a case and an expertise category suited to crop or livestock concerns (for example crop protection, soil nutrition, veterinary health, animal nutrition or poultry management).
- The app suggests a relevant professional role and lets the farmer prepare and copy a structured summary from a selected case. Urgency and additional context can be recorded.
- Track whether the farmer prepared it, shared it themselves, received a response or closed the record.
- The app does **not** send the summary to an officer, confirm an officer's identity or claim that an expert has reviewed it.

### Farm inventory
- Manually record seeds, fertiliser, animal feed, veterinary supplies, tools, irrigation supplies and other inputs.
- Create, refresh, edit and delete records; update names, categories, units, notes, quantities and reorder thresholds. Items at or below their user-entered threshold are marked low stock.
- Inventory is not connected to shops, supplier catalogues or stock systems.

### Revenue and cost estimator
- Calculate estimated gross revenue, surplus/loss and margin from farmer-entered quantities, prices and costs.
- It does not fetch live market prices and cannot guarantee a selling price or profit.

### Account settings and preferences
- Settings panels cover Account Settings, Farm Settings, Weather Settings, Notifications, AI Settings, Language & Region, Appearance, Privacy & Security and About.
- Preferences are saved per account. Light/dark/system theme and compact layout are applied by the frontend. Answer-detail preferences affect Ask AI and crop case assessments; the option to save AI history is respected by Ask AI and photo diagnosis.
- Weather location and rainfall units are stored as preferences only; live forecasts are not connected. Notification toggles control saved in-app preferences only; SMS, email and push delivery are not implemented. Language preference controls AI response/speech language; some interface labels remain English.

### Supervisor overview and demo mode
- Optional supervisor overview is protected by a server-side `SUPERVISOR_ACCESS_TOKEN` and an `X-Supervisor-Token` request header.
- It is a local prototype overview, **not a role-based supervisor account**. It reads only the signed-in account workspace, not platform-wide farmer records.
- Optional `DEMO_MODE=true` replaces Ask AI and case-assessment calls with clearly labelled scripted sample responses so a presentation can run without an AI provider. Demo responses must never be used for real farm decisions. Restart the backend after changing `.env`.
- System settings report provider readiness, classifier availability, knowledge count and demo-mode state. Spoken answer playback is user-initiated and depends on browser speech synthesis.

## Configuration

Copy `.env.example` to `.env` and configure only the values you need:

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER=groq` | Use Groq; add `GROQ_API_KEY`. |
| `LLM_PROVIDER=huggingface` | Use Hugging Face Inference Providers; add `HF_TOKEN` and optionally `HF_MODEL`. |
| `DEMO_MODE=false` | Set to `true` only for a clearly labelled scripted demonstration. |
| `SUPERVISOR_ACCESS_TOKEN` | Optional long random token for the local supervisor overview. Do not use a short or reused password. |
| `SHAMBASENSE_DB` | Optional base SQLite database path used for the local prototype and account-store naming. |
| `AUTH_REQUIRED=true` | Require a signed-in farmer for private workspace API routes. Enabled by default. |
| `SESSION_DAYS=14` | Session lifetime in days (clamped to 1–30). |
| `SESSION_COOKIE_SECURE=true` | Set in HTTPS hosting environments so the session cookie is sent only over HTTPS. Keep false only for local HTTP development. |
| `MEDIA_ROOT` | Optional path for local case-video files. Defaults to `backend/uploads`; use durable object storage rather than instance-local storage for cloud deployment. |
| `CLASSIFIER_MODEL_PATH`, `CLASSIFIER_LABELS_PATH` | Optional paths to an ONNX image classifier and its ordered labels. |
| `DIAGNOSE_USE_VISION=false` | If enabled with the Hugging Face provider, the downsized photo is also sent to the model provider. Default is classifier-only input. |

## Data, privacy and deployment limits

- Farmer accounts are stored in a separate accounts SQLite database. Each account's profile, questions, reminders, cases, case observations, assessments, case events, learning sessions, referral records and inventory are stored in a separate account-specific SQLite file. The community report database is shared and contains only opt-in crop or animal species, county, issue category, case type and timestamp fields. Case videos are stored under `MEDIA_ROOT/user_<id>/` and their metadata is stored in that account workspace.
- The previous single-user demo database is preserved but is not automatically assigned to the first new account. Existing demo history/profile data therefore does not appear in a newly registered account unless separately migrated by the project owner.
- **This is still a local, single-instance prototype, not production multi-tenant hosting.** Account isolation is implemented with separate local SQLite files, not PostgreSQL row-level ownership. Do not deploy publicly or enter sensitive farmer information until the app is migrated to a persistent managed database, security controls are reviewed, backups/recovery and account recovery are implemented, and HTTPS is enforced.
- `SUPERVISOR_ACCESS_TOKEN` is an additional gate for one local overview, not a replacement for account roles or proper access-control policy. Do not expose the endpoint publicly in this build.
- Reminders are stored in the app only; no SMS, email, push or WhatsApp notifications are sent.
- ExpertConnect prepares summaries only; it does not contact extension officers.
- Community groups count submitted reports rather than verified or deduplicated farmers. No outbreak verification is performed.
- Market calculation uses user-entered estimates; inventory is manually maintained; there is no live weather, market, supplier or logistics feed. Weather settings are preferences only. Notification settings do not deliver SMS, email or push messages.
- Video uploads are limited to MP4, MOV or WebM files up to 20 MB. The 60-second clip check is performed in the browser; videos are not analysed by AI. Local filesystem storage is not durable across cloud application replacements and must be migrated to managed object storage before cloud use.
- Authentication does not yet include email verification, password reset/recovery, multi-factor authentication or robust login rate limiting. A SameSite=Lax HttpOnly cookie is used; complete CSRF/origin validation and secure-cookie settings before public launch.
- Questions sent to `/ask` and case details sent for AI assessment are transmitted to the selected LLM provider. Avoid entering unnecessary personal details.
- Photos uploaded to `/diagnose` are processed in memory and not stored as image files. By default only classifier labels and scores are passed to the LLM. With `DIAGNOSE_USE_VISION=true` on Hugging Face, the downsized image is also sent to that provider.

## API routes

- `GET /`, `GET /health`, `GET /docs`
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `GET /profile`, `PUT /profile`, `GET /account`, `PATCH /account`, `POST /account/password`, `GET /settings`, `PUT /settings`, `POST /ask`, `POST /diagnose`
- `GET /history`, `DELETE /history`
- `GET /cases`, `POST /cases`, `GET /cases/{id}`
- `POST /cases/{id}/observations`, `PATCH /cases/{id}/status`, `POST /cases/{id}/assessments`, `POST /cases/{id}/actions`
- `GET /cases/{id}/media`, `POST /cases/{id}/media/videos`, `GET /case-media/{id}`, `DELETE /case-media/{id}`
- `GET /livestock/options`, `GET /expert/categories?case_type=crop|livestock`
- `POST /cases/{id}/referrals`, `GET /referrals`, `PATCH /referrals/{id}`
- `GET /reminders`, `POST /reminders`, `PATCH /reminders/{id}/complete`, `DELETE /reminders/{id}`
- `GET /dashboard/summary`
- `GET /learning/modules`, `POST /learning/sessions`, `GET /learning/progress`
- `POST /community/reports`, `GET /community/pulse`
- `GET /inventory`, `POST /inventory`, `PATCH /inventory/{id}`, `DELETE /inventory/{id}`
- `GET /supervisor/overview` (requires `X-Supervisor-Token`)
- `GET /knowledge/status`

## Tests

Run from the project root:

```powershell
python -m pytest backend\tests -q
```

The offline tests cover the original API plus case workflows, safe database migration, dashboard summary, learning quiz scoring, community aggregation thresholds, referral category selection, account-scoped inventory updates, livestock cases and cautious demo assessments, private video attachment storage, saved settings and AI-history preferences, demo mode and supervisor-token protection. Model-provider calls are mocked; tests do not prove AI factual accuracy or validate a real Groq/Hugging Face credential. The included ONNX-dependent test is skipped when ONNX Runtime is not installed.

## Known validation limits

- The browser automation environment used to validate this build blocked local Chromium navigation with `ERR_BLOCKED_BY_ADMINISTRATOR`; a complete interactive browser walkthrough on your own Windows laptop is still required.
- The prototype has not undergone an independent security review, an agricultural extension officer's content review, field validation, accessibility audit or load testing.
- The classifier is not a general crop disease detector; its current labels cover pepper, potato and tomato only, and its field accuracy has not been measured.

## Language model providers

The same prompts work with either provider; choose with `LLM_PROVIDER` in `.env`.

| Setting | Meaning |
|---|---|
| `LLM_PROVIDER=huggingface` | Hugging Face Inference Providers. Needs `HF_TOKEN`; model from `HF_MODEL` (default `google/gemma-4-E4B-it`); optional `HF_INFERENCE_PROVIDER` (default `auto`). |
| `DIAGNOSE_USE_VISION=true` | Option 2: Gemma also looks at the photo in `/diagnose`. Ignored on Groq. |
| `LLM_TEMPERATURE` | Default `0.3` (cautious, factual). Google's Gemma 4 card suggests 1.0; compare both on your Kiswahili questions. |

Setup for Gemma 4: create a token at huggingface.co > Settings > Tokens with permission to call Inference Providers, set `LLM_PROVIDER=huggingface` and `HF_TOKEN`, restart, then check `/health`.

How the two Gemma modes behave:
- **Text mode (default):** Gemma only sees the classifier labels, scores and reviewed knowledge excerpts, and writes the English/Kiswahili explanation.
- **Vision mode:** Gemma also receives the photo (placed before the text) and is told to treat the classifier as one signal, describe only symptoms it can see, and say so when it disagrees. If the provider rejects the image request, the app retries in text mode automatically (`vision_used` is `false` in the response).
- Leaked reasoning blocks from Gemma's thinking mode are stripped from answers.
- **Not verified:** not every Gemma 4 size is served by every Hugging Face provider, and this package has only been tested against fake clients. Check the model page's Inference Providers section, then try one real request before a demo.

## Photo diagnosis setup

1. Train/export a classifier (e.g. in Colab) to **ONNX** and save its class names as a JSON list in the same order as the model outputs, e.g. `["Tomato___Late_blight", "Tomato___healthy", ...]`.
   PyTorch export example:

   ```python
   import json, torch
   model.eval()
   torch.onnx.export(model, torch.randn(1, 3, 224, 224), "crop_disease.onnx",
                     input_names=["input"], output_names=["scores"], opset_version=17)
   json.dump(class_names, open("labels.json", "w"))
   ```

2. The package already contains `models/crop_disease.onnx`, its external data file, and `models/labels.json`. To try this included model, add these project-root-relative paths to `.env`:

   ```dotenv
   CLASSIFIER_MODEL_PATH=models/crop_disease.onnx
   CLASSIFIER_LABELS_PATH=models/labels.json
   ```

   If you replace the model, ensure its output class order matches the labels file. `CLASSIFIER_INPUT_SIZE` and `CLASSIFIER_NORMALIZE` (`imagenet` or `none`) must match the model's training preprocessing.
3. Install requirements, restart the backend, and check `/health` shows `"classifier_configured": true`. If it remains false, check the backend startup message and local ONNX Runtime installation.

Behaviour to know about:
- The current bundled labels cover pepper, potato, and tomato only. Do not rely on the classifier for maize, beans, or other unsupported crops; use a farmer's description and seek local extension guidance instead.
- Predictions below `CONFIDENCE_THRESHOLD` (default 0.6) are reported as **uncertain**: no knowledge lookup is done and the model is told not to name a likely disease.
- Reviewed excerpts are matched by exact class name. Give a document in `knowledge_base.json` a `labels` list (e.g. `"labels": ["Tomato___Late_blight"]`); otherwise a strict keyword fallback is used.
- If the language model is unavailable, the classifier results are still returned (with a warning).
- Uploaded photos are processed in memory and **not stored**; only the text summary and answer are saved to history. By default photos are not sent to the language model, only the classifier's labels and scores (see *Language model providers* for the optional vision mode).
- Lab-style datasets (e.g. PlantVillage) often score much lower on real farm photos. Evaluate on your own field photos before relying on the confidence numbers.

## Add reviewed knowledge excerpts

`backend/knowledge_base.json` is a small, local corpus for retrieval. Add only text you have reviewed and are permitted to reuse. Each item should have `title`, `url`, `text`, and optionally `date` and `labels` (classifier class names it covers). The app performs simple token-overlap retrieval, passes matching excerpts to the model, and returns source links for matches. The package now includes a small curated starter corpus with concise paraphrased excerpts prepared from public KALRO and FAO reference pages. These excerpts have not been reviewed by a Kenya-based agricultural specialist. Retrieval is still simple lexical token matching, not a live web search or a sophisticated vector database. Review the source links with an extension specialist and update the excerpt set as agricultural guidance changes. Do not add chemical application rates or crop-specific treatment instructions unless they are verified against applicable Kenyan guidance.

## Model evaluation

`backend/evaluate_models.py` records responses and latency for a small fixed set. Configure `EVAL_MODEL_A` and `EVAL_MODEL_B` after verifying model IDs and access in your provider accounts. Prefix each with its provider, e.g. `EVAL_MODEL_A=groq:openai/gpt-oss-20b` and `EVAL_MODEL_B=hf:google/gemma-4-E4B-it` (needs `GROQ_API_KEY` and `HF_TOKEN`). Results go to `docs/model-evaluation.csv`. It intentionally does not score or claim a winner. Review each output for factuality, practicality, uncertainty, and Kiswahili quality.

## Sources used for the starter knowledge corpus

The stored excerpts are paraphrases, not copied passages. The links below are the source references; the app does not fetch these pages live during a farmer's question.
- KALRO – Maize Good Agricultural Practices: https://keep.kalro.org/good-agricultural-practices/Maize
- FAO – How to practice Integrated Pest Management?: https://www.fao.org/agriculture/crops/thematic-sitemap/theme/spi/scpi-home/managing-ecosystems/integrated-pest-management/ipm-how/en/
- FAO – Integrated Pest Management: https://www.fao.org/pest-and-pesticide-management/ipm/integrated-pest-management/en/
- FAO – Farmer Field School approach: https://www.fao.org/agriculture/ippm/programme/ffs-approach/en/

Additional Kenyan reference organisations for future source review: KALRO https://www.kalro.org/ and the Kenya Ministry of Agriculture and Livestock Development https://www.kilimo.go.ke/.

## Latest UI bug-fix update

The latest package includes fixes for asynchronous form resets in Community Pulse, Inventory, FarmAction reminders and password-change forms. ExpertConnect now refreshes the signed-in farmer's crop and livestock case list at startup, when the section is opened, after a case is created, and from a manual Refresh case list button. See `BUGFIX_NOTES_EXPERTCONNECT_COMMUNITY_INVENTORY.md` for details and validation results.

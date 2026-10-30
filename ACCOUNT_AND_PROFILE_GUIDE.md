# MkulimaBridge account and farm profile guide

## Create your farmer account

1. Start FastAPI from the project root:
   `python -m uvicorn backend.main:app --reload`
2. Open `http://127.0.0.1:8000/`.
3. Select **Create account**.
4. Enter your full name, email address and a password of at least 10 characters containing at least one letter and one number.
5. Select **Create farmer account**. The application signs you in and opens your private workspace.

## Sign in again

Use the email address and password used during registration. The session cookie is HttpOnly and expires according to `SESSION_DAYS` (14 days by default). Select **Sign out** to revoke the current session and return to the sign-in screen.

## Save and view your farm details

1. Open **Farm Profile** from the left sidebar.
2. Enter your farmer name, county and main crop. These three fields are required. Sub-county/area and farm size are optional.
3. Select **Save Farm Profile**.
4. Look for the green success message and the **Your saved farm details** card. It displays the saved values and last-saved time.
5. Select **Edit details** to return to the form and update your information.

The saved profile is used as context for relevant ShambaSense AI questions. It belongs to the signed-in account's private local workspace.

## Important prototype limits

- This local version stores each account's private workspace in its own SQLite file. It is suitable for local development and controlled testing, not a multi-instance production deployment.
- The old shared demo database is preserved and is not automatically imported into a new account. This avoids silently assigning legacy data to the first person who registers.
- Email verification, password reset/recovery and multi-factor authentication are not yet available. Keep the service on a trusted development machine/network.
- Before inviting real farmers, migrate to managed PostgreSQL, enforce HTTPS, set `SESSION_COOKIE_SECURE=true`, complete CSRF/origin and rate-limit reviews, add recovery and account-management workflows, and test backups and restoration.

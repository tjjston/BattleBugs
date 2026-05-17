# iNaturalist Computer Vision setup

iNat's Computer Vision API is a real, professionally-trained
arthropod-recognition model. When configured, it becomes the **primary**
classification path for new bug submissions, ahead of the local LLM. The
LLM only runs when iNat is unconfigured, unreachable, or returns a
score below 0.55.

There are two ways to get a token. Try the **fast path** first.

---

## Fast path: personal JWT (60 seconds, no app registration)

iNaturalist issues every logged-in user a personal JWT that the same CV
endpoint accepts. The token expires after ~24 hours — fine for trying
this out and easy to refresh.

1. Sign in to https://www.inaturalist.org in your browser.
2. While signed in, open https://www.inaturalist.org/users/api_token
   in the same browser. You'll see a JSON blob like:
   ```json
   {"api_token": "eyJhbGciOi...long.jwt.value...sjvk"}
   ```
3. Copy the `api_token` value into your `.env`:
   ```dotenv
   INATURALIST_API_TOKEN=eyJhbGciOi...
   ```
4. `docker compose restart web`. You're done — the next submission gets
   scored by iNat CV.

The downside: this JWT lasts ~24 hours, so for production use, fall
back to the **stable path** below. For development, just paste a fresh
one whenever it expires.

---

## Stable path: OAuth application + bearer token (1-year token)

Use this when you want a token that doesn't expire daily.

### 1. Register an application on iNaturalist

1. Sign in at https://www.inaturalist.org with the account you want the
   API calls attributed to. A personal account is fine.
2. Visit https://www.inaturalist.org/oauth/applications and click
   **New Application**. (Note: iNat sometimes gates application creation
   behind a few days of account activity. If you can't see the form,
   use the **Fast path** above instead.)
3. Fill in:
   - **Name**: anything (e.g. `BattleBugs local`)
   - **Description**: e.g. `Personal arthropod classification helper`
   - **Redirect URI**: `urn:ietf:wg:oauth:2.0:oob` (we use the password
     grant, no redirect needed)
   - **Confidential**: leave checked
4. After creation you'll get a **Client ID** and a **Client Secret**.
   Treat the secret like a password.

### 2. Exchange your credentials for a bearer token

iNat allows the OAuth `password` grant for first-party apps. Run this in
your shell with placeholders replaced — your iNat password is sent only
to iNat over HTTPS:

```bash
curl -sX POST https://www.inaturalist.org/oauth/token \
     -d "grant_type=password" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET" \
     -d "username=YOUR_INAT_USERNAME" \
     -d "password=YOUR_INAT_PASSWORD"
```

You'll get back:

```json
{
  "access_token": "abcd1234...",
  "token_type": "Bearer",
  "scope": "write",
  "created_at": 1731640000
}
```

Copy the `access_token` value. Tokens are long-lived (~1 year) but are
revocable from your iNaturalist account settings.

### 3. Drop the token into `.env`

```dotenv
INATURALIST_API_TOKEN=abcd1234...
```

Restart the container (`docker compose restart web` or your usual flow)
and the next bug submission will be scored by iNat CV first.

---

## Verify it's wired up

Submit a bug photo. In `docker logs battlebug-web` you should see:

```
WARNING in bug_classifier: iNat CV top result: Photinus pyralis (Common Eastern Firefly) rank=species score=0.847
WARNING in bug_classifier: CLASSIFY [step 2.5/5] iNat CV WON — approved=True confidence=0.85 species='Photinus pyralis'
```

If you see `iNat CV returned 401 Unauthorized`, the token is invalid or
expired — regenerate it. If iNat is unreachable, the classifier falls
through to the local LLM path as before — nothing breaks, classification
quality just drops back to the previous level.

## Rate limits

iNat asks third-party apps for at most **100 requests/minute** and
**10,000/day**. BattleBugs only calls CV on submission and re-classify,
so this is comfortably under the limit for personal use.

## Token rotation

When the token expires (or you want to revoke and regenerate it), repeat
step 2 with the same client_id/secret and update the value in `.env`.
You don't need to re-register the application.

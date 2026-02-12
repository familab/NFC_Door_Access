# Single Sign-On (SSO) with Google OAuth

[← Back to README](../README.md)

This document explains how to set up Google OAuth 2.0 authentication for the Door Controller web interface.

## Overview

The Door Controller supports two authentication methods:
1. **Basic Auth** - Username/password (always enabled)
2. **Google OAuth** - Sign in with Google accounts (optional, requires setup)

When Google OAuth is enabled and configured, users will see a "Sign in with Google" button on the login page. You can control which Google accounts are allowed using email and domain whitelists.

## Prerequisites

- A Google account with access to [Google Cloud Console](https://console.cloud.google.com/)
- Admin access to the Door Controller configuration

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top and select **New Project**
3. Enter a project name (e.g., "Door Controller OAuth")
4. Click **Create**
5. Wait for the project to be created and select it from the project dropdown

## Step 2: Enable Google+ API (Optional)

While not strictly required for basic OAuth, enabling the Google+ API can provide better user profile information:

1. In the Google Cloud Console, go to **APIs & Services** > **Library**
2. Search for "Google+ API"
3. Click on it and press **Enable**

## Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services** > **OAuth consent screen**
2. Select **External** user type (or **Internal** if using Google Workspace and only want organization users)
3. Click **Create**
4. Fill in the required fields:
   - **App name**: Door Controller
   - **User support email**: Your email address
   - **Developer contact information**: Your email address
5. Click **Save and Continue**
6. On the **Scopes** page, click **Add or Remove Scopes**
7. Add the following scopes:
   - `openid`
   - `email`
   - `profile` (optional, for user's name and picture)
8. Click **Update** then **Save and Continue**
9. On the **Test users** page (if in testing mode):
   - Add email addresses of users who should have access during testing
   - Click **Save and Continue**
10. Review and click **Back to Dashboard**

## Step 4: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **OAuth client ID**
3. Select **Web application** as the application type
4. Enter a name (e.g., "Door Controller Web")
5. Under **Authorized redirect URIs**, add your callback URL:
   - For local development: `http://localhost:3667/login/google/callback`
   - For production: `https://your-domain.com/login/google/callback`
   - You can add multiple URIs for different environments
6. Click **Create**
7. A dialog will show your **Client ID** and **Client Secret**
8. **Copy both values** - you'll need them in the next step
9. Click **OK**

> **Note**: You can always retrieve these values later from the Credentials page.

## Step 5: Configure Door Controller

You have two options for providing OAuth credentials:

### Option A: Using creds.json (Recommended)

Add the following fields to your `creds.json` file:

```json
{
  "type": "service_account",
  ... (existing Google Sheets service account fields) ...

  "google_oauth_enabled": true,
  "google_oauth_client_id": "YOUR_CLIENT_ID_HERE.apps.googleusercontent.com",
  "google_oauth_client_secret": "YOUR_CLIENT_SECRET_HERE",
  "google_oauth_redirect_uri": "http://localhost:3667/login/google/callback",
  "google_oauth_scopes": ["openid", "email"],
  "google_oauth_allow_http": true,
  "auth_whitelist_emails": ["user1@gmail.com", "user2@example.com"],
  "auth_whitelist_domains": ["*.yourorg.com"]
}
```

> **Note**: Set `google_oauth_allow_http` to `true` for local development or when using HTTP tunnels (ngrok, etc). In production with HTTPS, set it to `false` or omit it.

### Option B: Using Environment Variables

Set the following environment variables:

```bash
# Enable Google OAuth
export DOOR_GOOGLE_OAUTH_ENABLED=true

# OAuth credentials
export DOOR_GOOGLE_OAUTH_CLIENT_ID="YOUR_CLIENT_ID_HERE.apps.googleusercontent.com"
export DOOR_GOOGLE_OAUTH_CLIENT_SECRET="YOUR_CLIENT_SECRET_HERE"
export DOOR_GOOGLE_OAUTH_REDIRECT_URI="http://localhost:3667/login/google/callback"

# Optional: Custom scopes (defaults to openid, email)
export DOOR_GOOGLE_OAUTH_SCOPES='["openid", "email", "profile"]'

# Allow OAuth over HTTP (for local dev or tunnels)
export DOOR_GOOGLE_OAUTH_ALLOW_HTTP=true

# Whitelists
export DOOR_AUTH_WHITELIST_EMAILS='["user1@gmail.com", "user2@example.com"]'
export DOOR_AUTH_WHITELIST_DOMAINS='["*.yourorg.com"]'
```

### Option C: Using config.json

Create or update `config.json` in the project root (use `config.example.json` as a template):

```json
{
  "GOOGLE_OAUTH_ENABLED": true,
  "GOOGLE_OAUTH_CLIENT_ID": "YOUR_CLIENT_ID_HERE.apps.googleusercontent.com",
  "GOOGLE_OAUTH_CLIENT_SECRET": "YOUR_CLIENT_SECRET_HERE",
  "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost:3667/login/google/callback",
  "GOOGLE_OAUTH_ALLOW_HTTP": true,
  "AUTH_WHITELIST_EMAILS": ["user1@gmail.com", "user2@example.com"],
  "AUTH_WHITELIST_DOMAINS": ["*.yourorg.com"]
}
```

Pass the config file when starting the server:
```python
from src_service.config import Config
config = Config("config.json")
```

## Step 6: Configure Whitelists

The whitelist determines which Google accounts can sign in. There are two types:

### Email Whitelist
Exact email addresses that are allowed:

```json
"auth_whitelist_emails": [
  "alice@gmail.com",
  "bob@example.com"
]
```

### Domain Whitelist
Domain patterns that are allowed. Supports wildcards:

```json
"auth_whitelist_domains": [
  "yourcompany.com",           // Exact domain match
  "*.yourcompany.com",         // Any subdomain
  "*.m.familab.org"           // Multi-level subdomain
]
```

**Important**:
- If both lists are **empty**, all Google accounts will be allowed (not recommended for production)
- Email matching is **case-insensitive**
- Wildcard `*.domain.com` matches all subdomains but not the root domain itself
- For the root domain to match, add it explicitly: `["domain.com", "*.domain.com"]`

## Step 7: Restart the Server

After configuration, restart the Door Controller web server:

```bash
python start.py
```

Or if using systemd:
```bash
sudo systemctl restart door-app
```

## Step 8: Test the Setup

1. Navigate to your Door Controller web interface (e.g., `http://localhost:3667`)
2. You should be redirected to `/login`
3. You should see both:
   - Username/Password form (Basic Auth)
   - "Sign in with Google" button
4. Click "Sign in with Google"
5. You'll be redirected to Google's sign-in page
6. After signing in with an authorized Google account, you'll be redirected back and authenticated

## Troubleshooting

### "Google OAuth is not configured" Error

**Cause**: `GOOGLE_OAUTH_ENABLED` is `true` but credentials are missing.

**Solution**: Verify that `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` are set correctly.

### "Google OAuth is not enabled" Error

**Cause**: `GOOGLE_OAUTH_ENABLED` is `false` or not set.

**Solution**: Set `GOOGLE_OAUTH_ENABLED=true` in your configuration.

### "Email not allowed" Error

**Cause**: The Google account email is not in the whitelist.

**Solution**:
- Add the email to `AUTH_WHITELIST_EMAILS`, OR
- Add the domain pattern to `AUTH_WHITELIST_DOMAINS`, OR
- Leave both empty to allow all emails (development only)

### Redirect URI Mismatch Error

**Cause**: The redirect URI in your config doesn't match what's registered in Google Cloud Console.

**Solution**:
1. Go to Google Cloud Console > Credentials
2. Edit your OAuth client
3. Ensure the redirect URI exactly matches `GOOGLE_OAUTH_REDIRECT_URI`
4. Common formats:
   - `http://localhost:3667/login/google/callback`
   - `https://door.example.com/login/google/callback`

### Google Sign-In Button Not Appearing

**Cause**: One of the following:
- `GOOGLE_OAUTH_ENABLED` is `false`
- `GOOGLE_OAUTH_CLIENT_ID` is empty
- `GOOGLE_OAUTH_CLIENT_SECRET` is empty

**Solution**: Check the browser console and server logs for configuration errors.

## Security Best Practices

1. **Always use HTTPS in production**
   ```json
   "HEALTH_SERVER_TLS": true,
   "GOOGLE_OAUTH_REDIRECT_URI": "https://door.yourdomain.com/login/google/callback"
   ```

2. **Keep credentials secret**
   - Never commit `creds.json` with real credentials to version control
   - Add `creds.json` to `.gitignore`
   - Use environment variables in production

3. **Restrict whitelists**
   - Don't leave whitelists empty in production
   - Use domain whitelists for organizations
   - Use email whitelists for specific individuals

4. **Set appropriate session timeout**
   ```json
   "AUTH_SESSION_TTL_SECONDS": 28800  // 8 hours
   ```

5. **Monitor OAuth consent screen status**
   - If set to "Testing", only test users can sign in
   - Move to "Production" when ready for wider access
   - Verify app regularly in Google Cloud Console

## Configuration Reference

| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `GOOGLE_OAUTH_ENABLED` | boolean | `false` | Enable/disable Google OAuth |
| `GOOGLE_OAUTH_CLIENT_ID` | string | `""` | OAuth client ID from Google Console |
| `GOOGLE_OAUTH_CLIENT_SECRET` | string | `""` | OAuth client secret from Google Console |
| `GOOGLE_OAUTH_REDIRECT_URI` | string | `""` | Callback URL (must match Google Console) |
| `GOOGLE_OAUTH_SCOPES` | array | `["openid", "email"]` | OAuth scopes to request |
| `AUTH_WHITELIST_EMAILS` | array | `[]` | List of allowed email addresses |
| `AUTH_WHITELIST_DOMAINS` | array | `[]` | List of allowed domain patterns |
| `AUTH_SESSION_TTL_SECONDS` | integer | `28800` | Session lifetime (8 hours) |
| `AUTH_SESSION_COOKIE_NAME` | string | `"door_session"` | Session cookie name |

## Support

For issues or questions:
- Check server logs for detailed error messages
- Review the configuration in `/admin` page (if accessible via Basic Auth)
- Verify Google Cloud Console settings match your configuration
- Ensure the OAuth consent screen is published or users are added as test users

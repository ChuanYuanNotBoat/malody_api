# Sensitive Configuration Setup

## 1) Crawler cookies (malody_rankings / stb / player_profile)

Use one of the following:

- `cookies.local.json` (recommended for local manual deployment)
- `MALODY_COOKIES_JSON`
- `MALODY_SESSIONID` and `MALODY_CSRFTOKEN`

Example `cookies.local.json`:

```json
{
  "sessionid": "your-session-id",
  "csrftoken": "your-csrf-token"
}
```

## 2) Mail credentials (crawler_controller)

You can keep `config.yaml` values empty and provide credentials by env vars:

- `MALODY_MAIL_SMTP_USERNAME`
- `MALODY_MAIL_SMTP_PASSWORD`
- `MALODY_MAIL_SMTP_FROM_ADDR`
- `MALODY_MAIL_IMAP_USERNAME`
- `MALODY_MAIL_IMAP_PASSWORD`
- `MALODY_ALLOWED_SENDERS` (comma-separated)
- `MALODY_REPORT_TO`

Example (PowerShell):

```powershell
$env:MALODY_MAIL_SMTP_USERNAME="your-email@qq.com"
$env:MALODY_MAIL_SMTP_PASSWORD="your-smtp-auth-code"
$env:MALODY_MAIL_SMTP_FROM_ADDR="your-email@qq.com"
$env:MALODY_MAIL_IMAP_USERNAME="your-email@qq.com"
$env:MALODY_MAIL_IMAP_PASSWORD="your-imap-auth-code"
$env:MALODY_ALLOWED_SENDERS="a@example.com,b@example.com"
$env:MALODY_REPORT_TO="notify@example.com"
```


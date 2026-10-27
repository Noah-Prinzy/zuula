# Supabase Email Templates for Zuula

These are custom HTML email templates for Supabase Auth. To use them, you must first enable **Custom SMTP** in Supabase (Authentication → Emails → SMTP Settings); Supabase only lets you edit templates after that. Paste each file into Authentication → Emails → Templates.

## Templates

| File                     | Subject Line                          |
|--------------------------|---------------------------------------|
| `confirm-signup.html`    | Confirm your Zuula account            |
| `reset-password.html`    | Reset your Zuula password             |

## Notes
- Supabase uses **Go template syntax**. The templates include:
  - `{{ .Token }}`: The 6-digit verification code.
  - `{{ .ConfirmationURL }}`: The fallback confirmation link.
- All CSS is inlined for email-client compatibility.
- No external images, fonts, or scripts are used.
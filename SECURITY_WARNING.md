# 🔴 CRITICAL SECURITY WARNING

## Your API Token May Be Compromised

Your `.env` file contains a Tradier API token that was previously committed to this codebase:

```
Token: B0qRj8pKKXGLcwGyyPI7ik5EM9rf
```

## Immediate Action Required

1. **Revoke the exposed token** at Tradier immediately:
   - Log in to your Tradier account
   - Go to API settings
   - Revoke/delete the token: `B0qRj8pKKXGLcwGyyPI7ik5EM9rf`

2. **Generate a new token**:
   - Create a new API token in your Tradier account
   - Update your `.env` file with the new token

3. **If this repo was pushed to GitHub or any remote:**
   - The token is permanently in git history
   - You MUST revoke it even if you delete the repo
   - Consider the token compromised

4. **Verify no unauthorized activity**:
   - Check your Tradier account for any unexpected trades or API calls
   - Review account access logs

## What Has Been Fixed

✅ Created `.gitignore` to prevent future `.env` commits
✅ Created `.env.example` template for secure setup
✅ Added security documentation to README
✅ Added version pinning to requirements.txt

## Going Forward

- Never commit `.env` files
- Always use `.env.example` templates
- Rotate API keys regularly
- Use environment-specific tokens (sandbox vs production)

## Questions?

If you need help securing your API credentials, consult Tradier's security documentation:
https://documentation.tradier.com/brokerage-api/getting-started

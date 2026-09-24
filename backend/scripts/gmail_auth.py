"""One-time Gmail OAuth consent.

Opens a browser, asks you to grant access to the support mailbox, then PRINTS
the refresh token for you to paste into .env. Nothing is written to disk --
credentials live in .env only.

Reads GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET from .env, so fill those in
first from your existing OAuth 2.0 Client ID.

Usage:
    python -m scripts.gmail_auth
"""
from google_auth_oauthlib.flow import InstalledAppFlow

from config import get_settings
from services.gmail_client import GMAIL_SCOPES


def main() -> int:
    settings = get_settings()

    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        print("✗ Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env first.")
        print("  Both come from your OAuth 2.0 Client ID in Google Cloud Console.")
        print("  The client must be of type 'Desktop app' for this flow to work.")
        return 1

    client_config = {
        "installed": {
            "client_id": settings.GMAIL_CLIENT_ID,
            "client_secret": settings.GMAIL_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, GMAIL_SCOPES)
    # access_type=offline + prompt=consent is what makes Google actually return
    # a refresh token; without prompt=consent a repeat authorization returns none.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print("✗ Google did not return a refresh token. Revoke the app's access at")
        print("  https://myaccount.google.com/permissions and run this again.")
        return 1

    print("\n✓ Add this line to backend/.env:\n")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}\n")
    print("  This is a live credential for the mailbox. .env is gitignored --")
    print("  keep it that way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

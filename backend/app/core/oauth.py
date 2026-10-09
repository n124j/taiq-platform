"""
Minimal OAuth2 authorization-code helpers for Google / GitHub sign-in.
No SDK dependency — just the raw authorize/token/userinfo calls via httpx.
"""
from urllib.parse import urlencode
import httpx
from app.core.config import settings

PROVIDERS = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
    },
}


def redirect_uri(provider: str) -> str:
    return f"{settings.BACKEND_URL}/api/v1/auth/{provider}/callback"


def build_authorize_url(provider: str, state: str) -> str:
    cfg = PROVIDERS[provider]
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri(provider),
        "scope": cfg["scope"],
        "state": state,
        "response_type": "code",
    }
    if provider == "google":
        params["prompt"] = "select_account"
    return f"{cfg['authorize_url']}?{urlencode(params)}"


async def exchange_code_for_token(provider: str, code: str) -> str:
    cfg = PROVIDERS[provider]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            cfg["token_url"],
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri(provider),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            raise ValueError(f"No access_token in {provider} token response")
        return token


async def fetch_profile(provider: str, access_token: str) -> dict:
    """Returns a normalized {email, name, avatar_url, provider_id} dict."""
    cfg = PROVIDERS[provider]
    async with httpx.AsyncClient(timeout=10) as client:
        if provider == "google":
            resp = await client.get(
                cfg["userinfo_url"],
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "email": data.get("email"),
                "name": data.get("name"),
                "avatar_url": data.get("picture"),
                "provider_id": data.get("sub"),
            }

        if provider == "github":
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            }
            resp = await client.get(cfg["userinfo_url"], headers=headers)
            resp.raise_for_status()
            data = resp.json()

            email = data.get("email")
            if not email:
                # Private email — GitHub only exposes it via /user/emails
                emails_resp = await client.get("https://api.github.com/user/emails", headers=headers)
                if emails_resp.status_code == 200:
                    emails = emails_resp.json()
                    primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                    verified = next((e for e in emails if e.get("verified")), None)
                    chosen = primary or verified
                    email = chosen["email"] if chosen else None

            return {
                "email": email,
                "name": data.get("name") or data.get("login"),
                "avatar_url": data.get("avatar_url"),
                "provider_id": str(data.get("id")),
            }

        raise ValueError(f"Unknown OAuth provider: {provider}")

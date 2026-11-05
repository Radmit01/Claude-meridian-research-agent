"""Call Atlas with credentials loaded only from a local .env file.

Prints progress at each step so a hang (e.g. waiting on browser auth) is
visible and localized instead of silently sitting for 5 minutes.

Two auth methods are supported, selected via the AUTH_METHOD env var:
  - "browser" (default): InteractiveBrowserCredential — opens your default
    browser and runs a local redirect listener on localhost. Can hang/timeout
    in locked-down corporate environments (no default browser, localhost
    loopback blocked by firewall/endpoint security, or the app registration's
    redirect URI doesn't match).
  - "device_code": DeviceCodeCredential — prints a short code + URL, you
    complete login in ANY browser on ANY device, and the library polls for
    completion. No local redirect listener needed, so it sidesteps the
    loopback/browser-launch problems above. Use this if "browser" times out.

Set AUTH_METHOD=device_code in .env (or as an environment variable) to try it.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

import anthropic
from azure.identity import DeviceCodeCredential, InteractiveBrowserCredential
from dotenv import load_dotenv

# How long to wait for interactive browser login before giving up (seconds).
# The azure-identity default is 300s; bumped here since corporate MFA/
# conditional-access prompts can take longer than that to click through.
BROWSER_AUTH_TIMEOUT_SECONDS = int(os.getenv("BROWSER_AUTH_TIMEOUT_SECONDS", "600"))


@dataclass(frozen=True)
class AtlasConfig:
    client_id: str
    tenant_id: str
    token_scope: str
    subscription_key: str
    base_url: str
    auth_type: str
    model: str
    auth_method: str
# changes

    @classmethod
    def from_env(cls, env_file: str = ".env") -> "AtlasConfig":
        values = load_dotenv(env_file, override=True)
        if not values:
            raise FileNotFoundError(f"Could not load {env_file}")
        print(f"[1/5] Loaded environment values from {env_file!r}.")
        config = {
            "client_id": os.getenv("CLIENT_ID"),
            "tenant_id": os.getenv("TENANT_ID"),
            "token_scope": os.getenv("TOKEN_SCOPE"),
            "subscription_key": os.getenv("MSF_SUBSCRIPTION_KEY"),
            "base_url": os.getenv("ANTHROPIC_BASE_URL"),
            "auth_type": os.getenv("AUTHENTICATION_TYPE_VALUE", "EntraID"),
            "model": os.getenv("ANTHROPIC_MODEL"),
            "auth_method": os.getenv("AUTH_METHOD", "browser").strip().lower(),
        }
        missing = [
            name.upper()
            for name, value in config.items()
            if not value and name != "auth_method"
        ]
        if missing:
            raise ValueError(f"Missing required environment values: {', '.join(missing)}")
        print(
            "[2/5] Config looks complete "
            f"(auth_method={config['auth_method']!r}, base_url={config['base_url']!r}, "
            f"model={config['model']!r})."
        )
        print(
            "[2b/5] Environment parameters loaded: "
            f"client_id={config['client_id'][:8]}..., "
            f"tenant_id={config['tenant_id'][:8]}..., "
            f"token_scope={config['token_scope']!r}, "
            f"subscription_key={config['subscription_key'][:8]}..., "
            f"auth_type={config['auth_type']!r}."
        )
        return cls(**config)  # type: ignore[arg-type]


def _get_bearer_token(config: AtlasConfig) -> str:
    if config.auth_method == "device_code":
        print(
            "[3/5] Using DeviceCodeCredential. A code and URL will be printed "
            "below — open the URL in any browser on any device, enter the "
            "code, and complete sign-in. This process will keep polling "
            "until you do."
        )
        credential = DeviceCodeCredential(
            client_id=config.client_id,
            tenant_id=config.tenant_id,
        )
    elif config.auth_method == "browser":
        print(
            f"[3/5] Using InteractiveBrowserCredential (timeout="
            f"{BROWSER_AUTH_TIMEOUT_SECONDS}s). Your default browser should "
            "open now — complete sign-in there. If no browser window opens "
            "within ~10 seconds, press Ctrl+C and switch to "
            "AUTH_METHOD=device_code in your .env."
        )
        credential = InteractiveBrowserCredential(
            client_id=config.client_id,
            tenant_id=config.tenant_id,
            timeout=BROWSER_AUTH_TIMEOUT_SECONDS,
        )
    else:
        raise ValueError(
            f"Unknown AUTH_METHOD {config.auth_method!r}; expected 'browser' or 'device_code'"
        )

    start = time.monotonic()
    token = credential.get_token(config.token_scope).token
    elapsed = time.monotonic() - start
    print(
        f"[4/5] Bearer token acquired in {elapsed:.1f}s "
        f"(length={len(token)}, prefix={token[:8]}...). Never logging the full token."
    )
    return token


def create_client(config: AtlasConfig) -> anthropic.Anthropic:
    bearer_token = _get_bearer_token(config)
    headers = {
        "MSF-Subscription-Key": config.subscription_key,
        "AtlasAuthType": config.auth_type,
    }
    print(
        f"[4b/5] Creating Anthropic client with headers: "
        f"MSF-Subscription-Key={config.subscription_key[:8]}..., "
        f"AtlasAuthType={config.auth_type!r}."
    )
    return anthropic.Anthropic(
        auth_token=bearer_token,
        base_url=config.base_url.rstrip("/"),
        default_headers=headers,
    )


def main() -> None:
    try:
        config = AtlasConfig.from_env(os.getenv("ATLAS_ENV_FILE", ".env"))
        client = create_client(config)
        print("[5/5] Sending test request to Atlas...")
        response = client.messages.create(
            model=config.model,
            max_tokens=100,
            messages=[{"role": "user", "content": "Reply exactly: Atlas connection works"}],
        )
        print("Atlas response:", response.content[0].text)
    except Exception as exc:
        print(f"FAILED at some step above: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

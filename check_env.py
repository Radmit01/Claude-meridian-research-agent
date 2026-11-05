from dotenv import load_dotenv
import os

load_dotenv()

required = [
    "CLIENT_ID",
    "TENANT_ID",
    "TOKEN_SCOPE",
    "MSF_SUBSCRIPTION_KEY",
    "ANTHROPIC_BASE_URL",
    "AUTHENTICATION_TYPE_VALUE",
    "ANTHROPIC_MODEL",
]

for key in required:
    val = os.getenv(key)
    status = "OK" if val and "YOUR_" not in val else "MISSING or still a placeholder"
    length = len(val) if val else 0
    print(f"{key}: {status} (length={length})")

sub_key = os.getenv("MSF_SUBSCRIPTION_KEY")
if sub_key:
    print("MSF_SUBSCRIPTION_KEY has leading/trailing whitespace:", sub_key != sub_key.strip())
    print("MSF_SUBSCRIPTION_KEY contains quote characters:", ('"' in sub_key) or ("'" in sub_key))
    print("MSF_SUBSCRIPTION_KEY is alphanumeric:", sub_key.isalnum())
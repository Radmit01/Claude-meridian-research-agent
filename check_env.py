from dotenv import load_dotenv
import os

load_dotenv()

required = [
    "CLIENT_ID",
    "TENANT_ID",
    "TOKEN_SCOPE",
    "SUBSCRIPTION_KEY",
    "ANTHROPIC_BASE_URL",
    "AUTHENTICATION_TYPE_VALUE",
    "ANTHROPIC_MODEL",
]

for key in required:
    val = os.getenv(key)
    status = "OK" if val and "YOUR_" not in val else "MISSING or still a placeholder"
    length = len(val) if val else 0
    print(f"{key}: {status} (length={length})")
    key = os.getenv("SUBSCRIPTION_KEY")
print("SUBSCRIPTION_KEY has leading/trailing whitespace:", key != key.strip())
print("SUBSCRIPTION_KEY contains quote characters:", ('"' in key) or ("'" in key))
print("SUBSCRIPTION_KEY is alphanumeric:", key.isalnum())
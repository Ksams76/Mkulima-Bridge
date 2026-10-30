
from pathlib import Path
import requests
from dotenv import load_dotenv
import os

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

key = os.getenv("GEMINI_API_KEY")

if not key:
    print("ERROR: GEMINI_API_KEY was not loaded.")
else:
    response = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
        timeout=20,
    )
    print("HTTP status:", response.status_code)

    if response.ok:
        print("SUCCESS: Google accepted the API key.")
    else:
        error = response.json().get("error", {})
        print("Error:", error.get("message"))
        for detail in error.get("details", []):
            print("Reason:", detail.get("reason"))

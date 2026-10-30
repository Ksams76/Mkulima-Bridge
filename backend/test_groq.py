
from pathlib import Path
import os

from dotenv import load_dotenv
from groq import Groq

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    print("ERROR: GROQ_API_KEY was not loaded.")
else:
    try:
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ShambaSense AI, an agricultural "
                        "information assistant for Kenyan farmers."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "My maize leaves are turning yellow. "
                        "Give me two possible causes and one "
                        "safe thing to check first."
                    ),
                },
            ],
            max_tokens=250,
        )

        print("SUCCESS: Groq returned an AI response.")
        print(response.choices[0].message.content)

    except Exception as error:
        print("Groq test failed:", type(error).__name__)
        print("Details:", str(error)[:500])

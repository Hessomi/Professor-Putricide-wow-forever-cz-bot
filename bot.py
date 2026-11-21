
import os
import json
import requests

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
SOURCE_CHANNEL = os.environ["SOURCE_CHANNEL_ID"]
TARGET_CHANNEL = os.environ["TARGET_CHANNEL_ID"]

DISCORD_API = "https://discord.com/api/v10"
GEMINI_MODEL = "gemini-2.5-flash-lite"
STATE_FILE = "state.json"

HEADERS = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "Content-Type": "application/json"
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_message_id": None}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def get_messages():
    response = requests.get(
        f"{DISCORD_API}/channels/{SOURCE_CHANNEL}/messages",
        headers=HEADERS,
        params={"limit": 100},
        timeout=30
    )
    response.raise_for_status()
    return response.json()


def extract_content(message):
    parts = []
    source_url = None

    if message.get("content"):
        parts.append(message["content"])

    for embed in message.get("embeds", []):
        if embed.get("title"):
            parts.append(embed["title"])

        if embed.get("description"):
            parts.append(embed["description"])

        for field in embed.get("fields", []):
            parts.append(
                f"{field.get('name', '')}: {field.get('value', '')}"
            )

        if embed.get("url"):
            source_url = embed["url"]

    if not source_url:
        source_url = (
            f"https://discord.com/channels/"
            f"{message['guild_id']}/"
            f"{SOURCE_CHANNEL}/{message['id']}"
        )

    return "\n\n".join(parts).strip(), source_url


def summarize(text):
    prompt = f"""
You are Professor Putricide from World of Warcraft.

Create a concise and accurate Czech summary of these
World of Warcraft: Forever patch notes.

Rules:
- Start with 🧪 GOOD NEWS, EVERYONE!
- Write entirely in Czech except official game terminology.
- Preserve English names of spells, items, talents and classes.
- Organize changes into clear categories.
- Highlight important gameplay changes.
- Never invent information.
- Include only changes explicitly stated in the source.
- Use clean Discord Markdown.
- Keep the summary concise.

ORIGINAL PATCH NOTES:

{text}
"""

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent",
        headers={
            "x-goog-api-key": GEMINI_KEY,
            "Content-Type": "application/json"
        },
        json={
            "contents": [
                {"parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1200
            }
        },
        timeout=90
    )

    response.raise_for_status()
    data = response.json()

    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def publish(text, source_url):
    content = (
        f"{text}\n\n"
        f"🔗 [Originální oznámení]({source_url})"
    )

    chunks = [
        content[i:i + 1900]
        for i in range(0, len(content), 1900)
    ]

    for chunk in chunks:
        response = requests.post(
            f"{DISCORD_API}/channels/{TARGET_CHANNEL}/messages",
            headers=HEADERS,
            json={
                "content": chunk,
                "allowed_mentions": {"parse": []}
            },
            timeout=30
        )
        response.raise_for_status()


def main():
    state = load_state()
    messages = get_messages()

    messages.sort(key=lambda m: int(m["id"]))

    if state["last_message_id"] is None:
        if messages:
            state["last_message_id"] = messages[-1]["id"]
            save_state(state)

        print("Initial checkpoint saved. Waiting for new updates.")
        return

    last_id = int(state["last_message_id"])

    new_messages = [
        message for message in messages
        if int(message["id"]) > last_id
    ]

    for message in new_messages:
        if not message.get("author", {}).get("bot"):
            state["last_message_id"] = message["id"]
            save_state(state)
            continue

        original, source_url = extract_content(message)

        if not original:
            state["last_message_id"] = message["id"]
            save_state(state)
            continue

        print(f"Processing message {message['id']}")

        summary = summarize(original)
        publish(summary, source_url)

        state["last_message_id"] = message["id"]
        save_state(state)

        print("Published successfully.")

    print("Check completed.")


if __name__ == "__main__":
    main()

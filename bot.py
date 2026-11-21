
import os
import json
import re
import time
from pathlib import Path

import requests

# =====================================================
# PROFESSOR PUTRICIDE - WORLD OF WARCRAFT: FOREVER
# =====================================================

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
SOURCE_CHANNEL = os.environ["SOURCE_CHANNEL_ID"]
TARGET_CHANNEL = os.environ["TARGET_CHANNEL_ID"]
GUILD_ID = os.environ["GUILD_ID"]

DISCORD_API = "https://discord.com/api/v10"
GEMINI_MODEL = "gemini-3.5-flash-lite"

STATE_FILE = Path("state.json")

DISCORD_HEADERS = {
    "Authorization": f"Bot {DISCORD_TOKEN}",
    "Content-Type": "application/json"
}


# =====================================================
# STATE - EVIDENCE ZPRACOVANYCH ZPRAV
# =====================================================

def load_state():
    if not STATE_FILE.exists():
        return {"last_message_id": None}

    with STATE_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state):
    temporary_file = STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    temporary_file.replace(STATE_FILE)


# =====================================================
# DISCORD API
# =====================================================

def discord_request(method, url, **kwargs):
    for attempt in range(5):
        response = requests.request(
            method,
            url,
            headers=DISCORD_HEADERS,
            timeout=30,
            **kwargs
        )

        if response.status_code == 429:
            delay = response.json().get("retry_after", 2)
            time.sleep(float(delay) + 0.5)
            continue

        if response.status_code >= 500:
            time.sleep(2 ** attempt)
            continue

        response.raise_for_status()
        return response

    raise RuntimeError("Discord API opakovaně selhalo.")


def get_latest_message():
    response = discord_request(
        "GET",
        f"{DISCORD_API}/channels/{SOURCE_CHANNEL}/messages",
        params={"limit": 1}
    )

    messages = response.json()
    return messages[0] if messages else None


def get_new_messages(last_message_id):
    collected = []
    before_id = None

    while True:
        params = {"limit": 100}

        if before_id:
            params["before"] = before_id

        response = discord_request(
            "GET",
            f"{DISCORD_API}/channels/{SOURCE_CHANNEL}/messages",
            params=params
        )

        batch = response.json()

        if not batch:
            break

        collected.extend(batch)
        oldest_id = batch[-1]["id"]

        if int(oldest_id) <= int(last_message_id):
            break

        if len(batch) < 100:
            break

        before_id = oldest_id

    new_messages = [
        message for message in collected
        if int(message["id"]) > int(last_message_id)
    ]

    return sorted(new_messages, key=lambda m: int(m["id"]))


# =====================================================
# EXTRACT PATCH NOTES
# =====================================================

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

        if embed.get("url"):
            source_url = embed["url"]

        for field in embed.get("fields", []):
            name = field.get("name", "")
            value = field.get("value", "")
            parts.append(f"{name}: {value}")

    original_text = "\n\n".join(parts).strip()

    if not source_url:
        urls = re.findall(r"https?://\S+", original_text)
        if urls:
            source_url = urls[0].rstrip(").,]")

    if not source_url:
        source_url = (
            f"https://discord.com/channels/"
            f"{GUILD_ID}/{SOURCE_CHANNEL}/{message['id']}"
        )

    return original_text, source_url


# =====================================================
# GEMINI AI - CZECH SUMMARY
# =====================================================

def summarize_with_ai(original_text):
    prompt = f"""
Jsi Professor Putricide ze světa World of Warcraft.

Tvým úkolem je vytvořit přesné a stručné české shrnutí
oficiálních patch notes pro World of Warcraft: Forever.

PRAVIDLA:

1. Začni přesně:
🧪 GOOD NEWS, EVERYONE!

2. Piš česky.
3. Názvy class, spellů, talentů, předmětů a herních
   mechanik ponechávej v originální angličtině.
4. Rozděl změny do přehledných kategorií.
5. Zvýrazni důležité změny balancování, opravy bugů,
   změny dungeonů, raidů a předmětů.
6. Nevymýšlej žádné informace.
7. Pokud je informace neúplná, nepokoušej se ji domýšlet.
8. Neopakuj zbytečně stejnou informaci.
9. Používej přehledný Discord Markdown.
10. Zachovej přesné číselné hodnoty změn.
11. Pokud oznámení neobsahuje důležité změny, stručně
    popiš jeho skutečný obsah.

Styl:
Professor Putricide, lehce šílený laboratorní humor,
ale především přehlednost a technická přesnost.

ORIGINÁLNÍ PATCH NOTES:

<patch_notes>
{original_text}
</patch_notes>
"""

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent",
        headers={
            "x-goog-api-key": GEMINI_KEY,
            "Content-Type": "application/json"
        },
        json={
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
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

    candidates = data.get("candidates", [])

    if not candidates:
        raise RuntimeError("Gemini nevrátil žádné shrnutí.")

    parts = candidates[0].get("content", {}).get("parts", [])

    result = "".join(
        part.get("text", "")
        for part in parts
    ).strip()

    if not result:
        raise RuntimeError("Gemini vrátil prázdnou odpověď.")

    return result


# =====================================================
# DISCORD PUBLICATION
# =====================================================

def split_message(text, limit=1900):
    lines = text.splitlines()
    chunks = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line

        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = line[:limit]
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def publish_message(summary, source_url):
    content = (
        f"{summary}\n\n"
        f"🔗 [Originální patch notes]({source_url})"
    )

    for chunk in split_message(content):
        discord_request(
            "POST",
            f"{DISCORD_API}/channels/{TARGET_CHANNEL}/messages",
            json={
                "content": chunk,
                "allowed_mentions": {"parse": []}
            }
        )


# =====================================================
# MAIN
# =====================================================

def main():
    state = load_state()

    print("🧪 Professor Putricide se probouzí...")

    # První spuštění pouze uloží výchozí bod.
    # Historické zprávy se nebudou publikovat.
    if state.get("last_message_id") is None:
        latest = get_latest_message()

        if latest:
            state["last_message_id"] = latest["id"]
            save_state(state)

        print("Výchozí bod uložen. Čekám na nové patch notes.")
        return

    new_messages = get_new_messages(state["last_message_id"])

    if not new_messages:
        print("Žádné nové patch notes.")
        return

    for message in new_messages:

        # Zpracováváme pouze zprávy od botů s embedy.
        if not message.get("author", {}).get("bot"):
            state["last_message_id"] = message["id"]
            save_state(state)
            continue

        if not message.get("embeds"):
            state["last_message_id"] = message["id"]
            save_state(state)
            continue

        original_text, source_url = extract_content(message)

        if not original_text:
            state["last_message_id"] = message["id"]
            save_state(state)
            continue

        print(f"Zpracovávám zprávu: {message['id']}")

        # Pokud AI nebo Discord selže, zpráva zůstane
        # nezpracovaná a při dalším spuštění se zkusí znovu.
        summary = summarize_with_ai(original_text)

        publish_message(summary, source_url)

        # Posuneme stav až po úspěšném zveřejnění.
        state["last_message_id"] = message["id"]
        save_state(state)

        print("GOOD NEWS, EVERYONE! Zpráva publikována.")

    print("Kontrola dokončena.")


if __name__ == "__main__":
    main()

import os
import re
import json
import random
import datetime
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# ---------------- Gemini Setup ----------------
global_gemini_model = None
try:
    # API key must be loaded from environment variables.
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set.")
    genai.configure(api_key=api_key)
    global_gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    print("Gemini model loaded successfully")
except Exception as e:
    print(f"Gemini initialization failed: {e}")
    global_gemini_model = None

# ---------------- Random Tag/Score ----------------
TAGS = ["Gong", "Bang", "Che", "Critical", "Magic"]
def choose_random_tag_and_score():
    """Returns a random tag and score."""
    return random.choice(TAGS), random.randint(1, 5)

# ---------------- Nickname Formatting Function ----------------
def shorten_nickname(nick: str, max_len: int = 8) -> str:
    """Cleans up and shortens AI-generated nicknames to 8 characters for the game."""
    if not nick:
        return "ㅇㅋㅋㅋ"
    s = re.sub(r"[\(\)\[\]\{\}<>/\\]", "", nick.strip())
    s = re.sub(r"ㅋ{3,}", "ㅋㅋ", s)
    s = re.sub(r"\?{3,}", "??", s)
    s = s.replace(" ", "")
    # Try to preserve meaning by removing longer tokens first
    for token in ["??", "ㅋㅋ", "ㅎ", "ㅋ"]:
        while len(s) > max_len and token in s:
            s = s.replace(token, "", 1)
    if len(s) > max_len:
        s = s[:max_len]
    # Add 'ㅋ' if the end is bland
    if s and s[-1] not in "ㅋ?ㅎ" and len(s) < max_len:
        s = (s + "ㅋ")[:max_len]
    return s or "ㅇㅋㅋㅋ"

# --- History Summarization Function for Token Saving ---
def summarize_history(history: dict) -> str:
    """
    Converts extensive play history (JSON) into a short summary string
    to save tokens when sending to the AI.
    """
    summaries = []
    try:
        if history.get("map_stats"):
            top_map = max(history["map_stats"], key=history["map_stats"].get)
            summaries.append(f"Main Map: {top_map}")
        if history.get("class_stats"):
            top_class = max(history["class_stats"], key=history["class_stats"].get)
            summaries.append(f"Main Class: {top_class}")
        if history.get("difficulty_stats"):
            top_diff = max(history["difficulty_stats"], key=history["difficulty_stats"].get)
            summaries.append(f"Preferred Difficulty: {top_diff}")
    except Exception:
        return "Error analyzing records"
    
    return ", ".join(summaries) if summaries else "No cumulative records"

# ---------------- Local Fallback Nicknames (if Gemini fails) ----------------
def local_fallback_response(game_result):
    """Generates a backup response for when the Gemini API call fails."""
    alias = random.choice(["하타치ㅋ", "상타치", "케찹맨..", "쫄?", "거지근성ㅋ"])
    hint = random.choice(["집게발", "쌩신인", "교수노예", "장난감집게","SM데뷔","JYP출신"])
    base = f"{hint}털림{alias}??"
    if str(game_result).upper() == "WIN":
        base = f"{hint}캐리{alias}ㅋㅋ"
    
    return {
        "nickname": shorten_nickname(base, 8),
        "updated_persona": "Persona update failed (backup response)"
    }

# ---------------- Main API Endpoint ----------------
@app.post("/api/ask")
def ask_gemini_nickname_with_persona():
    """Receives a single string from the client, parses it, and requests a nickname and persona from the AI."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json() or {}
    
    all_data_string = data.get("all_data")
    if not all_data_string:
        return jsonify({"error": "'all_data' is required."}), 400
        
    parts = all_data_string.split('/')
    if len(parts) < 16:
        return jsonify({"error": f"Invalid format. Expected 16 data parts, but received {len(parts)}."}), 400

    try:
        # 1. This round's play result (parsed from string)
        current_play = {
            "map": parts[0], "difficulty": parts[1], "class": parts[2],
            "result": (parts[3] or "").upper()
        }
        
        # 2. Cumulative play history (parsed from string)
        play_history = {
            "map_stats": {
                "강의실": int(parts[4]), "인형뽑기": int(parts[5]), "스트릿": int(parts[6]),
            },
            "class_stats": {
                "법사": int(parts[7]), "검사": int(parts[8]), "해적": int(parts[9]), "궁수": int(parts[10]),
            },
            "difficulty_stats": {
                "hard": int(parts[11]), "normal": int(parts[12]), "easy": int(parts[13]),
            },
        }

        # 3. Previous persona (parsed from string)
        previous_persona = parts[14] or "This user is playing for the first time."

        # 4. Dialogue with boss (parsed from string)
        boss_dialogue = parts[15] or ""
        
    except (IndexError, ValueError) as e:
        return jsonify({"error": f"Data parsing error: {e}"}), 400

    # Validate required values
    if current_play["result"] not in ("WIN", "LOSE"):
        return jsonify({"error": "game_result must be WIN or LOSE"}), 400

    tag, score = choose_random_tag_and_score()

    if global_gemini_model is None:
        fallback = local_fallback_response(current_play["result"])
        return jsonify({**fallback, "tag": tag, "score": score})

    history_summary = summarize_history(play_history)

    prompt = f"""
As a game AI, your role is to analyze a player's records to update their 'Jammin-che' (childish slang) style nickname and persona.

[Analysis Data]
1. Past Persona (Weight 40%): "{previous_persona}"
2. Latest Information (Weight 60%):
   - Just Played: {json.dumps(current_play, ensure_ascii=False)}
   - Cumulative Tendency: "{history_summary}"
   - Recent Dialogue with Boss: "{boss_dialogue}"

[Mission]
1. Generate Nickname:
   - Synthesize the data above, focusing more on 'Latest Information', to create one 'Jammin-che' style nickname.
   - [Rules] 6-8 characters without spaces, allow 'ㅋㅋ'/'??', no profanity, do not directly use map/class names, change tone based on result (WIN: boastful, LOSE: provocative).
2. Update Persona:
   - Merge the 'Latest Information' with the 'Past Persona' to summarize the player's characteristics in 1-2 sentences.
   - Reflect the tone or personality from the boss dialogue in the persona.

[Output Format]
You MUST respond ONLY in the following JSON format. Absolutely no explanations.
{{"nickname": "GeneratedNickname", "updated_persona": "UpdatedPersonaSentence"}}
"""

    generation_config = {"response_mime_type": "application/json", "temperature": 1.0}

    try:
        resp = global_gemini_model.generate_content(prompt, generation_config=generation_config)
        raw = resp.text or "{}"
        print(f"[{datetime.datetime.now()}] Gemini raw: {raw[:150]}...")
        
        obj = json.loads(raw)
        nickname = obj.get("nickname")
        updated_persona = obj.get("updated_persona")

        if not all([nickname, updated_persona]):
            raise ValueError("Model failed to generate nickname or updated_persona.")
        
        nickname = shorten_nickname(nickname, 8)

    except Exception as e:
        print(f"[{datetime.datetime.now()}] Gemini processing error -> local fallback: {e}")
        fallback = local_fallback_response(current_play["result"])
        nickname = fallback["nickname"]
        updated_persona = fallback["updated_persona"]

    return jsonify({
        "nickname": nickname, "tag": tag, "score": score,
        "updated_persona": updated_persona
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)



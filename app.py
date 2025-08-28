import os
import json
import random
import datetime
from flask import Flask, request, jsonify, Response
import google.generativeai as genai

app = Flask(__name__)

@app.get("/health")
def health():
    return Response(status=204)

# ---------------- Gemini 준비 ----------------
global_gemini_model = None
try:
    # 여러 키 이름 지원(있는 것 먼저 사용)
    api_key = (
        os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    genai.configure(api_key=api_key)
    global_gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    print("Gemini 모델 로드 완료")
except Exception as e:
    print(f"Gemini 초기화 실패: {e}")
    global_gemini_model = None

# ---------------- 랜덤 태그/점수 ----------------
TAGS = ["Gong", "Bang", "Che", "Critical", "Magic"]

def choose_random_tag_and_score():
    return random.choice(TAGS), random.randint(1, 5)

# ---------------- 로컬 백업 닉네임 ----------------
LAUGH = ["ㅋㅋ", "ㅎㅎ", "ㅋ", ""]
DIF_MAP = {
    "easy": ["뉴비", "초보감성", "귀염뽀짝"],
    "normal": ["국룰러", "중간맛", "평타장인"],
    "hard": ["근성러", "빡집중", "손괴물"],
    "hell": ["지옥행", "피눈물", "멘탈깎임"],
}

def local_fallback_nickname(map_name, difficulty, player_nickname, game_result):
    diff = (difficulty or "").lower()
    tags = DIF_MAP.get(diff, ["챌린저", "도전자", "돌격대"])
    # 패배면 '쫄보' 프리픽스, 승리면 난이도 테마 중 하나
    prefix = "쫄보" if (str(game_result).upper() == "LOSE") else random.choice(tags)
    laugh = random.choice(LAUGH)
    core = player_nickname or "플레이어"
    tail = f"{map_name}러" if map_name else "겜러"
    # (요청은 단순 치환이므로 기존 스타일 유지)
    nick = f"{prefix} {core}{laugh} ({tail})"
    return nick.strip()

# ---------------- 메인 엔드포인트 ----------------
@app.post("/api/ask")
def ask_gemini_nickname():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json() or {}
    map_name = data.get("map_name")
    difficulty = data.get("difficulty")
    player_nickname = data.get("player_nickname")
    game_result = (data.get("game_result") or "").upper()  # WIN / LOSE 기대

    # 필수 필드 검증
    if not (isinstance(player_nickname, str) and player_nickname.strip()):
        return jsonify({"error": "Missing or invalid 'player_nickname'"}), 400
    if game_result not in ("WIN", "LOSE"):
        return jsonify({"error": "game_result must be WIN or LOSE"}), 400

    # 태그/점수는 서버에서 완전 랜덤
    tag, score = choose_random_tag_and_score()

    # 모델이 없으면 바로 로컬 백업
    if global_gemini_model is None:
        nickname = local_fallback_nickname(map_name, difficulty, player_nickname, game_result)
        return jsonify({
            "input": {
                "map_name": map_name, "difficulty": difficulty,
                "player_nickname": player_nickname, "game_result": game_result
            },
            "nickname": nickname, "tag": tag, "score": score
        })

    # --------- 프롬프트: 잼민체(짧고 직격), 결과 반영(WIN/LOSE) ---------
    prompt = (
        "너는 한국 초딩 잼민이 페르소나다. 짧고 얄밉게 도발한다. "
        "인터넷 밈체(ㅋㅋ, ㅎ, ??, ㄷㄷ)와 철자깨기(넘, 새키, 못갔쥬, 쥬??)를 적극 사용하라. "
        "욕설은 금지하지만 짭욕은 허용된다.\n\n"
        "규칙:\n"
        "1) 출력은 JSON 하나, 필드명은 nickname만.\n"
        "2) 플레이어 닉네임/맵 이름은 원문 그대로 쓰지 말고, 음식·과일·밈·별명으로 비틀어 자연스럽게 녹여 쓸 것.\n"
        "3) 맵/난이도는 그대로 말하지 말고 잼민이식 상황극으로 변형해 암시만 줄 것. "
        "   예: hard→하드못갔쥬, 인형뽑기맵→집게발.\n"
        "4) 게임 결과가 'win'이면 자뻑/허세, 'lose'면 찔리게 도발.\n"
        "5) 별명은 1문장, 8자이내. 짧고 직격타, 1~2번 도발만. 완벽한 문장은 금지, 오탈자/붙여쓰기/쥬?? 활용.\n\n"
        "[입력]\n"
        f"- 맵 이름: {map_name}\n"
        f"- 난이도: {difficulty}\n"
        f"- 플레이어 닉네임: {player_nickname}\n"
        f"- 결과: {game_result}\n"
    )

    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {
                "nickname": {"type": "string"}
            },
            "required": ["nickname"]
        }
    }

    try:
        resp = global_gemini_model.generate_content(prompt, generation_config=generation_config)
        raw = resp.text or ""
        print(f"[{datetime.datetime.now()}] Gemini raw: {raw[:120]}...")
        obj = json.loads(raw)
        nickname = obj.get("nickname")
        if not nickname or not isinstance(nickname, str):
            raise ValueError("Invalid nickname from model")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] Gemini 처리 오류 → 로컬 백업: {e}")
        nickname = local_fallback_nickname(map_name, difficulty, player_nickname, game_result)

    return jsonify({
        "input": {
            "map_name": map_name, "difficulty": difficulty,
            "player_nickname": player_nickname, "game_result": game_result
        },
        "nickname": nickname,
        "tag": tag,         # 서버가 난수로 생성
        "score": score      # 서버가 난수로 생성
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)

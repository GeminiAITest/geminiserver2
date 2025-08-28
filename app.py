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
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
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
def local_fallback_nickname(map_name, difficulty, player_nickname, boss_reply):
    diff = (difficulty or "").lower()
    tags = DIF_MAP.get(diff, ["챌린저", "도전자", "돌격대"])
    prefix = "쫄보" if any(k in (boss_reply or "") for k in ["살려", "제발", "도와", "용서"]) else random.choice(tags)
    laugh = random.choice(LAUGH)
    # 최대한 한국 감성 + 입력 반영
    core = player_nickname or "플레이어"
    tail = f"{map_name}러" if map_name else "겜러"
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
    boss_reply = data.get("boss_reply")

    if not all(isinstance(x, str) and x.strip() for x in [player_nickname or ""]):
        return jsonify({"error": "Missing or invalid 'player_nickname'"}), 400

    # 태그/점수는 서버에서 완전 랜덤
    tag, score = choose_random_tag_and_score()

    # 모델이 없으면 바로 로컬 백업
    if global_gemini_model is None:
        nickname = local_fallback_nickname(map_name, difficulty, player_nickname, boss_reply)
        return jsonify({
            "input": {
                "map_name": map_name, "difficulty": difficulty,
                "player_nickname": player_nickname, "boss_reply": boss_reply
            },
            "nickname": nickname, "tag": tag, "score": score
        })

    # --------- 프롬프트: 한국 밈/슬랭 감성(느슨), 입력 반영 ---------
    prompt = (
        "아래 플레이 정보와 대사를 보고, 한국 인터넷 문화/게이머 밈 감성으로 **짧고 임팩트 있는 별칭**을 1개 만들어줘.\n"
        "사람들이 '와 이렇게까지 한국인을 잘 안다고?' 싶을 정도로 자연스러운 톤이면 좋고, 과도한 비속어나 혐오는 금지.\n"
        "규칙:\n"
        "1) 별칭은 한국어 한 줄 문자열. 6~18자 내외 권장, 띄어쓰기 1~2회 허용.\n"
        "2) (선택) 'ㅋㅋ','ㅎㅎ' 등 가벼운 웃음표시 0~1회 허용.\n"
        "3) 반드시 입력 정보 일부를 반영(예: 난이도 뉘앙스, 맵명, 플레이어 닉네임, 대사 분위기).\n"
        "   - 예시: 맵='인형뽑기맵', 난이도='hard', 닉='토마토', 대사='제발 살려주세요' → '쫄보 토마토ㅋㅋ'\n"
        "4) 출력은 JSON만. 다른 말/주석/코드블록 금지. 필드명은 nickname 하나만.\n\n"
        f"[입력]\n"
        f"- 맵 이름: {map_name}\n"
        f"- 맵 난이도: {difficulty}\n"
        f"- 플레이어 닉네임: {player_nickname}\n"
        f"- 보스에게 답변한 문장: {boss_reply}\n"
    )

    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "OBJECT",
            "properties": {
                "nickname": {"type": "STRING"}
            },
            "required": ["nickname"],
            "additionalProperties": False
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
        nickname = local_fallback_nickname(map_name, difficulty, player_nickname, boss_reply)

    return jsonify({
        "input": {
            "map_name": map_name, "difficulty": difficulty,
            "player_nickname": player_nickname, "boss_reply": boss_reply
        },
        "nickname": nickname,
        "tag": tag,         # 서버가 난수로 생성
        "score": score      # 서버가 난수로 생성
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)

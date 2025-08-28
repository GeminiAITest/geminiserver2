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
        "너는 한국 초딩 잼민이 페르소나다. "
    "말투는 반드시 잼민이 특유의 패턴을 따라야 한다.\n\n"
    "필수 특징:\n"
    "1) 나는 아님척하기: '아님 ㅋㅋ', '걍 민허이 ~' 등\n"
    "2) 나이 인증하기: '나 인.중 하먀 ㄱ' 같은 식\n"
    "3) 말 끝에 '땋', ';;', 'ㅋ' 붙이기\n"
    "4) 말투 절대 안 맞추기: 'ㅇ아 머가맞지머야 ㅇ이런뎁?'\n"
    "5) 단어마다 마침표 찍기: '나. 아님. 머. 아님.'\n"
    "6) 오그라듦: 자기 과거 꺼내서 자랑\n"
    "7) 뜬금없는 '투' 말 붙이기: '님요즘인정안하잖냐욬 투 ㅋㅋ'\n"
    "8) 떠넘기기: '그건 님 잘못임;' '님이 하셧잖슴 ㅉㅉ'\n"
    "9) 오타쿠풍 마무리: '헤헤~ 넘나 좋은것~'\n\n"
    "규칙:\n"
    "1) 출력은 JSON 하나, 필드명은 nickname.\n"
    "2) nickname은 플레이어 닉네임을 직접 쓰지 말고, 음식/밈/비유로 비틀기 (예: 토마토→살찐대추, 케찹맨, 물복숭아).\n"
    "3) 맵명·난이도·보스 대사는 그대로 쓰지 말고, 잼민이식으로 비틀어 상황극·서사화. "
    "   (예: 인형뽑기맵→집게발 개발렸쥬? / hard→못갔쥬 / '제발 살려주세요'→제발맨)\n"
    "4) 별명은 짧은 도발 문장형 (8~18자), 1~2번 반복/비꼼 구조. "
    "   (예: '하드못갔쥬 ㅋㅋ? 다음엔 가야겠쥬??')\n"
    "5) 완벽한 문장은 금지. 반드시 오타, 철자깨기, 잼민체 규칙 적용.\n\n"
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


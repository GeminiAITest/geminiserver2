import os
import re
import json
import random
import datetime
from flask import Flask, request, jsonify, Response
import google.generativeai as genai

app = Flask(__name__)
@app.get("/")
def root():
    return "Server is running!", 200
    
@app.get("/health")
def health():
    return Response(status=204)

# ---------------- Gemini 준비 ----------------
global_gemini_model = None
try:
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

# ---------------- 잼민체 닉네임 길이 강제(≤8자) ----------------
def _compress(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    # 괄호류/슬래시 제거
    s = re.sub(r"[\(\)\[\]\{\}<>/\\]", "", s)
    # 과도한 반복 축약
    s = re.sub(r"ㅋ{3,}", "ㅋㅋ", s)
    s = re.sub(r"ㅎ{3,}", "ㅎㅎ", s)
    s = re.sub(r"\?{3,}", "??", s)
    # 공백 한 번 정리
    s = re.sub(r"\s+", " ", s)
    return s

def shorten_nickname(nick: str, max_len: int = 8) -> str:
    s = _compress(nick)
    # 공백 제거 우선 (공백 없이 6~8자 목표)
    s = s.replace(" ", "")
    # 너무 길면 약한 후순위 토큰부터 제거
    for token in ["??", "ㅋㅋ", "ㅎ", "ㅋ"]:
        while len(s) > max_len and token in s:
            s = s.replace(token, "", 1)
    # 그래도 길면 하드 컷
    if len(s) > max_len:
        s = s[:max_len]
    # 끝이 밋밋하면 가벼운 타격감 추가(여유 있을 때만)
    if s and s[-1] not in "ㅋ?ㅎ" and len(s) < max_len:
        s = (s + "ㅋ")[:max_len]
    # 완전 빈 문자열 방지
    return s or "ㅇㅋㅋㅋ"

# ---------------- 로컬 백업 닉네임 (짧게 생성) ----------------
ALIASES = ["하타치ㅋ", "상타치", "케찹맨..", "쫄?", "거지근성ㅋ", "불쌍한넘"]
MAP_HINTS = ["집게발", "기계손", "보스발톱", "장난감집게", "클로"]

def map_hint_from(name: str | None) -> str:
    n = (name or "")
    if "인형" in n or "뽑기" in n:
        return random.choice(["집게발", "기계손", "장난감집게"])
    if "강의" in n:
        return random.choice(["교수의노예", "재수강생", "학점따개"])
    if "스트릿" in n or "스트" in n:
        return random.choice(["이빨밀당녀(놈)", "스윙즈", "패션X자"])
    return random.choice(MAP_HINTS)

def local_fallback_nickname(map_name, difficulty, player_nickname, game_result):
    alias = random.choice(ALIASES)
    hint = map_hint_from(map_name)
    if str(game_result).upper() == "WIN":
        base = f"{hint}캐리{alias}ㅋㅋ"
    else:
        base = f"{hint}털림{alias}??"
    return shorten_nickname(base, 8)

# ---------------- 메인 엔드포인트 ----------------
@app.post("/api/ask")
def ask_gemini_nickname():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json() or {}
    map_name = data.get("map_name")
    difficulty = data.get("difficulty")
    player_nickname = data.get("player_nickname")
    game_result = (data.get("game_result") or "").upper()  # WIN / LOSE

    # 필수 검증
    if not (isinstance(player_nickname, str) and player_nickname.strip()):
        return jsonify({"error": "Missing or invalid 'player_nickname'"}), 400
    if game_result not in ("WIN", "LOSE"):
        return jsonify({"error": "game_result must be WIN or LOSE"}), 400

    # 태그/점수는 서버에서 랜덤
    tag, score = choose_random_tag_and_score()

    # 모델이 없으면 로컬 백업
    if global_gemini_model is None:
        nickname = local_fallback_nickname(map_name, difficulty, player_nickname, game_result)
        return jsonify({
            "input": {
                "map_name": map_name, "difficulty": difficulty,
                "player_nickname": player_nickname, "game_result": game_result
            },
            "nickname": nickname, "tag": tag, "score": score
        })

    # --------- 프롬프트: 잼민체, 공백 없이 6~8자(최대 8자) ---------
    # 닉/맵 원문 직표기 금지(암시만), 괄호 금지. 결과에 따라 톤 분기.
    prompt = (
        "잼민체 별명 1문장 생성. 공백 없이 6~8자(최대 8자). "
        "짧고 직격. ㅋㅋ/??/ㅎ·철자깨기(못갔쥬/넘/새키 등) 허용, 욕설 금지. "
        "닉·맵 원문 직표기 금지(음식/밈으로 비틀어 암시), 괄호 금지. "
        "hard→하드못갔쥬, 인형뽑기→집게발 같은 식. "
        f"결과가 '{'win' if game_result=='WIN' else 'lose'}'이면: win=자뻑/허세, lose=찔리게 도발.\n\n"
        f"- 맵: {map_name}\n"
        f"- 난이도: {difficulty}\n"
        f"- 닉네임: {player_nickname}\n"
        f"- 결과: {game_result}\n"
        'JSON으로 {"nickname":"..."}만 출력.'
    )

    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {"nickname": {"type": "string"}},
            "required": ["nickname"]
        },
        # 살짝 창의성 유지
        "temperature": 1.0
    }

    try:
        resp = global_gemini_model.generate_content(prompt, generation_config=generation_config)
        raw = resp.text or ""
        print(f"[{datetime.datetime.now()}] Gemini raw: {raw[:120]}...")
        obj = json.loads(raw)
        nickname = obj.get("nickname")
        if not nickname or not isinstance(nickname, str):
            raise ValueError("Invalid nickname from model")
        # ★ 길이 강제 폴리싱
        nickname = shorten_nickname(nickname, 8)

    except Exception as e:
        print(f"[{datetime.datetime.now()}] Gemini 처리 오류 → 로컬 백업: {e}")
        nickname = local_fallback_nickname(map_name, difficulty, player_nickname, game_result)

    return jsonify({
        "input": {
            "map_name": map_name, "difficulty": difficulty,
            "player_nickname": player_nickname, "game_result": game_result
        },
        "nickname": nickname,
        "tag": tag,
        "score": score
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)



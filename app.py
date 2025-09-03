import os
import re
import json
import random
import datetime
from flask import Flask, request, jsonify, Response
import google.generativeai as genai

app = Flask(__name__)

# ---------------- Gemini 준비 ----------------
global_gemini_model = None
try:
    # API 키는 반드시 환경 변수에서 로드해야 합니다.
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
    genai.configure(api_key=api_key)
    global_gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    print("Gemini 모델 로드 완료")
except Exception as e:
    print(f"Gemini 초기화 실패: {e}")
    global_gemini_model = None

# ---------------- 랜덤 태그/점수 ----------------
TAGS = ["Gong", "Bang", "Che", "Critical", "Magic"]
def choose_random_tag_and_score():
    """랜덤 태그와 점수를 반환합니다."""
    return random.choice(TAGS), random.randint(1, 5)

# ---------------- 닉네임 길이 및 형식 정리 함수 ----------------
def shorten_nickname(nick: str, max_len: int = 8) -> str:
    """AI가 생성한 닉네임을 게임에 맞게 8자 이하로 정리합니다."""
    if not nick:
        return "ㅇㅋㅋㅋ"
    s = re.sub(r"[\(\)\[\]\{\}<>/\\]", "", nick.strip())
    s = re.sub(r"ㅋ{3,}", "ㅋㅋ", s)
    s = re.sub(r"\?{3,}", "??", s)
    s = s.replace(" ", "")
    # 긴 토큰부터 제거하여 의미 유지 시도
    for token in ["??", "ㅋㅋ", "ㅎ", "ㅋ"]:
        while len(s) > max_len and token in s:
            s = s.replace(token, "", 1)
    if len(s) > max_len:
        s = s[:max_len]
    # 끝이 심심하면 'ㅋ' 추가
    if s and s[-1] not in "ㅋ?ㅎ" and len(s) < max_len:
        s = (s + "ㅋ")[:max_len]
    return s or "ㅇㅋㅋㅋ"

# --- ★★★ 토큰 절약을 위한 플레이 기록 요약 함수 ★★★ ---
def summarize_history(history: dict) -> str:
    """
    클라이언트로부터 받은 방대한 플레이 기록(JSON)을
    AI에게 전달하기 좋은 짧은 요약 문자열로 변환하여 토큰을 절약합니다.
    """
    summaries = []
    # 가장 많이 플레이한 맵/직업/난이도 찾기
    try:
        if history.get("map_stats"):
            top_map = max(history["map_stats"], key=history["map_stats"].get)
            summaries.append(f"주력 맵: {top_map}")
        if history.get("class_stats"):
            top_class = max(history["class_stats"], key=history["class_stats"].get)
            summaries.append(f"주력 직업: {top_class}")
        if history.get("difficulty_stats"):
            top_diff = max(history["difficulty_stats"], key=history["difficulty_stats"].get)
            summaries.append(f"선호 난이도: {top_diff}")
    except Exception:
        # 데이터가 비어있거나 형식이 잘못된 경우에도 오류 없이 처리
        return "기록 분석 중 오류"
    
    return ", ".join(summaries) if summaries else "누적 기록 없음"

# ---------------- 로컬 백업 닉네임 (Gemini 실패 시) ----------------
def local_fallback_response(game_result):
    """Gemini API 호출 실패 시 사용할 백업 응답을 생성합니다."""
    alias = random.choice(["하타치ㅋ", "상타치", "케찹맨..", "쫄?", "거지근성ㅋ"])
    hint = random.choice(["집게발", "기계손", "보스발톱", "장난감집게"])
    base = f"{hint}털림{alias}??"
    if str(game_result).upper() == "WIN":
        base = f"{hint}캐리{alias}ㅋㅋ"
    
    return {
        "nickname": shorten_nickname(base, 8),
        "updated_persona": "페르소나 업데이트 실패 (백업 응답)"
    }

# ---------------- 메인 API 엔드포인트 ----------------
@app.post("/api/ask")
def ask_gemini_nickname_with_persona():
    """클라이언트로부터 유저 데이터를 받아 AI에게 닉네임과 페르소나 생성을 요청합니다."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json() or {}
    
    # 1. 이번 판 플레이 결과
    current_play = {
        "map": data.get("map_name"),
        "difficulty": data.get("difficulty"),
        "class": data.get("class"),
        "result": (data.get("game_result") or "").upper()
    }
    
    # 2. 누적된 플레이 기록
    play_history = {
        "map_stats": data.get("map_stats", {}),
        "class_stats": data.get("class_stats", {}),
        "difficulty_stats": data.get("difficulty_stats", {}),
    }

    # 3. 지난번에 AI가 만들어준 페르소나
    previous_persona = data.get("previous_persona", "이 유저는 첫 접속입니다.")

    # 4. 게임 중 보스와의 대화 내용
    boss_dialogue = data.get("boss_dialogue", "")

    # 필수 값 검증
    if current_play["result"] not in ("WIN", "LOSE"):
        return jsonify({"error": "game_result must be WIN or LOSE"}), 400

    tag, score = choose_random_tag_and_score()

    # Gemini 모델 로드 실패 시 백업 로직으로 즉시 응답
    if global_gemini_model is None:
        fallback = local_fallback_response(current_play["result"])
        return jsonify({**fallback, "tag": tag, "score": score})

    # 프롬프트에 보낼 데이터 요약 (토큰 절약)
    history_summary = summarize_history(play_history)

    # Gemini에게 전달할 프롬프트
    prompt = f"""
당신은 플레이어의 기록을 분석해 '잼민체' 별명과 페르소나를 갱신하는 게임 AI입니다.

[분석 데이터]
1. 과거 페르소나 (가중치 40%): "{previous_persona}"
2. 최신 정보 (가중치 60%):
   - 방금 플레이: {json.dumps(current_play, ensure_ascii=False)}
   - 누적 성향: "{history_summary}"
   - 최근 보스와의 대화: "{boss_dialogue}"

[임무]
1. 닉네임 생성:
   - 위 데이터를 종합하되, '최신 정보'에 비중을 두어 '잼민체' 별명 1개 생성
   - [규칙] 공백 없이 6~8자, ㅋㅋ/?? 등 허용, 욕설 금지, 맵/직업명 직접 사용 금지, 결과(WIN/LOSE)에 따라 톤 변경 (WIN:허세, LOSE:도발)
2. 페르소나 갱신:
   - 과거 페르소나에 최신 정보를 융합하여, 플레이어의 특징을 1~2문장으로 요약.
   - 보스와의 대화에서 드러난 말투나 성격을 페르소나에 반영.

[출력 형식]
반드시 아래 JSON 형식으로만 응답. 설명 절대 금지.
{{"nickname": "생성된닉네임", "updated_persona": "갱신된페르소나문장"}}
"""

    generation_config = {
        "response_mime_type": "application/json",
        "temperature": 1.0, # 창의성을 위해 온도를 약간 높게 설정
    }

    try:
        resp = global_gemini_model.generate_content(prompt, generation_config=generation_config)
        raw = resp.text or "{}"
        print(f"[{datetime.datetime.now()}] Gemini raw: {raw[:150]}...")
        
        obj = json.loads(raw)
        nickname = obj.get("nickname")
        updated_persona = obj.get("updated_persona")

        if not all([nickname, updated_persona]):
            raise ValueError("모델이 nickname 또는 updated_persona를 생성하지 못했습니다.")
        
        # AI가 규칙을 어겨도 최종적으로 길이를 강제함
        nickname = shorten_nickname(nickname, 8)

    except Exception as e:
        print(f"[{datetime.datetime.now()}] Gemini 처리 오류 → 로컬 백업: {e}")
        fallback = local_fallback_response(current_play["result"])
        nickname = fallback["nickname"]
        updated_persona = fallback["updated_persona"]

    # 클라이언트에 최종 결과 반환
    return jsonify({
        "nickname": nickname,
        "tag": tag,
        "score": score,
        "updated_persona": updated_persona
    })

if __name__ == "__main__":
    # 서버 실행
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)

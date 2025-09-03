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
    # API 키 환경 변수에서 로드
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
    return random.choice(TAGS), random.randint(1, 5)

# ---------------- 닉네임 길이 및 형식 정리 함수 ----------------
def shorten_nickname(nick: str, max_len: int = 8) -> str:
    # 기존 shorten_nickname 함수와 동일
    s = re.sub(r"[\(\)\[\]\{\}<>/\\]", "", (nick or "").strip())
    s = re.sub(r"ㅋ{3,}", "ㅋㅋ", s)
    s = re.sub(r"\?{3,}", "??", s)
    s = s.replace(" ", "")
    for token in ["??", "ㅋㅋ", "ㅎ", "ㅋ"]:
        while len(s) > max_len and token in s:
            s = s.replace(token, "", 1)
    if len(s) > max_len:
        s = s[:max_len]
    if s and s[-1] not in "ㅋ?ㅎ" and len(s) < max_len:
        s = (s + "ㅋ")[:max_len]
    return s or "ㅇㅋㅋㅋ"

# ---------------- 로컬 백업 닉네임 (Gemini 실패 시) ----------------
ALIASES = ["하타치ㅋ", "상타치", "케찹맨..", "쫄?", "거지근성ㅋ", "불쌍한넘"]
MAP_HINTS = ["집게발", "기계손", "보스발톱", "장난감집게", "클로"]

def local_fallback_response(game_result):
    alias = random.choice(ALIASES)
    hint = random.choice(MAP_HINTS)
    if str(game_result).upper() == "WIN":
        base = f"{hint}캐리{alias}ㅋㅋ"
    else:
        base = f"{hint}털림{alias}??"
    
    # ★★★ 변경점: 백업 응답도 새로운 API 형식에 맞게 nickname과 updated_persona를 모두 반환
    return {
        "nickname": shorten_nickname(base, 8),
        "updated_persona": "로컬 백업 페르소나: 최근 플레이 기록 반영에 실패함."
    }

# ---------------- 메인 API 엔드포인트 ----------------
@app.post("/api/ask")
def ask_gemini_nickname_with_persona():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json() or {}
    
    # --- ★★★ 변경점: 클라이언트로부터 받을 새로운 데이터들 ---
    # 1. 이번 판 플레이 결과 (기존과 동일)
    current_play = {
        "map_name": data.get("map_name"),
        "difficulty": data.get("difficulty"),
        "class": data.get("class"), # 직업 추가
        "game_result": (data.get("game_result") or "").upper()
    }
    
    # 2. 누적된 플레이 기록
    play_history = {
        "map_stats": data.get("map_stats", {}), # {"맵이름": 판수}
        "class_stats": data.get("class_stats", {}), # {"직업이름": 판수}
        "difficulty_stats": data.get("difficulty_stats", {}), # {"난이도": 판수}
    }

    # 3. 지난번에 AI가 만들어준 페르소나
    previous_persona = data.get("previous_persona", "이 유저는 오늘 처음 접속했습니다.")

    # 4. 지난번 닉네임에 대한 유저의 피드백 (말투 분석용)
    user_feedback = data.get("user_feedback", "")

    # 필수 검증
    if current_play["game_result"] not in ("WIN", "LOSE"):
        return jsonify({"error": "game_result must be WIN or LOSE"}), 400

    # 태그/점수는 여전히 서버에서 랜덤 생성
    tag, score = choose_random_tag_and_score()

    # 모델이 없으면 로컬 백업
    if global_gemini_model is None:
        fallback = local_fallback_response(current_play["game_result"])
        return jsonify({
            "nickname": fallback["nickname"],
            "tag": tag,
            "score": score,
            "updated_persona": fallback["updated_persona"]
        })

    # --- ★★★ 변경점: Gemini에게 전달할 프롬프트 대폭 수정 ---
    # 이제 AI는 '닉네임 생성'과 '페르소나 갱신' 두 가지 임무를 동시에 수행
    prompt = f"""
당신은 플레이어의 전투 기록을 분석하여, 재치있는 '잼민체' 별명을 추천하고 플레이어의 페르소나를 갱신하는 게임 AI입니다.

[분석할 데이터]
1. 과거의 누적된 페르소나 (가중치 40%):
   - "{previous_persona}"

2. 방금 플레이한 최신 전투 기록 (가중치 60%):
   - 최신 플레이: {json.dumps(current_play, ensure_ascii=False)}
   - 전체 플레이 통계: {json.dumps(play_history, ensure_ascii=False)}
   - 유저의 이전 닉네임 피드백: "{user_feedback}"

[수행할 임무]
1. 닉네임 생성:
   - 위 '분석할 데이터'를 종합적으로 고려하여, '최신 전투 기록'에 더 큰 비중(60%)을 두어 '잼민체' 별명을 1개 생성해주세요.
   - [닉네임 생성 규칙]
     - 공백 없이 6~8자 (최대 8자)
     - 짧고 강렬하게, ㅋㅋ/??/ㅎ 와 철자 파괴(예: 못갔쥬, 새키) 허용
     - 욕설, 비속어, 성적인 표현 절대 금지
     - 맵, 직업, 난이도 이름은 직접 사용하지 말고, 관련된 밈이나 특징으로 비틀어서 암시 (예: 인형뽑기 -> 집게사장ㅋ)
     - 게임 결과가 'WIN'이면 자뻑/허세 톤, 'LOSE'면 약 올리는 톤

2. 페르소나 갱신:
   - '과거의 누적된 페르소나' 내용에 '방금 플레이한 최신 전투 기록'과 '유저 피드백'을 자연스럽게 융합하여, 플레이어의 특징을 요약하는 새로운 페르소나 문장(1~2 문장)을 생성해주세요.
   - 유저 피드백에서 드러나는 말투(예: "~삼?")가 있다면 페르소나에 반영해주세요.

[출력 형식]
반드시 아래와 같은 JSON 형식으로만 응답해주세요. 다른 설명은 절대 추가하지 마세요.
{{"nickname": "생성된닉네임", "updated_persona": "갱신된페르소나문장"}}
"""

    generation_config = {
        "response_mime_type": "application/json",
        "temperature": 1.0,
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
        
        # 길이 및 형식 최종 정리
        nickname = shorten_nickname(nickname, 8)

    except Exception as e:
        print(f"[{datetime.datetime.now()}] Gemini 처리 오류 → 로컬 백업: {e}")
        fallback = local_fallback_response(current_play["game_result"])
        nickname = fallback["nickname"]
        updated_persona = fallback["updated_persona"]

    # --- ★★★ 변경점: 클라이언트에게 updated_persona도 함께 반환 ---
    return jsonify({
        "nickname": nickname,
        "tag": tag,
        "score": score,
        "updated_persona": updated_persona # 클라이언트는 이 값을 받아서 저장해야 함
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)

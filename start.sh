#!/bin/bash
set -e

# ==========================================================
# start.sh - 환경 설정 + 봇 실행 통합 스크립트
# ----------------------------------------------------------
# 사용법:
#   ./start.sh                  → .env 사용 (기본)
#   ./start.sh .env.kiwoom      → 지정 파일 사용
#   ENV_FILE=.env.kiwoom ./start.sh  → 환경변수로 지정
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="venv"
REQUIREMENTS="requests yfinance pytz pandas_market_calendars python-dotenv pillow python-telegram-bot[job-queue] peewee"
MIN_MINOR=10

# 위치 인자 우선, 없으면 ENV_FILE 변수, 그래도 없으면 .env
if [ -n "$1" ]; then
    ENV_FILE="$1"
fi
ENV_FILE="${ENV_FILE:-.env}"
echo "[INFO] env 파일: $ENV_FILE"

# ----------------------------------------------------------
# 1) 이미 실행 중인지 확인
# ----------------------------------------------------------
if [ -f .bot_pid ] && kill -0 "$(cat .bot_pid)" 2>/dev/null; then
    echo "[!] 봇이 이미 실행 중입니다 (PID: $(cat .bot_pid))"
    echo "    종료하려면: ./stop.sh"
    exit 1
fi

# ----------------------------------------------------------
# 2) Python 탐색 (기존 venv > PYTHON 환경변수 > 시스템 최신 버전)
# ----------------------------------------------------------
find_best_python() {
    # 기존 venv가 있으면 그대로 사용
    if [ -x "$VENV_DIR/bin/python" ]; then
        echo "$VENV_DIR/bin/python"
        return
    fi
    # PYTHON 환경변수가 지정되어 있으면 우선 사용
    if [ -n "$PYTHON" ] && command -v "$PYTHON" &>/dev/null; then
        echo "$PYTHON"
        return
    fi
    # 시스템에서 python3.13 ~ python3.10 순으로 탐색
    for v in 13 12 11 $MIN_MINOR; do
        if command -v "python3.$v" &>/dev/null; then
            echo "python3.$v"
            return
        fi
    done
    # fallback
    if command -v python3 &>/dev/null; then
        echo "python3"
        return
    fi
}

PYTHON=$(find_best_python)

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python을 찾을 수 없습니다. Python 3.${MIN_MINOR}+ 를 설치해주세요."
    exit 1
fi

PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MINOR_VER=$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MINOR_VER" -lt "$MIN_MINOR" ]; then
    echo "[ERROR] Python 3.${MIN_MINOR}+ 가 필요합니다. (감지됨: $PY_VERSION)"
    echo "        python3.${MIN_MINOR} 이상을 설치하거나, PYTHON=python3.12 ./start.sh 로 지정해주세요."
    exit 1
fi
echo "[OK] Python $PY_VERSION ($PYTHON)"

# ----------------------------------------------------------
# 3) 가상환경 생성 (없으면)
# ----------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "[*] 가상환경 생성 중..."
    "$PYTHON" -m venv "$VENV_DIR"
    echo "[OK] 가상환경 생성 완료"
fi

# ----------------------------------------------------------
# 4) 의존성 설치
# ----------------------------------------------------------
echo "[*] 의존성 확인 중..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet $REQUIREMENTS
echo "[OK] 의존성 준비 완료"

# ----------------------------------------------------------
# 5) env 파일 확인
# ----------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    # 기본 .env 이름일 때만 _env.example에서 자동 복사
    if [ "$ENV_FILE" = ".env" ] && [ -f _env.example ]; then
        echo "[!] .env 파일이 없습니다. _env.example 에서 복사합니다."
        cp _env.example .env
        echo "[!] .env 파일을 열어 실제 값을 입력한 뒤 다시 실행해주세요."
        exit 1
    else
        echo "[ERROR] $ENV_FILE 파일이 없습니다."
        echo "         키움 모드는: cp _env.kiwoom.example .env.kiwoom 후 값을 입력하고 ./start.sh .env.kiwoom 으로 실행하세요."
        exit 1
    fi
fi

# 브로커 선택 감지 (기본 KIS)
BROKER_VAL=$(grep "^BROKER=" "$ENV_FILE" | cut -d'=' -f2- | tr -d ' "' | tr '[:lower:]' '[:upper:]')
BROKER_VAL=${BROKER_VAL:-KIS}

if [ "$BROKER_VAL" = "KIWOOM" ]; then
    REQUIRED_VARS="TELEGRAM_TOKEN KIWOOM_APPKEY KIWOOM_SECRETKEY KIWOOM_ACCOUNT_NO"
    echo "[INFO] BROKER=KIWOOM (키움 REST API 모드)"
else
    REQUIRED_VARS="TELEGRAM_TOKEN APP_KEY APP_SECRET CANO"
    echo "[INFO] BROKER=KIS (한국투자증권 모드 · 기본값)"
fi

# 필수 환경변수 검증
MISSING=()
for VAR in $REQUIRED_VARS; do
    VAL=$(grep "^${VAR}=" "$ENV_FILE" | cut -d'=' -f2-)
    if [ -z "$VAL" ] || echo "$VAL" | grep -q "여기에"; then
        MISSING+=("$VAR")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "[ERROR] $ENV_FILE 에 다음 값이 설정되지 않았습니다:"
    for V in "${MISSING[@]}"; do
        echo "  - $V"
    done
    echo "  $ENV_FILE 파일을 수정한 뒤 다시 실행해주세요."
    exit 1
fi
echo "[OK] $ENV_FILE 검증 완료"

# ----------------------------------------------------------
# 6) 필요 디렉토리 생성
# ----------------------------------------------------------
mkdir -p data logs
echo "[OK] data/, logs/ 디렉토리 준비 완료"

# ----------------------------------------------------------
# 7) 타임존 설정 (클라우드 서버 대응)
# ----------------------------------------------------------
export TZ="${TZ:-Asia/Seoul}"
echo "[OK] 타임존: $TZ"

# ----------------------------------------------------------
# 8) 봇 실행
# ----------------------------------------------------------
echo "[*] 봇을 시작합니다..."
export ENV_FILE
nohup "$VENV_DIR/bin/python" main.py > logs/bot.log 2>&1 & echo $! > .bot_pid
echo "[OK] 봇 시작 완료 (PID: $(cat .bot_pid))"
echo "    로그 확인: tail -f logs/bot.log"
echo "    종료: ./stop.sh"

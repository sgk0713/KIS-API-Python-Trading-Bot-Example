#!/bin/bash
set -e

# ==========================================================
# start.sh - 환경 설정 + 봇 실행 통합 스크립트
# ==========================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON=${PYTHON:-python3}
VENV_DIR="venv"
REQUIREMENTS="requests yfinance pytz pandas_market_calendars python-dotenv pillow python-telegram-bot[job-queue] peewee"

# ----------------------------------------------------------
# 1) 이미 실행 중인지 확인
# ----------------------------------------------------------
if [ -f .bot_pid ] && kill -0 "$(cat .bot_pid)" 2>/dev/null; then
    echo "[!] 봇이 이미 실행 중입니다 (PID: $(cat .bot_pid))"
    echo "    종료하려면: ./stop.sh"
    exit 1
fi

# ----------------------------------------------------------
# 2) Python 버전 확인
# ----------------------------------------------------------
if ! command -v "$PYTHON" &>/dev/null; then
    echo "[ERROR] $PYTHON 을 찾을 수 없습니다. Python 3.10+ 를 설치해주세요."
    exit 1
fi

PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "[ERROR] Python 3.10+ 가 필요합니다. (현재: $PY_VERSION)"
    exit 1
fi
echo "[OK] Python $PY_VERSION"

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
# 5) .env 파일 확인
# ----------------------------------------------------------
if [ ! -f .env ]; then
    if [ -f _env.example ]; then
        echo "[!] .env 파일이 없습니다. _env.example 에서 복사합니다."
        cp _env.example .env
        echo "[!] .env 파일을 열어 실제 값을 입력한 뒤 다시 실행해주세요."
        exit 1
    else
        echo "[ERROR] .env 파일과 _env.example 모두 없습니다."
        exit 1
    fi
fi

# 필수 환경변수 검증
MISSING=()
for VAR in TELEGRAM_TOKEN APP_KEY APP_SECRET CANO; do
    VAL=$(grep "^${VAR}=" .env | cut -d'=' -f2-)
    if [ -z "$VAL" ] || echo "$VAL" | grep -q "여기에"; then
        MISSING+=("$VAR")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "[ERROR] .env 에 다음 값이 설정되지 않았습니다:"
    for V in "${MISSING[@]}"; do
        echo "  - $V"
    done
    echo "  .env 파일을 수정한 뒤 다시 실행해주세요."
    exit 1
fi
echo "[OK] .env 검증 완료"

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
nohup "$VENV_DIR/bin/python" main.py > logs/bot.log 2>&1 & echo $! > .bot_pid
echo "[OK] 봇 시작 완료 (PID: $(cat .bot_pid))"
echo "    로그 확인: tail -f logs/bot.log"
echo "    종료: ./stop.sh"

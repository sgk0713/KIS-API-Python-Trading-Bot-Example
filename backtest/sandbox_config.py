"""
샌드박스 Config — 프로덕션 data/* 파일을 건드리지 않고 백테스트 전용
디렉토리에 쓰고, datetime.now() 를 시뮬레이션 날짜로 우회.
"""
import os
import datetime
from config import ConfigManager


class BacktestConfig(ConfigManager):
    """
    프로덕션 ConfigManager 상속.
      - FILES 경로를 sandbox_dir 아래로 교체
      - _sim_date 속성으로 datetime.now() 의존 메서드를 우회
      - 기본 파라미터(seed/split/target/compound) 주입
    """

    # 프로덕션 FILES 키 → 파일명 매핑 (부모 __init__ 없이 직접 정의)
    _PRODUCTION_FILES = {
        "TOKEN": "token.dat",
        "CHAT_ID": "chat_id.dat",
        "LEDGER": "ledger.json",
        "HISTORY": "history.json",
        "SPLIT": "split_config.json",
        "TICKER": "active_tickers.json",
        "UPWARD_SNIPER": "upward_sniper.json",
        "SECRET_MODE": "secret_mode.dat",
        "PROFIT_CFG": "profit_config.json",
        "LOCKS": "trade_locks.json",
        "SEED_CFG": "seed_config.json",
        "COMPOUND_CFG": "compound_config.json",
        "VERSION_CFG": "version_config.json",
        "REVERSE_CFG": "reverse_config.json",
        "SNIPER_MULTIPLIER_CFG": "sniper_multiplier.json",
        "SPLIT_HISTORY": "split_history.json",
        "AVWAP_HYBRID_CFG": "avwap_hybrid.json",
    }

    def __init__(self, sandbox_dir, ticker, seed, split, target_pct, compound_rate):
        self.SANDBOX_DIR = sandbox_dir
        os.makedirs(sandbox_dir, exist_ok=True)

        # FILES 맵: 모든 경로를 sandbox_dir 아래로 교체
        self.FILES = {
            key: os.path.join(sandbox_dir, fname)
            for key, fname in self._PRODUCTION_FILES.items()
        }

        self._sim_date = None
        self._bt_ticker = ticker
        self._bt_seed = seed
        self._bt_split = split
        self._bt_target = target_pct
        self._bt_compound = compound_rate

        # 에스크로 인메모리 캐시 (부모 __init__ 미호출이므로 직접 초기화)
        self._escrow_cache = {}

        # 부모 __init__ 은 호출하지 않음 — 파일 경로·락 등이 프로덕션을 가리켜서 위험
        # 대신 필요한 초기값만 명시적으로 세팅
        self._bootstrap_sandbox()

    def _bootstrap_sandbox(self):
        """샌드박스 디렉토리에 빈 JSON 파일들 초기화."""
        defaults = {
            "LEDGER": [],
            "REVERSE_CFG": {},
            "LOCKS": {},
            "HISTORY": [],
            "SPLIT_HISTORY": {},
            "SEED_CFG": {},
            "COMPOUND_CFG": {},
            "VERSION_CFG": {},
            "PROFIT_CFG": {},
            "AVWAP_HYBRID_CFG": {},
        }
        for key, default in defaults.items():
            path = self.FILES.get(key)
            if path and not os.path.exists(path):
                self._save_json(path, default)

    # ==========================================================
    # 티커별 파라미터: 프로덕션은 각 JSON 파일을 보지만
    # 백테스트는 주입받은 값을 반환. seed 만 archive_graduation 에서
    # 복리 반영으로 변경될 수 있어 set_seed 를 지원.
    # ==========================================================
    def get_seed(self, ticker):
        return self._bt_seed

    def set_seed(self, ticker, value):
        self._bt_seed = int(value)

    def get_split_count(self, ticker):
        return self._bt_split

    def get_target_profit(self, ticker):
        return self._bt_target

    def get_compound_rate(self, ticker):
        return self._bt_compound

    def get_active_tickers(self):
        return [self._bt_ticker]

    def get_version(self, ticker):
        return "V14"

    def _today_str(self):
        if self._sim_date is None:
            raise RuntimeError("BacktestConfig._sim_date 가 설정되지 않았습니다")
        return self._sim_date.strftime('%Y-%m-%d')

    # ==========================================================
    # 시간 주입 오버라이드 — datetime.now() → self._sim_date
    # ==========================================================
    def set_lock(self, ticker, market_type):
        locks = self._load_json(self.FILES["LOCKS"], {})
        locks[f"{self._today_str()}_{ticker}_{market_type}"] = True
        self._save_json(self.FILES["LOCKS"], locks)

    def check_lock(self, ticker, market_type):
        locks = self._load_json(self.FILES["LOCKS"], {})
        return locks.get(f"{self._today_str()}_{ticker}_{market_type}", False)

    def set_reverse_state(self, ticker, is_active, day_count, exit_target=0.0, last_update_date=None):
        if last_update_date is None:
            last_update_date = self._today_str()
        d = self._load_json(self.FILES["REVERSE_CFG"], {})
        d[ticker] = {
            "is_active": is_active,
            "day_count": day_count,
            "exit_target": exit_target,
            "last_update_date": last_update_date,
        }
        self._save_json(self.FILES["REVERSE_CFG"], d)

    def get_total_locked_cash(self, exclude_ticker=None):
        # 단일 티커 백테스트 — 항상 0
        return 0.0

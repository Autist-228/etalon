#!/usr/bin/env python3
"""
Module 3 Config - Комиссии и настройки
"""

# === ДИНАМИЧЕСКИЕ КОМИССИИ (из официальных документов) ===
# Kalshi: fee = round_up(0.07 * C * P * (1-P)) для тейкера
#         fee = round_up(0.0175 * C * P * (1-P)) для мейкера
# Polymarket: 0% для большинства рынков (NBA, NHL, EPL, esports)
#             fee = 0.0175 * P * (1-P) для NCAAB и Serie A (с 18.02.2026)
KALSHI_TAKER_RATE = 0.07
KALSHI_MAKER_RATE = 0.0175
POLY_TAKER_RATE_SPORTS = 0.0175  # NCAAB, Serie A only

KALSHI_FEE = 0.01  # DEPRECATED - kept for backward compat
POLYMARKET_FEE = 0.0  # FIXED: was 0.02, actually 0% for most sports
TOTAL_FEE = 0.01  # DEPRECATED - use dynamic fees

POLY_FEE_MARKETS = {'NCAAMB', 'NCAAWB', 'SERIEA'}  # markets with Poly taker fees


def kalshi_taker_fee(price: float) -> float:
    """Kalshi taker fee per contract at given price (0-1)"""
    import math
    if price <= 0 or price >= 1:
        return 0.0
    return math.ceil(KALSHI_TAKER_RATE * price * (1 - price) * 100) / 100


def poly_taker_fee(price: float, sport_code: str = '') -> float:
    """Polymarket taker fee per contract. 0 for most sports."""
    if sport_code.upper() in POLY_FEE_MARKETS:
        return POLY_TAKER_RATE_SPORTS * price * (1 - price)
    return 0.0

# Интервал обновления (секунды)
UPDATE_INTERVAL = 1.0

# Порог для алерта положительной вилки (%)
POSITIVE_FORK_THRESHOLD = 0.0

# Порог для "горячей" вилки (%)
HOT_FORK_THRESHOLD = 3.0

# API URLs
KALSHI_API_URL = "https://api.elections.kalshi.com/trade-api/v2"
POLYMARKET_CLOB_API = "https://clob.polymarket.com"
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"

# Таймауты
API_TIMEOUT = 5  # секунд

# Цвета для терминала (ANSI)
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

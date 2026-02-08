#!/usr/bin/env python3
"""
Module 3 Config - Комиссии и настройки
"""

# Комиссии платформ (в процентах от выигрыша)
KALSHI_FEE = 0.01  # 1% комиссия Kalshi
POLYMARKET_FEE = 0.02  # 2% комиссия Polymarket

# Общая комиссия при арбитраже (сумма обеих)
TOTAL_FEE = KALSHI_FEE + POLYMARKET_FEE  # 3%

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

#!/usr/bin/env python3
"""
Module 4 Config - Настройки исполнителя
Все секреты через переменные окружения!
"""

import os
from dotenv import load_dotenv

# Загружаем .env файл
load_dotenv()

# === РЕЖИМ РАБОТЫ ===
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'

# === ПОРОГИ И ЛИМИТЫ ===
MIN_FORK_PCT = float(os.getenv('MIN_FORK_PCT', '15'))  # Минимальный % вилки для исполнения
MAX_TRADES_PER_SESSION = int(os.getenv('MAX_TRADES_PER_SESSION', '1'))  # Макс сделок за сессию
COOLDOWN_SECONDS = int(os.getenv('COOLDOWN_SECONDS', '60'))  # Пауза между сделками
ORDER_FILL_TIMEOUT = int(os.getenv('ORDER_FILL_TIMEOUT', '60'))  # Таймаут на исполнение ордера

# ЛОГИКА СТАВОК (убрали MAX лимиты!)
# Poly stake = poly_min + $1.00
# Kalshi stake = подстраивается под Poly

# === PROXY CONFIGURATION ===
PROXY_HOST = os.getenv('PROXY_HOST', '')
PROXY_HTTP_PORT = os.getenv('PROXY_HTTP_PORT', '60349')
PROXY_SOCKS5_PORT = os.getenv('PROXY_SOCKS5_PORT', '18208')
PROXY_USER = os.getenv('PROXY_USER', '')
PROXY_PASS = os.getenv('PROXY_PASS', '')

def get_http_proxy():
    """Get HTTP proxy URL for requests"""
    if PROXY_HOST and PROXY_USER:
        return f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_HTTP_PORT}"
    return None

def get_socks5_proxy():
    """Get SOCKS5 proxy URL"""
    if PROXY_HOST and PROXY_USER:
        return f"socks5://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_SOCKS5_PORT}"
    return None

def get_proxy_dict():
    """Get proxy dict for requests library"""
    http_proxy = get_http_proxy()
    if http_proxy:
        return {
            'http': http_proxy,
            'https': http_proxy,
        }
    return None

# === KALSHI API ===
KALSHI_API_KEY = os.getenv('KALSHI_API_KEY', '')
KALSHI_PRIVATE_KEY_FILE = os.getenv('KALSHI_PRIVATE_KEY_FILE', 'kalshi_private_key.pem')
KALSHI_API_URL = "https://api.elections.kalshi.com/trade-api/v2"

def load_kalshi_private_key():
    """Load Kalshi RSA private key from file"""
    # Try relative to script directory first
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.path.join(script_dir, KALSHI_PRIVATE_KEY_FILE)
    
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            return f.read()
    
    # Try current directory
    if os.path.exists(KALSHI_PRIVATE_KEY_FILE):
        with open(KALSHI_PRIVATE_KEY_FILE, 'r') as f:
            return f.read()
    
    # Fallback to env var (for backward compatibility)
    return os.getenv('KALSHI_API_SECRET', '')

KALSHI_API_SECRET = load_kalshi_private_key()

# === POLYMARKET ===
POLYMARKET_PRIVATE_KEY = os.getenv('POLYMARKET_PRIVATE_KEY', '')  # Polygon wallet private key
POLYGON_RPC_URL = os.getenv('POLYGON_RPC_URL', 'https://polygon-rpc.com')
POLYMARKET_CLOB_API = "https://clob.polymarket.com"
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"

# === ФАЙЛЫ ===
EXECUTED_TRADES_FILE = os.getenv('EXECUTED_TRADES_FILE', 'executed_trades.json')
SIGNALS_FILE = os.getenv('SIGNALS_FILE', 'signals.jsonl')
TRADE_LOG_FILE = os.getenv('TRADE_LOG_FILE', 'trade_log.jsonl')

# === ТАЙМАУТЫ ===
API_TIMEOUT = 30  # секунд (increased for proxy latency)
ORDER_TIMEOUT = 60  # секунд на исполнение ордера


def validate_config():
    """Проверить что конфиг валидный для LIVE режима"""
    errors = []
    
    if not DRY_RUN:
        if not KALSHI_API_KEY:
            errors.append("KALSHI_API_KEY not set")
        if not KALSHI_API_SECRET:
            errors.append("KALSHI_API_SECRET not set")
        if not POLYMARKET_PRIVATE_KEY:
            errors.append("POLYMARKET_PRIVATE_KEY not set")
    
    if MIN_FORK_PCT < 0:
        errors.append("MIN_FORK_PCT must be >= 0")
    if MAX_TRADES_PER_SESSION < 1:
        errors.append("MAX_TRADES_PER_SESSION must be >= 1")
    
    return errors


def print_config():
    """Вывести текущую конфигурацию (без секретов)"""
    print("=" * 60)
    print("MODULE 4 EXECUTOR CONFIG")
    print("=" * 60)
    print(f"  DRY_RUN:                {DRY_RUN}")
    print(f"  MIN_FORK_PCT:           {MIN_FORK_PCT}%")
    print(f"  STAKE LOGIC:            Poly = min + $1, Kalshi подстраивается")
    print(f"  MAX_TRADES_PER_SESSION: {MAX_TRADES_PER_SESSION}")
    print(f"  COOLDOWN_SECONDS:       {COOLDOWN_SECONDS}")
    print(f"  ORDER_FILL_TIMEOUT:     {ORDER_FILL_TIMEOUT}s")
    print(f"  KALSHI_API_KEY:         {'***' + KALSHI_API_KEY[-4:] if KALSHI_API_KEY else 'NOT SET'}")
    print(f"  POLYMARKET_KEY:         {'***' + POLYMARKET_PRIVATE_KEY[-4:] if POLYMARKET_PRIVATE_KEY else 'NOT SET'}")
    print(f"  PROXY:                  {'YES' if PROXY_HOST else 'NO'}")
    print("=" * 60)

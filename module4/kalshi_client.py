#!/usr/bin/env python3
"""
Kalshi Trading Client - исполнение ордеров на Kalshi
"""

import requests
import time
import base64
import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from .config import KALSHI_API_KEY, KALSHI_API_SECRET, KALSHI_API_URL, API_TIMEOUT, get_proxy_dict


class KalshiClient:
    """Клиент для торговли на Kalshi"""
    
    def __init__(self):
        self.api_key = KALSHI_API_KEY
        self.private_key = self._load_private_key(KALSHI_API_SECRET)
        self.session = requests.Session()
        self.base_url = KALSHI_API_URL
        
        # Configure proxy
        self.proxies = get_proxy_dict()
        if self.proxies:
            self.session.proxies.update(self.proxies)
            print(f"✅ Kalshi client using proxy: {self.proxies.get('https', 'none')[:50]}...")
        
    def _load_private_key(self, key_str: str):
        """Загрузить RSA приватный ключ"""
        if not key_str:
            return None
        try:
            key_bytes = key_str.encode('utf-8')
            return serialization.load_pem_private_key(
                key_bytes,
                password=None,
                backend=default_backend()
            )
        except Exception as e:
            print(f"❌ Failed to load Kalshi private key: {e}")
            return None
    
    def _sign_request(self, timestamp: str, method: str, path: str) -> str:
        """Подписать запрос RSA-PSS ключом (Kalshi требует PSS padding)"""
        if not self.private_key:
            return ""
        
        # Kalshi signature format: timestamp + method + path (without query params)
        # Remove query params from path for signature
        path_without_query = path.split('?')[0]
        message = f"{timestamp}{method}{path_without_query}"
        
        # Use RSA-PSS padding as required by Kalshi
        signature = self.private_key.sign(
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    
    def _get_headers(self, method: str, path: str) -> Dict:
        """Получить заголовки с авторизацией"""
        timestamp = str(int(time.time() * 1000))
        # Path for signature must include /trade-api/v2 prefix
        full_path = f"/trade-api/v2{path}"
        signature = self._sign_request(timestamp, method, full_path)
        
        return {
            'Content-Type': 'application/json',
            'KALSHI-ACCESS-KEY': self.api_key,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
        }
    
    def get_balance(self) -> Optional[float]:
        """Получить баланс аккаунта в USD"""
        try:
            path = "/portfolio/balance"
            headers = self._get_headers("GET", path)
            resp = self.session.get(
                f"{self.base_url}{path}",
                headers=headers,
                timeout=API_TIMEOUT
            )
            
            if resp.status_code == 200:
                data = resp.json()
                # Kalshi возвращает баланс в центах
                balance_cents = data.get('balance', 0)
                return balance_cents / 100
            else:
                print(f"❌ Kalshi balance error: {resp.status_code} - {resp.text}")
                return None
                
        except Exception as e:
            print(f"❌ Kalshi balance exception: {e}")
            return None
    
    def get_market_price(self, ticker: str) -> Optional[Dict]:
        """Получить текущие цены рынка"""
        try:
            path = f"/markets/{ticker}"
            resp = self.session.get(
                f"{self.base_url}{path}",
                timeout=API_TIMEOUT
            )
            
            if resp.status_code == 200:
                data = resp.json()
                market = data.get('market', {})
                return {
                    'yes_bid': market.get('yes_bid', 0) / 100,
                    'yes_ask': market.get('yes_ask', 0) / 100,
                    'no_bid': market.get('no_bid', 0) / 100,
                    'no_ask': market.get('no_ask', 0) / 100,
                    'status': market.get('status', ''),
                }
            return None
            
        except Exception as e:
            print(f"❌ Kalshi market price error: {e}")
            return None
    
    def place_order(self, ticker: str, side: str, contracts: int, 
                    limit_price: float = None) -> Tuple[bool, Dict]:
        """
        Разместить ордер на Kalshi.
        
        Args:
            ticker: тикер рынка (например KXNBATOTAL-26JAN25DALMIL-219)
            side: 'yes' или 'no'
            contracts: количество контрактов
            limit_price: лимитная цена (0-1), если None - market order
        
        Returns:
            (success, result_dict)
        """
        try:
            path = "/portfolio/orders"
            headers = self._get_headers("POST", path)
            
            # Kalshi использует центы для цен
            order_data = {
                'ticker': ticker,
                'action': 'buy',
                'side': side,
                'count': contracts,
                'type': 'market' if limit_price is None else 'limit',
            }
            
            if limit_price is not None:
                # Цена в центах (0-99)
                order_data['yes_price'] = int(limit_price * 100) if side == 'yes' else None
                order_data['no_price'] = int(limit_price * 100) if side == 'no' else None
            
            resp = self.session.post(
                f"{self.base_url}{path}",
                headers=headers,
                json=order_data,
                timeout=API_TIMEOUT
            )
            
            if resp.status_code in [200, 201]:
                data = resp.json()
                order = data.get('order', {})
                return True, {
                    'order_id': order.get('order_id', ''),
                    'status': order.get('status', ''),
                    'ticker': ticker,
                    'side': side,
                    'contracts': contracts,
                    'filled_count': order.get('filled_count', 0),
                    'avg_price': order.get('avg_price', 0) / 100 if order.get('avg_price') else None,
                }
            else:
                return False, {
                    'error': f"HTTP {resp.status_code}",
                    'message': resp.text,
                    'ticker': ticker,
                    'side': side,
                }
                
        except Exception as e:
            return False, {
                'error': 'exception',
                'message': str(e),
                'ticker': ticker,
                'side': side,
            }
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """Получить статус ордера"""
        try:
            path = f"/portfolio/orders/{order_id}"
            headers = self._get_headers("GET", path)
            resp = self.session.get(
                f"{self.base_url}{path}",
                headers=headers,
                timeout=API_TIMEOUT
            )
            
            if resp.status_code == 200:
                data = resp.json()
                order = data.get('order', {})
                return {
                    'order_id': order.get('order_id', ''),
                    'status': order.get('status', ''),
                    'filled_count': order.get('filled_count', 0),
                    'remaining_count': order.get('remaining_count', 0),
                    'avg_price': order.get('avg_price', 0) / 100 if order.get('avg_price') else None,
                }
            return None
            
        except Exception as e:
            print(f"❌ Kalshi order status error: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Отменить ордер
        
        Returns:
            True если успешно отменён
        """
        try:
            path = f"/portfolio/orders/{order_id}"
            headers = self._get_headers("DELETE", path)
            
            resp = self.session.delete(
                f"{self.base_url}{path}",
                headers=headers,
                timeout=API_TIMEOUT
            )
            
            return resp.status_code in [200, 204]
            
        except Exception as e:
            print(f"❌ Kalshi cancel order error: {e}")
            return False
    
    def get_market_info(self, ticker: str) -> Optional[Dict]:
        """Получить информацию о рынке включая лимиты ордеров"""
        try:
            path = f"/markets/{ticker}"
            resp = self.session.get(
                f"{self.base_url}{path}",
                timeout=API_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                market = data.get('market', {})
                return {
                    'ticker': ticker,
                    'status': market.get('status', ''),
                    'yes_bid': market.get('yes_bid', 0) / 100,
                    'yes_ask': market.get('yes_ask', 0) / 100,
                    'no_bid': market.get('no_bid', 0) / 100,
                    'no_ask': market.get('no_ask', 0) / 100,
                    'can_close_early': market.get('can_close_early', False),
                    'floor_strike': market.get('floor_strike'),
                    'cap_strike': market.get('cap_strike'),
                }
            return None
        except Exception as e:
            print(f"❌ Kalshi market info error: {e}")
            return None

    def get_active_markets(self, event_ticker: str = None, limit: int = 10) -> list:
        """Получить активные рынки"""
        try:
            path = "/markets"
            params = {'limit': limit, 'status': 'open'}
            if event_ticker:
                params['event_ticker'] = event_ticker
            headers = self._get_headers("GET", path)
            resp = self.session.get(
                f"{self.base_url}{path}",
                headers=headers,
                params=params,
                timeout=API_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get('markets', [])
            return []
        except Exception as e:
            print(f"❌ Kalshi active markets error: {e}")
            return []

    def calculate_contracts(self, budget_usd: float, price: float) -> int:
        """
        Рассчитать количество контрактов для бюджета.
        
        На Kalshi: 1 контракт = $1 при выигрыше
        Стоимость покупки = price * contracts
        """
        if price <= 0 or price >= 1:
            return 0
        
        # Сколько контрактов можем купить на бюджет
        contracts = int(budget_usd / price)
        return max(1, contracts)  # Минимум 1 контракт


# Тест
if __name__ == "__main__":
    client = KalshiClient()
    
    print("Testing Kalshi Client...")
    
    # Тест получения цен (не требует авторизации)
    prices = client.get_market_price("KXNBATOTAL-26JAN25DALMIL-219")
    if prices:
        print(f"  Market prices: {prices}")
    else:
        print("  Could not get market prices")
    
    # Тест баланса (требует авторизации)
    if KALSHI_API_KEY:
        balance = client.get_balance()
        if balance is not None:
            print(f"  Balance: ${balance:.2f}")
        else:
            print("  Could not get balance")

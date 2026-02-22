#!/usr/bin/env python3
"""
Prices Fetcher - получение цен в реальном времени с Kalshi и Polymarket
НЕЗАВИСИМЫЙ модуль - сам долбит API каждую секунду
"""

import requests
from typing import Dict, Optional, List
from datetime import datetime, timezone
import time
import json

from .config import KALSHI_API_URL, POLYMARKET_CLOB_API, POLYMARKET_GAMMA_API, API_TIMEOUT


class PricesFetcher:
    """Получение СВЕЖИХ цен с Kalshi и Polymarket каждую секунду"""
    
    def __init__(self):
        self.session = requests.Session()
        # Минимальный кэш только для дедупликации в рамках одной секунды
        self.cache = {}
        self.cache_ttl = 0.3  # 300ms - защита от дублей в одной итерации
        
    def fetch_kalshi_market(self, market_ticker: str) -> Optional[Dict]:
        """
        Получить СВЕЖИЕ цены с Kalshi для конкретного market_ticker.
        Делает реальный запрос к API!
        """
        cache_key = f"kalshi_m_{market_ticker}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        try:
            url = f"{KALSHI_API_URL}/markets/{market_ticker}"
            resp = self.session.get(url, timeout=API_TIMEOUT)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            market = data.get('market', {})
            
            # Kalshi возвращает цены в центах (0-100)
            result = {
                'yes_bid': market.get('yes_bid', 0) / 100,
                'yes_ask': market.get('yes_ask', 0) / 100,
                'no_bid': market.get('no_bid', 0) / 100,
                'no_ask': market.get('no_ask', 0) / 100,
                'last_price': market.get('last_price', 0) / 100,
                'volume': market.get('volume', 0),
                'status': market.get('status', ''),
            }
            
            self._set_cached(cache_key, result)
            return result
            
        except Exception as e:
            return None
    
    def fetch_kalshi_event_markets(self, event_ticker: str) -> Optional[List[Dict]]:
        """
        Получить СВЕЖИЕ цены всех рынков события Kalshi.
        Делает реальный запрос к API!
        """
        cache_key = f"kalshi_e_{event_ticker}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        try:
            url = f"{KALSHI_API_URL}/events/{event_ticker}"
            resp = self.session.get(url, timeout=API_TIMEOUT)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            event = data.get('event', {})
            markets = event.get('markets', [])
            
            result = []
            for m in markets:
                result.append({
                    'ticker': m.get('ticker', ''),
                    'title': m.get('title', ''),
                    'yes_bid': m.get('yes_bid', 0) / 100,
                    'yes_ask': m.get('yes_ask', 0) / 100,
                    'no_bid': m.get('no_bid', 0) / 100,
                    'no_ask': m.get('no_ask', 0) / 100,
                    'last_price': m.get('last_price', 0) / 100,
                    'volume': m.get('volume', 0),
                    'yes_sub_title': m.get('yes_sub_title', ''),
                    'no_sub_title': m.get('no_sub_title', ''),
                })
            
            self._set_cached(cache_key, result)
            return result
            
        except Exception as e:
            return None
    
    def fetch_polymarket_by_slug(self, slug: str) -> Optional[Dict]:
        """
        Получить СВЕЖИЕ цены с Polymarket по slug.
        Делает реальный запрос к API!
        """
        cache_key = f"poly_s_{slug}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        try:
            url = f"{POLYMARKET_GAMMA_API}/events"
            params = {'slug': slug}
            resp = self.session.get(url, params=params, timeout=API_TIMEOUT)
            
            if resp.status_code != 200:
                return None
            
            events = resp.json()
            if not events or len(events) == 0:
                return None
            
            event = events[0]
            markets = event.get('markets', [])
            if not markets:
                return None
            
            market = markets[0]
            prices_str = market.get('outcomePrices', '[]')
            if isinstance(prices_str, str):
                prices = json.loads(prices_str)
            else:
                prices = prices_str
            
            yes_price = float(prices[0]) if len(prices) > 0 else 0.5
            no_price = float(prices[1]) if len(prices) > 1 else 0.5
            
            result = {
                'yes_price': yes_price,
                'no_price': no_price,
            }
            
            self._set_cached(cache_key, result)
            return result
            
        except Exception as e:
            return None
    
    def fetch_polymarket_by_condition(self, condition_id: str) -> Optional[Dict]:
        """
        ⚠️ DEPRECATED: Этот метод использует сломанный API endpoint!
        Используйте fetch_polymarket_by_slug_and_condition() вместо него.
        
        /markets?condition_id=... возвращает НЕПРАВИЛЬНЫЕ данные (случайные рынки).
        """
        print(f"⚠️ WARNING: fetch_polymarket_by_condition() is DEPRECATED and returns WRONG data!")
        return None  # Возвращаем None чтобы не использовать неправильные данные
    
    def fetch_polymarket_by_slug_and_condition(self, slug: str, condition_id: str = None, 
                                                token_ids: List[str] = None, question: str = None,
                                                outcome_key: str = None) -> Optional[Dict]:
        """
        Получить СВЕЖИЕ цены с Polymarket ПРАВИЛЬНЫМ способом:
        1. GET /events?slug=... 
        2. Найти market по question ИЛИ outcome_key (conditionId может устареть!)
        3. Получить цены из CLOB bid/ask (исполняемые цены)
        
        Args:
            slug: slug события (например 'nhl-las-ott-2026-01-25')
            condition_id: conditionId (может быть устаревшим!)
            token_ids: token_ids для CLOB
            question: вопрос маркета для поиска (ОСНОВНОЙ способ!)
            outcome_key: outcome_key для поиска
        
        Returns:
            Dict с yes_bid, yes_ask, no_bid, no_ask или None если не найдено
        """
        cache_key = f"poly_sc_{slug}_{question[:30] if question else condition_id[:20]}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        try:
            # Шаг 1: Получаем событие по slug
            url = f"{POLYMARKET_GAMMA_API}/events"
            params = {'slug': slug}
            resp = self.session.get(url, params=params, timeout=API_TIMEOUT)
            
            if resp.status_code != 200:
                return None
            
            events = resp.json()
            if not events:
                return None
            
            # Шаг 2: Ищем market по question (ОСНОВНОЙ способ!)
            target_market = None
            
            for event in events:
                markets = event.get('markets', [])
                
                # Сначала пытаемся найти по question
                if question:
                    for market in markets:
                        if market.get('question', '') == question:
                            target_market = market
                            break
                
                # Если не нашли по question, пробуем по conditionId
                if not target_market and condition_id:
                    for market in markets:
                        if market.get('conditionId') == condition_id:
                            target_market = market
                            break
                
                if target_market:
                    break
            
            if not target_market:
                # Не найден ни по question, ни по conditionId
                return None
            
            # Шаг 3: Получаем token_ids если не переданы
            if not token_ids:
                tokens_raw = target_market.get('clobTokenIds', '[]')
                if isinstance(tokens_raw, str):
                    token_ids = json.loads(tokens_raw)
                else:
                    token_ids = tokens_raw or []
            
            if not token_ids or len(token_ids) < 2:
                # Нет token_ids - используем цены из Gamma (fallback)
                prices_str = target_market.get('outcomePrices', '[]')
                if isinstance(prices_str, str):
                    prices = json.loads(prices_str)
                else:
                    prices = prices_str
                
                yes_price = float(prices[0]) if prices else 0.5
                no_price = float(prices[1]) if len(prices) > 1 else 0.5
                
                result = {
                    'yes_bid': yes_price,
                    'yes_ask': yes_price,
                    'no_bid': no_price,
                    'no_ask': no_price,
                    'yes_price': yes_price,
                    'no_price': no_price,
                    'yes': yes_price,  # ← КЛЮЧ ДЛЯ СОВМЕСТИМОСТИ С fork_tracker!
                    'no': no_price,    # ← КЛЮЧ ДЛЯ СОВМЕСТИМОСТИ С fork_tracker!
                    'source': 'gamma_fallback',
                    'condition_id_verified': True,
                }
                self._set_cached(cache_key, result)
                return result
            
            # Шаг 4: Получаем цены из CLOB (исполняемые bid/ask)
            yes_token = token_ids[0]
            no_token = token_ids[1]
            
            yes_prices = self._fetch_clob_prices(yes_token)
            no_prices = self._fetch_clob_prices(no_token)
            
            if not yes_prices and not no_prices:
                # CLOB не работает - fallback на Gamma
                prices_str = target_market.get('outcomePrices', '[]')
                if isinstance(prices_str, str):
                    prices = json.loads(prices_str)
                else:
                    prices = prices_str
                
                yes_price = float(prices[0]) if prices else 0.5
                no_price = float(prices[1]) if len(prices) > 1 else 0.5
                
                result = {
                    'yes_bid': yes_price,
                    'yes_ask': yes_price,
                    'no_bid': no_price,
                    'no_ask': no_price,
                    'yes_price': yes_price,
                    'no_price': no_price,
                    'yes': yes_price,  # ← КЛЮЧ ДЛЯ СОВМЕСТИМОСТИ!
                    'no': no_price,    # ← КЛЮЧ ДЛЯ СОВМЕСТИМОСТИ!
                    'source': 'gamma_fallback_no_clob',
                    'condition_id_verified': True,
                }
                self._set_cached(cache_key, result)
                return result
            
            yes_bid = yes_prices.get('bid', 0) if yes_prices else 0
            yes_ask = yes_prices.get('ask', 1) if yes_prices else 1
            no_bid = no_prices.get('bid', 0) if no_prices else 0
            no_ask = no_prices.get('ask', 1) if no_prices else 1
            yes_mid = yes_prices.get('mid', 0.5) if yes_prices else 0.5
            no_mid = no_prices.get('mid', 0.5) if no_prices else 0.5
            
            result = {
                'yes_bid': yes_bid,
                'yes_ask': yes_ask,
                'no_bid': no_bid,
                'no_ask': no_ask,
                'yes_price': yes_mid,
                'no_price': no_mid,
                'yes': yes_mid,  # ← КЛЮЧ ДЛЯ СОВМЕСТИМОСТИ (mid = (bid+ask)/2)!
                'no': no_mid,    # ← КЛЮЧ ДЛЯ СОВМЕСТИМОСТИ!
                'source': 'clob',
                'condition_id_verified': True,
            }
            
            self._set_cached(cache_key, result)
            return result
            
        except Exception as e:
            print(f"❌ Error in fetch_polymarket_by_slug_and_condition: {e}")
            return None
    
    def _fetch_clob_prices(self, token_id: str) -> Optional[Dict]:
        """Получить bid/ask/mid из CLOB для token_id"""
        try:
            # Пробуем получить midpoint (быстрее чем book)
            resp = self.session.get(
                f"{POLYMARKET_CLOB_API}/midpoint",
                params={'token_id': token_id},
                timeout=API_TIMEOUT
            )
            
            if resp.status_code == 200:
                data = resp.json()
                mid = float(data.get('mid', 0.5))
                
                # Пробуем получить book для bid/ask
                book_resp = self.session.get(
                    f"{POLYMARKET_CLOB_API}/book",
                    params={'token_id': token_id},
                    timeout=API_TIMEOUT
                )
                
                if book_resp.status_code == 200:
                    book = book_resp.json()
                    bids = book.get('bids', [])
                    asks = book.get('asks', [])
                    
                    best_bid = max((float(b['price']) for b in bids), default=None)
                    best_ask = min((float(a['price']) for a in asks), default=None)
                    
                    if best_bid is not None and best_ask is not None:
                        return {
                            'bid': best_bid,
                            'ask': best_ask,
                            'mid': mid,
                        }
                    elif best_bid is not None:
                        return {
                            'bid': best_bid,
                            'ask': best_bid,
                            'mid': mid,
                            'no_asks': True,
                        }
                    elif best_ask is not None:
                        return {
                            'bid': best_ask,
                            'ask': best_ask,
                            'mid': mid,
                            'no_bids': True,
                        }
                
                return {'bid': mid, 'ask': mid, 'mid': mid}
            
            return None
            
        except Exception as e:
            return None
    
    def clear_cache(self):
        """Очистить кэш для получения совсем свежих данных"""
        self.cache = {}
    
    def _get_cached(self, key: str) -> Optional[Dict]:
        """Получить из кэша если не истёк (очень короткий TTL)"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_ttl:
                return data
        return None
    
    def _set_cached(self, key: str, data: Dict):
        """Сохранить в кэш"""
        self.cache[key] = (data, time.time())
    
    # Алиасы для совместимости
    def fetch_kalshi_prices(self, market_ticker: str) -> Optional[Dict]:
        return self.fetch_kalshi_market(market_ticker)
    
    def fetch_kalshi_event_prices(self, event_ticker: str) -> Optional[List[Dict]]:
        return self.fetch_kalshi_event_markets(event_ticker)
    
    def fetch_polymarket_prices(self, token_id: str = None, condition_id: str = None, slug: str = None) -> Optional[Dict]:
        if slug:
            return self.fetch_polymarket_by_slug(slug)
        if condition_id:
            return self.fetch_polymarket_by_condition(condition_id)
        return None


# Тест
if __name__ == "__main__":
    fetcher = PricesFetcher()
    
    # Тест Kalshi
    print("Testing Kalshi...")
    kalshi_prices = fetcher.fetch_kalshi_event_prices("KXNHLGAME-26JAN25-TBLCBJ")
    if kalshi_prices:
        print(f"  Found {len(kalshi_prices)} markets")
        for m in kalshi_prices[:3]:
            print(f"    {m['ticker']}: YES={m['yes_bid']:.2f}/{m['yes_ask']:.2f}")
    else:
        print("  No data")
    
    # Тест Polymarket
    print("\nTesting Polymarket...")
    poly_prices = fetcher.fetch_polymarket_by_slug("lightning-vs-blue-jackets")
    if poly_prices:
        print(f"  YES={poly_prices.get('yes_price', 0):.2f}, NO={poly_prices.get('no_price', 0):.2f}")
    else:
        print("  No data")

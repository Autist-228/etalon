#!/usr/bin/env python3
"""
MODULE 3.5 - LIMITS & LIQUIDITY CHECKER
Проверяет реальную исполнимость вилок: минимальные ставки, ликвидность, order book
"""

import requests
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

@dataclass
class LimitsResult:
    """Результат проверки лимитов"""
    is_executable: bool
    min_stake_usd: float
    max_stake_usd: float
    kalshi_min: float
    kalshi_max: float
    poly_min: float
    poly_max: float
    reason: str
    classification: str  # EXECUTABLE, TOO_SMALL, TOO_RISKY, FAKE


class LimitsChecker:
    """Проверка минимальных ставок и ликвидности"""
    
    def __init__(self):
        self.session = requests.Session()
        # Константы
        self.KALSHI_MIN_ORDER = 1.0  # $1 минимум на Kalshi
        self.POLY_MIN_ORDER = 0.01  # Минимум на Polymarket (вычисляем по стакану)
        self.MAX_RISK_DEFAULT = 100.0  # $100 максимум по умолчанию
    
    def check_kalshi_limits(self, market_ticker: str) -> Dict:
        """
        Получить лимиты и ликвидность с Kalshi
        
        Returns:
            {
                'min_order_size': float,
                'max_order_size': float,
                'yes_bid': float,
                'yes_ask': float,
                'yes_bid_size': int (contracts),
                'yes_ask_size': int,
                'liquidity_usd': float
            }
        """
        try:
            # Получаем market data
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{market_ticker}"
            resp = self.session.get(url, timeout=5)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json().get('market', {})
            
            # Kalshi даёт цены в центах (0-100)
            yes_bid = data.get('yes_bid', 0) / 100.0
            yes_ask = data.get('yes_ask', 0) / 100.0
            no_bid = data.get('no_bid', 0) / 100.0
            no_ask = data.get('no_ask', 0) / 100.0
            
            # Минимальный размер ордера (обычно $1)
            min_order = self.KALSHI_MIN_ORDER
            
            # Максимальный размер (вычисляем по open_interest или volume)
            open_interest = data.get('open_interest', 0)
            volume = data.get('volume', 0)
            
            # Оцениваем максимальную ликвидность как 10% от open_interest
            max_liquidity_contracts = max(int(open_interest * 0.1), 10)
            
            # В USD: contracts * price
            yes_liquidity_usd = max_liquidity_contracts * yes_ask if yes_ask > 0 else 0
            no_liquidity_usd = max_liquidity_contracts * no_ask if no_ask > 0 else 0
            
            return {
                'min_order_size': min_order,
                'max_order_size': max(yes_liquidity_usd, no_liquidity_usd),
                'yes_bid': yes_bid,
                'yes_ask': yes_ask,
                'no_bid': no_bid,
                'no_ask': no_ask,
                'yes_bid_size': max_liquidity_contracts,
                'yes_ask_size': max_liquidity_contracts,
                'no_bid_size': max_liquidity_contracts,
                'no_ask_size': max_liquidity_contracts,
                'liquidity_usd': yes_liquidity_usd + no_liquidity_usd,
                'open_interest': open_interest,
                'volume': volume
            }
            
        except Exception as e:
            return None
    
    def check_polymarket_limits(self, condition_id: str, token_id: str = None) -> Dict:
        """
        Получить лимиты и ликвидность с Polymarket через CLOB
        
        Args:
            condition_id: conditionId market
            token_id: tokenId для конкретного исхода (YES/NO)
        
        Returns:
            {
                'min_order_size': float,
                'max_order_size': float,
                'best_bid': float,
                'best_ask': float,
                'bid_liquidity_usd': float,
                'ask_liquidity_usd': float,
                'total_liquidity_usd': float
            }
        """
        try:
            # Получаем order book с CLOB
            # Используем simplified book для скорости
            url = f"https://clob.polymarket.com/book"
            params = {
                'token_id': token_id if token_id else condition_id
            }
            
            resp = self.session.get(url, params=params, timeout=5)
            
            if resp.status_code != 200:
                # Fallback: пробуем через markets endpoint
                return self._check_polymarket_fallback(condition_id)
            
            book = resp.json()
            
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            
            if not bids or not asks:
                return self._check_polymarket_fallback(condition_id)
            
            # Лучшие цены
            best_bid_price = float(bids[0]['price']) if bids else 0
            best_ask_price = float(asks[0]['price']) if asks else 0
            
            # Ликвидность на лучших уровнях
            best_bid_size = float(bids[0]['size']) if bids else 0  # В контрактах
            best_ask_size = float(asks[0]['size']) if asks else 0
            
            # Суммарная ликвидность (топ 5 уровней)
            bid_liquidity_contracts = sum(float(b['size']) for b in bids[:5])
            ask_liquidity_contracts = sum(float(a['size']) for a in asks[:5])
            
            # В USD
            bid_liquidity_usd = bid_liquidity_contracts * best_bid_price
            ask_liquidity_usd = ask_liquidity_contracts * best_ask_price
            
            # Минимальный размер: ИЩЕМ МАЛЕНЬКИЕ ОРДЕРА В СТАКАНЕ!
            # Polymarket позволяет дробные контракты (минимум ~0.01 contract)
            small_orders = []
            
            for bid in bids[:20]:
                size = float(bid['size'])
                price = float(bid['price'])
                usd = size * price
                # Ищем ордера от $0.01 до $1000
                if usd >= 0.01 and usd <= 1000:
                    small_orders.append(usd)
            
            for ask in asks[:20]:
                size = float(ask['size'])
                price = float(ask['price'])
                usd = size * price
                # Ищем ордера от $0.01 до $1000
                if usd >= 0.01 and usd <= 1000:
                    small_orders.append(usd)
            
            # Минимум = самый маленький найденный ордер
            if small_orders:
                min_order = min(small_orders)
            else:
                # Fallback: 1 контракт по best ask (минимум $0.01)
                min_order = max(best_ask_price if best_ask_price > 0 else self.POLY_MIN_ORDER, 0.01)
            
            # ВАЖНО: Возвращаем ОБЕ ликвидности!
            # Для покупки YES нужна ask_liquidity
            # Для покупки NO (продажа YES) нужна bid_liquidity
            return {
                'min_order_size': min_order,
                'max_order_size': ask_liquidity_usd,  # По умолчанию ASK (покупка)
                'max_buy_liquidity': ask_liquidity_usd,  # Для покупки токена
                'max_sell_liquidity': bid_liquidity_usd,  # Для продажи токена
                'best_bid': best_bid_price,
                'best_ask': best_ask_price,
                'best_bid_size': best_bid_size,
                'best_ask_size': best_ask_size,
                'bid_liquidity_usd': bid_liquidity_usd,
                'ask_liquidity_usd': ask_liquidity_usd,
                'total_liquidity_usd': bid_liquidity_usd + ask_liquidity_usd
            }
            
        except Exception as e:
            return self._check_polymarket_fallback(condition_id)
    
    def _check_polymarket_fallback(self, condition_id: str) -> Dict:
        """Fallback: оценка по gamma API без order book"""
        # Возвращаем консервативные оценки
        return {
            'min_order_size': 1.0,  # $1 консервативно
            'max_order_size': 50.0,  # $50 консервативно
            'best_bid': 0.5,
            'best_ask': 0.5,
            'best_bid_size': 100,
            'best_ask_size': 100,
            'bid_liquidity_usd': 50.0,
            'ask_liquidity_usd': 50.0,
            'total_liquidity_usd': 100.0
        }
    
    def check_fork_executability(
        self,
        kalshi_ticker: str,
        poly_condition_id: str,
        poly_token_id: str,
        kalshi_side: str,  # 'YES' or 'NO'
        poly_side: str,     # 'YES' or 'NO'
        expected_roi: float,
        max_risk: float = None
    ) -> LimitsResult:
        """
        Проверить реальную исполнимость вилки
        
        Args:
            kalshi_ticker: Kalshi market ticker
            poly_condition_id: Polymarket conditionId
            poly_token_id: Polymarket tokenId для нужного исхода
            kalshi_side: Какую сторону покупаем на Kalshi
            poly_side: Какую сторону покупаем на Polymarket
            expected_roi: Ожидаемый ROI (в процентах)
            max_risk: Максимальный риск в USD
        
        Returns:
            LimitsResult с полной информацией об исполнимости
        """
        if max_risk is None:
            max_risk = self.MAX_RISK_DEFAULT
        
        # Получаем лимиты
        kalshi_limits = self.check_kalshi_limits(kalshi_ticker)
        poly_limits = self.check_polymarket_limits(poly_condition_id, poly_token_id)
        
        if not kalshi_limits or not poly_limits:
            return LimitsResult(
                is_executable=False,
                min_stake_usd=0,
                max_stake_usd=0,
                kalshi_min=0,
                kalshi_max=0,
                poly_min=0,
                poly_max=0,
                reason="Failed to fetch limits",
                classification="FAKE"
            )
        
        # Минимумы и максимумы
        kalshi_min = kalshi_limits['min_order_size']
        kalshi_max = kalshi_limits['max_order_size']
        poly_min = poly_limits['min_order_size']
        poly_max = poly_limits['max_order_size']
        
        # Эффективный минимум = максимум из двух минимумов
        effective_min = max(kalshi_min, poly_min)
        
        # Эффективный максимум = минимум из двух максимумов
        effective_max = min(kalshi_max, poly_max, max_risk)
        
        # Проверки
        if effective_min > max_risk:
            return LimitsResult(
                is_executable=False,
                min_stake_usd=effective_min,
                max_stake_usd=effective_max,
                kalshi_min=kalshi_min,
                kalshi_max=kalshi_max,
                poly_min=poly_min,
                poly_max=poly_max,
                reason=f"Min stake (${effective_min:.2f}) > max risk (${max_risk:.2f})",
                classification="TOO_RISKY"
            )
        
        if effective_max < effective_min:
            return LimitsResult(
                is_executable=False,
                min_stake_usd=effective_min,
                max_stake_usd=effective_max,
                kalshi_min=kalshi_min,
                kalshi_max=kalshi_max,
                poly_min=poly_min,
                poly_max=poly_max,
                reason=f"Max stake (${effective_max:.2f}) < min stake (${effective_min:.2f})",
                classification="TOO_SMALL"
            )
        
        if effective_min < 1.0:
            return LimitsResult(
                is_executable=False,
                min_stake_usd=effective_min,
                max_stake_usd=effective_max,
                kalshi_min=kalshi_min,
                kalshi_max=kalshi_max,
                poly_min=poly_min,
                poly_max=poly_max,
                reason=f"Min stake too small: ${effective_min:.2f}",
                classification="TOO_SMALL"
            )
        
        # Всё ОК - вилка исполнима!
        return LimitsResult(
            is_executable=True,
            min_stake_usd=effective_min,
            max_stake_usd=effective_max,
            kalshi_min=kalshi_min,
            kalshi_max=kalshi_max,
            poly_min=poly_min,
            poly_max=poly_max,
            reason=f"Executable: ${effective_min:.2f} - ${effective_max:.2f}",
            classification="EXECUTABLE"
        )

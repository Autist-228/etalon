#!/usr/bin/env python3
"""
Module 4 - Executor V2
НОВАЯ ЛОГИКА:
- MIN_FORK = 10%
- Poly stake = poly_min + $1 (max $2.50)
- Kalshi stake = подстраивается (max $5.00)
- Проверка fill статуса
- Отмена если не исполнилось
"""

import os
import sys
import json
import time
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module4.config import (
    DRY_RUN, MIN_FORK_PCT,
    MAX_TRADES_PER_SESSION, COOLDOWN_SECONDS, ORDER_FILL_TIMEOUT,
    EXECUTED_TRADES_FILE, TRADE_LOG_FILE,
    MAX_POLY_STAKE, MAX_KALSHI_STAKE, POLY_MIN_SHARES, TOTAL_FEE,
)
from module4.kalshi_client import KalshiClient
from module4.polymarket_client import PolymarketClient


@dataclass
class StakeCalc:
    """Расчёт ставок"""
    poly_stake: float
    kalshi_stake: float
    total_stake: float
    expected_return: float
    expected_profit: float
    actual_roi: float
    poly_contracts: float
    kalshi_contracts: float


@dataclass
class TradeResult:
    """Результат исполнения"""
    trade_id: str
    timestamp: str
    status: str  # 'success', 'partial', 'failed', 'skipped', 'dry_run'
    
    # Расчёты
    stakes: Optional[Dict]
    
    # Результаты исполнения
    kalshi_result: Dict
    poly_result: Dict
    
    # Фактические данные
    kalshi_filled: Optional[float] = None
    poly_filled: Optional[float] = None
    kalshi_fill_price: Optional[float] = None
    poly_fill_price: Optional[float] = None
    
    actual_roi: Optional[float] = None
    error: Optional[str] = None


class ExecutorV2:
    """Исполнитель вилок V2"""
    
    def __init__(self):
        self.kalshi = KalshiClient()
        self.polymarket = PolymarketClient()
        
        self.executed_trade_ids: Set[str] = set()
        self.trades_this_session = 0
        self.last_trade_time = 0
        
        self._load_executed_trades()
        
        print(f"\n{'='*60}")
        print(f"EXECUTOR V2 INITIALIZED")
        print(f"{'='*60}")
        print(f"  MIN_FORK:      {MIN_FORK_PCT}%")
        print(f"  STAKE LOGIC:   Poly = min + $1, Kalshi \u043f\u043e\u0434\u0441\u0442\u0440\u0430\u0438\u0432\u0430\u0435\u0442\u0441\u044f")
        print(f"  DRY_RUN:       {DRY_RUN}")
        if DRY_RUN:
            print(f"  >>> SAFE MODE: NO TRADES WILL BE EXECUTED <<<")
        print(f"{'='*60}")
        
        self._show_balances()
        print()
    
    def _show_balances(self):
        """Show Kalshi + Polymarket balances on startup"""
        print(f"\n  BALANCES:")
        
        kalshi_balance = self.kalshi.get_balance()
        if kalshi_balance is not None:
            print(f"    Kalshi:      ${kalshi_balance:.2f}")
        else:
            print(f"    Kalshi:      N/A (could not fetch)")
        
        poly_usdc = self.polymarket.get_usdc_balance()
        if poly_usdc is not None:
            print(f"    Polymarket:  ${poly_usdc:.6f} USDC")
        else:
            print(f"    Polymarket:  N/A (could not fetch)")
        
        if self.polymarket.w3 and self.polymarket.address:
            try:
                gas_wei = self.polymarket.w3.eth.get_balance(self.polymarket.address)
                gas_matic = gas_wei / 1e18
                print(f"    Gas (MATIC): {gas_matic:.4f}")
            except Exception as e:
                print(f"    Gas (MATIC): N/A ({e})")
        else:
            print(f"    Gas (MATIC): N/A (no web3)")
        
        print(f"    Wallet:      {self.polymarket.address or 'NOT SET'}")
        print(f"  {'='*56}")
    
    def _load_executed_trades(self):
        """Загрузить список исполненных сделок"""
        try:
            if os.path.exists(EXECUTED_TRADES_FILE):
                with open(EXECUTED_TRADES_FILE, 'r') as f:
                    data = json.load(f)
                    self.executed_trade_ids = set(data.get('trade_ids', []))
                print(f"📂 Loaded {len(self.executed_trade_ids)} executed trade IDs")
        except Exception as e:
            print(f"⚠️ Could not load executed trades: {e}")
    
    def _save_executed_trades(self):
        """Сохранить список исполненных сделок"""
        try:
            with open(EXECUTED_TRADES_FILE, 'w') as f:
                json.dump({
                    'trade_ids': list(self.executed_trade_ids),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️ Could not save executed trades: {e}")
    
    def _log_trade(self, result: TradeResult):
        """Записать результат в лог"""
        try:
            with open(TRADE_LOG_FILE, 'a') as f:
                f.write(json.dumps(asdict(result)) + '\n')
        except Exception as e:
            print(f"⚠️ Could not log trade: {e}")
    
    @staticmethod
    def generate_trade_id(fixture: str, market: str, line: Optional[float],
                          k_side: str, p_side: str) -> str:
        """Генерировать ID сделки"""
        key = f"{fixture}|{market}|{line}|{k_side}|{p_side}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def calculate_stakes(self, poly_price: float, kalshi_price: float,
                        poly_min: float) -> Optional[StakeCalc]:
        """
        ЛОГИКА РАСЧЁТА (с комиссией и лимитами):
        1. Poly stake = poly_min + $1.00 (но не больше MAX_POLY_STAKE)
        2. Kalshi stake = подстраивается (но не больше MAX_KALSHI_STAKE)
        3. Комиссия 3% вычитается из ожидаемого возврата
        4. Poly minimum 15 shares (платформенный лимит)
        """
        poly_stake = min(poly_min + 1.00, MAX_POLY_STAKE)
        
        poly_contracts = poly_stake / poly_price
        if poly_contracts < POLY_MIN_SHARES:
            print(f"  ⚠️ SKIP: Poly {poly_contracts:.1f} shares < min {POLY_MIN_SHARES} (platform limit)")
            return None
        
        expected_return_gross = poly_contracts
        expected_return = expected_return_gross * (1.0 - TOTAL_FEE)
        
        kalshi_contracts = round(expected_return_gross)
        kalshi_stake = kalshi_contracts * kalshi_price
        
        if kalshi_stake > MAX_KALSHI_STAKE:
            kalshi_contracts = int(MAX_KALSHI_STAKE / kalshi_price)
            kalshi_stake = kalshi_contracts * kalshi_price
            expected_return_gross = kalshi_contracts
            expected_return = expected_return_gross * (1.0 - TOTAL_FEE)
            poly_contracts = expected_return_gross
            poly_stake = poly_contracts * poly_price
        
        if kalshi_stake < 1.00:
            print(f"  ⚠️ SKIP: Kalshi stake ${kalshi_stake:.2f} < min $1.00 (platform limit)")
            return None
        if kalshi_contracts < 1:
            print(f"  ⚠️ SKIP: Kalshi contracts {kalshi_contracts} < 1")
            return None
        
        total_stake = poly_stake + kalshi_stake
        profit = expected_return - total_stake
        actual_roi = (profit / total_stake) * 100 if total_stake > 0 else 0
        
        return StakeCalc(
            poly_stake=poly_stake,
            kalshi_stake=kalshi_stake,
            total_stake=total_stake,
            expected_return=expected_return,
            expected_profit=profit,
            actual_roi=actual_roi,
            poly_contracts=poly_contracts,
            kalshi_contracts=kalshi_contracts
        )
    
    def can_execute(self, trade_id: str, fork_pct: float) -> Tuple[bool, str]:
        """Проверить можно ли исполнить"""
        if trade_id in self.executed_trade_ids:
            return False, "duplicate"
        
        if self.trades_this_session >= MAX_TRADES_PER_SESSION:
            return False, "max_trades_reached"
        
        now = time.time()
        if now - self.last_trade_time < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (now - self.last_trade_time)
            return False, f"cooldown_{remaining:.0f}s"
        
        if fork_pct < MIN_FORK_PCT:
            return False, f"below_threshold_{fork_pct:.2f}%"
        
        return True, "ok"
    
    def execute_fork(self, fork_result: Dict, link: Dict) -> Optional[TradeResult]:
        """
        Исполнить вилку
        
        Args:
            fork_result: из Module 3 track_2way()
            link: outcome_link из Module 2
        """
        fork = fork_result.get('fork')
        if not fork:
            return None
        
        # Извлекаем данные
        fixture = fork_result.get('fixture_title', 'Unknown')
        market = fork_result.get('market_type', '')
        line = fork_result.get('line_value')
        fork_pct = fork.fork_percent
        
        kalshi_side = fork.kalshi_side.lower()
        poly_side = fork.poly_side.lower()
        kalshi_price = fork.kalshi_price
        poly_price = fork.poly_price
        
        # Kalshi данные
        k_data = link.get('kalshi', {})
        kalshi_ticker = k_data.get('market_id', '')
        
        # Polymarket данные
        p_data = link.get('polymarket', {})
        token_ids = p_data.get('token_ids', [])
        if len(token_ids) < 2:
            return None
        poly_token_id = token_ids[0] if poly_side == 'yes' else token_ids[1]
        
        # Лимиты из Module 3.5
        limits = fork_result.get('limits')
        if not limits:
            print(f"  ⚠️ SKIP: No limits data from M3")
            return None
        if not limits.is_executable:
            print(f"  ⚠️ SKIP: Not executable - {limits.reason} ({limits.classification})")
            return None
        
        poly_min = limits.poly_min
        
        # Trade ID
        trade_id = self.generate_trade_id(fixture, market, line, kalshi_side, poly_side)
        
        # Проверка can_execute
        can_exec, reason = self.can_execute(trade_id, fork_pct)
        if not can_exec:
            print(f"  ⚠️ SKIP: {reason}")
            return None
        
        # Расчёт ставок
        stakes = self.calculate_stakes(poly_price, kalshi_price, poly_min)
        if not stakes:
            return None
        
        # Вывод расчёта
        print(f"\n{'='*70}")
        print(f"🎯 EXECUTING FORK: {trade_id}")
        print(f"{'='*70}")
        print(f"  Fixture:   {fixture}")
        print(f"  Market:    {market} ({line})")
        print(f"  Fork:      {fork_pct:+.2f}%")
        print(f"\n  📊 STAKE CALCULATION:")
        print(f"  Poly min:  ${poly_min:.2f}")
        print(f"  Poly stake: ${stakes.poly_stake:.2f} ({stakes.poly_contracts:.2f} contracts @ {poly_price:.1%})")
        print(f"  Kalshi stake: ${stakes.kalshi_stake:.2f} ({stakes.kalshi_contracts:.2f} contracts @ {kalshi_price:.1%})")
        print(f"  Total:     ${stakes.total_stake:.2f}")
        print(f"  Expected return: ${stakes.expected_return:.2f}")
        print(f"  Expected profit: ${stakes.expected_profit:+.2f}")
        print(f"  Actual ROI: {stakes.actual_roi:+.2f}%")
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        if DRY_RUN:
            print(f"\n  🔸 DRY RUN MODE - NOT EXECUTING")
            result = TradeResult(
                trade_id=trade_id,
                timestamp=timestamp,
                status='dry_run',
                stakes=asdict(stakes),
                kalshi_result={'would_execute': True},
                poly_result={'would_execute': True},
                actual_roi=stakes.actual_roi
            )
            
            # Помечаем как исполненный
            self.executed_trade_ids.add(trade_id)
            self._save_executed_trades()
            self.trades_this_session += 1
            self.last_trade_time = time.time()
            
            self._log_trade(result)
            return result
        
        # === LIVE EXECUTION ===
        print(f"\n  🔴 LIVE MODE - EXECUTING")
        
        # STEP 0: Balance check
        print(f"\n  💰 Step 0: Checking balances...")
        kalshi_balance = self.kalshi.get_balance()
        poly_balance = self.polymarket.get_usdc_balance()
        
        if kalshi_balance is not None and kalshi_balance < stakes.kalshi_stake:
            print(f"     ❌ ABORT: Kalshi balance ${kalshi_balance:.2f} < stake ${stakes.kalshi_stake:.2f}")
            return TradeResult(
                trade_id=trade_id, timestamp=timestamp, status='failed',
                stakes=asdict(stakes),
                kalshi_result={'error': 'insufficient_balance'},
                poly_result={'status': 'not_attempted'},
                error=f'Kalshi balance ${kalshi_balance:.2f} < stake ${stakes.kalshi_stake:.2f}'
            )
        if poly_balance is not None and poly_balance < stakes.poly_stake:
            print(f"     ❌ ABORT: Poly balance ${poly_balance:.2f} < stake ${stakes.poly_stake:.2f}")
            return TradeResult(
                trade_id=trade_id, timestamp=timestamp, status='failed',
                stakes=asdict(stakes),
                kalshi_result={'status': 'not_attempted'},
                poly_result={'error': 'insufficient_balance'},
                error=f'Poly balance ${poly_balance:.2f} < stake ${stakes.poly_stake:.2f}'
            )
        print(f"     Kalshi: ${kalshi_balance:.2f} (need ${stakes.kalshi_stake:.2f})")
        print(f"     Poly:   ${poly_balance:.2f} (need ${stakes.poly_stake:.2f})")
        print(f"     ✅ Balances OK")
        
        kalshi_result = {'status': 'not_attempted'}
        poly_result = {'status': 'not_attempted'}
        kalshi_order_id = None
        poly_order_id = None
        
        errors = []
        
        # STEP 1: Размещаем Kalshi ордер
        kalshi_contracts = int(stakes.kalshi_contracts)
        print(f"\n  📤 Step 1: Placing Kalshi order...")
        print(f"     Ticker: {kalshi_ticker}")
        print(f"     Side: {kalshi_side.upper()}")
        print(f"     Contracts: {kalshi_contracts}")
        print(f"     Price: {kalshi_price:.1%}")
        
        try:
            success, k_result = self.kalshi.place_order(
                ticker=kalshi_ticker,
                side=kalshi_side,
                contracts=kalshi_contracts,
                limit_price=kalshi_price
            )
            
            kalshi_result = k_result
            
            if success:
                kalshi_order_id = k_result.get('order_id')
                print(f"     ✅ Kalshi order placed: {kalshi_order_id}")
            else:
                errors.append(f"Kalshi order failed: {k_result.get('error', 'unknown')}")
                print(f"     ❌ Kalshi order failed: {k_result.get('error')}")
        except Exception as e:
            errors.append(f"Kalshi exception: {str(e)}")
            print(f"     ❌ Kalshi exception: {e}")
        
        # STEP 2: Размещаем Polymarket ордер
        poly_shares = stakes.poly_contracts
        print(f"\n  📤 Step 2: Placing Polymarket order...")
        print(f"     Token: {poly_token_id[:20]}...")
        print(f"     Side: BUY")
        print(f"     Shares: {poly_shares:.2f} (=${stakes.poly_stake:.2f} USDC)")
        print(f"     Price: {poly_price:.1%}")
        
        if not kalshi_order_id:
            print(f"     ⚠️ SKIP Poly: Kalshi order failed, not placing second leg")
            errors.append("Polymarket skipped: Kalshi order failed")
        else:
            try:
                success, p_result = self.polymarket.place_order(
                    token_id=poly_token_id,
                    side='BUY',
                    size=poly_shares,
                    price=poly_price
                )
            
                poly_result = p_result
                
                if success:
                    poly_order_id = p_result.get('order_id')
                    print(f"     ✅ Polymarket order placed: {poly_order_id}")
                else:
                    errors.append(f"Polymarket order failed: {p_result.get('error', 'unknown')}")
                    print(f"     ❌ Polymarket order failed: {p_result.get('error')}")
            except Exception as e:
                errors.append(f"Polymarket exception: {str(e)}")
                print(f"     ❌ Polymarket exception: {e}")
        
        # STEP 3: Проверка исполнения
        print(f"\n  ⏳ Step 3: Waiting for fills (timeout {ORDER_FILL_TIMEOUT}s)...")
        
        kalshi_filled = False
        poly_filled = False
        kalshi_fill_price = None
        poly_fill_price = None
        
        start_wait = time.time()
        
        while (time.time() - start_wait) < ORDER_FILL_TIMEOUT:
            # Проверяем Kalshi
            if kalshi_order_id and not kalshi_filled:
                k_status = self.kalshi.get_order_status(kalshi_order_id)
                if k_status:
                    filled_count = k_status.get('filled_count', 0)
                    if filled_count >= kalshi_contracts:
                        kalshi_filled = True
                        kalshi_fill_price = k_status.get('avg_price')
                        print(f"     ✅ Kalshi FILLED: {filled_count} contracts @ {kalshi_fill_price:.1%}")
            
            # Проверяем Polymarket
            if poly_order_id and not poly_filled:
                p_status = self.polymarket.get_order_status(poly_order_id)
                if p_status:
                    status = p_status.get('status', '')
                    if status == 'MATCHED':
                        poly_filled = True
                        poly_fill_price = p_status.get('price')
                        print(f"     ✅ Polymarket MATCHED @ {poly_fill_price:.1%}")
            
            # Оба исполнились - выходим
            if kalshi_filled and poly_filled:
                print(f"     ✅ Both legs filled in {time.time() - start_wait:.1f}s")
                break
            
            time.sleep(2)  # Проверяем каждые 2 секунды
        
        # STEP 4: Обработка результатов
        print(f"\n  📊 Step 4: Post-trade reconciliation...")
        
        final_status = 'unknown'
        
        if kalshi_filled and poly_filled:
            # SUCCESS: обе ноги исполнились
            final_status = 'success'
            print(f"     ✅ SUCCESS: Both legs filled")
            
            # Расчёт фактического ROI
            actual_return = min(stakes.expected_return, stakes.expected_return)  # Минимум от обеих ног
            actual_roi = ((actual_return - stakes.total_stake) / stakes.total_stake) * 100
            print(f"     💰 Actual ROI: {actual_roi:+.2f}%")
            
        elif not kalshi_filled and not poly_filled:
            # FAILED: ничего не исполнилось
            final_status = 'failed'
            errors.append("Both orders not filled within timeout")
            print(f"     ❌ FAILED: Both orders timed out")
            
            # Отменяем оба
            if kalshi_order_id:
                self.kalshi.cancel_order(kalshi_order_id)
                print(f"     🔴 Cancelled Kalshi order")
            if poly_order_id:
                self.polymarket.cancel_order(poly_order_id)
                print(f"     🔴 Cancelled Polymarket order")
        
        else:
            # PARTIAL: одна нога исполнилась, другая нет - LEG RISK!
            final_status = 'partial'
            errors.append(f"Leg risk: K={kalshi_filled}, P={poly_filled}")
            print(f"     ⚠️ PARTIAL FILL - LEG RISK!")
            print(f"        Kalshi: {'FILLED' if kalshi_filled else 'NOT FILLED'}")
            print(f"        Polymarket: {'FILLED' if poly_filled else 'NOT FILLED'}")
            
            # Отменяем не исполнившуюся
            if not kalshi_filled and kalshi_order_id:
                self.kalshi.cancel_order(kalshi_order_id)
                print(f"     🔴 Cancelled Kalshi order")
            if not poly_filled and poly_order_id:
                self.polymarket.cancel_order(poly_order_id)
                print(f"     🔴 Cancelled Polymarket order")
            
            # Пытаемся развернуть исполненную ногу (продать купленное)
            print(f"     🔄 Attempting to unwind filled leg...")
            if kalshi_filled and kalshi_order_id:
                try:
                    unwind_side = 'no' if kalshi_side == 'yes' else 'yes'
                    self.kalshi.place_order(
                        ticker=kalshi_ticker, side=unwind_side,
                        contracts=kalshi_contracts, limit_price=None
                    )
                    print(f"     🔄 Kalshi unwind order placed (market sell)")
                except Exception as e:
                    errors.append(f"Kalshi unwind failed: {e}")
                    print(f"     ❌ Kalshi unwind FAILED: {e}")
            if poly_filled and poly_order_id:
                try:
                    self.polymarket.place_order(
                        token_id=poly_token_id, side='SELL',
                        size=poly_shares, price=None
                    )
                    print(f"     🔄 Polymarket unwind order placed (market sell)")
                except Exception as e:
                    errors.append(f"Poly unwind failed: {e}")
                    print(f"     ❌ Poly unwind FAILED: {e}")
        
        # STEP 5: Создаём результат
        result = TradeResult(
            trade_id=trade_id,
            timestamp=timestamp,
            status=final_status,
            stakes=asdict(stakes),
            kalshi_result=kalshi_result,
            poly_result=poly_result,
            kalshi_filled=1.0 if kalshi_filled else 0.0,
            poly_filled=1.0 if poly_filled else 0.0,
            kalshi_fill_price=kalshi_fill_price,
            poly_fill_price=poly_fill_price,
            actual_roi=actual_roi if final_status == 'success' else None,
            error='; '.join(errors) if errors else None
        )
        
        # Помечаем как исполненный только если SUCCESS
        if final_status == 'success':
            self.executed_trade_ids.add(trade_id)
            self._save_executed_trades()
            self.trades_this_session += 1
            self.last_trade_time = time.time()
        
        self._log_trade(result)
        return result
    
    def process_opportunities(self, fork_results: List[Dict], links_map: Dict) -> List[TradeResult]:
        """Обработать список возможностей"""
        results = []
        
        for fork_result in fork_results:
            link_id = fork_result.get('link_id')
            if not link_id or link_id not in links_map:
                continue
            
            link = links_map[link_id]
            result = self.execute_fork(fork_result, link)
            
            if result:
                results.append(result)
                
                # Одна сделка за сессию
                if self.trades_this_session >= MAX_TRADES_PER_SESSION:
                    print(f"\n  ⚠️ Max trades per session reached ({MAX_TRADES_PER_SESSION})")
                    break
        
        return results
    
    def get_stats(self) -> Dict:
        """Получить статистику"""
        return {
            'trades_this_session': self.trades_this_session,
            'max_trades_per_session': MAX_TRADES_PER_SESSION,
            'total_executed': len(self.executed_trade_ids),
            'dry_run': DRY_RUN
        }

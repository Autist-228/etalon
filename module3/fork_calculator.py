#!/usr/bin/env python3
"""
Fork Calculator v3 - расчёт вилок с учётом alignment + 3-way режим

КЛЮЧЕВЫЕ ПРАВИЛА:
1. Бинарные рынки (alignment = SAME):
   YES на обеих платформах = один и тот же исход
   → Вилка: Kalshi YES + Poly NO или Kalshi NO + Poly YES
   
2. 3-way режим (футбол):
   Покупаем все 3 исхода (Win A, Draw, Win B) по лучшим ценам
   → Арбитраж если сумма < 1 - fees
"""

from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass

from .config import KALSHI_FEE, POLYMARKET_FEE, TOTAL_FEE


@dataclass
class ForkResult:
    """Результат расчёта вилки"""
    has_fork: bool
    fork_percent: float
    best_strategy: str
    kalshi_side: str
    poly_side: str
    kalshi_price: float
    poly_price: float
    total_cost: float
    gross_return: float
    net_return: float
    profit: float
    alignment: str


@dataclass
class ThreeWayResult:
    """Результат 3-way арбитража"""
    has_arbitrage: bool
    arbitrage_percent: float
    total_cost: float
    net_return: float
    profit: float
    strategy: Dict  # {outcome: {platform, price}}
    details: str


class ForkCalculator:
    """Калькулятор вилок между Kalshi и Polymarket с учётом alignment"""
    
    def __init__(self, kalshi_fee: float = KALSHI_FEE, poly_fee: float = POLYMARKET_FEE):
        self.kalshi_fee = kalshi_fee
        self.poly_fee = poly_fee
        self.total_fee = kalshi_fee + poly_fee
    
    def calculate_from_outcome_link(self, outcome_link: Dict, 
                                     kalshi_prices: Dict = None, 
                                     poly_prices: Dict = None) -> Optional[ForkResult]:
        """
        Рассчитать вилку из outcome_link с учётом alignment.
        
        Args:
            outcome_link: связка из outcome_matcher
            kalshi_prices: свежие цены Kalshi (опционально, иначе из link)
            poly_prices: свежие цены Polymarket (опционально, иначе из link)
        
        Returns:
            ForkResult с лучшей стратегией
        """
        alignment = outcome_link.get('alignment', 'SAME')
        
        # Получаем цены
        if kalshi_prices:
            k_yes = kalshi_prices.get('yes_ask') or kalshi_prices.get('yes_price') or kalshi_prices.get('yes_bid', 0.5)
            k_no = kalshi_prices.get('no_ask') or kalshi_prices.get('no_price') or kalshi_prices.get('no_bid', 0.5)
        else:
            k_data = outcome_link.get('kalshi', {})
            k_yes = k_data.get('yes_price', 0.5)
            k_no = k_data.get('no_price', 0.5)
        
        if poly_prices:
            p_yes = poly_prices.get('yes_price', 0.5)
            p_no = poly_prices.get('no_price', 0.5)
        else:
            p_data = outcome_link.get('polymarket', {})
            p_yes = p_data.get('yes_price', 0.5)
            p_no = p_data.get('no_price', 0.5)
        
        # Проверяем валидность цен
        if k_yes <= 0 or k_no <= 0 or p_yes <= 0 or p_no <= 0:
            return None
        
        return self.calculate_with_alignment(k_yes, k_no, p_yes, p_no, alignment)
    
    def calculate_with_alignment(self, k_yes: float, k_no: float, 
                                  p_yes: float, p_no: float, 
                                  alignment: str = 'SAME') -> Optional[ForkResult]:
        """
        Рассчитать вилку с учётом alignment.
        
        Args:
            k_yes: Kalshi YES price (0-1)
            k_no: Kalshi NO price (0-1)
            p_yes: Polymarket YES price (0-1)
            p_no: Polymarket NO price (0-1)
            alignment: 'SAME' или 'OPPOSITE'
        """
        strategies = []
        
        if alignment == 'SAME':
            # YES на обеих = один и тот же исход
            # Для вилки берём ПРОТИВОПОЛОЖНЫЕ стороны
            
            # Стратегия 1: Kalshi YES + Poly NO
            cost1 = k_yes + p_no
            net_return1 = 1.0 - self.total_fee
            profit1 = net_return1 - cost1
            fork_pct1 = (profit1 / cost1) * 100 if cost1 > 0 else -100
            
            strategies.append({
                'kalshi_side': 'YES',
                'poly_side': 'NO',
                'kalshi_price': k_yes,
                'poly_price': p_no,
                'cost': cost1,
                'net_return': net_return1,
                'profit': profit1,
                'fork_pct': fork_pct1,
            })
            
            # Стратегия 2: Kalshi NO + Poly YES
            cost2 = k_no + p_yes
            net_return2 = 1.0 - self.total_fee
            profit2 = net_return2 - cost2
            fork_pct2 = (profit2 / cost2) * 100 if cost2 > 0 else -100
            
            strategies.append({
                'kalshi_side': 'NO',
                'poly_side': 'YES',
                'kalshi_price': k_no,
                'poly_price': p_yes,
                'cost': cost2,
                'net_return': net_return2,
                'profit': profit2,
                'fork_pct': fork_pct2,
            })
            
        else:  # alignment == 'OPPOSITE'
            # YES на Kalshi = NO на Poly (по смыслу)
            # Для вилки берём ОДИНАКОВЫЕ стороны
            
            # Стратегия 1: Kalshi YES + Poly YES
            cost1 = k_yes + p_yes
            net_return1 = 1.0 - self.total_fee
            profit1 = net_return1 - cost1
            fork_pct1 = (profit1 / cost1) * 100 if cost1 > 0 else -100
            
            strategies.append({
                'kalshi_side': 'YES',
                'poly_side': 'YES',
                'kalshi_price': k_yes,
                'poly_price': p_yes,
                'cost': cost1,
                'net_return': net_return1,
                'profit': profit1,
                'fork_pct': fork_pct1,
            })
            
            # Стратегия 2: Kalshi NO + Poly NO
            cost2 = k_no + p_no
            net_return2 = 1.0 - self.total_fee
            profit2 = net_return2 - cost2
            fork_pct2 = (profit2 / cost2) * 100 if cost2 > 0 else -100
            
            strategies.append({
                'kalshi_side': 'NO',
                'poly_side': 'NO',
                'kalshi_price': k_no,
                'poly_price': p_no,
                'cost': cost2,
                'net_return': net_return2,
                'profit': profit2,
                'fork_pct': fork_pct2,
            })
        
        # Выбираем лучшую стратегию
        best = max(strategies, key=lambda x: x['fork_pct'])
        
        return ForkResult(
            has_fork=best['profit'] > 0,
            fork_percent=best['fork_pct'],
            best_strategy=f"Kalshi {best['kalshi_side']} ({best['kalshi_price']:.1%}) + Poly {best['poly_side']} ({best['poly_price']:.1%})",
            kalshi_side=best['kalshi_side'],
            poly_side=best['poly_side'],
            kalshi_price=best['kalshi_price'],
            poly_price=best['poly_price'],
            total_cost=best['cost'],
            gross_return=1.0,
            net_return=best['net_return'],
            profit=best['profit'],
            alignment=alignment,
        )
    
    # Обратная совместимость со старым API
    def calculate(self, kalshi_prices: Dict, poly_prices: Dict) -> Optional[ForkResult]:
        """Старый метод для обратной совместимости (alignment=SAME)"""
        if not kalshi_prices or not poly_prices:
            return None
        
        k_yes = kalshi_prices.get('yes_ask') or kalshi_prices.get('yes_bid', 0.5)
        k_no = kalshi_prices.get('no_ask') or kalshi_prices.get('no_bid', 0.5)
        p_yes = poly_prices.get('yes_price', 0.5)
        p_no = poly_prices.get('no_price', 0.5)
        
        if k_yes <= 0 or k_no <= 0 or p_yes <= 0 or p_no <= 0:
            return None
        
        return self.calculate_with_alignment(k_yes, k_no, p_yes, p_no, 'SAME')
    
    def calculate_simple(self, k_yes: float, k_no: float, p_yes: float, p_no: float) -> ForkResult:
        """Упрощённый расчёт (alignment=SAME)"""
        return self.calculate_with_alignment(k_yes, k_no, p_yes, p_no, 'SAME')
    
    def calculate_3way(self, outcomes: List[Dict]) -> Optional[ThreeWayResult]:
        """
        Рассчитать 3-way арбитраж для футбола.
        
        Args:
            outcomes: список из 3 исходов, каждый содержит:
                {
                    'outcome_key': 'TEAM_A_WIN' | 'DRAW' | 'TEAM_B_WIN',
                    'kalshi_yes': float,
                    'poly_yes': float
                }
        
        Returns:
            ThreeWayResult или None если нет 3 исходов
        """
        if len(outcomes) != 3:
            return None
        
        # Проверяем что есть все 3 исхода
        keys = set(o.get('outcome_key') for o in outcomes)
        required = {'TEAM_A_WIN', 'DRAW', 'TEAM_B_WIN'}
        if keys != required:
            return None
        
        # Для каждого исхода выбираем лучшую цену (минимальную)
        strategy = {}
        total_cost = 0
        
        for outcome in outcomes:
            key = outcome['outcome_key']
            k_price = outcome.get('kalshi_yes', 1.0)
            p_price = outcome.get('poly_yes', 1.0)
            
            if k_price <= p_price:
                best_price = k_price
                best_platform = 'kalshi'
            else:
                best_price = p_price
                best_platform = 'polymarket'
            
            strategy[key] = {
                'platform': best_platform,
                'price': best_price,
                'kalshi_price': k_price,
                'poly_price': p_price,
            }
            total_cost += best_price
        
        # Рассчитываем арбитраж
        net_return = 1.0 - self.total_fee
        profit = net_return - total_cost
        arbitrage_percent = (profit / total_cost) * 100 if total_cost > 0 else -100
        
        # Формируем описание стратегии
        details_parts = []
        for key in ['TEAM_A_WIN', 'DRAW', 'TEAM_B_WIN']:
            s = strategy[key]
            details_parts.append(f"{key}: {s['platform']} @ {s['price']*100:.1f}%")
        details = " | ".join(details_parts)
        
        return ThreeWayResult(
            has_arbitrage=profit > 0,
            arbitrage_percent=arbitrage_percent,
            total_cost=total_cost,
            net_return=net_return,
            profit=profit,
            strategy=strategy,
            details=details
        )


# Тест
if __name__ == "__main__":
    calc = ForkCalculator()
    
    print("="*60)
    print("FORK CALCULATOR v2 TEST")
    print("="*60)
    
    # Тест 1: alignment=SAME, реальные цены (должна быть небольшая отрицательная вилка)
    print("\nTest 1: SAME alignment (Draw market)")
    print("  Kalshi:     YES=30%, NO=70%")
    print("  Polymarket: YES=28.5%, NO=71.5%")
    result = calc.calculate_with_alignment(0.30, 0.70, 0.285, 0.715, 'SAME')
    if result:
        print(f"  → Fork: {result.fork_percent:+.2f}%")
        print(f"  → Strategy: {result.best_strategy}")
        print(f"  → Has fork: {result.has_fork}")
    
    # Тест 2: alignment=SAME, искусственная вилка
    print("\nTest 2: SAME alignment (artificial fork)")
    print("  Kalshi:     YES=40%, NO=60%")
    print("  Polymarket: YES=55%, NO=45%")
    result = calc.calculate_with_alignment(0.40, 0.60, 0.55, 0.45, 'SAME')
    if result:
        print(f"  → Fork: {result.fork_percent:+.2f}%")
        print(f"  → Strategy: {result.best_strategy}")
        print(f"  → Has fork: {result.has_fork}")
    
    # Тест 3: alignment=OPPOSITE
    print("\nTest 3: OPPOSITE alignment")
    print("  Kalshi:     YES=40%, NO=60%")
    print("  Polymarket: YES=55%, NO=45%")
    result = calc.calculate_with_alignment(0.40, 0.60, 0.55, 0.45, 'OPPOSITE')
    if result:
        print(f"  → Fork: {result.fork_percent:+.2f}%")
        print(f"  → Strategy: {result.best_strategy}")
        print(f"  → Has fork: {result.has_fork}")
    
    # Тест 4: Реальные данные из outcome_link
    print("\nTest 4: From outcome_link")
    outcome_link = {
        'alignment': 'SAME',
        'kalshi': {'yes_price': 0.30, 'no_price': 0.70},
        'polymarket': {'yes_price': 0.285, 'no_price': 0.715}
    }
    result = calc.calculate_from_outcome_link(outcome_link)
    if result:
        print(f"  → Fork: {result.fork_percent:+.2f}%")
        print(f"  → Strategy: {result.best_strategy}")

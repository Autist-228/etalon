#!/usr/bin/env python3
"""
SNAPSHOT MODEL
Слепок данных M1 для пакетной обработки в M2

Кросс-фильтрация: оставляем ТОЛЬКО события, которые есть на ОБЕИХ платформах.
Это убирает политику, крипту и прочее что есть только на одной платформе.
"""

from dataclasses import dataclass, asdict, field
from typing import Dict, List, Set, Tuple
from datetime import datetime, timezone
import re
from rapidfuzz import fuzz


def normalize_name(name: str) -> str:
    """Нормализация имени для сравнения.
    'Open Sud de France: Adrian Mannarino vs Arthur Gea' -> 'mannarino gea'
    'Mannarino vs Gea' -> 'mannarino gea'
    """
    name = name.lower()
    
    name = name.replace(' - more markets', '')
    name = name.replace(': total points', '').replace(': totals', '')
    name = name.replace(': spreads', '').replace(': spread', '')
    name = name.replace(': both teams to score', '')
    name = name.replace(': double doubles', '').replace(': triple doubles', '')
    name = name.replace(': steals', '').replace(': blocks', '')
    name = name.replace(': points', '').replace(': rebounds', '')
    name = name.replace(': assists', '').replace(': three pointers', '')
    name = name.replace(': anytime goalscorer', '').replace(': first goalscorer', '')
    name = name.replace(': anytime goal', '').replace(': first goal', '')
    name = name.replace(': winning margin', '').replace(': team totals', '')
    name = name.replace(' total maps', '').replace(' map 1', '').replace(' map 2', '').replace(' map 3', '')
    
    name = re.sub(r'^.*?:\s*', '', name)
    
    for prefix in ['(w)', '(m)', 'women\'s', 'men\'s', 'qualification:']:
        name = name.replace(prefix, '')
    
    name = re.sub(r'\s+vs\.?\s+', ' ', name)
    
    name = re.sub(r'\(bo\d+\)', '', name)
    name = re.sub(r'\(game\s*\d+\)', '', name)
    
    name = name.replace('-', ' ')
    
    name = re.sub(r'[^a-z0-9\s]', '', name)
    
    tokens = name.split()
    tokens = [t for t in tokens if len(t) > 1]
    
    return ' '.join(tokens)


def extract_key_tokens(name: str) -> Set[str]:
    """Извлечь ключевые токены (фамилии, названия команд)."""
    normalized = normalize_name(name)
    tokens = set(normalized.split())
    noise = {'vs', 'the', 'fc', 'sc', 'cf', 'cd', 'ca', 'de', 'la', 'el',
             'set', 'match', 'over', 'under', 'game', 'round', 'bo3', 'bo5',
             'map', 'total', 'spread', 'esports', 'gaming', 'team'}
    return tokens - noise


def events_match(kalshi_title: str, poly_title: str, threshold: int = 65) -> bool:
    """Проверить совпадают ли два события (Kalshi vs Polymarket).
    
    Использует комбинацию:
    1. Fuzzy match нормализованных имён
    2. Пересечение ключевых токенов (фамилии игроков / названия команд)
    """
    k_norm = normalize_name(kalshi_title)
    p_norm = normalize_name(poly_title)
    
    if k_norm == p_norm:
        return True
    
    ratio = fuzz.token_sort_ratio(k_norm, p_norm)
    if ratio >= threshold:
        return True
    
    k_tokens = extract_key_tokens(kalshi_title)
    p_tokens = extract_key_tokens(poly_title)
    
    if len(k_tokens) >= 2 and len(p_tokens) >= 2:
        overlap = k_tokens & p_tokens
        min_tokens = min(len(k_tokens), len(p_tokens))
        if min_tokens > 0 and len(overlap) / min_tokens >= 0.5:
            return True
    
    return False


KALSHI_SUFFIXES = [
    ': Total Points', ': Totals', ' Totals',
    ': Spreads', ': Spread', ' Spreads',
    ': Both Teams to Score', ' Both Teams to Score',
    ': Double Doubles', ': Triple Doubles',
    ': Steals', ': Blocks',
    ': Points', ': Rebounds', ': Assists', ': Three Pointers',
    ': Anytime Goalscorer', ': First Goalscorer',
    ': Anytime Goal', ': First Goal',
    ': Winning Margin', ': Team Totals',
    ' Total Maps', ' Map 1', ' Map 2', ' Map 3',
]


def cross_filter(kalshi_events: List[Dict], poly_events: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Кросс-фильтрация: оставить только события которые есть на ОБЕИХ платформах.
    
    Returns:
        (filtered_kalshi, filtered_poly) - только пересекающиеся события
    """
    if not kalshi_events or not poly_events:
        return [], []
    
    poly_base_titles = {}
    for pe in poly_events:
        title = pe['event_title']
        base = title.replace(' - More Markets', '')
        if base not in poly_base_titles:
            poly_base_titles[base] = []
        poly_base_titles[base].append(pe)
    
    kalshi_base_titles = {}
    for ke in kalshi_events:
        title = ke['event_title']
        base = title
        for suffix in KALSHI_SUFFIXES:
            base = base.replace(suffix, '')
        base = base.strip()
        if base not in kalshi_base_titles:
            kalshi_base_titles[base] = []
        kalshi_base_titles[base].append(ke)
    
    matched_kalshi_bases = set()
    matched_poly_bases = set()
    
    for k_base in kalshi_base_titles:
        for p_base in poly_base_titles:
            if events_match(k_base, p_base):
                matched_kalshi_bases.add(k_base)
                matched_poly_bases.add(p_base)
    
    filtered_kalshi = []
    for ke in kalshi_events:
        title = ke['event_title']
        base = title
        for suffix in KALSHI_SUFFIXES:
            base = base.replace(suffix, '')
        base = base.strip()
        if base in matched_kalshi_bases:
            filtered_kalshi.append(ke)
    
    filtered_poly = []
    for pe in poly_events:
        title = pe['event_title']
        base = title.replace(' - More Markets', '')
        if base in matched_poly_bases:
            filtered_poly.append(pe)
    
    return filtered_kalshi, filtered_poly


@dataclass
class Snapshot:
    """
    Слепок данных M1 (Listeners).
    
    Содержит:
    - Kalshi события в окне 6 часов (ТОЛЬКО пересекающиеся с Polymarket)
    - Polymarket события в окне 6 часов (ТОЛЬКО пересекающиеся с Kalshi)
    - Время создания слепка
    - Параметры окна
    - Статистика фильтрации
    
    M2 работает на этом слепке ПАКЕТНО!
    """
    snapshot_ts: str
    kalshi_events: List[Dict]
    poly_events: List[Dict]
    hours_ahead: int
    filters: Dict
    
    def to_dict(self):
        """Конвертация в dict"""
        return asdict(self)
    
    @property
    def kalshi_count(self):
        return len(self.kalshi_events)
    
    @property
    def poly_count(self):
        return len(self.poly_events)
    
    def __repr__(self):
        return f"Snapshot(ts={self.snapshot_ts}, kalshi={self.kalshi_count}, poly={self.poly_count})"


def create_snapshot(hours_ahead: int = 6, mode: str = 'all') -> Snapshot:
    """
    Создать слепок данных через M1.
    
    Args:
        hours_ahead: окно вперёд в часах
        mode: 'all' | 'live_only' | 'upcoming_only'
    
    Returns:
        Snapshot с отфильтрованными данными
    """
    from kalshi_listener import KalshiListener
    from polymarket_listener import PolymarketListener
    
    mode_label = {'all': 'live + upcoming', 'live_only': 'LIVE ONLY', 'upcoming_only': 'UPCOMING ONLY'}
    print(f"\n{'='*60}")
    print(f"  M1 SNAPSHOT (окно: {hours_ahead}ч, режим: {mode_label.get(mode, mode)})")
    print(f"{'='*60}")
    
    kalshi = KalshiListener(hours_ahead=hours_ahead)
    kalshi_result = kalshi.run()
    kalshi_raw = kalshi_result['events']
    
    poly = PolymarketListener(hours_ahead=hours_ahead)
    poly_result = poly.run()
    poly_raw = poly_result['events']
    
    if mode == 'live_only':
        kalshi_raw = [e for e in kalshi_raw if e.get('hours_left', 0) < 0]
        poly_raw = [e for e in poly_raw if e.get('hours_left', 0) < 0]
        print(f"   MODE live_only: Kalshi={len(kalshi_raw)}, Polymarket={len(poly_raw)}")
    elif mode == 'upcoming_only':
        kalshi_raw = [e for e in kalshi_raw if e.get('hours_left', 0) >= 0]
        poly_raw = [e for e in poly_raw if e.get('hours_left', 0) >= 0]
        print(f"   MODE upcoming_only: Kalshi={len(kalshi_raw)}, Polymarket={len(poly_raw)}")
    
    print(f"\n   ДО кросс-фильтрации: Kalshi={len(kalshi_raw)}, Polymarket={len(poly_raw)}")
    
    filtered_kalshi, filtered_poly = cross_filter(kalshi_raw, poly_raw)
    
    print(f"   ПОСЛЕ кросс-фильтрации: Kalshi={len(filtered_kalshi)}, Polymarket={len(filtered_poly)}")
    
    dropped_k = len(kalshi_raw) - len(filtered_kalshi)
    dropped_p = len(poly_raw) - len(filtered_poly)
    if dropped_k > 0 or dropped_p > 0:
        print(f"   Отброшено (нет на другой платформе): Kalshi={dropped_k}, Polymarket={dropped_p}")
    
    snapshot = Snapshot(
        snapshot_ts=datetime.now(timezone.utc).isoformat(),
        kalshi_events=filtered_kalshi,
        poly_events=filtered_poly,
        hours_ahead=hours_ahead,
        filters={
            'kalshi_raw': len(kalshi_raw),
            'poly_raw': len(poly_raw),
            'kalshi_after_xfilter': len(filtered_kalshi),
            'poly_after_xfilter': len(filtered_poly),
            'kalshi_dropped': dropped_k,
            'poly_dropped': dropped_p,
        }
    )
    
    print(f"\n   Слепок создан: {snapshot}")
    
    return snapshot

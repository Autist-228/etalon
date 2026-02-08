#!/usr/bin/env python3
"""
Scorer - подсчет score совпадения между событиями
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple
from .normalizer import TeamNormalizer


class EventScorer:
    """Подсчет score совпадения между событиями Kalshi и Polymarket"""
    
    # Веса для scoring
    WEIGHTS = {
        'time_exact': 30,      # Время совпадает ±30 мин
        'time_close': 20,      # Время совпадает ±60 мин
        'team1_match': 35,     # Team1 совпадает
        'team2_match': 35,     # Team2 совпадает
        'league_match': 10,    # Лига совпадает (бонус)
        'market_type_match': 5,  # Тип рынка совпадает (бонус)
    }
    
    # Пороги - ВАЖНО: требуем совпадение ОБЕИХ команд
    THRESHOLDS = {
        'auto_link': 90,       # Автоматический LINK (обе команды + время)
        'ask_llm': 70,         # Спросить LLM
        'skip': 70,            # Ниже этого - skip
    }
    
    def __init__(self, normalizer: TeamNormalizer = None):
        self.normalizer = normalizer or TeamNormalizer()
    
    def score(self, kalshi_event: Dict, poly_event: Dict) -> Tuple[int, Dict]:
        """
        Подсчитать score совпадения.
        
        Returns:
            (total_score, details_dict)
        """
        details = {
            'time_score': 0,
            'team1_score': 0,
            'team2_score': 0,
            'league_score': 0,
            'market_type_score': 0,
            'reasons': []
        }
        
        total = 0
        
        # 1. Время
        time_score, time_reason = self._score_time(kalshi_event, poly_event)
        details['time_score'] = time_score
        details['reasons'].append(time_reason)
        total += time_score
        
        # 2. Team1
        team1_score, team1_reason = self._score_team(
            kalshi_event.get('team1', ''),
            poly_event.get('team1', ''),
            'team1'
        )
        details['team1_score'] = team1_score
        details['reasons'].append(team1_reason)
        total += team1_score
        
        # 3. Team2
        team2_score, team2_reason = self._score_team(
            kalshi_event.get('team2', ''),
            poly_event.get('team2', ''),
            'team2'
        )
        details['team2_score'] = team2_score
        details['reasons'].append(team2_reason)
        total += team2_score
        
        # 4. Проверяем обратный порядок команд (home/away могут быть перепутаны)
        if team1_score < 20 and team2_score < 20:
            # Пробуем обратный порядок
            alt_team1_score, _ = self._score_team(
                kalshi_event.get('team1', ''),
                poly_event.get('team2', ''),
                'team1_alt'
            )
            alt_team2_score, _ = self._score_team(
                kalshi_event.get('team2', ''),
                poly_event.get('team1', ''),
                'team2_alt'
            )
            
            if alt_team1_score + alt_team2_score > team1_score + team2_score:
                # Обратный порядок лучше
                total = total - team1_score - team2_score + alt_team1_score + alt_team2_score
                details['team1_score'] = alt_team1_score
                details['team2_score'] = alt_team2_score
                details['reasons'].append("teams_swapped: true")
        
        # 5. Лига (бонус)
        league_score, league_reason = self._score_league(kalshi_event, poly_event)
        details['league_score'] = league_score
        details['reasons'].append(league_reason)
        total += league_score
        
        # 6. Тип рынка (бонус)
        market_score, market_reason = self._score_market_type(kalshi_event, poly_event)
        details['market_type_score'] = market_score
        details['reasons'].append(market_reason)
        total += market_score
        
        details['total'] = total
        
        return total, details
    
    def _score_time(self, kalshi: Dict, poly: Dict) -> Tuple[int, str]:
        """Оценка совпадения времени"""
        k_time = kalshi.get('start_time')
        p_time = poly.get('start_time')
        
        if not k_time or not p_time:
            return 0, "time: no data"
        
        # Приводим к datetime если строка
        if isinstance(k_time, str):
            try:
                k_time = datetime.fromisoformat(k_time.replace('Z', '+00:00'))
            except:
                return 0, "time: parse error kalshi"
        
        if isinstance(p_time, str):
            try:
                p_time = datetime.fromisoformat(p_time.replace('Z', '+00:00'))
            except:
                return 0, "time: parse error poly"
        
        # Разница в минутах
        diff = abs((k_time - p_time).total_seconds() / 60)
        
        if diff <= 30:
            return self.WEIGHTS['time_exact'], f"time: exact match ({diff:.0f} min)"
        elif diff <= 60:
            return self.WEIGHTS['time_close'], f"time: close match ({diff:.0f} min)"
        elif diff <= 180:  # 3 часа
            return 10, f"time: within 3h ({diff:.0f} min)"
        elif diff <= 360:  # 6 часов
            return 5, f"time: within 6h ({diff:.0f} min)"
        else:
            return 0, f"time: too far ({diff:.0f} min)"
    
    def _score_team(self, team1: str, team2: str, label: str) -> Tuple[int, str]:
        """Оценка совпадения команды"""
        if not team1 or not team2:
            return 0, f"{label}: no data"
        
        # Fuzzy match
        score = self.normalizer.fuzzy_match(team1, team2)
        
        # Более строгие пороги - требуем хорошее совпадение
        if score >= 85:
            return self.WEIGHTS['team1_match'], f"{label}: exact ({score}%)"
        elif score >= 75:
            return int(self.WEIGHTS['team1_match'] * 0.8), f"{label}: high ({score}%)"
        elif score >= 65:
            return int(self.WEIGHTS['team1_match'] * 0.5), f"{label}: medium ({score}%)"
        else:
            return 0, f"{label}: no match ({score}%)"
    
    def _score_league(self, kalshi: Dict, poly: Dict) -> Tuple[int, str]:
        """Оценка совпадения лиги"""
        k_league = kalshi.get('league', '').lower()
        p_league = poly.get('league', '').lower()
        
        if not k_league or not p_league:
            return 0, "league: no data"
        
        if k_league == 'unknown' or p_league == 'unknown':
            return 0, "league: unknown"
        
        if k_league == p_league:
            return self.WEIGHTS['league_match'], f"league: match ({k_league})"
        
        # Проверяем похожие лиги
        similar = {
            ('ncaa', 'college'): True,
            ('soccer', 'football'): True,
            ('esports', 'gaming'): True,
        }
        
        if (k_league, p_league) in similar or (p_league, k_league) in similar:
            return int(self.WEIGHTS['league_match'] * 0.5), f"league: similar ({k_league} vs {p_league})"
        
        return 0, f"league: no match ({k_league} vs {p_league})"
    
    def _score_market_type(self, kalshi: Dict, poly: Dict) -> Tuple[int, str]:
        """Оценка совпадения типа рынка"""
        k_type = kalshi.get('market_type', '').lower()
        p_type = poly.get('market_type', '').lower()
        
        if not k_type or not p_type:
            return 0, "market_type: no data"
        
        if k_type == p_type:
            return self.WEIGHTS['market_type_match'], f"market_type: match ({k_type})"
        
        return 0, f"market_type: no match ({k_type} vs {p_type})"
    
    def get_decision(self, score: int) -> str:
        """Получить решение по score"""
        if score >= self.THRESHOLDS['auto_link']:
            return 'auto_link'
        elif score >= self.THRESHOLDS['ask_llm']:
            return 'ask_llm'
        else:
            return 'skip'


# Тест
if __name__ == "__main__":
    scorer = EventScorer()
    
    # Тест 1: Идеальное совпадение
    kalshi1 = {
        'team1': 'warriors',
        'team2': 'timberwolves',
        'league': 'nba',
        'start_time': '2026-01-25T03:30:00+00:00',
        'market_type': 'winner'
    }
    poly1 = {
        'team1': 'golden state warriors',
        'team2': 'minnesota timberwolves',
        'league': 'nba',
        'start_time': '2026-01-25T03:30:00+00:00',
        'market_type': 'winner'
    }
    
    score1, details1 = scorer.score(kalshi1, poly1)
    print(f"Test 1 (perfect match): score={score1}, decision={scorer.get_decision(score1)}")
    print(f"  Details: {details1}")
    
    # Тест 2: Команды в обратном порядке
    poly2 = {
        'team1': 'minnesota timberwolves',
        'team2': 'golden state warriors',
        'league': 'nba',
        'start_time': '2026-01-25T03:30:00+00:00',
        'market_type': 'winner'
    }
    
    score2, details2 = scorer.score(kalshi1, poly2)
    print(f"\nTest 2 (teams swapped): score={score2}, decision={scorer.get_decision(score2)}")
    print(f"  Details: {details2}")
    
    # Тест 3: Разные события
    poly3 = {
        'team1': 'lakers',
        'team2': 'celtics',
        'league': 'nba',
        'start_time': '2026-01-25T05:00:00+00:00',
        'market_type': 'winner'
    }
    
    score3, details3 = scorer.score(kalshi1, poly3)
    print(f"\nTest 3 (different events): score={score3}, decision={scorer.get_decision(score3)}")
    print(f"  Details: {details3}")

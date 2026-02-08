#!/usr/bin/env python3
"""
Normalizer v2 - улучшенная нормализация названий команд + работа с aliases
"""

import json
import os
import re
from typing import Dict, Optional, List, Tuple
from rapidfuzz import fuzz, process


class TeamNormalizer:
    """Нормализация названий команд с использованием aliases и fuzzy matching"""
    
    def __init__(self, aliases_path: str = None):
        if aliases_path is None:
            aliases_path = os.path.join(os.path.dirname(__file__), 'aliases.json')
        
        self.aliases_path = aliases_path
        self.aliases = self._load_aliases()
        self._build_reverse_index()
    
    def _load_aliases(self) -> Dict:
        """Загрузить aliases из файла"""
        try:
            with open(self.aliases_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def _save_aliases(self):
        """Сохранить aliases в файл"""
        with open(self.aliases_path, 'w', encoding='utf-8') as f:
            json.dump(self.aliases, f, indent=2, ensure_ascii=False)
    
    def _build_reverse_index(self):
        """Построить обратный индекс: alias -> canonical name"""
        self.reverse_index = {}  # alias -> (league, canonical)
        self.league_index = {}   # league -> {alias -> canonical} - НОВОЕ: для league-aware поиска
        self.all_names = []  # все известные имена для fuzzy search
        
        for league, teams in self.aliases.items():
            if league not in self.league_index:
                self.league_index[league] = {}
            
            for canonical, aliases in teams.items():
                # Добавляем canonical
                canonical_clean = self._clean_name(canonical)
                self.reverse_index[canonical_clean] = (league, canonical)
                self.league_index[league][canonical_clean] = canonical
                self.all_names.append(canonical_clean)
                
                # Добавляем все aliases
                for alias in aliases:
                    alias_clean = self._clean_name(alias)
                    self.reverse_index[alias_clean] = (league, canonical)
                    self.league_index[league][alias_clean] = canonical
                    if alias_clean not in self.all_names:
                        self.all_names.append(alias_clean)
    
    def normalize(self, team_name: str, league: str = None) -> str:
        """
        Нормализовать название команды.
        Возвращает canonical name или очищенное оригинальное название.
        
        Args:
            team_name: название команды/города
            league: лига события (nba, nfl, nhl, mlb и т.д.) - если известна,
                    поиск будет СНАЧАЛА в этой лиге
        """
        if not team_name:
            return ''
        
        # Очищаем название
        cleaned = self._clean_name(team_name)
        
        # НОВОЕ: Если указана лига - ищем СНАЧАЛА в этой лиге
        if league and league in self.league_index:
            league_aliases = self.league_index[league]
            if cleaned in league_aliases:
                return league_aliases[cleaned]
            
            # Частичное совпадение в рамках лиги
            for alias, canonical in league_aliases.items():
                if len(alias) >= 4:
                    if alias in cleaned or cleaned in alias:
                        return canonical
        
        # Fallback: Пробуем найти в reverse_index (точное совпадение) - СТАРОЕ ПОВЕДЕНИЕ
        if cleaned in self.reverse_index:
            found_league, canonical = self.reverse_index[cleaned]
            return canonical
        
        # Пробуем найти частичное совпадение (название содержится в aliases)
        for alias, (found_league, canonical) in self.reverse_index.items():
            if len(alias) >= 4:
                if alias in cleaned or cleaned in alias:
                    return canonical
        
        # Пробуем fuzzy match для коротких названий
        if len(cleaned) <= 10 and self.all_names:
            matches = process.extract(cleaned, self.all_names, scorer=fuzz.ratio, limit=3)
            if matches and matches[0][1] >= 85:
                best_match = matches[0][0]
                if best_match in self.reverse_index:
                    _, canonical = self.reverse_index[best_match]
                    return canonical
        
        # Не нашли - возвращаем очищенное название
        return cleaned
    
    def _clean_name(self, name: str) -> str:
        """Очистить название команды - УЛУЧШЕННАЯ версия"""
        if not name:
            return ''
        
        name = name.lower().strip()
        
        # Убираем суффиксы типа ": Totals", ": Spreads", "- More Markets"
        name = re.sub(r'\s*:\s*(totals|spreads|both teams to score|points|goal).*', '', name)
        name = re.sub(r'\s*-\s*more markets.*', '', name)
        
        # Убираем даты и форматы типа "(BO3)", "(W)"
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', name)
        name = re.sub(r'\s*\d{4}-\d{2}-\d{2}.*', '', name)
        name = re.sub(r'\s*on\s+\d{4}-\d{2}-\d{2}.*', '', name)
        
        # Убираем "Will X win" паттерны
        name = re.sub(r'^will\s+', '', name)
        name = re.sub(r'\s+win(\s+|$).*', '', name)
        name = re.sub(r'\s+end\s+in\s+a\s+draw.*', '', name)
        
        # Убираем общие суффиксы/префиксы
        remove_patterns = [
            ' fc', ' bc', ' sc', ' ac', ' cf', ' sk', ' fk',
            'fc ', 'bc ', 'sc ', 'ac ', 'cf ', 'sk ', 'fk ',
            ' united', ' city', ' town', ' county',
            ' state', ' st.', ' st ',
            ' university', ' college',
            ' esports', ' gaming', ' team',
        ]
        
        for pattern in remove_patterns:
            name = name.replace(pattern, ' ')
        
        # Нормализуем специальные символы
        name = name.replace("'", "")
        name = name.replace("´", "")
        name = name.replace("-", " ")
        name = name.replace(".", " ")
        
        # Убираем "vs", "vs.", "at", "@"
        name = re.sub(r'\s+(vs\.?|at|@)\s+', ' ', name)
        
        # Убираем множественные пробелы
        name = ' '.join(name.split())
        
        return name.strip()
    
    def add_alias(self, league: str, canonical: str, alias: str):
        """Добавить новый alias (самообучение)"""
        if league not in self.aliases:
            self.aliases[league] = {}
        
        if canonical not in self.aliases[league]:
            self.aliases[league][canonical] = []
        
        alias_lower = alias.lower()
        if alias_lower not in self.aliases[league][canonical]:
            self.aliases[league][canonical].append(alias_lower)
            self._save_aliases()
            self._build_reverse_index()
    
    def fuzzy_match(self, name1: str, name2: str, league: str = None) -> int:
        """
        Fuzzy match двух названий - УЛУЧШЕННАЯ версия.
        Возвращает score 0-100.
        
        Args:
            name1: первое название
            name2: второе название
            league: лига для league-aware нормализации
        """
        if not name1 or not name2:
            return 0
        
        # Нормализуем оба названия (с учётом лиги если указана)
        n1 = self.normalize(name1, league=league)
        n2 = self.normalize(name2, league=league)
        
        # Если после нормализации одинаковые - 100%
        if n1 == n2:
            return 100
        
        # Проверяем содержание (одно в другом)
        if n1 in n2 or n2 in n1:
            shorter = n1 if len(n1) < len(n2) else n2
            if len(shorter) >= 4:
                return 95
        
        # Проверяем совпадение значимых слов
        words1 = set(w for w in n1.split() if len(w) >= 3)
        words2 = set(w for w in n2.split() if len(w) >= 3)
        
        if words1 and words2:
            common = words1 & words2
            if common:
                # Есть общие слова
                coverage = len(common) / min(len(words1), len(words2))
                if coverage >= 0.5:
                    return 90
        
        # Fuzzy ratio
        score = fuzz.ratio(n1, n2)
        
        # Token sort ratio - для случаев когда слова в разном порядке
        token_score = fuzz.token_sort_ratio(n1, n2)
        
        # Token set ratio - для частичных совпадений
        token_set_score = fuzz.token_set_ratio(n1, n2)
        
        # Берем максимум
        return max(score, token_score, token_set_score)
    
    def are_same_team(self, name1: str, name2: str, threshold: int = 75, league: str = None) -> bool:
        """
        Проверить, одна ли это команда.
        
        Args:
            name1: первое название
            name2: второе название
            threshold: порог совпадения (0-100)
            league: лига для league-aware нормализации
        """
        return self.fuzzy_match(name1, name2, league=league) >= threshold
    
    def extract_teams_from_title(self, title: str, league: str = None) -> Tuple[str, str]:
        """
        Извлечь названия команд из заголовка события.
        
        Args:
            title: заголовок события
            league: лига для league-aware нормализации
        """
        # Очищаем от суффиксов
        title = re.sub(r'\s*:\s*(totals|spreads|both teams to score|points|goal).*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*-\s*more markets.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*\([^)]*\)\s*', ' ', title)
        
        # Паттерны разделения команд
        patterns = [
            r'^(.+?)\s+at\s+(.+?)$',
            r'^(.+?)\s+vs\.?\s+(.+?)$',
            r'^(.+?)\s+@\s+(.+?)$',
        ]
        
        for pattern in patterns:
            match = re.match(pattern, title.strip(), re.IGNORECASE)
            if match:
                team1 = self._clean_name(match.group(1))
                team2 = self._clean_name(match.group(2))
                return self.normalize(team1, league=league), self.normalize(team2, league=league)
        
        return self._clean_name(title), ''
    
    @staticmethod
    def detect_league(event_ticker: str = None, slug: str = None, title: str = None) -> str:
        """
        Определить лигу события по ticker, slug или title.
        
        Args:
            event_ticker: Kalshi event ticker (например KXNBA...)
            slug: Polymarket slug (например nba-dal-mil-...)
            title: заголовок события
        
        Returns:
            Название лиги (nba, nfl, nhl, mlb и т.д.) или None
        """
        # Kalshi ticker
        if event_ticker:
            ticker_upper = event_ticker.upper()
            if 'NBA' in ticker_upper: return 'nba'
            if 'NFL' in ticker_upper: return 'nfl'
            if 'NHL' in ticker_upper: return 'nhl'
            if 'MLB' in ticker_upper: return 'mlb'
            if 'WNBA' in ticker_upper: return 'nba'  # WNBA тоже в NBA алиасах
            if 'NCAAB' in ticker_upper or 'CBB' in ticker_upper: return 'nba'  # College basketball
            if 'NCAAF' in ticker_upper or 'CFB' in ticker_upper: return 'nfl'  # College football
        
        # Polymarket slug
        if slug:
            slug_lower = slug.lower()
            if slug_lower.startswith('nba-'): return 'nba'
            if slug_lower.startswith('nfl-'): return 'nfl'
            if slug_lower.startswith('nhl-'): return 'nhl'
            if slug_lower.startswith('mlb-'): return 'mlb'
            if slug_lower.startswith('ahl-'): return 'nhl'  # AHL близко к NHL
            if slug_lower.startswith('epl-'): return 'epl'
            if slug_lower.startswith('laliga-'): return 'laliga'
            if slug_lower.startswith('seriea-'): return 'seriea'
            if slug_lower.startswith('bundesliga-'): return 'bundesliga'
            if slug_lower.startswith('ligue1-'): return 'ligue1'
            # Esports
            if slug_lower.startswith('lol-'): return 'esports_lol'
            if slug_lower.startswith('val-'): return 'esports_valorant'
            if slug_lower.startswith('cs2-') or slug_lower.startswith('csgo-'): return 'esports_cs'
            if slug_lower.startswith('dota2-') or slug_lower.startswith('dota-'): return 'esports_dota'
        
        # Title-based detection (fallback)
        if title:
            title_lower = title.lower()
            # NBA keywords
            if any(kw in title_lower for kw in ['mavericks', 'lakers', 'celtics', 'warriors', 'heat', 'bulls', 'raptors', 'nuggets', 'pelicans', 'spurs', 'suns', 'bucks', 'thunder', 'grizzlies', 'clippers', 'nets']):
                return 'nba'
            # NFL keywords
            if any(kw in title_lower for kw in ['cowboys', 'patriots', 'eagles', 'chiefs', 'bills', 'dolphins', 'broncos', 'saints', 'seahawks', 'rams', '49ers', 'packers', 'bears', 'ravens', 'steelers']):
                return 'nfl'
            # NHL keywords
            if any(kw in title_lower for kw in ['bruins', 'penguins', 'canucks', 'flames', 'oilers', 'maple leafs', 'canadiens', 'rangers', 'devils', 'kraken', 'blackhawks', 'panthers', 'lightning', 'ducks']):
                return 'nhl'
        
        return None


# Тест
if __name__ == "__main__":
    normalizer = TeamNormalizer()
    
    # Тесты нормализации
    tests = [
        ("Warriors", "nba"),
        ("Golden State Warriors", "nba"),
        ("GSW", "nba"),
        ("Timberwolves", "nba"),
        ("Minnesota Timberwolves", "nba"),
        ("Bruins", "nhl"),
        ("Boston Bruins", "nhl"),
        ("Laval Rocket", "ahl"),
        ("Calgary Wranglers", "ahl"),
    ]
    
    print("=== Тесты нормализации ===")
    for name, league in tests:
        normalized = normalizer.normalize(name, league)
        print(f"  {name} ({league}) -> {normalized}")
    
    print("\n=== Тесты fuzzy match ===")
    pairs = [
        ("Warriors", "Golden State Warriors"),
        ("Timberwolves", "Minnesota Timberwolves"),
        ("Bruins", "Boston Bruins"),
        ("Lakers", "Celtics"),
        ("Oklahoma", "Oklahoma Sooners"),
    ]
    
    for n1, n2 in pairs:
        score = normalizer.fuzzy_match(n1, n2)
        same = normalizer.are_same_team(n1, n2)
        print(f"  {n1} vs {n2}: score={score}, same={same}")

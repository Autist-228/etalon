#!/usr/bin/env python3
"""
Parser - извлечение team1, team2, sport, start_time из событий
"""

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


class EventParser:
    """Парсер событий Kalshi и Polymarket"""
    
    # Паттерны для определения лиги из тикера Kalshi
    KALSHI_LEAGUE_PATTERNS = {
        'KXNBA': 'nba',
        'KXNHL': 'nhl', 
        'KXNFL': 'nfl',
        'KXMLB': 'mlb',
        'KXAHL': 'ahl',
        'KXEPL': 'soccer',
        'KXNCAA': 'ncaa',
        'KXUFC': 'mma',
        'KXLOL': 'esports',
        'KXCOD': 'esports',
        'KXTENNIS': 'tennis',
    }
    
    # Ключевые слова для определения лиги из названия
    LEAGUE_KEYWORDS = {
        'nba': ['nba', 'warriors', 'lakers', 'celtics', 'nets', 'knicks', '76ers', 'bulls', 'cavaliers', 'heat', 'magic', 'wizards', 'hornets', 'hawks', 'pacers', 'bucks', 'pistons', 'raptors', 'nuggets', 'timberwolves', 'thunder', 'blazers', 'jazz', 'mavericks', 'rockets', 'grizzlies', 'pelicans', 'spurs', 'suns', 'kings', 'clippers'],
        'nhl': ['nhl', 'bruins', 'sabres', 'red wings', 'panthers', 'canadiens', 'senators', 'lightning', 'maple leafs', 'hurricanes', 'blue jackets', 'devils', 'islanders', 'rangers', 'flyers', 'penguins', 'capitals', 'blackhawks', 'avalanche', 'stars', 'wild', 'predators', 'blues', 'jets', 'ducks', 'coyotes', 'flames', 'oilers', 'sharks', 'kraken', 'canucks', 'golden knights'],
        'nfl': ['nfl', 'bills', 'dolphins', 'patriots', 'ravens', 'bengals', 'browns', 'steelers', 'texans', 'colts', 'jaguars', 'titans', 'broncos', 'chiefs', 'raiders', 'chargers', 'cowboys', 'giants', 'eagles', 'commanders', 'bears', 'lions', 'packers', 'vikings', 'falcons', 'saints', 'buccaneers', 'cardinals', 'rams', '49ers', 'seahawks'],
        'ahl': ['ahl', 'rocket', 'wranglers', 'marlies', 'wolf pack', 'bears', 'phantoms', 'checkers', 'penguins', 'thunderbirds', 'senators', 'crunch', 'comets', 'monsters', 'americans', 'admirals', 'wolves', 'icehogs', 'reign', 'roadrunners', 'silver knights', 'condors', 'barracuda', 'gulls', 'canucks', 'eagles', 'islanders', 'bruins'],
        'soccer': ['fc', 'united', 'city', 'real', 'barcelona', 'juventus', 'bayern', 'psg', 'chelsea', 'arsenal', 'liverpool', 'manchester', 'tottenham', 'lazio', 'lecce', 'sion', 'luzern', 'gilloise', 'leuven', 'racing club', 'gimnasia', 'belgrano', 'rosario'],
        'ncaa': ['ncaa', 'wildcats', 'bulldogs', 'tigers', 'eagles', 'bears', 'lions', 'panthers', 'cardinals', 'blue devils', 'tar heels', 'wolfpack', 'seminoles', 'gators', 'crimson tide', 'volunteers', 'razorbacks', 'aggies', 'longhorns', 'sooners', 'jayhawks', 'mountaineers', 'cyclones', 'cowboys', 'red raiders', 'horned frogs', 'mustangs', 'owls', 'cougars', 'huskies', 'ducks', 'beavers', 'bruins', 'trojans', 'sun devils', 'buffaloes', 'utes', 'lobos', 'aztecs', 'spartans', 'wolverines', 'buckeyes', 'nittany lions', 'hawkeyes', 'badgers', 'gophers', 'boilermakers', 'hoosiers', 'illini', 'cornhuskers', 'terrapins', 'scarlet knights'],
        'esports': ['valorant', 'counter-strike', 'cs:', 'lol:', 'dota', 'call of duty', 'cod:', 'league of legends', 'csgo', 'cs2'],
        'mma': ['ufc', 'mma', 'bellator'],
        'tennis': ['tennis', 'atp', 'wta', 'grand slam', 'australian open', 'french open', 'wimbledon', 'us open'],
    }
    
    def parse_kalshi_event(self, event: Dict) -> Dict:
        """Парсинг события Kalshi"""
        ticker = event.get('event_ticker', '')
        title = event.get('event_title', '')
        
        # Определяем лигу из тикера
        league = self._detect_league_from_ticker(ticker)
        if not league:
            league = self._detect_league_from_title(title)
        
        # Извлекаем команды
        team1, team2 = self._extract_teams(title)
        
        # Время начала (берем из первого рынка)
        start_time = self._parse_start_time_kalshi(event)
        
        # Тип рынка
        market_type = self._detect_market_type_kalshi(event)
        
        return {
            'source': 'kalshi',
            'original_title': title,
            'ticker': ticker,
            'team1': team1,
            'team2': team2,
            'league': league or 'unknown',
            'start_time': start_time,
            'market_type': market_type,
            'raw_event': event
        }
    
    def parse_polymarket_event(self, event: Dict) -> Dict:
        """Парсинг события Polymarket"""
        title = event.get('event_title', '')
        
        # Определяем лигу из названия
        league = self._detect_league_from_title(title)
        
        # Извлекаем команды
        team1, team2 = self._extract_teams(title)
        
        # Время начала
        start_time = self._parse_start_time_polymarket(event)
        
        # Тип рынка
        market_type = self._detect_market_type_polymarket(event)
        
        return {
            'source': 'polymarket',
            'original_title': title,
            'event_slug': event.get('event_slug', ''),
            'team1': team1,
            'team2': team2,
            'league': league or 'unknown',
            'start_time': start_time,
            'market_type': market_type,
            'raw_event': event
        }
    
    def _detect_league_from_ticker(self, ticker: str) -> Optional[str]:
        """Определить лигу из тикера Kalshi"""
        ticker_upper = ticker.upper()
        for prefix, league in self.KALSHI_LEAGUE_PATTERNS.items():
            if ticker_upper.startswith(prefix):
                return league
        return None
    
    def _detect_league_from_title(self, title: str) -> Optional[str]:
        """Определить лигу из названия события"""
        title_lower = title.lower()
        
        # Сначала проверяем явные маркеры
        if 'valorant:' in title_lower or 'valorant ' in title_lower:
            return 'esports'
        if 'counter-strike:' in title_lower or 'cs:' in title_lower:
            return 'esports'
        if 'lol:' in title_lower or 'league of legends' in title_lower:
            return 'esports'
        if 'dota' in title_lower:
            return 'esports'
        if 'call of duty' in title_lower or 'cod:' in title_lower:
            return 'esports'
        if 'ahl:' in title_lower:
            return 'ahl'
        
        # Потом по ключевым словам
        for league, keywords in self.LEAGUE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in title_lower:
                    return league
        
        return None
    
    def _extract_teams(self, title: str) -> Tuple[str, str]:
        """Извлечь названия команд из заголовка"""
        # Убираем суффиксы типа (W), (BO3), - More Markets
        title = re.sub(r'\s*\([^)]*\)\s*', ' ', title)
        title = re.sub(r'\s*-\s*More Markets.*', '', title)
        title = re.sub(r'\s*-\s*VCL.*', '', title)
        title = re.sub(r'\s*-\s*CCT.*', '', title)
        title = re.sub(r'\s*-\s*LEC.*', '', title)
        title = re.sub(r'\s*-\s*CBLOL.*', '', title)
        title = re.sub(r'\s*-\s*LCS.*', '', title)
        
        # Паттерны разделения команд
        patterns = [
            r'^(.+?)\s+at\s+(.+?)$',           # Team1 at Team2
            r'^(.+?)\s+vs\.?\s+(.+?)$',        # Team1 vs Team2 или Team1 vs. Team2
            r'^(.+?)\s+@\s+(.+?)$',            # Team1 @ Team2
        ]
        
        for pattern in patterns:
            match = re.match(pattern, title.strip(), re.IGNORECASE)
            if match:
                team1 = self._clean_team_name(match.group(1))
                team2 = self._clean_team_name(match.group(2))
                return team1, team2
        
        # Если не нашли паттерн, возвращаем весь заголовок как team1
        return self._clean_team_name(title), ''
    
    def _clean_team_name(self, name: str) -> str:
        """Очистить название команды"""
        # Убираем лишние пробелы
        name = ' '.join(name.split())
        # Убираем специальные символы в начале/конце
        name = name.strip('.:;,- ')
        # Приводим к lowercase
        name = name.lower()
        return name
    
    def _parse_start_time_kalshi(self, event: Dict) -> Optional[datetime]:
        """Парсинг времени начала для Kalshi"""
        # У Kalshi есть expected_expiration_time и close_time
        # Для матчей close_time обычно = время начала + длительность
        # Но нам нужно время начала, поэтому берем close_time и вычитаем ~3 часа для спорта
        
        # Пока берем end_time как приближение (потом можно уточнить)
        end_time = event.get('end_time_dt')
        if end_time:
            return end_time
        
        # Пробуем из raw_event
        raw = event.get('raw_event', event)
        markets = raw.get('markets', [])
        if markets:
            exp_time = markets[0].get('expected_expiration_time')
            if exp_time:
                try:
                    return datetime.fromisoformat(exp_time.replace('Z', '+00:00'))
                except:
                    pass
        
        return None
    
    def _parse_start_time_polymarket(self, event: Dict) -> Optional[datetime]:
        """Парсинг времени начала для Polymarket"""
        # У Polymarket есть endDate
        end_time = event.get('end_time_dt')
        if end_time:
            return end_time
        
        # Пробуем из строки
        end_str = event.get('end_time')
        if end_str:
            try:
                return datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            except:
                pass
        
        return None
    
    def _detect_market_type_kalshi(self, event: Dict) -> str:
        """Определить тип рынка Kalshi"""
        title = event.get('event_title', '').lower()
        ticker = event.get('event_ticker', '').upper()
        
        if 'spread' in title or 'SPREAD' in ticker:
            return 'spread'
        if 'total' in title or 'TOTAL' in ticker or 'over' in title:
            return 'total'
        if 'touchdown' in title or 'TD' in ticker:
            return 'prop'
        
        return 'winner'
    
    def _detect_market_type_polymarket(self, event: Dict) -> str:
        """Определить тип рынка Polymarket"""
        title = event.get('event_title', '').lower()
        
        if 'spread' in title or 'handicap' in title:
            return 'spread'
        if 'total' in title or 'over' in title or 'under' in title:
            return 'total'
        if 'more markets' in title:
            return 'other'
        
        return 'winner'


# Тест
if __name__ == "__main__":
    parser = EventParser()
    
    # Тест Kalshi
    kalshi_event = {
        'event_ticker': 'KXNBAGAME-25JAN26-GSWMIN',
        'event_title': 'Warriors at Timberwolves',
        'end_time_dt': datetime(2026, 1, 25, 3, 30, tzinfo=timezone.utc)
    }
    print("Kalshi:", parser.parse_kalshi_event(kalshi_event))
    
    # Тест Polymarket
    poly_event = {
        'event_title': 'Warriors vs. Timberwolves',
        'event_slug': 'warriors-vs-timberwolves',
        'end_time_dt': datetime(2026, 1, 25, 3, 30, tzinfo=timezone.utc)
    }
    print("Polymarket:", parser.parse_polymarket_event(poly_event))

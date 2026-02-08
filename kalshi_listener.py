#!/usr/bin/env python3
"""
Kalshi Live Games Listener - модуль для бота 322
Слушает LIVE спортивные игры на Kalshi - матчи на ближайшие 6 часов
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import json

KALSHI_API_URL = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiListener:
    def __init__(self, hours_ahead: int = 6):
        self.hours_ahead = hours_ahead
        self.games: List[Dict] = []
        
    def get_current_time(self) -> datetime:
        return datetime.now(timezone.utc)
    
    def parse_time(self, time_str: Optional[str]) -> Optional[datetime]:
        if not time_str:
            return None
        try:
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        except:
            return None
    
    def fetch_all_events(self) -> List[Dict]:
        """Получить все открытые события"""
        all_events = []
        cursor = None
        max_pages = 30
        
        for page in range(max_pages):
            url = f"{KALSHI_API_URL}/events?limit=200&with_nested_markets=true&status=open"
            if cursor:
                url += f"&cursor={cursor}"
            
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    break
                
                data = resp.json()
                events = data.get('events', [])
                all_events.extend(events)
                
                cursor = data.get('cursor')
                if not cursor or not events:
                    break
                    
            except Exception as e:
                print(f"  ❌ Kalshi error: {e}")
                break
        
        return all_events
    
    SPORT_DURATION = {
        'EPL': 2.0, 'LALIGA': 2.0, 'SERIEA': 2.0, 'BUNDESLIGA': 2.0,
        'EREDIVISIE': 2.0, 'SUPERLIG': 2.0, 'DENSUPERLIGA': 2.0,
        'EFLCHAMPIONSHIP': 2.0, 'LIGAPORTUGAL': 2.0, 'BELGIANPL': 2.0,
        'SWISSLEAGUE': 2.0, 'EKSTRAKLASA': 2.0, 'SLGREECE': 2.0,
        'HNL': 2.0, 'BRASILEIRO': 2.0, 'ARGPREMDIV': 2.0,
        'SCOTTISHPREM': 2.0, 'UCL': 2.0, 'UEL': 2.0, 'UECL': 2.0,
        'SIXNATIONS': 2.0, 'LIGAMX': 2.0, 'JLEAGUE': 2.0,
        'WC': 2.0, 'WCGROUPQUAL': 2.0, 'WCGROUPWIN': 2.0,
        'NBA': 2.5, 'NCAAMB': 2.5, 'NCAAWB': 2.5, 'BBL': 2.5,
        'BBSERIEA': 2.5, 'ACB': 2.5, 'BSL': 2.5, 'LNBELITE': 2.5,
        'ABA': 2.5, 'ARGLNB': 2.5, 'VTB': 2.5, 'GBL': 2.5,
        'KBL': 2.5, 'FIBAECUP': 2.5, 'FIBACHAMPLEAGUE': 2.5,
        'ATP': 2.5, 'WTA': 2.5, 'ATPCHALLENGER': 2.5, 'WTACHALLENGER': 2.5,
        'LOL': 1.5, 'LOLTOTAL': 3.0, 'VALORANT': 1.5, 'CS2': 1.0,
        'NHL': 2.5, 'KHL': 2.5, 'NCAAHOCKEY': 2.5,
        'NFL': 3.5, 'NCAAF': 3.5,
    }
    DEFAULT_DURATION = 2.5

    def _estimate_sport_duration(self, event_ticker: str) -> float:
        """Estimate match duration from ticker prefix."""
        import re
        m = re.match(r'KX([A-Z]+?)(?:GAME|MAP|MATCH|TOTAL|SPREAD|BTTS|MARGIN)-', event_ticker)
        if m:
            sport = m.group(1)
            if 'MAP' in event_ticker.upper().split('-')[0]:
                return min(self.SPORT_DURATION.get(sport, 1.0), 1.5)
            return self.SPORT_DURATION.get(sport, self.DEFAULT_DURATION)
        return self.DEFAULT_DURATION

    def filter_live_games(self, events: List[Dict]) -> List[Dict]:
        """Filter live sports games within the next N hours.
        
        Kalshi expected_expiration_time = when match ENDS (not starts!).
        We estimate start_time = exp_time - sport_duration.
        Keep events where estimated start is within [now - duration, now + hours_ahead].
        """
        now = self.get_current_time()
        cutoff_start = now + timedelta(hours=self.hours_ahead)
        
        filtered = []
        seen_events = set()
        
        for event in events:
            category = event.get('category', '')
            
            if category != 'Sports':
                continue
            
            event_ticker = event.get('event_ticker', '')
            
            if event_ticker in seen_events:
                continue
            
            title = event.get('title', '')
            markets = event.get('markets', [])
            
            if not markets:
                continue
            
            market = markets[0]
            exp_time = self.parse_time(market.get('expected_expiration_time'))
            close_time = self.parse_time(market.get('close_time'))
            end_time = exp_time or close_time
            
            if not end_time:
                continue
            
            duration_h = self._estimate_sport_duration(event_ticker)
            estimated_start = end_time - timedelta(hours=duration_h)
            
            is_live = estimated_start <= now < end_time
            is_upcoming = now <= estimated_start <= cutoff_start
            
            if is_live or is_upcoming:
                seen_events.add(event_ticker)
                hours_left = (estimated_start - now).total_seconds() / 3600
                
                # Собираем все рынки события
                event_markets = []
                for m in markets:
                    market_ticker = m.get('ticker', '')
                    ticker_upper = market_ticker.upper()
                    
                    if 'SPREAD' in ticker_upper:
                        market_type = 'SPREAD'
                    elif 'TOTAL' in ticker_upper or 'OVER' in ticker_upper:
                        market_type = 'TOTAL'
                    elif 'TD' in ticker_upper:
                        market_type = 'TOUCHDOWN'
                    else:
                        market_type = 'WINNER'
                    
                    event_markets.append({
                        'market_ticker': market_ticker,
                        'market_title': m.get('title', ''),
                        'market_type': market_type,
                        'yes_bid': m.get('yes_bid', 0),
                        'yes_ask': m.get('yes_ask', 0),
                        'no_bid': m.get('no_bid', 0),
                        'no_ask': m.get('no_ask', 0),
                        'last_price': m.get('last_price', 0),
                        'volume': m.get('volume', 0),
                        'yes_sub_title': m.get('yes_sub_title', ''),
                        'no_sub_title': m.get('no_sub_title', ''),
                    })
                
                # НОВОЕ: Извлечь участников из yes_sub_title
                participants = []
                for m in event_markets:
                    yes_sub = m.get('yes_sub_title', '').strip()
                    if yes_sub and yes_sub not in participants:
                        participants.append(yes_sub)
                
                filtered.append({
                    'source': 'kalshi',
                    'event_title': title,
                    'event_ticker': event_ticker,
                    'category': category,
                    'status': market.get('status', ''),
                    'end_time': end_time.isoformat(),
                    'end_time_dt': end_time,
                    'hours_left': hours_left,
                    'markets': event_markets,
                    'markets_count': len(event_markets),
                    'participants': participants,  # НОВОЕ!
                })
        
        filtered.sort(key=lambda x: x['hours_left'])
        return filtered
    
    def aggregate_fixtures(self, events: List[Dict]) -> Dict[str, Dict]:
        """Агрегация событий в fixtures (один матч = один fixture)"""
        fixtures = {}
        
        for event in events:
            title = event['event_title']
            
            base_title = title
            market_type = 'MONEYLINE'
            
            if ': Total Points' in title:
                base_title = title.replace(': Total Points', '')
                market_type = 'TOTAL'
            elif ': Totals' in title or ' Totals' in title:
                base_title = title.replace(': Totals', '').replace(' Totals', '')
                market_type = 'TOTAL'
            elif ': Spreads' in title or ' Spreads' in title:
                base_title = title.replace(': Spreads', '').replace(' Spreads', '')
                market_type = 'SPREAD'
            elif ': Spread' in title:
                base_title = title.replace(': Spread', '')
                market_type = 'SPREAD'
            elif ': Both Teams to Score' in title or ' Both Teams to Score' in title:
                base_title = title.replace(': Both Teams to Score', '').replace(' Both Teams to Score', '')
                market_type = 'BTTS'
            elif ': Double Doubles' in title:
                base_title = title.replace(': Double Doubles', '')
                market_type = 'PROPS_DOUBLE_DOUBLES'
            elif ': Triple Doubles' in title:
                base_title = title.replace(': Triple Doubles', '')
                market_type = 'PROPS_TRIPLE_DOUBLES'
            elif ': Points' in title:
                base_title = title.replace(': Points', '')
                market_type = 'PROPS_POINTS'
            elif ': Rebounds' in title:
                base_title = title.replace(': Rebounds', '')
                market_type = 'PROPS_REBOUNDS'
            elif ': Assists' in title:
                base_title = title.replace(': Assists', '')
                market_type = 'PROPS_ASSISTS'
            elif ': Three Pointers' in title:
                base_title = title.replace(': Three Pointers', '')
                market_type = 'PROPS_THREE_POINTERS'
            elif ': Steals' in title:
                base_title = title.replace(': Steals', '')
                market_type = 'PROPS_STEALS'
            elif ': Blocks' in title:
                base_title = title.replace(': Blocks', '')
                market_type = 'PROPS_BLOCKS'
            elif ': Anytime Goalscorer' in title or ': First Goalscorer' in title:
                base_title = title.replace(': Anytime Goalscorer', '').replace(': First Goalscorer', '')
                market_type = 'PROPS_GOALSCORER'
            elif ': Anytime Goal' in title or ': First Goal' in title:
                base_title = title.replace(': Anytime Goal', '').replace(': First Goal', '')
                market_type = 'PROPS_GOAL'
            elif ': Winning Margin' in title:
                base_title = title.replace(': Winning Margin', '')
                market_type = 'WINNING_MARGIN'
            elif ': Team Totals' in title:
                base_title = title.replace(': Team Totals', '')
                market_type = 'TEAM_TOTALS'
            elif ' Total Maps' in title or ' Map 1' in title or ' Map 2' in title or ' Map 3' in title:
                base_title = title.replace(' Total Maps', '').replace(' Map 1', '').replace(' Map 2', '').replace(' Map 3', '')
                market_type = 'ESPORTS_MAPS'
            
            base_title = base_title.strip()
            
            # Создаём или обновляем fixture
            if base_title not in fixtures:
                fixtures[base_title] = {
                    'fixture_title': base_title,
                    'start_time': event['end_time'],
                    'start_time_dt': event['end_time_dt'],
                    'hours_left': event['hours_left'],
                    'events': [],
                    'market_types': [],
                    'total_markets': 0
                }
            
            fixtures[base_title]['events'].append(event)
            fixtures[base_title]['market_types'].append(market_type)
            fixtures[base_title]['total_markets'] += event['markets_count']
        
        return fixtures
    
    def run(self) -> Dict:
        """Основной метод запуска"""
        print("\n🔍 Kalshi: загрузка событий...")
        all_events = self.fetch_all_events()
        print(f"   Всего событий: {len(all_events)}")
        
        live_games = self.filter_live_games(all_events)
        self.games = live_games
        
        # Подсчет рынков
        total_markets = sum(g['markets_count'] for g in live_games)
        
        # Агрегация в fixtures
        fixtures = self.aggregate_fixtures(live_games)
        
        return {
            'source': 'kalshi',
            'events': live_games,
            'events_count': len(live_games),
            'total_markets': total_markets,
            'fixtures': fixtures,
            'fixtures_count': len(fixtures)
        }


def main():
    listener = KalshiListener(hours_ahead=6)
    result = listener.run()
    
    print(f"\n{'='*80}")
    print(f"KALSHI РЕЗУЛЬТАТ")
    print(f"{'='*80}")
    print(f"Событий на ближайшие 6ч: {result['events_count']}")
    print(f"Всего рынков: {result['total_markets']}")
    
    if result['events']:
        print(f"\n📋 События:")
        for i, g in enumerate(result['events'][:20], 1):
            print(f"  {i:2}. {g['event_title'][:50]}... | {g['hours_left']:.1f}ч | {g['markets_count']} рынков")
    
    return result


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Polymarket Sports Listener - модуль для бота 322
Слушает LIVE спортивные события на Polymarket - матчи на ближайшие 6 часов
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import json

GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

# Tag IDs
SPORTS_TAG_ID = 1
GAME_BETS_TAG_ID = 100639  # Конкретные матчи


class PolymarketListener:
    def __init__(self, hours_ahead: int = 6):
        self.hours_ahead = hours_ahead
        self.events: List[Dict] = []
        self.markets_map: Dict[str, Dict] = {}
        
    def get_current_time(self) -> datetime:
        return datetime.now(timezone.utc)
    
    def parse_time(self, time_str: Optional[str]) -> Optional[datetime]:
        if not time_str:
            return None
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
        ]:
            try:
                dt = datetime.strptime(time_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        if '+' in time_str or time_str.endswith('Z'):
            try:
                return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            except:
                pass
        return None

    def get_game_start_time(self, event: Dict) -> Optional[datetime]:
        """Извлечь gameStartTime из маркетов события.
        Polymarket endDate = дедлайн закрытия маркета (через ~7 дней).
        gameStartTime = реальное время начала матча."""
        markets = event.get('markets', [])
        for m in markets:
            gst = m.get('gameStartTime')
            if gst:
                parsed = self.parse_time(gst)
                if parsed:
                    return parsed
        return None
    
    def fetch_sports_events(self, max_events: int = 3000) -> List[Dict]:
        """Получить спортивные события (game bets)"""
        all_events = []
        offset = 0
        
        while len(all_events) < max_events:
            params = {
                'tag_id': GAME_BETS_TAG_ID,
                'active': 'true',
                'closed': 'false',
                'limit': 100,
                'offset': offset
            }
            
            try:
                response = requests.get(
                    f"{GAMMA_API_URL}/events",
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                events = response.json()
                
                if not events:
                    break
                    
                all_events.extend(events)
                
                if len(events) < 100:
                    break
                    
                offset += 100
                    
            except Exception as e:
                print(f"  ❌ Polymarket error: {e}")
                break
        
        return all_events
    
    def filter_live_and_upcoming(self, events: List[Dict]) -> List[Dict]:
        """Фильтровать события - только live или в ближайшие N часов.
        
        ВАЖНО: Используем gameStartTime (реальное время начала матча),
        а НЕ endDate (дедлайн закрытия маркета на платформе, обычно +7 дней).
        
        Логика: берём события где gameStartTime попадает в окно [now - 3h, now + 6h].
        now - 3h нужен чтобы захватить матчи которые уже идут (начались до 3ч назад).
        """
        now = self.get_current_time()
        cutoff = now + timedelta(hours=self.hours_ahead)
        live_start = now - timedelta(hours=3)
        
        filtered = []
        skipped_no_gst = 0
        seen_slugs = set()
        
        for event in events:
            slug = event.get('slug', '')
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            
            game_start = self.get_game_start_time(event)
            
            if not game_start:
                skipped_no_gst += 1
                continue
            
            if live_start <= game_start <= cutoff:
                hours_left = (game_start - now).total_seconds() / 3600
                
                markets = event.get('markets', [])
                
                # Получаем цены из первого рынка (СТАРОЕ - НЕ ТРОГАЮ)
                outcomes = []
                prices = []
                if markets:
                    market = markets[0]
                    try:
                        outcomes = json.loads(market.get('outcomes', '[]')) if isinstance(market.get('outcomes'), str) else market.get('outcomes', [])
                        prices = json.loads(market.get('outcomePrices', '[]')) if isinstance(market.get('outcomePrices'), str) else market.get('outcomePrices', [])
                    except:
                        pass
                
                # НОВОЕ: Детальная информация по каждому market
                markets_detailed = []
                for market in markets:
                    try:
                        # Safe parse outcomes
                        outcomes_raw = market.get('outcomes', '[]')
                        if isinstance(outcomes_raw, str):
                            market_outcomes = json.loads(outcomes_raw)
                        else:
                            market_outcomes = outcomes_raw if isinstance(outcomes_raw, list) else []
                        
                        # Safe parse prices
                        prices_raw = market.get('outcomePrices', '[]')
                        if isinstance(prices_raw, str):
                            market_prices = json.loads(prices_raw)
                        else:
                            market_prices = prices_raw if isinstance(prices_raw, list) else []
                        
                        # Validate
                        if not market_outcomes or not market_prices:
                            markets_detailed.append({
                                'condition_id': market.get('conditionId'),
                                'valid': False,
                                'invalid_reason': 'empty_outcomes_or_prices'
                            })
                            continue
                        
                        if len(market_outcomes) != len(market_prices):
                            markets_detailed.append({
                                'condition_id': market.get('conditionId'),
                                'valid': False,
                                'invalid_reason': 'outcomes_prices_mismatch'
                            })
                            continue
                        
                        # Create outcome->price mapping
                        outcome_price_map = dict(zip(market_outcomes, market_prices))
                        
                        raw_tids = market.get('clobTokenIds', '[]')
                        if isinstance(raw_tids, str):
                            try:
                                clob_tids = json.loads(raw_tids)
                            except:
                                clob_tids = []
                        else:
                            clob_tids = raw_tids if isinstance(raw_tids, list) else []
                        
                        markets_detailed.append({
                            'condition_id': market.get('conditionId'),
                            'clob_token_ids': clob_tids,
                            'question': market.get('question', ''),
                            'outcomes': market_outcomes,
                            'prices': market_prices,
                            'outcome_price_map': outcome_price_map,
                            'valid': True
                        })
                        
                    except Exception as e:
                        markets_detailed.append({
                            'condition_id': market.get('conditionId'),
                            'valid': False,
                            'invalid_reason': f'parse_error: {str(e)}'
                        })
                
                filtered.append({
                    'source': 'polymarket',
                    'event_title': event.get('title', 'N/A'),
                    'event_slug': event.get('slug', ''),
                    'game_start_time': game_start.isoformat(),
                    'game_start_time_dt': game_start,
                    'end_time': game_start.isoformat(),
                    'end_time_dt': game_start,
                    'hours_left': hours_left,
                    'volume': event.get('volume', 0),
                    'liquidity': event.get('liquidity', 0),
                    'markets_count': len(markets),
                    'outcomes': outcomes,  # СТАРОЕ - оставляю
                    'prices': prices,      # СТАРОЕ - оставляю
                    'condition_ids': [m.get('conditionId') for m in markets if m.get('conditionId')],
                    'markets_detailed': markets_detailed  # НОВОЕ!
                })
        
        if skipped_no_gst > 0:
            print(f"   ⚠️  Пропущено {skipped_no_gst} событий без gameStartTime")
        
        filtered.sort(key=lambda x: x['hours_left'])
        return filtered
    
    def build_markets_map(self, events: List[Dict]):
        """Построить карту рынков для быстрого поиска"""
        for event in events:
            for cid in event.get('condition_ids', []):
                self.markets_map[cid] = {
                    'event_title': event.get('event_title'),
                    'event_slug': event.get('event_slug'),
                }
    
    def aggregate_fixtures(self, events: List[Dict]) -> Dict[str, Dict]:
        """Агрегация событий в fixtures (привязываем 'More Markets' к основному)"""
        fixtures = {}
        
        for event in events:
            title = event['event_title']
            
            # Убираем "- More Markets" для получения базового названия
            base_title = title.replace(' - More Markets', '')
            market_type = 'MORE_MARKETS' if '- More Markets' in title else 'MONEYLINE'
            
            # Создаём или обновляем fixture
            if base_title not in fixtures:
                fixtures[base_title] = {
                    'fixture_title': base_title,
                    'start_time': event['end_time'],
                    'start_time_dt': event['end_time_dt'],
                    'hours_left': event['hours_left'],
                    'events': [],
                    'market_types': [],
                    'total_volume': 0,
                    'total_liquidity': 0
                }
            
            fixtures[base_title]['events'].append(event)
            fixtures[base_title]['market_types'].append(market_type)
            fixtures[base_title]['total_volume'] += event.get('volume', 0)
            fixtures[base_title]['total_liquidity'] += event.get('liquidity', 0)
        
        return fixtures
    
    def run(self) -> Dict:
        """Основной метод запуска"""
        print("\n🔍 Polymarket: загрузка спортивных событий...")
        all_events = self.fetch_sports_events()
        print(f"   Всего спортивных событий: {len(all_events)}")
        
        live_events = self.filter_live_and_upcoming(all_events)
        self.events = live_events
        self.build_markets_map(live_events)
        
        # Агрегация в fixtures
        fixtures = self.aggregate_fixtures(live_events)
        
        return {
            'source': 'polymarket',
            'events': live_events,
            'total_count': len(live_events),
            'markets_map_size': len(self.markets_map),
            'fixtures': fixtures,
            'fixtures_count': len(fixtures)
        }


def main():
    listener = PolymarketListener(hours_ahead=6)
    result = listener.run()
    
    print(f"\n{'='*80}")
    print(f"POLYMARKET РЕЗУЛЬТАТ")
    print(f"{'='*80}")
    print(f"Спортивных событий на ближайшие 6ч: {result['total_count']}")
    
    if result['events']:
        print(f"\n📋 События:")
        for i, e in enumerate(result['events'][:20], 1):
            vol = f"${e['volume']:,.0f}" if e['volume'] else "N/A"
            print(f"  {i:2}. {e['event_title'][:50]}... | {e['hours_left']:.1f}ч | {vol}")
    
    return result


if __name__ == "__main__":
    main()

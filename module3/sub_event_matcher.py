#!/usr/bin/env python3
"""
M3 Sub-Event Matcher - Independent matching for Totals/Spreads/BTTS

M2 only handles WINNER/MONEYLINE markets. This module independently
extracts and matches sub-events (Totals, Spreads, Over/Under, BTTS)
directly from M1 snapshot data.

PIPELINE:
1. From M1 snapshot, get Kalshi events with TOTAL/SPREAD markets
2. For each, find the corresponding Polymarket event (by slug from M2 links)
3. Match Kalshi TOTAL markets to Polymarket Over/Under markets
4. Match by line value (e.g., Over 2.5 on Kalshi = Over 2.5 on Poly)
5. Create outcome_links compatible with M3 tracker

Uses Claude API only when line values are ambiguous.
"""

import os
import sys
import re
import json
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module3.prices_fetcher import PricesFetcher

GAMMA_API_URL = "https://gamma-api.polymarket.com"


def extract_line_value(title: str) -> Optional[float]:
    """Extract numeric line value from market title.
    
    Examples:
        'Over 2.5' -> 2.5
        'Under 220.5' -> 220.5  
        'Team A -3.5' -> -3.5
        'Team A +3.5' -> 3.5
    """
    m = re.search(r'[+-]?\d+\.?\d*', title)
    if m:
        return float(m.group())
    return None


def normalize_line_title(title: str) -> str:
    """Normalize a market title for comparison."""
    return re.sub(r'[^a-z0-9\s.+-]', '', title.lower()).strip()


class SubEventMatcher:
    """Independent sub-event matching for Totals/Spreads."""
    
    def __init__(self):
        self.fetcher = PricesFetcher()
        self.stats = {
            'kalshi_sub_events': 0,
            'poly_sub_events_found': 0,
            'matched_links': 0,
            'skipped_no_poly': 0,
            'skipped_no_line_match': 0,
        }
    
    def match_sub_events(self, snapshot, existing_links: List[Dict]) -> List[Dict]:
        """
        Extract and match sub-events from M1 snapshot.
        
        Args:
            snapshot: M1 Snapshot object
            existing_links: M2 outcome_links (to get slug mappings)
            
        Returns:
            List of outcome_links for sub-events (compatible with M3 tracker)
        """
        slug_map = self._build_slug_map(existing_links)
        
        kalshi_sub_events = self._extract_kalshi_sub_events(snapshot.kalshi_events)
        self.stats['kalshi_sub_events'] = len(kalshi_sub_events)
        
        if not kalshi_sub_events:
            return []
        
        sub_links = []
        
        for k_sub in kalshi_sub_events:
            fixture_title = k_sub['fixture_title']
            
            poly_slug = slug_map.get(fixture_title)
            if not poly_slug:
                for key in slug_map:
                    if self._titles_similar(key, fixture_title):
                        poly_slug = slug_map[key]
                        break
            
            if not poly_slug:
                self.stats['skipped_no_poly'] += 1
                continue
            
            poly_markets = self._fetch_poly_sub_markets(poly_slug)
            if not poly_markets:
                self.stats['skipped_no_poly'] += 1
                continue
            
            self.stats['poly_sub_events_found'] += 1
            
            for k_market in k_sub['markets']:
                matched = self._match_market_to_poly(k_market, poly_markets, fixture_title, poly_slug)
                if matched:
                    sub_links.append(matched)
                    self.stats['matched_links'] += 1
                else:
                    self.stats['skipped_no_line_match'] += 1
        
        self._print_stats()
        return sub_links
    
    def _build_slug_map(self, existing_links: List[Dict]) -> Dict[str, str]:
        """Build mapping from fixture_title -> polymarket slug using M2 links."""
        slug_map = {}
        for link in existing_links:
            fixture_id = link.get('fixture_id', '')
            poly_slug = link.get('polymarket', {}).get('slug', '')
            if fixture_id and poly_slug:
                slug_map[fixture_id] = poly_slug
        return slug_map
    
    def _extract_kalshi_sub_events(self, kalshi_events: List[Dict]) -> List[Dict]:
        """Extract Kalshi events that have TOTAL/SPREAD/BTTS markets."""
        sub_events = []
        seen_fixtures = {}
        
        for event in kalshi_events:
            title = event.get('event_title', '')
            markets = event.get('markets', [])
            
            base_title = title
            market_category = None
            
            if ': Total Points' in title:
                base_title = title.replace(': Total Points', '').strip()
                market_category = 'TOTAL'
            elif ': Totals' in title or ' Totals' in title:
                base_title = title.replace(': Totals', '').replace(' Totals', '').strip()
                market_category = 'TOTAL'
            elif ': Spreads' in title or ' Spreads' in title:
                base_title = title.replace(': Spreads', '').replace(' Spreads', '').strip()
                market_category = 'SPREAD'
            elif ': Spread' in title:
                base_title = title.replace(': Spread', '').strip()
                market_category = 'SPREAD'
            elif ': Both Teams to Score' in title:
                base_title = title.replace(': Both Teams to Score', '').strip()
                market_category = 'BTTS'
            else:
                for m in markets:
                    mt = m.get('market_type', '')
                    if mt in ('TOTAL', 'SPREAD'):
                        market_category = mt
                        break
            
            if not market_category:
                continue
            
            sub_markets = []
            for m in markets:
                ticker = m.get('market_ticker', '')
                m_title = m.get('market_title', '')
                yes_sub = m.get('yes_sub_title', '')
                no_sub = m.get('no_sub_title', '')
                
                line_val = extract_line_value(m_title) or extract_line_value(yes_sub)
                
                sub_markets.append({
                    'market_ticker': ticker,
                    'market_title': m_title,
                    'yes_sub_title': yes_sub,
                    'no_sub_title': no_sub,
                    'market_category': market_category,
                    'line_value': line_val,
                    'yes_bid': m.get('yes_bid', 0),
                    'yes_ask': m.get('yes_ask', 0),
                    'no_bid': m.get('no_bid', 0),
                    'no_ask': m.get('no_ask', 0),
                })
            
            if sub_markets:
                if base_title not in seen_fixtures:
                    seen_fixtures[base_title] = {
                        'fixture_title': base_title,
                        'original_title': title,
                        'markets': [],
                    }
                seen_fixtures[base_title]['markets'].extend(sub_markets)
        
        return list(seen_fixtures.values())
    
    def _fetch_poly_sub_markets(self, slug: str) -> List[Dict]:
        """Fetch Polymarket sub-markets (Over/Under, Spreads) for a given slug."""
        import requests
        
        try:
            base_slug = slug.replace('-more-markets', '').rstrip('-')
            
            for try_slug in [slug, base_slug, f"{base_slug}-more-markets"]:
                resp = requests.get(
                    f"{GAMMA_API_URL}/events",
                    params={'slug': try_slug},
                    timeout=10
                )
                
                if resp.status_code != 200:
                    continue
                
                events = resp.json()
                if not events:
                    continue
                
                sub_markets = []
                for event in events:
                    for market in event.get('markets', []):
                        question = market.get('question', '')
                        outcomes_raw = market.get('outcomes', '[]')
                        if isinstance(outcomes_raw, str):
                            outcomes = json.loads(outcomes_raw)
                        else:
                            outcomes = outcomes_raw or []
                        
                        prices_raw = market.get('outcomePrices', '[]')
                        if isinstance(prices_raw, str):
                            prices = json.loads(prices_raw)
                        else:
                            prices = prices_raw or []
                        
                        raw_tids = market.get('clobTokenIds', '[]')
                        if isinstance(raw_tids, str):
                            try:
                                token_ids = json.loads(raw_tids)
                            except:
                                token_ids = []
                        else:
                            token_ids = raw_tids if isinstance(raw_tids, list) else []
                        
                        is_over_under = sorted(outcomes) in [['Over', 'Under'], ['Under', 'Over']]
                        has_line = bool(extract_line_value(question))
                        
                        if is_over_under or has_line:
                            line_val = extract_line_value(question)
                            sub_markets.append({
                                'condition_id': market.get('conditionId', ''),
                                'question': question,
                                'outcomes': outcomes,
                                'prices': prices,
                                'token_ids': token_ids,
                                'line_value': line_val,
                                'is_over_under': is_over_under,
                                'slug': try_slug,
                            })
                
                if sub_markets:
                    return sub_markets
            
            return []
            
        except Exception as e:
            print(f"  Sub-event fetch error for {slug}: {e}")
            return []
    
    def _match_market_to_poly(self, k_market: Dict, poly_markets: List[Dict],
                               fixture_title: str, poly_slug: str) -> Optional[Dict]:
        """Match a single Kalshi TOTAL/SPREAD market to a Polymarket market."""
        k_line = k_market.get('line_value')
        k_category = k_market.get('market_category', '')
        k_title = k_market.get('market_title', '')
        
        best_match = None
        best_score = -1
        
        for pm in poly_markets:
            p_line = pm.get('line_value')
            p_question = pm.get('question', '')
            
            score = 0
            
            if k_line is not None and p_line is not None:
                if abs(k_line - p_line) < 0.01:
                    score += 100
                elif abs(k_line - p_line) < 0.6:
                    score += 50
                else:
                    continue
            
            if pm.get('is_over_under') and k_category == 'TOTAL':
                score += 20
            
            k_norm = normalize_line_title(k_title)
            p_norm = normalize_line_title(p_question)
            
            if 'over' in k_norm and 'over' in p_norm:
                score += 10
            if 'under' in k_norm and 'under' in p_norm:
                score += 10
            if 'spread' in k_norm and 'spread' in p_norm:
                score += 10
            
            if score > best_score:
                best_score = score
                best_match = pm
        
        if not best_match or best_score < 50:
            return None
        
        p_outcomes = best_match.get('outcomes', [])
        p_prices = best_match.get('prices', [])
        p_token_ids = best_match.get('token_ids', [])
        
        if len(p_outcomes) < 2 or len(p_prices) < 2:
            return None
        
        if p_outcomes[0] == 'Over':
            alignment = 'DIRECT'
        elif p_outcomes[0] == 'Under':
            alignment = 'FLIPPED'
        else:
            alignment = 'DIRECT'
        
        k_yes_ask = k_market.get('yes_ask', 50) / 100.0
        k_no_ask = k_market.get('no_ask', 50) / 100.0
        k_yes_bid = k_market.get('yes_bid', 50) / 100.0
        k_no_bid = k_market.get('no_bid', 50) / 100.0
        
        link_id = f"sub_{fixture_title}_{k_category}_{k_line}"
        
        link = {
            'id': link_id,
            'fixture_id': fixture_title,
            'sub_event': True,
            'market_type': k_category,
            'line_value': k_line,
            'alignment': alignment,
            'start_time': '',
            'kalshi': {
                'market_id': k_market.get('market_ticker', ''),
                'yes_outcome': k_market.get('yes_sub_title', 'Over'),
                'no_outcome': k_market.get('no_sub_title', 'Under'),
                'yes_price': k_yes_ask,
                'no_price': k_no_ask,
                'yes_bid': k_yes_bid,
                'no_bid': k_no_bid,
            },
            'polymarket': {
                'market_id': best_match.get('condition_id', ''),
                'slug': best_match.get('slug', poly_slug),
                'token_ids': p_token_ids,
                'question': best_match.get('question', ''),
                'yes_outcome': p_outcomes[0],
                'no_outcome': p_outcomes[1] if len(p_outcomes) > 1 else '?',
                'yes_price': float(p_prices[0]) if p_prices else 0.5,
                'no_price': float(p_prices[1]) if len(p_prices) > 1 else 0.5,
            }
        }
        
        return link
    
    def _titles_similar(self, title1: str, title2: str) -> bool:
        """Check if two fixture titles refer to the same match."""
        t1 = re.sub(r'[^a-z0-9\s]', '', title1.lower()).split()
        t2 = re.sub(r'[^a-z0-9\s]', '', title2.lower()).split()
        
        noise = {'vs', 'the', 'fc', 'sc', 'cf', 'de', 'la', 'el'}
        t1_clean = set(t for t in t1 if t not in noise and len(t) > 1)
        t2_clean = set(t for t in t2 if t not in noise and len(t) > 1)
        
        if not t1_clean or not t2_clean:
            return False
        
        overlap = t1_clean & t2_clean
        min_len = min(len(t1_clean), len(t2_clean))
        return len(overlap) / min_len >= 0.5 if min_len > 0 else False
    
    def _print_stats(self):
        """Print sub-event matching statistics."""
        print(f"\n{'='*60}")
        print(f"  SUB-EVENT MATCHER STATISTICS")
        print(f"{'='*60}")
        print(f"  Kalshi sub-events (Total/Spread/BTTS): {self.stats['kalshi_sub_events']}")
        print(f"  Poly sub-markets found:                {self.stats['poly_sub_events_found']}")
        print(f"  Matched sub-event links:               {self.stats['matched_links']}")
        print(f"  Skipped (no Poly event):               {self.stats['skipped_no_poly']}")
        print(f"  Skipped (no line match):               {self.stats['skipped_no_line_match']}")
        print(f"{'='*60}")

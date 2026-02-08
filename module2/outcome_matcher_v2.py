"""
М2: OUTCOME MATCHER V2 - AI-FIRST ARCHITECTURE

ФИЛОСОФИЯ:
- KALSHI = ИСТОЧНИК ИСТИНЫ (якорь!)
- Polymarket = только каталог для поиска
- Fail-safe > coverage (лучше skip чем 1 фейк-матч!)
- Claude = арбитр для ЛЮБОГО неоднозначного случая
- Sport detection = минимальные надёжные маркеры, unknown → пропускаем
- Sport mismatch → не блокируем, а спрашиваем Claude
- >10 кандидатов = автоматический SKIP

PIPELINE (ОТ KALSHI!):
1. Берём ОДНО событие Kalshi
2. Извлекаем sport из event_ticker (Kalshi — надёжный!)
3. Извлекаем участников из markets[].yes_sub_title
4. Ищем на Poly где есть ОБА участника + время ±8ч
5. Sport filter: мягкий! unknown → пропускаем, mismatch → Claude
6. Если > 10 кандидатов → SKIP
7. Если >1 кандидат ИЛИ sport mismatch → Claude: EXACT или NONE?
8. Post-check: оба участника есть в Poly?
9. ACCEPT или SKIP
"""

from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime
import anthropic
import os
import json
import re
from dotenv import load_dotenv

load_dotenv()

WEAK_WORDS = {
    'fc', 'sc', 'bc', 'cf', 'ac', 'dc', 'sk', 'fk', 'as', 'kk', 'jk',
    'sv', 'vfl', 'vfb', 'tsg', 'ogc', 'rc', 'rcd', 'ud', 'ca', 'cd',
    'ssc', 'ss', 'us', 'acf', 'cfc', 'afc', 'losc', 'bsc', 'hsc',
    'united', 'city', 'real', 'town', 'county',
    'university', 'college', 'state',
    'team', 'club', 'athletic', 'sport', 'sporting', 'national',
    'esports', 'gaming', 'e-sports',
    'saudi', 'israel',
    'jr', 'sr', 'ii', 'iii', 'iv',
    'basket', 'basquet', 'futbol',
    'jl', 'sbv', 'saski', 'nac',
    'ik', 'if', 'hk', 'bk', 'gf', 'hc',
    'hockey',
    'de', 'la', 'el', 'en', 'les', 'des', 'du', 'di', 'da', 'do',
    'belgrade', 'piraeus', 'dordogne', 'vitoria', 'gasteiz',
    'bresse',
    'izmir', 'istanbul', 'ankara',
}

SPELLING_VARIANTS = {
    'ittifaq': ['ettifaq'],
    'ettifaq': ['ittifaq'],
    'olympiakos': ['olympiacos'],
    'olympiacos': ['olympiakos'],
    'ittihad': ['ettihad'],
    'ettihad': ['ittihad'],
    'dynamo': ['dinamo'],
    'dinamo': ['dynamo'],
    'zenit': ['zenith'],
    'zenith': ['zenit'],
    'lokomotiv': ['lokomotiva'],
    'lokomotiva': ['lokomotiv'],
    'trabzonspor': ['trabzon'],
    'trabzon': ['trabzonspor'],
    'cska': ['cska moscow', 'cska moskva'],
    'spartak': ['spartac'],
    'spartac': ['spartak'],
    'juventus': ['juve'],
    'juve': ['juventus'],
    'internazionale': ['inter'],
    'borussia': ['bvb'],
    'bvb': ['borussia dortmund'],
    'munich': ['munchen', 'münchen'],
    'munchen': ['munich'],
    'hamburg': ['hamburger'],
    'hamburger': ['hamburg'],
    'timra': ['timraa'],
    'timraa': ['timra'],
    'frolunda': ['froelunda'],
    'froelunda': ['frolunda'],
    'lulea': ['luleaa'],
    'luleaa': ['lulea'],
    'brynas': ['brynaes'],
    'brynaes': ['brynas'],
    'orebro': ['oerebro'],
    'oerebro': ['orebro'],
    'farjestad': ['faerjestad'],
    'faerjestad': ['farjestad'],
    'djurgardens': ['djurgaarden', 'djurgarden'],
    'djurgaarden': ['djurgardens', 'djurgarden'],
    'djurgarden': ['djurgardens', 'djurgaarden'],
    'linkoping': ['linkoeping'],
    'linkoeping': ['linkoping'],
    'skelleftea': ['skellefteaa'],
    'skellefteaa': ['skelleftea'],
    'leksands': ['leksand'],
    'leksand': ['leksands'],
    'dn soopers': ['dn freecs', 'dn sooper'],
    'dn freecs': ['dn soopers'],
    'cordoba': ['córdoba'],
    'córdoba': ['cordoba'],
    'union': ['unión'],
    'unión': ['union'],
    'vicente': ['gil vicente', 'barcelos'],
    'nijmegen': ['nec'],
    'nec': ['nijmegen'],
    'caliente': ['tijuana'],
    'copenhagen': ['kobenhavn', 'koebenhavn'],
    'kobenhavn': ['copenhagen', 'koebenhavn'],
    'koebenhavn': ['copenhagen', 'kobenhavn'],
    'eindhoven': ['psv', 'psv eindhoven'],
    'psv': ['eindhoven', 'psv eindhoven'],
    'alkmaar': ['az', 'az alkmaar'],
    'az': ['alkmaar', 'az alkmaar'],
    'goztepe': ['goeztepe', 'goztepe izmir'],
    'goeztepe': ['goztepe', 'goztepe izmir'],
    'cologne': ['koln', 'koeln'],
    'koln': ['cologne', 'koeln'],
    'koeln': ['cologne', 'koln'],
}

ABBREVIATIONS = {
    'qpr': 'queens park rangers',
    'psg': 'paris saint germain',
    'bvb': 'borussia dortmund',
    'nufc': 'newcastle united',
    'mufc': 'manchester united',
    'mcfc': 'manchester city',
    'thfc': 'tottenham hotspur',
    'avfc': 'aston villa',
    'wba': 'west bromwich albion',
    'swfc': 'sheffield wednesday',
    'sufc': 'sheffield united',
    'bcfc': 'birmingham city',
    'afcb': 'bournemouth',
    'cpfc': 'crystal palace',
    'wwfc': 'wolverhampton wanderers',
    'nffc': 'nottingham forest',
    'ga eagles': 'go ahead eagles',
    'psv': 'psv eindhoven',
    'az': 'az alkmaar',
}

def normalize_team_name(name: str) -> str:
    """Normalize team name for comparison"""
    if not name:
        return ""
    name = name.lower().strip()
    # Remove common suffixes
    name = re.sub(r'\s+(w|women)$', '', name)  # Women's teams
    name = re.sub(r'\s+(m|men)$', '', name)    # Men's teams
    return name

def extract_strong_tokens(name: str) -> List[str]:
    """
    Extract strong tokens (non-mascot, non-filler words)
    Слабые: redhawks, waves, bulldogs, wildcats, fc, united, city
    Сильные: seattle, pepperdine, northwestern
    """
    MASCOTS = {
        'redhawks', 'waves', 'bulldogs', 'wildcats', 'tigers', 'eagles',
        'bears', 'lions', 'panthers', 'cougars', 'falcons', 'hawks',
        'bruins', 'spartans', 'trojans', 'aggies', 'cowboys', 'broncos',
        'mountaineers', 'buffaloes', 'ducks', 'beavers', 'huskies',
        'pilots', 'toreros', 'gaels', 'roadrunners', 'reign', 'gulls',
        'barracuda', 'firebirds', 'knights', 'jackrabbits', 'governors',
        'bisons', 'sooners', 'sun', 'devils', 'utes', 'scarlet', 'lobos'
    }
    
    tokens = re.findall(r'\b\w+\b', name.lower())
    strong = [t for t in tokens if t not in MASCOTS and t not in WEAK_WORDS and len(t) > 2]
    return strong if strong else tokens  # Fallback to all if no strong

def find_poly_outcome_for_team(kalshi_team: str, poly_outcomes: List[str]) -> Optional[int]:
    """
    Find which poly outcome matches kalshi_team
    Returns index or None
    
    Matching by strong tokens:
    - "Seattle" matches "Seattle Redhawks"
    - "Pepperdine" matches "Pepperdine Waves"
    - "Hailey Baptiste" matches "Baptiste" (последний токен = фамилия)
    """
    k_strong = extract_strong_tokens(kalshi_team)
    
    for i, p_outcome in enumerate(poly_outcomes):
        p_strong = extract_strong_tokens(p_outcome)
        
        if all(any(kt in pt or pt in kt for pt in p_strong) for kt in k_strong):
            return i
    
    if len(k_strong) >= 2:
        k_last = k_strong[-1]
        for i, p_outcome in enumerate(poly_outcomes):
            p_strong = extract_strong_tokens(p_outcome)
            if any(k_last in pt or pt in k_last for pt in p_strong):
                other_indices = [j for j in range(len(poly_outcomes)) if j != i]
                other_match = False
                for j in other_indices:
                    oj_strong = extract_strong_tokens(poly_outcomes[j])
                    if any(k_last in ot or ot in k_last for ot in oj_strong):
                        other_match = True
                        break
                if not other_match:
                    return i
    
    return None

def align_poly_prices(kalshi_yes_team: str, poly_outcomes: List[str], 
                     poly_prices: List[float]) -> Optional[Tuple[float, float, str]]:
    """
    Align Poly prices to Kalshi YES/NO
    
    Returns: (yes_price_aligned, no_price_aligned, alignment) or None
    """
    if len(poly_outcomes) != 2 or len(poly_prices) != 2:
        return None
    
    # Find which poly outcome matches kalshi_yes_team
    yes_index = find_poly_outcome_for_team(kalshi_yes_team, poly_outcomes)
    
    if yes_index is None:
        return None  # Can't determine
    
    # Calculate alignment
    yes_price = poly_prices[yes_index]
    no_price = poly_prices[1 - yes_index]
    
    alignment = "DIRECT" if yes_index == 0 else "FLIPPED"
    
    return (yes_price, no_price, alignment)

UNICODE_MANUAL_MAP = {
    'ø': 'o', 'æ': 'ae', 'ð': 'd', 'þ': 'th',
    'ł': 'l', 'ß': 'ss', 'đ': 'd',
    'Ø': 'o', 'Æ': 'ae', 'Ð': 'd', 'Þ': 'th',
    'Ł': 'l', 'Đ': 'd',
}

def _apply_unicode_map(text: str) -> str:
    return ''.join(UNICODE_MANUAL_MAP.get(c, c) for c in text)

def clean_token(token: str) -> str:
    """Clean token from punctuation for comparison"""
    import unicodedata
    text = token.lower()
    text = _apply_unicode_map(text)
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = unicodedata.normalize('NFC', text)
    return re.sub(r'[.\'\-]', '', text)

def normalize_text(text: str) -> str:
    """Normalize entire text for matching (remove punctuation, lowercase)"""
    import unicodedata
    text = text.lower()
    text = _apply_unicode_map(text)
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'[.\']', '', text)
    return text

def token_matches_in_text(token: str, text: str) -> bool:
    """
    Check if token matches in text with WORD BOUNDARIES + special variants
    
    HANDLES:
    - Hyphens: "Al-Ittihad" → checks joined AND split parts
    - Spelling variants: "Ittifaq" also checks "Ettifaq"
    - Special cases: "st" → st/saint/state, "mt" → mt/mount
    """
    cleaned = clean_token(token)
    text_norm = normalize_text(text)
    
    if cleaned == 'st':
        variants = ['st', 'saint', 'state']
        for variant in variants:
            pattern = r'\b' + re.escape(variant) + r'\b'
            if re.search(pattern, text_norm):
                return True
        return False
    
    if cleaned == 'mt':
        variants = ['mt', 'mount']
        for variant in variants:
            pattern = r'\b' + re.escape(variant) + r'\b'
            if re.search(pattern, text_norm):
                return True
        return False
    
    pattern = r'\b' + re.escape(cleaned) + r'\b'
    if re.search(pattern, text_norm):
        return True
    
    if cleaned in SPELLING_VARIANTS:
        for variant in SPELLING_VARIANTS[cleaned]:
            pattern = r'\b' + re.escape(variant) + r'\b'
            if re.search(pattern, text_norm):
                return True
    
    if '-' in token:
        parts = [p.lower() for p in token.split('-') if len(p) >= 2]
        if parts and all(_token_or_variant_in_text(p, text_norm) for p in parts):
            return True
    
    return False


def _token_or_variant_in_text(tok: str, text_norm: str) -> bool:
    """Check token OR its spelling variants in text"""
    if re.search(r'\b' + re.escape(tok) + r'\b', text_norm):
        return True
    if tok in SPELLING_VARIANTS:
        for variant in SPELLING_VARIANTS[tok]:
            if re.search(r'\b' + re.escape(variant) + r'\b', text_norm):
                return True
    return False


class OutcomeMatcherV2:
    """М2 V2 - Kalshi-first, fail-safe architecture"""
    
    def __init__(self):
        # Load .env
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except:
            pass
        
        # Anthropic
        api_key = os.getenv('ANTHROPIC_API_KEY')
        self.anthropic = anthropic.Anthropic(api_key=api_key) if api_key else None
        
        # Stats
        self.stats = {
            'total_kalshi_events': 0,
            'accepted': 0,
            'skipped_no_participants': 0,
            'skipped_props': 0,
            'skipped_no_candidates': 0,
            'skipped_too_many_candidates': 0,
            'skipped_claude_none': 0,
            'skipped_postcheck': 0,
            'claude_calls': 0,
            'avg_candidates': [],
        }
        
        self.ticker_to_sport = {
            'KXSCOTTISHPREM': 'football',
            'KXDFBPOKAL': 'football',
            'KXPREMIERLEAGUE': 'football',
            'KXEPL': 'football',
            'KXBUNDESLIGA': 'football',
            'KXLALIGA': 'football',
            'KXSERIEA': 'football',
            'KXLIGUE': 'football',
            'KXEREDIVISIE': 'football',
            'KXEFLCHAMPIONSHIP': 'football',
            'KXDENSUPERLIGA': 'football',
            'KXSAUDIPL': 'football',
            'KXLIGAMX': 'football',
            'KXALEAGUE': 'football',
            'KXLIGAPORTUGAL': 'football',
            'KXARGPREMDIV': 'football',
            'KXMLS': 'football',
            'KXCHAMPIONSLEAGUE': 'football',
            'KXEUROPALEAGUE': 'football',
            'KXCONFLEAGUE': 'football',
            'KXCOPAAMERIC': 'football',
            'KXWWC': 'football',
            'KXSUPERLIG': 'football',
            'KXALLSVENSKAN': 'football',
            'KXEKSTRAKLASA': 'football',
            'KXJUPILERLEAGUE': 'football',
            'KXSWISSSUPERLEAGUE': 'football',
            'KXCOPPAITALIA': 'football',
            'KXFACUP': 'football',
            'KXLEAGUECUP': 'football',
            'KXCOPAREY': 'football',
            'KXBRASILEIRO': 'football',
            'KXLIGAPRO': 'football',
            'KXSERIEB': 'football',
            'KXLIGUE2': 'football',
            'KXSEGUNDADIV': 'football',
            'KX2BUNDESLIGA': 'football',
            'KXEUROCUP': 'basketball',
            'KXEUROLEAGUE': 'basketball',
            'KXLNBELITE': 'basketball',
            'KXNCAAMB': 'basketball',
            'KXNCAAB': 'basketball',
            'KXNCAAWB': 'basketball',
            'KXNCAAW': 'basketball',
            'KXNBA': 'basketball',
            'KXNBL': 'basketball',
            'KXWNBA': 'basketball',
            'KXACB': 'basketball',
            'KXARGLNB': 'basketball',
            'KXNHL': 'hockey',
            'KXKHL': 'hockey',
            'KXWOWHOCKEY': 'hockey',
            'KXAHL': 'hockey',
            'KXSHL': 'hockey',
            'KXNCAAHOCKEY': 'hockey',
            'KXLIIGA': 'hockey',
            'KXDEL': 'hockey',
            'KXTENNIS': 'tennis',
            'KXATP': 'tennis',
            'KXWTA': 'tennis',
            'KXDOTA': 'dota2',
            'KXDOTA2': 'dota2',
            'KXCS2': 'cs2',
            'KXCS': 'cs2',
            'KXVALORANT': 'valorant',
            'KXR6': 'r6',
            'KXLOL': 'lol',
            'KXBOXING': 'boxing',
            'KXUFC': 'mma',
            'KXPFL': 'mma',
            'KXBELLATOR': 'mma',
            'KXSIXNATIONS': 'rugby',
            'KXRUGBY': 'rugby',
            'KXURC': 'rugby',
            'KXT20': 'cricket',
            'KXCRICKET': 'cricket',
            'KXIPL': 'cricket',
            'KXODI': 'cricket',
            'KXWOCURL': 'curling',
            'KXCURLING': 'curling',
            'KXNCAAMLAX': 'lacrosse',
            'KXLACROSSE': 'lacrosse',
            'KXPLL': 'lacrosse',
            'KXF1': 'motorsport',
            'KXNASCAR': 'motorsport',
            'KXINDYCAR': 'motorsport',
            'KXGOLF': 'golf',
            'KXPGA': 'golf',
        }
        
        # Props patterns to skip
        self.props_patterns = [
            'KXNBA2D',  # NBA double-doubles
            'KXNBA3P',  # NBA 3-pointers
            'KXNBAPROP',  # NBA props
            'POINTS',
            'ASSISTS',
            'REBOUNDS',
            'BLOCKS',
            'STEALS',
            'TRIPLE',
            'DOUBLE',
        ]
    
    def match(self, kalshi_events: List[Dict], poly_events: List[Dict]) -> Dict:
        """Main matching function - KALSHI FIRST!"""
        print("="*80)
        print("🔗 OUTCOME MATCHER V2 (KALSHI-FIRST, FAIL-SAFE)")
        print("="*80)
        print(f"📊 Kalshi events: {len(kalshi_events)}")
        print(f"📊 Polymarket events: {len(poly_events)}")
        print()
        
        outcome_links = []
        
        # FOR EACH KALSHI EVENT (source of truth!)
        for k_event in kalshi_events:
            self.stats['total_kalshi_events'] += 1
            
            # Process this Kalshi event
            result = self._process_kalshi_event(k_event, poly_events)
            
            if result:
                self.stats['accepted'] += 1
                # Create outcome links
                links = self._create_outcome_links(k_event, result)
                outcome_links.extend(links)
        
        # Print stats
        self._print_stats()
        
        # Save for save_links()
        self._last_outcome_links = outcome_links
        
        return {
            'outcome_links': outcome_links,
            'stats': self.stats
        }
    
    def _process_kalshi_event(self, k_event: Dict, poly_events: List[Dict]) -> Optional[Dict]:
        """
        Process ONE Kalshi event (it's the anchor!)
        
        Returns: matched Poly event or None
        """
        k_ticker = k_event.get('event_ticker', '')
        k_title = k_event.get('event_title', '')
        k_time = k_event.get('end_time', '')
        k_markets = k_event.get('markets', [])
        
        if not k_ticker or not k_title or not k_time:
            return None
        
        # STEP 1: Check if it's props (skip!)
        if self._is_props(k_ticker, k_title):
            self.stats['skipped_props'] += 1
            return None
        
        # STEP 2: Extract sport from ticker
        k_sport = self._extract_sport_from_ticker(k_ticker)
        
        # STEP 3: Extract participants from markets
        k_participants = self._extract_participants(k_markets)
        
        if len(k_participants) != 2:
            self.stats['skipped_no_participants'] += 1
            return None
        
        print(f"   🎯 Kalshi: {k_title[:50]}...")
        print(f"      Sport: {k_sport}, Participants: {k_participants}")
        
        # STEP 4: Find candidates on Poly
        candidates = self._find_poly_candidates(
            k_sport=k_sport,
            k_participants=k_participants,
            k_time=k_time,
            poly_events=poly_events
        )
        
        if not candidates:
            self.stats['skipped_no_candidates'] += 1
            print(f"      ❌ No candidates found")
            return None
        
        self.stats['avg_candidates'].append(len(candidates))
        
        # STEP 5: Check candidate count
        if len(candidates) > 10:
            self.stats['skipped_too_many_candidates'] += 1
            print(f"      ❌ Too many candidates: {len(candidates)} > 10 (SKIP!)")
            return None
        
        print(f"      🔍 {len(candidates)} candidates → Claude...")
        
        # STEP 6: Claude confirmation (if we have Anthropic)
        has_sport_mismatch = any(c.get('_sport_mismatch') for c in candidates)
        need_claude = len(candidates) > 1 or has_sport_mismatch
        
        if self.anthropic and need_claude:
            if has_sport_mismatch:
                sm = [c for c in candidates if c.get('_sport_mismatch')]
                print(f"      ⚠️ Sport mismatch detected ({sm[0].get('_k_sport')}≠{sm[0].get('_p_sport')}), asking AI...")
            match_idx = self._claude_confirm(k_title, k_participants, k_sport, candidates)
            
            if match_idx is None:
                self.stats['skipped_claude_none'] += 1
                print(f"      ❌ Claude: NONE")
                return None
            
            matched = candidates[match_idx]
        else:
            matched = candidates[0]
        
        # STEP 7: Post-check
        if not self._post_check(k_participants, matched):
            self.stats['skipped_postcheck'] += 1
            print(f"      ❌ Post-check FAILED")
            return None
        
        print(f"      ✅ MATCHED: {matched.get('event_title', '')[:50]}...")
        return matched
    
    def _is_props(self, ticker: str, title: str) -> bool:
        """Check if it's props (skip these!)"""
        text = (ticker + ' ' + title).upper()
        return any(pattern.upper() in text for pattern in self.props_patterns)
    
    def _extract_sport_from_ticker(self, ticker: str) -> str:
        """Extract sport from event_ticker prefix"""
        ticker_upper = ticker.upper()
        
        for prefix, sport in self.ticker_to_sport.items():
            if ticker_upper.startswith(prefix.upper()):
                return sport
        
        return 'unknown'
    
    def _extract_participants(self, markets: List[Dict]) -> List[str]:
        """
        Extract participants from markets[].yes_sub_title
        
        Returns: list of 2 participants (teams/players)
        """
        participants = []
        
        for market in markets:
            yes_sub = market.get('yes_sub_title', '').strip()
            
            # Skip "Tie" and empty
            if yes_sub and yes_sub.lower() not in ['tie', 'draw', '']:
                if yes_sub not in participants:
                    participants.append(yes_sub)
        
        return participants
    
    def _find_poly_candidates(
        self, 
        k_sport: str, 
        k_participants: List[str], 
        k_time: str,
        poly_events: List[Dict]
    ) -> List[Dict]:
        """
        Find Poly candidates where:
        1. Same sport
        2. BOTH participants present in event_title
        3. Time matches (±4 hours)
        """
        candidates = []
        
        # Normalize participants
        k_p1_norm = self._normalize_participant(k_participants[0])
        k_p2_norm = self._normalize_participant(k_participants[1])
        
        for p_event in poly_events:
            p_title = p_event.get('event_title', '')
            p_time = p_event.get('end_time', '')
            
            if not p_title or not p_time:
                continue
            
            if not self._time_match(k_time, p_time, window_hours=8):
                continue
            
            p_sport = self._detect_poly_sport(p_title)
            sport_ok = True
            if k_sport != 'unknown' and p_sport != 'unknown':
                if k_sport != p_sport:
                    sport_ok = False
            
            p_title_norm = self._normalize_participant(p_title)
            
            if self._participant_in_text(k_p1_norm, p_title_norm) and \
               self._participant_in_text(k_p2_norm, p_title_norm):
                if not sport_ok:
                    p_event = dict(p_event)
                    p_event['_sport_mismatch'] = True
                    p_event['_k_sport'] = k_sport
                    p_event['_p_sport'] = p_sport
                candidates.append(p_event)
        
        candidates.sort(key=lambda x: (
            1 if '- more markets' in x.get('event_title', '').lower() else 0
        ))
        
        seen_base_slugs = set()
        deduped = []
        for c in candidates:
            slug = c.get('event_slug', '')
            base_slug = slug.replace('-more-markets', '')
            if base_slug in seen_base_slugs and '- more markets' in c.get('event_title', '').lower():
                continue
            seen_base_slugs.add(base_slug)
            deduped.append(c)
        
        return deduped
    
    def _normalize_participant(self, text: str) -> str:
        """Normalize participant name"""
        import unicodedata
        text = text.lower()
        MANUAL_MAP = {
            'ø': 'o', 'æ': 'ae', 'ð': 'd', 'þ': 'th',
            'ł': 'l', 'ß': 'ss', 'đ': 'd',
            'Ø': 'o', 'Æ': 'ae', 'Ð': 'd', 'Þ': 'th',
            'Ł': 'l', 'Đ': 'd',
        }
        text = ''.join(MANUAL_MAP.get(c, c) for c in text)
        text = unicodedata.normalize('NFD', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        text = unicodedata.normalize('NFC', text)
        text = re.sub(r'\b(fc|bc|sc|cf|sk|fk|kk|as|team|esports|gaming|e-sports|saudi|club)\b', '', text)
        text = re.sub(r'-', ' ', text)
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        return ' '.join(text.split())
    
    def _participant_in_text(self, participant: str, text: str) -> bool:
        """
        Check if participant is in text with WORD BOUNDARIES + strong/weak words
        
        CONSTITUTION RULES:
        - NO substring match! ("high" in "highlanders" ❌)
        - Word boundaries (\b) ONLY!
        - Strong vs weak words (fc/united/city ignored)
        - Special: "st" matches st/saint/state (NO global normalization!)
        - Abbreviations expanded: "QPR" → checks "queens park rangers" tokens
        """
        participant_clean = participant.strip().lower()
        
        if participant_clean in ABBREVIATIONS:
            expanded = ABBREVIATIONS[participant_clean]
            exp_tokens = [t for t in expanded.split() if len(t) >= 2]
            exp_strong = [t for t in exp_tokens if clean_token(t) not in WEAK_WORDS]
            if not exp_strong:
                exp_strong = exp_tokens
            found = sum(1 for t in exp_strong if token_matches_in_text(t, text))
            if len(exp_strong) <= 1:
                if found >= 1:
                    return True
            else:
                if found >= min(2, len(exp_strong)):
                    return True
        
        tokens = [t for t in participant.split() if len(t) >= 2]
        
        if not tokens:
            return False
        
        strong_tokens = []
        for t in tokens:
            ct = clean_token(t)
            if ct in WEAK_WORDS:
                continue
            if '-' in t:
                parts = [p.lower() for p in t.split('-') if len(p) >= 2]
                if parts and all(p in WEAK_WORDS for p in parts):
                    continue
            strong_tokens.append(t)
        
        if not strong_tokens:
            strong_tokens = tokens
        
        found = 0
        for token in strong_tokens:
            if token_matches_in_text(token, text):
                found += 1
        
        if len(strong_tokens) == 1:
            return found >= 1
        else:
            min_needed = min(2, len(strong_tokens))
            return found >= min_needed
    
    def _time_match(self, time1: str, time2: str, window_hours: int = 4) -> bool:
        """Check if times match within window"""
        try:
            t1 = datetime.fromisoformat(time1.replace('Z', '+00:00'))
            t2 = datetime.fromisoformat(time2.replace('Z', '+00:00'))
            delta = abs((t1 - t2).total_seconds() / 3600)
            return delta <= window_hours
        except:
            return False
    
    def _detect_poly_sport(self, title: str) -> str:
        """Detect sport from Poly event_title or slug"""
        text = title.lower()

        prefix_map = {
            'counter-strike:': 'cs2', 'cs2:': 'cs2', 'csgo:': 'cs2',
            'dota 2:': 'dota2', 'dota2:': 'dota2',
            'valorant:': 'valorant',
            'rainbow six': 'r6',
            'lol:': 'lol', 'league of legends:': 'lol',
            'ahl:': 'hockey', 'shl:': 'hockey', 'del:': 'hockey',
            'khl:': 'hockey', 'nhl:': 'hockey', 'liiga:': 'hockey',
            't20 world cup:': 'cricket', 't20:': 'cricket',
            'ipl:': 'cricket', 'odi:': 'cricket',
            'six nations:': 'rugby', 'urc:': 'rugby',
            'world curling:': 'curling',
            'pga:': 'golf', 'lpga:': 'golf',
            'formula 1:': 'motorsport', 'f1:': 'motorsport',
            'nascar:': 'motorsport', 'indycar:': 'motorsport',
            'ncaa lacrosse:': 'lacrosse', 'pll:': 'lacrosse',
            'nba:': 'basketball', 'nbl:': 'basketball', 'acb:': 'basketball',
            'euroleague:': 'basketball', 'eurocup:': 'basketball',
            'ncaab:': 'basketball', 'ncaamb:': 'basketball',
            'atp:': 'tennis', 'wta:': 'tennis',
            'liga mx:': 'football', 'a-league:': 'football',
            'mls:': 'football', 'champions league:': 'football',
            'europa league:': 'football', 'conference league:': 'football',
            'copa del rey:': 'football', 'coppa italia:': 'football',
            'fa cup:': 'football', 'dfb pokal:': 'football',
        }
        for prefix, sport in prefix_map.items():
            if text.startswith(prefix):
                return sport

        keywords = {
            'dota2': ['dota', 'dota 2', 'dota2'],
            'cs2': ['cs2', 'csgo', 'counter-strike', 'counter strike'],
            'valorant': ['valorant', 'vct '],
            'r6': ['rainbow six', 'r6 siege', 'six invitational'],
            'lol': ['lol:', 'league of legends'],
            'boxing': ['boxing'],
            'mma': ['ufc', 'mma', 'bellator', 'pfl'],
            'cricket': ['t20 world cup', 'cricket', 'ipl ', ' odi '],
            'rugby': ['six nations', 'rugby', ' urc '],
            'curling': ['curling'],
            'lacrosse': ['lacrosse'],
            'motorsport': ['formula 1', 'f1 grand prix', 'nascar', 'indycar'],
            'golf': ['pga tour', 'lpga', 'masters tournament', 'us open golf'],
        }

        for sport, kws in keywords.items():
            if any(kw in text for kw in kws):
                return sport

        basketball_markers = [
            'basketball', 'nba ', ' nba',
            'euroleague', 'eurocup basketball',
            'baskonia', 'olimpia milano', 'fenerbahce beko',
            'anadolu efes', 'maccabi tel aviv',
            'zalgiris', 'alba berlin',
            'ldlc asvel',
        ]
        for marker in basketball_markers:
            if marker in text:
                return 'basketball'

        hockey_markers = [
            'hockey', 'nhl ', ' nhl', 'khl ',
            'ahl ', 'shl ',
        ]
        for marker in hockey_markers:
            if marker in text:
                return 'hockey'

        tennis_markers = [
            'tennis', 'atp ', 'wta ',
            'wimbledon', 'roland garros', 'australian open',
        ]
        for marker in tennis_markers:
            if marker in text:
                return 'tennis'

        football_markers = [
            ' fc', 'fc ', ' afc', 'afc ',
            'hotspur', 'real madrid', 'barcelona',
            'juventus', 'inter milan', 'ac milan',
            'paris saint', 'psg', 'bundesliga',
            'premier league', 'la liga', 'serie a',
            'ligue 1', 'eredivisie',
        ]
        for marker in football_markers:
            if marker in text:
                return 'football'

        return 'unknown'
    
    def _claude_confirm(
        self, 
        k_title: str, 
        k_participants: List[str], 
        k_sport: str,
        candidates: List[Dict]
    ) -> Optional[int]:
        """
        Claude confirms match - chunks of 3
        
        Returns: index of matched candidate or None
        """
        chunk_size = 3
        
        for chunk_start in range(0, len(candidates), chunk_size):
            chunk_end = min(chunk_start + chunk_size, len(candidates))
            chunk = candidates[chunk_start:chunk_end]
            
            self.stats['claude_calls'] += 1
            
            # Build prompt
            cand_text = ""
            for i, cand in enumerate(chunk, 1):
                cand_text += f"{i}. {cand.get('event_title', '')}\n"
            
            prompt = f"""Match Kalshi to Polymarket.

Kalshi: "{k_title}"
Participants: "{k_participants[0]}" AND "{k_participants[1]}"
Sport: {k_sport}

Candidates:
{cand_text}

RULES:
- BOTH participants MUST be in the Poly title!
- Return {{"match": 0}} if NONE
- Return {{"match": 1|2|3}} if EXACT match
- NO "best guess"! Only EXACT or NONE!

JSON:"""
            
            try:
                msg = self.anthropic.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=50,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}]
                )
                
                answer = msg.content[0].text.strip()
                
                # Parse JSON
                data = json.loads(answer)
                match_num = data.get('match', 0)
                
                if match_num > 0 and match_num <= len(chunk):
                    # Found! Return global index
                    return chunk_start + (match_num - 1)
            
            except Exception as e:
                print(f"         ⚠️ Claude error: {e}")
                continue
        
        # Not found in any chunk
        return None
    
    def _post_check(self, k_participants: List[str], p_event: Dict) -> bool:
        """
        Post-check: verify BOTH participants are in Poly event
        
        Requires ALL strong tokens (not just 2)
        Word boundaries + variants + spelling + abbreviations
        NO substring match!
        
        MECHANICAL check (no LLM!)
        """
        p_title = p_event.get('event_title', '')
        
        for participant in k_participants:
            participant_clean = participant.strip().lower()
            
            if participant_clean in ABBREVIATIONS:
                expanded = ABBREVIATIONS[participant_clean]
                exp_tokens = [t for t in expanded.split() if len(t) >= 2]
                exp_strong = [t for t in exp_tokens if clean_token(t) not in WEAK_WORDS]
                if not exp_strong:
                    exp_strong = exp_tokens
                found = sum(1 for t in exp_strong if token_matches_in_text(t, p_title))
                if found >= min(2, len(exp_strong)):
                    continue
            
            tokens = [t for t in participant.split() if len(t) >= 2]
            
            strong_tokens = []
            for t in tokens:
                ct = clean_token(t)
                if ct in WEAK_WORDS:
                    continue
                if '-' in t:
                    parts = [p.lower() for p in t.split('-') if len(p) >= 2]
                    if parts and all(p in WEAK_WORDS for p in parts):
                        continue
                strong_tokens.append(t)
            
            if not strong_tokens:
                strong_tokens = tokens
            
            for token in strong_tokens:
                if not token_matches_in_text(token, p_title):
                    return False
        
        return True
    
    def _extract_teams_from_title(self, title: str) -> List[str]:
        """
        Извлекает 2 команды из заголовка Polymarket.
        
        Форматы:
          "Team A vs. Team B"
          "Team A vs Team B"
          "1. FC Union Berlin vs. Eintracht Frankfurt"
          "NAC Breda vs. SBV Excelsior"
          "FC Metz vs. Lille OSC"
          "Team A vs. Team B - More Markets"  ← обрезаем суффикс
        
        Возвращает [home_team, away_team] или [] если не удалось
        """
        clean = re.sub(r'\s*-\s*More Markets.*$', '', title, flags=re.IGNORECASE)
        
        parts = re.split(r'\s+vs\.?\s+', clean, maxsplit=1)
        if len(parts) == 2:
            return [parts[0].strip(), parts[1].strip()]
        
        return []

    def _find_poly_market_for_team(self, team_name: str, poly_teams: List[str], 
                                     poly_markets: List[Dict]) -> Optional[Dict]:
        """
        Найти Polymarket маркет для конкретной команды.
        
        poly_teams = ["Home Team", "Away Team"] (из заголовка)
        poly_markets = [market0_data, market1_data, ...] (valid маркеты с ["Yes","No"])
        
        Маркет 0 = home, Маркет 1 = away, Маркет 2 = draw (если есть)
        
        Ищем по совпадению имени Kalshi команды с poly_teams[i]
        """
        team_norm = self._normalize_participant(team_name)
        team_tokens = team_norm.split()
        
        best_idx = None
        best_score = 0
        
        for i, pt in enumerate(poly_teams):
            if i >= len(poly_markets):
                break
            
            pt_norm = self._normalize_participant(pt)
            
            score = 0
            for tok in team_tokens:
                if len(tok) >= 3 and tok in pt_norm:
                    score += 1
            
            for pt_tok in pt_norm.split():
                if len(pt_tok) >= 3 and pt_tok in team_norm:
                    score += 1
            
            if score > best_score:
                best_score = score
                best_idx = i
        
        if best_idx is not None and best_score >= 1:
            return poly_markets[best_idx]
        
        return None

    def _create_outcome_links(self, k_event: Dict, p_event: Dict) -> List[Dict]:
        """
        Создаёт outcome links из совпавших событий.
        
        ОБРАБАТЫВАЕТ ДВА ФОРМАТА POLYMARKET:
        
        1) ОБЫЧНЫЙ: outcomes = ["Team A", "Team B"]
           → align_poly_prices по имени команды
        
        2) БИНАРНЫЙ (футбол): все маркеты имеют outcomes = ["Yes", "No"]
           → извлекаем команды из event_title
           → Маркет 0 = Home wins, Маркет 1 = Away wins, Маркет 2 = Draw
           → для каждого Kalshi маркета находим соответствующий Poly маркет
        """
        links = []
        
        k_title = k_event.get('event_title', '')
        k_markets = k_event.get('markets', [])
        k_participants = k_event.get('participants', [])
        
        p_slug = p_event.get('event_slug', '')
        p_title = p_event.get('event_title', '')
        p_condition_ids = p_event.get('condition_ids', [])
        p_markets_detailed = p_event.get('markets_detailed', [])
        
        p_outcomes_old = p_event.get('outcomes', [])
        p_prices_old = p_event.get('prices', [])
        
        valid_markets = [md for md in p_markets_detailed if md.get('valid')]
        
        all_binary = (
            len(valid_markets) >= 2
            and all(
                sorted(md.get('outcomes', [])) in [['No', 'Yes'], ['Yes', 'No']]
                for md in valid_markets
                if md.get('outcomes') not in [['Over', 'Under'], ['Under', 'Over']]
            )
        )
        
        has_team_outcomes = any(
            md.get('outcomes', []) not in [['Yes', 'No'], ['No', 'Yes'], ['Over', 'Under'], ['Under', 'Over']]
            and len(md.get('outcomes', [])) >= 2
            for md in valid_markets
        )
        
        if has_team_outcomes:
            return self._create_links_team_outcomes(k_event, p_event, valid_markets)
        elif all_binary:
            return self._create_links_binary_markets(k_event, p_event, valid_markets)
        else:
            return self._create_links_team_outcomes(k_event, p_event, valid_markets)
    
    def _create_links_team_outcomes(self, k_event: Dict, p_event: Dict, 
                                     valid_markets: List[Dict]) -> List[Dict]:
        """
        ПУТЬ 1: Poly маркет с outcomes = ["Team A", "Team B"]
        Стандартная логика для тенниса, баскетбола, киберспорта
        """
        links = []
        
        k_title = k_event.get('event_title', '')
        k_markets = k_event.get('markets', [])
        k_participants = k_event.get('participants', [])
        
        p_slug = p_event.get('event_slug', '')
        p_condition_ids = p_event.get('condition_ids', [])
        p_markets_detailed = p_event.get('markets_detailed', [])
        
        p_outcomes_old = p_event.get('outcomes', [])
        p_prices_old = p_event.get('prices', [])
        
        team_markets = []
        for md in valid_markets:
            outcomes = md.get('outcomes', [])
            if outcomes in [['Yes', 'No'], ['No', 'Yes'], ['Over', 'Under'], ['Under', 'Over']]:
                continue
            if 'Over' in str(outcomes) and 'Under' in str(outcomes):
                continue
            if len(outcomes) >= 2:
                team_markets.append(md)
        
        if not team_markets:
            if p_outcomes_old and p_prices_old and p_outcomes_old not in [['Yes', 'No'], ['No', 'Yes']]:
                p_outcomes = p_outcomes_old
                p_prices = [float(p) if p else 0.5 for p in p_prices_old]
                p_condition_id = p_condition_ids[0] if p_condition_ids else ''
                team_markets = [{'outcomes': p_outcomes, 'prices': p_prices_old, 'condition_id': p_condition_id}]
            else:
                return []
        
        for k_market in k_markets:
            k_market_ticker = k_market.get('market_ticker', '')
            k_yes_sub = k_market.get('yes_sub_title', '').strip()
            
            if k_yes_sub.lower() in ['tie', 'draw', '']:
                continue
            
            k_yes_price = k_market.get('yes_ask', 50) / 100.0
            
            best_result = None
            best_diff = float('inf')
            best_md = None
            
            for md in team_markets:
                md_outcomes = md.get('outcomes', [])
                md_prices_raw = md.get('prices', [])
                md_prices = [float(p) if p else 0.5 for p in md_prices_raw]
                
                result = align_poly_prices(k_yes_sub, md_outcomes, md_prices)
                if result is None:
                    continue
                
                p_yes, _, _ = result
                diff = abs(p_yes - k_yes_price)
                if diff < best_diff:
                    best_diff = diff
                    best_result = result
                    best_md = md
            
            if best_result is None:
                self.stats['skipped_alignment_unknown'] = self.stats.get('skipped_alignment_unknown', 0) + 1
                continue
            
            p_yes_aligned, p_no_aligned, alignment = best_result
            p_condition_id = best_md.get('condition_id', '') if best_md else ''
            p_outcomes = best_md.get('outcomes', []) if best_md else []
            
            if alignment == "FLIPPED":
                self.stats['alignment_flipped'] = self.stats.get('alignment_flipped', 0) + 1
            else:
                self.stats['alignment_direct'] = self.stats.get('alignment_direct', 0) + 1
            
            k_yes_ask = k_yes_price
            k_no_ask = k_market.get('no_ask', 50) / 100.0
            k_yes_bid = k_market.get('yes_bid', 50) / 100.0
            k_no_bid = k_market.get('no_bid', 50) / 100.0
            
            k_no_team = None
            for p in k_participants:
                if p not in ['Tie', 'Draw', k_yes_sub]:
                    k_no_team = p
                    break
            
            link = {
                'fixture_id': k_title,
                'alignment': alignment,
                'kalshi': {
                    'market_id': k_market_ticker,
                    'yes_outcome': k_yes_sub,
                    'no_outcome': k_no_team or 'Other',
                    'yes_price': k_yes_ask,
                    'no_price': k_no_ask,
                    'yes_bid': k_yes_bid,
                    'no_bid': k_no_bid,
                },
                'polymarket': {
                    'market_id': p_condition_id,
                    'slug': p_event.get('event_slug', ''),
                    'token_ids': best_md.get('clob_token_ids', []) if best_md else [],
                    'yes_outcome': p_outcomes[0] if len(p_outcomes) > 0 else '?',
                    'no_outcome': p_outcomes[1] if len(p_outcomes) > 1 else '?',
                    'yes_price': p_yes_aligned,
                    'no_price': p_no_aligned,
                }
            }
            
            links.append(link)
        
        return links
    
    def _create_links_binary_markets(self, k_event: Dict, p_event: Dict,
                                      valid_markets: List[Dict]) -> List[Dict]:
        """
        ПУТЬ 2: Poly маркеты с outcomes = ["Yes", "No"] (футбол)
        
        Polymarket футбол: 3 бинарных маркета (Home/Draw/Away)
        но ПОРЯДОК НЕПРЕДСКАЗУЕМ — может быть Home/Away/Draw или Home/Draw/Away
        
        РЕШЕНИЕ: Сопоставление по ЦЕНАМ
        Kalshi цена близка к Poly цене → это тот же маркет
        """
        links = []
        
        k_title = k_event.get('event_title', '')
        k_markets = k_event.get('markets', [])
        k_participants = k_event.get('participants', [])
        
        p_slug = p_event.get('event_slug', '')
        p_title = p_event.get('event_title', '')
        p_condition_ids = p_event.get('condition_ids', [])
        
        binary_markets = [
            md for md in valid_markets
            if sorted(md.get('outcomes', [])) == ['No', 'Yes']
        ]
        
        if len(binary_markets) < 2:
            return []
        
        poly_teams = self._extract_teams_from_title(p_title)
        
        for md in binary_markets:
            prices_raw = md.get('prices', [])
            outcomes = md.get('outcomes', [])
            yes_idx = outcomes.index('Yes') if 'Yes' in outcomes else 0
            md['_yes_price'] = float(prices_raw[yes_idx]) if prices_raw else 0.5
        
        for k_market in k_markets:
            k_market_ticker = k_market.get('market_ticker', '')
            k_yes_sub = k_market.get('yes_sub_title', '').strip()
            
            if k_yes_sub.lower() in ['tie', 'draw', '']:
                continue
            
            k_yes_price = k_market.get('yes_ask', 50) / 100.0
            
            best_market = None
            best_diff = float('inf')
            
            for md in binary_markets:
                diff = abs(md['_yes_price'] - k_yes_price)
                if diff < best_diff:
                    best_diff = diff
                    best_market = md
            
            if best_market is None or best_diff > 0.25:
                self.stats['skipped_alignment_unknown'] = self.stats.get('skipped_alignment_unknown', 0) + 1
                continue
            
            m_outcomes = best_market.get('outcomes', [])
            m_prices_raw = best_market.get('prices', [])
            m_prices = [float(p) if p else 0.5 for p in m_prices_raw]
            m_condition_id = best_market.get('condition_id', '')
            
            yes_idx = m_outcomes.index('Yes') if 'Yes' in m_outcomes else 0
            no_idx = 1 - yes_idx
            
            p_yes_price = m_prices[yes_idx]
            p_no_price = m_prices[no_idx]
            
            self.stats['alignment_direct'] = self.stats.get('alignment_direct', 0) + 1
            
            k_yes_ask = k_market.get('yes_ask', 50) / 100.0
            k_no_ask = k_market.get('no_ask', 50) / 100.0
            k_yes_bid = k_market.get('yes_bid', 50) / 100.0
            k_no_bid = k_market.get('no_bid', 50) / 100.0
            
            k_no_team = None
            for p in k_participants:
                if p not in ['Tie', 'Draw', k_yes_sub]:
                    k_no_team = p
                    break
            
            matched_poly_team = '?'
            if poly_teams:
                ksub_norm = self._normalize_participant(k_yes_sub)
                for pt in poly_teams:
                    pt_norm = self._normalize_participant(pt)
                    if any(len(tok) >= 3 and tok in pt_norm for tok in ksub_norm.split()):
                        matched_poly_team = pt
                        break
            
            link = {
                'fixture_id': k_title,
                'alignment': 'BINARY_PRICE_MATCH',
                'price_diff': round(best_diff, 4),
                'poly_team_matched': matched_poly_team,
                'kalshi': {
                    'market_id': k_market_ticker,
                    'yes_outcome': k_yes_sub,
                    'no_outcome': k_no_team or 'Other',
                    'yes_price': k_yes_ask,
                    'no_price': k_no_ask,
                    'yes_bid': k_yes_bid,
                    'no_bid': k_no_bid,
                },
                'polymarket': {
                    'market_id': m_condition_id,
                    'slug': p_slug,
                    'token_ids': best_market.get('clob_token_ids', []) if best_market else [],
                    'yes_outcome': 'Yes',
                    'no_outcome': 'No',
                    'yes_price': p_yes_price,
                    'no_price': p_no_price,
                }
            }
            
            links.append(link)
        
        return links
    
    def _print_stats(self):
        """Print statistics"""
        # Calculate totals
        matched_fixtures = self.stats['accepted']
        total_outcome_links = self.stats.get('alignment_direct', 0) + self.stats.get('alignment_flipped', 0)
        
        print("\n" + "="*80)
        print("📊 OUTCOME MATCHER V2 STATISTICS")
        print("="*80)
        print(f"📥 INPUT:")
        print(f"   Kalshi events: {self.stats['total_kalshi_events']}")
        print(f"   Poly events: {self.stats.get('total_poly_events', 0)}")
        print()
        print(f"✅ MATCHED:")
        print(f"   Fixtures (матчи): {matched_fixtures}")
        print(f"   Outcome links (исходы): {total_outcome_links}")
        print()
        print(f"🔗 ALIGNMENT BREAKDOWN:")
        print(f"   DIRECT (same outcome):  {self.stats.get('alignment_direct', 0)} links")
        print(f"   FLIPPED (inverted):     {self.stats.get('alignment_flipped', 0)} links")
        print()
        print(f"❌ SKIPPED:")
        print(f"   No participants: {self.stats['skipped_no_participants']}")
        print(f"   Props:           {self.stats['skipped_props']}")
        print(f"   No candidates:   {self.stats['skipped_no_candidates']}")
        print(f"   >10 candidates:  {self.stats['skipped_too_many_candidates']}")
        print(f"   Claude NONE:     {self.stats['skipped_claude_none']}")
        print(f"   Post-check:      {self.stats['skipped_postcheck']}")
        print(f"   Alignment UNKNOWN: {self.stats.get('skipped_alignment_unknown', 0)}")
        print()
        print(f"🤖 CLAUDE API:")
        print(f"   Calls: {self.stats['claude_calls']}")
        
        if self.stats['avg_candidates']:
            avg = sum(self.stats['avg_candidates']) / len(self.stats['avg_candidates'])
            print(f"   Avg candidates/event: {avg:.1f}")
        
        print("="*80)
    
    def save_links(self, filepath: str):
        """Save outcome links to JSON file"""
        import json
        links = getattr(self, '_last_outcome_links', [])
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(links, f, indent=2)
        print(f"💾 Saved {len(links)} outcome links to {filepath}")

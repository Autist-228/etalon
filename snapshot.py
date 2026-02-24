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
import unicodedata
from rapidfuzz import fuzz


UNICODE_MAP = {
    'ø': 'o', 'Ø': 'O', 'æ': 'ae', 'Æ': 'AE', 'ð': 'd', 'Ð': 'D',
    'þ': 'th', 'Þ': 'TH', 'ł': 'l', 'Ł': 'L', 'ß': 'ss', 'đ': 'd', 'Đ': 'D',
    'ü': 'u', 'Ü': 'U', 'ö': 'o', 'Ö': 'O', 'ä': 'a', 'Ä': 'A',
    'ğ': 'g', 'Ğ': 'G', 'ş': 's', 'Ş': 'S', 'ç': 'c', 'Ç': 'C',
    'ñ': 'n', 'Ñ': 'N', 'ã': 'a', 'Ã': 'A', 'õ': 'o', 'Õ': 'O',
    'í': 'i', 'Í': 'I', 'á': 'a', 'Á': 'A', 'é': 'e', 'É': 'E',
    'ó': 'o', 'Ó': 'O', 'ú': 'u', 'Ú': 'U', 'ý': 'y', 'Ý': 'Y',
    'ė': 'e', 'ę': 'e', 'ą': 'a', 'ś': 's', 'ź': 'z', 'ż': 'z',
    'ć': 'c', 'ń': 'n', 'ů': 'u', 'ř': 'r', 'ě': 'e', 'š': 's',
    'č': 'c', 'ž': 'z', 'ț': 't', 'ă': 'a',
}


def transliterate(text: str) -> str:
    result = []
    for ch in text:
        if ch in UNICODE_MAP:
            result.append(UNICODE_MAP[ch])
        else:
            result.append(ch)
    s = ''.join(result)
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return unicodedata.normalize('NFC', s)


TEAM_ALIASES = [
    ({'atlanta'}, {'hawks'}),
    ({'boston'}, {'celtics'}),
    ({'brooklyn'}, {'nets'}),
    ({'charlotte'}, {'hornets'}),
    ({'chicago'}, {'bulls'}),
    ({'cleveland'}, {'cavaliers', 'cavs'}),
    ({'dallas'}, {'mavericks', 'mavs'}),
    ({'denver'}, {'nuggets'}),
    ({'detroit'}, {'pistons'}),
    ({'golden', 'state'}, {'warriors'}),
    ({'houston'}, {'rockets'}),
    ({'indiana'}, {'pacers'}),
    ({'los', 'angeles'}, {'clippers', 'lakers'}),
    ({'memphis'}, {'grizzlies'}),
    ({'miami'}, {'heat'}),
    ({'milwaukee'}, {'bucks'}),
    ({'minnesota'}, {'timberwolves', 'wolves'}),
    ({'new', 'orleans'}, {'pelicans'}),
    ({'new', 'york'}, {'knicks'}),
    ({'oklahoma', 'city'}, {'thunder'}),
    ({'orlando'}, {'magic'}),
    ({'philadelphia'}, {'76ers', 'sixers'}),
    ({'phoenix'}, {'suns'}),
    ({'portland'}, {'blazers', 'trail'}),
    ({'sacramento'}, {'kings'}),
    ({'san', 'antonio'}, {'spurs'}),
    ({'toronto'}, {'raptors'}),
    ({'utah'}, {'jazz'}),
    ({'washington'}, {'wizards'}),
    ({'tampa', 'bay'}, {'buccaneers', 'bucs', 'lightning', 'rays'}),
    ({'green', 'bay'}, {'packers'}),
    ({'kansas', 'city'}, {'chiefs', 'royals'}),
    ({'pittsburgh'}, {'steelers', 'penguins', 'pirates'}),
    ({'seattle'}, {'seahawks', 'kraken'}),
    ({'baltimore'}, {'ravens', 'orioles'}),
    ({'cincinnati'}, {'bengals', 'reds'}),
    ({'jacksonville'}, {'jaguars', 'jags'}),
    ({'buffalo'}, {'bills', 'sabres'}),
    ({'carolina'}, {'panthers', 'hurricanes'}),
    ({'arizona'}, {'cardinals', 'diamondbacks', 'coyotes'}),
    ({'colorado'}, {'avalanche', 'rockies'}),
    ({'columbus'}, {'blue', 'jackets'}),
    ({'edmonton'}, {'oilers'}),
    ({'calgary'}, {'flames'}),
    ({'montreal'}, {'canadiens', 'habs'}),
    ({'ottawa'}, {'senators', 'sens'}),
    ({'vancouver'}, {'canucks'}),
    ({'winnipeg'}, {'jets'}),
    ({'connecticut'}, {'huskies', 'uconn'}),
    ({'uconn'}, {'huskies', 'connecticut'}),
    ({'duke'}, {'blue', 'devils'}),
    ({'kentucky'}, {'wildcats'}),
    ({'kansas'}, {'jayhawks'}),
    ({'north', 'carolina'}, {'tar', 'heels', 'unc'}),
    ({'gonzaga'}, {'bulldogs', 'zags'}),
    ({'villanova'}, {'wildcats'}),
    ({'michigan'}, {'wolverines'}),
    ({'michigan', 'state'}, {'spartans'}),
    ({'ohio', 'state'}, {'buckeyes'}),
    ({'purdue'}, {'boilermakers'}),
    ({'iowa'}, {'hawkeyes'}),
    ({'iowa', 'state'}, {'cyclones'}),
    ({'tennessee'}, {'volunteers', 'vols'}),
    ({'auburn'}, {'tigers'}),
    ({'alabama'}, {'crimson', 'tide'}),
    ({'florida'}, {'gators'}),
    ({'texas'}, {'longhorns'}),
    ({'houston'}, {'cougars'}),
    ({'baylor'}, {'bears'}),
    ({'marquette'}, {'golden', 'eagles'}),
    ({'creighton'}, {'bluejays'}),
    ({'st', 'johns'}, {'red', 'storm'}),
    ({'providence'}, {'friars'}),
    ({'xavier'}, {'musketeers'}),
    ({'memphis'}, {'tigers'}),
    ({'louisville'}, {'cardinals'}),
    ({'wisconsin'}, {'badgers'}),
    ({'illinois'}, {'fighting', 'illini'}),
    ({'indiana'}, {'hoosiers'}),
    ({'oregon'}, {'ducks'}),
    ({'arizona'}, {'wildcats'}),
    ({'arizona', 'state'}, {'sun', 'devils'}),
    ({'ucla'}, {'bruins'}),
    ({'usc'}, {'trojans'}),
    ({'inter'}, {'internazionale', 'inter', 'milano'}),
    ({'internazionale'}, {'inter', 'milano'}),
    ({'bodoe'}, {'bodo', 'glimt', 'bodoglimt'}),
    ({'bodo'}, {'bodoe', 'glimt', 'bodoglimt'}),
    ({'qarabag'}, {'qarabag', 'agdam'}),
    ({'qpr'}, {'queens', 'park', 'rangers'}),
    ({'queens', 'park', 'rangers'}, {'qpr'}),
    ({'west', 'brom'}, {'west', 'bromwich', 'albion', 'wba'}),
    ({'wba'}, {'west', 'bromwich', 'albion'}),
    ({'newcastle'}, {'newcastle', 'united'}),
    ({'leverkusen'}, {'bayer', 'leverkusen', 'bayer04'}),
    ({'olympiakos'}, {'olympiacos', 'olympiakos'}),
    ({'olympiacos'}, {'olympiakos', 'olympiacos'}),
    ({'psg'}, {'paris', 'saint', 'germain'}),
    ({'paris'}, {'psg', 'saint', 'germain'}),
    ({'juventus'}, {'juve'}),
    ({'juve'}, {'juventus'}),
    ({'bvb'}, {'borussia', 'dortmund'}),
    ({'borussia', 'dortmund'}, {'bvb'}),
    ({'psv'}, {'eindhoven', 'psv'}),
    ({'eindhoven'}, {'psv'}),
    ({'fenerbahce'}, {'fenerbahce'}),
    ({'besiktas'}, {'besiktas'}),
    ({'galatasaray'}, {'galatasaray'}),
    ({'sporting'}, {'sporting', 'lisboa', 'lisbon'}),
    ({'benfica'}, {'benfica', 'lisboa'}),
    ({'porto'}, {'porto'}),
    ({'ajax'}, {'ajax', 'amsterdam'}),
    ({'feyenoord'}, {'feyenoord', 'rotterdam'}),
    ({'az'}, {'alkmaar', 'az'}),
    ({'alkmaar'}, {'az'}),
    ({'ac', 'milan'}, {'milan', 'rossoneri'}),
    ({'napoli'}, {'napoli', 'ssc'}),
    ({'roma'}, {'roma', 'as'}),
    ({'lazio'}, {'lazio', 'ss'}),
    ({'atletico'}, {'atletico', 'madrid'}),
    ({'real', 'madrid'}, {'real'}),
    ({'barcelona'}, {'barca'}),
    ({'barca'}, {'barcelona'}),
    ({'bayern'}, {'bayern', 'munich', 'munchen'}),
    ({'munich'}, {'bayern', 'munchen'}),
    ({'man', 'city'}, {'manchester', 'city', 'mcfc'}),
    ({'manchester', 'city'}, {'man', 'city', 'mcfc'}),
    ({'man', 'utd'}, {'manchester', 'united', 'mufc'}),
    ({'manchester', 'united'}, {'man', 'utd', 'mufc'}),
    ({'liverpool'}, {'liverpool'}),
    ({'chelsea'}, {'chelsea'}),
    ({'arsenal'}, {'arsenal'}),
    ({'tottenham'}, {'spurs', 'hotspur'}),
    ({'wolves'}, {'wolverhampton', 'wanderers', 'wwfc'}),
    ({'wolverhampton'}, {'wolves', 'wwfc'}),
    ({'nott', 'forest'}, {'nottingham', 'forest', 'nffc'}),
    ({'nottingham'}, {'nott', 'forest', 'nffc'}),
    ({'sheffield', 'utd'}, {'sheffield', 'united', 'sufc'}),
]


def _expand_with_aliases(tokens: Set[str]) -> Set[str]:
    expanded = set(tokens)
    for city_tokens, nickname_tokens in TEAM_ALIASES:
        if city_tokens <= tokens:
            expanded |= nickname_tokens
        if nickname_tokens & tokens:
            expanded |= city_tokens
    return expanded


def normalize_name(name: str) -> str:
    name = transliterate(name).lower()
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
    normalized = normalize_name(name)
    tokens = set(normalized.split())
    noise = {'vs', 'the', 'fc', 'sc', 'cf', 'cd', 'ca', 'de', 'la', 'el',
             'set', 'match', 'over', 'under', 'game', 'round', 'bo3', 'bo5',
             'map', 'total', 'spread', 'esports', 'gaming', 'team'}
    tokens = tokens - noise
    return _expand_with_aliases(tokens)


def events_match(kalshi_title: str, poly_title: str, threshold: int = 60) -> bool:
    k_norm = normalize_name(kalshi_title)
    p_norm = normalize_name(poly_title)
    if k_norm == p_norm:
        return True
    ratio = fuzz.token_sort_ratio(k_norm, p_norm)
    if ratio >= threshold:
        return True
    k_tokens = extract_key_tokens(kalshi_title)
    p_tokens = extract_key_tokens(poly_title)
    if k_tokens and p_tokens:
        overlap = k_tokens & p_tokens
        if len(overlap) >= 2:
            return True
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
    ': First Half Winner', ': Second Half Winner',
    ': First Half Spread', ': Second Half Spread',
    ': First Half Total', ': Second Half Total',
    ': First Quarter Winner', ': First Quarter Spread',
    ': Turnovers', ': Fantasy Points',
    ' Game 1', ' Game 2', ' Game 3', ' Game 4', ' Game 5',
    ' Set 1', ' Set 2', ' Set 3',
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
    from kalshi_listener import KalshiListener
    from polymarket_listener import PolymarketListener

    live_only = (mode == 'live_only')
    mode_label = {'all': 'live + upcoming', 'live_only': 'LIVE ONLY', 'upcoming_only': 'UPCOMING ONLY'}
    print(f"\n{'='*60}")
    print(f"  M1 SNAPSHOT ({hours_ahead}h, {mode_label.get(mode, mode)})")
    print(f"{'='*60}")

    kalshi = KalshiListener(hours_ahead=hours_ahead, live_only=live_only)
    kalshi_result = kalshi.run()
    kalshi_raw = kalshi_result['events']

    poly = PolymarketListener(hours_ahead=hours_ahead, live_only=live_only)
    poly_result = poly.run()
    poly_raw = poly_result['events']

    if mode == 'upcoming_only':
        kalshi_raw = [e for e in kalshi_raw if e.get('hours_left', 0) >= 0]
        poly_raw = [e for e in poly_raw if e.get('hours_left', 0) >= 0]

    print(f"   Before cross-filter: Kalshi={len(kalshi_raw)}, Poly={len(poly_raw)}")

    filtered_kalshi, filtered_poly = cross_filter(kalshi_raw, poly_raw)

    print(f"   After cross-filter: Kalshi={len(filtered_kalshi)}, Poly={len(filtered_poly)}")

    dropped_k = len(kalshi_raw) - len(filtered_kalshi)
    dropped_p = len(poly_raw) - len(filtered_poly)
    if dropped_k > 0 or dropped_p > 0:
        print(f"   Dropped (no match): Kalshi={dropped_k}, Poly={dropped_p}")

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

    print(f"   Snapshot: {snapshot}")
    return snapshot

#!/usr/bin/env python3
"""
Fork Tracker v4 - ПЛАНИРОВЩИК (НЕ ЦИКЛ!)

КЛЮЧЕВОЕ ОТЛИЧИЕ:
- НЕ проходим все links каждую итерацию
- Проверяем ТОЛЬКО те links, которым ПОРА (next_check_at <= now)
- Плюсовые вилки → раз в 1 сек
- Минусовые вилки → раз в 30 сек
- Главный цикл → 0.5 сек (БЫСТРЫЙ!)

РЕЗУЛЬТАТ:
- Плюсовую вилку видим за 1-2 сек! ✅
- Минусовые не мешают! ✅
- Количество links НЕ ВЛИЯЕТ на скорость реакции! ✅
"""

import os
import sys
import time
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module3.prices_fetcher import PricesFetcher
from module3.fork_calculator import ForkCalculator
from module3.limits_checker import LimitsChecker
from module3.config import POSITIVE_FORK_THRESHOLD, TOTAL_FEE, Colors, kalshi_taker_fee, poly_taker_fee

# === ДИАГНОСТИЧЕСКИЕ ФУНКЦИИ ДЛЯ ЧЕК-ЛИСТА ===
def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"

def _f(x):
    try:
        if x is None:
            return "None"
        if isinstance(x, (int, float)):
            return f"{x:.4f}"
        return str(x)
    except Exception:
        return str(x)

def _isfinite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)

def _sum_ok(a, b, tol=0.05):
    return _isfinite(a) and _isfinite(b) and abs((a + b) - 1.0) <= tol

# Интервалы проверки
POSITIVE_INTERVAL = 1.0    # Плюсовые вилки - раз в 1 сек
NEGATIVE_INTERVAL = 10.0   # Минусовые вилки - раз в 10 сек (было 30)
MAIN_LOOP_SLEEP = 0.5      # Главный цикл - каждые 0.5 сек


class ScheduledLink:
    """Link с планировщиком"""
    
    def __init__(self, link: Dict):
        self.link = link
        self.link_id = link.get('id', '')
        
        # Планировщик
        self.next_check_at = 0.0  # Когда проверять в следующий раз
        
        # Последний результат
        self.last_result = None
        self.last_fork_percent = -100.0
        self.last_check_at = 0.0


class ForkTrackerV4:
    """Трекер вилок v4 - ПЛАНИРОВЩИК"""
    
    def __init__(self):
        self.fetcher = PricesFetcher()
        self.calculator = ForkCalculator()
        self.limits_checker = LimitsChecker()
        
        # Планировщик links
        self.scheduled_links: Dict[str, ScheduledLink] = {}
        self.outcome_links: List[Dict] = []  # Для совместимости с Control Center
        
        # Reload данных (как в V3)
        self.last_data_reload = 0
        self.data_reload_interval = 600  # 10 минут (600 секунд)
        
        # Статистика
        self.stats = {
            'total_checks': 0,
            'positive_forks': 0,
            'best_fork': -100,
            'best_fork_event': '',
            'errors': 0,
        }
        
        # Флаг остановки
        self.running = False
        
        # Интервалы (можно менять извне!)
        self.POSITIVE_INTERVAL = POSITIVE_INTERVAL
        self.NEGATIVE_INTERVAL = NEGATIVE_INTERVAL
    
    def _diag_link(self, link_id: str, link: dict, k_prices: dict, p_prices: dict, 
                   fork_pct: float = None, decision: str = None, reason: str = None,
                   cost1: float = None, cost2: float = None, edge1: float = None, edge2: float = None):
        """Диагностический лог для чек-листа релиза"""
        k = k_prices or {}
        p = p_prices or {}

        # читаем именно ASK (source of truth)
        k_yes_ask = k.get("yes_ask", None)
        k_no_ask  = k.get("no_ask", None)
        p_yes_ask = p.get("yes_ask", None)
        p_no_ask  = p.get("no_ask", None)

        # fallback (на случай если ask нет — чтобы видеть это в логах, а не молча)
        k_yes = k.get("yes", k_yes_ask)
        k_no  = k.get("no",  k_no_ask)
        p_yes = p.get("yes", p_yes_ask)
        p_no  = p.get("no",  p_no_ask)
        
        # Overround
        overround_k = (k_yes_ask + k_no_ask - 1.0) if (k_yes_ask and k_no_ask) else None
        overround_p = (p_yes_ask + p_no_ask - 1.0) if (p_yes_ask and p_no_ask) else None

        print(
            f"[{_ts()}][V4][LINK] id={link_id} "
            f"decision={decision or '-'} reason={reason or '-'} fork_pct={_f(fork_pct)}\n"
            f"  K keys={sorted(list(k.keys()))}\n"
            f"  P keys={sorted(list(p.keys()))}\n"
            f"  K yes_ask={_f(k_yes_ask)} no_ask={_f(k_no_ask)} yes_bid={_f(k.get('yes_bid'))} no_bid={_f(k.get('no_bid'))} src={k.get('source')}\n"
            f"  P yes_ask={_f(p_yes_ask)} no_ask={_f(p_no_ask)} yes_bid={_f(p.get('yes_bid'))} no_bid={_f(p.get('no_bid'))} src={p.get('source')}\n"
            f"  overround: K={_f(overround_k)} P={_f(overround_p)}\n"
            f"  fork_calc: cost1={_f(cost1)} edge1={_f(edge1)} | cost2={_f(cost2)} edge2={_f(edge2)}"
        )
    
    def load_outcome_links(self, links: List[Dict]):
        """Загрузить outcome_links и создать планировщик"""
        self.outcome_links = links  # Сохраняем для совместимости
        self.scheduled_links = {}
        
        for i, link in enumerate(links):
            # Генерируем id если его нет
            link_id = link.get('id') or link.get('fixture_id') or f"link_{i}"
            
            scheduled = ScheduledLink(link)
            scheduled.link_id = link_id  # Обновляем
            scheduled.next_check_at = time.time()  # Проверить сразу!
            self.scheduled_links[link_id] = scheduled
        
        print(f"✅ Планировщик: {len(self.scheduled_links)} links загружено")
    
    def remove_finished_events(self) -> int:
        """Удалить завершённые события (старт уже прошёл)"""
        now = datetime.now(timezone.utc)
        removed = 0
        
        to_remove = []
        for link_id, scheduled in self.scheduled_links.items():
            link = scheduled.link
            start_time_str = link.get('start_time', '')
            
            if start_time_str:
                try:
                    # Парсим время старта
                    if '+' in start_time_str:
                        start_time = datetime.fromisoformat(start_time_str)
                    else:
                        start_time = datetime.fromisoformat(start_time_str + '+00:00')
                    
                    # Если событие уже началось, удаляем
                    if start_time < now:
                        to_remove.append(link_id)
                        removed += 1
                except:
                    pass
        
        # Удаляем
        for link_id in to_remove:
            del self.scheduled_links[link_id]
        
        return removed
    
    def add_new_links(self, new_links: List[Dict]) -> int:
        """Добавить новые links (только те, которых ещё нет)"""
        added = 0
        
        for link in new_links:
            link_id = link.get('id', '')
            if link_id and link_id not in self.scheduled_links:
                scheduled = ScheduledLink(link)
                scheduled.next_check_at = time.time()  # Проверить сразу!
                self.scheduled_links[link_id] = scheduled
                added += 1
        
        return added
    
    def stop(self):
        """Остановить трекер"""
        self.running = False
    
    def load_fresh_data(self):
        """Загрузить свежие данные через модули 1 и 2"""
        from kalshi_listener import KalshiListener
        from polymarket_listener import PolymarketListener
        from module2.outcome_matcher_v2 import OutcomeMatcherV2
        
        print("📥 Загрузка событий из Module 1...")
        
        kalshi = KalshiListener(hours_ahead=6)
        kalshi_result = kalshi.run()
        
        polymarket = PolymarketListener(hours_ahead=6)
        poly_result = polymarket.run()
        
        print("🔗 Создание outcome_links (Module 2 v2)...")
        matcher = OutcomeMatcherV2()
        result = matcher.match(kalshi_result['events'], poly_result['events'])
        
        self.load_outcome_links(result['outcome_links'])
        
        return result
    
    def track_2way(self, scheduled: ScheduledLink) -> Optional[Dict]:
        """Отследить 2-way вилку для ONE link"""
        link = scheduled.link
        now = time.time()
        
        # Получаем данные
        k_data = link.get('kalshi', {})
        p_data = link.get('polymarket', {})
        
        k_market_id = k_data.get('market_id', '')
        p_slug = p_data.get('slug', '')
        # ИСПРАВЛЕНИЕ: М2 записывает condition_id как 'market_id'!
        p_condition_id = p_data.get('market_id', '') or p_data.get('condition_id', '')
        p_token_ids = p_data.get('token_ids', [])
        p_question = p_data.get('question', '')  # ВОПРОС для поиска!
        
        # Запрашиваем свежие цены
        k_prices = self.fetcher.fetch_kalshi_market(k_market_id)
        p_prices = self.fetcher.fetch_polymarket_by_slug_and_condition(
            slug=p_slug,
            condition_id=p_condition_id,
            token_ids=p_token_ids,
            question=p_question  # ПЕРЕДАЁМ ВОПРОС!
        )
        
        # === ЧЕК-ЛИСТ РЕЛИЗА: ФИЛЬТРЫ С ДИАГНОСТИКОЙ ===
        # УНИКАЛЬНЫЙ link_id с учётом исхода (чтобы не затирать YES/NO)
        fixture_id = link.get('fixture_id', 'unknown')
        alignment = link.get('alignment', 'DIRECT')
        link_id = f"{fixture_id}::{alignment}"
        
        if not k_prices or not p_prices:
            self._diag_link(link_id, link, k_prices, p_prices, decision="REJECT", reason="fetch_failed")
            return None
        
        # Читаем ASK (source of truth!)
        k_yes_ask = k_prices.get("yes_ask", 0)
        k_no_ask  = k_prices.get("no_ask", 0)
        k_yes_bid = k_prices.get("yes_bid", 0)
        k_no_bid  = k_prices.get("no_bid", 0)
        
        p_yes = p_prices.get("yes", 0)
        p_no = p_prices.get("no", 0)
        p_yes_ask = p_prices.get("yes_ask", 0) or p_yes
        p_no_ask  = p_prices.get("no_ask", 0) or p_no
        p_yes_bid = p_prices.get("yes_bid", 0) or p_yes
        p_no_bid  = p_prices.get("no_bid", 0) or p_no
        p_source = p_prices.get("source", "")
        
        # GAMMA FALLBACK → добавляем виртуальный спред +1%
        if "gamma" in p_source.lower():
            p_yes_ask = min(p_yes + 0.01, 0.99)
            p_no_ask = min(p_no + 0.01, 0.99)
            p_yes_bid = max(p_yes - 0.01, 0.01)
            p_no_bid = max(p_no - 0.01, 0.01)
        
        # 1) Единицы: проверка 0..1
        def _is_closed(x): 
            return x >= 0.98 or x <= 0.02
        
        if max(k_yes_ask, k_no_ask, p_yes_ask, p_no_ask) > 1.0001:
            self._diag_link(link_id, link, k_prices, p_prices, decision="REJECT", reason="units_not_0_1")
            return None
        
        # 2) OVERROUND LIMIT (вместо strict sanity)
        overround_k = (k_yes_ask + k_no_ask) - 1.0
        overround_p = (p_yes_ask + p_no_ask) - 1.0
        
        if overround_k > 0.15:  # Kalshi спред >15%
            self._diag_link(link_id, link, k_prices, p_prices, decision="REJECT", reason="overround_k_gt_15pct")
            return None
        
        if overround_p > 0.15:  # Poly спред >15% (was 4%, too strict with 0% poly fee)
            self._diag_link(link_id, link, k_prices, p_prices, decision="REJECT", reason="overround_p_gt_15pct")
            return None
        
        # 3) SPREAD TOO WIDE (нет ликвидности)
        spread_k = max(k_yes_ask - k_yes_bid, k_no_ask - k_no_bid) if (k_yes_bid > 0 and k_no_bid > 0) else 0
        if spread_k > 0.15:  # >15% spread = мусор
            self._diag_link(link_id, link, k_prices, p_prices, decision="REJECT", reason="spread_k_too_wide")
            return None
        
        # 4) Закрытые markets (≥98% или ≤2%)
        if _is_closed(k_yes_ask) or _is_closed(k_no_ask) or _is_closed(p_yes_ask) or _is_closed(p_no_ask):
            self._diag_link(link_id, link, k_prices, p_prices, decision="REJECT", reason="closed_filter")
            return None
        
        # 5) ПРАВИЛЬНЫЙ РАСЧЁТ ВИЛКИ с ДИНАМИЧЕСКИМИ комиссиями!
        # Kalshi: fee = round_up(0.07 * P * (1-P)) per contract (taker)
        # Polymarket: 0% for most sports, 0.0175 * P * (1-P) for NCAAB/Serie A
        import re
        sport_code = ''
        k_ticker = k_data.get('market_id', '')
        m_sport = re.match(r'KX([A-Z]+?)(?:GAME|MAP|MATCH|TOTAL|SPREAD|BTTS|MARGIN)-', k_ticker.upper())
        if m_sport:
            sport_code = m_sport.group(1)
        
        if alignment == 'FLIPPED':
            k_fee1 = kalshi_taker_fee(k_yes_ask)
            p_fee1 = poly_taker_fee(p_yes_ask, sport_code)
            cost1 = k_yes_ask + k_fee1 + p_yes_ask + p_fee1
            
            k_fee2 = kalshi_taker_fee(k_no_ask)
            p_fee2 = poly_taker_fee(p_no_ask, sport_code)
            cost2 = k_no_ask + k_fee2 + p_no_ask + p_fee2
        else:
            k_fee1 = kalshi_taker_fee(k_yes_ask)
            p_fee1 = poly_taker_fee(p_no_ask, sport_code)
            cost1 = k_yes_ask + k_fee1 + p_no_ask + p_fee1
            
            k_fee2 = kalshi_taker_fee(k_no_ask)
            p_fee2 = poly_taker_fee(p_yes_ask, sport_code)
            cost2 = k_no_ask + k_fee2 + p_yes_ask + p_fee2
        
        edge1 = 1.0 - cost1
        edge2 = 1.0 - cost2
        
        edge = max(edge1, edge2)
        fork_pct = edge * 100.0
        
        # 6) Слишком хорошо (>20% = фантом/не тот market)
        if edge > 0.20:
            self._diag_link(link_id, link, k_prices, p_prices, fork_pct=fork_pct, decision="REJECT", reason="fork_gt_20pct")
            return None
        
        # 7) Несогласованность (после alignment от М2)
        # For FLIPPED: K_YES and P_YES are OPPOSITE teams, so large gap is EXPECTED
        # Check consistency using hedged pairs instead
        if alignment == 'FLIPPED':
            gap_check = abs((k_yes_ask + p_yes_ask) - 1.0) > 0.50
        else:
            gap_check = abs(k_yes_ask - p_yes_ask) > 0.50
        if gap_check:
            self._diag_link(link_id, link, k_prices, p_prices, fork_pct=fork_pct, decision="REJECT", reason="inconsistency_yes_gap")
            return None
        
        # ✅ Все фильтры пройдены
        self._diag_link(link_id, link, k_prices, p_prices, fork_pct=fork_pct, decision="OK", reason="pass_all_filters",
                       cost1=cost1, cost2=cost2, edge1=edge1, edge2=edge2)
        
        # Рассчитываем вилку через калькулятор (для совместимости с остальным кодом)
        calc_alignment = 'OPPOSITE' if alignment == 'FLIPPED' else 'SAME'
        fork_result = self.calculator.calculate_with_alignment(
            k_yes=k_yes_ask,
            k_no=k_no_ask,
            p_yes=p_yes_ask,
            p_no=p_no_ask,
            alignment=calc_alignment
        )
        
        if not fork_result:
            return None
        
        # Проверяем лимиты (если плюсовая)
        # Проверка лимитов через LimitsChecker
        limits = None
        if len(p_token_ids) >= 2 and fork_result.fork_percent >= 0:
            from module3.limits_checker import LimitsChecker
            checker = LimitsChecker()
            
            # Определяем token_id в зависимости от стороны
            poly_side = fork_result.poly_side
            poly_token_id = p_token_ids[0] if poly_side.upper() == 'YES' else p_token_ids[1]
            
            limits = checker.check_fork_executability(
                kalshi_ticker=k_market_id,
                poly_condition_id=p_condition_id,
                poly_token_id=poly_token_id,
                kalshi_side=fork_result.kalshi_side,
                poly_side=fork_result.poly_side,
                expected_roi=fork_result.fork_percent
            )
        
        # Sanity check
        is_suspect = fork_result.fork_percent > 50
        
        # Формируем результат
        result = {
            'type': '2way',
            'link_id': scheduled.link_id,
            'fixture_title': link.get('fixture_id', link.get('fixture_title', '')),
            'market_type': link.get('market_type', ''),
            'outcome_key': link.get('outcome_key', ''),
            'fork': fork_result,
            'kalshi_prices': k_prices,
            'poly_prices': p_prices,
            'limits': limits,
            'is_suspect': is_suspect,
        }
        
        return result
    
    def run_scheduler(self, duration: int = None, executor=None):
        """
        Главный планировщик - БЫСТРЫЙ ЦИКЛ!
        
        Args:
            duration: Время работы в секундах. Если None - работает бесконечно!
            executor: Executor для исполнения сделок (опционально)
        """
        
        if not self.scheduled_links:
            print("❌ Нет links для планировщика!")
            return
        
        print(f"\n🚀 ПЛАНИРОВЩИК ЗАПУЩЕН!")
        print(f"   Links: {len(self.scheduled_links)}")
        print(f"   Плюсовые: раз в {self.POSITIVE_INTERVAL} сек")
        print(f"   Минусовые: раз в {self.NEGATIVE_INTERVAL} сек")
        print(f"   Главный цикл: каждые {MAIN_LOOP_SLEEP} сек")
        if duration:
            print(f"   Длительность: {duration} сек")
        else:
            print(f"   Режим: БЕСКОНЕЧНЫЙ (управляется M0)")
        if executor:
            print(f"   🎯 EXECUTOR ENABLED")
        print(f"   Нажмите Ctrl+C для остановки\n")
        
        start_time = time.time()
        self.last_data_reload = start_time  # Инициализируем
        iteration = 0
        self.running = True
        
        try:
            while self.running:
                iteration += 1
                now = time.time()
                
                # Проверка времени (если задан duration)
                if duration and (now - start_time) >= duration:
                    print(f"\n⏱️ Время вышло ({duration} сек)")
                    break
                
                # === RELOAD ОТКЛЮЧЁН В РЕЖИМЕ M0! M0 сам управляет обновлениями! ===
                # Оставляем для совместимости со старым режимом
                if duration and (now - self.last_data_reload) >= self.data_reload_interval:
                    print(f"\n🔄 RELOAD: Прошло {self.data_reload_interval/60:.0f} минут, загружаем новые события...")
                    old_count = len(self.scheduled_links)
                    
                    try:
                        self.load_fresh_data()
                        new_count = len(self.scheduled_links)
                        print(f"✅ RELOAD завершён: {old_count} → {new_count} links")
                    except Exception as e:
                        print(f"❌ RELOAD ошибка: {e}")
                    
                    self.last_data_reload = now
                
                # === ПЛАНИРОВЩИК: ВЫБИРАЕМ ТОЛЬКО ТЕХ КОМУ ПОРА! ===
                links_to_check = [
                    s for s in self.scheduled_links.values()
                    if s.next_check_at <= now
                ]
                
                # Логируем каждые 10 итераций
                if iteration % 10 == 0:
                    print(f"[Scheduler] Iteration #{iteration} | To check: {len(links_to_check)}/{len(self.scheduled_links)}")
                
                # Проверяем ТОЛЬКО выбранные links!
                positive_results = []
                
                for scheduled in links_to_check:
                    result = self.track_2way(scheduled)
                    
                    if result:
                        fork_pct = result['fork'].fork_percent
                        
                        # Сохраняем результат
                        scheduled.last_result = result
                        scheduled.last_fork_percent = fork_pct
                        scheduled.last_check_at = now
                        
                        # Планируем следующую проверку
                        if fork_pct >= POSITIVE_FORK_THRESHOLD:
                            # ПЛЮСОВАЯ → через 1 сек!
                            scheduled.next_check_at = now + POSITIVE_INTERVAL
                            positive_results.append(result)
                        else:
                            # МИНУСОВАЯ → через 30 сек!
                            scheduled.next_check_at = now + NEGATIVE_INTERVAL
                    else:
                        # Не удалось получить данные → через 5 сек
                        scheduled.next_check_at = now + 5.0
                
                # Статистика
                self.stats['total_checks'] = iteration
                if positive_results:
                    self.stats['positive_forks'] += len(positive_results)
                    
                    # Лучшая вилка
                    best = max(positive_results, key=lambda x: x['fork'].fork_percent)
                    best_pct = best['fork'].fork_percent
                    if best_pct > self.stats['best_fork']:
                        self.stats['best_fork'] = best_pct
                        self.stats['best_fork_event'] = best['fixture_title']
                
                # === MODULE 4: Исполнение вилок ===
                if executor and positive_results:
                    # Фильтруем не SUSPECT
                    executable = [r for r in positive_results if not r.get('is_suspect', False)]
                    
                    if executable:
                        links_map = {s.link_id: s.link for s in self.scheduled_links.values()}
                        exec_results = executor.process_opportunities(executable, links_map)
                        
                        if exec_results:
                            stats = executor.get_stats()
                            print(f"🎯 Executor: {len(exec_results)} trades")
                
                # Короткий сон!
                time.sleep(MAIN_LOOP_SLEEP)
        
        except KeyboardInterrupt:
            print(f"\n\n🛑 Остановлено пользователем")
            print(f"   Итераций: {iteration}")
            print(f"   Положительных вилок: {self.stats['positive_forks']}")
            if self.stats['best_fork'] > -100:
                print(f"   Лучшая: {self.stats['best_fork']:+.2f}% ({self.stats['best_fork_event'][:40]})")
    
    def get_all_results(self) -> List[Dict]:
        """Получить ВСЕ последние результаты для Control Center"""
        results = []
        
        for scheduled in self.scheduled_links.values():
            if scheduled.last_result:
                results.append(scheduled.last_result)
        
        return results
    
    def get_positive_results(self) -> List[Dict]:
        """Получить только ПЛЮСОВЫЕ результаты"""
        results = []
        
        for scheduled in self.scheduled_links.values():
            if scheduled.last_result and scheduled.last_fork_percent >= POSITIVE_FORK_THRESHOLD:
                results.append(scheduled.last_result)
        
        return results

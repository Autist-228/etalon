#!/usr/bin/env python3
"""
M0 - ОРКЕСТРАТОР СИСТЕМЫ

ЛОГИКА:
1. M1 создаёт snapshot (1 раз)
2. M2 матчит events → outcome_links (1 раз)
3. M3 получает outcome_links и РАБОТАЕТ ПОСТОЯННО:
   - Плюсовые вилки: обновление раз в 1 сек
   - Минусовые вилки: обновление раз в 5 сек
   - Убирает завершённые события
   - Получает новые из M2 каждые 10 минут

ВСЕ МОДУЛИ НЕЗАВИСИМЫЕ!
"""

import sys
import os
import time
from datetime import datetime, timezone
import signal

# ЗАГРУЗКА .env ПЕРВЫМ ДЕЛОМ!
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from snapshot import create_snapshot
from module2.outcome_matcher_v2 import OutcomeMatcherV2
from module3.fork_tracker_v4_scheduler import ForkTrackerV4
from module3.sub_event_matcher import SubEventMatcher
from module4.executor_v2 import ExecutorV2
from module4.config import print_config as print_m4_config, validate_config as validate_m4_config


class M0Orchestrator:
    """Оркестратор системы"""
    
    VALID_MODES = ('all', 'live_only', 'upcoming_only')
    
    def __init__(self, mode: str = 'all', hours_ahead: int = 6):
        self.running = True
        self.tracker = None
        self.executor = None
        
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {self.VALID_MODES}")
        self.mode = mode
        self.hours_ahead = hours_ahead
        
        self.M1_INTERVAL = 10 * 60
        
        self.last_m1_run = 0
        self.last_m2_run = 0
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, sig, frame):
        """Обработка сигналов остановки"""
        print("\n\n⚠️ Получен сигнал остановки!")
        self.running = False
        if self.tracker:
            self.tracker.stop()
    
    def run_m1(self):
        """M1: Создание snapshot"""
        print("\n" + "="*80)
        print("📸 M1: СОЗДАНИЕ SNAPSHOT")
        print("="*80)
        
        start_time = time.time()
        snapshot = create_snapshot(hours_ahead=self.hours_ahead, mode=self.mode)
        elapsed = time.time() - start_time
        
        print(f"\n✅ M1 завершён!")
        print(f"   Время: {elapsed:.2f} сек")
        print(f"   Kalshi: {snapshot.kalshi_count} событий")
        print(f"   Polymarket: {snapshot.poly_count} событий")
        
        self.last_m1_run = time.time()
        return snapshot
    
    def run_m2(self, snapshot):
        """M2: Матчинг событий"""
        print("\n" + "="*80)
        print("🔗 M2: МАТЧИНГ СОБЫТИЙ")
        print("="*80)
        
        start_time = time.time()
        matcher = OutcomeMatcherV2()
        result = matcher.match(snapshot.kalshi_events, snapshot.poly_events)
        elapsed = time.time() - start_time
        
        outcome_links = result['outcome_links']
        stats = result.get('stats', {})
        
        print(f"\n✅ M2 завершён!")
        print(f"   Время: {elapsed:.2f} сек")
        print(f"   Outcome links: {len(outcome_links)}")
        print(f"\n🤖 ANTHROPIC:")
        print(f"   API calls: {stats.get('claude_api_calls', 0)}")
        print(f"   Confirmed: {stats.get('claude_confirmed', 0)}")
        print(f"   Cache hits: {stats.get('claude_cache_hits', 0)}")
        
        self.last_m2_run = time.time()
        return outcome_links
    
    def start_m3(self, initial_links):
        """M3: Запуск трекера (работает постоянно!)"""
        print("\n" + "="*80)
        print("🎯 M3: ЗАПУСК ТРЕКЕРА (ПОСТОЯННЫЙ РЕЖИМ)")
        print("="*80)
        
        # Создаём трекер с правильными интервалами
        self.tracker = ForkTrackerV4()
        
        # Изменяем интервалы
        self.tracker.POSITIVE_INTERVAL = 1.0  # Плюсовые: 1 сек
        self.tracker.NEGATIVE_INTERVAL = 5.0  # Минусовые: 5 сек
        
        # V4 принимает list напрямую!
        self.tracker.load_outcome_links(initial_links)
        
        print(f"\n✅ M3 инициализирован!")
        print(f"   Links загружено: {len(initial_links)}")
        print(f"   Плюсовые вилки: обновление раз в 1 сек")
        print(f"   Минусовые вилки: обновление раз в 5 сек")
        print(f"   M2 будет обновлять links каждые 10 минут")
        print(f"   M3 будет работать в главном цикле M0")
    
    def start_m4(self):
        """M4: Инициализация Executor"""
        print("\n" + "="*80)
        print("💰 M4: ИНИЦИАЛИЗАЦИЯ EXECUTOR")
        print("="*80)
        
        # Проверка конфига
        print_m4_config()
        errors = validate_m4_config()
        
        if errors:
            print("\n❌ ОШИБКИ КОНФИГУРАЦИИ M4:")
            for err in errors:
                print(f"   - {err}")
            print("\n⚠️ M4 ОТКЛЮЧЕН!")
            self.executor = None
            return
        
        # Создаём executor
        self.executor = ExecutorV2()
        
        from module4.config import MIN_FORK_PCT as m4_min_fork
        print(f"\n✅ M4 готов к исполнению вилок (мин. {m4_min_fork}%)")
        print(f"   Executor будет получать вилки от M3")
    
    def run_sub_event_matching(self, snapshot, outcome_links):
        """M3 Sub-Events: Match Totals/Spreads/BTTS independently"""
        print("\n" + "="*80)
        print("  M3-SUB: MATCHING TOTALS/SPREADS/BTTS")
        print("="*80)
        
        try:
            matcher = SubEventMatcher()
            sub_links = matcher.match_sub_events(snapshot, outcome_links)
            print(f"\n  Sub-event links: {len(sub_links)}")
            return sub_links
        except Exception as e:
            print(f"\n  Sub-event matching error: {e}")
            return []
    
    def update_m3_links(self, new_links):
        """Обновить links в M3"""
        if not self.tracker:
            return
        
        print(f"\n📥 Обновление links в M3...")
        print(f"   Новых links: {len(new_links)}")
        
        # Удаляем завершённые события
        removed = self.tracker.remove_finished_events()
        print(f"   Удалено завершённых: {removed}")
        
        # Добавляем новые links
        added = self.tracker.add_new_links(new_links)
        print(f"   Добавлено новых: {added}")
        
        print(f"   Всего активных links: {len(self.tracker.scheduled_links)}")
    
    def run(self):
        """Главный цикл оркестратора"""
        print("="*80)
        print("🚀 M0 - ОРКЕСТРАТОР СИСТЕМЫ")
        print("="*80)
        print(f"⏰ Старт: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print()
        print("📋 НАСТРОЙКИ:")
        print(f"   MODE:          {self.mode}")
        print(f"   HOURS_AHEAD:   {self.hours_ahead}")
        print(f"   M1 (snapshot): раз в 10 минут (окно {self.hours_ahead} часов вперёд)")
        print(f"   M2 (matcher):  сразу после M1 на том же snapshot")
        print(f"   M3 (tracker):  постоянно (плюсовые 1 сек, минусовые 5 сек)")
        print(f"   M4 (executor): автоисполнение на вилках >= 10%")
        print()
        print("Нажмите Ctrl+C для остановки")
        print("="*80)
        
        # ПЕРВЫЙ ЗАПУСК
        print("\n🔥 ПЕРВЫЙ ЗАПУСК СИСТЕМЫ...")
        
        # M1 → M2 → M3 → M4
        snapshot = self.run_m1()
        outcome_links = self.run_m2(snapshot)
        
        if len(outcome_links) == 0:
            print("\n❌ НЕТ OUTCOME LINKS! Останавливаюсь...")
            return
        
        sub_links = self.run_sub_event_matching(snapshot, outcome_links)
        all_links = outcome_links + sub_links
        
        self.start_m3(all_links)
        self.start_m4()
        
        # ГЛАВНЫЙ ЦИКЛ
        print("\n" + "="*80)
        print("♻️ ГЛАВНЫЙ ЦИКЛ ЗАПУЩЕН!")
        print("="*80)
        
        try:
            while self.running:
                now = time.time()
                
                # Проверяем нужно ли запустить M1 → M2
                if now - self.last_m1_run >= self.M1_INTERVAL:
                    print(f"\n⏰ Время для M1+M2! (прошло {(now - self.last_m1_run)/60:.1f} минут)")
                    
                    # M1: создаём snapshot
                    snapshot = self.run_m1()
                    
                    # M2: СРАЗУ матчим на ТОМ ЖЕ snapshot (НЕ создаём новый!)
                    outcome_links = self.run_m2(snapshot)
                    
                    sub_links = self.run_sub_event_matching(snapshot, outcome_links)
                    all_links = outcome_links + sub_links
                    
                    self.update_m3_links(all_links)
                
                # === M3: ПРОВЕРКА ВИЛОК (планировщик) ===
                if self.tracker:
                    links_to_check = [
                        s for s in self.tracker.scheduled_links.values()
                        if s.next_check_at <= now
                    ]
                    
                    # Проверяем links
                    positive_forks = []
                    for scheduled in links_to_check:
                        result = self.tracker.track_2way(scheduled)
                        
                        if result:
                            fork_pct = result['fork'].fork_percent
                            
                            # Обновляем scheduled
                            scheduled.last_result = result
                            scheduled.last_fork_percent = fork_pct
                            scheduled.last_check_at = now
                            
                            # Планируем следующую проверку
                            if fork_pct >= 0:  # Плюсовая
                                scheduled.next_check_at = now + self.tracker.POSITIVE_INTERVAL
                                positive_forks.append(result)
                                
                                # Логируем
                                print(f"\n💰 ВИЛКА: {fork_pct:+.2f}% | {result['fixture_title']}")
                            else:  # Минусовая
                                scheduled.next_check_at = now + self.tracker.NEGATIVE_INTERVAL
                                
                                # Логируем отрицательные тоже!
                                print(f"\n💸 ВИЛКА: {fork_pct:+.2f}% | {result['fixture_title']}")
                        else:
                            scheduled.next_check_at = now + 5.0
                    
                    # === M4: ИСПОЛНЕНИЕ ВИЛОК >= MIN_FORK_PCT ===
                    if self.executor and positive_forks:
                        # Получаем порог из config
                        from module4.config import MIN_FORK_PCT
                        # Фильтруем вилки >= MIN_FORK_PCT
                        executable = [r for r in positive_forks 
                                     if r['fork'].fork_percent >= MIN_FORK_PCT 
                                     and not r.get('is_suspect', False)]
                        
                        if executable:
                            print(f"\n🎯 M4: Найдено {len(executable)} исполнимых вилок (>= {MIN_FORK_PCT}%)")
                            links_map = {s.link_id: s.link for s in self.tracker.scheduled_links.values()}
                            exec_results = self.executor.process_opportunities(executable, links_map)
                            
                            if exec_results:
                                print(f"✅ M4: Исполнено {len(exec_results)} сделок")
                
                # Показываем статистику раз в минуту
                if int(now) % 60 == 0:
                    self._print_status()
                
                time.sleep(0.5)  # Проверяем каждые 0.5 сек (быстрый цикл!)
                
        except KeyboardInterrupt:
            print("\n\n⚠️ Остановка по Ctrl+C...")
        
        finally:
            if self.tracker:
                self.tracker.stop()
            
            print("\n" + "="*80)
            print("✅ M0 ОСТАНОВЛЕН!")
            print("="*80)
            
            if self.tracker:
                self._print_final_stats()
    
    def _print_status(self):
        """Показать текущий статус"""
        if not self.tracker:
            return
        
        stats = self.tracker.stats
        
        print(f"\n📊 СТАТУС:")
        print(f"   Active links: {len(self.tracker.scheduled_links)}")
        print(f"   Total checks: {stats['total_checks']}")
        print(f"   Positive forks: {stats['positive_forks']}")
        print(f"   Best fork: {stats['best_fork']:.2f}%")
    
    def _print_final_stats(self):
        """Финальная статистика"""
        stats = self.tracker.stats
        
        print("\n📊 ФИНАЛЬНАЯ СТАТИСТИКА M3:")
        print(f"   Total checks: {stats['total_checks']}")
        print(f"   Positive forks: {stats['positive_forks']}")
        print(f"   Best fork: {stats['best_fork']:.2f}%")
        print(f"   Errors: {stats['errors']}")


def main():
    """Точка входа"""
    import argparse
    parser = argparse.ArgumentParser(description='M0 Orchestrator')
    parser.add_argument('--mode', choices=M0Orchestrator.VALID_MODES, default='all',
                        help='Event filter mode: all | live_only | upcoming_only')
    parser.add_argument('--hours', type=int, default=6,
                        help='Hours ahead window for M1 snapshot (default: 6)')
    args = parser.parse_args()
    
    orchestrator = M0Orchestrator(mode=args.mode, hours_ahead=args.hours)
    orchestrator.run()


if __name__ == "__main__":
    main()

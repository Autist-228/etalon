#!/usr/bin/env python3
"""
Validator - проверка правильности матчинга через DeepSeek
Независимый модуль для Module 3
"""

import os
import json
from typing import Dict, List, Optional, Tuple
from openai import OpenAI

# DeepSeek API
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-159f560c378d4dc4903c8d839d67483b')


class MatchValidator:
    """Валидатор матчей через DeepSeek LLM"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.client = None
        self.cache = {}  # Кэш проверенных пар
        
        if self.api_key:
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url="https://api.deepseek.com"
                )
                print("✅ DeepSeek validator initialized")
            except Exception as e:
                print(f"⚠️ DeepSeek init error: {e}")
                self.client = None
        else:
            print("⚠️ DeepSeek API key not set")
    
    def validate_match(self, kalshi_title: str, poly_title: str, 
                       kalshi_league: str = '', poly_league: str = '') -> Tuple[bool, str]:
        """
        Проверить правильность матчинга двух событий.
        
        Returns:
            (is_valid, reason)
        """
        # Проверяем кэш
        cache_key = f"{kalshi_title}|{poly_title}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        if not self.client:
            return True, "no_validator"  # Без валидатора считаем валидным
        
        try:
            prompt = f"""Event 1: {kalshi_title}
Event 2: {poly_title}

Same game? Say NO only if:
1. Teams are COMPLETELY DIFFERENT (e.g. "Lakers vs Celtics" vs "Heat vs Bulls")
2. One has ": Points" or ": Total" and other doesn't

Otherwise say YES. Don't overthink.

Answer: YES or NO + short reason"""

            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You filter obvious mismatches. Say YES unless teams are clearly wrong. Montreal=Canadiens, Boston=Bruins, etc. Be permissive."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50,
                temperature=0
            )
            
            answer = response.choices[0].message.content.strip()
            
            is_valid = answer.upper().startswith("YES")
            reason = answer
            
            # Кэшируем результат
            self.cache[cache_key] = (is_valid, reason)
            
            return is_valid, reason
            
        except Exception as e:
            return True, f"error: {e}"  # При ошибке считаем валидным
    
    def validate_batch(self, links: List[Dict]) -> List[Dict]:
        """
        Проверить список связок и вернуть только валидные.
        
        Returns:
            List of validated links with 'validation' field added
        """
        validated = []
        invalid_count = 0
        
        print(f"\n🔍 Validating {len(links)} matches with DeepSeek...")
        
        for i, link in enumerate(links):
            k_title = link.get('kalshi', {}).get('title', '')
            p_title = link.get('polymarket', {}).get('title', '')
            k_league = link.get('kalshi', {}).get('league', '')
            p_league = link.get('polymarket', {}).get('league', '')
            
            is_valid, reason = self.validate_match(k_title, p_title, k_league, p_league)
            
            link['validation'] = {
                'is_valid': is_valid,
                'reason': reason
            }
            
            if is_valid:
                validated.append(link)
            else:
                invalid_count += 1
                print(f"   ❌ Invalid: {k_title[:40]} vs {p_title[:40]}")
                print(f"      Reason: {reason}")
            
            # Прогресс
            if (i + 1) % 10 == 0:
                print(f"   Checked: {i + 1}/{len(links)}")
        
        print(f"\n✅ Validation complete: {len(validated)} valid, {invalid_count} invalid")
        
        return validated
    
    def quick_validate(self, kalshi_title: str, poly_title: str) -> bool:
        """
        Быстрая проверка без LLM - по ключевым словам.
        Используется для фильтрации ОЧЕВИДНЫХ ошибок.
        Лучше пропустить сомнительный матч чем отфильтровать хороший.
        """
        k = kalshi_title.lower()
        p = poly_title.lower()
        
        # Проверка типа рынка - Points/Total vs Winner
        # Kalshi часто имеет ": Points", ": Total", ": Spread" в названии
        k_is_points = any(x in k for x in [': points', ': total', ': spread', 'over ', 'under ', ': goal', ': assist', 'anytime goal', 'first goal'])
        p_is_points = any(x in p for x in [': points', ': total', ': spread', 'over ', 'under ', ': goal', ': assist', 'more markets'])
        
        # Если один ЯВНО про очки/тоталы, а другой нет - не совпадают
        if k_is_points and not p_is_points:
            return False
        if p_is_points and not k_is_points:
            return False
        
        # Для остальных случаев - пропускаем (лучше проверить через DeepSeek если вилка большая)
        return True


# Тест
if __name__ == "__main__":
    validator = MatchValidator()
    
    # Тесты
    tests = [
        ("Warriors at Timberwolves", "Warriors vs. Timberwolves", True),
        ("TB Lightning at CBJ Blue Jackets: Points", "Lightning vs. Blue Jackets", False),  # Разные типы!
        ("Montreal at Boston", "Canadiens vs. Bruins", True),
        ("Furman at Samford", "Chattanooga Mocs vs. Samford Bulldogs", False),  # Разные команды!
        ("UC Riverside at UC Davis", "UC Davis Aggies vs. UC Riverside Highlanders", True),
    ]
    
    print("=== Quick Validation Tests ===")
    for k, p, expected in tests:
        result = validator.quick_validate(k, p)
        status = "✅" if result == expected else "❌"
        print(f"{status} {k[:30]} vs {p[:30]} = {result} (expected {expected})")
    
    print("\n=== DeepSeek Validation Tests ===")
    if validator.client:
        for k, p, expected in tests[:3]:
            is_valid, reason = validator.validate_match(k, p)
            status = "✅" if is_valid == expected else "❌"
            print(f"{status} {k[:30]} vs {p[:30]}")
            print(f"   Result: {is_valid}, Reason: {reason}")

#!/usr/bin/env python3
"""
Polymarket Trading Client - исполнение ордеров на Polymarket через CLOB API
Uses py-clob-client with proper EIP-712 signatures
"""

import requests
import time
import json
from typing import Dict, Optional, Tuple, List
from eth_account import Account
from web3 import Web3

from .config import (
    POLYMARKET_PRIVATE_KEY, POLYGON_RPC_URL,
    POLYMARKET_CLOB_API, POLYMARKET_GAMMA_API, API_TIMEOUT,
    get_proxy_dict, get_http_proxy
)

# py-clob-client imports
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    import py_clob_client.http_helpers.helpers as clob_helpers
    import httpx
    CLOB_CLIENT_AVAILABLE = True
    
    # Configure proxy for py-clob-client's global httpx client
    _proxy_url = get_http_proxy()
    if _proxy_url:
        # Replace the global httpx client with one that uses proxy
        clob_helpers._http_client = httpx.Client(
            http2=True,
            proxy=_proxy_url,
            timeout=30.0
        )
        print(f"✅ py-clob-client httpx client configured with proxy")
        
except ImportError as e:
    CLOB_CLIENT_AVAILABLE = False
    print(f"⚠️ py-clob-client not installed: {e}")


class PolymarketClient:
    """Клиент для торговли на Polymarket через CLOB с EIP-712"""
    
    # Polymarket chain ID (Polygon mainnet)
    CHAIN_ID = 137
    
    def __init__(self):
        self.private_key = POLYMARKET_PRIVATE_KEY
        self.clob_url = POLYMARKET_CLOB_API
        self.gamma_url = POLYMARKET_GAMMA_API
        
        # Setup session with proxy
        self.session = requests.Session()
        self.proxies = get_proxy_dict()
        if self.proxies:
            self.session.proxies.update(self.proxies)
            print(f"✅ Polymarket HTTP session using proxy")
        
        # Initialize Web3 and account
        self.w3 = None
        self.account = None
        self.address = None
        self.clob_client = None
        self.api_creds = None
        
        if self.private_key:
            try:
                self.w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
                self.account = Account.from_key(self.private_key)
                self.address = self.account.address
                print(f"✅ Polymarket wallet initialized: {self.address}")
            except Exception as e:
                print(f"❌ Failed to init Polymarket account: {e}")
    
    def _init_clob_client(self) -> bool:
        """Initialize CLOB client with API credentials via EIP-712"""
        if not CLOB_CLIENT_AVAILABLE:
            print("❌ py-clob-client not available")
            return False
        
        if not self.private_key:
            print("❌ No private key configured")
            return False
        
        try:
            # Create CLOB client - it handles EIP-712 signing internally
            # The client will derive API credentials from the private key
            # Note: proxy is configured globally in the module imports
            self.clob_client = ClobClient(
                host=self.clob_url,
                key=self.private_key,
                chain_id=self.CHAIN_ID,
                signature_type=0,  # EOA wallet signature
                funder=self.address,
            )
            
            print(f"✅ CLOB client created for {self.address}")
            
            # Derive API credentials (this creates/retrieves API key via EIP-712 signature)
            self.api_creds = self.clob_client.derive_api_key()
            if self.api_creds:
                print(f"✅ CLOB API credentials derived successfully")
                print(f"   API Key: {self.api_creds.api_key[:20]}...")
                
                # Set the credentials on the client for authenticated requests
                self.clob_client.set_api_creds(self.api_creds)
                print(f"✅ API credentials set on CLOB client")
                return True
            else:
                print("❌ Failed to derive API credentials")
                return False
                
        except Exception as e:
            print(f"❌ CLOB client init error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_clob_balance(self, asset_type: str = "USDC") -> Optional[Dict]:
        """Get balance/allowance from CLOB API (requires auth)"""
        if not self.clob_client:
            if not self._init_clob_client():
                return None
        
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams
            # Use the authenticated client to get balance allowance
            params = BalanceAllowanceParams(
                asset_type=asset_type,
                signature_type=2  # POLY_GNOSIS_SAFE
            )
            balance_info = self.clob_client.get_balance_allowance(params)
            return balance_info
        except Exception as e:
            print(f"❌ CLOB balance error: {e}")
            return None
    
    def get_usdc_balance(self) -> Optional[float]:
        """Получить баланс USDC на Polygon (on-chain) - проверяет оба контракта"""
        if not self.address or not self.w3:
            return None
        
        try:
            # USDC контракты на Polygon
            usdc_contracts = [
                "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # Native USDC (новый)
                "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # Bridged USDC.e (старый)
            ]
            
            # ABI для balanceOf
            abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"}]
            
            total_balance = 0.0
            for usdc_address in usdc_contracts:
                try:
                    contract = self.w3.eth.contract(address=usdc_address, abi=abi)
                    balance_wei = contract.functions.balanceOf(self.address).call()
                    total_balance += balance_wei / 1e6  # USDC имеет 6 decimals
                except:
                    pass
            
            return total_balance
            
        except Exception as e:
            print(f"❌ USDC balance error: {e}")
            return None
    
    def get_market_prices(self, token_id: str) -> Optional[Dict]:
        """Получить текущие цены из CLOB orderbook"""
        try:
            # Получаем midpoint
            resp = self.session.get(
                f"{self.clob_url}/midpoint",
                params={'token_id': token_id},
                timeout=API_TIMEOUT
            )
            
            if resp.status_code != 200:
                return None
            
            mid_data = resp.json()
            mid = float(mid_data.get('mid', 0.5))
            
            # Получаем orderbook для bid/ask
            book_resp = self.session.get(
                f"{self.clob_url}/book",
                params={'token_id': token_id},
                timeout=API_TIMEOUT
            )
            
            if book_resp.status_code == 200:
                book = book_resp.json()
                bids = book.get('bids', [])
                asks = book.get('asks', [])
                
                best_bid = float(bids[0]['price']) if bids else mid - 0.01
                best_ask = float(asks[0]['price']) if asks else mid + 0.01
                
                return {
                    'bid': best_bid,
                    'ask': best_ask,
                    'mid': mid,
                }
            
            return {'bid': mid, 'ask': mid, 'mid': mid}
            
        except Exception as e:
            print(f"❌ Polymarket prices error: {e}")
            return None
    
    def get_markets(self, limit: int = 10) -> Optional[List[Dict]]:
        """Get list of markets from CLOB"""
        try:
            resp = self.session.get(
                f"{self.clob_url}/markets",
                params={'limit': limit},
                timeout=API_TIMEOUT
            )
            
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"❌ Get markets error: {resp.status_code} - {resp.text[:200]}")
                return None
                
        except Exception as e:
            print(f"❌ Get markets exception: {e}")
            return None
    
    def place_order(self, token_id: str, side: str, size: float,
                    price: float = None) -> Tuple[bool, Dict]:
        """
        Разместить ордер на Polymarket CLOB.
        
        Args:
            token_id: ID токена (YES или NO outcome)
            side: 'BUY' или 'SELL'
            size: количество shares (НЕ USD!)
            price: лимитная цена (0-1), если None - берём лучшую цену
        
        Returns:
            (success, result_dict)
        """
        if not self.clob_client:
            if not self._init_clob_client():
                return False, {'error': 'CLOB client not initialized'}
        
        try:
            # Получаем текущие цены если не указана
            if price is None:
                prices = self.get_market_prices(token_id)
                if not prices:
                    return False, {'error': 'Could not get market prices'}
                price = prices['ask'] if side == 'BUY' else prices['bid']
            
            # Import required types
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL
            
            order_side = BUY if side.upper() == 'BUY' else SELL
            
            # Create OrderArgs object (CORRECT WAY)
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side,
            )
            
            # Build and sign order using OrderArgs
            signed_order = self.clob_client.create_order(order_args)
            
            # Submit order with GTC (Good Till Cancelled)
            result = self.clob_client.post_order(signed_order, OrderType.GTC)
            
            if result:
                return True, {
                    'order_id': result.get('orderID', ''),
                    'status': result.get('status', 'placed'),
                    'token_id': token_id,
                    'side': side,
                    'size': size,
                    'price': price,
                }
            else:
                return False, {
                    'error': 'Order submission failed',
                    'token_id': token_id,
                    'side': side,
                }
                
        except Exception as e:
            return False, {
                'error': 'exception',
                'message': str(e),
                'token_id': token_id,
                'side': side,
            }
    
    def buy_outcome(self, token_id: str, budget_usd: float) -> Tuple[bool, Dict]:
        """
        Купить outcome на заданный бюджет.
        
        Args:
            token_id: ID токена (YES или NO)
            budget_usd: бюджет в USD
        
        Returns:
            (success, result_dict)
        """
        # Получаем текущую цену
        prices = self.get_market_prices(token_id)
        if not prices:
            return False, {'error': 'Could not get prices'}
        
        ask_price = prices['ask']
        
        # Рассчитываем размер позиции
        # На Polymarket: покупаем shares, каждая share стоит ask_price
        # При выигрыше получаем $1 за share
        shares = budget_usd / ask_price
        
        return self.place_order(token_id, 'BUY', shares, ask_price)
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Получить статус ордера
        
        Returns:
            Dict с данными ордера или None если не найден
        """
        if not self.clob_client:
            if not self._init_clob_client():
                return None
        
        try:
            # Get order by ID
            result = self.clob_client.get_order(order_id)
            
            if result:
                return {
                    'order_id': result.get('id', ''),
                    'status': result.get('status', ''),  # 'LIVE', 'MATCHED', 'CANCELLED'
                    'filled': result.get('matched', 0),
                    'remaining': result.get('remaining', 0),
                    'price': result.get('price', 0),
                }
            return None
            
        except Exception as e:
            print(f"❌ Polymarket order status error: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Отменить ордер
        
        Returns:
            True если успешно отменён
        """
        if not self.clob_client:
            if not self._init_clob_client():
                return False
        
        try:
            result = self.clob_client.cancel(order_id)
            return result is not None
            
        except Exception as e:
            print(f"❌ Polymarket cancel order error: {e}")
            return False
    
    def cancel_all_orders(self) -> bool:
        """Отменить все ордера"""
        if not self.clob_client:
            if not self._init_clob_client():
                return False
        
        try:
            result = self.clob_client.cancel_all()
            return result is not None
        except Exception as e:
            print(f"❌ Polymarket cancel all error: {e}")
            return False
    
    def get_market_info(self, token_id: str) -> Optional[Dict]:
        """Получить информацию о рынке включая min_order_size"""
        try:
            resp = self.session.get(
                f"{self.clob_url}/markets/{token_id}",
                timeout=API_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'token_id': token_id,
                    'condition_id': data.get('condition_id', ''),
                    'minimum_order_size': float(data.get('minimum_order_size', 5)),
                    'minimum_tick_size': float(data.get('minimum_tick_size', 0.01)),
                    'active': data.get('active', False),
                    'closed': data.get('closed', False),
                    'accepting_orders': data.get('accepting_orders', False),
                }
            return None
        except Exception as e:
            print(f"❌ Polymarket market info error: {e}")
            return None

    def get_token_ids_for_market(self, condition_id: str, slug: str) -> Optional[List[str]]:
        """Получить token_ids для рынка"""
        try:
            resp = self.session.get(
                f"{self.gamma_url}/events",
                params={'slug': slug},
                timeout=API_TIMEOUT
            )
            
            if resp.status_code != 200:
                return None
            
            events = resp.json()
            if not events:
                return None
            
            for event in events:
                for market in event.get('markets', []):
                    if market.get('conditionId') == condition_id:
                        tokens = market.get('clobTokenIds', '[]')
                        if isinstance(tokens, str):
                            return json.loads(tokens)
                        return tokens
            
            return None
            
        except Exception as e:
            print(f"❌ Get token_ids error: {e}")
            return None
    
    def test_connection(self) -> Dict:
        """Test connection and return status"""
        result = {
            'wallet_initialized': self.address is not None,
            'wallet_address': self.address,
            'proxy_configured': self.proxies is not None,
            'clob_client_available': CLOB_CLIENT_AVAILABLE,
            'clob_auth_ok': False,
            'api_key': None,
            'markets_accessible': False,
            'usdc_balance': None,
        }
        
        # Test markets endpoint (no auth required)
        markets = self.get_markets(limit=1)
        result['markets_accessible'] = markets is not None
        
        # Test USDC balance (on-chain)
        result['usdc_balance'] = self.get_usdc_balance()
        
        # Test CLOB auth
        if CLOB_CLIENT_AVAILABLE and self.private_key:
            try:
                if self._init_clob_client():
                    result['clob_auth_ok'] = True
                    result['api_key'] = self.api_creds.api_key[:20] + "..." if self.api_creds else None
            except Exception as e:
                result['clob_auth_error'] = str(e)
        
        return result


# Тест
if __name__ == "__main__":
    client = PolymarketClient()
    
    print("Testing Polymarket Client...")
    print("=" * 50)
    
    # Full connection test
    status = client.test_connection()
    for key, value in status.items():
        print(f"  {key}: {value}")

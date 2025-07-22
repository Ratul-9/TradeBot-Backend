import upstox_client
from django.utils import timezone
from decimal import Decimal
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING
from .models import (
    MarketData, Stock, SMEStock, OrderBook, UserPortfolio, 
    UserBalance, Trade, Room, TradingSession
)
from rest_framework.response import Response
import logging
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth import get_user_model
import uuid

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser
else:
    from django.contrib.auth import get_user_model
    User = get_user_model()

logger = logging.getLogger(__name__)

from datetime import datetime, timedelta
from typing import Optional, Dict, List
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

    

class BalanceService:
    """Service for managing user balances"""
    
    @staticmethod
    def get_or_create_balance(user, room: Room) -> UserBalance:
        """Get or create user balance for a room"""
        balance, created = UserBalance.objects.get_or_create(
            user=user,
            room=room,
            defaults={'total_cash_balance': Decimal('100000.00')}  # Default starting balance
        )
        return balance
    
    @staticmethod
    def can_afford_order(user, room: Room, amount: Decimal) -> bool:
        """Check if user can afford an order"""
        balance = BalanceService.get_or_create_balance(user, room)
        return balance.available_cash_balance >= amount
    
    @staticmethod
    def reserve_cash(user, room: Room, amount: Decimal) -> bool:
        """Reserve cash for an order"""
        balance = BalanceService.get_or_create_balance(user, room)
        return balance.reserve_cash(amount)
    
    @staticmethod
    def execute_buy_order(user, room: Room, amount: Decimal) -> bool:
        """Execute a buy order (convert reserved cash to actual spend)"""
        balance = BalanceService.get_or_create_balance(user, room)
        return balance.execute_cash_reservation(amount)
    
    @staticmethod
    def execute_sell_order(user, room: Room, amount: Decimal):
        """Execute a sell order (add cash from stock sale)"""
        balance = BalanceService.get_or_create_balance(user, room)
        balance.add_cash(amount)
    
    @staticmethod
    def release_cash_reservation(user, room: Room, amount: Decimal):
        """Release reserved cash (order cancelled)"""
        balance = BalanceService.get_or_create_balance(user, room)
        balance.release_cash_reservation(amount)


class PortfolioService:
    """Service for managing user portfolios"""
    
    @staticmethod
    def get_or_create_portfolio(user, room: Room, symbol: str) -> UserPortfolio:
        """Get or create portfolio entry for user-room-symbol"""
        portfolio, created = UserPortfolio.objects.get_or_create(
            user=user,
            room=room,
            symbol=symbol
        )
        return portfolio
    
    @staticmethod
    def can_sell_quantity(user, room: Room, symbol: str, quantity: int) -> bool:
        """Check if user has enough stocks to sell"""
        try:
            portfolio = UserPortfolio.objects.get(user=user, room=room, symbol=symbol)
            return portfolio.available_quantity >= quantity
        except UserPortfolio.DoesNotExist:
            return False
    
    @staticmethod
    def reserve_stocks(user, room: Room, symbol: str, quantity: int) -> bool:
        """Reserve stocks for a sell order"""
        try:
            portfolio = UserPortfolio.objects.get(user=user, room=room, symbol=symbol)
            return portfolio.reserve_quantity(quantity)
        except UserPortfolio.DoesNotExist:
            return False
    
    @staticmethod
    def execute_buy_trade(user, room: Room, symbol: str, quantity: int, price: Decimal):
        """Execute a buy trade - add stocks to portfolio"""
        portfolio = PortfolioService.get_or_create_portfolio(user, room, symbol)
        portfolio.add_buy_transaction(quantity, price)
    
    @staticmethod
    def execute_sell_trade(user, room: Room, symbol: str, quantity: int, price: Decimal) -> bool:
        """Execute a sell trade - remove stocks from portfolio"""
        try:
            portfolio = UserPortfolio.objects.get(user=user, room=room, symbol=symbol)
            return portfolio.add_sell_transaction(quantity, price)
        except UserPortfolio.DoesNotExist:
            return False
    
    @staticmethod
    def release_stock_reservation(user, room: Room, symbol: str, quantity: int):
        """Release reserved stocks (order cancelled)"""
        try:
            portfolio = UserPortfolio.objects.get(user=user, room=room, symbol=symbol)
            portfolio.release_quantity_reservation(quantity)
        except UserPortfolio.DoesNotExist:
            pass


class TradingService:
    """Main service for handling trading operations"""
    
    def __init__(self):
        # self.market_service = MarketDataService()
        self.balance_service = BalanceService()
        self.portfolio_service = PortfolioService()
    
    def place_order(self, user, room: Room, order_data: Dict) -> Tuple[bool, str, Optional[OrderBook]]:
        """
        Place a trading order
        Returns: (success, message, order_object)
        """
        try:
            with transaction.atomic():
                order_type = order_data['order_type']
                symbol = order_data['symbol']
                quantity = order_data['quantity']
                price = order_data['order_price']
                order_category = order_data.get('order_category', OrderBook.MARKET)
                
                # Calculate total order value
                total_value = quantity * price
                
                # Validate order based on type
                if order_type == OrderBook.BUY:
                    # Check if user has enough cash
                    if not self.balance_service.can_afford_order(user, room, total_value):
                        return False, "Insufficient balance", None
                    
                    # Reserve cash
                    if not self.balance_service.reserve_cash(user, room, total_value):
                        return False, "Failed to reserve cash", None
                
                elif order_type == OrderBook.SELL:
                    # Check if user has enough stocks
                    if not self.portfolio_service.can_sell_quantity(user, room, symbol, quantity):
                        return False, "Insufficient stocks", None
                    
                    # Reserve stocks
                    if not self.portfolio_service.reserve_stocks(user, room, symbol, quantity):
                        return False, "Failed to reserve stocks", None
                
                # Create order
                order = OrderBook.objects.create(
                    user=user,
                    room=room,
                    **order_data
                )
                
                # For market orders, execute immediately
                if order_category == OrderBook.MARKET:
                    success, message = self._execute_market_order(order)
                    if not success:
                        # Rollback reservations
                        self._rollback_reservations(order)
                        return False, message, None
                
                return True, "Order placed successfully", order
                
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return False, f"Error placing order: {str(e)}", None
    
    def cancel_order(self, order: OrderBook, reason: str = "") -> Tuple[bool, str]:
        """Cancel a pending order"""
        try:
            with transaction.atomic():
                if order.order_status != OrderBook.PENDING:
                    return False, "Cannot cancel non-pending order"
                
                # Release reservations
                self._rollback_reservations(order)
                
                # Update order status
                order.order_status = OrderBook.CANCELLED
                order.cancellation_timestamp = timezone.now()
                order.notes = f"Cancelled: {reason}" if reason else "Cancelled by user"
                order.save()
                
                return True, "Order cancelled successfully"
                
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False, f"Error cancelling order: {str(e)}"
    
    def _execute_market_order(self, order: OrderBook) -> Tuple[bool, str]:
        """Execute a market order immediately"""
        try:
            # Get current market price
            market_data = self.market_service.get_market_data(order.symbol)
            if not market_data:
                return False, "Market data not available"
            
            execution_price = market_data['ltp']
            
            # Execute the trade
            return self._execute_trade(order, execution_price, order.quantity)
            
        except Exception as e:
            logger.error(f"Error executing market order: {e}")
            return False, f"Error executing order: {str(e)}"
    
    def _execute_trade(self, order: OrderBook, execution_price: Decimal, quantity: int) -> Tuple[bool, str]:
        """Execute a trade"""
        try:
            total_value = quantity * execution_price
            
            if order.order_type == OrderBook.BUY:
                # Execute buy order
                if not self.balance_service.execute_buy_order(order.user, order.room, total_value):
                    return False, "Failed to execute buy order"
                
                # Update portfolio
                self.portfolio_service.execute_buy_trade(
                    order.user, order.room, order.symbol, quantity, execution_price
                )
            
            elif order.order_type == OrderBook.SELL:
                # Execute sell order
                if not self.portfolio_service.execute_sell_trade(
                    order.user, order.room, order.symbol, quantity, execution_price
                ):
                    return False, "Failed to execute sell order"
                
                # Add cash to balance
                self.balance_service.execute_sell_order(order.user, order.room, total_value)
            
            # Update order status
            order.filled_quantity += quantity
            order.executed_price = execution_price
            order.execution_timestamp = timezone.now()
            
            if order.is_fully_filled:
                order.order_status = OrderBook.EXECUTED
            else:
                order.order_status = OrderBook.PARTIALLY_FILLED
            
            order.save()
            
            # Create trade record
            Trade.objects.create(
                user=order.user,
                room=order.room,
                order=order,
                trade_type=order.order_type,
                symbol=order.symbol,
                quantity=quantity,
                price=execution_price,
                total_value=total_value,
                market_price_at_execution=execution_price
            )
            
            return True, "Trade executed successfully"
            
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False, f"Error executing trade: {str(e)}"
    
    def _rollback_reservations(self, order: OrderBook):
        """Rollback reservations for cancelled/failed orders"""
        try:
            if order.order_type == OrderBook.BUY:
                remaining_value = order.remaining_quantity * order.order_price
                self.balance_service.release_cash_reservation(
                    order.user, order.room, remaining_value
                )
            elif order.order_type == OrderBook.SELL:
                self.portfolio_service.release_stock_reservation(
                    order.user, order.room, order.symbol, order.remaining_quantity
                )
        except Exception as e:
            logger.error(f"Error rolling back reservations: {e}")
    
    def get_user_portfolio_summary(self, user, room: Room) -> Dict:
        """Get complete portfolio summary for a user in a room"""
        try:
            # Get cash balance
            balance = self.balance_service.get_or_create_balance(user, room)
            
            # Get all portfolio holdings
            portfolios = UserPortfolio.objects.filter(user=user, room=room, total_quantity__gt=0)
            
            total_investment = Decimal('0.00')
            current_portfolio_value = Decimal('0.00')
            total_realized_pnl = Decimal('0.00')
            total_unrealized_pnl = Decimal('0.00')
            
            for portfolio in portfolios:
                total_investment += portfolio.total_buy_value - portfolio.total_sell_value
                total_realized_pnl += portfolio.realized_pnl
                
                # Get current market value
                market_data = self.market_service.get_market_data(portfolio.symbol)
                if market_data:
                    current_value = portfolio.total_quantity * market_data['ltp']
                    current_portfolio_value += current_value
                    total_unrealized_pnl += portfolio.calculate_unrealized_pnl(market_data['ltp'])
                else:
                    # Fallback to average buy price
                    current_portfolio_value += portfolio.total_quantity * portfolio.average_buy_price
            
            # Get trade count
            total_trades = Trade.objects.filter(user=user, room=room).count()
            
            return {
                'cash_balance': balance.available_cash_balance,
                'total_investment': total_investment,
                'current_portfolio_value': current_portfolio_value,
                'total_realized_pnl': total_realized_pnl,
                'total_unrealized_pnl': total_unrealized_pnl,
                'total_pnl': total_realized_pnl + total_unrealized_pnl,
                'net_worth': balance.available_cash_balance + current_portfolio_value,
                'total_trades': total_trades,
                'holdings_count': portfolios.count()
            }
            
        except Exception as e:
            logger.error(f"Error getting portfolio summary: {e}")
            return {}
    
    def get_room_leaderboard(self, room: Room) -> List[Dict]:
        """Get leaderboard for a room"""
        try:
            participants = UserBalance.objects.filter(room=room)
            leaderboard = []
            
            for balance in participants:
                summary = self.get_user_portfolio_summary(balance.user, room)
                if summary:
                    starting_balance = Decimal('100000.00')  # Default starting balance
                    percentage_return = ((summary['net_worth'] - starting_balance) / starting_balance) * 100
                    
                    leaderboard.append({
                        'username': balance.user.username,
                        'net_worth': summary['net_worth'],
                        'total_pnl': summary['total_pnl'],
                        'total_trades': summary['total_trades'],
                        'percentage_return': percentage_return
                    })
            
            # Sort by net worth (descending)
            leaderboard.sort(key=lambda x: x['net_worth'], reverse=True)
            
            # Add ranks
            for i, entry in enumerate(leaderboard):
                entry['rank'] = i + 1
            
            return leaderboard
            
        except Exception as e:
            logger.error(f"Error generating leaderboard: {e}")
            return []


# Service instances
trading_service = TradingService()
# market_service = MarketDataService()
balance_service = BalanceService()
portfolio_service = PortfolioService()
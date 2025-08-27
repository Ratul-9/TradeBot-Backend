from functools import cache
import time
from celery import shared_task
from requests import Response
import upstox_client
from .models import OrderBook, MarketData, RoomParticipant, SMEStock, Stock, UserBalance, UserPortfolio, Trade
from django.utils import timezone
from decimal import Decimal
from .models import Room
import pytz
import logging
from rest_framework import permissions, status

logger  = logging.getLogger(__name__)

@shared_task
def execute_pending_orders():
    logger.warning("Running execute_pending_orders at %s", timezone.now())
    print(">>> Running execute_pending_orders task <<<")


    symbols = MarketData.objects.values_list('symbol', flat=True).distinct()

    for symbol in symbols:
        market_data = MarketData.objects.filter(symbol=symbol).order_by('-last_updated').first()
        if not market_data:
            continue
        ltp = market_data.ltp

        pending_orders = OrderBook.objects.filter(
            symbol=symbol,
            order_status=OrderBook.PENDING,
            order_category=OrderBook.LIMIT,
        )

        for order in pending_orders:
            user = order.user
            room = order.room
            should_execute = (
                (order.order_type == OrderBook.BUY and ltp <= order.order_price) or
                (order.order_type == OrderBook.SELL and ltp >= order.order_price)
            )

            if should_execute:
                order.executed_price = ltp
                order.filled_quantity = order.quantity
                order.order_status = OrderBook.EXECUTED
                order.execution_timestamp = timezone.now()
                order.save()

                total_value = ltp * order.quantity

                # --- Handle BUY Order Logic ---
                if order.order_type == OrderBook.BUY:
                    balance = UserBalance.objects.get(user=user, room=room)
                    
                    # Execute reserved cash
                    if not balance.execute_cash_reservation(total_value):
                        # Rollback the order status in case of failure
                        order.order_status = OrderBook.FAILED
                        order.save()
                        continue

                    # FIXED: Release excess reserved cash for limit orders
                    if order.order_category == OrderBook.LIMIT:
                        original_reserved = order.order_price * order.quantity
                        actual_cost = total_value
                        excess_reservation = original_reserved - actual_cost
                        
                        if excess_reservation > 0:
                            # Release the excess reserved cash back to available balance
                            balance.total_cash_balance += excess_reservation
                            balance.reserved_cash_balance -= excess_reservation
                            balance.save()

                    # Portfolio update
                    portfolio, _ = UserPortfolio.objects.get_or_create(
                        user=user,
                        room=room,
                        symbol=symbol,
                        defaults={
                            'stock_name': order.symbol,
                            'total_quantity': 0,
                            'average_buy_price': Decimal('0.00'),
                            'total_buy_value': Decimal('0.00')
                        }
                    )
                    portfolio.add_buy_transaction(order.quantity, ltp)
                    portfolio.save()

                    # Create stop loss order if applicable
                    if order.has_stop_loss and order.stop_loss_trigger_price and order.stop_loss_limit_price:
                        OrderBook.objects.create(
                            user=user,
                            room=room,
                            order_type=OrderBook.SELL,
                            symbol=symbol,
                            quantity=order.quantity,
                            order_price=order.stop_loss_limit_price,
                            order_category=OrderBook.STOP_LOSS_LIMIT,
                            order_status=OrderBook.PENDING,
                            executed_price=None,
                            execution_timestamp=None,
                            parent_order_id=order.id,
                            stop_loss_trigger_price=order.stop_loss_trigger_price,
                            stop_loss_limit_price=order.stop_loss_limit_price
                        )

                # --- Handle SELL Order Logic ---
                elif order.order_type == OrderBook.SELL:
                    balance = UserBalance.objects.get(user=user, room=room)
                    balance.total_cash_balance += total_value
                    balance.save()

                    # Deduct from portfolio
                    try:
                        portfolio = UserPortfolio.objects.get(user=user, room=room, symbol=symbol)
                        portfolio.remove_sell_transaction(order.quantity)
                        portfolio.save()
                    except UserPortfolio.DoesNotExist:
                        pass

                # --- Create trade record ---
                Trade.objects.create(
                    user=user,
                    room=room,
                    order=order,
                    trade_type=Trade.BUY if order.order_type == OrderBook.BUY else Trade.SELL,
                    symbol=symbol,
                    quantity=order.quantity,
                    price=ltp,
                    total_value=total_value
                )

        # Handle stop loss orders
        stop_loss_orders = OrderBook.objects.filter(
            symbol=symbol,
            order_status=OrderBook.PENDING,
            order_category=OrderBook.STOP_LOSS_LIMIT,
        )

        for sl_order in stop_loss_orders:
            # Check if stop loss should be triggered
            should_trigger = (ltp <= sl_order.stop_loss_trigger_price)
            
            if should_trigger:
                # Convert to limit sell order and check if it should execute
                should_execute = (ltp >= sl_order.stop_loss_limit_price)
                
                if should_execute:
                    # Execute the stop loss order
                    sl_order.executed_price = ltp
                    sl_order.filled_quantity = sl_order.quantity
                    sl_order.order_status = OrderBook.EXECUTED
                    sl_order.execution_timestamp = timezone.now()
                    sl_order.save()
                    
                    total_value = ltp * sl_order.quantity
                    
                    # Add cash to balance
                    balance = UserBalance.objects.get(user=sl_order.user, room=sl_order.room)
                    balance.total_cash_balance += total_value
                    balance.save()
                    
                    # Deduct from portfolio
                    try:
                        portfolio = UserPortfolio.objects.get(
                            user=sl_order.user, 
                            room=sl_order.room, 
                            symbol=symbol
                        )
                        portfolio.remove_sell_transaction(sl_order.quantity)
                        portfolio.save()
                    except UserPortfolio.DoesNotExist:
                        pass
                    
                    # Create trade record
                    Trade.objects.create(
                        user=sl_order.user,
                        room=sl_order.room,
                        order=sl_order,
                        trade_type=Trade.SELL,
                        symbol=symbol,
                        quantity=sl_order.quantity,
                        price=ltp,
                        total_value=total_value
                    )

class ShortSellService:
    def get_instrument_key(self, symbol: str) -> str | None:
        try:
            cache_key = f"instrument_key_{symbol}"
            instrument_key = cache.get(cache_key)

            if instrument_key:
                return instrument_key

            # First check in Stock table
            stock = Stock.objects.filter(symbol=symbol).first()
            if stock and stock.isin_number:
                instrument_key = f"NSE_EQ|{stock.isin_number}"
                cache.set(cache_key, instrument_key, 600)
                return instrument_key

            # Then check SMEStock table
            sme_stock = SMEStock.objects.filter(symbol=symbol).first()
            if sme_stock and sme_stock.isin_number:
                instrument_key = f"NSE_EQ|{sme_stock.isin_number}"
                cache.set(cache_key, instrument_key, 600)
                return instrument_key

            return None

        except Exception as e:
            logger.error(f"Error fetching instrument key for {symbol}: {e}")
            return None
        

    def get_ltp(self, symbol):
        apiInstance = upstox_client.HistoryV3Api()
        instrument_key = self.get_instrument_key(symbol)

        if not instrument_key:
            return {"error": f"Could not get instrument key for {symbol}"}
        
        # Try 1-minute data first, then fall back to daily data
        intervals_to_try = [
            ("minutes", "1"),
            ("days", "1")
        ]
        
        for unit, interval in intervals_to_try:
            try:
                response = apiInstance.get_intra_day_candle_data(
                    instrument_key=instrument_key,
                    interval=interval, 
                    unit=unit
                )

                candles = response.data.candles

                if candles:
                    first_candle = candles[0]
                    ltp = first_candle[4]  # Close price
                    return {"ltp": ltp}
                    
            except Exception as e:
                logger.error(f"Error fetching {unit} data for {symbol}: {e}")
                continue
        
        return {"error": "No historical data found for the symbol"}
    

    def calculate_borrowing_cost(self, order, days_held):
        annual_borrowing_rate = Decimal('0.08')
        daily_rate = annual_borrowing_rate / 365

        position_value = order.order_price * order.quantity
        borrowing_cost = position_value * daily_rate * days_held

        return borrowing_cost
    
    def is_market_open(self):
        ist = pytz.timezone('Asia/Kolkata')
        current_time_ist = timezone.now().astimezone(ist)

        if current_time_ist.weekday() > 4:
            return False, "weekend"
        
        market_open = time(9, 15)
        market_close = time(16, 0)
        current_time_only = current_time_ist.time()


        if current_time_only < market_open or current_time_only > market_close:
            return False, "outside_market_hours"
        
        return True, "market_open"
    
    def get_open_short_positions(self):
        
        try:
            current_date = timezone.now().date()
            short_orders = OrderBook.objects.filter(is_short_sell = True, order_timestamp = current_date)

            return short_orders
        
        except Exception as e:
            return e
    
    def calculate_pnl(self, short_order):
        days_held = (timezone.now() - short_order.order_timestamp).days

        if days_held == 0:
            days_held = 1
        
        ltp_resp = self.get_ltp(short_order.symbol)
        ltp = Decimal(str(ltp_resp["ltp"]))        


        gross_pnl = (short_order.order_price - ltp) * short_order.quantity
        borrowing_cost = self.calculate_borrowing_cost(short_order, days_held)
        position_value = short_order.order_price * short_order.quantity
        transaction_cost = (position_value + ltp * short_order.quantity) * Decimal('0.001')
        net_pnl = gross_pnl - borrowing_cost - transaction_cost

        return {
            'gross_pnl': gross_pnl,
            'borrowing_cost': borrowing_cost,
            'transaction_cost': transaction_cost,
            'net_pnl': net_pnl,
            'days_held': days_held
        }
    
    def squre_off_positions(self, short_order):
        try:
            ltp_resp = self.get_ltp(short_order.symbol)
            ltp = Decimal(str(ltp_resp["ltp"]))        

            if not ltp:
                raise ValueError(f"Could not get LTP for {short_order.symbol}")
            
            pnl_data = self.calculate_pnl(short_order=short_order)
            
            square_off_order = OrderBook.objects.create(
                user = short_order.user,
                room = short_order.room,
                symbol = short_order.symbol,
                order_type = OrderBook.BUY,
                order_category = OrderBook.MARKET,
                quantity = short_order.quantity,
                order_price = ltp,
                is_short_sell = False,
                order_status = OrderBook.EXECUTED,
                order_timestamp = timezone.now(),
                execution_timestamp = timezone.now()
            )

            short_order.order_status = OrderBook.SQUARED_OFF
            short_order.execution_timestamp = timezone.now()
            short_order.save()

            self.update_portfolio_after_square_off(short_order, square_off_order, pnl_data['net_pnl'])

            self.update_balance_after_square_off(short_order, pnl_data['net_pnl'])

            return {
                'success': True,
                'square_off_order_id': square_off_order.id,
                'pnl': pnl_data['net_pnl'],
            }

        except Exception as e:
            logger.error(f"Error squaring off position {short_order.id}: {str(e)}")
            return {'success': False, 'error': str(e)}
    

    def update_portfolio_after_square_off(self, short_order, square_off_order, net_pnl):
        try:
            portfolio = UserPortfolio.objects.get(
                user=short_order.user, 
                room=short_order.room, 
                symbol=short_order.symbol
            )
        
            # Use the model's method instead of manual updates
            success = portfolio.cover_short_position(
                short_order.quantity, 
                square_off_order.order_price
            )
        
            if not success:
                logger.error(f"Failed to cover short position - insufficient short quantity")
            
        except UserPortfolio.DoesNotExist:
            logger.warning(f"Portfolio not found for {short_order.user.username} - {short_order.symbol}")
    

    def update_balance_after_square_off(self, short_order, current_ltp, pnl_data):
        try:
            balance = UserBalance.objects.get(user=short_order.user, room=short_order.room)

            # 1. Deduct the cost of buying back the shares
            buy_back_cost = current_ltp * short_order.quantity
            balance.available_cash_balance -= buy_back_cost
            
            # 2. Release the margin that was blocked during short sell
            position_value = short_order.order_price * short_order.quantity
            margin_released = position_value * Decimal('0.02')
            balance.available_cash_balance += margin_released
            
            # 3. Deduct borrowing costs and transaction costs
            balance.available_cash_balance -= pnl_data['borrowing_cost']
            balance.available_cash_balance -= pnl_data['transaction_cost']
            
            balance.save()
            
        except UserBalance.DoesNotExist:
            logger.error(f"Balance not found for {short_order.user.username}")

    def bulk_square_off(self, short_orders):
        results = {
            'total_positions': short_orders.count(),
            'squared_off': 0,
            'failed': 0,
            'errors': []
        }

        for short_order in short_orders:
            result = self.squre_off_positions(short_order)
            if result['success']:
                results['squared_off'] += 1
                logger.info(f"Squared off {short_order.symbol} for {short_order.user.username}")
            else:
                results['failed'] += 1
                results['errors'].append({
                    'order_id': short_order.id,
                    'symbol': short_order.symbol,
                    'error': result['error']
                })
        return results


@shared_task
def auto_square_off_short_sells():
    service = ShortSellService()

    is_open, reason = service.is_market_open()
    if not  is_open:
        return {"status": "skipped", "reason": reason}
    


    
    open_postions = service.get_open_short_positions()
    results = service.bulk_square_off(open_postions)
    results["status"] = "completed"
    results["timestamp"] = timezone.now().isoformat()
    
    logger.info(f"Auto square-off completed: {results}")
    return results
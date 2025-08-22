from celery import shared_task
from .models import OrderBook, MarketData, UserBalance, UserPortfolio, Trade
from django.utils import timezone
from decimal import Decimal
from .models import Room

@shared_task
def execute_pending_orders():
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
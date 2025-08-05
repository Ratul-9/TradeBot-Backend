from celery import shared_task
from .models import OrderBook, MarketData, UserBalance, UserPortfolio, Trade
from django.utils import timezone
from decimal import Decimal
from rooms.models import Room  # Assuming Room is in rooms.models

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
                    if order.has_stop_loss and order.stop_loss_price:
                        OrderBook.objects.create(
                            user=user,
                            room=room,
                            order_type=OrderBook.SELL,
                            symbol=symbol,
                            quantity=order.quantity,
                            order_price=order.stop_loss_price,
                            order_category=OrderBook.STOP_LOSS,
                            order_status=OrderBook.PENDING,
                            executed_price=None,
                            execution_timestamp=None,
                            parent_order_id=order.id,
                            stop_loss_price=order.stop_loss_price
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

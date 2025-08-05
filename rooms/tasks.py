from celery import shared_task
from .models import OrderBook, MarketData
from django.utils import timezone
from decimal import Decimal

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
            order_status = OrderBook.PENDING,
            order_category = OrderBook.LIMIT,
        )

        for order in pending_orders:
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
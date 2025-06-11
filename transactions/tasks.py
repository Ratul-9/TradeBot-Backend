from celery import shared_task
from .models import PendingOrder, Transaction, Portfolio
from users.models import CustomUser
from decimal import Decimal
import requests
import logging

logger = logging.getLogger(__name__)  # Logging setup

@shared_task
def check_pending_orders():
    pending_orders = PendingOrder.objects.filter(status="PENDING")
    
    for order in pending_orders:
        response = requests.get(f"http://127.0.0.1:8000/api/stocks/price/{order.symbol}/")
        
        if response.status_code == 200:
            stock_price = Decimal(response.json().get("last_price", 0))
            user = order.user

            if order.order_type == "BUY" and stock_price <= order.target_price:
                total_price = stock_price * order.quantity

                if user.virtual_balance >= total_price:
                    user.virtual_balance -= total_price
                    user.save()

                    Transaction.objects.create(
                        user=user,
                        symbol=order.symbol,
                        quantity=order.quantity,
                        price_per_stock=stock_price,
                        total_price=total_price,
                        transaction_type="BUY",
                    )

                    portfolio, created = Portfolio.objects.get_or_create(user=user, symbol=order.symbol)

                    # Corrected average price calculation
                    if created:
                        portfolio.quantity = order.quantity
                        portfolio.average_price = stock_price
                    else:
                        total_shares = portfolio.quantity + order.quantity
                        portfolio.average_price = ((portfolio.quantity * portfolio.average_price) + total_price) / total_shares
                        portfolio.quantity = total_shares

                    portfolio.save()
                    order.status = "EXECUTED"
                    order.save()

                    # If the order had a stop-loss price, create a corresponding SELL order
                    if order.stop_loss_price and order.stop_loss_price > 0:
                        PendingOrder.objects.create(
                            user=user,
                            symbol=order.symbol,
                            quantity=order.quantity,
                            stop_loss_price=order.stop_loss_price,
                            status="PENDING",
                            order_type="SELL",
                        )

                    logger.info(f"BUY order executed: {order.symbol} at ₹{stock_price}")

            # SELL Order Execution (Normal Limit Sell)
            elif order.order_type == "SELL" and stock_price >= order.target_price:
                execute_sell_order(order, stock_price)

            # Stop-Loss Execution
            elif order.order_type == "SELL" and order.stop_loss_price and stock_price <= order.stop_loss_price:
                execute_sell_order(order, stock_price)


def execute_sell_order(order, stock_price):
    """Helper function to execute sell orders (normal sell & stop-loss)."""
    user = order.user
    portfolio_entry = Portfolio.objects.filter(user=user, symbol=order.symbol).first()

    if portfolio_entry and portfolio_entry.quantity >= order.quantity:
        portfolio_entry.quantity -= order.quantity

        if portfolio_entry.quantity == 0:
            portfolio_entry.delete()
        else:
            portfolio_entry.save()

        total_price = stock_price * order.quantity
        user.virtual_balance += total_price
        user.save()

        Transaction.objects.create(
            user=user,
            symbol=order.symbol,
            quantity=order.quantity,
            price_per_stock=stock_price,
            total_price=total_price,
            transaction_type="SELL",
        )

        order.status = "EXECUTED"
        order.save()

        logger.info(f"SELL order executed: {order.symbol} at ₹{stock_price}")

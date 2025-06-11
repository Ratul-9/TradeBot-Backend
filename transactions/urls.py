from django.urls import path
from .views import buy_stock, sell_stock, transaction_history, portfolio_view, order_book_view

urlpatterns = [
    path("buy/", buy_stock, name="buy_stock"),
    path("sell/", sell_stock, name="sell-stock"),
    path("history/", transaction_history, name="transaction_history"),
    path("portfolio/", portfolio_view, name="portfolio_view"),
    path("order-book/", order_book_view, name="oder_book_view")
]

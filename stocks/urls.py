from django.urls import path
from .views import get_stock_data, get_historical_stock_data, search_stock

urlpatterns = [
    path('price/<str:symbol>/', get_stock_data, name='get_stock_data'),
    path('history/<str:symbol>/', get_historical_stock_data, name='get-historical-stock-data'),
    path('search/', search_stock, name='search_stock'),
]
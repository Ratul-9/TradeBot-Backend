from django.urls import path
from .views import (
    CreateRoomView,
    JoinRoomView,
    LeaveRoomView,
    RoomDetailView,
    RoomTradeBuyView,
    RoomTradeSellView,
    RoomLeaderboardView,
    RoomTradeHistoryView,
    RoomCloseView,
    ParticipantView,
    LiveRoomView,
    StockSearchView,
    HistoricalDataView,
    StockDataView,
    UserPortfolioView,
    OrderHistoryView,
    MarketStatusView,
    HealthCheckView,
)

urlpatterns = [
    # Room management
    path('create/', CreateRoomView.as_view(), name='create-room'),        #Working
    path('<int:room_id>/join/', JoinRoomView.as_view(), name='join-room'), #Working
    path('<int:room_id>/leave/', LeaveRoomView.as_view(), name='leave-room'), #Working
    path('<int:room_id>/details/', RoomDetailView.as_view(), name='room-details'), #Working
    path('<int:room_id>/close/', RoomCloseView.as_view(), name='close-room'), #Working
    path('<int:room_id>/status/', LiveRoomView.as_view(), name='status'), #working
    path('<int:room_id>/participants/', ParticipantView.as_view(), name='participants'), #Working
    
    # Trading operations
    path('<int:room_id>/buy/', RoomTradeBuyView.as_view(), name='buy'), #Working
    path('<int:room_id>/sell/', RoomTradeSellView.as_view(), name='sell'), #Working
    path('<int:room_id>/leaderboard/', RoomLeaderboardView.as_view(), name='leaderboard'), #Working
    path('<int:room_id>/tradehistory/', RoomTradeHistoryView.as_view(), name='trade-record'), #Working
    
    # Portfolio and orders
    path('<int:room_id>/portfolio/', UserPortfolioView.as_view(), name='user-portfolio'), #Working
    path('<int:room_id>/orders/', OrderHistoryView.as_view(), name='order-history'), #Working
    
    # Market data
    path('<int:room_id>/stockData/', StockDataView.as_view(), name='market-data'), #Working
    path('<int:room_id>/historical-data/', HistoricalDataView.as_view(), name='historical-data'), #Working
    path('market-status/', MarketStatusView.as_view(), name='market-status'), #Working
    
    # Stock search and lookup
    path('<int:room_id>/search/', StockSearchView.as_view(), name='search-stock'),
    
    # User management
    
    # Utility endpoints
    path('health/', HealthCheckView.as_view(), name='health-check'), #Working
]
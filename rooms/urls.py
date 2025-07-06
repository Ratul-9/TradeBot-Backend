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
    LiveRoomStatusView,
    AdminUserRoomDetailsView,
    UserMeView

)


urlpatterns = [
    path('create/', CreateRoomView.as_view(), name='create-room'),
    path('<int:room_id>/join/', JoinRoomView.as_view(), name='join-room'),
    path('<int:room_id>/leave/', LeaveRoomView.as_view(), name='leave-room'),
    path('<int:room_id>/details/', RoomDetailView.as_view(), name='room-details'),
    path('<int:room_id>/buy/', RoomTradeBuyView.as_view(), name='Buy'),
    path('<int:room_id>/sell/', RoomTradeSellView.as_view(), name='Sell'),
    path('<int:room_id>/leaderboard/', RoomLeaderboardView.as_view(), name='leaderboard'),
    path('<int:room_id>/tradehistory/', RoomTradeHistoryView.as_view(), name='Trade-Record'),
    path('<int:room_id>/status/', LiveRoomStatusView.as_view(), name='status'),
    path('<int:room_id>/user-details/<int:user_id>/', AdminUserRoomDetailsView.as_view(), name='admin-user-room-details'),
    path('users/me/', UserMeView.as_view(), name='user-me'),

]
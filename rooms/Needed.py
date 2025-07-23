## 1.
# class AdminUserRoomDetailsView(APIView):
#     permission_classes = [IsAuthenticated]

#     def get(self, request, room_id, user_id):
#         room = get_object_or_404(Room, id=room_id)
#         if request.user != room.admin:
#             return Response({"error": "Only the admin can view user details."}, status=403)

#         check_and_close_room(room)
#         if room.is_closed:
#             return Response({"error": "Room is closed. This view is only available during live sessions."}, status=403)

#         user = get_object_or_404(User, id=user_id)

#         # Use trading service to get comprehensive user portfolio summary
#         portfolio_summary = trading_service.get_user_portfolio_summary(user, room)

#         # Get detailed holdings
#         from .models import UserPortfolio
#         portfolios = UserPortfolio.objects.filter(user=user, room=room, total_quantity__gt=0)
        
#         holdings = []
#         for portfolio in portfolios:
#             # Get current market data for each holding
#             # market_data = market_service.get_market_data(portfolio.symbol)
#             # current_price = market_data['ltp'] if market_data else portfolio.average_buy_price
            
#             holdings.append({
#                 "symbol": portfolio.symbol,
#                 "quantity": portfolio.total_quantity,
#                 "average_buy_price": str(portfolio.average_buy_price),
#                 # "current_price": str(current_price),
#                 "total_buy_value": str(portfolio.total_buy_value),
#                 # "current_value": str(portfolio.total_quantity * current_price),
#                 # "unrealized_pnl": str(portfolio.calculate_unrealized_pnl(current_price))
#             })

#         trades = Trade.objects.filter(user=user, room=room).order_by('-trade_timestamp')[:20]
#         trade_history = [
#             {
#                 "symbol": trade.symbol,
#                 "type": trade.trade_type,
#                 "quantity": trade.quantity,
#                 "price": str(trade.price),
#                 "total_value": str(trade.total_value),
#                 "timestamp": trade.trade_timestamp
#             }
#             for trade in trades
#         ]

#         return Response({
#             "username": user.username,
#             "portfolio_summary": portfolio_summary,
#             "stock_holdings": holdings,
#             "trade_history": trade_history,
#         }, status=200)
# 

# 2.
# class UserMeView(APIView):
#     permission_classes = [IsAuthenticated]

#     def get(self, request):
#         user = request.user
#         return Response({
#             "username": user.username,
#             "email": user.email,
#             "is_staff": user.is_staff,
#             "is_superuser": user.is_superuser
#         })
    

# 3.
# class RoomByNameView(APIView):
#     permission_classes = [IsAuthenticated]

#     def get(self, request, room_name):
#         try:
#             # Look for room by name (case-insensitive)
#             room = Room.objects.filter(name__iexact=room_name).first()
            
#             # If not found by name, try by code (if you have a code field)
#             if not room:
#                 room = Room.objects.filter(code__iexact=room_name).first()
            
#             if not room:
#                 return Response({'error': 'Room not found'}, status=status.HTTP_404_NOT_FOUND)

#             return Response({
#                 'id': room.id,
#                 'name': room.name,
#                 'code': getattr(room, 'code', None),  
#                 'has_password': bool(room.password),  
#             }, status=status.HTTP_200_OK)

#         except Exception as e:
#             return Response({'error': 'Failed to lookup room'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 4.
# class CancelOrderView(APIView):
#     """
#     New view to cancel pending orders
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, room_id, order_id):
#         try:
#             room = Room.objects.filter(id=room_id).first()
#             if not room:
#                 return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

#             participant = RoomParticipant.objects.filter(
#                 user=request.user, 
#                 room=room, 
#                 is_active=True
#             ).first()
#             if not participant:
#                 return Response({
#                     "error": "You are not an active participant in this room"
#                 }, status=status.HTTP_403_FORBIDDEN)

#             # Get the order
#             try:
#                 order = OrderBook.objects.get(id=order_id, user=request.user, room=room)
#             except OrderBook.DoesNotExist:
#                 return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

#             reason = request.data.get('reason', '')

#             # Use trading service to cancel the order
#             success, message = trading_service.cancel_order(order, reason)

#             if success:
#                 return Response({"message": message}, status=status.HTTP_200_OK)
#             else:
#                 return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

#         except Exception as e:
#             return Response({
#                 "error": f"An error occurred: {str(e)}"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# # Keep the existing historical data views as they are working well


# 5.
#Need Doing
# class PendingOrdersView(APIView):
#     """
#     View to get only pending orders for a user
#     """
#     permission_classes = [IsAuthenticated]

#     def get(self, request, room_id):
#         try:
#             room = Room.objects.filter(id=room_id).first()
#             if not room:
#                 return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

#             participant = RoomParticipant.objects.filter(
#                 user=request.user, 
#                 room=room, 
#                 is_active=True
#             ).first()
#             if not participant:
#                 return Response({
#                     "error": "You are not an active participant in this room"
#                 }, status=status.HTTP_403_FORBIDDEN)

#             # Get only pending orders
#             pending_orders = OrderBook.objects.filter(
#                 user=request.user, 
#                 room=room, 
#                 order_status=OrderBook.PENDING
#             ).order_by('-order_timestamp')

#             orders_data = []
#             for order in pending_orders:
#                 orders_data.append({
#                     "id": order.id,
#                     "symbol": order.symbol,
#                     "order_type": order.order_type,
#                     "order_category": order.order_category,
#                     "quantity": order.quantity,
#                     "order_price": str(order.order_price),
#                     "order_timestamp": order.order_timestamp,
#                     "notes": order.notes
#                 })

#             return Response({
#                 "room": {
#                     "id": room.id,
#                     "name": room.name
#                 },
#                 "pending_orders": orders_data,
#                 "count": len(orders_data)
#             }, status=status.HTTP_200_OK)

#         except Exception as e:
#             return Response({
#                 "error": f"An error occurred: {str(e)}"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 6.
# class UserRoomsView(APIView):
#     """
#     View to get all rooms where user is a participant
#     """
#     permission_classes = [IsAuthenticated]

#     def get(self, request):
#         try:
#             user = request.user

#             # Get rooms where user is an active participant
#             participant_rooms = RoomParticipant.objects.filter(
#                 user=user, 
#                 is_active=True
#             ).select_related('room').order_by('-join_time')

#             # Get rooms where user is admin
#             admin_rooms = Room.objects.filter(admin=user).order_by('-created_at')

#             rooms_data = []
            
#             # Add participant rooms
#             for participant in participant_rooms:
#                 room = participant.room
#                 rooms_data.append({
#                     "id": room.id,
#                     "name": room.name,
#                     "role": "participant",
#                     "is_closed": room.is_closed,
#                     "start_time": room.start_time,
#                     "end_time": room.end_time,
#                     "join_time": participant.join_time,
#                     "admin": room.admin.username
#                 })

#             # Add admin rooms (avoid duplicates)
#             participant_room_ids = {p.room.id for p in participant_rooms}
#             for room in admin_rooms:
#                 if room.id not in participant_room_ids:
#                     rooms_data.append({
#                         "id": room.id,
#                         "name": room.name,
#                         "role": "admin",
#                         "is_closed": room.is_closed,
#                         "start_time": room.start_time,
#                         "end_time": room.end_time,
#                         "join_time": None,
#                         "admin": room.admin.username
#                     })

#             # Sort by most recent activity
#             rooms_data.sort(key=lambda x: x.get('join_time') or timezone.now(), reverse=True)

#             return Response({
#                 "rooms": rooms_data,
#                 "count": len(rooms_data)
#             }, status=status.HTTP_200_OK)

#         except Exception as e:
#             return Response({
#                 "error": f"An error occurred: {str(e)}"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



# 7.
# class PlaceLimitOrderView(APIView):
#     """
#     View to place limit orders (not executed immediately)
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, room_id):
#         try:
#             user = request.user
#             data = request.data

#             room = Room.objects.filter(id=room_id).first()
#             if not room:
#                 return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

#             now = timezone.now()
#             check_and_close_room(room)
#             if room.is_closed:
#                 return Response({"error": "Room is closed, no more trades allowed"}, status=403)

#             if not (room.start_time and room.end_time and room.start_time <= now <= room.end_time):
#                 return Response({"error": "Room is not active yet"}, status=403)

#             participant = RoomParticipant.objects.filter(user=user, room=room, is_active=True).first()
#             if not participant:
#                 return Response({"error": "You are not an active participant in this room"}, status=status.HTTP_403_FORBIDDEN)

#             # Extract order data
#             symbol = data.get("symbol")
#             quantity = int(data.get("quantity", 0))
#             price_per_stock = Decimal(data.get("price_per_stock", 0))
#             order_type = data.get("order_type", "").upper()

#             if not symbol or quantity <= 0 or price_per_stock <= 0:
#                 return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)

#             if order_type not in [OrderBook.BUY, OrderBook.SELL]:
#                 return Response({"error": "Invalid order type"}, status=status.HTTP_400_BAD_REQUEST)

#             # Prepare order data for trading service
#             order_data = {
#                 'order_type': order_type,
#                 'symbol': symbol,
#                 'quantity': quantity,
#                 'order_price': price_per_stock,
#                 'order_category': OrderBook.LIMIT,  # Limit order
#             }

#             # Use trading service to place the order
#             success, message, order = trading_service.place_order(user, room, order_data)

#             if success:
#                 return Response({
#                     "message": message,
#                     "order_id": order.id if order else None,
#                     "order_status": "pending"
#                 }, status=status.HTTP_201_CREATED)
#             else:
#                 return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

#         except ValueError as e:
#             return Response({"error": f"Invalid data format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
#         except Exception as e:
#             return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 8.
# class BulkCancelOrdersView(APIView):
#     """
#     View to cancel multiple pending orders at once
#     """
#     permission_classes = [IsAuthenticated]

#     def post(self, request, room_id):
#         try:
#             room = Room.objects.filter(id=room_id).first()
#             if not room:
#                 return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

#             participant = RoomParticipant.objects.filter(
#                 user=request.user, 
#                 room=room, 
#                 is_active=True
#             ).first()
#             if not participant:
#                 return Response({
#                     "error": "You are not an active participant in this room"
#                 }, status=status.HTTP_403_FORBIDDEN)

#             order_ids = request.data.get('order_ids', [])
#             if not order_ids or not isinstance(order_ids, list):
#                 return Response({
#                     "error": "order_ids array is required"
#                 }, status=status.HTTP_400_BAD_REQUEST)

#             if len(order_ids) > 20:  # Limit bulk operations
#                 return Response({
#                     "error": "Maximum 20 orders can be cancelled at once"
#                 }, status=status.HTTP_400_BAD_REQUEST)

#             reason = request.data.get('reason', 'Bulk cancellation')
            
#             cancelled_orders = []
#             failed_orders = []

#             for order_id in order_ids:
#                 try:
#                     order = OrderBook.objects.get(id=order_id, user=request.user, room=room)
#                     success, message = trading_service.cancel_order(order, reason)
                    
#                     if success:
#                         cancelled_orders.append({
#                             "order_id": order_id,
#                             "symbol": order.symbol,
#                             "status": "cancelled"
#                         })
#                     else:
#                         failed_orders.append({
#                             "order_id": order_id,
#                             "error": message
#                         })
                        
#                 except OrderBook.DoesNotExist:
#                     failed_orders.append({
#                         "order_id": order_id,
#                         "error": "Order not found"
#                     })
#                 except Exception as e:
#                     failed_orders.append({
#                         "order_id": order_id,
#                         "error": str(e)
#                     })

#             return Response({
#                 "message": f"Processed {len(order_ids)} orders",
#                 "cancelled": cancelled_orders,
#                 "failed": failed_orders,
#                 "cancelled_count": len(cancelled_orders),
#                 "failed_count": len(failed_orders)
#             }, status=status.HTTP_200_OK)

#         except Exception as e:
#             return Response({
#                 "error": f"An error occurred: {str(e)}"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# 9. 
# class RoomStatsView(APIView):
#     """
#     View to get overall room statistics
#     """
#     permission_classes = [IsAuthenticated]

#     def get(self, request, room_id):
#         try:
#             room = Room.objects.filter(id=room_id).first()
#             if not room:
#                 return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

#             # Check if user is admin or participant
#             is_admin = request.user == room.admin
#             participant = RoomParticipant.objects.filter(
#                 user=request.user, 
#                 room=room, 
#                 is_active=True
#             ).first()

#             if not is_admin and not participant:
#                 return Response({
#                     "error": "You don't have access to this room"
#                 }, status=status.HTTP_403_FORBIDDEN)

#             # Get room statistics
#             total_participants = RoomParticipant.objects.filter(room=room, is_active=True).count()
#             total_trades = Trade.objects.filter(room=room).count()
#             total_volume = Trade.objects.filter(room=room).aggregate(
#                 total=Sum('total_value')
#             )['total'] or Decimal('0')

#             # Get most active stocks
#             popular_stocks = Trade.objects.filter(room=room).values('symbol').annotate(
#                 trade_count=models.Count('id'),
#                 total_volume=Sum('total_value')
#             ).order_by('-trade_count')[:10]

#             # Get top traders (only if admin)
#             top_traders = []
#             if is_admin:
#                 leaderboard = trading_service.get_room_leaderboard(room)
#                 top_traders = leaderboard[:5]  # Top 5 traders

#             return Response({
#                 "room": {
#                     "id": room.id,
#                     "name": room.name,
#                     "is_closed": room.is_closed,
#                     "start_time": room.start_time,
#                     "end_time": room.end_time
#                 },
#                 "statistics": {
#                     "total_participants": total_participants,
#                     "total_trades": total_trades,
#                     "total_volume": str(total_volume),
#                     "popular_stocks": list(popular_stocks),
#                     "top_traders": top_traders if is_admin else []
#                 },
#                 "user_role": "admin" if is_admin else "participant"
#             }, status=status.HTTP_200_OK)

#         except Exception as e:
#             return Response({
#                 "error": f"An error occurred: {str(e)}"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

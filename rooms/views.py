from rest_framework.views import APIView
import upstox_client
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import models
from django.db.models import Sum
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import Room, RoomParticipant, UserBalance, Trade
from .serializers import RoomSerializer, JoinRoomSerializer, LeaveRoomSerializer, LiveRoomStatusSerializer, CloseRoomSerializer
from django.contrib.auth import get_user_model
from rest_framework import permissions, status
from .utils import check_and_close_room
from transactions.models import Transaction, Portfolio, PendingOrder
from decimal import Decimal
from django.db.models import Sum, F, Case, When, DecimalField
from django.db.models import ExpressionWrapper
from .models import Stock, SMEStock
from django.db.models import Q


User = get_user_model()

class CreateRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self,request):
        if not request.user.is_staff:
            return Response(
                {"detail": "Only staff members can create rooms."},
                status=status.HTTP_403_FORBIDDEN
            )
        data = request.data.copy()
        serializer = RoomSerializer(data=data)
        if serializer.is_valid():
            serializer.save(admin=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
class JoinRoomView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, room_id):
        serializer = JoinRoomSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        password = serializer.validated_data.get('password', '')

        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({'error': 'Room does not exist'}, status=status.HTTP_404_NOT_FOUND)

        if room.password and room.password != password:
            return Response({'error': 'Incorrect password'}, status=status.HTTP_403_FORBIDDEN)

        user = request.user

        # Create or update participant
        participant, created = RoomParticipant.objects.get_or_create(
            user=user,
            room=room,
            defaults={'join_time': timezone.now(), 'is_active': True}
        )
        if not created:
            # If participant exists but is inactive, reactivate them
            if not participant.is_active:
                participant.is_active = True
                participant.join_time = timezone.now()
                participant.leave_time = None
                participant.save()
        user_balance, balance_created = UserBalance.objects.get_or_create(
            user=user,
            room=room,
            defaults={'cash_balance': 100000.00}  
        )
        if not balance_created:
            user_balance.cash_balance = 100000.00  
            user_balance.save()

        return Response({
            'message': f'Joined room "{room.name}" successfully.',
            'room': {
                'id': room.id,
                'name': room.name,
                'admin': room.admin.username,
                'start_time': room.start_time.isoformat() if room.start_time else None,
                'end_time': room.end_time.isoformat() if room.end_time else None,
            }
        }, status=status.HTTP_200_OK)
     
class LeaveRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):

        user = request.user

        try:
            participant = RoomParticipant.objects.get(user=user, room_id=room_id, is_active=True)
        except RoomParticipant.DoesNotExist:
            return Response({'error': 'You are not an active participant of this room.'}, status=status.HTTP_404_NOT_FOUND)

        participant.is_active = False
        participant.leave_time = timezone.now()
        participant.save()

        return Response({'message': f'You have successfully left the room.'}, status=status.HTTP_200_OK)

class RoomCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id, is_closed=False)
        except Room.DoesNotExist:
            return Response({"error": "Room does not exist or already closed."}, status=404)

        if request.user != room.admin:
            return Response({"error": "Only admin can close the room."}, status=403)

       
        room.is_closed = True
        room.save()

        
        RoomParticipant.objects.filter(room=room).exclude(user=room.admin).update(
            is_active=False,
            leave_time=timezone.now()
        )

        return Response({"message": "Room closed and all participants removed (except admin)."}, status=200)


from django.utils import timezone

class LiveRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": "Room Not  Found"}, status=status.HTTP_404_NOT_FOUND)
        
        room.refresh_from_db()
        availability = room.is_closed

        return Response({"is_closed" : availability} , status=status.HTTP_200_OK)

class ParticipantView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({'error' : 'Room Not Found'}, status=status.HTTP_404_NOT_FOUND)
        
        check_and_close_room(room)

        room.refresh_from_db()

        participants = RoomParticipant.objects.filter(room=room, is_active=True).order_by('join_time')
        participant_data = []

        for participant in participants:
            balance = UserBalance.objects.filter(user=participant.user, room=room).first()
            participant_data.append({

                'username': participant.user.username,
                'cash_balance': str(balance.cash_balance) if balance else "0.00",
                'join_time': participant.join_time,

            })
        
        return Response(participant_data, status=status.HTTP_200_OK)

class RoomDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({'error': 'Room not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Debug: Check room status and times
        now = timezone.now()
        print(f"=== Room Detail Debug ===")
        print(f"Room ID: {room_id}")
        print(f"Room name: {room.name}")
        print(f"Current time: {now}")
        print(f"Room start_time: {room.start_time}")
        print(f"Room end_time: {room.end_time}")
        print(f"is_closed BEFORE check: {room.is_closed}")
        print(f"Time until end: {room.end_time - now if room.end_time else 'No end time'}")
        print(f"Is time past end? {now > room.end_time if room.end_time else 'No end time'}")
        
        # Check and close room if needed
        check_and_close_room(room)
        
        # Refresh from database to get updated status
        room.refresh_from_db()
        print(f"is_closed AFTER check: {room.is_closed}")
        
        # Check if room is closed and user is not admin
        if room.is_closed and request.user != room.admin:
            print(f"Room is closed and user {request.user.username} is not admin {room.admin.username}")
            return Response({"error": "Room is closed"}, status=403)

        participants = RoomParticipant.objects.filter(room=room, is_active=True)
        participant_data = []

        for participant in participants:
            balance = UserBalance.objects.filter(user=participant.user, room=room).first()
            participant_data.append({
                'username': participant.user.username,
                'cash_balance': str(balance.cash_balance) if balance else "0.00",
                'join_time': participant.join_time,
            })

        room_info = {
            'id': room.id,
            'name': room.name,
            'room_name': room.name,
            'admin': room.admin.username,
            'start_time': room.start_time,
            'end_time': room.end_time,
            'is_closed': room.is_closed,
            'active_participants': participant_data
        }

        print(f"Returning room info successfully")
        return Response(room_info, status=status.HTTP_200_OK)
    
class RoomTradeBuyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        try:
            user = request.user
            data = request.data

            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            
            now = timezone.now()
            check_and_close_room(room)
            if room.is_closed:
                return Response({"error": "Room is closed, no more trades allowed"}, status=403)

            if not (room.start_time and room.end_time and room.start_time <= now <= room.end_time):
                return Response({"error": "Room is not active yet"}, status=403)

            
            participant = RoomParticipant.objects.filter(user=user, room=room, is_active=True).first()
            if not participant:
                return Response({"error": "You are not an active participant in this room"}, status=status.HTTP_403_FORBIDDEN)

            
            symbol = data.get("symbol")
            quantity = int(data.get("quantity", 0))
            price_per_stock = Decimal(data.get("price_per_stock", 0))

            if not symbol or quantity <= 0 or price_per_stock <= 0:
                return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)

            total_price = quantity * price_per_stock

            
            user_balance = UserBalance.objects.filter(user=user, room=room).first()
            if not user_balance:
                return Response({"error": "User balance not found for this room"}, status=status.HTTP_404_NOT_FOUND)

            if user_balance.cash_balance < total_price:
                return Response({"error": "Insufficient balance in this room"}, status=status.HTTP_400_BAD_REQUEST)

            
            user_balance.cash_balance -= total_price
            user_balance.save()

            
            trade = Trade.objects.create(
                user=user,
                room=room,
                trade_type="BUY",
                symbol=symbol,
                quantity=quantity,
                price=price_per_stock,
            )

            return Response({"message": "Trade executed successfully", "trade_id": trade.id}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RoomTradeSellView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, room_id):
        try:
            user = request.user
            data = request.data

            
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            
            now = timezone.now()
            check_and_close_room(room)
            if room.is_closed:
                return Response({"error": "Room is closed, no more trades allowed"}, status=403)
            
            if not (room.start_time and room.end_time and room.start_time <= now <= room.end_time):
                return Response({"error": "Room is not active yet"}, status=403)

            
            participant = RoomParticipant.objects.filter(user=user, room=room, is_active=True).first()
            if not participant:
                return Response({"error": "You are not an active participant in this room"}, status=status.HTTP_403_FORBIDDEN)

            symbol = data.get("symbol")
            quantity = int(data.get("quantity", 0))
            price_per_stock = Decimal(data.get("price_per_stock", 0))

            if not symbol or quantity <= 0 or price_per_stock <= 0:
                return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)

            
            total_bought = Trade.objects.filter(user=user, room=room, symbol=symbol, trade_type="BUY").aggregate(total=models.Sum("quantity"))["total"] or 0
            total_sold = Trade.objects.filter(user=user, room=room, symbol=symbol, trade_type="SELL").aggregate(total=models.Sum("quantity"))["total"] or 0

            available_quantity = total_bought - total_sold

            if available_quantity < quantity:
                return Response({"error": "Not enough holdings to sell"}, status=status.HTTP_400_BAD_REQUEST)

            
            total_price = quantity * price_per_stock
            user_balance = UserBalance.objects.filter(user=user, room=room).first()

            if not user_balance:
                return Response({"error": "User balance not found for this room"}, status=status.HTTP_404_NOT_FOUND)

            user_balance.cash_balance += total_price
            user_balance.save()

            
            trade = Trade.objects.create(
                user=user,
                room=room,
                trade_type="SELL",
                symbol=symbol,
                quantity=quantity,
                price=price_per_stock,
            )

            return Response({"message": "Sell trade executed successfully", "trade_id": trade.id}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RoomLeaderboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)

        
        check_and_close_room(room)

        
        now = timezone.now()

        
        if room.end_time and now > room.end_time and request.user != room.admin:
            return Response({"error": "Room is closed. Only the admin can view the leaderboard."}, status=403)

        
        participants = RoomParticipant.objects.filter(room=room)
        leaderboard = []

        for participant in participants:
            user = participant.user
            trades = Trade.objects.filter(user=user, room=room)

            pnl = 0
            for trade in trades:
                if trade.trade_type == Trade.BUY:
                    pnl -= trade.quantity * float(trade.price)
                elif trade.trade_type == Trade.SELL:
                    pnl += trade.quantity * float(trade.price)

            try:
                balance = UserBalance.objects.get(user=user, room=room)
                total_value = pnl + float(balance.cash_balance)
            except UserBalance.DoesNotExist:
                total_value = pnl

            leaderboard.append({
                "username": user.username,
                "net_worth": round(total_value, 2)
            })

        leaderboard.sort(key=lambda x: x["net_worth"], reverse=True)

        return Response({
            "room": room.name,
            "is_closed": room.is_closed,
            "leaderboard": leaderboard
        }, status=200)

    
class RoomTradeHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)

        user = request.user
        trades = Trade.objects.filter(user=user, room=room).order_by("-timestamp")

        trade_history = [
            {
                "symbol": trade.symbol,
                "trade_type": trade.trade_type,
                "quantity": trade.quantity,
                "price": str(trade.price),
                "timestamp": trade.timestamp,
            }
            for trade in trades
        ]

        return Response({
            "room": room.name,
            "username": user.username,
            "trade_history": trade_history
        }, status=200)
    




class AdminUserRoomDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id, user_id):
        room = get_object_or_404(Room, id=room_id)
        if request.user != room.admin:
            return Response({"error": "Only the admin can view user details."}, status=403)

        check_and_close_room(room)
        if room.is_closed:
            return Response({"error": "Room is closed. This view is only available during live sessions."}, status=403)

        user = get_object_or_404(User, id=user_id)

        trades = Trade.objects.filter(user=user, room=room)
        holdings = {}
        for trade in trades:
            if trade.symbol not in holdings:
                holdings[trade.symbol] = 0
            if trade.trade_type == Trade.BUY:
                holdings[trade.symbol] += trade.quantity
            else:
                holdings[trade.symbol] -= trade.quantity

        portfolio = [
            {"symbol": sym, "quantity": qty} for sym, qty in holdings.items() if qty > 0
        ]

        trade_history = [
            {
                "symbol": trade.symbol,
                "type": trade.trade_type,
                "quantity": trade.quantity,
                "price": str(trade.price),
                "timestamp": trade.timestamp
            }
            for trade in trades.order_by('-timestamp')
        ]

        user_balance = UserBalance.objects.filter(user=user, room=room).first()
        cash_balance = float(user_balance.cash_balance) if user_balance else 0

        total_buy = sum(trade.quantity * float(trade.price) for trade in trades if trade.trade_type == "BUY")
        total_sell = sum(trade.quantity * float(trade.price) for trade in trades if trade.trade_type == "SELL")
        pnl = total_sell - total_buy
        net_worth = cash_balance + pnl

        return Response({
            "username": user.username,
            "portfolio_value": round(net_worth, 2),
            "cash_balance": cash_balance,
            "stock_holdings": portfolio,
            "trade_history": trade_history,
        }, status=200)
    
class UserMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            "username": user.username,
            "email": user.email,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser
        })
    
class RoomByNameView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_name):
        try:
            # Look for room by name (case-insensitive)
            room = Room.objects.filter(name__iexact=room_name).first()
            
            # If not found by name, try by code (if you have a code field)
            if not room:
                room = Room.objects.filter(code__iexact=room_name).first()
            
            if not room:
                return Response({'error': 'Room not found'}, status=status.HTTP_404_NOT_FOUND)

            return Response({
                'id': room.id,
                'name': room.name,
                'code': getattr(room, 'code', None),  # If you have a code field
                'has_password': bool(room.password),  # Don't return the actual password
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({'error': 'Failed to lookup room'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class StockSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            search_query = request.GET.get('q', '').strip().upper()
            limit = min(int(request.GET.get('limit', 20)), 100)

            if not search_query:
                return Response({
                    'error': 'Please Provide search query using q parameter'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if len(search_query) < 1:
                return Response({
                    'error': 'Search query must be at least 1 character long'
                }, status=status.HTTP_400_BAD_REQUEST)

            results = []

            # Search normal stocks
            normal_stocks = Stock.objects.filter(
                Q(symbol__icontains=search_query) |
                Q(name_of_company__icontains=search_query)
            ).values('symbol', 'name_of_company', 'series')[:limit//2]

            for stock in normal_stocks:
                results.append({
                    'symbol': stock['symbol'],  # ✅ Fixed: lowercase key
                    'name_of_company': stock['name_of_company'],  # ✅ Fixed: lowercase key with underscore
                    'series': stock['series'],  # ✅ Fixed: lowercase key
                    'type': 'NSE'
                })

            # Search SME stocks with remaining limit
            remaining_limit = limit - len(results)
            if remaining_limit > 0:
                sme_stocks = SMEStock.objects.filter(
                    Q(symbol__icontains=search_query) |
                    Q(name_of_company__icontains=search_query)
                ).values('symbol', 'name_of_company', 'series')[:remaining_limit]

                for stock in sme_stocks:
                    results.append({
                        'symbol': stock['symbol'],  # ✅ Fixed: lowercase key
                        'name_of_company': stock['name_of_company'],  # ✅ Fixed: lowercase key with underscore
                        'series': stock['series'],  # ✅ Fixed: lowercase key
                        'type': 'SME'
                    })

            # Sort results by symbol for consistent ordering
            results.sort(key=lambda x: x['symbol'])  # ✅ Fixed: lowercase key

            return Response({
                'query': search_query,
                'count': len(results),
                'stocks': results  # ✅ Changed from 'results' to 'stocks' to match frontend expectation
            }, status=status.HTTP_200_OK)
        
        except ValueError:
            return Response({
                'error': 'Invalid limit parameter. Must be a number.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        except Exception as e:
            return Response({
                'error': f'An error occurred while searching: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class HistoricalDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            # Verify room exists and user has access
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            # Check if user is active participant in the room
            participant = RoomParticipant.objects.filter(
                user=request.user, 
                room=room, 
                is_active=True
            ).first()
            if not participant:
                return Response({
                    "error": "You are not an active participant in this room"
                }, status=status.HTTP_403_FORBIDDEN)

            # Get query parameters
            symbol = request.GET.get('symbol', '').strip()
            time_interval = request.GET.get('time_interval', '1D')  # Default to 1 Day

            # Validate required parameters
            if not symbol:
                return Response({
                    "error": "Symbol parameter is required"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Look up ISIN number from database based on symbol
            try:
                # First try to find in regular stocks
                stock = Stock.objects.filter(symbol=symbol).first()
                if stock:
                    isin = stock.isin_number
                    exchange = "NSE_EQ"  # Regular NSE stock
                else:
                    # Try SME stocks
                    sme_stock = SMEStock.objects.filter(symbol=symbol).first()
                    if sme_stock:
                        isin = sme_stock.isin_number
                        exchange = "NSE_SME"  # SME stock
                    else:
                        return Response({
                            "error": f"Stock symbol '{symbol}' not found in database"
                        }, status=status.HTTP_404_NOT_FOUND)

                # Create instrument key in Upstox format
                instrument_key = f"{exchange}|{isin}"

            except Exception as e:
                return Response({
                    "error": f"Error looking up stock information: {str(e)}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Define time interval mappings
            time_interval_mapping = {
                '1D': {'days': 1, 'name': '1 Day', 'interval': 'minute', 'interval_value': '1'},
                '1W': {'days': 7, 'name': '1 Week', 'interval': 'minute', 'interval_value': '5'},
                '1M': {'days': 30, 'name': '1 Month', 'interval': 'minute', 'interval_value': '30'},
                '3M': {'days': 90, 'name': '3 Months', 'interval': 'day', 'interval_value': '1'},
                '6M': {'days': 180, 'name': '6 Months', 'interval': 'day', 'interval_value': '1'},
                '1Y': {'days': 365, 'name': '1 Year', 'interval': 'day', 'interval_value': '1'},
                'YTD': {'ytd': True, 'name': 'Year to Date', 'interval': 'day', 'interval_value': '1'},
                'ALL': {'days': 365 * 2, 'name': 'All Time (2 Years)', 'interval': 'day', 'interval_value': '1'}
            }

            # Validate time interval
            if time_interval not in time_interval_mapping:
                return Response({
                    "error": f"Invalid time_interval. Available options: {', '.join(time_interval_mapping.keys())}",
                    "available_intervals": [
                        {"key": k, "name": v["name"]} for k, v in time_interval_mapping.items()
                    ]
                }, status=status.HTTP_400_BAD_REQUEST)

            # Calculate date range based on selected time interval
            from datetime import datetime, timedelta
            
            now = timezone.now()
            
            if time_interval == 'YTD':
                # Year to Date
                from_date = datetime(now.year, 1, 1).strftime('%Y-%m-%d')
                to_date = now.strftime('%Y-%m-%d')
            else:
                # Calculate from current date backwards
                days_back = time_interval_mapping[time_interval]['days']
                from_datetime = now - timedelta(days=days_back)
                from_date = from_datetime.strftime('%Y-%m-%d')
                to_date = now.strftime('%Y-%m-%d')

            # Get interval details for this time period
            interval_type = time_interval_mapping[time_interval]['interval']
            interval_value = time_interval_mapping[time_interval]['interval_value']

            # Configure Upstox client
            try:
                # Initialize the History V3 API
                apiInstance = upstox_client.HistoryV3Api()
                
                # Make API call using V3 format
                # Format: get_historical_candle_data1(instrument_key, interval, interval_value, to_date, from_date)
                response = apiInstance.get_historical_candle_data1(
                    instrument_key, 
                    interval_type, 
                    interval_value, 
                    to_date, 
                    from_date
                )

                # Process the response
                if response and hasattr(response, 'data') and response.data:
                    candles_data = response.data.get('candles', [])
                    
                    # Format the data for frontend consumption
                    formatted_data = []
                    for candle in candles_data:
                        if len(candle) >= 5:  # Ensure we have all required data
                            formatted_data.append({
                                'timestamp': candle[0],  # Unix timestamp
                                'datetime': datetime.fromtimestamp(candle[0]/1000).strftime('%Y-%m-%d %H:%M:%S') if candle[0] else None,
                                'open': float(candle[1]),
                                'high': float(candle[2]),
                                'low': float(candle[3]),
                                'close': float(candle[4]),
                                'volume': int(candle[5]) if len(candle) > 5 else 0
                            })

                    # Calculate basic statistics for the chart
                    statistics = {}
                    if formatted_data:
                        prices = [candle['close'] for candle in formatted_data]
                        first_price = formatted_data[0]['open']
                        last_price = formatted_data[-1]['close']
                        
                        statistics = {
                            'symbol': symbol,
                            'current_price': last_price,
                            'opening_price': first_price,
                            'highest_price': max(prices),
                            'lowest_price': min(prices),
                            'price_change': round(last_price - first_price, 2),
                            'price_change_percent': round(
                                ((last_price - first_price) / first_price) * 100, 2
                            ) if first_price > 0 else 0,
                            'total_volume': sum(candle['volume'] for candle in formatted_data),
                            'total_trades': len(formatted_data)
                        }

                    return Response({
                        "success": True,
                        "symbol": symbol,
                        "instrument_key": instrument_key,
                        "exchange": exchange,
                        "time_interval": time_interval,
                        "time_interval_name": time_interval_mapping[time_interval]['name'],
                        "interval_type": interval_type,
                        "interval_value": interval_value,
                        "from_date": from_date,
                        "to_date": to_date,
                        "data_points": len(formatted_data),
                        "statistics": statistics,
                        "chart_data": formatted_data  
                    }, status=status.HTTP_200_OK)

                else:
                    return Response({
                        "error": "No historical data found for the given parameters",
                        "symbol": symbol,
                        "instrument_key": instrument_key,
                        "time_interval": time_interval,
                        "suggestions": [
                            "Try a different time interval",
                            "Check if the stock was actively traded during this period",
                            "Verify the stock symbol is correct"
                        ]
                    }, status=status.HTTP_404_NOT_FOUND)

            except Exception as e:
                error_message = f"Upstox API Error: {str(e)}"
                
                # Handle specific Upstox API errors
                if "ApiException" in str(type(e)):
                    try:
                        import json
                        if hasattr(e, 'body') and e.body:
                            error_data = json.loads(e.body)
                            error_message = error_data.get('message', error_message)
                    except:
                        pass

                return Response({
                    "error": error_message,
                    "symbol": symbol,
                    "instrument_key": instrument_key if 'instrument_key' in locals() else None,
                    "time_interval": time_interval
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "error": f"An unexpected error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class TimeIntervalsView(APIView):
    """
    Helper view to get available time intervals for the frontend dropdown
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            # Verify room exists and user has access
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            participant = RoomParticipant.objects.filter(
                user=request.user, 
                room=room, 
                is_active=True
            ).first()
            if not participant:
                return Response({
                    "error": "You are not an active participant in this room"
                }, status=status.HTTP_403_FORBIDDEN)

            # Available time intervals for frontend dropdown
            time_intervals = [
                {
                    "key": "1D", 
                    "name": "1 Day", 
                    "description": "Intraday data with 1-minute intervals",
                    "best_for": "Day trading, short-term analysis"
                },
                {
                    "key": "1W", 
                    "name": "1 Week", 
                    "description": "Weekly data with 5-minute intervals",
                    "best_for": "Weekly trend analysis"
                },
                {
                    "key": "1M", 
                    "name": "1 Month", 
                    "description": "Monthly data with 30-minute intervals",
                    "best_for": "Short-term trend analysis"
                },
                {
                    "key": "3M", 
                    "name": "3 Months", 
                    "description": "Quarterly data with daily intervals",
                    "best_for": "Medium-term analysis"
                },
                {
                    "key": "6M", 
                    "name": "6 Months", 
                    "description": "Half-yearly data with daily intervals",
                    "best_for": "Medium to long-term analysis"
                },
                {
                    "key": "1Y", 
                    "name": "1 Year", 
                    "description": "Yearly data with daily intervals",
                    "best_for": "Long-term trend analysis"
                },
                {
                    "key": "YTD", 
                    "name": "Year to Date", 
                    "description": "From January 1st to current date",
                    "best_for": "Current year performance"
                },
                {
                    "key": "ALL", 
                    "name": "All Time", 
                    "description": "Maximum available historical data",
                    "best_for": "Complete historical analysis"
                }
            ]

            return Response({
                "time_intervals": time_intervals,
                "default_interval": "1D",
                "usage": {
                    "endpoint": f"/api/rooms/{room_id}/historical-data/",
                    "parameters": {
                        "symbol": "Stock symbol (required)",
                        "time_interval": "One of the available interval keys (optional, default: 1D)"
                    },
                    "example": f"/api/rooms/{room_id}/historical-data/?symbol=RELIANCE&time_interval=1W"
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StockLookupView(APIView):
    """
    Helper view to verify if a stock symbol exists and get its details
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            participant = RoomParticipant.objects.filter(
                user=request.user, 
                room=room, 
                is_active=True
            ).first()
            if not participant:
                return Response({
                    "error": "You are not an active participant in this room"
                }, status=status.HTTP_403_FORBIDDEN)

            symbol = request.GET.get('symbol', '').strip()
            if not symbol:
                return Response({
                    "error": "Symbol parameter is required"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Look up stock in database
            stock = Stock.objects.filter(symbol=symbol).first()
            if stock:
                return Response({
                    "found": True,
                    "symbol": stock.symbol,
                    "company_name": stock.name_of_company,
                    "isin": stock.isin_number,
                    "series": stock.series,
                    "exchange": "NSE",
                    "type": "Regular Stock",
                    "instrument_key": f"NSE_EQ|{stock.isin_number}"
                }, status=status.HTTP_200_OK)

            sme_stock = SMEStock.objects.filter(symbol=symbol).first()
            if sme_stock:
                return Response({
                    "found": True,
                    "symbol": sme_stock.symbol,
                    "company_name": sme_stock.name_of_company,
                    "isin": sme_stock.isin_number,
                    "series": sme_stock.series,
                    "exchange": "NSE_SME",
                    "type": "SME Stock",
                    "instrument_key": f"NSE_SME|{sme_stock.isin_number}"
                }, status=status.HTTP_200_OK)

            return Response({
                "found": False,
                "symbol": symbol,
                "message": "Stock symbol not found in our database"
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            return Response({
                "error": f"An error occurred during lookup: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from rest_framework.views import APIView
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

    def post(self, request):
        serializer = LeaveRoomSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        room_id = serializer.validated_data['room_id']
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
    
class LiveRoomStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, room_id):
        room = get_object_or_404(Room, id=room_id)

        # Check if request.user is the admin of this room
        if request.user != room.admin:
            return Response({"error": "You are not authorized to view this room's status."}, status=status.HTTP_403_FORBIDDEN)

        # Get active participants
        active_participants = RoomParticipant.objects.filter(room=room, is_active=True)

        participants_data = []

        for participant in active_participants:
            user = participant.user
            # Get user balance for this room
            user_balance_obj = UserBalance.objects.filter(user=user, room=room).first()
            cash_balance = user_balance_obj.cash_balance if user_balance_obj else 0

            # Calculate total bought and total sold by summing Transactions
            trades = Transaction.objects.filter(user=user, room=room)

            total_bought = trades.filter(transaction_type="BUY").annotate(
                total_value=ExpressionWrapper(F('quantity') * F('price'), output_field=DecimalField())
            ).aggregate(total=Sum('total_value'))['total'] or 0

            total_sold = trades.filter(transaction_type="SELL").annotate(
                total_value=ExpressionWrapper(F('quantity') * F('price'), output_field=DecimalField())
            ).aggregate(total=Sum('total_value'))['total'] or 0

            profit_loss = (total_sold or 0) - (total_bought or 0)

            participants_data.append({
                "username": user.username,
                "cash_balance": cash_balance,
                "total_bought": total_bought,
                "total_sold": total_sold,
                "profit_loss": profit_loss,
            })

        response_data = {
            "room_name": room.name,
            "participants": participants_data
        }

        serializer = LiveRoomStatusSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
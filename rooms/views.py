from rest_framework.views import APIView
import upstox_client
import requests
from django.utils import timezone
from rest_framework.response import Response
from upstox_client.rest import ApiException
from rest_framework.permissions import IsAuthenticated
from django.db import models
from django.db.models import Sum
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from .models import Room, RoomParticipant, UserBalance, Trade, OrderBook
from .serializers import RoomSerializer, JoinRoomSerializer
from django.contrib.auth import get_user_model
from rest_framework import permissions, status
from .utils import check_and_close_room
from .models import UserPortfolio
from decimal import Decimal, InvalidOperation
from django.db.models import Sum, F, Case, When, DecimalField
from django.db.models import ExpressionWrapper
from .models import Stock, SMEStock
from django.db.models import Q
import logging
from django.conf import settings

logger = logging.getLogger(__name__)
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

        participant, created = RoomParticipant.objects.get_or_create(
            user=user,
            room=room,
            defaults={'join_time': timezone.now(), 'is_active': True}
        )
        if not created:
            if not participant.is_active:
                participant.is_active = True
                participant.join_time = timezone.now()
                participant.leave_time = None
                participant.save()

        # Get or create user balance for this room
        user_balance, balance_created = UserBalance.objects.get_or_create(
            user=user,
            room=room,
            defaults={
                'total_cash_balance': Decimal('100000.00'),
                'reserved_cash_balance': Decimal('0.00')
            }
        )

        return Response({
            'message': f'Joined room "{room.name}" successfully.',
            'room': {
                'id': room.id,
                'name': room.name,
                'admin': room.admin.username,
                'start_time': room.start_time.isoformat() if room.start_time else None,
                'end_time': room.end_time.isoformat() if room.end_time else None,
            },
            'balance': {
                'total_cash': float(user_balance.total_cash_balance),
                'available_cash': float(user_balance.available_cash_balance),
                'reserved_cash': float(user_balance.reserved_cash_balance)
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

class LiveRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": "Room Not Found"}, status=status.HTTP_404_NOT_FOUND)
        
        room.refresh_from_db()
        availability = room.is_closed

        return Response({"is_closed": availability}, status=status.HTTP_200_OK)

class ParticipantView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({'error': 'Room Not Found'}, status=status.HTTP_404_NOT_FOUND)
        
        check_and_close_room(room)
        room.refresh_from_db()

        participants = RoomParticipant.objects.filter(room=room, is_active=True).order_by('join_time')
        participant_data = []

        for participant in participants:
            # Get or create user balance for this room
            balance, created = UserBalance.objects.get_or_create(
                user=participant.user,
                room=room,
                defaults={
                    'total_cash_balance': Decimal('100000.00'),
                    'reserved_cash_balance': Decimal('0.00')
                }
            )
            
            participant_data.append({
                'username': participant.user.username,
                'cash_balance': str(balance.available_cash_balance),
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
        

        check_and_close_room(room)
        
        
        room.refresh_from_db()
        print(f"is_closed AFTER check: {room.is_closed}")
      
        if room.is_closed and request.user != room.admin:
            print(f"Room is closed and user {request.user.username} is not admin {room.admin.username}")
            return Response({"error": "Room is closed"}, status=403)

        participants = RoomParticipant.objects.filter(room=room, is_active=True)
        participant_data = []

        for participant in participants:
            # Get or create user balance for this room
            balance, created = UserBalance.objects.get_or_create(
                user=participant.user,
                room=room,
                defaults={
                    'total_cash_balance': Decimal('100000.00'),
                    'reserved_cash_balance': Decimal('0.00')
                }
            )
            
            participant_data.append({
                'username': participant.user.username,
                'cash_balance': str(balance.available_cash_balance),
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

    def get_stock_name(self, symbol):
        """Get company name from symbol, fallback to symbol if not found"""
        try:
            # Check regular stocks first
            stock = Stock.objects.filter(symbol=symbol).first()
            if stock and hasattr(stock, 'name_of_company') and stock.name_of_company:
                return stock.name_of_company.strip()

            # Check SME stocks
            sme_stock = SMEStock.objects.filter(symbol=symbol).first()
            if sme_stock and hasattr(sme_stock, 'name_of_company') and sme_stock.name_of_company:
                return sme_stock.name_of_company.strip()

            # Fallback to symbol
            return symbol
        except Exception:
            return symbol

    def get_indianapi_stock_data(self, stock_name):
        """Fetch stock data from IndianAPI"""
        try:
            base_url = "https://stock.indianapi.in/stock"
            params = {'name': stock_name}
            headers = {
                "X-Api-Key": settings.INDIANAPI_KEY,
                "Content-Type": "application/json"
            }

            response = requests.get(
                base_url,
                headers=headers,  
                params=params
            )
            response.raise_for_status()
            data = response.json()

            # Validate response structure
            if not data:
                return None

            current_price = data.get('currentPrice', {})

            # Get LTP from NSE or BSE
            ltp = current_price.get('NSE') or current_price.get('BSE')
            if ltp is None:
                return None

            # Convert LTP to float safely
            try:
                ltp = float(ltp)
            except (ValueError, TypeError):
                return None

            return {
                'ltp': ltp,
                'company_name': data.get('companyName', ''),
            }

        except Exception:
            return None

    def create_stop_loss_order(self, user, room, symbol, quantity, stop_loss_price, stock_name, original_order_id):
        """Create a stop loss sell order"""
        try:
            stop_loss_order = OrderBook.objects.create(
                user=user,
                room=room,
                order_type=OrderBook.SELL,
                symbol=symbol,
                quantity=quantity,
                order_price=stop_loss_price,
                order_category=OrderBook.STOP_LOSS,  # You'll need to add this to your OrderBook model
                order_status=OrderBook.PENDING,
                executed_price=None,
                execution_timestamp=None,
                parent_order_id=original_order_id,  # Link to the original buy order
                stop_loss_price=stop_loss_price  # You'll need to add this field to your OrderBook model
            )
            return stop_loss_order
        except Exception as e:
            # Log the error for debugging
            print(f"Error creating stop loss order: {str(e)}")
            return None

    def post(self, request, room_id):
        try:
            user = request.user
            data = request.data

            # Validate room
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            # Check if room is active
            now = timezone.now()
            check_and_close_room(room)
            if room.is_closed:
                return Response({"error": "Room is closed, no more trades allowed"}, status=403)

            if not (room.start_time and room.end_time and room.start_time <= now <= room.end_time):
                return Response({"error": "Room is not active yet"}, status=403)

            # Validate participant
            participant = RoomParticipant.objects.filter(user=user, room=room, is_active=True).first()
            if not participant:
                return Response({"error": "You are not an active participant in this room"}, status=status.HTTP_403_FORBIDDEN)

            # Extract and validate input data
            symbol = data.get("symbol", "").strip().upper()
            quantity = int(data.get("quantity", 0))
            order_category = data.get("order_category", "").strip().upper()
            
            # New stop loss fields
            has_stop_loss = data.get("has_stop_loss", False)
            stop_loss_price = data.get("stop_loss_price")

            if not symbol or quantity <= 0:
                return Response({"error": "Invalid input: symbol and positive quantity are required"}, status=status.HTTP_400_BAD_REQUEST)
            
            if not order_category:
                return Response({"Error": "No order category selected"})

            # Validate stop loss if provided
            if has_stop_loss:
                if not stop_loss_price:
                    return Response({"error": "Stop loss price is required when stop loss is enabled"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    stop_loss_price = Decimal(str(stop_loss_price))
                    if stop_loss_price <= 0:
                        return Response({"error": "Stop loss price must be greater than 0"}, status=status.HTTP_400_BAD_REQUEST)
                except (ValueError, TypeError, InvalidOperation):
                    return Response({"error": "Invalid stop loss price format"}, status=status.HTTP_400_BAD_REQUEST)
            
            if order_category == "MARKET":
                stock_exists = Stock.objects.filter(symbol=symbol).exists()
                sme_exists = SMEStock.objects.filter(symbol=symbol).exists()

                if not (stock_exists or sme_exists):
                    return Response({
                        "error": f"Symbol '{symbol}' not found in our database"
                    }, status=status.HTTP_404_NOT_FOUND)

                # Get stock name and fetch current market price
                stock_name = self.get_stock_name(symbol)
                if not stock_name:
                    return Response({"error": "Stock name not found"}, status=status.HTTP_404_NOT_FOUND)
                
                stock_data = self.get_indianapi_stock_data(symbol)
                if not stock_data or not stock_data.get('ltp'):
                    return Response({
                        "error": "Unable to fetch current market price. Please try again later."
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                current_price = Decimal(str(stock_data['ltp']))
                
                # Validate stop loss price against current price for buy orders
                if has_stop_loss and stop_loss_price >= current_price:
                    return Response({
                        "error": "Stop loss price must be below the current market price for buy orders"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                total_cost = current_price * Decimal(quantity)  # Use Decimal for precision

                # Fetch or create user's balance for this room
                balance, created = UserBalance.objects.get_or_create(
                    user=user,
                    room=room,
                    defaults={
                        'total_cash_balance': Decimal('100000.00'),
                        'reserved_cash_balance': Decimal('0.00')
                    }
                )

                # Check if user has sufficient available balance
                if balance.available_cash_balance < total_cost:
                    return Response({
                        "error": "Insufficient balance",
                        "required": float(total_cost),
                        "available": float(balance.available_cash_balance)
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Reserve the cash for the buy order
                if not balance.reserve_cash(total_cost):
                    return Response({
                        "error": "Failed to reserve cash for the order"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # Execute the reservation (deduct from total balance) since it's a market order
                if not balance.execute_cash_reservation(total_cost):
                    # If execution fails, release the reservation to rollback
                    balance.release_cash_reservation(total_cost)
                    return Response({
                        "error": "Failed to execute cash deduction"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # Create the buy order
                order = OrderBook.objects.create(
                    user=user,
                    room=room,
                    order_type=OrderBook.BUY,
                    symbol=symbol,
                    quantity=quantity,
                    order_price=current_price,
                    order_category=OrderBook.MARKET,
                    order_status=OrderBook.EXECUTED, 
                    executed_price=current_price,
                    execution_timestamp=timezone.now(),
                    has_stop_loss=has_stop_loss,
                    stop_loss_price=stop_loss_price if has_stop_loss else None
                )

                # Create stop loss order if requested
                stop_loss_order = None
                if has_stop_loss:
                    stop_loss_order = self.create_stop_loss_order(
                        user=user,
                        room=room,
                        symbol=symbol,
                        quantity=quantity,
                        stop_loss_price=stop_loss_price,
                        stock_name=stock_name,
                        original_order_id=order.id
                    )
                    
                    if not stop_loss_order:
                        # If stop loss creation fails, you might want to handle this
                        # For now, we'll continue but log the issue
                        print(f"Warning: Failed to create stop loss order for order {order.id}")

                # Update or create portfolio entry
                portfolio, created = UserPortfolio.objects.get_or_create(
                    user=user,
                    room=room,
                    symbol=symbol,
                    defaults={
                        'stock_name': stock_name,  
                        'total_quantity': 0,
                        'average_buy_price': Decimal('0.00'),
                        'total_buy_value': Decimal('0.00')
                    }
                )
                if not created:
                    portfolio.stock_name = stock_name  # Update stock name if already exists
                portfolio.add_buy_transaction(quantity, current_price)
                portfolio.save()  # Ensure save after update

                # Create trade record
                trade = Trade.objects.create(
                    user=user,
                    room=room,
                    order=order,
                    trade_type=Trade.BUY,
                    symbol=symbol,
                    quantity=quantity,
                    price=current_price,
                    total_value=total_cost
                )

                response_data = {
                    "success": True,
                    "message": "Buy order executed successfully",
                    "order_id": order.id,
                    "trade_id": trade.id,
                    "symbol": symbol,
                    "quantity": quantity,
                    "executed_price": float(current_price),
                    "total_cost": float(total_cost),
                    "remaining_balance": float(balance.available_cash_balance)
                }

                # Add stop loss information to response if applicable
                if has_stop_loss:
                    response_data.update({
                        "stop_loss_enabled": True,
                        "stop_loss_price": float(stop_loss_price),
                        "stop_loss_order_id": stop_loss_order.id if stop_loss_order else None
                    })

                return Response(response_data, status=status.HTTP_201_CREATED)

            elif order_category == "LIMIT":
                limit_price = data.get("limit_price")
                try:
                    limit_price = Decimal(str(limit_price))
                    if limit_price <= 0:
                        return Response({"error": "Limit price must be greater than 0"}, status=status.HTTP_400_BAD_REQUEST)
                except (ValueError, TypeError, InvalidOperation):
                        return Response({"error": "Invalid limit price format"}, status=status.HTTP_400_BAD_REQUEST)
                
                # Validate stop loss price against limit price for limit orders
                if has_stop_loss and stop_loss_price >= limit_price:
                    return Response({
                        "error": "Stop loss price must be below the limit price for buy orders"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                stock_exists = Stock.objects.filter(symbol=symbol).exists()
                sme_exists = SMEStock.objects.filter(symbol=symbol).exists()
                if not (stock_exists or sme_exists):
                    return Response({"error": f"Symbol '{symbol}' not found in our database"}, status=status.HTTP_404_NOT_FOUND)

                # Get stock name
                stock_name = self.get_stock_name(symbol)
                if not stock_name:
                    return Response({"error": "Stock name not found"}, status=status.HTTP_404_NOT_FOUND)
                
                total_cost = limit_price * Decimal(quantity)

                balance, created = UserBalance.objects.get_or_create(
                    user=user,
                    room=room,
                    defaults={
                        'total_cash_balance': Decimal('100000.00'),
                        'reserved_cash_balance': Decimal('0.00')
                    }
                )

                if balance.available_cash_balance < total_cost:
                    return Response({
                        "error": "Insufficient balance",
                        "required": float(total_cost),
                        "available": float(balance.available_cash_balance)
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Reserve the cash for the limit order (but don't execute yet)
                if not balance.reserve_cash(total_cost):
                    return Response({
                        "error": "Failed to reserve cash for the order"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
                order = OrderBook.objects.create(
                    user=user,
                    room=room,
                    order_type=OrderBook.BUY,
                    symbol=symbol,
                    quantity=quantity,
                    order_price=limit_price,
                    order_category=OrderBook.LIMIT,
                    order_status=OrderBook.PENDING, 
                    executed_price=None,
                    execution_timestamp=None,
                    has_stop_loss=has_stop_loss,
                    stop_loss_price=stop_loss_price if has_stop_loss else None
                )

                response_data = {
                    "success": True,
                    "message": "Limit buy order placed successfully",
                    "order_id": order.id,
                    "symbol": symbol,
                    "quantity": quantity,
                    "limit_price": float(limit_price),
                    "total_cost": float(total_cost),
                    "order_status": "PENDING",
                    "remaining_balance": float(balance.available_cash_balance)
                }

                # Add stop loss information to response if applicable
                if has_stop_loss:
                    response_data.update({
                        "stop_loss_enabled": True,
                        "stop_loss_price": float(stop_loss_price),
                        "message": "Limit buy order placed successfully with stop loss. Stop loss order will be created when the buy order is executed."
                    })

                return Response(response_data, status=status.HTTP_201_CREATED)
            else:
                return Response({"error": "Error placing buy"})

        except ValueError as e:
            return Response({"error": f"Invalid data format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RoomTradeSellView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_stock_name(self, symbol):
        """Get company name from symbol, fallback to symbol if not found"""
        try:
            # Check regular stocks first
            stock = Stock.objects.filter(symbol=symbol).first()
            if stock and hasattr(stock, 'name_of_company') and stock.name_of_company:
                return stock.name_of_company.strip()

            # Check SME stocks
            sme_stock = SMEStock.objects.filter(symbol=symbol).first()
            if sme_stock and hasattr(sme_stock, 'name_of_company') and sme_stock.name_of_company:
                return sme_stock.name_of_company.strip()

            # Fallback to symbol
            return symbol
        except Exception:
            return symbol

    def get_indianapi_stock_data(self, stock_name):
        """Fetch stock data from IndianAPI"""
        try:
            base_url = "https://stock.indianapi.in/stock"
            params = {'name': stock_name}
            headers = {
                "X-Api-Key": settings.INDIANAPI_KEY,
                "Content-Type": "application/json"
            }

            response = requests.get(
                base_url,
                headers=headers,  
                params=params
            )
            response.raise_for_status()
            data = response.json()

            # Validate response structure
            if not data:
                return None

            current_price = data.get('currentPrice', {})

            # Get LTP from NSE or BSE
            ltp = current_price.get('NSE') or current_price.get('BSE')
            if ltp is None:
                return None

            # Convert LTP to float safely
            try:
                ltp = float(ltp)
            except (ValueError, TypeError):
                return None

            return {
                'ltp': ltp,
                'company_name': data.get('companyName', ''),
            }

        except Exception:
            return None

    def post(self, request, room_id):
        try:
            user = request.user
            data = request.data

            # Validate room
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            # Check if room is active
            now = timezone.now()
            check_and_close_room(room)
            if room.is_closed:
                return Response({"error": "Room is closed, no more trades allowed"}, status=403)

            if not (room.start_time and room.end_time and room.start_time <= now <= room.end_time):
                return Response({"error": "Room is not active yet"}, status=403)

            # Validate participant
            participant = RoomParticipant.objects.filter(user=user, room=room, is_active=True).first()
            if not participant:
                return Response({"error": "You are not an active participant in this room"}, status=status.HTTP_403_FORBIDDEN)

            # Extract and validate input data
            symbol = data.get("symbol", "").strip().upper()
            quantity = int(data.get("quantity", 0))
            order_category = data.get("order_category", "").strip().upper()
            is_short_sell = data.get("is_short_sell", False)

            if not symbol or quantity <= 0:
                return Response({"error": "Invalid input: symbol and positive quantity are required"}, status=status.HTTP_400_BAD_REQUEST)

            if not order_category:
                return Response({"error": "Please mention order category"})

            if order_category == "MARKET":
                stock_exists = Stock.objects.filter(symbol=symbol).exists()
                sme_exists = SMEStock.objects.filter(symbol=symbol).exists()

                if not (stock_exists or sme_exists):
                    return Response({
                        "error": f"Symbol '{symbol}' not found in our database"
                    }, status=status.HTTP_404_NOT_FOUND)

                # Fetch user's portfolio for this stock
                portfolio = UserPortfolio.objects.filter(
                    user=user,
                    room=room,
                    symbol=symbol
                ).first()

                if not portfolio:
                    return Response({
                        "error": f"No portfolio found for symbol {symbol}",
                        "detail": "You don't own this stock in your portfolio"
                    }, status=status.HTTP_400_BAD_REQUEST)

                if not is_short_sell:
                # Check available quantity
                    if portfolio.available_quantity < quantity:
                        return Response({
                            "error": "Insufficient quantity in portfolio",
                            "requested": quantity,
                            "available": portfolio.available_quantity
                        }, status=status.HTTP_400_BAD_REQUEST)

                    # Get stock name and fetch current market price
                    stock_name = self.get_stock_name(symbol)
                    if not stock_name:
                        return Response({"error": "Stock name not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    stock_data = self.get_indianapi_stock_data(symbol)
                    if not stock_data or not stock_data.get('ltp'):
                        return Response({
                            "error": "Unable to fetch current market price. Please try again later."
                        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                    current_price = Decimal(str(stock_data['ltp']))
                    total_proceeds = current_price * Decimal(quantity)  # Use Decimal for precision

                    # Fetch or create user's balance for this room
                    balance, created = UserBalance.objects.get_or_create(
                        user=user,
                        room=room,
                        defaults={
                            'total_cash_balance': Decimal('100000.00'),
                            'reserved_cash_balance': Decimal('0.00')
                        }
                    )

                    # Create the sell order
                    order = OrderBook.objects.create(
                        user=user,
                        room=room,
                        order_type=OrderBook.SELL,
                        symbol=symbol,
                        quantity=quantity,
                        order_price=current_price,
                        order_category=OrderBook.MARKET,
                        order_status=OrderBook.EXECUTED,
                        filled_quantity=quantity,
                        executed_price=current_price,
                        execution_timestamp=timezone.now()
                    )

                    # Execute the sell transaction in portfolio
                    if not portfolio.add_sell_transaction(quantity, current_price):
                        return Response({"error": "Failed to update portfolio"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                    # Add proceeds to balance
                    previous_balance = balance.available_cash_balance
                    balance.add_cash(total_proceeds)

                    # Create trade record
                    trade = Trade.objects.create(
                        user=user,
                        room=room,
                        order=order,
                        trade_type=Trade.SELL,
                        symbol=symbol,
                        quantity=quantity,
                        price=current_price,
                        total_value=total_proceeds
                    )

                    response_data = {
                        "success": True,
                        "message": "Sell order executed successfully",
                        "order_id": order.id,
                        "trade_id": trade.id,
                        "symbol": symbol,
                        "quantity": quantity,
                        "executed_price": float(current_price),
                        "total_proceeds": float(total_proceeds),
                        "new_balance": float(balance.available_cash_balance),
                        "previous_balance": float(previous_balance),
                        "portfolio": {
                            "remaining_quantity": portfolio.total_quantity,
                            "average_price": float(portfolio.average_buy_price),
                            "realized_pnl": float(portfolio.realized_pnl)
                        }
                    }

                    return Response(response_data, status=status.HTTP_201_CREATED)
                else:

                    stock_name = self.get_stock_name(symbol)
                    if not stock_name:
                        return Response({"error": "Stock name not found"}, status=status.HTTP_404_NOT_FOUND)
                    
                    stock_data = self.get_indianapi_stock_data(symbol)
                    if not stock_data or not stock_data.get('ltp'):
                        return Response({
                            "error": "Unable to fetch current market price. Please try again later."
                        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                    
                    current_price = Decimal(str(stock_data['ltp']))
                    total_proceeds = current_price*quantity

                    balance, created = UserBalance.objects.get_or_create(
                        user=user,
                        room=room,
                        defaults={
                            'total_cash_balance': Decimal('100000.00'),
                            'reserved_cash_balance': Decimal('0.00')
                        }
                    )

                    order = OrderBook.objects.create(
                        user=user,
                        room=room,
                        order_type=OrderBook.SELL,
                        symbol=symbol,
                        quantity=quantity,
                        order_price=current_price,
                        order_category=OrderBook.MARKET,
                        order_status=OrderBook.EXECUTED,
                        filled_quantity=quantity,
                        executed_price=current_price,
                        execution_timestamp=timezone.now()
                    )

                    if not portfolio.add_short_sell_transaction(quantity, current_price):
                        return Response({"error": "Failed to update portfolio"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
                    previous_balance = balance.available_cash_balance
                    balance.add_cash(total_proceeds)

                    trade = Trade.objects.create(
                        user=user,
                        room=room,
                        order=order,
                        trade_type=Trade.SELL,
                        symbol=symbol,
                        quantity=quantity,
                        price=current_price,
                        total_value=total_proceeds
                    )

                    response_data = {
                        "success": True,
                        "message": "Sell order executed successfully",
                        "order_id": order.id,
                        "trade_id": trade.id,
                        "symbol": symbol,
                        "quantity": quantity,
                        "executed_price": float(current_price),
                        "total_proceeds": float(total_proceeds),
                        "new_balance": float(balance.available_cash_balance),
                        "previous_balance": float(previous_balance),
                        "portfolio": {
                            "remaining_quantity": portfolio.total_quantity,
                            "average_price": float(portfolio.average_buy_price),
                            "realized_pnl": float(portfolio.realized_pnl)
                        }
                    }

                    return Response(response_data, status=status.HTTP_201_CREATED)
                
            elif order_category == "LIMIT":
                limit_price = data.get("limit_price")
                if not limit_price:
                    return Response({"error": "Limit Price is required"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    limit_price = Decimal(str(limit_price))
                    if limit_price <= 0:
                        return Response({
                            "error": "Limit price must be greater than 0"
                        }, status=status.HTTP_400_BAD_REQUEST)
                except (ValueError, TypeError, InvalidOperation):
                    return Response({
                        "error": "Invalid limit price format"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                stock_exists = Stock.objects.filter(symbol=symbol).exists()
                sme_exists = SMEStock.objects.filter(symbol=symbol).exists()

                if not (stock_exists or sme_exists):
                    return Response({"error": f"Symbol '{symbol}' not found in our database"}, status=status.HTTP_404_NOT_FOUND)
                
                portfolio = UserPortfolio.objects.filter(
                    user=user,
                    room=room,
                    symbol=symbol
                ).first()

                if not portfolio:
                    return Response({
                        "error": f"No portfolio found for symbol {symbol}",
                        "detail": "You don't own this stock in your portfolio"
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Check available quantity
                if portfolio.available_quantity < quantity:
                    return Response({
                        "error": "Insufficient quantity in portfolio",
                        "requested": quantity,
                        "available": portfolio.available_quantity
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Get current market price for reference (optional validation)
                stock_name = self.get_stock_name(symbol)
                # stock_data = self.get_indianapi_stock_data(symbol)
                
                # if stock_data and stock_data.get('ltp'):
                #     current_market_price = Decimal(str(stock_data['ltp']))
                    

                # Reserve the quantity in portfolio (prevent overselling)
                if not portfolio.reserve_quantity(quantity):
                    return Response({
                        "error": "Failed to reserve quantity for limit order"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # Create the limit sell order (PENDING status)
                order = OrderBook.objects.create(
                    user=user,
                    room=room,
                    order_type=OrderBook.SELL,
                    symbol=symbol,
                    quantity=quantity,
                    order_price=limit_price,
                    order_category=OrderBook.LIMIT,
                    order_status=OrderBook.PENDING,
                    filled_quantity=0,
                    executed_price=None,
                    execution_timestamp=None
                )

                response_data = {
                    "success": True,
                    "message": "Limit sell order placed successfully",
                    "order_id": order.id,
                    "symbol": symbol,
                    "quantity": quantity,
                    "limit_price": float(limit_price),
                    "order_status": "PENDING",
                    "portfolio": {
                        "total_quantity": portfolio.total_quantity,
                        "available_quantity": portfolio.available_quantity,
                        "reserved_quantity": portfolio.reserved_quantity
                    }
                }

                return Response(response_data, status=status.HTTP_201_CREATED)

            else:
                return Response({
                    "error": "Invalid order category. Must be either 'MARKET' or 'LIMIT'"
                }, status=status.HTTP_400_BAD_REQUEST)


        except ValueError as e:
            return Response({"error": f"Invalid data format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class RoomLeaderboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get_stock_data(self, symbol):
        """Fetch current stock price from IndianAPI"""
        try:
            base_url = "https://stock.indianapi.in/stock"
            params = {'name': symbol}
            headers = {
                "X-Api-Key": settings.INDIANAPI_KEY,
                "Content-Type": "application/json"
            }

            response = requests.get(base_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            current_price = data.get('currentPrice', {})
            ltp = current_price.get('NSE') or current_price.get('BSE')
            
            if ltp is None:
                return None

            return float(ltp)
        except Exception:
            return None

    def calculate_user_pnl(self, user, room):
        """Calculate total P&L for a user in a room"""
        try:
            # Get user's portfolios
            portfolios = UserPortfolio.objects.filter(
                user=user,
                room=room
            )
            
            total_realized_pnl = Decimal('0.00')
            total_unrealized_pnl = Decimal('0.00')
            
            for portfolio in portfolios:
                # Add realized P&L
                total_realized_pnl += portfolio.realized_pnl
                
                # Calculate unrealized P&L if user still holds stocks
                if portfolio.total_quantity > 0:
                    current_price = self.get_stock_data(portfolio.symbol)
                    if current_price:
                        current_price = Decimal(str(current_price))
                        unrealized_pnl = portfolio.calculate_unrealized_pnl(current_price)
                        total_unrealized_pnl += unrealized_pnl
            
            total_pnl = total_realized_pnl + total_unrealized_pnl
            
            # Get total trades count
            total_trades = Trade.objects.filter(user=user, room=room).count()
            
            # Get user balance for net worth calculation
            balance = UserBalance.objects.filter(user=user, room=room).first()
            cash_balance = balance.available_cash_balance if balance else Decimal('100000.00')
            
            # Calculate current portfolio value
            portfolio_value = Decimal('0.00')
            for portfolio in portfolios.filter(total_quantity__gt=0):
                current_price = self.get_stock_data(portfolio.symbol)
                if current_price:
                    portfolio_value += portfolio.total_quantity * Decimal(str(current_price))
                else:
                    portfolio_value += portfolio.total_quantity * portfolio.average_buy_price
            
            net_worth = cash_balance + portfolio_value
            
            return {
                'total_pnl': total_pnl,
                'realized_pnl': total_realized_pnl,
                'unrealized_pnl': total_unrealized_pnl,
                'total_trades': total_trades,
                'net_worth': net_worth,
                'cash_balance': cash_balance,
                'portfolio_value': portfolio_value
            }
        except Exception as e:
            logger.error(f"Error calculating P&L for user {user.username}: {e}")
            return None

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)

        check_and_close_room(room)
        now = timezone.now()

        # Check if room is closed and user is not admin
        if room.end_time and now > room.end_time and request.user != room.admin:
            return Response({"error": "Room is closed. Only the admin can view the leaderboard."}, status=403)

        # Get all participants in the room
        participants = RoomParticipant.objects.filter(
            room=room,
            is_active=True
        ).select_related('user')

        leaderboard = []
        starting_balance = Decimal('100000.00')  # Default starting balance

        for participant in participants:
            user_data = self.calculate_user_pnl(participant.user, room)
            
            if user_data:
                # Calculate percentage return based on P&L
                percentage_return = (user_data['total_pnl'] / starting_balance) * 100
                
                leaderboard.append({
                    'username': participant.user.username,
                    'user_id': participant.user.id,
                    'total_pnl': float(user_data['total_pnl']),
                    'realized_pnl': float(user_data['realized_pnl']),
                    'unrealized_pnl': float(user_data['unrealized_pnl']),
                    'net_worth': float(user_data['net_worth']),
                    'cash_balance': float(user_data['cash_balance']),
                    'portfolio_value': float(user_data['portfolio_value']),
                    'total_trades': user_data['total_trades'],
                    'percentage_return': float(percentage_return)
                })

        # Sort by total P&L (descending) - highest P&L first
        leaderboard.sort(key=lambda x: x['total_pnl'], reverse=True)
        
        # Add ranks
        for i, entry in enumerate(leaderboard):
            entry['rank'] = i + 1
            # Add position indicator
            if entry['total_pnl'] > 0:
                entry['position'] = 'profit'
            elif entry['total_pnl'] < 0:
                entry['position'] = 'loss'
            else:
                entry['position'] = 'neutral'

        # Calculate room statistics
        room_stats = {
            'total_participants': len(leaderboard),
            'profitable_traders': sum(1 for entry in leaderboard if entry['total_pnl'] > 0),
            'loss_making_traders': sum(1 for entry in leaderboard if entry['total_pnl'] < 0),
            'average_pnl': float(sum(entry['total_pnl'] for entry in leaderboard) / len(leaderboard)) if leaderboard else 0,
            'total_trades': sum(entry['total_trades'] for entry in leaderboard)
        }

        return Response({
            "room": {
                "id": room.id,
                "name": room.name,
                "is_closed": room.is_closed,
                "start_time": room.start_time,
                "end_time": room.end_time
            },
            "room_statistics": room_stats,
            "leaderboard": leaderboard,
            "current_user_rank": next((entry['rank'] for entry in leaderboard if entry['user_id'] == request.user.id), None)
        }, status=200)

class RoomTradeHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.get(id=room_id)
        except Room.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)

        user = request.user
        if not user:
            return Response({"User Not Found"})
        
        trades = Trade.objects.filter(user=user, room=room).order_by("timestamp")
        if not trades:
            return Response({"Trades Not Found"})

        trade_history = [
            {
                "symbol": trade.symbol,
                "trade_type": trade.trade_type,
                "quantity": trade.quantity,
                "price": str(trade.price),
                "total_value": str(trade.total_value),
                "timestamp": trade.timestamp,
            }
            for trade in trades
        ]

        if not trade_history:
            return Response({"No Trade History"})

        return Response({
            "room": room.name,
            "username": user.username,
            "trade_history": trade_history
        }, status=200)


        
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
                    'symbol': stock['symbol'],
                    'name_of_company': stock['name_of_company'],
                    'series': stock['series'],
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
                        'symbol': stock['symbol'],
                        'name_of_company': stock['name_of_company'],
                        'series': stock['series'],
                        'type': 'SME'
                    })

            # Sort results by symbol for consistent ordering
            results.sort(key=lambda x: x['symbol'])

            return Response({
                'query': search_query,
                'count': len(results),
                'stocks': results
            }, status=status.HTTP_200_OK)
        
        except ValueError:
            return Response({
                'error': 'Invalid limit parameter. Must be a number.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        except Exception as e:
            return Response({
                'error': f'An error occurred while searching: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StockDataView(APIView):
    """
    View to get current stock data using IndianAPI
    """
    permission_classes = [IsAuthenticated]

    def get_stock_name(self, symbol):
        """Get company name from symbol, fallback to symbol if not found"""
        try:
            # Check regular stocks first
            stock = Stock.objects.filter(symbol=symbol).first()
            if stock and hasattr(stock, 'name_of_company') and stock.name_of_company:
                return stock.name_of_company.strip()

            # Check SME stocks
            sme_stock = SMEStock.objects.filter(symbol=symbol).first()
            if sme_stock and hasattr(sme_stock, 'name_of_company') and sme_stock.name_of_company:
                return sme_stock.name_of_company.strip()

            # Fallback to symbol
            return symbol
        except Exception:
            return symbol

    def get_indianapi_stock_data(self, stock_name):
        """Fetch stock data from IndianAPI"""
        try:
            base_url = "https://stock.indianapi.in/stock"
            params = {'name': stock_name}
            headers = {
                "X-Api-Key": settings.INDIANAPI_KEY,
                "Content-Type": "application/json"
            }

            response = requests.get(
                base_url,
                headers=headers,  
                params=params
            )
            response.raise_for_status()
            data = response.json()

            # Validate response structure
            if not data:
                return None

            current_price = data.get('currentPrice', {})

            # Get LTP from NSE or BSE
            ltp = current_price.get('NSE') or current_price.get('BSE')
            if ltp is None:
                return None

            # Convert LTP to float safely
            try:
                ltp = float(ltp)
            except (ValueError, TypeError):
                return None

            return {
                'company_name': data.get('companyName', ''),
                'industry': data.get('industry', ''),
                'ltp': ltp,
                'nse_price': current_price.get('NSE'),
                'bse_price': current_price.get('BSE'),
                'percent_change': data.get('percentChange'),
                'year_high': data.get('yearHigh'),
                'year_low': data.get('yearLow'),
                'technical_data': data.get('stockTechnicalData', {}),
                'key_metrics': data.get('keyMetrics', {}),
            }

        except requests.exceptions.Timeout:
            return None
        except requests.exceptions.RequestException:
            return None
        except (ValueError, KeyError):
            return None
        except Exception:
            return None

    def get(self, request, room_id):
        """Get stock data for a symbol"""
        symbol = None
        
        try:
            # Validate room and participant
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response(
                    {"error": "Room not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )

            participant = RoomParticipant.objects.filter(
                user=request.user,
                room=room,
                is_active=True
            ).first()
            
            if not participant:
                return Response({
                    "error": "You are not an active participant in this room"
                }, status=status.HTTP_403_FORBIDDEN)

            # Validate symbol parameter
            symbol = request.GET.get('symbol', '').strip().upper()
            if not symbol:
                return Response({
                    "error": "Symbol parameter is required"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Check if symbol exists in database
            stock_exists = Stock.objects.filter(symbol=symbol).exists()
            sme_exists = SMEStock.objects.filter(symbol=symbol).exists()

            if not (stock_exists or sme_exists):
                return Response({
                    "error": f"Symbol '{symbol}' not found in our database",
                    "symbol": symbol
                }, status=status.HTTP_404_NOT_FOUND)

            # Get stock name and fetch data
            stock_name = self.get_stock_name(symbol)
            if not stock_name:
                return Response({"Stock Name Not found"})
            stock_data = self.get_indianapi_stock_data(symbol)

            if not stock_data:
                return Response({
                    "error": "Unable to fetch current stock data. Please try again later.",
                    "symbol": symbol,
                    "Name": stock_name
                }, status=status.HTTP_404_NOT_FOUND)

            # Return successful response
            return Response({
                "success": True,
                "symbol": symbol,
                "company_name": stock_data['company_name'],
                "industry": stock_data['industry'],
                "ltp": stock_data['ltp'],
                "current_price": {
                    "NSE": stock_data['nse_price'],
                    "BSE": stock_data['bse_price']
                },
                "percent_change": stock_data['percent_change'],
                "year_high": stock_data['year_high'],
                "year_low": stock_data['year_low'],
                "technical_data": stock_data['technical_data'],
                "key_metrics": stock_data['key_metrics'],
                "source": "IndianAPI"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": "An internal error occurred. Please try again later.",
                "symbol": symbol
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserPortfolioView(APIView):
    """
    New view to get user's portfolio summary
    """
    permission_classes = [IsAuthenticated]

    def get_stock_data(self, symbol):
        """Fetch current stock price from IndianAPI"""
        try:
            base_url = "https://stock.indianapi.in/stock"
            params = {'name': symbol}
            headers = {
                "X-Api-Key": settings.INDIANAPI_KEY,
                "Content-Type": "application/json"
            }

            response = requests.get(base_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            if not data:
                return None

            current_price = data.get('currentPrice', {})
            ltp = current_price.get('NSE') or current_price.get('BSE')
            
            if ltp is None:
                return None

            return float(ltp)
        except Exception:
            return None

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

            portfolios = UserPortfolio.objects.filter(
                user=request.user,
                room=room
            ).exclude(total_quantity=0)

            total_investment = Decimal('0.00')
            total_current_value = Decimal('0.00')
            total_realized_pnl = Decimal('0.00')
            total_unrealized_pnl = Decimal('0.00')
            
            holdings = []
            for portfolio in portfolios:
                current_price = self.get_stock_data(portfolio.symbol)
                if current_price is None:
                    current_price = float(portfolio.average_buy_price)
                
                current_price = Decimal(str(current_price))
                
                # Calculate values
                investment = portfolio.total_buy_value - portfolio.total_sell_value
                current_value = portfolio.total_quantity * current_price
                unrealized_pnl = portfolio.calculate_unrealized_pnl(current_price)
                
                # Update totals
                total_investment += investment
                total_current_value += current_value
                total_realized_pnl += portfolio.realized_pnl
                total_unrealized_pnl += unrealized_pnl
                
                holdings.append({
                    "symbol": portfolio.symbol,
                    "stock_name": portfolio.stock_name,
                    "quantity": portfolio.total_quantity,
                    "available_quantity": portfolio.available_quantity,
                    "average_buy_price": float(portfolio.average_buy_price),
                    "current_price": float(current_price),
                    "total_investment": float(investment),
                    "current_value": float(current_value),
                    "unrealized_pnl": float(unrealized_pnl),
                    "realized_pnl": float(portfolio.realized_pnl),
                    "pnl_percentage": float(((current_value - investment) / investment * 100) if investment > 0 else 0)
                })

            # Calculate overall portfolio summary
            total_pnl = total_realized_pnl + total_unrealized_pnl
            overall_pnl_percentage = float(((total_current_value - total_investment) / total_investment * 100) if total_investment > 0 else 0)

            portfolio_summary = {
                "total_investment": float(total_investment),
                "current_value": float(total_current_value),
                "total_realized_pnl": float(total_realized_pnl),
                "total_unrealized_pnl": float(total_unrealized_pnl),
                "total_pnl": float(total_pnl),
                "overall_pnl_percentage": overall_pnl_percentage,
                "total_holdings": len(holdings)
            }

            balance = UserBalance.objects.filter(user=request.user, room=room).first()
            if balance:
                portfolio_summary["available_cash"] = float(balance.available_cash_balance)
                portfolio_summary["total_portfolio_value"] = float(balance.available_cash_balance + total_current_value)

            return Response({
                "portfolio_summary": portfolio_summary,
                "holdings": holdings,
                "room": {
                    "id": room.id,
                    "name": room.name,
                    "is_active": not room.is_closed
                },
                "user": {
                    "id": request.user.id,
                    "username": request.user.username
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class OrderHistoryView(APIView):
    """
    New view to get user's order history
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

            orders = OrderBook.objects.filter(user=request.user, room=room).order_by('order_timestamp')

            order_history = []
            for order in orders:
                order_history.append({
                    "id": order.id,
                    "symbol": order.symbol,
                    "order_type": order.order_type,
                    "order_category": order.order_category,
                    "quantity": order.quantity,
                    "filled_quantity": order.filled_quantity,
                    "order_price": str(order.order_price),
                    "executed_price": str(order.executed_price) if order.executed_price else None,
                    "order_status": order.order_status,
                    "order_timestamp": order.order_timestamp,
                    "execution_timestamp": order.execution_timestamp,
                    "cancellation_timestamp": order.cancellation_timestamp,
                    "notes": order.notes
                })

            return Response({
                "room": {
                    "id": room.id,
                    "name": room.name
                },
                "orders": order_history
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class HistoricalDataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            # Validate Room
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            # Validate Participant
            participant = RoomParticipant.objects.filter(
                user=request.user,
                room=room,
                is_active=True
            ).first()
            if not participant:
                return Response({"error": "You are not an active participant in this room"}, status=status.HTTP_403_FORBIDDEN)

            # Get Query Params
            symbol = request.GET.get('symbol', '').strip().upper()
            raw_interval = request.GET.get('interval', '1minute')
            to_date = request.GET.get('to_date', timezone.now().strftime('%Y-%m-%d'))
            from_date = request.GET.get('from_date', (timezone.now() - timezone.timedelta(days=30)).strftime('%Y-%m-%d'))

            if not symbol:
                return Response({"error": "Symbol parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

            interval_map = {
                "1minute": ("minutes", "1"),
                "5minute": ("minutes", "5"),
                "15minute": ("minutes", "15"),
                "30minute": ("minutes", "30"),
                "1hour": ("hours", "1"),
                "day": ("days", "1"),
                "week": ("weeks", "1"),
                "month": ("months", "1")
            }

            if raw_interval not in interval_map:
                return Response({"error": "Invalid interval"}, status=status.HTTP_400_BAD_REQUEST)

            unit, interval = interval_map[raw_interval]


            # === Instrument Key Logic ===
            instrument_key = self.get_instrument_key(symbol)
            if instrument_key == None:
                return Response({
                    "error": f"Instrument key not found for symbol: {symbol}"
                }, status=status.HTTP_404_NOT_FOUND)

            # === Upstox SDK ===
            apiInstance = upstox_client.HistoryV3Api()

            # return Response({
            #     "instruement_key": instrument_key,
            #     "interval": interval,
            #     "unit": unit,
            #     "from": from_date,
            #     "to": to_date
            # })

            try:
                response = apiInstance.get_historical_candle_data1(
                    instrument_key=instrument_key,
                    interval=interval,
                    unit=unit,
                    from_date=from_date,
                    to_date=to_date
                )

                candles = response.data.candles

                if not candles:
                    return Response({
                        "error": "No historical data found for the symbol",
                        "symbol": symbol
                    }, status=404)

                return Response({"candles": candles})

                candles_data = getattr(response, "data", {}).get("candles", [])
                if not candles_data:
                    return Response({
                        "error": "No historical data found for the symbol",
                        "symbol": symbol
                    }, status=404)

                formatted_candles = []
                for candle in candles_data:
                    if len(candle) >= 6:
                        formatted_candles.append({
                            "timestamp": candle[0],
                            "open": float(candle[1]),
                            "high": float(candle[2]),
                            "low": float(candle[3]),
                            "close": float(candle[4]),
                            "volume": int(candle[5]),
                        })

                return Response({
                    "symbol": symbol,
                    "interval": raw_interval,
                    "from": from_date,
                    "to": to_date,
                    "candles": formatted_candles
                }, status=status.HTTP_200_OK)
            except ApiException as api_error:
                logger.error(f"Upstox API error for {symbol}: {api_error}")
                return Response({
                    "error": f"Upstox API error: {str(api_error)}",
                    "symbol": symbol
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"Unexpected error in HistoricalDataView: {e}")
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_instrument_key(self, symbol: str) -> str | None:
        """
        Returns NSE_EQ|ISIN key using Stock or SMEStock models.
        Caches results for better performance.
        """
        try:
            cache_key = f"instrument_key_{symbol}"
            instrument_key = cache.get(cache_key)

            if instrument_key:
                return instrument_key

            # First check in Stock table
            stock = Stock.objects.filter(symbol=symbol).first()
            if stock and stock.isin_number:
                instrument_key = f"NSE_EQ|{stock.isin_number}"
                cache.set(cache_key, instrument_key, 600)
                return instrument_key

            # Then check SMEStock table
            sme_stock = SMEStock.objects.filter(symbol=symbol).first()
            if sme_stock and sme_stock.isin_number:
                instrument_key = f"NSE_EQ|{sme_stock.isin_number}"
                cache.set(cache_key, instrument_key, 600)
                return instrument_key

            return None

        except Exception as e:
            logger.error(f"Error fetching instrument key for {symbol}: {e}")
            return None
        
class MarketStatusView(APIView):
    """
    View to get general market status and trading hours
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            now = timezone.now()
            
            # Basic market hours (you can customize this based on your requirements)
            market_open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
            market_close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
            
            is_market_open = market_open_time <= now <= market_close_time
            is_weekend = now.weekday() >= 5  # Saturday = 5, Sunday = 6
            
            # You can add more sophisticated market holiday checking here
            market_status = {
                "is_open": is_market_open and not is_weekend,
                "current_time": now,
                "market_open_time": market_open_time,
                "market_close_time": market_close_time,
                "is_weekend": is_weekend,
                "next_open": market_open_time if now < market_open_time else market_open_time + timezone.timedelta(days=1),
                "status_message": self._get_market_status_message(is_market_open, is_weekend, now, market_open_time, market_close_time)
            }

            return Response(market_status, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _get_market_status_message(self, is_market_open, is_weekend, now, market_open, market_close):
        """Helper method to generate market status message"""
        if is_weekend:
            return "Markets are closed (Weekend)"
        elif now < market_open:
            return f"Markets will open at {market_open.strftime('%H:%M')}"
        elif now > market_close:
            return f"Markets closed at {market_close.strftime('%H:%M')}"
        elif is_market_open:
            return "Markets are open"
        else:
            return "Markets are closed"




class HealthCheckView(APIView):
    """
    Simple health check endpoint
    """
    def get(self, request):
        return Response({
            "status": "healthy",
            "timestamp": timezone.now(),
            "services": {
                "market_data": "operational",
                "trading": "operational",
                "database": "operational"
            }
        }, status=status.HTTP_200_OK)


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
                'code': getattr(room, 'code', None),  
                'has_password': bool(room.password),  
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({'error': 'Failed to lookup room'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class RoomStatsView(APIView):
    """
    View to get overall room statistics
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            # Check if user is admin or participant
            is_admin = request.user == room.admin
            participant = RoomParticipant.objects.filter(
                user=request.user, 
                room=room, 
                is_active=True
            ).first()

            if not is_admin and not participant:
                return Response({
                    "error": "You don't have access to this room"
                }, status=status.HTTP_403_FORBIDDEN)

            # Get room statistics
            total_participants = RoomParticipant.objects.filter(room=room, is_active=True).count()
            total_trades = Trade.objects.filter(room=room).count()
            total_volume = Trade.objects.filter(room=room).aggregate(
                total=Sum('total_value')
            )['total'] or Decimal('0')

            # Get most active stocks
            popular_stocks = Trade.objects.filter(room=room).values('symbol').annotate(
                trade_count=models.Count('id'),
                total_volume=Sum('total_value')
            ).order_by('-trade_count')[:10]

            # Get top traders (only if admin)
            top_traders = []
                # leaderboard = trading_service.get_room_leaderboard(room)
                # top_traders = leaderboard[:5]  # Top 5 traders

            return Response({
                "room": {
                    "id": room.id,
                    "name": room.name,
                    "is_closed": room.is_closed,
                    "start_time": room.start_time,
                    "end_time": room.end_time
                },
                "statistics": {
                    "total_participants": total_participants,
                    "total_trades": total_trades,
                    "total_volume": str(total_volume),
                    "popular_stocks": list(popular_stocks),
                    "top_traders": top_traders if is_admin else []
                },
                "user_role": "admin" if is_admin else "participant"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserRoomsView(APIView):
    """
    View to get all rooms where user is a participant
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user

            # Get rooms where user is an active participant
            participant_rooms = RoomParticipant.objects.filter(
                user=user, 
                is_active=True
            ).select_related('room').order_by('-join_time')

            # Get rooms where user is admin
            admin_rooms = Room.objects.filter(admin=user).order_by('-created_at')

            rooms_data = []
            
            # Add participant rooms
            for participant in participant_rooms:
                room = participant.room
                rooms_data.append({
                    "id": room.id,
                    "name": room.name,
                    "role": "participant",
                    "is_closed": room.is_closed,
                    "start_time": room.start_time,
                    "end_time": room.end_time,
                    "join_time": participant.join_time,
                    "admin": room.admin.username
                })

            # Add admin rooms (avoid duplicates)
            participant_room_ids = {p.room.id for p in participant_rooms}
            for room in admin_rooms:
                if room.id not in participant_room_ids:
                    rooms_data.append({
                        "id": room.id,
                        "name": room.name,
                        "role": "admin",
                        "is_closed": room.is_closed,
                        "start_time": room.start_time,
                        "end_time": room.end_time,
                        "join_time": None,
                        "admin": room.admin.username
                    })

            # Sort by most recent activity
            rooms_data.sort(key=lambda x: x.get('join_time') or timezone.now(), reverse=True)

            return Response({
                "rooms": rooms_data,
                "count": len(rooms_data)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserBalanceView(APIView):
    """
    Get user's balance for a specific room
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, room_id):
        try:
            # Validate room exists
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response(
                    {"error": "Room not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if user is a participant in this room
            participant = RoomParticipant.objects.filter(
                user=request.user, 
                room=room, 
                is_active=True
            ).first()
            
            if not participant:
                return Response({
                    "error": "You are not an active participant in this room"
                }, status=status.HTTP_403_FORBIDDEN)

            # Get or create user balance for this room
            balance, created = UserBalance.objects.get_or_create(
                user=request.user,
                room=room,
                defaults={
                    'total_cash_balance': Decimal('100000.00'),
                    'reserved_cash_balance': Decimal('0.00')
                }
            )

            return Response({
                "user_id": request.user.id,
                "username": request.user.username,
                "room_id": room.id,
                "room_name": room.name,
                "balance": {
                    "total_cash_balance": float(balance.total_cash_balance),
                    "reserved_cash_balance": float(balance.reserved_cash_balance),
                    "available_cash_balance": float(balance.available_cash_balance),
                },
                "created_new_balance": created
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class AdminUserRoomDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get_stock_data(self, symbol):
        try:
            base_url = "https://stock.indianapi.in/stock"
            params = {'name': symbol}
            headers = {
                "X-Api-Key": settings.INDIANAPI_KEY,
                "Content-Type": "application/json"
            }

            response = requests.get(base_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            current_price = data.get('currentPrice', {}).get('NSE') or data.get('currentPrice', {}).get('BSE')
            return float(current_price) if current_price else None
        except Exception:
            return None

    def get(self, request, room_id, user_id):
        try:
            # Validate room
            room = Room.objects.filter(id=room_id).first()
            if not room:
                return Response({"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND)

            # Check if request.user is admin
            if room.admin != request.user:
                return Response({"error": "Only the admin can view user details."}, status=status.HTTP_403_FORBIDDEN)

            # Check and close room if expired
            check_and_close_room(room)
            now = timezone.now()

            if room.is_closed:
                return Response({"error": "Room is closed, no more trades allowed"}, status=status.HTTP_403_FORBIDDEN)

            if not (room.start_time and room.end_time and room.start_time <= now <= room.end_time):
                return Response({"error": "Room is not active yet"}, status=status.HTTP_403_FORBIDDEN)

            # Validate user exists
            user = get_object_or_404(User, id=user_id)

            # Check if user is an active participant
            participant = RoomParticipant.objects.filter(user=user, room=room, is_active=True).first()
            if not participant:
                return Response({"error": "User is not an active participant in this room"}, status=status.HTTP_403_FORBIDDEN)

            portfolios = UserPortfolio.objects.filter(user=user, room=room).exclude(total_quantity=0)

            total_investment = Decimal('0.00')
            total_current_value = Decimal('0.00')
            total_realized_pnl = Decimal('0.00')
            total_unrealized_pnl = Decimal('0.00')
            holdings = []

            for portfolio in portfolios:
                current_price = self.get_stock_data(portfolio.symbol) or float(portfolio.average_buy_price)
                current_price = Decimal(str(current_price))

                investment = portfolio.total_buy_value - portfolio.total_sell_value
                current_value = portfolio.total_quantity * current_price
                unrealized_pnl = portfolio.calculate_unrealized_pnl(current_price)

                total_investment += investment
                total_current_value += current_value
                total_realized_pnl += portfolio.realized_pnl
                total_unrealized_pnl += unrealized_pnl

                holdings.append({
                    "symbol": portfolio.symbol,
                    "stock_name": portfolio.stock_name,
                    "quantity": portfolio.total_quantity,
                    "available_quantity": portfolio.available_quantity,
                    "average_buy_price": float(portfolio.average_buy_price),
                    "current_price": float(current_price),
                    "total_investment": float(investment),
                    "current_value": float(current_value),
                    "unrealized_pnl": float(unrealized_pnl),
                    "realized_pnl": float(portfolio.realized_pnl),
                    "pnl_percentage": float(((current_value - investment) / investment * 100) if investment > 0 else 0)
                })

            total_pnl = total_realized_pnl + total_unrealized_pnl
            overall_pnl_percentage = float(((total_current_value - total_investment) / total_investment * 100) if total_investment > 0 else 0)

            portfolio_summary = {
                "total_investment": float(total_investment),
                "current_value": float(total_current_value),
                "total_realized_pnl": float(total_realized_pnl),
                "total_unrealized_pnl": float(total_unrealized_pnl),
                "total_pnl": float(total_pnl),
                "overall_pnl_percentage": overall_pnl_percentage,
                "total_holdings": len(holdings)
            }

            # Get balance
            balance = UserBalance.objects.filter(user=user, room=room).first()
            if balance:
                portfolio_summary["available_cash"] = float(balance.available_cash_balance)
                portfolio_summary["total_portfolio_value"] = float(balance.available_cash_balance + total_current_value)

            # Trade history
            trades = Trade.objects.filter(user=user, room=room).order_by('-trade_timestamp')[:20]
            trade_history = [
                {
                    "symbol": trade.symbol,
                    "type": trade.trade_type,
                    "quantity": trade.quantity,
                    "price": float(trade.price),
                    "total_value": float(trade.total_value),
                    "timestamp": trade.timestamp
                }
                for trade in trades
            ]

            return Response({
                "user": {
                    "id": user.id,
                    "username": user.username
                },
                "room": {
                    "id": room.id,
                    "name": room.name,
                    "is_active": not room.is_closed
                },
                "portfolio_summary": portfolio_summary,
                "holdings": holdings,
                "trade_history": trade_history
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    

class PendingOrdersView(APIView):
    """
    View to get only pending orders for a user
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

            # Get only pending orders
            pending_orders = OrderBook.objects.filter(
                user=request.user, 
                room=room, 
                order_status=OrderBook.PENDING
            ).order_by('-order_timestamp')

            orders_data = []
            for order in pending_orders:
                orders_data.append({
                    "id": order.id,
                    "symbol": order.symbol,
                    "order_type": order.order_type,
                    "order_category": order.order_category,
                    "quantity": order.quantity,
                    "order_price": str(order.order_price),
                    "order_timestamp": order.order_timestamp,
                    "notes": order.notes
                })

            return Response({
                "room": {
                    "id": room.id,
                    "name": room.name
                },
                "pending_orders": orders_data,
                "count": len(orders_data)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CancelOrderView(APIView):
    """
    View to cancel pending orders
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id, order_id):
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

            # Get the order
            try:
                order = OrderBook.objects.get(id=order_id, user=request.user, room=room)
            except OrderBook.DoesNotExist:
                return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

            # Check if order can be cancelled
            if order.status != 'PENDING':
                return Response({
                    "error": "Only pending orders can be cancelled"
                }, status=status.HTTP_400_BAD_REQUEST)

            reason = request.data.get('reason', 'Cancelled by user')

            # Cancel the order directly in the view
            order.status = 'CANCELLED'
            order.cancelled_at = timezone.now()
            order.cancellation_reason = reason
            order.save()

            # If it was a buy order, return the locked funds to available balance
            if order.order_type == 'BUY':
                participant.locked_balance -= order.total_amount
                participant.available_balance += order.total_amount
                participant.save()

            # If it was a sell order, return the locked quantity to available
            elif order.order_type == 'SELL':
                try:
                    portfolio = UserPortfolio.objects.get(
                        user=request.user,
                        room=room,
                        symbol=order.symbol
                    )
                    portfolio.locked_quantity -= order.quantity
                    portfolio.save()
                except UserPortfolio.DoesNotExist:
                    # This shouldn't happen, but handle gracefully
                    pass

            return Response({
                "message": f"Order cancelled successfully. Reason: {reason}"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
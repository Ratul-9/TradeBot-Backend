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
        


    def get_instrument_key(self, symbol: str) -> str | None:
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
        

    def get_ltp(self, symbol):
        apiInstance = upstox_client.HistoryV3Api()
        instrument_key = self.get_instrument_key(symbol)


        if not instrument_key:
            return {"error": f"Could not get instrument key for {symbol}"}
        
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
        
        unit, interval = interval_map["1minute"]


        try:
            response = apiInstance.get_intra_day_candle_data(
                instrument_key=instrument_key,
                interval=interval, 
                unit=unit
            )

            candles = response.data.candles

            if not candles:
                return Response({
                    "error": "No historical data found for the symbol",
                    "symbol": symbol
                }, status=404)
            
            first_candle = candles[0]

            ltp = first_candle[4]

            return {"ltp": ltp}



        except Exception as e:
            return {"error": f"Exception while fetching LTP: {e}"}


                
        
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

    def create_stop_loss_order(self, user, room, symbol, quantity, stop_loss_trigger_price, stop_loss_limit_price, stock_name, original_order_id):
        """Create a stop loss sell order with trigger and limit price"""
        try:
            stop_loss_order = OrderBook.objects.create(
                user=user,
                room=room,
                order_type=OrderBook.SELL,
                symbol=symbol,
                quantity=quantity,
                order_price=stop_loss_limit_price,  # This is the limit price for execution
                order_category=OrderBook.STOP_LOSS_LIMIT,  # New category
                order_status=OrderBook.PENDING,
                executed_price=None,
                execution_timestamp=None,
                parent_order_id=original_order_id,
                stop_loss_trigger_price=stop_loss_trigger_price,  # Trigger price
                stop_loss_limit_price=stop_loss_limit_price  # Limit price for execution
            )
            return stop_loss_order
        except Exception as e:
            print(f"Error creating stop loss order: {str(e)}")
            return None

    def execute_partial_buy_order(self, user, room, symbol, quantity, execution_price, stock_name, balance, original_order=None):
        """Execute a partial buy order and update portfolio"""
        try:
            cost = execution_price * Decimal(quantity)
            
            # Execute the cash reservation
            if not balance.execute_cash_reservation(cost):
                return None, None
            
            # Create executed order
            executed_order = OrderBook.objects.create(
                user=user,
                room=room,
                order_type=OrderBook.BUY,
                symbol=symbol,
                quantity=quantity,
                order_price=execution_price,
                order_category=OrderBook.MARKET if not original_order else original_order.order_category,
                order_status=OrderBook.EXECUTED,
                executed_price=execution_price,
                execution_timestamp=timezone.now(),
                parent_order_id=original_order.id if original_order else None
            )
            
            # Update portfolio
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
                portfolio.stock_name = stock_name
            portfolio.add_buy_transaction(quantity, execution_price)
            portfolio.save()
            
            # Create trade record
            trade = Trade.objects.create(
                user=user,
                room=room,
                order=executed_order,
                trade_type=Trade.BUY,
                symbol=symbol,
                quantity=quantity,
                price=execution_price,
                total_value=cost
            )
            
            return executed_order, trade
            
        except Exception as e:
            print(f"Error executing partial buy order: {str(e)}")
            return None, None

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
            
            # Enhanced stop loss fields
            has_stop_loss = data.get("has_stop_loss", False)
            stop_loss_trigger_price = data.get("stop_loss_trigger_price")  # Renamed from stop_loss_price
            stop_loss_limit_price = data.get("stop_loss_limit_price")  # New field

            if not symbol or quantity <= 0:
                return Response({"error": "Invalid input: symbol and positive quantity are required"}, status=status.HTTP_400_BAD_REQUEST)
            
            if not order_category:
                return Response({"Error": "No order category selected"})

            # Validate stop loss if provided
            if has_stop_loss:
                if not stop_loss_trigger_price or not stop_loss_limit_price:
                    return Response({
                        "error": "Both stop loss trigger price and limit price are required when stop loss is enabled"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    stop_loss_trigger_price = Decimal(str(stop_loss_trigger_price))
                    stop_loss_limit_price = Decimal(str(stop_loss_limit_price))
                    
                    if stop_loss_trigger_price <= 0 or stop_loss_limit_price <= 0:
                        return Response({
                            "error": "Stop loss prices must be greater than 0"
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    if stop_loss_limit_price > stop_loss_trigger_price:
                        return Response({
                            "error": "Stop loss limit price must be less than or equal to trigger price"
                        }, status=status.HTTP_400_BAD_REQUEST)
                        
                except (ValueError, TypeError, InvalidOperation):
                    return Response({
                        "error": "Invalid stop loss price format"
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if symbol exists
            stock_exists = Stock.objects.filter(symbol=symbol).exists()
            sme_exists = SMEStock.objects.filter(symbol=symbol).exists()
            if not (stock_exists or sme_exists):
                return Response({
                    "error": f"Symbol '{symbol}' not found in our database"
                }, status=status.HTTP_404_NOT_FOUND)

            # Get stock name
            stock_name = self.get_stock_name(symbol)
            if not stock_name:
                return Response({"error": "Stock name not found"}, status=status.HTTP_404_NOT_FOUND)
            
            ltp_resp = self.get_ltp(symbol)
            ltp = ltp_resp["ltp"]
            
            if "error" in ltp:
                return Response(ltp, status=503)
            
            # Get or create user balance
            balance, created = UserBalance.objects.get_or_create(
                user=user,
                room=room,
                defaults={
                    'total_cash_balance': Decimal('100000.00'),
                    'reserved_cash_balance': Decimal('0.00')
                }
            )
            
            if order_category == "MARKET":
                # Validate stop loss price against current price for buy orders
                if has_stop_loss and stop_loss_trigger_price >= ltp:
                    return Response({
                        "error": "Stop loss trigger price must be below the current market price for buy orders"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                total_cost = ltp * Decimal(quantity)

                # Check if user has sufficient available balance
                if balance.available_cash_balance < total_cost:
                    return Response({
                        "error": "Insufficient balance",
                        "required": float(total_cost),
                        "available": float(balance.available_cash_balance)
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Reserve and execute the cash
                if not balance.reserve_cash(total_cost):
                    return Response({
                        "error": "Failed to reserve cash for the order"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                if not balance.execute_cash_reservation(total_cost):
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
                    order_price=ltp,
                    order_category=OrderBook.MARKET,
                    order_status=OrderBook.EXECUTED, 
                    executed_price=ltp,
                    execution_timestamp=timezone.now(),
                    has_stop_loss=has_stop_loss,
                    stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                    stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None
                )

                # Create stop loss order if requested
                stop_loss_order = None
                if has_stop_loss:
                    stop_loss_order = self.create_stop_loss_order(
                        user=user,
                        room=room,
                        symbol=symbol,
                        quantity=quantity,
                        stop_loss_trigger_price=stop_loss_trigger_price,
                        stop_loss_limit_price=stop_loss_limit_price,
                        stock_name=stock_name,
                        original_order_id=order.id
                    )
                    
                    if not stop_loss_order:
                        print(f"Warning: Failed to create stop loss order for order {order.id}")

                # Update portfolio
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
                    portfolio.stock_name = stock_name
                portfolio.add_buy_transaction(quantity, ltp)
                portfolio.save()

                # Create trade record
                trade = Trade.objects.create(
                    user=user,
                    room=room,
                    order=order,
                    trade_type=Trade.BUY,
                    symbol=symbol,
                    quantity=quantity,
                    price=ltp,
                    total_value=total_cost
                )

                response_data = {
                    "success": True,
                    "message": "Buy order executed successfully",
                    "order_id": order.id,
                    "trade_id": trade.id,
                    "symbol": symbol,
                    "quantity": quantity,
                    "executed_price": float(ltp),
                    "total_cost": float(total_cost),
                    "remaining_balance": float(balance.available_cash_balance)
                }

                if has_stop_loss:
                    response_data.update({
                        "stop_loss_enabled": True,
                        "stop_loss_trigger_price": float(stop_loss_trigger_price),
                        "stop_loss_limit_price": float(stop_loss_limit_price),
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
                if has_stop_loss and stop_loss_trigger_price >= limit_price:
                    return Response({
                        "error": "Stop loss trigger price must be below the limit price for buy orders"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                total_limit_cost = limit_price * Decimal(quantity)

                if balance.available_cash_balance < total_limit_cost:
                    return Response({
                        "error": "Insufficient balance",
                        "required": float(total_limit_cost),
                        "available": float(balance.available_cash_balance)
                    }, status=status.HTTP_400_BAD_REQUEST)

                # NEW LOGIC: Check if limit price >= current LTP
                if limit_price >= ltp:
                    # Immediate partial execution at current LTP
                    executable_quantity = min(quantity, int(balance.available_cash_balance / ltp))
                    immediate_cost = ltp * Decimal(executable_quantity)
                    remaining_quantity = quantity - executable_quantity
                    
                    # Reserve total limit cost first
                    if not balance.reserve_cash(total_limit_cost):
                        return Response({
                            "error": "Failed to reserve cash for the order"
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
                    # Execute immediate portion
                    executed_order = None
                    trade = None
                    if executable_quantity > 0:
                        executed_order, trade = self.execute_partial_buy_order(
                            user, room, symbol, executable_quantity, ltp, stock_name, balance
                        )
                        
                        if not executed_order:
                            balance.release_cash_reservation(total_limit_cost)
                            return Response({
                                "error": "Failed to execute immediate portion of the order"
                            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
                    # Create pending order for remaining quantity (if any)
                    pending_order = None
                    if remaining_quantity > 0:
                        pending_order = OrderBook.objects.create(
                            user=user,
                            room=room,
                            order_type=OrderBook.BUY,
                            symbol=symbol,
                            quantity=remaining_quantity,
                            order_price=limit_price,
                            order_category=OrderBook.LIMIT,
                            order_status=OrderBook.PENDING,
                            executed_price=None,
                            execution_timestamp=None,
                            has_stop_loss=has_stop_loss,
                            stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                            stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None,
                            parent_order_id=executed_order.id if executed_order else None
                        )
                    
                    # Create stop loss order for executed quantity only
                    stop_loss_order = None
                    if has_stop_loss and executed_order:
                        stop_loss_order = self.create_stop_loss_order(
                            user=user,
                            room=room,
                            symbol=symbol,
                            quantity=executable_quantity,
                            stop_loss_trigger_price=stop_loss_trigger_price,
                            stop_loss_limit_price=stop_loss_limit_price,
                            stock_name=stock_name,
                            original_order_id=executed_order.id
                        )
                    
                    response_data = {
                        "success": True,
                        "message": f"Limit order partially executed: {executable_quantity} shares at market price, {remaining_quantity} shares pending at limit price",
                        "executed_order_id": executed_order.id if executed_order else None,
                        "pending_order_id": pending_order.id if pending_order else None,
                        "trade_id": trade.id if trade else None,
                        "symbol": symbol,
                        "total_quantity": quantity,
                        "executed_quantity": executable_quantity,
                        "pending_quantity": remaining_quantity,
                        "executed_price": float(ltp) if executed_order else None,
                        "limit_price": float(limit_price),
                        "immediate_cost": float(immediate_cost) if executed_order else 0,
                        "remaining_balance": float(balance.available_cash_balance)
                    }
                    
                    if has_stop_loss and executed_order:
                        response_data.update({
                            "stop_loss_enabled": True,
                            "stop_loss_trigger_price": float(stop_loss_trigger_price),
                            "stop_loss_limit_price": float(stop_loss_limit_price),
                            "stop_loss_order_id": stop_loss_order.id if stop_loss_order else None,
                            "stop_loss_note": "Stop loss created for executed quantity only"
                        })
                    
                    return Response(response_data, status=status.HTTP_201_CREATED)
                
                else:
                    # Traditional limit order logic (limit_price < current_ltp)
                    # Reserve the cash for the limit order (but don't execute yet)
                    if not balance.reserve_cash(total_limit_cost):
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
                        stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                        stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None
                    )

                    response_data = {
                        "success": True,
                        "message": "Limit buy order placed successfully",
                        "order_id": order.id,
                        "symbol": symbol,
                        "quantity": quantity,
                        "limit_price": float(limit_price),
                        "total_cost": float(total_limit_cost),
                        "order_status": "PENDING",
                        "remaining_balance": float(balance.available_cash_balance)
                    }

                    if has_stop_loss:
                        response_data.update({
                            "stop_loss_enabled": True,
                            "stop_loss_trigger_price": float(stop_loss_trigger_price),
                            "stop_loss_limit_price": float(stop_loss_limit_price),
                            "message": "Limit buy order placed successfully with stop loss. Stop loss order will be created when the buy order is executed."
                        })

                    return Response(response_data, status=status.HTTP_201_CREATED)
            
            else:
                return Response({"error": "Invalid order category"}, status=status.HTTP_400_BAD_REQUEST)

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

    def create_stop_loss_order(self, user, room, symbol, quantity, stop_loss_trigger_price, stop_loss_limit_price, stock_name, original_order_id, is_short_sell=False):
        """Create a stop loss buy order (for short positions) with trigger and limit prices"""
        try:
            stop_loss_order = OrderBook.objects.create(
                user=user,
                room=room,
                order_type=OrderBook.BUY,  # Stop loss for sell/short is a BUY order
                symbol=symbol,
                quantity=quantity,
                order_price=stop_loss_limit_price,
                order_category=OrderBook.STOP_LOSS,
                order_status=OrderBook.PENDING,
                executed_price=None,
                execution_timestamp=None,
                parent_order_id=original_order_id,
                stop_loss_trigger_price=stop_loss_trigger_price,
                stop_loss_limit_price=stop_loss_limit_price,
                remaining_quantity=quantity,
                is_short_sell=is_short_sell
            )
            return stop_loss_order
        except Exception as e:
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
            is_short_sell = data.get("is_short_sell", False)
            
            # Stop loss fields
            has_stop_loss = data.get("has_stop_loss", False)
            stop_loss_trigger_price = data.get("stop_loss_trigger_price")
            stop_loss_limit_price = data.get("stop_loss_limit_price")

            if not symbol or quantity <= 0:
                return Response({"error": "Invalid input: symbol and positive quantity are required"}, status=status.HTTP_400_BAD_REQUEST)

            if not order_category:
                return Response({"error": "Please mention order category"})

            # Validate stop loss if provided
            if has_stop_loss:
                if not stop_loss_trigger_price or not stop_loss_limit_price:
                    return Response({
                        "error": "Both trigger price and limit price are required for stop loss orders"
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    stop_loss_trigger_price = Decimal(str(stop_loss_trigger_price))
                    stop_loss_limit_price = Decimal(str(stop_loss_limit_price))
                    
                    if stop_loss_trigger_price <= 0 or stop_loss_limit_price <= 0:
                        return Response({
                            "error": "Stop loss prices must be greater than 0"
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    if stop_loss_limit_price < stop_loss_trigger_price:
                        return Response({
                            "error": "Stop loss limit price must be greater than or equal to trigger price for sell orders"
                        }, status=status.HTTP_400_BAD_REQUEST)
                        
                except (ValueError, TypeError, InvalidOperation):
                    return Response({"error": "Invalid stop loss price format"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if stock exists
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

            # Fetch or create portfolio
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

            # Fetch or create user's balance
            balance, created = UserBalance.objects.get_or_create(
                user=user,
                room=room,
                defaults={
                    'total_cash_balance': Decimal('100000.00'),
                    'reserved_cash_balance': Decimal('0.00')
                }
            )

            if order_category == "MARKET":
                # Validate stop loss price against current price
                if has_stop_loss and stop_loss_trigger_price <= current_price:
                    return Response({
                        "error": "Stop loss trigger price must be above the current market price for sell/short orders"
                    }, status=status.HTTP_400_BAD_REQUEST)

                if not is_short_sell:
                    # Regular sell - check if user has sufficient quantity
                    if portfolio.available_quantity < quantity:
                        return Response({
                            "error": "Insufficient quantity in portfolio",
                            "requested": quantity,
                            "available": portfolio.available_quantity
                        }, status=status.HTTP_400_BAD_REQUEST)

                    # Execute regular sell
                    total_proceeds = current_price * Decimal(quantity)

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
                        execution_timestamp=timezone.now(),
                        is_short_sell=False,
                        has_stop_loss=has_stop_loss,
                        stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                        stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None
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

                    # Create stop loss order if requested
                    stop_loss_order = None
                    if has_stop_loss:
                        stop_loss_order = self.create_stop_loss_order(
                            user=user,
                            room=room,
                            symbol=symbol,
                            quantity=quantity,
                            stop_loss_trigger_price=stop_loss_trigger_price,
                            stop_loss_limit_price=stop_loss_limit_price,
                            stock_name=stock_name,
                            original_order_id=order.id,
                            is_short_sell=False
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

                    if has_stop_loss:
                        response_data.update({
                            "stop_loss_enabled": True,
                            "stop_loss_trigger_price": float(stop_loss_trigger_price),
                            "stop_loss_limit_price": float(stop_loss_limit_price),
                            "stop_loss_order_id": stop_loss_order.id if stop_loss_order else None
                        })

                else:
                    # Short sell - no quantity check needed
                    total_proceeds = current_price * Decimal(quantity)

                    # Create the short sell order
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
                        execution_timestamp=timezone.now(),
                                                is_short_sell=True,
                        has_stop_loss=has_stop_loss,
                        stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                        stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None
                    )

                    # Add short position to portfolio
                    portfolio.add_short_position(quantity, current_price)

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

                    # Create stop loss order if requested
                    stop_loss_order = None
                    if has_stop_loss:
                        stop_loss_order = self.create_stop_loss_order(
                            user=user,
                            room=room,
                            symbol=symbol,
                            quantity=quantity,
                            stop_loss_trigger_price=stop_loss_trigger_price,
                            stop_loss_limit_price=stop_loss_limit_price,
                            stock_name=stock_name,
                            original_order_id=order.id,
                            is_short_sell=True
                        )

                    response_data = {
                        "success": True,
                        "message": "Short sell order executed successfully",
                        "order_id": order.id,
                        "trade_id": trade.id,
                        "symbol": symbol,
                        "quantity": quantity,
                        "executed_price": float(current_price),
                        "total_proceeds": float(total_proceeds),
                        "new_balance": float(balance.available_cash_balance),
                        "previous_balance": float(previous_balance),
                        "is_short_sell": True,
                        "portfolio": {
                            "long_quantity": portfolio.total_quantity,
                            "short_quantity": portfolio.short_quantity,
                            "net_position": portfolio.net_position,
                            "average_short_price": float(portfolio.average_short_price),
                            "realized_pnl": float(portfolio.realized_pnl)
                        }
                    }

                    if has_stop_loss:
                        response_data.update({
                            "stop_loss_enabled": True,
                            "stop_loss_trigger_price": float(stop_loss_trigger_price),
                            "stop_loss_limit_price": float(stop_loss_limit_price),
                            "stop_loss_order_id": stop_loss_order.id if stop_loss_order else None,
                            "stop_loss_type": "BUY"  # Stop loss for short is a buy order
                        })

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
                
                # Validate stop loss price against limit price
                if has_stop_loss and stop_loss_trigger_price <= limit_price:
                    return Response({
                        "error": "Stop loss trigger price must be above the limit price for sell orders"
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Check if immediate execution is possible (LTP >= limit price for sell)
                if current_price >= limit_price:
                    # Immediate execution at current price
                    if not is_short_sell:
                        # Regular sell - check quantity
                        if portfolio.available_quantity < quantity:
                            # Partial execution based on available quantity
                            quantity_to_execute = portfolio.available_quantity
                            remaining_quantity = quantity - quantity_to_execute
                            
                            if quantity_to_execute <= 0:
                                return Response({
                                    "error": "No shares available to sell",
                                    "requested": quantity,
                                    "available": 0
                                }, status=status.HTTP_400_BAD_REQUEST)
                        else:
                            quantity_to_execute = quantity
                            remaining_quantity = 0

                        # Execute immediate portion
                        immediate_proceeds = current_price * Decimal(quantity_to_execute)

                        # Create the order
                        order = OrderBook.objects.create(
                            user=user,
                            room=room,
                            order_type=OrderBook.SELL,
                            symbol=symbol,
                            quantity=quantity,  # Total requested quantity
                            order_price=limit_price,
                            order_category=OrderBook.LIMIT,
                            order_status=OrderBook.PARTIALLY_EXECUTED if remaining_quantity > 0 else OrderBook.EXECUTED,
                            filled_quantity=quantity_to_execute,
                            executed_price=current_price,
                            execution_timestamp=timezone.now() if quantity_to_execute > 0 else None,
                            partially_executed_quantity=quantity_to_execute,
                            remaining_quantity=remaining_quantity,
                            is_short_sell=False,
                            has_stop_loss=has_stop_loss,
                            stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                            stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None
                        )

                        # Execute the sell transaction
                        if quantity_to_execute > 0:
                            portfolio.add_sell_transaction(quantity_to_execute, current_price)
                            balance.add_cash(immediate_proceeds)

                            # Create trade record
                            trade = Trade.objects.create(
                                user=user,
                                room=room,
                                order=order,
                                trade_type=Trade.SELL,
                                symbol=symbol,
                                quantity=quantity_to_execute,
                                price=current_price,
                                total_value=immediate_proceeds
                            )

                            # Create stop loss if fully executed
                            stop_loss_order = None
                            if has_stop_loss and remaining_quantity == 0:
                                stop_loss_order = self.create_stop_loss_order(
                                    user=user,
                                    room=room,
                                    symbol=symbol,
                                    quantity=quantity_to_execute,
                                    stop_loss_trigger_price=stop_loss_trigger_price,
                                    stop_loss_limit_price=stop_loss_limit_price,
                                    stock_name=stock_name,
                                    original_order_id=order.id,
                                    is_short_sell=False
                                )

                        response_data = {
                            "success": True,
                            "message": f"Limit sell order: {quantity_to_execute} shares executed at {float(current_price)}" + 
                                      (f", {remaining_quantity} shares pending" if remaining_quantity > 0 else ""),
                            "order_id": order.id,
                            "symbol": symbol,
                            "total_quantity": quantity,
                            "executed_quantity": quantity_to_execute,
                            "executed_price": float(current_price) if quantity_to_execute > 0 else None,
                            "remaining_quantity": remaining_quantity,
                            "limit_price": float(limit_price),
                            "immediate_proceeds": float(immediate_proceeds) if quantity_to_execute > 0 else 0,
                            "order_status": order.order_status,
                            "new_balance": float(balance.available_cash_balance),
                            "portfolio": {
                                "remaining_quantity": portfolio.total_quantity,
                                "average_price": float(portfolio.average_buy_price),
                                "realized_pnl": float(portfolio.realized_pnl)
                            }
                        }

                        if quantity_to_execute > 0:
                            response_data["trade_id"] = trade.id

                        if has_stop_loss:
                            response_data.update({
                                "stop_loss_enabled": True,
                                "stop_loss_trigger_price": float(stop_loss_trigger_price),
                                "stop_loss_limit_price": float(stop_loss_limit_price),
                                "stop_loss_order_id": stop_loss_order.id if stop_loss_order else None,
                                "stop_loss_note": "Stop loss will be created after full order execution" if remaining_quantity > 0 else "Stop loss order created"
                            })

                    else:
                        # Short sell - immediate execution
                        immediate_proceeds = current_price * Decimal(quantity)

                        # Create the order
                        order = OrderBook.objects.create(
                            user=user,
                            room=room,
                            order_type=OrderBook.SELL,
                            symbol=symbol,
                            quantity=quantity,
                            order_price=limit_price,
                            order_category=OrderBook.LIMIT,
                            order_status=OrderBook.EXECUTED,
                            filled_quantity=quantity,
                            executed_price=current_price,
                            execution_timestamp=timezone.now(),
                            is_short_sell=True,
                            has_stop_loss=has_stop_loss,
                            stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                            stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None
                        )

                        # Add short position
                        portfolio.add_short_position(quantity, current_price)
                        balance.add_cash(immediate_proceeds)

                        # Create trade record
                        trade = Trade.objects.create(
                            user=user,
                            room=room,
                            order=order,
                            trade_type=Trade.SELL,
                            symbol=symbol,
                            quantity=quantity,
                            price=current_price,
                            total_value=immediate_proceeds
                        )

                        # Create stop loss if requested
                        stop_loss_order = None
                        if has_stop_loss:
                            stop_loss_order = self.create_stop_loss_order(
                                user=user,
                                room=room,
                                symbol=symbol,
                                quantity=quantity,
                                stop_loss_trigger_price=stop_loss_trigger_price,
                                stop_loss_limit_price=stop_loss_limit_price,
                                stock_name=stock_name,
                                original_order_id=order.id,
                                is_short_sell=True
                            )

                        response_data = {
                            "success": True,
                            "message": "Short sell limit order executed immediately at market price",
                            "order_id": order.id,
                            "trade_id": trade.id,
                            "symbol": symbol,
                            "quantity": quantity,
                            "executed_price": float(current_price),
                            "limit_price": float(limit_price),
                            "total_proceeds": float(immediate_proceeds),
                            "new_balance": float(balance.available_cash_balance),
                            "is_short_sell": True,
                            "portfolio": {
                                "long_quantity": portfolio.total_quantity,
                                "short_quantity": portfolio.short_quantity,
                                "net_position": portfolio.net_position,
                                "average_short_price": float(portfolio.average_short_price),
                                "realized_pnl": float(portfolio.realized_pnl)
                            }
                        }

                        if has_stop_loss:
                            response_data.update({
                                "stop_loss_enabled": True,
                                "stop_loss_trigger_price": float(stop_loss_trigger_price),
                                "stop_loss_limit_price": float(stop_loss_limit_price),
                                "stop_loss_order_id": stop_loss_order.id if stop_loss_order else None,
                                "stop_loss_type": "BUY"
                            })

                    return Response(response_data, status=status.HTTP_201_CREATED)

                else:
                    # LTP < limit price, place as pending order
                    if not is_short_sell:
                        # Regular sell - check and reserve quantity
                        if portfolio.available_quantity < quantity:
                            return Response({
                                "error": "Insufficient quantity in portfolio",
                                "requested": quantity,
                                "available": portfolio.available_quantity
                            }, status=status.HTTP_400_BAD_REQUEST)

                        # Reserve the quantity
                        if not portfolio.reserve_quantity(quantity):
                            return Response({
                                "error": "Failed to reserve quantity for limit order"
                            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                    # Create pending order
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
                        execution_timestamp=None,
                        remaining_quantity=quantity,
                        is_short_sell=is_short_sell,
                        has_stop_loss=has_stop_loss,
                        stop_loss_trigger_price=stop_loss_trigger_price if has_stop_loss else None,
                        stop_loss_limit_price=stop_loss_limit_price if has_stop_loss else None
                    )

                    response_data = {
                        "success": True,
                        "message": f"Limit {'short ' if is_short_sell else ''}sell order placed successfully",
                        "order_id": order.id,
                        "symbol": symbol,
                        "quantity": quantity,
                        "limit_price": float(limit_price),
                        "current_ltp": float(current_price),
                        "order_status": "PENDING",
                        "is_short_sell": is_short_sell
                    }

                    if not is_short_sell:
                        response_data["portfolio"] = {
                            "total_quantity": portfolio.total_quantity,
                            "available_quantity": portfolio.available_quantity,
                            "reserved_quantity": portfolio.reserved_quantity
                        }

                    if has_stop_loss:
                        response_data.update({
                            "stop_loss_enabled": True,
                            "stop_loss_trigger_price": float(stop_loss_trigger_price),
                            "stop_loss_limit_price": float(stop_loss_limit_price),
                            "message": response_data["message"] + ". Stop loss order will be created when the sell order is executed."
                        })

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

    def get(self, request, room_id, username):
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

            # Validate user exists by username
            user = get_object_or_404(User, username=username)

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
            trades = Trade.objects.filter(user=user, room=room).order_by('-timestamp')[:20]
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
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
import logging
from django.conf import settings

from .services import trading_service,balance_service, portfolio_service
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

        user_balance = balance_service.get_or_create_balance(user, room)

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
            balance = balance_service.get_or_create_balance(participant.user, room)
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
           
            balance = balance_service.get_or_create_balance(participant.user, room)
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

            # Extract order data
            symbol = data.get("symbol")
            quantity = int(data.get("quantity", 0))
            price_per_stock = Decimal(data.get("price_per_stock", 0))

            if not symbol or quantity <= 0 or price_per_stock <= 0:
                return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)

            # Prepare order data for trading service
            order_data = {
                'order_type': OrderBook.BUY,
                'symbol': symbol,
                'quantity': quantity,
                'order_price': price_per_stock,
                'order_category': OrderBook.MARKET,  # Market order for immediate execution
            }

            # Use trading service to place the order
            success, message, order = trading_service.place_order(user, room, order_data)

            if success:
                return Response({
                    "message": message,
                    "order_id": order.id if order else None,
                    "trade_executed": True
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

        except ValueError as e:
            return Response({"error": f"Invalid data format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
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

            # Extract order data
            symbol = data.get("symbol")
            quantity = int(data.get("quantity", 0))
            price_per_stock = Decimal(data.get("price_per_stock", 0))

            if not symbol or quantity <= 0 or price_per_stock <= 0:
                return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)

            # Prepare order data for trading service
            order_data = {
                'order_type': OrderBook.SELL,
                'symbol': symbol,
                'quantity': quantity,
                'order_price': price_per_stock,
                'order_category': OrderBook.MARKET,  # Market order for immediate execution
            }

            # Use trading service to place the order
            success, message, order = trading_service.place_order(user, room, order_data)

            if success:
                return Response({
                    "message": message,
                    "order_id": order.id if order else None,
                    "trade_executed": True
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

        except ValueError as e:
            return Response({"error": f"Invalid data format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
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

        # Use trading service to get leaderboard
        leaderboard = trading_service.get_room_leaderboard(room)

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
        trades = Trade.objects.filter(user=user, room=room).order_by("-trade_timestamp")

        trade_history = [
            {
                "symbol": trade.symbol,
                "trade_type": trade.trade_type,
                "quantity": trade.quantity,
                "price": str(trade.price),
                "total_value": str(trade.total_value),
                "timestamp": trade.trade_timestamp,
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

        # Use trading service to get comprehensive user portfolio summary
        portfolio_summary = trading_service.get_user_portfolio_summary(user, room)

        # Get detailed holdings
        from .models import UserPortfolio
        portfolios = UserPortfolio.objects.filter(user=user, room=room, total_quantity__gt=0)
        
        holdings = []
        for portfolio in portfolios:
            # Get current market data for each holding
            # market_data = market_service.get_market_data(portfolio.symbol)
            # current_price = market_data['ltp'] if market_data else portfolio.average_buy_price
            
            holdings.append({
                "symbol": portfolio.symbol,
                "quantity": portfolio.total_quantity,
                "average_buy_price": str(portfolio.average_buy_price),
                # "current_price": str(current_price),
                "total_buy_value": str(portfolio.total_buy_value),
                # "current_value": str(portfolio.total_quantity * current_price),
                # "unrealized_pnl": str(portfolio.calculate_unrealized_pnl(current_price))
            })

        trades = Trade.objects.filter(user=user, room=room).order_by('-trade_timestamp')[:20]
        trade_history = [
            {
                "symbol": trade.symbol,
                "type": trade.trade_type,
                "quantity": trade.quantity,
                "price": str(trade.price),
                "total_value": str(trade.total_value),
                "timestamp": trade.trade_timestamp
            }
            for trade in trades
        ]

        return Response({
            "username": user.username,
            "portfolio_summary": portfolio_summary,
            "stock_holdings": holdings,
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
                'code': getattr(room, 'code', None),  
                'has_password': bool(room.password),  
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

            # Use trading service to get comprehensive portfolio summary
            portfolio_summary = trading_service.get_user_portfolio_summary(request.user, room)

            # Get detailed holdings
            from .models import UserPortfolio
            portfolios = UserPortfolio.objects.filter(user=request.user, room=room, total_quantity__gt=0)
            
            holdings = []
            for portfolio in portfolios:
                # Get current market data for each holding
                # market_data = market_service.get_market_data(portfolio.symbol)
                # current_price = market_data['ltp'] if market_data else portfolio.average_buy_price
                
                holdings.append({
                    "symbol": portfolio.symbol,
                    "quantity": portfolio.total_quantity,
                    "average_buy_price": str(portfolio.average_buy_price),
                    # "current_price": str(current_price),
                    "total_investment": str(portfolio.total_buy_value - portfolio.total_sell_value),
                    # "current_value": str(portfolio.total_quantity * current_price),
                    # "unrealized_pnl": str(portfolio.calculate_unrealized_pnl(current_price)),
                    "realized_pnl": str(portfolio.realized_pnl)
                })

            return Response({
                "portfolio_summary": portfolio_summary,
                "holdings": holdings,
                "room": {
                    "id": room.id,
                    "name": room.name
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

            orders = OrderBook.objects.filter(user=request.user, room=room).order_by('-order_timestamp')

            order_history = []
            for order in orders:
                order_history.append({
                    "id": order.id,
                    "symbol": order.symbol,
                    "order_type": order.order_type,
                    "order_category": order.order_category,
                    "quantity": order.quantity,
                    "filled_quantity": order.filled_quantity,
                    "remaining_quantity": order.remaining_quantity,
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

class CancelOrderView(APIView):
    """
    New view to cancel pending orders
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

            reason = request.data.get('reason', '')

            # Use trading service to cancel the order
            success, message = trading_service.cancel_order(order, reason)

            if success:
                return Response({"message": message}, status=status.HTTP_200_OK)
            else:
                return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Keep the existing historical data views as they are working well

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
                "day": ("days", "1"),
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
            historical_api = upstox_client.HistoryV3Api()

            try:
                response = historical_api.get_historical_candle_data1(
                    instrument_key=instrument_key,
                    interval=interval,
                    unit=unit,
                    from_date="2024-06-01",
                    to_date="2024-06-30"
                )

                candles = getattr(response, 'candles', [])
                if not candles:
                    return Response({
                        "error": "No historical data found for the symbol",
                        "symbol": symbol
                    }, status=status.HTTP_404_NOT_FOUND)

                # Format candles
                formatted = [
                    {
                        "timestamp": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5])
                    }
                    for c in candles if len(c) >= 6
                ]

                return Response({
                    "symbol": symbol,
                    "interval": interval,
                    "from_date": from_date,
                    "to_date": to_date,
                    "candles": formatted
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
                cache.set(cache_key, instrument_key, 600)  # cache for 10 minutes
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

# class BatchMarketDataView(APIView):
#     """
#     View to get market data for multiple symbols at once
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

#             symbols = request.data.get('symbols', [])
#             if not symbols or not isinstance(symbols, list):
#                 return Response({
#                     "error": "Symbols array is required"
#                 }, status=status.HTTP_400_BAD_REQUEST)

#             if len(symbols) > 50:  # Limit batch size
#                 return Response({
#                     "error": "Maximum 50 symbols allowed per batch request"
#                 }, status=status.HTTP_400_BAD_REQUEST)

#             market_data_results = {}
#             failed_symbols = []

#             for symbol in symbols:
#                 try:
#                     market_data = market_service.get_market_data(symbol.strip().upper())
#                     if market_data:
#                         market_data_results[symbol] = market_data
#                     else:
#                         failed_symbols.append(symbol)
#                 except Exception as e:
#                     failed_symbols.append(symbol)

#             return Response({
#                 "success": True,
#                 "market_data": market_data_results,
#                 "failed_symbols": failed_symbols,
#                 "total_requested": len(symbols),
#                 "successful": len(market_data_results),
#                 "failed": len(failed_symbols)
#             }, status=status.HTTP_200_OK)

#         except Exception as e:
#             return Response({
#                 "error": f"An error occurred: {str(e)}"
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
            if is_admin:
                leaderboard = trading_service.get_room_leaderboard(room)
                top_traders = leaderboard[:5]  # Top 5 traders

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


class PlaceLimitOrderView(APIView):
    """
    View to place limit orders (not executed immediately)
    """
    permission_classes = [IsAuthenticated]

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

            # Extract order data
            symbol = data.get("symbol")
            quantity = int(data.get("quantity", 0))
            price_per_stock = Decimal(data.get("price_per_stock", 0))
            order_type = data.get("order_type", "").upper()

            if not symbol or quantity <= 0 or price_per_stock <= 0:
                return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)

            if order_type not in [OrderBook.BUY, OrderBook.SELL]:
                return Response({"error": "Invalid order type"}, status=status.HTTP_400_BAD_REQUEST)

            # Prepare order data for trading service
            order_data = {
                'order_type': order_type,
                'symbol': symbol,
                'quantity': quantity,
                'order_price': price_per_stock,
                'order_category': OrderBook.LIMIT,  # Limit order
            }

            # Use trading service to place the order
            success, message, order = trading_service.place_order(user, room, order_data)

            if success:
                return Response({
                    "message": message,
                    "order_id": order.id if order else None,
                    "order_status": "pending"
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

        except ValueError as e:
            return Response({"error": f"Invalid data format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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


class BulkCancelOrdersView(APIView):
    """
    View to cancel multiple pending orders at once
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
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

            order_ids = request.data.get('order_ids', [])
            if not order_ids or not isinstance(order_ids, list):
                return Response({
                    "error": "order_ids array is required"
                }, status=status.HTTP_400_BAD_REQUEST)

            if len(order_ids) > 20:  # Limit bulk operations
                return Response({
                    "error": "Maximum 20 orders can be cancelled at once"
                }, status=status.HTTP_400_BAD_REQUEST)

            reason = request.data.get('reason', 'Bulk cancellation')
            
            cancelled_orders = []
            failed_orders = []

            for order_id in order_ids:
                try:
                    order = OrderBook.objects.get(id=order_id, user=request.user, room=room)
                    success, message = trading_service.cancel_order(order, reason)
                    
                    if success:
                        cancelled_orders.append({
                            "order_id": order_id,
                            "symbol": order.symbol,
                            "status": "cancelled"
                        })
                    else:
                        failed_orders.append({
                            "order_id": order_id,
                            "error": message
                        })
                        
                except OrderBook.DoesNotExist:
                    failed_orders.append({
                        "order_id": order_id,
                        "error": "Order not found"
                    })
                except Exception as e:
                    failed_orders.append({
                        "order_id": order_id,
                        "error": str(e)
                    })

            return Response({
                "message": f"Processed {len(order_ids)} orders",
                "cancelled": cancelled_orders,
                "failed": failed_orders,
                "cancelled_count": len(cancelled_orders),
                "failed_count": len(failed_orders)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "error": f"An error occurred: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Additional utility views can be added here as needed
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

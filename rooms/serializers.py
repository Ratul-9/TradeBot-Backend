from rest_framework import serializers
from .models import (
    Room, RoomParticipant, UserBalance, OrderBook, UserPortfolio, 
    Trade, MarketData, TradingSession, Stock, SMEStock
)
from decimal import Decimal

class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ['id', 'name', 'password', 'start_time', 'end_time', 'is_closed']
        extra_kwargs = {'password': {'write_only': True}}

class JoinRoomSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=50, required=False, allow_blank=True)

class LeaveRoomSerializer(serializers.Serializer):
    pass

class LiveRoomStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ['is_closed']

class CloseRoomSerializer(serializers.Serializer):
    pass

class OrderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderBook
        fields = [
            'order_type', 'order_category', 'symbol', 'quantity', 
            'order_price', 'notes'
        ]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        return value

    def validate_order_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value

    def validate(self, data):
        # Additional business logic validation
        order_type = data.get('order_type')
        quantity = data.get('quantity')
        price = data.get('order_price')

        # Check for reasonable price ranges (you can customize this)
        if price > Decimal('100000'):
            raise serializers.ValidationError("Price seems unreasonably high")

        # Check for reasonable quantity
        if quantity > 10000:
            raise serializers.ValidationError("Quantity seems unreasonably high")

        return data

class OrderBookSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    remaining_quantity = serializers.IntegerField(read_only=True)
    is_fully_filled = serializers.BooleanField(read_only=True)
    total_order_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    executed_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = OrderBook
        fields = [
            'id', 'username', 'room_name', 'order_type', 'order_category',
            'symbol', 'quantity', 'filled_quantity', 'remaining_quantity',
            'order_price', 'executed_price', 'order_status', 
            'order_timestamp', 'execution_timestamp', 'cancellation_timestamp',
            'notes', 'is_fully_filled', 'total_order_value', 'executed_value'
        ]

class UserPortfolioSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)
    current_market_value = serializers.SerializerMethodField()
    unrealized_pnl = serializers.SerializerMethodField()
    total_pnl = serializers.SerializerMethodField()

    class Meta:
        model = UserPortfolio
        fields = [
            'id', 'username', 'room_name', 'symbol', 'total_quantity', 
            'reserved_quantity', 'available_quantity', 'average_buy_price',
            'total_buy_value', 'total_sell_value', 'realized_pnl',
            'current_market_value', 'unrealized_pnl', 'total_pnl',
            'created_at', 'updated_at'
        ]

    def get_current_market_value(self, obj):
        # Get current LTP for the symbol
        try:
            market_data = MarketData.objects.get(symbol=obj.symbol)
            return obj.total_quantity * market_data.ltp
        except MarketData.DoesNotExist:
            return obj.total_quantity * obj.average_buy_price

    def get_unrealized_pnl(self, obj):
        try:
            market_data = MarketData.objects.get(symbol=obj.symbol)
            return obj.calculate_unrealized_pnl(market_data.ltp)
        except MarketData.DoesNotExist:
            return Decimal('0.00')

    def get_total_pnl(self, obj):
        unrealized = self.get_unrealized_pnl(obj)
        return obj.realized_pnl + unrealized

class TradeSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    net_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = Trade
        fields = [
            'id', 'username', 'room_name', 'order_id', 'trade_type',
            'symbol', 'quantity', 'price', 'total_value', 'net_value',
            'timestamp', 'execution_id', 'market_price_at_execution', 'fees'
        ]

class MarketDataSerializer(serializers.ModelSerializer):
    is_stale = serializers.BooleanField(read_only=True)
    price_change = serializers.SerializerMethodField()

    class Meta:
        model = MarketData
        fields = [
            'symbol', 'ltp', 'open_price', 'high_price', 'low_price',
            'close_price', 'volume', 'change_percent', 'price_change',
            'last_updated', 'is_stale'
        ]

    def get_price_change(self, obj):
        if obj.close_price and obj.ltp:
            return obj.ltp - obj.close_price
        return Decimal('0.00')

class UserBalanceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    available_cash_balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    cash_balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = UserBalance
        fields = [
            'id', 'username', 'room_name', 'total_cash_balance',
            'reserved_cash_balance', 'available_cash_balance', 'cash_balance',
            'created_at', 'updated_at'
        ]

class TradingSessionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    room_name = serializers.CharField(source='room.name', read_only=True)
    session_duration = serializers.DurationField(read_only=True)
    net_pnl = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = TradingSession
        fields = [
            'id', 'username', 'room_name', 'session_start', 'session_end',
            'starting_balance', 'ending_balance', 'total_trades',
            'total_buy_value', 'total_sell_value', 'realized_pnl',
            'net_pnl', 'session_duration', 'is_active'
        ]

class StockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stock
        fields = [
            'symbol', 'name_of_company', 'series', 'date_of_listing',
            'paid_up_value', 'isin_number', 'face_value'
        ]

class SMEStockSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMEStock
        fields = [
            'symbol', 'name_of_company', 'series', 'date_of_listing',
            'paid_up_value', 'isin_number', 'face_value'
        ]

class PortfolioSummarySerializer(serializers.Serializer):
    """Serializer for complete portfolio summary"""
    cash_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_investment = serializers.DecimalField(max_digits=15, decimal_places=2)
    current_portfolio_value = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_realized_pnl = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_unrealized_pnl = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_pnl = serializers.DecimalField(max_digits=15, decimal_places=2)
    net_worth = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_trades = serializers.IntegerField()
    holdings_count = serializers.IntegerField()

class LeaderboardEntrySerializer(serializers.Serializer):
    """Serializer for leaderboard entries"""
    username = serializers.CharField()
    net_worth = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_pnl = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_trades = serializers.IntegerField()
    rank = serializers.IntegerField()
    percentage_return = serializers.DecimalField(max_digits=5, decimal_places=2)

class OrderCancelSerializer(serializers.Serializer):
    """Serializer for order cancellation"""
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

class BulkTradeSerializer(serializers.Serializer):
    """Serializer for bulk trade operations"""
    orders = OrderCreateSerializer(many=True)

    def validate_orders(self, value):
        if len(value) > 10:
            raise serializers.ValidationError("Cannot place more than 10 orders at once")
        return value
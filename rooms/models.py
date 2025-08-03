from django.db import models
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from decimal import Decimal

User = get_user_model()

class Room(models.Model):
    name = models.CharField(max_length=100)
    password = models.CharField(max_length=50, blank=True, null=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_rooms', null=True) 

    def __str__(self):
        return f"Room: {self.name} (Admin: {self.admin.username})"
    
class RoomParticipant(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    join_time = models.DateTimeField(default=timezone.now)
    leave_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} in {self.room.name}"

class UserBalance(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    total_cash_balance = models.DecimalField(max_digits=15, decimal_places=2, default=100000.00)
    reserved_cash_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(default=timezone.now, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'room']
        indexes = [
            models.Index(fields=['user', 'room']),
        ]

    @property
    def available_cash_balance(self):
        """Available cash = Total cash - Reserved cash"""
        return self.total_cash_balance - self.reserved_cash_balance

    @property
    def cash_balance(self):
        """Backward compatibility - returns available cash"""
        return self.available_cash_balance

    def reserve_cash(self, amount):
        """Reserve cash for pending orders"""
        if self.available_cash_balance >= amount:
            self.reserved_cash_balance += amount
            self.save()
            return True
        return False

    def release_cash_reservation(self, amount):
        """Release reserved cash (order cancelled)"""
        self.reserved_cash_balance = max(0, self.reserved_cash_balance - amount)
        self.save()

    def execute_cash_reservation(self, amount):
        """Convert reserved cash to actual spend (order executed)"""
        if self.reserved_cash_balance >= amount:
            self.reserved_cash_balance -= amount
            self.total_cash_balance -= amount
            self.save()
            return True
        return False

    def add_cash(self, amount):
        """Add cash from selling stocks"""
        self.total_cash_balance += amount
        self.save()

    def __str__(self):
        return f"{self.user.username} balance in {self.room.name}: {self.total_cash_balance} (Available: {self.available_cash_balance})"

class Stock(models.Model):
    """Model for normal equity stocks"""
    symbol = models.CharField(max_length=20, db_index=True, unique=True)
    name_of_company = models.CharField(max_length=200)
    series = models.CharField(max_length=10)
    date_of_listing = models.DateField()
    paid_up_value = models.DecimalField(max_digits=15, decimal_places=2)
    isin_number = models.CharField(max_length=12, unique=True)
    face_value = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['isin_number']),
            models.Index(fields=['name_of_company']),
        ]

    def __str__(self):
        return f"{self.symbol} - {self.name_of_company}"

class SMEStock(models.Model):
    """Model for SME (Small and Medium Enterprise) based equity stocks"""
    symbol = models.CharField(max_length=20, db_index=True, unique=True)
    name_of_company = models.CharField(max_length=200)
    series = models.CharField(max_length=10)
    date_of_listing = models.DateField()
    paid_up_value = models.DecimalField(max_digits=15, decimal_places=2)
    isin_number = models.CharField(max_length=12, unique=True)
    face_value = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['isin_number']),
            models.Index(fields=['name_of_company']),
        ]

    def __str__(self):
        return f"{self.symbol} - {self.name_of_company} (SME)"

class OrderBook(models.Model):
    BUY = 'BUY'
    SELL = 'SELL'
    ORDER_TYPE_CHOICES = [(BUY, 'Buy'), (SELL, 'Sell')]
    
    PENDING = 'PENDING'
    EXECUTED = 'EXECUTED'
    CANCELLED = 'CANCELLED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    ORDER_STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (EXECUTED, 'Executed'),
        (CANCELLED, 'Cancelled'),
        (PARTIALLY_FILLED, 'Partially Filled'),
    ]

    MARKET = 'MARKET'
    LIMIT = 'LIMIT'
    STOP_LOSS = 'STOP_LOSS'
    ORDER_CATEGORY_CHOICES = [
        (MARKET, 'Market Order'),
        (LIMIT, 'Limit Order'),
        (STOP_LOSS, 'Stop Loss Order'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    order_type = models.CharField(max_length=4, choices=ORDER_TYPE_CHOICES)
    order_category = models.CharField(max_length=10, choices=ORDER_CATEGORY_CHOICES, default=MARKET)
    symbol = models.CharField(max_length=20)
    quantity = models.PositiveIntegerField()
    filled_quantity = models.PositiveIntegerField(default=0)
    order_price = models.DecimalField(max_digits=10, decimal_places=2)
    executed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    order_status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default=PENDING)
    order_timestamp = models.DateTimeField(default=timezone.now)
    execution_timestamp = models.DateTimeField(null=True, blank=True)
    has_stop_loss = models.BooleanField(default=False)
    stop_loss_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parent_order_id = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    cancellation_timestamp = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'room']),
            models.Index(fields=['symbol', 'room']),
            models.Index(fields=['order_status']),
            models.Index(fields=['order_timestamp']),
        ]

    @property
    def remaining_quantity(self):
        return self.quantity - self.filled_quantity

    @property
    def is_fully_filled(self):
        return self.filled_quantity >= self.quantity

    @property
    def total_order_value(self):
        return self.quantity * self.order_price

    @property
    def executed_value(self):
        if self.executed_price and self.filled_quantity:
            return self.filled_quantity * self.executed_price
        return Decimal('0.00')

    def __str__(self):
        return f"Order {self.id}: {self.order_type} {self.quantity} {self.symbol} @ {self.order_price} - {self.order_status}"

class UserPortfolio(models.Model):
    """Track user's stock holdings per room"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    symbol = models.CharField(max_length=20)
    stock_name = models.CharField(max_length=200, blank=True)
    total_quantity = models.IntegerField(default=0)
    reserved_quantity = models.IntegerField(default=0)
    average_buy_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_buy_value = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    total_sell_value = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    realized_pnl = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'room', 'symbol']
        indexes = [
            models.Index(fields=['user', 'room']),
            models.Index(fields=['symbol']),
        ]

    @property
    def available_quantity(self):
        """Available quantity = Total quantity - Reserved quantity"""
        return max(0, self.total_quantity - self.reserved_quantity)

    def reserve_quantity(self, quantity):
        """Reserve stocks for pending sell orders"""
        if self.available_quantity >= quantity:
            self.reserved_quantity += quantity
            self.save()
            return True
        return False

    def release_quantity_reservation(self, quantity):
        """Release reserved stocks (order cancelled)"""
        self.reserved_quantity = max(0, self.reserved_quantity - quantity)
        self.save()

    def add_buy_transaction(self, quantity, price):
        """Add buy transaction and update portfolio"""
        total_cost = quantity * price
        
        # Update average buy price
        if self.total_quantity > 0:
            total_value = (self.total_quantity * self.average_buy_price) + total_cost
            self.total_quantity += quantity
            self.average_buy_price = total_value / self.total_quantity
        else:
            self.total_quantity = quantity
            self.average_buy_price = price
        
        self.total_buy_value += total_cost
        self.save()

    def add_sell_transaction(self, quantity, price):
        """Add sell transaction and update portfolio"""
        if quantity <= self.available_quantity:
            sale_value = quantity * price
            
            # Calculate realized P&L for sold quantity
            cost_basis = quantity * self.average_buy_price
            realized_pnl_for_sale = sale_value - cost_basis
            
            # Update portfolio
            self.total_quantity -= quantity
            self.reserved_quantity = max(0, self.reserved_quantity - quantity)
            self.total_sell_value += sale_value
            self.realized_pnl += realized_pnl_for_sale
            
            self.save()
            return True
        return False
    
    def add_short_sell_transaction(self, quantity, price):
        sale_value = quantity * price

        cost_basis = quantity*self.average_buy_price
        realized_pnl_for_sale = sale_value - cost_basis

        self.total_sell_value += sale_value
        self.realized_pnl += realized_pnl_for_sale

        self.save()

    def calculate_unrealized_pnl(self, current_price):
        """Calculate unrealized P&L based on current market price"""
        if self.total_quantity > 0 and current_price:
            current_market_value = self.total_quantity * current_price
            cost_basis = self.total_quantity * self.average_buy_price
            return current_market_value - cost_basis
        return Decimal('0.00')

    def __str__(self):
        return f"{self.user.username} - {self.symbol} in {self.room.name}: {self.total_quantity} shares @ {self.average_buy_price}"

class Trade(models.Model):
    BUY = 'BUY'
    SELL = 'SELL'
    TRADE_TYPE_CHOICES = [(BUY, 'Buy'), (SELL, 'Sell')]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    order = models.ForeignKey(OrderBook, on_delete=models.CASCADE, related_name='executions', null=True, blank=True)
    trade_type = models.CharField(max_length=4, choices=TRADE_TYPE_CHOICES)
    symbol = models.CharField(max_length=20)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    total_value = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)
    
    # Additional fields for better tracking
    execution_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    market_price_at_execution = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fees = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'room']),
            models.Index(fields=['symbol', 'room']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['execution_id']),
        ]

    @property
    def net_value(self):
        """Net value after fees"""
        return self.total_value - self.fees

    def save(self, *args, **kwargs):
        if not self.execution_id:
            import uuid
            self.execution_id = str(uuid.uuid4())[:12].upper()
        
        self.total_value = self.quantity * self.price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Trade {self.execution_id}: {self.trade_type} {self.quantity} {self.symbol} @ {self.price} by {self.user.username}"

class MarketData(models.Model):
    """Cache for real-time market data"""
    symbol = models.CharField(max_length=20, db_index=True)
    ltp = models.DecimalField(max_digits=10, decimal_places=2)  # Last Traded Price
    open_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    high_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    low_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    close_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    volume = models.BigIntegerField(default=0)
    change_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    last_updated = models.DateTimeField(default=timezone.now)
    
    class Meta:
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['last_updated']),
        ]

    @property
    def is_stale(self):
        """Check if data is older than 5 minutes"""
        from datetime import timedelta
        return timezone.now() - self.last_updated > timedelta(minutes=5)

    def __str__(self):
        return f"{self.symbol}: ₹{self.ltp} ({self.change_percent:+.2f}%)"

class TradingSession(models.Model):
    """Track individual user trading sessions within a room"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    session_start = models.DateTimeField(default=timezone.now)
    session_end = models.DateTimeField(null=True, blank=True)
    starting_balance = models.DecimalField(max_digits=15, decimal_places=2)
    ending_balance = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    total_trades = models.IntegerField(default=0)
    total_buy_value = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    total_sell_value = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    realized_pnl = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'room']),
            models.Index(fields=['session_start']),
        ]

    @property
    def session_duration(self):
        if self.session_end:
            return self.session_end - self.session_start
        return timezone.now() - self.session_start

    @property
    def net_pnl(self):
        if self.ending_balance and self.starting_balance:
            return self.ending_balance - self.starting_balance
        return Decimal('0.00')

    def __str__(self):
        return f"{self.user.username} session in {self.room.name} - {self.session_start.date()}"
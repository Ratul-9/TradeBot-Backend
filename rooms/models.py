from django.db import models
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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
    cash_balance = models.DecimalField(max_digits=15, decimal_places=2, default=100000.00)

    def __str__(self):
        return f"{self.user.username} balance in {self.room.name}: {self.cash_balance}"

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

class Trade(models.Model):
    BUY = 'BUY'
    SELL = 'SELL'
    TRADE_TYPE_CHOICES = [(BUY, 'Buy'), (SELL, 'Sell')]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    trade_type = models.CharField(max_length=4, choices=TRADE_TYPE_CHOICES)
    symbol = models.CharField(max_length=10)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.trade_type} {self.quantity} {self.symbol} @ {self.price} by {self.user.username}"
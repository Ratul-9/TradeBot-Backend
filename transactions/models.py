from django.db import models
from django.conf import settings

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)  
    symbol = models.CharField(max_length=10)  
    quantity = models.PositiveIntegerField()
    price_per_stock = models.DecimalField(max_digits=10, decimal_places=2)  
    total_price = models.DecimalField(max_digits=15, decimal_places=2)  
    transaction_type = models.CharField(max_length=4, choices=TRANSACTION_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.transaction_type} {self.quantity} {self.symbol}"


class PendingOrder(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("EXECUTED", "Executed"),
        ("CANCELLED", "Cancelled"),
    ]

    ORDER_TYPES = [
        ("BUY", "Buy"),
        ("SELL", "Sell"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    symbol = models.CharField(max_length=10)
    quantity = models.PositiveIntegerField()
    target_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  
    stop_loss_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # Added stop-loss feature
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    order_type = models.CharField(max_length=4, choices=ORDER_TYPES, default="BUY")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        order_info = f"{self.quantity} {self.symbol} at ₹{self.target_price}" if self.order_type == "BUY" else f"Sell {self.quantity} {self.symbol} if price drops to ₹{self.stop_loss_price}"
        return f"Pending Order: {self.user.username} - {order_info}"


class Portfolio(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    symbol = models.CharField(max_length=10)
    quantity = models.PositiveBigIntegerField(default=0)
    average_price = models.DecimalField(max_digits=10, decimal_places=2, default=0);

    class Meta:
        unique_together = ("user", "symbol")

    def __str__(self):
        return f"{self.user.username} owns {self.quantity} of {self.symbol}"

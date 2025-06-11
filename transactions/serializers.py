from rest_framework import serializers
from .models import Transaction, Portfolio, PendingOrder

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ["id", "user", "symbol", "quantity", "price_per_stock", "total_price", "transaction_type", "created_at"]
        read_only_fields = ["id", "total_price", "created_at"]

class PendingOrderSerializer(serializers.ModelSerializer):
    total_price = serializers.SerializerMethodField()

    class Meta:
        model = PendingOrder
        fields = ["id", "user", "symbol", "quantity", "target_price", "stop_loss_price", "total_price", "status", "order_type", "created_at"]
        read_only_fields = ["id", "total_price", "status", "created_at"]

    def get_total_price(self, obj):
        if obj.order_type == "BUY" and obj.target_price:
            return obj.quantity * obj.target_price
        elif obj.order_type == "SELL" and obj.stop_loss_price:
            return obj.quantity * obj.stop_loss_price
        return None

class PortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Portfolio
        fields = ["id", "symbol", "quantity", "average_price"]

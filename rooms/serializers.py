from rest_framework import serializers
from .models import Room, RoomParticipant, UserBalance
from transactions.models import Transaction
from django.db.models import Sum, F, Case, When, DecimalField

class RoomSerializer(serializers.ModelSerializer):
    admin_username = serializers.CharField(source='admin.username', read_only=True)

    class Meta:
        model = Room
        fields = ['id', 'name', 'password', 'admin_username', 'start_time', 'end_time']
        extra_kwargs = {
            'password': {'write_only': True}  # don't show password when reading
        }

class JoinRoomSerializer(serializers.Serializer):
    room_id = serializers.IntegerField()
    password = serializers.CharField(required=False, allow_blank=True)

class LeaveRoomSerializer(serializers.Serializer):
    room_id = serializers.IntegerField()


class ParticipantTradeSummarySerializer(serializers.Serializer):
    username = serializers.CharField()
    cash_balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_bought = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_sold = serializers.DecimalField(max_digits=15, decimal_places=2)
    profit_loss = serializers.DecimalField(max_digits=15, decimal_places=2)


class LiveRoomStatusSerializer(serializers.Serializer):
    room_name = serializers.CharField()
    participants = ParticipantTradeSummarySerializer(many=True)
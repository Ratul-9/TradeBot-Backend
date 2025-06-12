from django.contrib import admin
from .models import Room, RoomParticipant, UserBalance, Trade

admin.site.register(Room)
admin.site.register(RoomParticipant)
admin.site.register(UserBalance)
admin.site.register(Trade)

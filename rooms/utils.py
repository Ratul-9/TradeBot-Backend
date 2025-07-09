from .models import RoomParticipant
from django.utils import timezone

def check_and_close_room(room):
    now = timezone.now()

    if not room.is_closed and room.end_time and now > room.end_time:
        room.is_closed = True
        room.save()

        RoomParticipant.objects.filter(room=room).exclude(user=room.admin).update(
            is_active=False,
            leave_time=timezone.now()
        )

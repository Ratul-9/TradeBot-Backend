from django.utils import timezone
from .models import RoomParticipant

def check_and_close_room(room):
    now = timezone.now()
    if not room.is_closed and room.end_time and now > room.end_time:
        room.is_closed = True
        room.save()

        
        participants = RoomParticipant.objects.filter(room=room, is_active=True).exclude(user=room.admin)
        for participant in participants:
            participant.is_active = False
            participant.leave_time = now
            participant.save()

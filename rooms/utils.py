

from django.utils import timezone

def check_and_close_room(room):
    if not room.is_closed and room.end_time and timezone.now() > room.end_time:
        room.is_closed = True
        room.save()

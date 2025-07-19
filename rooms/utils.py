from django.utils import timezone
from .models import RoomParticipant
def check_and_close_room(room):
    now = timezone.now()
    
    print(f"=== check_and_close_room Debug ===")
    print(f"Room {room.id}: {room.name}")
    print(f"Current time: {now}")
    print(f"Room end_time: {room.end_time}")
    print(f"is_closed before check: {room.is_closed}")
    
    if room.end_time:
        time_diff = room.end_time - now
        print(f"Time difference: {time_diff}")
        print(f"Time difference in seconds: {time_diff.total_seconds()}")
        print(f"Is now > end_time? {now > room.end_time}")
    else:
        print("No end_time set for room")

    if not room.is_closed and room.end_time and now > room.end_time:
        print("CLOSING ROOM - time has passed")
        room.is_closed = True
        room.save()

        # Remove all participants except admin
        participants_updated = RoomParticipant.objects.filter(room=room).exclude(user=room.admin).update(
            is_active=False,
            leave_time=timezone.now()
        )
        print(f"Updated {participants_updated} participants to inactive")
    else:
        print("NOT closing room")
        if room.is_closed:
            print("  - Room is already closed")
        elif not room.end_time:
            print("  - Room has no end_time")
        elif now <= room.end_time:
            print("  - Current time is before end_time")
    
    print(f"is_closed after check: {room.is_closed}")
    print("=== check_and_close_room End ===")
    print()
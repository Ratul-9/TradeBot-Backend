from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('id','username', 'email', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email')
    ordering = ('id',)

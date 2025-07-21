from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    USER_ROLES = (
        ('user', 'Regular User'),
        ('admin', 'Administrator'),
    )
    
    virtual_balance = models.DecimalField(max_digits=10, decimal_places=2, default=100000.00)
    role = models.CharField(max_length=10, choices=USER_ROLES, default='user')
    
    groups = models.ManyToManyField(
        "auth.Group",
        related_name="customuser_groups", 
        blank=True
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        related_name="customuser_permissions",  
        blank=True
    )

    def save(self, *args, **kwargs):
        if self.role == 'admin':
            self.is_staff = True
        else:
            self.is_staff = False
        super().save(*args, **kwargs)
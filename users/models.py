from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    virtual_balance = models.DecimalField(max_digits=10, decimal_places=2, default=100000.00)

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

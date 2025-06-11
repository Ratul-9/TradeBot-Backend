from rest_framework import serializers
from django.contrib.auth import get_user_model
from users.models import CustomUser

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'password', 'virtual_balance']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        """Create a new user with a hashed password and return it."""
        virtual_balance = validated_data.get('virtual_balance', 100000.00)
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],

        )
        user.virtual_balance = virtual_balance
        user.save()
        return user
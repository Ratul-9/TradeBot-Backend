from rest_framework import serializers
from django.contrib.auth import get_user_model
from users.models import CustomUser
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'password', 'virtual_balance']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        virtual_balance = validated_data.get('virtual_balance', 100000.00)

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            is_active=False  
        )
        user.virtual_balance = virtual_balance
        user.save()
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        verification_url = f"http://localhost:8000/verify-email/{uid}/{token}/"

        send_mail(
            subject="Verify your email",
            message=f"Hi {user.username}, click the link to verify your email:\n{verification_url}",
            from_email="no-reply@yourapp.com",
            recipient_list=[user.email],
            fail_silently=False,
        )

        return user
from rest_framework import serializers
from django.contrib.auth import get_user_model
from users.models import CustomUser
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.conf import settings

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=CustomUser.USER_ROLES, default='user')

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'password', 'confirm_password', 'virtual_balance', 'role']
        extra_kwargs = {
            'password': {'write_only': True},
            'virtual_balance': {'read_only': True}
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError("Passwords don't match.")
        return attrs

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def create(self, validated_data):
        # Remove confirm_password from validated_data
        validated_data.pop('confirm_password', None)
        
        virtual_balance = validated_data.get('virtual_balance', 100000.00)
        role = validated_data.get('role', 'user')

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            role=role,
            is_active=False  
        )
        user.virtual_balance = virtual_balance
        user.save()

        # Generate verification token and URL
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        
        # Use settings for domain or fallback to localhost
        domain = getattr(settings, 'FRONTEND_URL', 'http://localhost:8000')
        verification_url = f"{domain}/verify-email/{uid}/{token}/"

        # Send verification email
        try:
            send_mail(
                subject="Verify your email - Welcome!",
                message=f"Hi {user.username},\n\nThank you for registering! Please click the link below to verify your email address:\n\n{verification_url}\n\nIf you didn't create this account, please ignore this email.\n\nBest regards,\nThe Team",
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@yourapp.com'),
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception as e:
            # Log the error but don't fail registration
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to send verification email to {user.email}: {str(e)}")

        return user

class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile data"""
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'virtual_balance', 'role', 'is_staff', 'date_joined']
        read_only_fields = ['id', 'date_joined', 'is_staff']
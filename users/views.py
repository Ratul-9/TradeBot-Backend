from rest_framework import generics, permissions
from django.contrib.auth import get_user_model
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import UserSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from rest_framework import status
import logging

from users import serializers
logger = logging.getLogger(__name__)
User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        if not user:
            raise serializers.ValidationError("No User found. Please check credentials")
        

        if not user.is_active:
            raise serializers.ValidationError("Please verify your email before logging in.")

        data['username'] = user.username
        data['email'] = user.email
        data['virtual_balance'] = user.virtual_balance
        return data


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class RegisterUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

class GetUserProfile(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

class StaffLoginView(generics.CreateAPIView):
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        user = authenticate(username=username, password=password)

        if user is not None and user.is_staff:
            refresh = RefreshToken.for_user(user)
            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'username': user.username,
                'is_staff': user.is_staff,
            }, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)


class GetUserBalance(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({"username": user.username, "virtual_balance": user.virtual_balance, "isSuperUser": user.is_superuser})


from django.utils.http import urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator
from django.http import HttpResponse

class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, uidb64, token):
        try:
            # Decode the user ID
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
            
            # Log for debugging
            logger.info(f"Email verification attempt for user: {user.email}")
            
        except (TypeError, ValueError, OverflowError, User.DoesNotExist) as e:
            logger.error(f"Error decoding user ID or user not found: {str(e)}")
            return HttpResponse('<h2>Invalid verification link.</h2>', status=400)

        try:
            # Check if the token is valid
            if default_token_generator.check_token(user, token):
                # Check if user is already active
                if user.is_active:
                    logger.info(f"User {user.email} is already verified")
                    return HttpResponse('<h2>Email already verified! You may now log in.</h2>', status=200)
                
                # Activate the user
                user.is_active = True
                user.save()
                logger.info(f"User {user.email} successfully verified")
                return HttpResponse('<h2>Email successfully verified! You may now log in.</h2>', status=200)
            else:
                logger.warning(f"Invalid or expired token for user: {user.email}")
                return HttpResponse('<h2>Invalid or expired token.</h2>', status=400)
                
        except Exception as e:
            logger.error(f"Unexpected error during email verification: {str(e)}")
            return HttpResponse('<h2>An error occurred during verification. Please try again.</h2>', status=500)

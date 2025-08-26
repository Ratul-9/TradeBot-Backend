from rest_framework import generics, permissions, status
from django.contrib.auth import get_user_model, authenticate
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import UserSerializer, UserProfileSerializer
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator
from django.http import HttpResponse
import logging
from django.conf import settings
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
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

        # Add user data to token response
        data['user'] = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'virtual_balance': float(user.virtual_balance),
            'role': user.role,
            'is_staff': user.is_staff,
        }
        return data

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class RegisterUserView(generics.CreateAPIView):
    """
    Register a new user with role selection (user or admin)
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Generate verification token and send email
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            
            # Get domain from environment variable or use default AWS IP
            domain = 'http://13.127.108.237'
            verification_url = f"{domain}/verify-email/{uid}/{token}/"
            
            try:
                # Send verification email
                from_email = 'EMAIL_HOST_USER'
                send_mail(
                    subject="Verify your email",
                    message=f"Hi {user.username},\n\nPlease click the following link to verify your email:\n\n{verification_url}\n\nBest regards,\nThe Team",
                    from_email=from_email,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                logger.info(f"Verification email sent to {user.email} with URL: {verification_url}")
            except Exception as e:
                logger.error(f"Failed to send verification email to {user.email}: {str(e)}")
                # Still return success but mention email issue
                return Response({
                    'message': 'Registration successful! There was an issue sending the verification email. Please use the resend option.',
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'role': user.role
                    }
                }, status=status.HTTP_201_CREATED)
            
            return Response({
                'message': 'Registration successful! Please check your email to verify your account.',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': user.role
                }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class GetUserProfile(generics.RetrieveUpdateAPIView):
    """
    Get or update user profile
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

class StaffLoginView(APIView):
    """
    Special login endpoint for staff/admin users
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return Response({
                'error': 'Username and password are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=username, password=password)

        if user is not None:
            if not user.is_active:
                return Response({
                    'error': 'Please verify your email before logging in.'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            if user.is_staff or user.role == 'admin':
                refresh = RefreshToken.for_user(user)
                return Response({
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'role': user.role,
                        'is_staff': user.is_staff,
                        'virtual_balance': float(user.virtual_balance)
                    }
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'error': 'Access denied. Staff privileges required.'
                }, status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)

class GetUserBalance(APIView):
    """
    Get current user's balance and basic info
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "virtual_balance": float(user.virtual_balance),
            "role": user.role,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser
        })

from django.shortcuts import redirect
class VerifyEmailView(APIView):
    """
    Email verification endpoint
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, uidb64, token):
        try:
            # Decode the user ID
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
            
            logger.info(f"Email verification attempt for user: {user.email}")
            
        except (TypeError, ValueError, OverflowError, User.DoesNotExist) as e:
            logger.error(f"Error decoding user ID or user not found: {str(e)}")
            return HttpResponse(
                '<div style="text-align: center; font-family: Arial, sans-serif; margin-top: 50px;">'
                '<h2 style="color: #dc3545;">Invalid verification link</h2>'
                '<p>The verification link is invalid or corrupted.</p>'
                '</div>', 
                status=400
            )

        try:
            # Check if the token is valid
            if default_token_generator.check_token(user, token):
                # Check if user is already active
                if user.is_active:
                    logger.info(f"User {user.email} is already verified")
                    return HttpResponse(
                        '<div style="text-align: center; font-family: Arial, sans-serif; margin-top: 50px;">'
                        '<h2 style="color: #28a745;">Email already verified!</h2>'
                        '<p>Your account is already active. You may now log in.</p>'
                        '</div>', 
                        status=200
                    )
                
                # Activate the user
                user.is_active = True
                user.save()
                logger.info(f"User {user.email} successfully verified")
                
                return redirect("http://65.1.132.156/")
            else:
                logger.warning(f"Invalid or expired token for user: {user.email}")
                return HttpResponse(
                    '<div style="text-align: center; font-family: Arial, sans-serif; margin-top: 50px;">'
                    '<h2 style="color: #dc3545;">Invalid or expired token</h2>'
                    '<p>The verification link has expired or is invalid. Please request a new verification email.</p>'
                    '</div>', 
                    status=400
                )
                
        except Exception as e:
            logger.error(f"Unexpected error during email verification: {str(e)}")
            return HttpResponse(
                '<div style="text-align: center; font-family: Arial, sans-serif; margin-top: 50px;">'
                '<h2 style="color: #dc3545;">Verification Error</h2>'
                '<p>An error occurred during verification. Please try again or contact support.</p>'
                '</div>', 
                status=500
            )

class ResendVerificationEmailView(APIView):
    """
    Resend verification email for inactive users
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            return Response({
                'error': 'Email is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
            
            if user.is_active:
                return Response({
                    'message': 'Account is already verified'
                }, status=status.HTTP_200_OK)

            # Generate new verification token
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            
            # Get domain from environment variable or use default AWS IP
            domain = 'http://13.127.108.237'
            verification_url = f"{domain}/verify-email/{uid}/{token}/"

            # Send verification email
            from_email = ('EMAIL_HOST_USER', 'no-reply@yourapp.com')
            send_mail(
                subject="Verify your email - Resent",
                message=f"Hi {user.username},\n\nHere's your new verification link:\n\n{verification_url}\n\nBest regards,\nThe Team",
                from_email=from_email,
                recipient_list=[user.email],
                fail_silently=False,
            )
            
            logger.info(f"Resent verification email to {user.email} with URL: {verification_url}")

            return Response({
                'message': 'Verification email sent successfully'
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({
                'error': 'No account found with this email address'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error resending verification email: {str(e)}")
            return Response({
                'error': 'Failed to send verification email'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

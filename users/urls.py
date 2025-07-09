from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import CustomTokenObtainPairView, RegisterUserView, GetUserProfile, GetUserBalance, StaffLoginView, VerifyEmailView


urlpatterns = [
    path('register/', RegisterUserView.as_view(), name='register'),
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('profile/', GetUserProfile.as_view(), name='profile'),
    path('user/balance/', GetUserBalance.as_view(), name='user_balance'),
    path('admin-login/', StaffLoginView.as_view(), name='admin-login'),
]

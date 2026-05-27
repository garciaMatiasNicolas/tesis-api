from django.urls import path, include
from users.views import UserModelViewSet, EmployeeViewSet, SupplierViewSet, EmailExistsAPIView, VerifyIsClientAPIView
from rest_framework.routers import DefaultRouter
from users.authentication import LoginView, VerifyOTPView, Enable2FAView
from users.recovery import (
    RecoveryRequestView,
    FullRecoveryConfirmView,
    PasswordRecoveryConfirmView,
    TwoFARecoveryConfirmView,
    ClientRecoveryRequestView,
    ClientRecoveryConfirmView,
)


router = DefaultRouter()
router.register(r'users', UserModelViewSet, basename='user')
router.register(r'employees', EmployeeViewSet, basename='employee')
router.register(r'suppliers', SupplierViewSet, basename='supplier')

urlpatterns = [
    path('check-email/', EmailExistsAPIView.as_view(), name='check-email'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('auth/enable-2fa/', Enable2FAView.as_view(), name='enable-2fa'),
    path('auth/verify-client/', VerifyIsClientAPIView.as_view(), name='verify-client'),
    # Recovery endpoints
    path('auth/recovery/request/', RecoveryRequestView.as_view(), name='recovery-request'),
    path('auth/recovery/full/', FullRecoveryConfirmView.as_view(), name='recovery-full'),
    path('auth/recovery/password/', PasswordRecoveryConfirmView.as_view(), name='recovery-password'),
    path('auth/recovery/2fa/', TwoFARecoveryConfirmView.as_view(), name='recovery-2fa'),
    path('auth/recovery/client/request/', ClientRecoveryRequestView.as_view(), name='recovery-client-request'),
    path('auth/recovery/client/confirm/', ClientRecoveryConfirmView.as_view(), name='recovery-client-confirm'),
    path('', include(router.urls)),
]
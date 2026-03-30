from django.urls import path, include
from users.views import UserModelViewSet, EmployeeViewSet, SupplierViewSet, EmailExistsAPIView, VerifyIsClientAPIView
from rest_framework.routers import DefaultRouter
from users.authentication import LoginView, VerifyOTPView, Enable2FAView


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
    path('', include(router.urls)),
] 
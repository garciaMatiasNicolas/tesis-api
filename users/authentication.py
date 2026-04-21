import pyotp
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from core.crm.models import Customer
import qrcode
from io import BytesIO
import base64
from django.contrib.auth import get_user_model
User = get_user_model()


class Enable2FAView(APIView):
    def get_permissions(self):
        email = self.request.data.get('email', None)
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "user_not_found"}, status=404)
        
        if user.first_login:
            return [AllowAny()]
        
        else:
            return [IsAuthenticated()]

    def post(self, request):
        otp = request.data.get("otp")
        email = request.data.get('email', None)
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "user_not_found"}, status=404)

        if user.is_2fa_enabled:
            return Response({"error": "2fa_enabled"}, status=400)

        if user.verify_otp(otp):
            user.first_login = False
            user.is_2fa_enabled = True
            user.save()
            return Response({"message": "2fa_enabled_success"}, status=200)

        return Response({"error": "token_invalid"}, status=400)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        ecommerce = request.data.get('ecommerce', False)
        user = authenticate(email=email, password=password)
        print(user)
        if user:
            user = User.objects.get(email=email)  # Obtener el usuario completo para acceder a sus campos
            is_customer = user.role == 'client' and Customer.objects.filter(user=user).exists()

            # Si es un cliente haciendo login en ecommerce, no requiere 2FA
            if is_customer and ecommerce:
                refresh = RefreshToken.for_user(user)
                return Response({
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user_id": user.id,
                    "user_name": f'{user.first_name} {user.last_name}',
                }, status=200)
            
            # Si es un cliente pero NO está en ecommerce, no permitir acceso al panel admin
            if is_customer and not ecommerce:
                return Response({"error": "not_authorized"}, status=403)

            if user.is_2fa_enabled:
                return Response({
                    "message": "2fa_required", 
                    "user_name": f'{user.first_name} {user.last_name}', 
                    "user_email": user.email,
                    "user_role": user.role,
                }, status=200)

            else:
                uri = user.get_totp_uri()
                img = qrcode.make(uri)
                buf = BytesIO()
                img.save(buf)
                img_base64 = base64.b64encode(buf.getvalue()).decode()

                return Response({
                    "message": "2fa_not_enabled", 
                    "user_name": f'{user.first_name} {user.last_name}', 
                    "user_email": user.email,
                    "user_role": user.role,
                    "otp_uri": uri,
                    "qr_code": f"data:image/png;base64,{img_base64}"
                }, status=200)

        return Response({"error": "credentials_invalid"}, status=401)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        otp = request.data.get("otp")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "user_not_found"}, status=404)

        if user.role == 'client':
            is_customer = Customer.objects.filter(user=user).exists()
            if not is_customer:
                return Response({"error": "not_authorized"}, status=403)

        if not user.is_2fa_enabled and not user.first_login:
            return Response({"error": "2fa_not_enabled"}, status=403)

        if user.verify_otp(otp):
            refresh = RefreshToken.for_user(user)
            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            })
        
        return Response({"error": "otp_invalid"}, status=400)



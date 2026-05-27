import pyotp
import qrcode
from io import BytesIO
import base64

from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth import get_user_model

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .models import PasswordRecoveryToken

User = get_user_model()

TOKEN_EXPIRY_HOURS = 1

_STORE_THEMES = {
    'wine':   {'primary_main': '#9a334d', 'primary_dark': '#7a2639', 'primary_gradient': 'linear-gradient(135deg, #9a334d 0%, #7a2639 100%)'},
    'coral':  {'primary_main': '#ff7256', 'primary_dark': '#e05a44', 'primary_gradient': 'linear-gradient(135deg, #ff7256 0%, #e05a44 100%)'},
    'mint':   {'primary_main': '#00bfa5', 'primary_dark': '#009688', 'primary_gradient': 'linear-gradient(135deg, #00bfa5 0%, #009688 100%)'},
    'nordic': {'primary_main': '#4a6fa5', 'primary_dark': '#3b5683', 'primary_gradient': 'linear-gradient(135deg, #4a6fa5 0%, #3b5683 100%)'},
    'ocean':  {'primary_main': '#3498db', 'primary_dark': '#2980b9', 'primary_gradient': 'linear-gradient(135deg, #3498db 0%, #2980b9 100%)'},
    'purple': {'primary_main': '#9c27b0', 'primary_dark': '#7b1fa2', 'primary_gradient': 'linear-gradient(135deg, #9c27b0 0%, #7b1fa2 100%)'},
}
_DEFAULT_THEME = _STORE_THEMES['wine']

_RECOVERY_SUBJECTS = {
    'full_recovery': 'Recupero de contraseña y dispositivo 2FA — Casta 1994 ERP',
    'password_only': 'Recupero de contraseña — Casta 1994 ERP',
    '2fa_only': 'Revinculación de dispositivo 2FA — Casta 1994 ERP',
    'client_recovery': 'Recupero de contraseña — Tienda Casta 1994',
}

_RECOVERY_TEMPLATES = {
    'full_recovery': 'full_recovery.html',
    'password_only': 'password_only.html',
    '2fa_only': '2fa_only.html',
    'client_recovery': 'client_recovery.html',
}

_STAFF_RECOVERY_TYPES = ('full_recovery', 'password_only', '2fa_only')


def _invalidate_existing_tokens(user, recovery_type):
    PasswordRecoveryToken.objects.filter(
        user=user, recovery_type=recovery_type, used=False
    ).update(used=True)


def _create_recovery_token(user, recovery_type):
    _invalidate_existing_tokens(user, recovery_type)
    return PasswordRecoveryToken.objects.create(user=user, recovery_type=recovery_type)


def _send_recovery_email(user, token, recovery_type, extra_context=None):
    context = {
        'user_name': user.first_name,
        'token': token,
        'expiry_hours': TOKEN_EXPIRY_HOURS,
    }
    if extra_context:
        context.update(extra_context)

    html_content = render_to_string(_RECOVERY_TEMPLATES[recovery_type], context)

    plain_text = (
        f"Hola {user.first_name},\n\n"
        f"Tu token de recuperación es:\n\n  {token}\n\n"
        f"Expira en {TOKEN_EXPIRY_HOURS} hora(s).\n\n"
        "Si no realizaste esta solicitud, ignorá este correo."
    )

    email = EmailMultiAlternatives(
        subject=_RECOVERY_SUBJECTS[recovery_type],
        body=plain_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)


def _build_qr_response(user, message_key):
    uri = user.get_totp_uri()
    img = qrcode.make(uri)
    buf = BytesIO()
    img.save(buf)
    img_base64 = base64.b64encode(buf.getvalue()).decode()
    return {
        "message": message_key,
        "otp_uri": uri,
        "qr_code": f"data:image/png;base64,{img_base64}",
        "user_email": user.email,
    }


def _get_valid_token(token_str, recovery_type):
    try:
        recovery_token = PasswordRecoveryToken.objects.get(
            token=token_str,
            recovery_type=recovery_type,
            used=False,
        )
    except PasswordRecoveryToken.DoesNotExist:
        return None, "invalid_token"

    if timezone.now() > recovery_token.expires_at:
        return None, "token_expired"

    return recovery_token, None


class RecoveryRequestView(APIView):
    """
    Inicia cualquiera de los 3 flujos de recuperación enviando un email con token.

    Body: { "email": "...", "recovery_type": "full_recovery" | "password_only" | "2fa_only" }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        recovery_type = request.data.get('recovery_type')

        if recovery_type not in _STAFF_RECOVERY_TYPES:
            return Response({"error": "invalid_recovery_type"}, status=400)

        if not email:
            return Response({"error": "email_required"}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "recovery_email_sent"}, status=200)

        if user.role == 'client':
            return Response({"error": "client_use_store_recovery"}, status=403)

        recovery_token = _create_recovery_token(user, recovery_type)

        try:
            _send_recovery_email(user, recovery_token.token, recovery_type)
        except Exception:
            return Response({"error": "email_send_failed"}, status=500)

        return Response({"message": "recovery_email_sent"}, status=200)


class FullRecoveryConfirmView(APIView):
    """
    Caso 1: Usuario olvidó contraseña Y no tiene acceso al dispositivo 2FA.
    Confirma con token de email → resetea contraseña y 2FA.
    El usuario deberá re-vincular su dispositivo 2FA al iniciar sesión.

    Body: { "token": "...", "new_password": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token_str = request.data.get('token')
        new_password = request.data.get('new_password')

        if not token_str or not new_password:
            return Response({"error": "token_and_password_required"}, status=400)

        recovery_token, error = _get_valid_token(token_str, 'full_recovery')
        if error:
            return Response({"error": error}, status=400)

        user = recovery_token.user
        user.set_password(new_password)
        user.is_2fa_enabled = False
        user.first_login = True
        user.otp_secret = pyotp.random_base32()
        user.save()

        recovery_token.used = True
        recovery_token.save()

        return Response(_build_qr_response(user, "password_reset_2fa_reset"), status=200)


class PasswordRecoveryConfirmView(APIView):
    """
    Caso 2: Usuario olvidó contraseña pero SÍ tiene acceso al dispositivo 2FA.
    Confirma con token de email + código OTP → resetea contraseña únicamente.

    Body: { "token": "...", "otp": "...", "new_password": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token_str = request.data.get('token')
        otp = request.data.get('otp')
        new_password = request.data.get('new_password')

        if not token_str or not otp or not new_password:
            return Response({"error": "token_otp_and_password_required"}, status=400)

        recovery_token, error = _get_valid_token(token_str, 'password_only')
        if error:
            return Response({"error": error}, status=400)

        user = recovery_token.user

        if not user.verify_otp(otp):
            return Response({"error": "otp_invalid"}, status=400)

        user.set_password(new_password)
        user.save()

        recovery_token.used = True
        recovery_token.save()

        return Response({"message": "password_reset_success"}, status=200)


class TwoFARecoveryConfirmView(APIView):
    """
    Caso 3: Usuario NO olvidó su contraseña pero perdió acceso al dispositivo 2FA.
    Confirma con token de email + contraseña actual → resetea 2FA únicamente.
    El usuario deberá re-vincular su dispositivo 2FA al iniciar sesión.

    Body: { "token": "...", "password": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token_str = request.data.get('token')
        password = request.data.get('password')

        if not token_str or not password:
            return Response({"error": "token_and_password_required"}, status=400)

        recovery_token, error = _get_valid_token(token_str, '2fa_only')
        if error:
            return Response({"error": error}, status=400)

        user = recovery_token.user

        if not user.check_password(password):
            return Response({"error": "password_invalid"}, status=400)

        user.is_2fa_enabled = False
        user.first_login = True
        user.otp_secret = pyotp.random_base32()
        user.save()

        recovery_token.used = True
        recovery_token.save()

        return Response(_build_qr_response(user, "2fa_reset_success"), status=200)


class ClientRecoveryRequestView(APIView):
    """
    Recupero de contraseña para clientes (ecommerce). Sin 2FA.

    Body: { "email": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from core.store.models import Store

        email = request.data.get('email')
        if not email:
            return Response({"error": "email_required"}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "recovery_email_sent"}, status=200)

        if user.role != 'client':
            return Response({"error": "not_a_client"}, status=403)

        recovery_token = _create_recovery_token(user, 'client_recovery')

        store = Store.objects.first()
        theme_id = store.theme_id if store else 'wine'
        store_name = store.name if store else 'Arkhos Store'
        theme_colors = _STORE_THEMES.get(theme_id, _DEFAULT_THEME)

        extra_context = {
            'store_name': store_name,
            **theme_colors,
        }

        try:
            _send_recovery_email(user, recovery_token.token, 'client_recovery', extra_context)
        except Exception:
            return Response({"error": "email_send_failed"}, status=500)

        return Response({"message": "recovery_email_sent"}, status=200)


class ClientRecoveryConfirmView(APIView):
    """
    Confirma el recupero de contraseña de un cliente.

    Body: { "token": "...", "new_password": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token_str = request.data.get('token')
        new_password = request.data.get('new_password')

        if not token_str or not new_password:
            return Response({"error": "token_and_password_required"}, status=400)

        recovery_token, error = _get_valid_token(token_str, 'client_recovery')
        if error:
            return Response({"error": error}, status=400)

        user = recovery_token.user

        if user.role != 'client':
            return Response({"error": "not_a_client"}, status=403)

        user.set_password(new_password)
        user.save()

        recovery_token.used = True
        recovery_token.save()

        return Response({"message": "password_reset_success"}, status=200)

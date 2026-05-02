from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import (
    access_token_expires_in_seconds,
    create_access_token,
    create_refresh_token,
    hash_secret,
    new_id,
    utc_now,
)
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.redis import get_redis_client
from app.models import RefreshSession, SmsVerificationEvent, User, UserProfile
from app.sms.provider import SmsProvider, get_sms_provider


@dataclass(frozen=True)
class NormalizedPhone:
    e164: str
    national_number: str
    country_code: str


def normalize_phone_number(phone_number: str, default_country_code: str = "86") -> NormalizedPhone:
    value = phone_number.strip().replace(" ", "").replace("-", "")
    if value.startswith("+"):
        if not value.startswith(f"+{default_country_code}"):
            raise AppError("VALIDATION_ERROR", "暂只支持中国大陆手机号", status_code=422)
        national_number = value[len(default_country_code) + 1 :]
        return NormalizedPhone(value, national_number, default_country_code)

    if value.isdigit() and len(value) == 11:
        return NormalizedPhone(f"+{default_country_code}{value}", value, default_country_code)

    raise AppError("VALIDATION_ERROR", "手机号格式不正确", status_code=422)


class AuthService:
    def __init__(
        self,
        db: Session,
        redis_client: Redis,
        sms_provider: SmsProvider,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.redis = redis_client
        self.sms_provider = sms_provider
        self.settings = settings or get_settings()

    def send_sms(self, phone_number: str, purpose: str, request: Request) -> dict:
        if purpose != "login":
            raise AppError("VALIDATION_ERROR", "不支持的短信用途", status_code=422)

        phone = normalize_phone_number(phone_number, self.settings.sms_country_code)
        phone_hash = hash_secret(phone.e164, self.settings)
        cooldown_key = f"sms:cooldown:{purpose}:{phone_hash}"
        if self.redis.get(cooldown_key):
            raise AppError("AUTH_SMS_RATE_LIMITED", "短信发送过于频繁", status_code=429)

        result = self.sms_provider.send_code(phone.national_number, phone.country_code)
        self._record_sms_event(
            phone_hash=phone_hash,
            country_code=phone.country_code,
            purpose=purpose,
            event_type="send",
            success=result.success,
            result_code=result.result_code,
            provider_request_id=result.provider_request_id,
            request=request,
        )
        self.db.commit()

        if not result.success:
            raise AppError(
                "INTERNAL_ERROR",
                "短信发送失败",
                status_code=502,
                details={"provider_code": result.result_code},
            )

        self.redis.setex(cooldown_key, self.settings.sms_send_cooldown_seconds, "1")
        return {
            "cooldown_seconds": self.settings.sms_send_cooldown_seconds,
            "expires_in_seconds": self.settings.sms_expires_in_seconds,
        }

    def verify_sms(self, phone_number: str, code: str, request: Request) -> dict:
        phone = normalize_phone_number(phone_number, self.settings.sms_country_code)
        phone_hash = hash_secret(phone.e164, self.settings)
        lock_key = f"sms:lock:login:{phone_hash}"
        if self.redis.get(lock_key):
            raise AppError(
                "AUTH_SMS_RATE_LIMITED",
                "验证码错误次数过多，请稍后再试",
                status_code=429,
            )

        result = self.sms_provider.check_code(phone.national_number, phone.country_code, code)
        self._record_sms_event(
            phone_hash=phone_hash,
            country_code=phone.country_code,
            purpose="login",
            event_type="check",
            success=result.success,
            result_code=result.result_code,
            provider_request_id=None,
            request=request,
        )

        if not result.success and result.result_code != "OK":
            self.db.commit()
            raise AppError(
                "INTERNAL_ERROR",
                "短信验证码校验失败",
                status_code=502,
                details={"provider_code": result.result_code},
            )

        if not result.success:
            self._track_failed_attempt(phone_hash)
            self.db.commit()
            raise AppError("AUTH_SMS_INVALID_CODE", "验证码不正确", status_code=401)

        self.redis.delete(f"sms:fail:login:{phone_hash}")
        user = self._get_or_create_user(phone.e164, phone.country_code)
        user.last_login_at = utc_now()
        user.phone_verified_at = user.phone_verified_at or utc_now()

        refresh_token = create_refresh_token()
        session = RefreshSession(
            id=new_id("sess"),
            user_id=user.id,
            refresh_token_hash=hash_secret(refresh_token, self.settings),
            expires_at=utc_now() + timedelta(days=self.settings.jwt_refresh_token_expire_days),
            created_ip_hash=self._ip_hash(request),
            user_agent=request.headers.get("user-agent"),
        )
        self.db.add(session)
        self.db.commit()

        return {
            "access_token": create_access_token(user.id, self.settings),
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in_seconds": access_token_expires_in_seconds(self.settings),
            "user": {
                "id": user.id,
                "phone_number": user.phone_number,
                "profile_completed": self._profile_completed(user.id),
            },
        }

    def refresh_access_token(self, refresh_token: str) -> dict:
        session = self._get_active_refresh_session(refresh_token)
        return {
            "access_token": create_access_token(session.user_id, self.settings),
            "expires_in_seconds": access_token_expires_in_seconds(self.settings),
        }

    def logout(self, refresh_token: str) -> dict:
        token_hash = hash_secret(refresh_token, self.settings)
        session = self.db.scalar(
            select(RefreshSession).where(RefreshSession.refresh_token_hash == token_hash)
        )
        if session and not session.revoked_at:
            session.revoked_at = utc_now()
            self.db.commit()
        return {"success": True}

    def _get_active_refresh_session(self, refresh_token: str) -> RefreshSession:
        token_hash = hash_secret(refresh_token, self.settings)
        session = self.db.scalar(
            select(RefreshSession).where(RefreshSession.refresh_token_hash == token_hash)
        )
        if not session or session.revoked_at or session.expires_at <= utc_now():
            raise AppError("AUTH_INVALID_TOKEN", "刷新登录态无效", status_code=401)
        return session

    def _get_or_create_user(self, phone_number: str, country_code: str) -> User:
        user = self.db.scalar(select(User).where(User.phone_number == phone_number))
        if user:
            return user

        user = User(
            id=new_id("user"),
            phone_number=phone_number,
            country_code=country_code,
            phone_verified_at=utc_now(),
            status="active",
        )
        self.db.add(user)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            user = self.db.scalar(select(User).where(User.phone_number == phone_number))
            if user:
                return user
            raise
        return user

    def _profile_completed(self, user_id: str) -> bool:
        profile = self.db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        return bool(profile and profile.completed_at)

    def _record_sms_event(
        self,
        phone_hash: str,
        country_code: str,
        purpose: str,
        event_type: str,
        success: bool,
        result_code: str,
        provider_request_id: str | None,
        request: Request,
    ) -> None:
        self.db.add(
            SmsVerificationEvent(
                id=new_id("sms_evt"),
                phone_number_hash=phone_hash,
                country_code=country_code,
                purpose=purpose,
                event_type=event_type,
                provider=self.sms_provider.provider_name,
                provider_request_id=provider_request_id,
                success=success,
                result_code=result_code,
                ip_hash=self._ip_hash(request),
                created_at=utc_now(),
            )
        )

    def _track_failed_attempt(self, phone_hash: str) -> None:
        fail_key = f"sms:fail:login:{phone_hash}"
        count = self.redis.incr(fail_key)
        self.redis.expire(fail_key, self.settings.sms_failed_lock_seconds)
        if count >= self.settings.sms_max_failed_attempts:
            lock_key = f"sms:lock:login:{phone_hash}"
            self.redis.setex(lock_key, self.settings.sms_failed_lock_seconds, "1")

    def _ip_hash(self, request: Request) -> str | None:
        if not request.client:
            return None
        return hash_secret(request.client.host, self.settings)


def get_auth_service(
    db: Annotated[Session, Depends(get_db)],
    redis_client: Annotated[Redis, Depends(get_redis_client)],
    sms_provider: Annotated[SmsProvider, Depends(get_sms_provider)],
) -> AuthService:
    return AuthService(db=db, redis_client=redis_client, sms_provider=sms_provider)

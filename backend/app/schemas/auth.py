from pydantic import BaseModel, Field


class SmsSendRequest(BaseModel):
    phone_number: str = Field(min_length=6, max_length=32)
    purpose: str = "login"


class SmsSendResponse(BaseModel):
    cooldown_seconds: int
    expires_in_seconds: int


class SmsVerifyRequest(BaseModel):
    phone_number: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=8)


class AuthUserResponse(BaseModel):
    id: str
    phone_number: str
    profile_completed: bool


class SmsVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: AuthUserResponse


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class RefreshResponse(BaseModel):
    access_token: str
    expires_in_seconds: int


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class LogoutResponse(BaseModel):
    success: bool

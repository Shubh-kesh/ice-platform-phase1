from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class GoogleAuthorizeResponse(BaseModel):
    authorize_url: str
    state: str
    code_verifier: str
    nonce: str


class GoogleCallbackRequest(BaseModel):
    code: str
    code_verifier: str
    state: str

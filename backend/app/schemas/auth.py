from pydantic import BaseModel, ConfigDict, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    role: str
    status: str

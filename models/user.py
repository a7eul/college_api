from pydantic import BaseModel
from typing import Optional

class User(BaseModel):
    id: int
    login: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    group_id: Optional[int] = None
    avatar_url: Optional[str] = None

class UserLogin(BaseModel):
    login: str
    password: str
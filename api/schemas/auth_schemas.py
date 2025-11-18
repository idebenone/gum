from pydantic import BaseModel

class LoginPayload(BaseModel):
    username: str
    password: str
    
class RegisterPayload(BaseModel):
    username: str
    first_name: str | None = None
    last_name: str | None = None
    location: str | None = None
    gender: str | None = None
    dob: str | None = None
    email: str | None = None
    password: str | None = None    
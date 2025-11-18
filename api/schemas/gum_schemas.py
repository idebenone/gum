from pydantic import BaseModel

class ObservePayload(BaseModel):
    text: str
    model: str | None = None

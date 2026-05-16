from datetime import datetime

from pydantic import BaseModel, field_validator


class EmailRecipientCreate(BaseModel):
    address: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("invalid email address")
        local, domain = v.split("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("invalid email address")
        return v


class EmailRecipientRead(BaseModel):
    id: int
    address: str
    created_at: datetime

    model_config = {"from_attributes": True}

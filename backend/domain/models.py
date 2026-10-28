from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TripSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str = "Москва"
    destination: str | None = None
    check_in: date = date(2026, 11, 21)
    check_out: date = date(2026, 11, 28)
    adults: int = Field(2, ge=1, le=6)
    children_ages: list[int] = Field(default_factory=lambda: [5], max_length=4)
    budget: int = Field(220000, ge=1000, le=3000000)
    mood: str = "Спокойствие"
    interests: list[str] = Field(default_factory=lambda: ["Пляж"], max_length=12)
    direct_only: bool = True
    require_club: bool = False
    pet: bool = False

    @model_validator(mode="after")
    def validate_trip(self):
        if not 1 <= (self.check_out - self.check_in).days <= 21:
            raise ValueError("Поездка должна длиться от 1 до 21 ночи")
        if any(age < 0 or age > 17 for age in self.children_ages):
            raise ValueError("Возраст ребёнка должен быть от 0 до 17 лет")
        return self


class ParseInput(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


class SearchInput(BaseModel):
    spec: TripSpec
    text: str = Field(default="", max_length=3000)


class ChangeInput(BaseModel):
    text: str = Field(default="", max_length=3000)
    action: Literal["message", "flight", "hotel", "late_checkout", "rebook"] = "message"
    value: str = Field(default="", max_length=100)


class ConfirmInput(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=100)


class CheckoutInput(BaseModel):
    version: int = Field(ge=1)
    travelers_confirmed: bool
    payment_mode: Literal["full", "split"] = "full"
    idempotency_key: str = Field(min_length=8, max_length=100)


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

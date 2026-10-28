from datetime import date, timedelta
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class JourneySpec(BaseModel):
    origin: str = Field(default="Москва", max_length=100)
    destination: str = Field(default="", max_length=100)
    check_in: date = Field(default_factory=lambda: date.today() + timedelta(days=7))
    check_out: date = Field(default_factory=lambda: date.today() + timedelta(days=14))
    adults: int = Field(default=2, ge=1, le=10)
    children_ages: list[int] = Field(default_factory=list, max_length=6)
    children_age_unknown: bool = False
    budget: int = Field(default=200000, ge=0, le=10000000)
    budget_unlimited: bool = False
    mood: str = Field(default="Спокойствие", max_length=50)
    interests: list[str] = Field(default_factory=list, max_length=15)
    wishes: str = Field(default="", max_length=3000)
    transport: Literal['air','train'] = 'air'
    outbound_slot: Literal['morning','day','evening','night'] = 'morning'
    inbound_slot: Literal['morning','day','evening','night'] = 'day'
    early_checkin: bool = False
    late_checkout: int | None = Field(default=None,ge=12,le=23)
    luggage_storage: bool = False
    no_night: bool = False
    max_travel_hours: float | None = Field(default=None,gt=0,le=72)
    nightly_budget: int | None = Field(default=None,ge=0)
    min_stars: int | None = Field(default=None,ge=1,le=5)
    required: list[str] = Field(default_factory=list,max_length=15)
    excluded_requirements: list[str] = Field(default_factory=list,max_length=15)
    locked: list[str] = Field(default_factory=list,max_length=15)
    model_fallback: bool = False

    @model_validator(mode="after")
    def valid(self):
        if self.check_out <= self.check_in:
            raise ValueError("Дата возвращения должна быть позже даты начала поездки")
        if (self.check_out-self.check_in).days > 30:
            raise ValueError("Максимальная длительность поездки — 30 ночей")
        if any(a < 0 or a > 17 for a in self.children_ages):
            raise ValueError("Укажи возраст детей от 0 до 17 лет")
        return self


class JourneySearch(BaseModel):
    spec: JourneySpec
    use_text: bool = True


class PlanItem(BaseModel):
    id: str = Field(max_length=100)
    kind: Literal["hotel", "flight", "transfer", "activity", "other"]
    title: str = Field(min_length=1, max_length=200)
    amount: int | None = Field(default=None, ge=0, le=10000000)
    start: str = Field(default="", max_length=50)
    end: str = Field(default="", max_length=50)
    notes: str = Field(default="", max_length=2000)
    booked: bool = False
    source: Literal["user"] = "user"

    @model_validator(mode="after")
    def valid(self):
        from datetime import datetime
        if not self.title.strip():
            raise ValueError('Укажи название события')
        if self.kind == 'flight' and (not self.start or not self.end):
            raise ValueError('Для перелёта укажи дату и время вылета и прилёта')
        for value in (self.start,self.end):
            if value:
                try: datetime.fromisoformat(value)
                except ValueError: raise ValueError('Укажи корректное время события')
        if self.start and self.end:
            start, end = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
            if (start.utcoffset() is None) != (end.utcoffset() is None):
                raise ValueError('Укажи время в одном формате')
            if end < start or (self.kind == 'flight' and end == start):
                raise ValueError('Окончание события должно быть позже начала')
        return self


class PlanEdit(BaseModel):
    version: int
    spec: JourneySpec | None = None
    items: list[PlanItem] | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10000)


class Profile(BaseModel):
    name: str = Field(default="", max_length=100)
    origin: str = Field(default="Москва", max_length=100)
    adults: int = Field(default=2, ge=1, le=10)
    children_ages: list[int] = Field(default_factory=list, max_length=6)
    preferences: str = Field(default="", max_length=2000)

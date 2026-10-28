from datetime import date, timedelta
from typing import Literal
from pydantic import BaseModel, Field, model_validator

Level = Literal['must', 'want', 'skip']

WISHES = {
    'kids': 'Для детей',
    'beach': 'Близко к морю',
    'sea_view': 'Вид на море',
    'breakfast': 'Завтрак',
    'all_inclusive': 'Всё включено',
    'pool': 'Бассейн',
    'pets': 'С питомцем',
    'quiet': 'Тихо',
    'office': 'Рядом с офисом',
    'culture': 'Музеи и театры пешком',
    'accessible': 'Без лестниц, доступно для коляски',
    'wifi': 'Wi-Fi',
}
EXTRAS = ('early_checkin', 'late_checkout', 'storage')


class FlowSpec(BaseModel):
    text: str = Field(default='', max_length=500)
    origin: str = Field(default='Москва', max_length=60)
    destination: str | None = Field(default=None, max_length=40)
    district: str | None = Field(default=None, max_length=40)
    check_in: date = Field(default_factory=lambda: date.today() + timedelta(days=7))
    check_out: date = Field(default_factory=lambda: date.today() + timedelta(days=14))
    adults: int = Field(default=2, ge=1, le=8)
    children_ages: list[int] = Field(default_factory=list, max_length=6)
    pets: bool = False
    budget: int | None = Field(default=None, ge=0, le=20_000_000)
    nightly_budget: int | None = Field(default=None, ge=0, le=1_000_000)
    cheap: bool = False
    purpose: Literal['leisure', 'business'] = 'leisure'
    target_point: str | None = Field(default=None, max_length=40)
    kind: Literal['sea', 'city', 'nature'] | None = None
    warm: bool = False
    max_flight_minutes: int | None = Field(default=None, ge=30, le=1440)
    priorities: dict[str, Level] = Field(default_factory=dict)
    hotel_id: str | None = Field(default=None, max_length=80)
    room_id: str | None = Field(default=None, max_length=20)
    rate_id: str | None = Field(default=None, max_length=20)
    extras: list[str] = Field(default_factory=list, max_length=5)
    arrival_time: str | None = Field(default=None, pattern=r'^\d{2}:\d{2}$')
    out_slot: Literal['morning', 'day', 'evening', 'night'] = 'morning'
    back_slot: Literal['morning', 'day', 'evening', 'night'] = 'day'
    locked: list[str] = Field(default_factory=list, max_length=10)
    countries: list[str] = Field(default_factory=list, max_length=5)   # «в Египет»: only these countries on screen 3
    only: list[str] = Field(default_factory=list, max_length=5)        # «Рас-эль-Хайма или Дубай»: compare exactly these
    remembered: list[str] = Field(default_factory=list, max_length=10)  # wishes from memory: rank only, never exclude

    @model_validator(mode='after')
    def valid(self):
        if self.check_out <= self.check_in:
            raise ValueError('Дата выезда должна быть позже даты заезда')
        if (self.check_out - self.check_in).days > 30:
            raise ValueError('Максимум 30 ночей')
        if any(a < 0 or a > 17 for a in self.children_ages):
            raise ValueError('Возраст ребёнка — от 0 до 17 лет')
        self.priorities = {k: v for k, v in self.priorities.items() if k in WISHES}
        self.extras = [e for e in dict.fromkeys(self.extras) if e in EXTRAS]
        if self.pets:
            self.priorities.setdefault('pets', 'must')
        return self

    @property
    def nights(self):
        return (self.check_out - self.check_in).days

    @property
    def people(self):
        return self.adults + len(self.children_ages)

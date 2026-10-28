from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.domain.models import TripSpec


def coverage_error(spec: TripSpec) -> str | None:
    if spec.origin.casefold().strip() not in {"москва", "мск", "moscow"}:
        return "В демо есть вылеты из Москвы. Другие города ещё не подключены."
    if spec.check_in < date(2026, 11, 1) or spec.check_out > date(2026, 12, 1):
        return "Демо-каталог покрывает ноябрь 2026: заезд с 1 ноября, выезд не позднее 1 декабря."
    if spec.pet:
        return "В демо-каталоге нет подтверждённой перевозки животных. Не будем обещать неподтверждённую поездку."
    return None


def quote(spec: TripSpec, hotel: dict, slot: str = "morning", extra: int = 0, discount: int = 0) -> dict:
    nights = (spec.check_out - spec.check_in).days
    rooms = max(1, (spec.adults + len(spec.children_ages) + 3) // 4)
    flight = spec.adults * hotel["flight_adult"] + sum(hotel["flight_child"] if age >= 2 else 4000 for age in spec.children_ages)
    hotel_cost = nights * hotel["night"] * rooms
    # Demo schedules: morning arrives on check-in day; evening arrives at 01:05
    # on that same local check-in date after departing on the previous date.
    # Immediate check-in for the evening alternative needs the previous night.
    adjustments = {"night": -9000, "morning": 0, "day": 4000, "evening": -7000}
    flight = max(1000, flight + adjustments.get(slot, 0))
    additional_night = 9000 * rooms if slot in {"night", "evening"} else 0
    night_transfer = 1000 if additional_night else 0
    items = [
        {"id": "flight", "label": "Перелёт туда-обратно", "amount": flight},
        {"id": "hotel", "label": f"Отель · {nights} ночей · {rooms} номер", "amount": hotel_cost},
        {"id": "transfer", "label": "Трансфер туда и обратно", "amount": hotel["transfer"] + night_transfer},
    ]
    if additional_night:
        items.append({"id": "arrival_night", "label": "Ночь для заселения после прилёта", "amount": additional_night})
    if extra:
        items.append({"id": "late_checkout", "label": "Выезд до 13:00 · демо-услуга", "amount": extra})
    if discount:
        items.append({"id": "discount", "label": "Снижение цены номера · демо", "amount": -discount})
    total = sum(x["amount"] for x in items)
    return {"items": items, "total": total, "currency": "RUB", "nights": nights,
            "rooms": rooms, "additional_night": additional_night,
            "cancel_until": (spec.check_in - timedelta(days=7)).isoformat(),
            "cancellation": "Отель: бесплатно до указанной даты. Перелёт: невозвратный. Трансфер: до 24 часов.",
            "data_mode": "synthetic"}


def validate(spec: TripSpec, hotel: dict, q: dict) -> list[dict]:
    club_ok = all(a >= hotel["club_age"] for a in spec.children_ages)
    return [
        {"code": "budget", "status": "pass" if q["total"] <= spec.budget else "fail", "label": "В пределах бюджета" if q["total"] <= spec.budget else "Выше заданного бюджета"},
        {"code": "club", "status": "pass" if club_ok else ("fail" if spec.require_club else "unknown"), "label": f"Детский клуб с {hotel['club_age']} лет" + (" — подходит" if club_ok else " — не всем детям подходит")},
        {"code": "inventory", "status": "pass", "label": "Наличие проверено в демо-каталоге"},
    ]


def flight_schedule(spec: TripSpec, slot: str, destination: str) -> dict:
    tz = ZoneInfo("Europe/Istanbul" if destination == "Анталья" else "Africa/Cairo")
    departure = {"morning": "09:40", "day": "13:40", "evening": "21:15", "night": "23:10"}[slot]
    travel_day = spec.check_in - timedelta(days=1) if slot in {"evening", "night"} else spec.check_in
    dep = datetime.combine(travel_day, time.fromisoformat(departure), ZoneInfo("Europe/Moscow"))
    arr = (dep + timedelta(minutes=290)).astimezone(tz)
    return {"departure": dep.isoformat(), "arrival": arr.isoformat(), "departure_time": departure,
            "arrival_time": arr.strftime("%H:%M"), "arrival_day_offset": (arr.date()-dep.date()).days,
            "duration_minutes": 290, "destination_timezone": str(tz)}


def timeline(spec: TripSpec, slot: str, destination: str) -> list[dict]:
    flight = flight_schedule(spec, slot, destination)
    tz = ZoneInfo(flight["destination_timezone"])
    return_flight = datetime.combine(spec.check_out, time(17, 20), tz)
    pickup = return_flight - timedelta(minutes=230)
    arrival = flight["arrival_time"]
    departure = flight["departure_time"]
    travel_day = spec.check_in - timedelta(days=1) if slot in {"evening", "night"} else spec.check_in
    return [
        {"at": travel_day.isoformat(), "time": "За 3 ч до рейса", "title": "Едешь в аэропорт", "text": "Добавь время на дорогу. Такси можно запланировать в демо после покупки.", "kind": "taxi"},
        {"at": travel_day.isoformat(), "time": departure + " · Москва", "title": "Прямой рейс к морю", "text": "Демо-рейс · 4 ч 50 мин · багаж 23 кг. Часовые пояса учтены при расчёте прилёта.", "kind": "flight"},
        {"at": spec.check_in.isoformat(), "time": arrival + " · местное", "title": "Встречаем в аэропорту", "text": "Трансфер до отеля. Для ночного прилёта в стоимость включены доплата и дополнительная ночь.", "kind": "transfer"},
        {"at": spec.check_in.isoformat(), "time": "После трансфера", "title": "Заселение", "text": "Номер и питание из выбранного тарифа. Все подтверждения здесь симулируются.", "kind": "hotel"},
        {"at": spec.check_in.isoformat(), "time": f"{(spec.check_out-spec.check_in).days} ночей", "title": "Твоя неделя у моря", "text": "Спокойные утра, время вместе и никаких лишних вкладок.", "kind": "stay"},
        {"at": spec.check_out.isoformat(), "time": pickup.strftime("%H:%M") + " · из отеля", "title": "Домой без спешки", "text": "Вылет 17:20. В расчёте: 50 минут дороги и 3 часа до вылета. Это параметры демо-сценария.", "kind": "return"},
    ]

import time
from datetime import timedelta
from uuid import uuid4

from backend.domain.models import TripSpec
from backend.domain.errors import Conflict
from backend.domain.planner import coverage_error
from backend.application.selection import make_offer
from backend.infrastructure.catalog import HOTELS, hotel_by_id
from backend.infrastructure.intent import demo_parse


def new_trip(spec: TripSpec, hotel_id: str) -> dict:
    hotel = hotel_by_id(hotel_id)
    if coverage_error(spec):
        raise Conflict(coverage_error(spec))
    if spec.destination and spec.destination.casefold() not in hotel["destination"].casefold():
        raise Conflict("Отель не соответствует направлению")
    offer = make_offer(spec, hotel)
    if any(c["status"] == "fail" for c in offer["checks"]):
        raise Conflict("Предложение не соответствует условиям поездки")
    return {"id": str(uuid4()), "version": 1, "status": "draft", "offer": offer,
            "quote_expires_at": time.time() + 900, "proposal": None, "actions": [], "messages": [], "payment_mode": None}


def propose(trip: dict, action: str, value: str, text: str) -> dict:
    old = trip["offer"]
    spec = TripSpec.model_validate(old["spec"])
    hotel, slot, extra, discount = old["hotel"], old["slot"], old["extra"], old["discount"]
    reply = ""
    t = text.casefold().replace("ё", "е")
    changed: list[str] = []
    if action == "message":
        if "поздн" in t or "выезд" in t:
            action = "late_checkout"
        elif "вечер" in t:
            action, value = "flight", "evening"
        elif "утр" in t and not any(x in t for x in ["дешев", "эконом", "бюджет"]):
            action, value = "flight", "morning"
    if action == "flight":
        if value not in {"morning", "day", "evening", "night"}:
            raise Conflict("Неизвестное время рейса")
        slot = value
        changed = ["Рейс", "Трансфер", "Заселение"]
        reply = "Пересчитал рейс, заселение и трансфер. "
        if slot in {"evening", "night"}:
            reply += "Ночной прилёт требует предыдущей ночи для немедленного заселения (+9 000 ₽ за номер) и ночного трансфера (+1 000 ₽)."
        else:
            reply += "Дневное заселение — дополнительная ночь не нужна."
    elif action == "hotel":
        hotel = hotel_by_id(value)
        if hotel["destination"] != old["hotel"]["destination"]:
            raise Conflict("Выбери отель в текущем направлении или начни новый поиск")
        changed = ["Отель", "Трансфер"]
        reply = hotel["reason"] + ". " + hotel["tradeoff"]
        discount = 0
    elif action == "late_checkout":
        extra = 1500
        changed = ["Поздний выезд"]
        reply = "Вылет в 17:20, из отеля нужно выехать в 13:30: 50 минут дороги и 3 часа до рейса. До 18:00 оставаться нельзя. В демо доступен выезд до 13:00 за 1 500 ₽. Добавить?"
    elif action == "rebook":
        if trip["status"] != "booked":
            raise Conflict("Мониторинг доступен после демобронирования")
        if old["discount"]:
            return {"reply": "Экономия 9 400 ₽ уже применена. Новых предложений пока нет.", "proposal": None}
        discount = 9400
        changed = ["Тариф отеля"]
        reply = "Симуляция: тот же номер, даты, питание и отмена. Новая бронь будет подтверждена до отмены старой. Чистая экономия — 9 400 ₽."
    elif action == "message":
        fields = demo_parse(text)
        if "два дня" in t or "2 дня" in t:
            fields.update(check_in=spec.check_in + timedelta(days=2), check_out=spec.check_out + timedelta(days=2))
        if "бабушк" in t:
            fields["adults"] = spec.adults + 1
        if fields:
            spec = TripSpec.model_validate({**spec.model_dump(), **fields})
            error = coverage_error(spec)
            if error:
                return {"reply": error, "proposal": None}
            changed = ["Условия поездки", "Стоимость", "План"]
            reply = "Пересчитал поездку с новыми условиями. "
        if any(x in t for x in ["дешев", "эконом", "бюджет"]) or fields:
            choices = [make_offer(spec, h, slot, extra) for h in HOTELS if h["destination"] == hotel["destination"]]
            valid = [o for o in choices if not any(c["status"] == "fail" for c in o["checks"])]
            if not valid:
                return {"reply": "Не нашёл подходящего варианта с сохранением условий. Текущую поездку оставил без изменений. Попробуй изменить бюджет или требования.", "proposal": None}
            choice = min(valid, key=lambda o: o["quote"]["total"])
            hotel = choice["hotel"]
            if not fields and choice["quote"]["total"] >= old["quote"]["total"]:
                return {"reply": "Сейчас это самый выгодный вариант с сохранением рейса и условий. Более дешёвого в демо-каталоге нет.", "proposal": None}
            changed += ["Отель", "Трансфер"]
            reply += "Рейс сохранил. " + hotel["tradeoff"]
            discount = 0
        else:
            return {"reply": "Могу пересчитать бюджет, сдвинуть поездку на два дня, выбрать вечерний рейс, сменить отель или проверить поздний выезд. Для другого изменения уточни условия через поиск.", "proposal": None}
    new_offer = make_offer(spec, hotel, slot, extra, discount)
    if any(c["status"] == "fail" for c in new_offer["checks"]):
        failures = "; ".join(c["label"] for c in new_offer["checks"] if c["status"] == "fail")
        return {"reply": f"Не могу применить: {failures}. Текущий план сохранён.", "proposal": None}
    proposal = {"id": str(uuid4()), "base_version": trip["version"], "expires_at": time.time() + 600,
                "offer": new_offer, "changed": list(dict.fromkeys(changed)),
                "delta": new_offer["quote"]["total"] - old["quote"]["total"],
                "reply": reply, "action": action}
    return {"reply": reply, "proposal": proposal}

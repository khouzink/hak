from datetime import datetime
from backend.domain.models import TripSpec
from backend.domain.planner import quote, validate, timeline, coverage_error, flight_schedule
from backend.infrastructure.catalog import CATALOG_VERSION, HOTELS, evidence

def make_offer(spec: TripSpec, hotel: dict, slot: str = "morning", extra: int = 0, discount: int = 0) -> dict:
    q = quote(spec, hotel, slot, extra, discount)
    flight = flight_schedule(spec, slot, hotel["destination"])
    arrival = datetime.fromisoformat(flight["arrival"])
    dates_ok = arrival.date() == spec.check_in and (arrival.hour >= 6 or q["additional_night"] > 0)
    checks = validate(spec, hotel, q)
    checks.insert(1, {"code": "dates", "status": "pass" if dates_ok else "fail", "label": "Даты рейса, отеля и трансфера согласованы" if dates_ok else "Не согласованы прилёт и заселение"})
    return {"hotel": hotel, "quote": q, "checks": checks,
            "slot": slot, "evidence": evidence(hotel), "catalog_version": CATALOG_VERSION,
            "spec": spec.model_dump(mode="json"), "timeline": timeline(spec, slot, hotel["destination"]),
            "flight": flight_schedule(spec, slot, hotel["destination"]),
            "extra": extra, "discount": discount}


def search(spec: TripSpec) -> dict:
    error = coverage_error(spec)
    if error:
        return {"offers": [], "reason": error, "scanned": 0}
    candidates = [h for h in HOTELS if not spec.destination or spec.destination.casefold() in h["destination"].casefold()]
    offers = [make_offer(spec, h) for h in candidates]
    valid = [o for o in offers if all(c["status"] != "fail" for c in o["checks"])]
    # Balanced, quiet and economical: prefer distinct destinations when available.
    selected = []
    for o in valid:
        if o["hotel"]["destination"] not in [x["hotel"]["destination"] for x in selected]:
            selected.append(o)
    selected.extend(o for o in valid if o not in selected)
    if spec.mood == "Спокойствие" and not spec.children_ages:
        selected.sort(key=lambda o: -o["hotel"]["quiet"])
    reason = ""
    if not selected:
        reason = "Подходящих вариантов нет. Попробуй изменить бюджет, направление или требование к детскому клубу."
        if offers:
            reason += f" Самая низкая цена в этой выборке — {min(o['quote']['total'] for o in offers):,} ₽."
    return {"offers": selected[:3], "reason": reason, "scanned": len(candidates)}



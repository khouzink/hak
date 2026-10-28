import asyncio
import json
import logging
import os
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from backend.application.trips import new_trip, propose
from backend.domain.models import ChangeInput, CheckoutInput, ConfirmInput, ParseInput, QuestionInput, SearchInput, TripSpec
from backend.application.selection import search
from backend.infrastructure.catalog import HOTELS, evidence
from backend.infrastructure.intent import parse_intent
from backend.infrastructure.store import Store
from backend.infrastructure.safety import validate_user_text
from backend.presentation.body_limit import BodyLimitMiddleware
from backend.presentation.errors import install_error_handlers

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("uno")
app = FastAPI(title="О!дин запрос", version="8.0.0")
app.add_middleware(BodyLimitMiddleware)
install_error_handlers(app)
store = Store()


@app.middleware("http")
async def session_and_trace(request: Request, call_next):
    session = request.cookies.get("uno_session") or str(uuid4())
    request.state.owner = session
    trace_id = str(uuid4())
    start = time.perf_counter()
    response = await call_next(request)
    if not request.cookies.get("uno_session"):
        response.set_cookie("uno_session", session, httponly=True, secure=os.getenv('SESSION_COOKIE_SECURE')=='1', samesite="strict", max_age=2592000)
    response.headers["X-Trace-ID"] = trace_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    log.info(json.dumps({"trace_id": trace_id, "path": request.url.path, "status": response.status_code, "ms": round((time.perf_counter()-start)*1000)}))
    return response


@app.get("/health")
def health():
    return {"status": "ok", "version": "9.0.0", "data_mode": "regional_public_facts_synthetic_rates", "live_rates": False}


@app.post("/api/intent")
async def intent(body: ParseInput):
    try:
        return await parse_intent(validate_user_text(body.text))
    except ValueError:
        raise
    except Exception:
        raise HTTPException(503, "Не удалось разобрать запрос. Проверь параметры вручную или повтори позже.")


@app.post("/api/search")
async def find(body: SearchInput):
    async def events():
        yield "data: " + json.dumps({"stage": "Проверяем пожелания", "progress": 10}) + "\n\n"
        await asyncio.sleep(0)
        result = search(body.spec)
        yield "data: " + json.dumps({"stage": "Сопоставляем рейсы, отели и трансферы", "progress": 75, "hotels": result["scanned"], "reviews": result["scanned"] * 3, "flights": 4 if result["scanned"] else 0}, ensure_ascii=False) + "\n\n"
        yield "data: " + json.dumps({"stage": "Готово", "progress": 100, "result": result}, ensure_ascii=False) + "\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class SelectInput(BaseModel):
    spec: TripSpec
    hotel_id: str


@app.post("/api/trips")
def select(body: SelectInput, request: Request):
    if body.hotel_id not in {h["id"] for h in HOTELS}:
        raise HTTPException(404, "Отель не найден")
    trip = new_trip(body.spec, body.hotel_id)
    store.create(trip, request.state.owner)
    return trip


@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: str, request: Request):
    return store.get(trip_id, request.state.owner)[0]


@app.post("/api/trips/{trip_id}/changes")
def change(trip_id: str, body: ChangeInput, request: Request):
    trip, rev = store.get(trip_id, request.state.owner)
    try:
        result = propose(trip, body.action, body.value, body.text)
    except StopIteration:
        raise HTTPException(404, "Отель не найден")
    trip["proposal"] = result["proposal"]
    if body.text:
        trip["messages"].append({"role": "user", "text": body.text})
        trip["messages"].append({"role": "assistant", "text": result["reply"]})
    trip["messages"] = trip["messages"][-50:]
    store.save(trip, request.state.owner, rev)
    return {**result, "trip": trip}


@app.post("/api/trips/{trip_id}/confirm")
def confirm(trip_id: str, body: ConfirmInput, request: Request):
    trip, rev = store.get(trip_id, request.state.owner)
    if any(a.get("proposal_id") == body.proposal_id for a in trip["actions"]):
        return trip
    p = trip["proposal"]
    if not p or p["id"] != body.proposal_id or p["base_version"] != trip["version"] or p["expires_at"] < time.time():
        raise ValueError("Предложение устарело. Запроси новый расчёт.")
    trip["offer"] = p["offer"]
    trip["version"] += 1
    trip["quote_expires_at"] = time.time() + 900
    trip["proposal"] = None
    trip["actions"].append({"id": str(uuid4()), "proposal_id": p["id"], "type": p["action"], "status": "done", "label": "Изменение подтверждено в демо", "at": time.time()})
    trip["messages"].append({"role": "assistant", "text": "Готово, план и стоимость обновлены. Подтверждение услуги в этом режиме симулируется."})
    store.save(trip, request.state.owner, rev)
    return trip


@app.post("/api/trips/{trip_id}/checkout")
def checkout(trip_id: str, body: CheckoutInput, request: Request):
    trip, rev = store.get(trip_id, request.state.owner)
    if trip["status"] == "booked":
        return trip
    if body.version != trip["version"] or trip["quote_expires_at"] < time.time():
        raise ValueError("Цена или версия устарела. Обнови предложение перед оплатой.")
    if not body.travelers_confirmed:
        raise ValueError("Сначала подтверди данные демонстрационных путешественников")
    trip.update(status="booked", payment_mode=body.payment_mode, version=trip["version"] + 1, proposal=None)
    trip["actions"].append({"id": str(uuid4()), "type": "checkout", "status": "done", "label": "Демобронирование оформлено", "idempotency_key": body.idempotency_key, "at": time.time()})
    for kind, label in [("cancel_reminder", "Напомнить об отмене отеля"), ("checkin", "Напомнить о регистрации на рейс"), ("taxi", "Напомнить заказать такси")]:
        trip["actions"].append({"id": str(uuid4()), "type": kind, "status": "planned", "label": label, "at": None})
    store.save(trip, request.state.owner, rev)
    return trip


@app.get("/api/trips/{trip_id}/alternatives")
def alternatives(trip_id: str, request: Request):
    from backend.application.selection import make_offer
    trip, _ = store.get(trip_id, request.state.owner)
    o = trip["offer"]
    spec = TripSpec.model_validate(o["spec"])
    choices = [make_offer(spec, h, o["slot"], o["extra"]) for h in HOTELS if h["destination"] == o["hotel"]["destination"] and h["id"] != o["hotel"]["id"]]
    return [c for c in choices if all(v["status"] != "fail" for v in c["checks"])]


@app.get("/api/trips/{trip_id}/flight-options")
def flight_options(trip_id: str, request: Request):
    from backend.application.selection import make_offer
    trip, _ = store.get(trip_id, request.state.owner)
    o = trip["offer"]
    spec = TripSpec.model_validate(o["spec"])
    return [make_offer(spec, o["hotel"], slot, o["extra"], o["discount"]) for slot in ["night", "morning", "day", "evening"]]


@app.post("/api/trips/{trip_id}/question")
def question(trip_id: str, body: QuestionInput, request: Request):
    trip, _ = store.get(trip_id, request.state.owner)
    hotel = trip["offer"]["hotel"]
    refs = evidence(hotel)
    q = body.question.casefold()
    if any(word in q for word in ["меню", "питан", "еда"]):
        answer, sources = "В демо-отзыве есть отдельная детская линия. Часы работы не подтверждены — их нужно уточнить у отеля.", [refs[2]]
    elif any(word in q for word in ["шум", "тихо", "ноч"]):
        answer, sources = "По демо-отзыву в дальнем корпусе спокойно, у бассейна вечером бывает музыка. Полную тишину гарантировать нельзя.", [refs[1]]
    elif "клуб" in q:
        answer, sources = f"В демо-карточке клуб с {hotel['club_age']} лет. Проверь возраст детей на дату поездки.", [refs[0]]
    else:
        answer, sources = "В доступных источниках нет подтверждённого ответа на этот вопрос. Уточни у отеля — выдумывать не буду.", []
    return {"answer": answer, "sources": sources, "data_mode": "synthetic"}


from backend.presentation.mcp import router as mcp_router
app.include_router(mcp_router)
from backend.presentation.product import router as product_router
app.include_router(product_router)
# Legacy synthetic endpoints are kept only for isolated regression tests.
if os.getenv("ENABLE_LEGACY_DEMO") != "1":
    app.router.routes[:] = [route for route in app.router.routes if not (getattr(route, "path", "").startswith("/api/") and not getattr(route, "path", "").startswith("/api/v1/"))]

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/")
def index():
    if not DIST.exists():
        return JSONResponse({"detail": "Сначала выполните npm run build в frontend"}, status_code=503)
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

from backend.presentation.poi import router as poi_router
app.include_router(poi_router)
from backend.flow import ports as flow_ports
from backend.flow.api import router as flow_router
from backend.presentation import product as product_provider

flow_ports.use(product_provider)  # the flow gets the model and the store without importing presentation
app.include_router(flow_router)

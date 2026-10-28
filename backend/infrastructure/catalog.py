"""Small, explicit synthetic inventory. Photos are reference-video illustrations."""
CATALOG_VERSION = "demo-2026-11-v1"
HOTELS = [
    dict(id="sunrise", name="Sunrise Garden Beach", destination="Хургада", stars=5,
         rating=9.2, night=17000, flight_adult=24000, flight_child=16000, transfer=3500,
         sea=150, club_age=4, quiet=0.85, meal="Всё включено", badge="Лучший выбор",
         image="/assets/hurghada.jpg", hotel_image="/assets/hotel.jpg", pets=False,
         reason="Прямой рейс утром, детский клуб и море в 150 метрах",
         tradeoff="Вечером у главного бассейна бывает музыка — выбираем тихий корпус"),
    dict(id="rixos", name="Rixos Premium", destination="Шарм-эль-Шейх", stars=5,
         rating=9.5, night=20000, flight_adult=25500, flight_child=17500, transfer=3500,
         sea=100, club_age=4, quiet=0.95, meal="Всё включено", badge="Тише всего",
         image="/assets/sharm.jpg", hotel_image="/assets/sharm.jpg", pets=False,
         reason="Тихая территория и короткий трансфер для спокойного отдыха",
         tradeoff="Дороже остальных вариантов; часть входа в море с понтона"),
    dict(id="antalya", name="Concorde De Luxe", destination="Анталья", stars=5,
         rating=8.9, night=11000, flight_adult=24000, flight_child=16000, transfer=4000,
         sea=200, club_age=4, quiet=0.75, meal="Всё включено", badge="Дешевле всего",
         image="/assets/antalya.jpg", hotel_image="/assets/antalya.jpg", pets=False,
         reason="Меньше расходов, прямой перелёт и большая территория",
         tradeoff="В ноябре купание в море не гарантировано — вариант для прогулок и бассейна"),
    dict(id="aqua", name="Steigenberger Aqua Magic", destination="Хургада", stars=5,
         rating=9.0, night=18700, flight_adult=24000, flight_child=16000, transfer=4000,
         sea=300, club_age=3, quiet=0.7, meal="Всё включено", badge="С аквапарком",
         image="/assets/hotel.jpg", hotel_image="/assets/hotel.jpg", pets=False,
         reason="Аквапарк и детский клуб с трёх лет",
         tradeoff="До моря 300 метров; у аквапарка активнее и шумнее"),
    dict(id="jaz", name="Jaz Aquamarine", destination="Хургада", stars=5,
         rating=8.7, night=15000, flight_adult=24000, flight_child=16000, transfer=3500,
         sea=600, club_age=4, quiet=0.8, meal="Всё включено", badge="Выгоднее",
         image="/assets/hurghada.jpg", hotel_image="/assets/hotel.jpg", pets=False,
         reason="Детский клуб сохранён, стоимость ниже",
         tradeoff="До моря 600 метров — прогулка дольше"),
]


def hotel_by_id(hotel_id: str) -> dict:
    return next(h for h in HOTELS if h["id"] == hotel_id)


def evidence(hotel: dict) -> list[dict]:
    return [
        {"id": hotel["id"] + "-club", "source": "Демо-карточка отеля", "date": "2026-10-24", "text": f"Детский клуб принимает детей с {hotel['club_age']} лет. Питание: всё включено.", "kind": "synthetic"},
        {"id": hotel["id"] + "-quiet", "source": "Синтетический отзыв · семья с ребёнком", "date": "2026-10-20", "text": "В дальнем корпусе спали спокойно. У главного бассейна вечером была музыка.", "kind": "synthetic"},
        {"id": hotel["id"] + "-food", "source": "Синтетический отзыв · путешествие с детьми", "date": "2026-10-18", "text": "В ресторане была отдельная детская линия. Часы работы не записали.", "kind": "synthetic"},
    ]

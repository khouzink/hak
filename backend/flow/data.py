"""Destination catalogue for the linear flow.

What is a fact and what is a model here:
- hotels, coordinates, stars, websites and amenity tags come from OpenStreetMap snapshots
  (backend/datasets/regions.json, sochi_open.json) and reviewed hotel pages (hotel_provider.HOTELS);
- climate comes from Open-Meteo archive averages (region_climate.json);
- airport coordinates are public reference points;
- flight duration, fares, transfer prices, room types and tariffs are a DEMO model;
- district summaries and destination "character" lines are editorial text, not hotel facts.
"""
import json
import math
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

DATASETS = Path(__file__).resolve().parents[1] / 'datasets'
ORIGIN = {'name': 'Москва', 'timezone': 'Europe/Moscow', 'airport': 'SVO', 'airport_name': 'Шереметьево'}

# minutes: model flight time from Moscow; fare: model round-trip fare per adult, ₽ (child −30 %);
# index: model price level of hotels vs. Moscow-region average.
DESTINATIONS = [
    {'id': 'el_gouna', 'name': 'Эль-Гуна', 'country': 'Египет', 'kind': 'sea', 'timezone': 'Africa/Cairo',
     'character': 'город на лагунах, мелко и тихо для детей', 'traits': ['sea', 'kids', 'quiet', 'lagoon'],
     'airport': {'code': 'HRG', 'name': 'аэропорт Хургады', 'lat': 27.1783, 'lon': 33.7994},
     'center': {'name': 'центр Эль-Гуны (Кафр)', 'lat': 27.3967, 'lon': 33.6770},
     'minutes': 290, 'fare': 36000, 'index': 1.0, 'resort': True, 'image': 'hurghada.jpg',
     'why': ['Лагуны с мелким заходом — спокойнее, чем открытый берег', 'Прямой рейс и короткий трансфер'],
     'tradeoff': 'Тише Хургады, но вечерних развлечений меньше',
     'districts': [
         {'id': 'lagoons', 'name': 'Лагуны Фанадир', 'osm': ['Fanadir Lagoons'], 'lat': 27.4120, 'lon': 33.6725,
          'summary': 'тихо, отели прямо на лагунах, мелко для детей', 'traits': ['quiet', 'kids', 'beach']},
         {'id': 'marina', 'name': 'Абу-Тиг Марина', 'osm': ['Abu Tig Marina', 'South Marina'], 'lat': 27.4060, 'lon': 33.6745,
          'summary': 'набережная и кафе рядом, но шумнее вечером', 'traits': ['center', 'nightlife', 'beach']},
         {'id': 'kafr', 'name': 'Кафр и центр', 'osm': ['Kafr', 'Phase 1', 'Sheraton Miramar'], 'lat': 27.3940, 'lon': 33.6790,
          'summary': 'центр городка, магазины и рестораны, до моря дальше', 'traits': ['center']},
     ]},
    {'id': 'marsa_alam', 'name': 'Марса-Алам', 'country': 'Египет', 'kind': 'sea', 'timezone': 'Africa/Cairo',
     'character': 'риф у берега, черепахи и дюгони', 'traits': ['sea', 'quiet', 'nature', 'reef'],
     'airport': {'code': 'RMF', 'name': 'аэропорт Марса-Алам', 'lat': 25.5571, 'lon': 34.5837},
     'center': {'name': 'Марса-Алам', 'lat': 25.0630, 'lon': 34.8900},
     'minutes': 300, 'fare': 38000, 'index': 0.85, 'resort': True, 'image': 'sharm.jpg',
     'why': ['Тише всего: мало отелей и нет большого города', 'Риф прямо у берега — можно смотреть рыб с маской'],
     'tradeoff': 'Трансфер из аэропорта дольше, вокруг почти нет города',
     'districts': []},
    {'id': 'ras_al_khaimah', 'name': 'Рас-эль-Хайма', 'country': 'ОАЭ', 'kind': 'sea', 'timezone': 'Asia/Dubai',
     'character': 'горы и пляжи, спокойнее и дешевле Дубая', 'traits': ['sea', 'quiet', 'mountains'],
     'airport': {'code': 'RKT', 'name': 'аэропорт Рас-эль-Хаймы', 'lat': 25.6135, 'lon': 55.9388},
     'center': {'name': 'центр Рас-эль-Хаймы', 'lat': 25.7895, 'lon': 55.9432},
     'minutes': 310, 'fare': 42000, 'index': 1.25, 'resort': True, 'image': 'antalya.jpg',
     'why': ['Самое тёплое море из вариантов в ноябре', 'Спокойнее Дубая, рядом горы Хаджар'],
     'tradeoff': 'Перелёт чуть длиннее и дороже Египта',
     'districts': [
         {'id': 'nakheel', 'name': 'Дафан-эн-Нахиль и лагуна', 'osm': ['دفان النخيل', 'دفن الخور راس الخيمه', 'دفان الخور', 'القرم', 'المعيريض'], 'lat': 25.7930, 'lon': 55.9600,
          'summary': 'центр у лагуны, кафе и магазины рядом', 'traits': ['center']},
         {'id': 'coast', 'name': 'Южное побережье', 'osm': ['خزام', 'الظيت الجنوبي'], 'lat': 25.7470, 'lon': 55.8980,
          'summary': 'курортные отели у пляжа, тише, до центра на машине', 'traits': ['quiet', 'beach', 'kids']},
     ]},
    {'id': 'hurghada', 'name': 'Хургада', 'country': 'Египет', 'kind': 'sea', 'timezone': 'Africa/Cairo',
     'character': 'большой курорт, много отелей и развлечений', 'traits': ['sea', 'nightlife', 'budget'],
     'airport': {'code': 'HRG', 'name': 'аэропорт Хургады', 'lat': 27.1783, 'lon': 33.7994},
     'center': {'name': 'центр Хургады', 'lat': 27.2000, 'lon': 33.8400},
     'minutes': 290, 'fare': 34000, 'index': 0.8, 'resort': True, 'image': 'hurghada.jpg',
     'why': ['Самый короткий трансфер из аэропорта', 'Много отелей в любом бюджете'], 'tradeoff': 'Шумнее и многолюднее', 'districts': []},
    {'id': 'sharm', 'name': 'Шарм-эль-Шейх', 'country': 'Египет', 'kind': 'sea', 'timezone': 'Africa/Cairo',
     'character': 'кораллы и дайвинг на Синае', 'traits': ['sea', 'reef', 'nightlife'],
     'airport': {'code': 'SSH', 'name': 'аэропорт Шарм-эль-Шейха', 'lat': 27.9773, 'lon': 34.3950},
     'center': {'name': 'Наама-Бей', 'lat': 27.9100, 'lon': 34.3200},
     'minutes': 280, 'fare': 35000, 'index': 0.9, 'resort': True, 'image': 'sharm.jpg',
     'why': ['Лучшие кораллы у берега', 'Тепло до декабря'], 'tradeoff': 'Вход в море часто с понтона, для малышей сложнее', 'districts': []},
    {'id': 'dubai', 'name': 'Дубай', 'country': 'ОАЭ', 'kind': 'sea', 'timezone': 'Asia/Dubai',
     'character': 'мегаполис у моря, шопинг и небоскрёбы', 'traits': ['sea', 'city', 'nightlife'],
     'airport': {'code': 'DXB', 'name': 'аэропорт Дубая', 'lat': 25.2532, 'lon': 55.3657},
     'center': {'name': 'Даунтаун', 'lat': 25.1972, 'lon': 55.2744},
     'minutes': 310, 'fare': 44000, 'index': 1.6, 'resort': False, 'image': 'antalya.jpg',
     'why': ['Тепло и много городских развлечений', 'Много прямых рейсов'], 'tradeoff': 'Дорого и шумно', 'districts': []},
    {'id': 'phuket', 'name': 'Пхукет', 'country': 'Таиланд', 'kind': 'sea', 'timezone': 'Asia/Bangkok',
     'character': 'тропический остров, сезон с ноября', 'traits': ['sea', 'nature', 'nightlife'],
     'airport': {'code': 'HKT', 'name': 'аэропорт Пхукета', 'lat': 8.1132, 'lon': 98.3169},
     'center': {'name': 'Пхукет-таун', 'lat': 7.8906, 'lon': 98.3981},
     'minutes': 570, 'fare': 78000, 'index': 0.9, 'resort': True, 'image': 'design-v2/u0.jpg',
     'why': ['Тропики и сезон без дождей', 'Много пляжей'], 'tradeoff': 'Перелёт около 9,5 часа', 'districts': []},
    {'id': 'nhatrang', 'name': 'Нячанг', 'country': 'Вьетнам', 'kind': 'sea', 'timezone': 'Asia/Ho_Chi_Minh',
     'character': 'городской пляж и острова', 'traits': ['sea', 'city', 'budget'],
     'airport': {'code': 'CXR', 'name': 'аэропорт Камрань', 'lat': 11.9982, 'lon': 109.2194},
     'center': {'name': 'центр Нячанга', 'lat': 12.2451, 'lon': 109.1943},
     'minutes': 540, 'fare': 70000, 'index': 0.7, 'resort': False, 'image': 'design-v2/u0.jpg',
     'why': ['Недорогие отели', 'Тепло круглый год'], 'tradeoff': 'Перелёт около 9 часов, в ноябре бывают дожди', 'districts': []},
    {'id': 'maldives', 'name': 'Мальдивы', 'country': 'Мальдивы', 'kind': 'sea', 'timezone': 'Indian/Maldives',
     'character': 'острова-отели в океане', 'traits': ['sea', 'quiet', 'romance'],
     'airport': {'code': 'MLE', 'name': 'аэропорт Мале', 'lat': 4.1918, 'lon': 73.5291},
     'center': {'name': 'Мале', 'lat': 4.1752, 'lon': 73.5092},
     'minutes': 540, 'fare': 95000, 'index': 3.0, 'resort': True, 'image': 'design-v2/u13.jpg',
     'why': ['Самая прозрачная вода', 'Полное уединение'], 'tradeoff': 'Очень дорого и долго лететь', 'districts': []},
    {'id': 'sochi', 'name': 'Сочи', 'country': 'Россия', 'kind': 'sea', 'timezone': 'Europe/Moscow',
     'character': 'море и горы без загранпаспорта', 'traits': ['sea', 'mountains', 'kids'],
     'airport': {'code': 'AER', 'name': 'аэропорт Сочи', 'lat': 43.4499, 'lon': 39.9566},
     'center': {'name': 'Морской вокзал Сочи', 'lat': 43.5792, 'lon': 39.7226},
     'minutes': 140, 'fare': 16000, 'index': 1.1, 'resort': True, 'image': 'design-v2/u0.jpg',
     'why': ['Без загранпаспорта и визы', 'Короткий перелёт'], 'tradeoff': 'Море холодное вне лета', 'pets_ok': True,
     'districts': [
         {'id': 'center', 'name': 'Центральный Сочи', 'osm': [], 'lat': 43.5800, 'lon': 39.7240, 'areas': ['Центральный Сочи', 'Сочи, ул. Виноградная'],
          'summary': 'набережная, музеи и театры пешком, оживлённо', 'traits': ['center', 'culture', 'nightlife']},
         {'id': 'sirius', 'name': 'Сириус и Имеретинская бухта', 'osm': [], 'lat': 43.4080, 'lon': 39.9600, 'areas': ['Сириус', 'Имеретинская бухта'],
          'summary': 'ровная набережная, парки и аттракционы, спокойнее центра', 'traits': ['kids', 'quiet', 'beach']},
     ]},
    {'id': 'kazan', 'name': 'Казань', 'country': 'Россия', 'kind': 'city', 'timezone': 'Europe/Moscow',
     'character': 'Кремль, татарская кухня и выставки', 'traits': ['city', 'culture', 'business'],
     'airport': {'code': 'KZN', 'name': 'аэропорт Казани', 'lat': 55.6062, 'lon': 49.2787},
     'center': {'name': 'Казанский Кремль', 'lat': 55.7987, 'lon': 49.1056},
     'minutes': 90, 'fare': 12000, 'index': 0.7, 'resort': False, 'image': 'design-v2/u6.jpg', 'pets_ok': True,
     'why': ['Много музеев в центре', 'Полтора часа лёта'], 'tradeoff': 'Зимой холодно', 'districts': [],
     'points': [{'id': 'expo', 'name': 'Казань Экспо', 'lat': 55.6347, 'lon': 49.2441, 'note': 'ориентир по карте'}]},
    {'id': 'kaliningrad', 'name': 'Калининград', 'country': 'Россия', 'kind': 'city', 'timezone': 'Europe/Kaliningrad',
     'character': 'Балтика, готика и Куршская коса рядом', 'traits': ['city', 'culture', 'sea', 'pets'],
     'airport': {'code': 'KGD', 'name': 'аэропорт Храброво', 'lat': 54.8900, 'lon': 20.5926},
     'center': {'name': 'Кафедральный собор', 'lat': 54.7064, 'lon': 20.5113},
     'minutes': 130, 'fare': 14000, 'index': 0.85, 'resort': False, 'image': 'design-v2/u6.jpg', 'pets_ok': True,
     'why': ['Без визы, но Европа по атмосфере', 'Море в получасе'], 'tradeoff': 'В ноябре прохладно и ветрено', 'districts': []},
    {'id': 'petersburg', 'name': 'Санкт-Петербург', 'country': 'Россия', 'kind': 'city', 'timezone': 'Europe/Moscow',
     'character': 'музеи, театры и разводные мосты', 'traits': ['city', 'culture'],
     'airport': {'code': 'LED', 'name': 'аэропорт Пулково', 'lat': 59.8003, 'lon': 30.2625},
     'center': {'name': 'Дворцовая площадь', 'lat': 59.9390, 'lon': 30.3158},
     'minutes': 85, 'fare': 10000, 'index': 1.0, 'resort': False, 'image': 'design-v2/u6.jpg', 'pets_ok': True,
     'why': ['Эрмитаж и театры пешком', 'Можно на поезде'], 'tradeoff': 'Короткий световой день осенью', 'districts': []},
    {'id': 'istanbul', 'name': 'Стамбул', 'country': 'Турция', 'kind': 'city', 'timezone': 'Europe/Istanbul',
     'character': 'город на двух континентах', 'traits': ['city', 'culture'],
     'airport': {'code': 'IST', 'name': 'аэропорт Стамбула', 'lat': 41.2753, 'lon': 28.7519},
     'center': {'name': 'Султанахмет', 'lat': 41.0055, 'lon': 28.9768},
     'minutes': 210, 'fare': 30000, 'index': 0.95, 'resort': False, 'image': 'design-v2/u11.jpg',
     'why': ['История и кухня', 'Без визы'], 'tradeoff': 'Трансфер из аэропорта около часа', 'districts': []},
    {'id': 'tbilisi', 'name': 'Тбилиси', 'country': 'Грузия', 'kind': 'city', 'timezone': 'Asia/Tbilisi',
     'character': 'гастро-город, серные бани', 'traits': ['city', 'culture', 'food'],
     'airport': {'code': 'TBS', 'name': 'аэропорт Тбилиси', 'lat': 41.6692, 'lon': 44.9547},
     'center': {'name': 'Старый город', 'lat': 41.6925, 'lon': 44.8090},
     'minutes': 180, 'fare': 26000, 'index': 0.7, 'resort': False, 'image': 'design-v2/u6.jpg',
     'why': ['Еда и вино', 'Старый город пешком'], 'tradeoff': 'Холмы — много подъёмов', 'districts': []},
    {'id': 'yerevan', 'name': 'Ереван', 'country': 'Армения', 'kind': 'city', 'timezone': 'Asia/Yerevan',
     'character': 'Арарат на горизонте, недорого', 'traits': ['city', 'culture', 'budget'],
     'airport': {'code': 'EVN', 'name': 'аэропорт Звартноц', 'lat': 40.1473, 'lon': 44.3959},
     'center': {'name': 'площадь Республики', 'lat': 40.1777, 'lon': 44.5126},
     'minutes': 185, 'fare': 24000, 'index': 0.65, 'resort': False, 'image': 'design-v2/u6.jpg',
     'why': ['Недорогие отели в центре', 'Без визы'], 'tradeoff': 'Море далеко', 'districts': []},
    {'id': 'batumi', 'name': 'Батуми', 'country': 'Грузия', 'kind': 'sea', 'timezone': 'Asia/Tbilisi',
     'character': 'море, бульвар и субтропики', 'traits': ['sea', 'city'],
     'airport': {'code': 'BUS', 'name': 'аэропорт Батуми', 'lat': 41.6103, 'lon': 41.5997},
     'center': {'name': 'Батумский бульвар', 'lat': 41.6510, 'lon': 41.6360},
     'minutes': 170, 'fare': 28000, 'index': 0.75, 'resort': False, 'image': 'design-v2/u0.jpg',
     'why': ['Море и город вместе'], 'tradeoff': 'Осенью дожди', 'districts': []},
    {'id': 'irkutsk', 'name': 'Иркутск', 'country': 'Россия', 'kind': 'nature', 'timezone': 'Asia/Irkutsk',
     'character': 'ворота Байкала', 'traits': ['nature', 'city'],
     'airport': {'code': 'IKT', 'name': 'аэропорт Иркутска', 'lat': 52.2680, 'lon': 104.3889},
     'center': {'name': 'центр Иркутска', 'lat': 52.2870, 'lon': 104.2810},
     'minutes': 340, 'fare': 30000, 'index': 0.75, 'resort': False, 'image': 'design-v2/u6.jpg', 'pets_ok': True,
     'why': ['До Байкала около часа', 'Прозрачный лёд в феврале–марте'], 'tradeoff': 'Перелёт почти 6 часов', 'districts': []},
    {'id': 'gorno', 'name': 'Горно-Алтайск', 'country': 'Россия', 'kind': 'nature', 'timezone': 'Asia/Barnaul',
     'character': 'ворота Алтая', 'traits': ['nature', 'mountains'],
     'airport': {'code': 'RGK', 'name': 'аэропорт Горно-Алтайска', 'lat': 51.9667, 'lon': 85.8333},
     'center': {'name': 'центр Горно-Алтайска', 'lat': 51.9606, 'lon': 85.9189},
     'minutes': 270, 'fare': 28000, 'index': 0.7, 'resort': False, 'image': 'design-v2/u6.jpg', 'pets_ok': True,
     'why': ['Горы и реки', 'Без толп'], 'tradeoff': 'Мало отелей высокого уровня', 'districts': []},
    {'id': 'minvody', 'name': 'Минеральные Воды', 'country': 'Россия', 'kind': 'nature', 'timezone': 'Europe/Moscow',
     'character': 'Кавказские Минеральные Воды', 'traits': ['nature', 'mountains'],
     'airport': {'code': 'MRV', 'name': 'аэропорт Минеральных Вод', 'lat': 44.2251, 'lon': 43.0819},
     'center': {'name': 'центр Минеральных Вод', 'lat': 44.2103, 'lon': 43.1353},
     'minutes': 135, 'fare': 14000, 'index': 0.7, 'resort': False, 'image': 'design-v2/u6.jpg', 'pets_ok': True,
     'why': ['Кисловодск и Пятигорск рядом'], 'tradeoff': 'В данных один отель', 'districts': []},
    {'id': 'novosibirsk', 'name': 'Новосибирск', 'country': 'Россия', 'kind': 'city', 'timezone': 'Asia/Novosibirsk',
     'character': 'столица Сибири, оперный театр', 'traits': ['city', 'culture', 'business'],
     'airport': {'code': 'OVB', 'name': 'аэропорт Толмачёво', 'lat': 55.0126, 'lon': 82.6507},
     'center': {'name': 'площадь Ленина', 'lat': 55.0302, 'lon': 82.9204},
     'minutes': 250, 'fare': 24000, 'index': 0.75, 'resort': False, 'image': 'design-v2/u6.jpg', 'pets_ok': True,
     'why': ['Оперный театр', 'Академгородок'], 'tradeoff': 'Холодно с ноября', 'districts': []},
]

ALIASES = {
    'эль-гун': 'el_gouna', 'эль гун': 'el_gouna', 'эльгун': 'el_gouna', 'el gouna': 'el_gouna',
    'марса-алам': 'marsa_alam', 'марса алам': 'marsa_alam', 'марса': 'marsa_alam', 'marsa alam': 'marsa_alam',
    'рас-эль-хайм': 'ras_al_khaimah', 'рас эль хайм': 'ras_al_khaimah', 'рас-аль-хайм': 'ras_al_khaimah', 'рас аль хайм': 'ras_al_khaimah', 'рас-аль хайм': 'ras_al_khaimah', 'ras al khaimah': 'ras_al_khaimah',
    'хургад': 'hurghada', 'hurghada': 'hurghada', 'шарм': 'sharm', 'дуба': 'dubai', 'dubai': 'dubai',
    'пхукет': 'phuket', 'нячанг': 'nhatrang', 'мальдив': 'maldives',
    'сочи': 'sochi', 'адлер': 'sochi', 'сириус': 'sochi', 'sochi': 'sochi',
    'казан': 'kazan', 'kazan': 'kazan', 'калининград': 'kaliningrad', 'питер': 'petersburg', 'петербург': 'petersburg',
    'стамбул': 'istanbul', 'тбилиси': 'tbilisi', 'ереван': 'yerevan', 'батуми': 'batumi',
    'иркутск': 'irkutsk', 'байкал': 'irkutsk', 'горно-алтайск': 'gorno', 'алтай': 'gorno',
    'минеральные воды': 'minvody', 'минвод': 'minvody', 'новосибирск': 'novosibirsk',
}
COUNTRIES = {'турци': 'Турция', 'египет': 'Египет', 'египт': 'Египет', 'оаэ': 'ОАЭ', 'эмират': 'ОАЭ', 'грузи': 'Грузия', 'армени': 'Армения',
             'таиланд': 'Таиланд', 'тайланд': 'Таиланд', 'вьетнам': 'Вьетнам', 'по росси': 'Россия', 'в росси': 'Россия'}
# Places people ask about that are not in the demo data (answer honestly, offer similar); names follow «Поездку …».
UNKNOWN_PLACES = {
    'бали': ('на Бали', 'sea'), 'гоа': ('на Гоа', 'sea'), 'кипр': ('на Кипр', 'sea'), 'шри-ланк': ('на Шри-Ланку', 'sea'),
    'занзибар': ('на Занзибар', 'sea'), 'сейшел': ('на Сейшелы', 'sea'), 'доминикан': ('в Доминикану', 'sea'),
    'куба': ('на Кубу', 'sea'), 'мексик': ('в Мексику', 'sea'), 'тенериф': ('на Тенерифе', 'sea'),
    'париж': ('в Париж', 'city'), 'рим': ('в Рим', 'city'), 'барселон': ('в Барселону', 'city'), 'прага': ('в Прагу', 'city'),
    'лондон': ('в Лондон', 'city'), 'токио': ('в Токио', 'city'), 'нью-йорк': ('в Нью-Йорк', 'city'),
    'териберк': ('в Териберку', 'nature'), 'хибин': ('в Хибины', 'nature'), 'кировск': ('в Кировск', 'nature'),
    'шерегеш': ('в Шерегеш', 'nature'), 'плес': ('в Плёс', 'nature'), 'зеленоградск': ('в Зеленоградск', 'sea'),
    'кисловодск': ('в Кисловодск', 'nature'), 'архыз': ('в Архыз', 'nature'), 'листвянк': ('в Листвянку', 'nature'),
    'анталь': ('в Анталью', 'sea'), 'сияни': ('в Териберку или Хибины за северным сиянием', 'nature'),
    'горнолыж': ('в горы на лыжах', 'nature'), 'на лыжах': ('в горы на лыжах', 'nature'), 'кататься на лыж': ('в горы на лыжах', 'nature'),
}

DEST = {d['id']: d for d in DESTINATIONS}


def find_destination(text):
    """Return a destination id mentioned in text, ignoring the origin ("из Москвы")."""
    t = text.casefold().replace('ё', 'е')
    for alias, did in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(r'(?<![а-яa-z])' + re.escape(alias), t):
            if not t[max(0, m.start() - 3):m.start()].endswith('из '):
                return did
    return None


def find_all_destinations(text):
    """Every catalogue destination named in text, in order of appearance (origin excluded)."""
    t = text.casefold().replace('ё', 'е')
    found = {}
    for alias, did in ALIASES.items():
        for m in re.finditer(r'(?<![а-яa-z])' + re.escape(alias), t):
            if not t[max(0, m.start() - 3):m.start()].endswith('из '):
                found[did] = min(found.get(did, m.start()), m.start())
    return sorted(found, key=found.get)


def find_countries(text):
    t = text.casefold().replace('ё', 'е')
    return list(dict.fromkeys(c for a, c in COUNTRIES.items() if re.search(r'(?<![а-яa-z])' + re.escape(a), t)))


def find_unknown_place(text):
    t = text.casefold().replace('ё', 'е')
    for alias, (name, kind) in UNKNOWN_PLACES.items():
        if re.search(r'(?<![а-яa-z])' + re.escape(alias), t):
            return {'name': name, 'kind': kind}
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def climate():
    data = json.loads((DATASETS / 'region_climate.json').read_text(encoding='utf-8'))
    return data


def month_climate(did, month):
    rows = climate()['regions'].get(did, [])
    return next((m for m in rows if m['month'] == month), None)


def _fact(label, value, source, kind='osm'):
    return {'label': label, 'value': value, 'source': source, 'kind': kind}


def _tag_flag(tags, *keys):
    for key in keys:
        if key in tags:
            v = str(tags[key]).casefold()
            if v in ('yes', 'leashed', 'outside', 'only', 'customers', 'wlan', 'true'):
                return True
            if v in ('no', 'false'):
                return False
    return None


def display_name(row):
    """OSM name as a Russian reader can read it: name:ru, else name:en when the local name is not Latin/Cyrillic."""
    tags = row.get('tags', {})
    name = tags.get('name:ru') or row['name']
    if not re.search(r'[A-Za-zА-Яа-яЁё]', name):
        name = tags.get('name:en') or tags.get('int_name') or name
    return name


OSM_EVIDENCE = [  # (wish, OSM tags, yes, no, fact label)
    ('pool', ('swimming_pool', 'leisure:swimming_pool'), 'Бассейн есть', 'Бассейна нет', 'Бассейн'),
    ('pets', ('pets', 'dog'), 'С животными можно', 'С животными нельзя', 'Питомцы'),
    ('accessible', ('wheelchair',), 'Доступно для коляски', 'Не приспособлено для коляски', 'Доступность'),
    ('wifi', ('internet_access',), 'Есть интернет', 'Интернета нет', 'Интернет'),
]


def _osm_stars(tags):
    stars = tags.get('stars')
    return int(stars) if str(stars).isdigit() and 1 <= int(stars) <= 5 else None


def _osm_website(tags):
    website = tags.get('website') or tags.get('contact:website')
    return 'https://' + website if website and not website.startswith('http') else website


def _osm_evidence(tags, url):
    """Yes/no answers OSM gives explicitly; a missing tag stays unknown."""
    evidence, facts = {}, []
    for key, osm_keys, yes, no, label in OSM_EVIDENCE:
        flag = _tag_flag(tags, *osm_keys)
        if flag is not None:
            evidence[key] = {'value': flag, 'text': yes if flag else no, 'source': url, 'source_name': 'OpenStreetMap'}
            facts.append(_fact(label, yes if flag else no, url))
    return evidence, facts


def _osm_hotel(row, did, retrieved):
    tags = row.get('tags', {})
    row = {**row, 'name': display_name(row)}
    url = row['source_url']
    stars = _osm_stars(tags)
    facts = [_fact('Объект в OpenStreetMap', row['name'], url)]
    if stars:
        facts.append(_fact('Звёзды', f'{stars}★ по данным OpenStreetMap', url))
    evidence, more = _osm_evidence(tags, url)
    district = (row.get('nominatim_district') or {}).get('name')
    return {'id': row['id'], 'name': row['name'], 'destination': did, 'stars': stars,
            'lat': row.get('latitude'), 'lon': row.get('longitude'), 'osm_district': district, 'area': None,
            'website': _osm_website(tags), 'source_url': url, 'retrieved_at': retrieved, 'facts': facts + more,
            'evidence': evidence, 'not_for': None, 'curated': False}


CURATED_EVIDENCE = [('pool', 'pool', 'Бассейн'), ('pets', 'pets', 'Питом'), ('family', 'kids', 'Для детей')]  # (hotel field, wish, fact label part)


def _curated_evidence(h):
    """Each yes/no from the hotel's own site, quoted from the matching fact."""
    ev = {}
    for key, wish, label in CURATED_EVIDENCE:
        if h.get(key) is not None:
            fact = next((f for f in h['facts'] if label in f['label']), h['facts'][0])
            ev[wish] = {'value': h[key], 'text': fact['value'], 'source': fact['source'], 'source_name': 'сайт отеля'}
    return ev


def _seasonal(h):
    """A kids' club that is closed out of season contradicts «для детей» in those months."""
    return [{'wish': 'kids', 'text': f['value'] + ' — в ноябре–апреле не работает', 'source': f['source'], 'months': [10, 11, 12, 1, 2, 3, 4, 5]}
            for f in h['facts'] if 'Сезонность' in f['label']]


def _curated_hotel(h, row):
    """A hand-checked Sochi hotel; position and stars come from its OSM twin when there is one."""
    osm = row or {}
    stars = osm.get('tags', {}).get('stars', '')
    return {'id': h['id'], 'name': h['name'], 'destination': 'sochi',
            'stars': int(stars) if str(stars).isdigit() else None,
            'lat': osm.get('latitude'), 'lon': osm.get('longitude'),
            'osm_district': None, 'area': h['area'], 'website': h['website'],
            'source_url': osm.get('source_url') or h['website'], 'retrieved_at': '2026-10-25',
            'facts': [{'label': f['label'], 'value': f['value'], 'source': f['source'], 'kind': 'site'} for f in h['facts']],
            'evidence': _curated_evidence(h), 'contradictions': _seasonal(h), 'not_for': h.get('tradeoff'), 'curated': True}


def _sochi_hotels():
    from backend.infrastructure.hotel_provider import HOTELS
    from backend.infrastructure.open_data import LINKS, snapshot
    snap = snapshot()
    by_id = {r['id']: r for r in snap['hotels']}
    result = [_curated_hotel(h, by_id.get(LINKS.get(h['id']))) for h in deepcopy(HOTELS)]
    curated_osm = set(LINKS.values())
    seen = {h['name'].casefold() for h in result}
    for row in snap['hotels']:
        if row['id'] in curated_osm or row['name'].casefold() in seen:
            continue
        seen.add(row['name'].casefold())
        result.append(_osm_hotel({**row, 'source_url': row['source_url']}, 'sochi', snap['retrieved_at'][:10]))
    return result


@lru_cache(maxsize=1)
def _all_hotels():
    regions = json.loads((DATASETS / 'regions.json').read_text(encoding='utf-8'))['regions']
    out = {}
    for r in regions:
        if r['id'] in DEST:
            seen = set()
            rows = []
            for row in r['hotels']:
                h = _osm_hotel(row, r['id'], r.get('retrieved_at', '')[:10])
                # A name a Russian reader cannot read (no Latin/Cyrillic and no name:en) is left out of the demo.
                if h['name'].casefold() in seen or not re.search(r'[A-Za-zА-Яа-яЁё]', h['name']):
                    continue
                seen.add(h['name'].casefold())
                rows.append(h)
            out[r['id']] = rows
    out['sochi'] = _sochi_hotels()
    for did, rows in out.items():
        dest = DEST[did]
        for h in rows:
            h['district'] = assign_district(dest, h)
    return out


def assign_district(dest, hotel):
    districts = dest.get('districts') or []
    if not districts:
        return None
    for d in districts:
        if hotel.get('osm_district') and hotel['osm_district'] in d.get('osm', []):
            return d['id']
        if hotel.get('area') and any(a in hotel['area'] for a in d.get('areas', [])):
            return d['id']
    if hotel.get('lat') is None:
        return None
    return min(districts, key=lambda d: haversine_km(hotel['lat'], hotel['lon'], d['lat'], d['lon']))['id']


def hotels(did):
    return deepcopy(_all_hotels().get(did, []))


def hotel(hid):
    for rows in _all_hotels().values():
        for h in rows:
            if h['id'] == hid:
                return deepcopy(h)
    return None


def catalogue_counts():
    return {d['id']: len(_all_hotels().get(d['id'], [])) for d in DESTINATIONS}

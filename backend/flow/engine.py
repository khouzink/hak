"""Deterministic selection: destinations → districts → three hotels → trip.

Facts (OSM, hotel sites, climate) are kept apart from the demo model (fares, rates,
rooms, transfers). Every rule here runs without an LLM and without network.
"""
import math
import statistics
import time as _time
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256
from zoneinfo import ZoneInfo

from backend.flow import data
from backend.flow.model import WISHES

MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
STAR_BASE = {5: 15000, 4: 10000, 3: 7000, 2: 5000, 1: 4000, None: 8000}
ROOMS = [
    {'id': 'standard', 'name': 'Стандартный номер', 'capacity': 3, 'adults': 2, 'factor': 1.0},
    {'id': 'family', 'name': 'Семейный номер', 'capacity': 4, 'adults': 3, 'factor': 1.35},
    {'id': 'superior', 'name': 'Улучшенный номер', 'capacity': 3, 'adults': 2, 'factor': 1.5},
]
MEALS = {'breakfast': 900, 'all_inclusive': 3200}
RATES = [
    {'id': 'nr', 'name': 'Без питания', 'meal': None, 'refundable': False, 'factor': 0.9},
    {'id': 'bb', 'name': 'Завтрак', 'meal': 'breakfast', 'refundable': True, 'factor': 1.0},
    {'id': 'ai', 'name': 'Всё включено', 'meal': 'all_inclusive', 'refundable': True, 'factor': 1.0},
]
OUT_SLOTS = {'morning': ('09:40', 1.0, 'утренний'), 'day': ('13:20', 0.95, 'дневной'), 'evening': ('20:30', 0.85, 'вечерний'), 'night': ('01:30', 0.8, 'ночной')}
BACK_SLOTS = {'morning': ('08:00', 0.9, 'утренний'), 'day': ('17:20', 1.0, 'дневной'), 'evening': ('21:30', 0.92, 'вечерний'), 'night': ('02:30', 0.8, 'ночной')}
STATUS_SCORE = {'yes': 1.0, 'tariff': 0.8, 'distance': 0.8, 'district': 0.6, 'unknown': 0.0, 'far': -0.4, 'no': -1.0}
MUST_OK = {'yes', 'tariff', 'distance'}
LOCATION_WISHES = {'quiet', 'beach'}


def money(v):
    return f'{round(v):,}'.replace(',', ' ') + ' ₽'


def fmt_day(d):
    return f'{d.day} {MONTHS[d.month - 1]}'


def fmt_range(a, b):
    return f'{a.day}–{b.day} {MONTHS[a.month - 1]}' if a.month == b.month else f'{fmt_day(a)} – {fmt_day(b)}'


def fmt_minutes(m):
    m = round(m)
    return f'{m // 60} ч {m % 60:02d} мин' if m >= 60 else f'{m} мин'


def fmt_party(spec):
    adults = {1: '1 взрослый'}.get(spec.adults, f'{spec.adults} взрослых')
    kids = [f'ребёнок {a} {years(a)}' for a in spec.children_ages]
    return ' + '.join([adults] + kids)


def years(a):
    return 'год' if a % 10 == 1 and a % 100 != 11 else 'года' if a % 10 in (2, 3, 4) and a % 100 not in (12, 13, 14) else 'лет'


def _variation(key, low=0.85, high=1.25):
    h = int(sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return low + (high - low) * h


HOTEL_IMAGES = ['design-v2/u1.jpg', 'design-v2/u13.jpg', 'design-v2/u16.jpg', 'design-v2/u6.jpg', 'design-v2/u3.jpg']


def hotel_image(hid):
    """Illustration only (no real hotel photos in open data); labelled as such in the UI."""
    return '/assets/' + HOTEL_IMAGES[int(sha256(hid.encode()).hexdigest()[:4], 16) % len(HOTEL_IMAGES)]


# ---------- model prices ----------

def base_night(hotel, dest):
    return round(STAR_BASE.get(hotel.get('stars')) * dest['index'] * _variation(hotel['id']), -2)


def room_options(spec):
    out = []
    for r in ROOMS:
        rooms = max(math.ceil(spec.people / r['capacity']), math.ceil(spec.adults / r['adults']))
        out.append({**r, 'rooms': rooms})
    return out


def rate_options(dest):
    return [r for r in RATES if r['id'] != 'ai' or dest.get('resort')]


def _night_factor(d, hotel):
    """Demo seasonality of one night: weekends, winter holidays and a small per-date swing."""
    weekend = 1.1 if d.weekday() in (4, 5) else 1
    holidays = 1.4 if (d.month, d.day) >= (12, 28) or (d.month, d.day) <= (1, 8) else 1
    return weekend * holidays * _variation(hotel['id'] + d.isoformat(), 0.96, 1.06)


def _ev_from_district(district, trait, text, otherwise):
    if district and trait in district['traits']:
        return {'status': 'district', 'text': text.format(name=district['name'], summary=district['summary']), 'source': None, 'source_name': 'описание района'}
    return otherwise


def _unknown(text):
    return {'status': 'unknown', 'text': text, 'source': None}


def _tariff(text):
    return {'status': 'tariff', 'text': text, 'source': None, 'source_name': 'демо-тариф'}


def _ev_kids(spec, hotel, dest, district):
    return _ev_from_district(district, 'kids', 'Район «{name}» спокойный и подходит детям; детский клуб у отеля не подтверждён',
                             _unknown('Детский клуб и детское меню в открытых данных не указаны'))


def _ev_all_inclusive(spec, hotel, dest, district):
    return _tariff('Есть тариф «всё включено» (демо-тариф)') if dest.get('resort') else _unknown('Тариф «всё включено» здесь не предлагаем')


def _ev_quiet(spec, hotel, dest, district):
    noisy = {'status': 'no', 'text': 'Район «{name}»: {summary}'.format(**district), 'source': None, 'source_name': 'описание района'} \
        if district and 'nightlife' in district['traits'] else _unknown('Шумоизоляция и тишина номера не подтверждены')
    return _ev_from_district(district, 'quiet', 'Район «{name}»: {summary}', noisy)


def _ev_beach(spec, hotel, dest, district):
    if dest['kind'] != 'sea':
        return {'status': 'no', 'text': 'Направление не у моря', 'source': None}
    return _ev_from_district(district, 'beach', 'Район «{name}» у воды', _unknown('Расстояние до пляжа в открытых данных не указано'))


def _near(row, limit, source, source_name, key='km'):
    return {'status': 'distance' if row[key] <= limit else 'far', 'text': f'{row["name"]}: {row["label"]}', 'source': source, 'source_name': source_name}


def _ev_office(spec, hotel, dest, district):
    row = next((x for x in distances(spec, hotel, dest) if x['kind'] == 'target'), None)
    return _near(row, 3, hotel['source_url'], 'координаты OpenStreetMap') if row else _unknown('Адрес офиса не указан — скажи в чате «офис на …»')


def _ev_culture(spec, hotel, dest, district):
    d = {x['kind']: x for x in distances(spec, hotel, dest)}
    if 'culture' in d:
        return _near(d['culture'], 15, d['culture'].get('source'), 'маршрут OSRM', 'minutes')
    if 'center' in d and dest['kind'] == 'city':
        return _near(d['center'], 1.5, hotel['source_url'], 'координаты OpenStreetMap')
    return _unknown('Пешие маршруты до музеев не посчитаны')


EVIDENCE = {
    'kids': _ev_kids, 'all_inclusive': _ev_all_inclusive, 'quiet': _ev_quiet, 'beach': _ev_beach, 'office': _ev_office, 'culture': _ev_culture,
    'breakfast': lambda *a: _tariff('Есть тариф с завтраком (демо-тариф)'),
    'sea_view': lambda *a: _unknown('Вид из номера в открытых данных не указан — уточним у отеля'),
    'accessible': lambda *a: _unknown('Доступность для коляски и лифты в открытых данных не указаны — уточним у отеля'),
    'pets': lambda *a: _unknown('Размещение с животными в открытых данных не указано — уточним у отеля'),
    'pool': lambda *a: _unknown('Бассейн в открытых данных не указан'),
    'wifi': lambda *a: _unknown('Интернет в открытых данных не указан — уточним у отеля'),
}


def _violation(spec, wish, level, status):
    """Hard: must without a source. Soft: want that the data contradicts (not for remembered wishes)."""
    if level == 'must' and not (status in MUST_OK or (wish in LOCATION_WISHES and status == 'district')):
        return {'wish': wish, 'reason': 'не подтверждено источником' if status != 'no' else 'противоречит'}
    if level == 'want' and status == 'no' and wish not in spec.remembered:
        return {'wish': wish, 'reason': 'противоречит желанию', 'soft': True}
    return None


def _violations(spec, hotel, dest, rows):
    found = [_violation(spec, w, level, rows.get(w, {}).get('status')) for w, level in spec.priorities.items()]
    found += [{'wish': c['wish'], 'reason': c['text'], 'soft': True} for c in hotel.get('contradictions', [])
              if spec.priorities.get(c['wish']) in ('must', 'want') and spec.check_in.month in c['months']]
    if spec.pets and not dest.get('pets_ok'):
        found.append({'wish': 'pets', 'reason': 'перевозка животного на этом направлении не проверена'})
    return [v for v in found if v]


def _location_score(spec, hotel, dest):
    """Business trips and cities: closer to the target point (or the centre) scores up to 2."""
    if spec.purpose != 'business' and dest['kind'] != 'city':
        return 0.0
    point = 'target' if spec.target_point else 'center'
    target = next((x for x in distances(spec, hotel, dest) if x['kind'] == point), None)
    return max(0.0, 2 - target['km'] / 2) if target else 0.0


def _ranked(source):
    return sorted(source, key=lambda a: (-a['score'], a['price']['total'], a['hotel']['id']))


def _best_slot(spec, dest, pool, budget):
    in_budget = [a for a in _ranked(pool) if a['price']['total'] <= budget]
    if in_budget:
        return in_budget[0], 'Лучший в бюджете'
    best = sorted(pool, key=lambda a: (a['price']['total'], -a['score']))[0]
    return best, 'Ближе всего к бюджету' if hotel_budget(spec, dest) else 'Лучший вариант'


def _cheaper(ranked, best):
    return next((a for a in ranked if a['price']['total'] <= best['price']['total'] * 0.92), None)


def _better(ranked, best):
    pricier = [a for a in ranked if a['price']['total'] > best['price']['total'] and quality(a) > quality(best)]
    return max(pricier, key=lambda a: (quality(a), -a['price']['total'])) if pricier else None


def _wish_changes(spec, base, other):
    gained, lost = [], []
    for w, level in spec.priorities.items():
        a, b = base['rows'].get(w), other['rows'].get(w)
        if level == 'skip' or not a or not b:
            continue
        sa, sb = STATUS_SCORE[a['status']], STATUS_SCORE[b['status']]
        if sb > sa:
            gained.append(WISHES[w].lower() + (' подтверждено' if b['status'] == 'yes' else ''))
        elif sb < sa:
            lost.append('не подтверждено: ' + WISHES[w].lower() if b['status'] in ('unknown', 'no') else WISHES[w].lower() + ' слабее')
    return gained, lost


def _star_change(base, other):
    """(gained, lost) wording about stars, or (None, None) when nothing to say."""
    sb, so = base['hotel'].get('stars'), other['hotel'].get('stars')
    if sb and so and so != sb:
        return (f'{so}★ вместо {sb}★', None) if so > sb else (None, f'{so}★ вместо {sb}★')
    if so and not sb:
        return f'подтверждено {so}★', None
    return (None, 'звёздность не подтверждена') if sb and not so else (None, None)


def _distance_change(spec, dest, base, other):
    point = 'target' if spec.target_point else 'center'
    tb, to = (next((x for x in distances(spec, a['hotel'], dest) if x['kind'] == point), None) for a in (base, other))
    if not tb or not to or abs(tb['km'] - to['km']) < 0.5:
        return None, None
    text = f'{"ближе" if to["km"] < tb["km"] else "дальше"} до точки «{to["name"]}» ({to["km"]:.1f} км)'.replace('.', ',')
    return (text, None) if to['km'] < tb['km'] else (None, text)


def _top_facts(spec, a):
    pr = spec.priorities
    order = sorted(a['rows'], key=lambda w: (pr.get(w) != 'must', -STATUS_SCORE[a['rows'][w]['status']]))
    top = [{'wish': w, 'text': a['rows'][w]['text'], 'status': a['rows'][w]['status']} for w in order
           if a['rows'][w]['status'] in ('yes', 'distance', 'district', 'tariff', 'far')]
    return top or [{'wish': None, 'text': f['label'] + ': ' + f['value'], 'status': 'yes'} for f in a['hotel']['facts'][1:3]]


def _checkin_note(spec, hotel, dest):
    issue = next((c for c in timeline(spec, hotel, dest)['checks'] if c['code'] in ('arrival', 'night') and c['status'] != 'ok'), None)
    return (True, 'Заселение сходится ✓') if not issue else (False, '⚠ ' + issue['short'])


def _budget_line(spec, dest, a):
    budget = hotel_budget(spec, dest)
    if not budget:
        return None
    rest = budget - a['price']['total']
    return {'text': f'В бюджете: остаётся {money(rest)}' if rest >= 0 else f'Выше бюджета на {money(-rest)}', 'source': None, 'source_name': 'расчёт по демо-ценам'}


def price(spec, hotel, dest, room_id=None, rate_id=None):
    """Hotel price for all nights and all guests (DEMO model)."""
    rooms = room_options(spec)
    room = next((r for r in rooms if r['id'] == room_id), None) or min(rooms, key=lambda r: (r['rooms'] * r['factor'], r['factor']))
    rate = next((r for r in rate_options(dest) if r['id'] == rate_id), None) or default_rate(spec, dest)
    night = base_night(hotel, dest) * room['factor'] * rate['factor'] * room['rooms']
    eaters = spec.adults + sum(0.5 for a in spec.children_ages if a >= 3)
    meal = MEALS.get(rate['meal'], 0) * dest['index'] * eaters
    nightly = [night * _night_factor(spec.check_in + timedelta(days=i), hotel) for i in range(spec.nights)]
    free_until = (spec.check_in - timedelta(days=7)).isoformat() if rate['refundable'] else None
    return {'room': room, 'rate': rate, 'night': round(sum(nightly) / len(nightly) + meal, -2), 'total': round(sum(nightly) + meal * spec.nights, -2),
            'nights': spec.nights, 'free_until': free_until}


def default_rate(spec, dest):
    pr = spec.priorities
    options = {r['id']: r for r in rate_options(dest)}
    if pr.get('all_inclusive') in ('must', 'want') and 'ai' in options:
        return options['ai']
    if spec.rate_id in options:
        return options[spec.rate_id]
    return options['bb']


def road(spec, dest):
    if dest['name'] == spec.origin:
        return {'total': 0, 'per_adult': 0, 'mode': 'none'}
    child = sum(round(dest['fare'] * (0.1 if a < 2 else 0.7)) for a in spec.children_ages)
    # Demo fare: half of the round trip per leg, cheaper at inconvenient hours.
    factor = (OUT_SLOTS[spec.out_slot][1] + BACK_SLOTS[spec.back_slot][1]) / 2
    return {'total': round((dest['fare'] * spec.adults + child) * factor, -2), 'per_adult': dest['fare'], 'mode': 'air'}


def transfer(spec, hotel, dest):
    a = dest['airport']
    lat, lon = (hotel['lat'], hotel['lon']) if hotel.get('lat') is not None else (dest['center']['lat'], dest['center']['lon'])
    km = data.haversine_km(a['lat'], a['lon'], lat, lon)
    cars = math.ceil(spec.people / 4)
    return {'km': round(km, 1), 'minutes': max(10, round(km * 1.3 / 70 * 60)), 'price': round((900 + 40 * km) * dest['index'] * cars, -2)}


# ---------- evidence ----------

def district_of(dest, hotel):
    return next((d for d in dest.get('districts', []) if d['id'] == hotel.get('district')), None)


def evidence(spec, hotel, dest, wish):
    """Status of one wish for one hotel: yes / no / unknown / tariff / district / distance / far."""
    e = hotel.get('evidence', {}).get(wish)
    if e:
        return {'status': 'yes' if e['value'] else 'no', 'text': e['text'], 'source': e['source'], 'source_name': e['source_name']}
    rule = EVIDENCE.get(wish, lambda *a: _unknown('В открытых данных не указано'))
    return rule(spec, hotel, dest, district_of(dest, hotel))


def distances(spec, hotel, dest):
    if hotel.get('lat') is None:
        return []
    out = []

    def straight(kind, name, lat, lon, note=None):
        km = data.haversine_km(hotel['lat'], hotel['lon'], lat, lon)
        walk = km * 1.25 / 4.5 * 60
        label = (f'{round(km * 1000, -1):.0f} м' if km < 1 else f'{km:.1f} км'.replace('.', ',')) + ' по прямой'
        if km <= 2.5:
            label += f' · ≈ {fmt_minutes(walk)} пешком'
        else:
            label += f' · ≈ {fmt_minutes(km * 1.3 / 40 * 60 + 5)} на машине'
        out.append({'kind': kind, 'name': name, 'km': round(km, 2), 'minutes': round(walk), 'label': label, 'method': 'straight', 'note': note})

    straight('center', dest['center']['name'], dest['center']['lat'], dest['center']['lon'])
    straight('airport', dest['airport']['name'], dest['airport']['lat'], dest['airport']['lon'])
    for p in dest.get('points', []):
        if p['id'] == spec.target_point:
            straight('target', p['name'], p['lat'], p['lon'], p.get('note'))
    if dest['id'] == 'sochi':
        from backend.infrastructure.poi_matrix import hotel_routes
        routes = hotel_routes(hotel['id'])
        if routes:
            r = routes[0]
            out.append({'kind': 'culture', 'name': r['poi_name'], 'km': round(r['distance_m'] / 1000, 2), 'minutes': round(r['duration_s'] / 60),
                        'label': f'{fmt_minutes(r["duration_s"] / 60)} пешком по маршруту', 'method': 'route', 'source': 'https://www.openstreetmap.org/' + r['poi_id']})
    return out


# ---------- ranking ----------

def assess(spec, hotel, dest):
    rows = {w: evidence(spec, hotel, dest, w) for w, level in spec.priorities.items() if level != 'skip'}
    match = sum(STATUS_SCORE[rows[w]['status']] * (2 if spec.priorities[w] == 'must' else 1) for w in rows)
    return {'hotel': hotel, 'price': price(spec, hotel, dest), 'rows': rows, 'violations': _violations(spec, hotel, dest, rows),
            'score_parts': {'match': match, 'stars': (hotel.get('stars') or 3) - 3, 'location': _location_score(spec, hotel, dest),
                            'data': min(len(hotel.get('facts', [])), 5) * 0.15}}


def score(a, median):
    price_weight = 3.0 if a['spec_cheap'] else 1.5
    rel = (median - a['price']['total']) / median if median else 0
    return round(a['score_parts']['match'] * 2 + a['score_parts']['stars'] * 0.8 + a['score_parts']['location'] + a['score_parts']['data'] + rel * price_weight * 2, 3)


def candidates(spec, dest, district=None):
    pool = data.hotels(dest['id'])
    assessed = [assess(spec, h, dest) for h in pool]
    ok = [a for a in assessed if not a['violations']]
    median = statistics.median([a['price']['total'] for a in ok or assessed] or [1])
    for a in assessed:
        a['spec_cheap'] = spec.cheap
        a['score'] = score(a, median)
    chosen = [a for a in ok if not district or a['hotel'].get('district') == district]
    if spec.nightly_budget:
        chosen = [a for a in chosen if a['price']['night'] <= spec.nightly_budget * a['price']['room']['rooms'] + 1]
    return {'all': assessed, 'ok': ok, 'pool': chosen, 'median': median, 'scanned': len(pool)}


def hotel_budget(spec, dest):
    if spec.nightly_budget:
        return spec.nightly_budget * spec.nights
    if spec.budget:
        return max(0, spec.budget - road(spec, dest)['total'] - 2 * 2500)
    return None


def quality(a):
    q = a['score_parts']
    return round(q['match'] * 2 + q['stars'] * 0.8 + q['location'] + q['data'], 3)


def _fill_slots(pool, wider, best):
    """Cheaper and better from the chosen district first, then from the whole destination."""
    found = {'best': best}
    for source in (pool, wider or []):
        ranked = _ranked(source)
        if not found.get('cheaper'):
            found['cheaper'] = _cheaper(ranked, best)
        if not found.get('better'):
            found['better'] = _better(ranked, best)
    return found


def pick_three(spec, dest, pool, median, wider=None):
    """Best within budget, a noticeably cheaper one, and a pricier one that wins on what matters.

    `wider` (the whole destination) is used only to fill a missing slot; the card then
    names its other district in the trade-off line.
    """
    if not pool:
        return []
    budget = hotel_budget(spec, dest) or median
    best, label = _best_slot(spec, dest, pool, budget)
    found = _fill_slots(pool, wider, best)
    slots = [('cheaper', 'Дешевле'), ('best', label), ('better', 'Дороже, но лучше')]
    out = [(code, title, found[code]) for code, title in slots if found.get(code)]
    # Nothing strictly cheaper or better: the next best within the same limits instead of padding with misfits.
    used = {id(a) for _, _, a in out}
    limit = max(budget, best['price']['total'])
    out += [('other', 'Ещё вариант', a) for a in _ranked(pool) if id(a) not in used and a['price']['total'] <= limit][:3 - len(out)]
    return out


def _district_change(dest, base, other):
    db, do = district_of(dest, base['hotel']), district_of(dest, other['hotel'])
    return f'район {do["name"]}' if db and do and db['id'] != do['id'] else None


def tradeoff(spec, dest, base, other):
    """'За счёт чего': price difference and what is gained or lost vs the best option."""
    diff = other['price']['total'] - base['price']['total']
    gained, lost = _wish_changes(spec, base, other)
    for g, lo in (_star_change(base, other), _distance_change(spec, dest, base, other)):
        gained += [g] if g else []
        lost += [lo] if lo else []
    side = lost if diff < 0 else gained
    side += [moved for moved in [_district_change(dest, base, other)] if moved]
    parts = side or ['по важному для тебя то же самое']
    return f'{"−" if diff < 0 else "+"}{money(abs(diff))}: ' + ', '.join(parts[:2])


def card(spec, dest, a, slot=None, label=None):
    h = a['hotel']
    district = district_of(dest, h)
    ok, note = _checkin_note(spec, h, dest)
    why = why_lines(spec, dest, a)
    return {'id': h['id'], 'slot': slot, 'label': label, 'name': h['name'], 'stars': h.get('stars'), 'rating': None,
            'district': district['name'] if district else None, 'image': hotel_image(h['id']),
            'facts': _top_facts(spec, a)[:2], 'total': a['price']['total'], 'night': a['price']['night'], 'nights': spec.nights,
            'room': a['price']['room']['name'], 'rate': a['price']['rate']['name'], 'why': why[0] if why else None,
            'checkin_ok': ok, 'checkin_note': note, 'score': a['score'], 'source_url': h['source_url']}


def why_lines(spec, dest, a):
    pr = spec.priorities
    out = [{'text': a['rows'][w]['text'], 'source': a['rows'][w].get('source'), 'source_name': a['rows'][w].get('source_name')}
           for w in sorted(a['rows'], key=lambda w: pr.get(w) != 'must') if a['rows'][w]['status'] in ('yes', 'distance', 'district')]
    district = district_of(dest, a['hotel'])
    extra = []
    if district and not any(district['name'] in x['text'] for x in out):
        extra.append({'text': f'Район «{district["name"]}»: {district["summary"]}', 'source': None, 'source_name': 'описание района'})
    if a['hotel'].get('stars'):
        extra.append({'text': f'{a["hotel"]["stars"]}★ по данным OpenStreetMap', 'source': a['hotel']['source_url'], 'source_name': 'OpenStreetMap'})
    extra.append(_budget_line(spec, dest, a))
    return (out + [x for x in extra if x])[:3]


# ---------- trip timeline ----------

def _at(d, hhmm, tz):
    h, m = map(int, hhmm.split(':'))
    return datetime.combine(d, time(h, m), ZoneInfo(tz))


def _plus(dt, minutes):
    return (dt.astimezone(timezone.utc) + timedelta(minutes=minutes)).astimezone(dt.tzinfo)


def _in(dt, tz):
    return dt.astimezone(ZoneInfo(tz))


def _check(code, status, label, short, fixes=None):
    return {'code': code, 'status': status, 'label': label, 'short': short, 'fixes': fixes or []}


def _outbound(spec, dest):
    """Moscow departure and local arrival: from the user's arrival time or from the model slot."""
    otz, dtz, minutes = data.ORIGIN['timezone'], dest['timezone'], dest['minutes']
    if spec.arrival_time:
        arrival = _at(spec.check_in, spec.arrival_time, dtz)
        return _in(_plus(arrival, -minutes), otz), arrival, 'user'
    departure = _at(spec.check_in, OUT_SLOTS[spec.out_slot][0], otz)
    return departure, _in(_plus(departure, minutes), dtz), 'model'


def _checkin(spec, at_hotel, extras, half_night, dtz):
    """When the room is ours, and what the arrival check says about it."""
    standard_in = _at(at_hotel.date(), '14:00', dtz)
    if at_hotel.date() > spec.check_in:
        return at_hotel, _check('arrival', 'attention', f'В отеле в {at_hotel:%H:%M} {fmt_day(at_hotel.date())} — первая оплаченная ночь почти пропадает', f'заселение в {at_hotel:%H:%M}')
    if 'early_checkin' in extras:
        return at_hotel, _check('arrival', 'ok', f'Ранний заезд добавлен: заселение сразу, в {at_hotel:%H:%M} по местному', 'ранний заезд')
    if at_hotel > standard_in:
        late = at_hotel.hour >= 22 or at_hotel.hour < 5
        return at_hotel, _check('arrival', 'attention' if late else 'ok', f'В отеле в {at_hotel:%H:%M} по местному' + (' — поздний приезд, предупредим отель' if late else ', номер уже готов ✓'), f'приезд в {at_hotel:%H:%M}' if late else 'заселение сходится')
    wait = round((standard_in - at_hotel).total_seconds() / 60)
    if wait > 90:
        return standard_in, _check('arrival', 'attention', f'В отеле в {at_hotel:%H:%M}, заселение с 14:00 — ждать {fmt_minutes(wait)}', f'ждать заселения {fmt_minutes(wait)}',
                                   [{'extra': 'early_checkin', 'label': 'Ранний заезд', 'price': half_night}, {'extra': 'storage', 'label': 'Оставить багаж и гулять', 'price': 0}])
    return standard_in, _check('arrival', 'ok', f'В отеле в {at_hotel:%H:%M}, заселение с 14:00 ✓', 'заселение сходится')


def _homebound(spec, dest, transfer_minutes, extras, airport_buffer):
    """Return flight, home, pickup and check-out (moved earlier when the pickup comes first)."""
    dtz = dest['timezone']
    back = _at(spec.check_out, BACK_SLOTS[spec.back_slot][0], dtz)
    if spec.back_slot == 'night':
        back = _plus(back, 24 * 60)  # 02:30 after the last night
    home = _in(_plus(back, dest['minutes']), data.ORIGIN['timezone'])
    pickup = _plus(back, -airport_buffer - transfer_minutes)
    checkout = min(_at(spec.check_out, '14:00' if 'late_checkout' in extras else '12:00', dtz), pickup)
    return back, home, pickup, checkout


LATE_CHECKOUT = '14:00'
CHILD_SEAT_AGE = 12  # a seat or booster is needed in a car below this age


def leaves_before(pickup, day, hhmm):
    """Does the airport transfer leave before hh:mm on the check-out day (a night flight leaves after it)?"""
    h, m = map(int, hhmm.split(':'))
    return pickup < datetime.combine(day, time(h, m), pickup.tzinfo)


def _departure_check(checkout, pickup, extras, half_night):
    gap = round((pickup - checkout).total_seconds() / 60)
    before_late_end = leaves_before(pickup, checkout.date(), LATE_CHECKOUT)  # the transfer leaves before a late check-out would end
    if 'late_checkout' in extras and before_late_end:
        return _check('departure', 'attention', f'Поздний выезд до {LATE_CHECKOUT} не успеете использовать: трансфер в аэропорт в {pickup:%H:%M}',
                      'поздний выезд не нужен', [{'extra': 'storage', 'label': 'Камера хранения', 'price': 0}])
    if gap > 60 and not extras & {'storage', 'late_checkout'}:
        fixes = [{'extra': 'storage', 'label': 'Камера хранения', 'price': 0}]
        if not before_late_end:
            fixes.append({'extra': 'late_checkout', 'label': f'Поздний выезд до {LATE_CHECKOUT}', 'price': half_night})
        return _check('departure', 'attention', f'Выезд из номера в {checkout:%H:%M}, трансфер в {pickup:%H:%M} — между ними {fmt_minutes(gap)}',
                      f'{fmt_minutes(gap)} между выездом и трансфером', fixes)
    return _check('departure', 'ok', f'Выезд в {checkout:%H:%M}, трансфер в {pickup:%H:%M} ✓', 'выезд сходится')


def _road_checks(spec, dest, points):
    """Night legs of the road, a flight longer than asked, an animal on board."""
    kids = spec.children_ages
    if any(x.hour < 6 for x in points):
        out = [_check('night', 'attention' if kids else 'ok', 'Есть ночной отрезок дороги' + (' — с ребёнком тяжело' if kids else ''), 'ночной переезд')]
    else:
        out = [_check('night', 'ok', 'Ночных переездов нет ✓', 'без ночных переездов')]
    minutes = dest['minutes']
    if spec.max_flight_minutes and minutes > spec.max_flight_minutes:
        out.append(_check('flight', 'attention', f'Перелёт {fmt_minutes(minutes)} — дольше, чем хотелось', f'лететь {fmt_minutes(minutes)}'))
    if spec.pets:
        ok = dest.get('pets_ok')
        out.append(_check('pets', 'ok' if ok else 'attention', 'Животное: перевозку в салоне уточним у перевозчика' if ok else 'Перевозка животного на этом направлении не проверена', 'животное в дороге'))
    return out


def _night_transfer(tr, transfer_start, pickup):
    """A transfer between 23:00 and 06:00 costs 30 % more per leg."""
    legs = len([x for x in (transfer_start, pickup) if x.hour >= 23 or x.hour < 6])
    tr = {**tr, 'night_legs': legs, 'total': round(tr['price'] * (2 + 0.3 * legs), -2)}
    return tr, [_check('night_transfer', 'attention', f'Ночной трансфер ({legs}) — дороже на 30 %', 'ночной трансфер')] if legs else []


def _step(code, title, at, tz_label, note=None):
    return {'code': code, 'title': title, 'time': at.strftime('%H:%M'), 'date': fmt_day(at.date()), 'tz': tz_label, 'iso': at.isoformat(), 'note': note}


def _steps(spec, dest, extras, tr, airport_buffer, arrival_source, at):
    local = 'по местному' if dest['timezone'] != data.ORIGIN['timezone'] else 'по Москве'
    return [
        _step('departure', f'Вылет из Москвы ({data.ORIGIN["airport"]})', at['departure'], 'по Москве', f'{OUT_SLOTS[spec.out_slot][2]} модельный рейс' if arrival_source == 'model' else 'по твоему времени прилёта'),
        _step('arrival', f'Прилёт, {dest["airport"]["name"]} ({dest["airport"]["code"]})', at['arrival'], local, f'в пути {fmt_minutes(dest["minutes"])} без пересадок'),
        _step('transfer', f'Трансфер {fmt_minutes(tr["minutes"])}', at['transfer'], local, f'{tr["km"]:.0f} км'.replace('.', ',')),
        _step('checkin', 'Заселение', at['checkin'], local, 'ранний заезд' if 'early_checkin' in extras else 'стандарт с 14:00'),
        _step('checkout', 'Выезд из номера', at['checkout'], local, 'поздний выезд' if 'late_checkout' in extras else ('багаж в камере хранения' if 'storage' in extras else None)),
        _step('pickup', 'Трансфер в аэропорт', at['pickup'], local, f'за {airport_buffer // 60} ч до вылета'),
        _step('return', 'Обратный вылет', at['back'], local, f'{BACK_SLOTS[spec.back_slot][2]} модельный рейс'),
        _step('home', 'В Москве', at['home'], 'по Москве'),
    ]


def _slot_trip(spec, hotel, dest, leg, field, slot):
    """The trip on this flight slot; an early outbound gets the early check-in it cannot do without."""
    s = spec.model_copy(update={field: slot, 'arrival_time': None})
    tl = timeline(s, hotel, dest)
    if leg != 'outbound' or 'early_checkin' in s.extras:
        return s, tl, []
    arrival = next(c for c in tl['checks'] if c['code'] == 'arrival')
    early_fix = any(f['extra'] == 'early_checkin' for f in arrival['fixes'])
    if arrival['status'] == 'ok' or not early_fix or int(tl['steps'][1]['time'][:2]) >= 9:
        return s, tl, []
    s = s.model_copy(update={'extras': s.extras + ['early_checkin']})
    return s, timeline(s, hotel, dest), ['ранний заезд']


def _slot_notes(leg, tl, needed):
    at = {x['code']: x['time'] for x in tl['steps']}
    notes = [f'прилёт {at["arrival"]}, заселение {at["checkin"]}' if leg == 'outbound' else f'трансфер в {at["pickup"]}, дома {at["home"]}']
    if tl['transfer']['night_legs']:
        notes.append('ночной трансфер')
    if any(c['code'] == 'night' and c['status'] != 'ok' for c in tl['checks']):
        notes.append('ночной отрезок с ребёнком')
    return notes + [n + ' обязателен' for n in needed]


def timeline(spec, hotel, dest, extras=None):
    """Arrival → check-in … check-out → departure, computed on UTC instants with IANA zones."""
    extras = set(spec.extras if extras is None else extras)
    departure, arrival, arrival_source = _outbound(spec, dest)
    tr = transfer(spec, hotel, dest)
    international = dest['country'] != 'Россия'
    transfer_start = _plus(arrival, 40 if international else 25)
    p = price(spec, hotel, dest, spec.room_id, spec.rate_id)
    half_night = round(base_night(hotel, dest) * p['room']['rooms'] * 0.5, -2)
    checkin, arrival_check = _checkin(spec, _plus(transfer_start, tr['minutes']), extras, half_night, dest['timezone'])
    airport_buffer = 180 if international else 120
    back, home, pickup, checkout = _homebound(spec, dest, tr['minutes'], extras, airport_buffer)
    tr, transfer_checks = _night_transfer(tr, transfer_start, pickup)
    checks = [arrival_check, _departure_check(checkout, pickup, extras, half_night), *_road_checks(spec, dest, (departure, arrival, back, home)), *transfer_checks]
    at = {'departure': departure, 'arrival': arrival, 'transfer': transfer_start, 'checkin': checkin, 'checkout': checkout, 'pickup': pickup, 'back': back, 'home': home}
    return {'steps': _steps(spec, dest, extras, tr, airport_buffer, arrival_source, at), 'checks': checks, 'transfer': tr, 'flight_minutes': dest['minutes'],
            'half_night': half_night, 'arrival_source': arrival_source, 'mode': 'demo_schedule'}


def extras_cost(spec, tl):
    out = []
    for e in spec.extras:
        price_ = tl['half_night'] if e in ('early_checkin', 'late_checkout') else 0
        out.append({'extra': e, 'label': {'early_checkin': 'Ранний заезд', 'late_checkout': 'Поздний выезд до 14:00', 'storage': 'Камера хранения'}[e], 'price': price_})
    return out


def breakdown(spec, hotel, dest):
    p = price(spec, hotel, dest, spec.room_id, spec.rate_id)
    tl = timeline(spec, hotel, dest)
    r = road(spec, dest)
    tr = tl['transfer']
    ex = extras_cost(spec, tl)
    rows = [
        {'kind': 'hotel', 'label': f'Отель: {p["nights"]} ноч. × {money(p["night"])} · {p["room"]["name"].lower()}, {p["rate"]["name"].lower()}', 'amount': p['total'], 'note': 'налоги включены · демо-цена'},
        {'kind': 'transfer', 'label': 'Трансферы туда и обратно', 'amount': tr['total'], 'note': 'демо-цена' + (' · ночная доплата 30 %' if tr['night_legs'] else '')},
    ]
    if r['total']:
        rows.append({'kind': 'road', 'label': f'Перелёт туда и обратно на {spec.people} чел. · {OUT_SLOTS[spec.out_slot][2]} туда, {BACK_SLOTS[spec.back_slot][2]} обратно', 'amount': r['total'], 'note': 'оценка, демо — билеты пока не продаём'})
    for e in ex:
        rows.append({'kind': 'extra', 'label': e['label'], 'amount': e['price'], 'note': 'демо-цена'})
    seats = sum(age < CHILD_SEAT_AGE for age in spec.children_ages)
    if seats:
        rows.append({'kind': 'extra', 'label': f'Детское кресло в трансфере × {seats}', 'amount': 0, 'note': 'включено в трансфер · демо'})
    rows.append({'kind': 'fee', 'label': 'Курортный или туристический сбор', 'amount': None, 'note': 'уточняется у отеля'})
    total = sum(x['amount'] or 0 for x in rows)
    return {'rows': rows, 'total': total, 'hotel_total': p['total'], 'price': p, 'timeline': tl}


def flight_options(spec, hotel, dest):
    """Compare model flights by the cost of the whole trip, not the ticket alone."""
    current = breakdown(spec, hotel, dest)['total']
    ticket = road(spec, dest)['total']
    out = {'outbound': [], 'return': []}
    for leg, slots, field in (('outbound', OUT_SLOTS, 'out_slot'), ('return', BACK_SLOTS, 'back_slot')):
        for slot, (hhmm, _, name) in slots.items():
            s, tl, needed = _slot_trip(spec, hotel, dest, leg, field, slot)
            total = breakdown(s, hotel, dest)['total']
            out[leg].append({'slot': slot, 'label': f'{name.capitalize()} · {hhmm}', 'selected': getattr(spec, field) == slot,
                             'ticket_delta': road(s, dest)['total'] - ticket, 'trip_total': total, 'trip_delta': total - current,
                             'notes': _slot_notes(leg, tl, needed), 'extras': ['early_checkin'] if needed else []})
    return out


def quote_id(spec, total):
    payload = spec.model_dump_json(include={'destination', 'hotel_id', 'room_id', 'rate_id', 'check_in', 'check_out', 'adults', 'children_ages', 'extras', 'arrival_time', 'out_slot', 'back_slot'})
    return sha256((payload + str(total)).encode()).hexdigest()[:16]


class Trace:
    def __init__(self):
        self.t0 = _time.perf_counter()
        self.steps = []

    def step(self, name, count=None, detail=None):
        self.steps.append({'name': name, 'count': count, 'detail': detail, 'ms': round((_time.perf_counter() - self.t0) * 1000)})

    def dump(self, **extra):
        return {'steps': self.steps, 'ms': round((_time.perf_counter() - self.t0) * 1000), 'llm_calls': 0, 'cost_rub': 0, **extra}

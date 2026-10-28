"""Screen payloads for the linear flow (screens 3, 4, 5, 7, 8)."""
from datetime import date

from backend.domain.errors import Conflict
from backend.flow import data
from backend.flow.engine import (MUST_OK, LOCATION_WISHES, Trace, assess, breakdown, candidates, card,
                                 distances, district_of, fmt_day, fmt_minutes, fmt_party, fmt_range, hotel_budget,
                                 hotel_image, money, pick_three, price, quote_id, rate_options, road, room_options,
                                 tradeoff, why_lines, _variation)
from backend.flow.model import WISHES, FlowSpec

DEMO_NOTE = 'Демо-цены: отели и факты — из открытых источников, цены, номера, тарифы и рейсы — модель для хакатона.'


def dest_or_fail(spec):
    dest = data.DEST.get(spec.destination or '')
    if not dest:
        raise Conflict('Сначала выбери направление')
    return dest


# ---------- screen 3: where to go ----------

def _wants(spec, wish):
    return spec.priorities.get(wish) in ('must', 'want')


def _weighted(traits, weights):
    return sum(w for trait, w in weights.items() if trait in traits)


# How much each trait of a place counts for a person: (does it apply to this person?, trait weights).
DEST_FIT = [
    (lambda s: s.children_ages or _wants(s, 'kids'), {'kids': 3, 'quiet': 1, 'nightlife': -1.5}),
    (lambda s: _wants(s, 'quiet'), {'quiet': 2, 'nightlife': -2}),
    (lambda s: _wants(s, 'culture'), {'culture': 2}),
    (lambda s: s.purpose == 'business', {'business': 2}),
    (lambda s: s.cheap, {'budget': 0.5}),
    (lambda s: s.kind == 'sea' or s.warm, {'sea': 1}),
]


DISTRICT_FIT = [
    (lambda s: s.children_ages or _wants(s, 'kids'), {'kids': 2, 'quiet': 1, 'beach': 1, 'nightlife': -2}),
    (lambda s: _wants(s, 'quiet'), {'quiet': 2, 'nightlife': -2}),
    (lambda s: _wants(s, 'beach'), {'beach': 2}),
    (lambda s: _wants(s, 'culture') or s.purpose == 'business', {'center': 2, 'culture': 1}),
]


def _fit(spec, traits, table):
    return sum(_weighted(set(traits), weights) for applies, weights in table if applies(spec))


def _miss_warm(spec, dest, cl):
    if spec.warm and (not cl or cl['day_c'] < 24):
        return {'code': 'warm', 'text': f'днём около +{round(cl["day_c"])}°' if cl else 'нет климатических данных', 'near': bool(cl and cl['day_c'] >= 22)}
    return None


def _miss_kind(spec, dest, cl):
    if spec.kind and dest['kind'] != spec.kind:
        return {'code': 'kind', 'text': {'sea': 'не у моря', 'city': 'не город', 'nature': 'не природа'}[spec.kind], 'near': False}
    return None


def _miss_flight(spec, dest, cl):
    if spec.max_flight_minutes and dest['minutes'] > spec.max_flight_minutes:
        return {'code': 'flight', 'text': f'лететь {fmt_minutes(dest["minutes"])}', 'near': dest['minutes'] <= spec.max_flight_minutes + 30}
    return None


def _miss_pets(spec, dest, cl):
    if spec.pets and not dest.get('pets_ok'):
        return {'code': 'pets', 'text': 'перевозка животного не проверена', 'near': False}
    return None


MISSES = (_miss_warm, _miss_kind, _miss_flight, _miss_pets)


def _misses(spec, dest, cl):
    """Conditions this place breaks; 'near' means close enough to offer as «почти подходит»."""
    return [m for m in (check(spec, dest, cl) for check in MISSES) if m]


def _considered(spec):
    return [d for d in data.DESTINATIONS if d['name'] != spec.origin and (not spec.only or d['id'] in spec.only)
            and (not spec.countries or d['country'] in spec.countries)]


def _dest_row(spec, dest):
    """A candidate place with its single broken condition (if any), or None when it cannot be offered."""
    cl = data.month_climate(dest['id'], spec.check_in.month)
    bad = _misses(spec, dest, cl)
    named = dest['id'] in spec.only  # a place the person named is always compared, with what it breaks
    if not named and (len(bad) > 1 or (bad and not bad[0]['near'] and bad[0]['code'] not in ('warm', 'flight'))):
        return None
    dspec = spec.model_copy(update={'destination': dest['id'], 'district': None})
    ok = candidates(dspec, dest)['ok']
    if not ok:
        return None
    return {'dest': dest, 'climate': cl, 'bad': bad[0] if bad else None, 'hotels_from': min(a['price']['total'] for a in ok),
            'road': road(dspec, dest)['total'], 'fit': _dest_fit(spec, dest), 'count': len(ok)}


def _rank(r):
    # Fit first, but a much pricier place has to earn its spot: −1 point per 150 000 ₽ of trip cost.
    return -(r['fit'] - (r['hotels_from'] + r['road']) / 150000), r['dest']['minutes']


def _choose_places(spec, strict, near, loose):
    if spec.only:
        # The person named the places: show each of them, strict or not, so they can compare.
        return sorted(strict + near + loose, key=lambda r: spec.only.index(r['dest']['id']))
    chosen, per_country = [], {}
    limit = 3 if spec.countries else 2
    for r in sorted(strict, key=_rank):
        c = r['dest']['country']
        if per_country.get(c, 0) < limit and len(chosen) < 3:
            per_country[c] = per_country.get(c, 0) + 1
            chosen.append(r)
    if len(chosen) < 3:
        chosen += [r for r in sorted(near, key=_rank) if per_country.get(r['dest']['country'], 0) < 2][:1]
    if not chosen:
        # Nothing fits every condition: the two closest misses, each naming what it breaks.
        chosen = sorted(loose, key=lambda r: (r['bad']['code'] != 'flight', r['dest']['minutes'], r['hotels_from'] + r['road']))[:2]
    return chosen


def _dest_label(r, chosen):
    d = r['dest']
    if r['bad']:
        return 'Почти подходит: ' + r['bad']['text']
    best = next(x for x in chosen if not x['bad'])  # named places keep their order, so a miss can come first
    if r is best:
        return 'Лучший баланс'
    if calm(d) == max(calm(x['dest']) for x in chosen) and calm(d) > calm(best['dest']):
        return 'Тише всего'
    cheapest = min(chosen, key=lambda x: x['hotels_from'] + x['road'])
    return 'Дешевле всего' if cheapest is r else 'Ещё вариант'


def _weather(cl):
    if not cl:
        return None
    day, night = round(cl['day_c']), round(cl['night_c'])
    text = f'днём +{day}°, ночью +{night}°' if cl['night_c'] >= 0 else f'днём {day:+d}°, ночью {night:+d}°'
    return {'day': day, 'night': night, 'text': text, 'source': 'Open-Meteo, среднее за 2016–2025, не прогноз'}


def _dest_card(spec, r, label):
    d = r['dest']
    return {'id': d['id'], 'name': d['name'], 'country': d['country'], 'label': label, 'near': bool(r['bad']),
            'character': d['character'], 'image': '/assets/' + d['image'], 'weather': _weather(r['climate']),
            'road_text': f'≈ {fmt_minutes(d["minutes"])} без пересадок',
            'price_text': f'отели от {money(r["hotels_from"])} за {spec.nights} ноч. · дорога ≈ {money(r["road"])}',
            'hotels_from': r['hotels_from'], 'road_total': r['road'], 'hotels_count': r['count'], 'why': d['why'][:2], 'tradeoff': d['tradeoff']}


def _dest_note(spec, cards):
    if not cards:
        return 'Ни одно направление не подошло под все условия. Попробуй убрать одно из них.'
    if spec.only:
        return None
    if all(c['near'] for c in cards):
        return 'Под все условия не подошло ни одно место. Вот ближайшие — у каждого указано, какое условие нарушено.'
    return f'Под все условия подошли только {len(cards)}' if len(cards) < 3 else None


def _district_row(spec, d, ok):
    mine = [a['price']['total'] for a in ok if a['hotel'].get('district') == d['id']]
    return {'id': d['id'], 'name': d['name'], 'summary': d['summary'], 'fit': _district_fit(spec, d), 'count': len(mine), 'from': min(mine, default=None)}


def _nightly_relaxation(spec, cands):
    if not spec.nightly_budget or len(cands['ok']) < 3:
        return []
    need = int(round(sorted(a['price']['night'] / a['price']['room']['rooms'] for a in cands['ok'])[2] + 49, -2))
    return [{'wish': 'budget', 'label': f'Поднять лимит до {money(need)} за ночь — будет 3 варианта', 'patch': {'nightly_budget': need}}] if need > spec.nightly_budget else []


def _tariff_price(spec, dest, pool, wish):
    """What a meal plan adds on the cheapest fitting hotel."""
    if wish == 'all_inclusive' and not dest.get('resort'):
        return {'text': 'нет в этом направлении', 'delta': None}
    ref = min(pool, key=lambda a: a['price']['total'], default=None)
    if not ref:
        return None
    room = ref['price']['room']['id']
    delta = price(spec, ref['hotel'], dest, room, 'bb' if wish == 'breakfast' else 'ai')['total'] - price(spec, ref['hotel'], dest, room, 'nr')['total']
    return {'text': f'+{money(delta)}', 'delta': delta}


def _wish_price(spec, dest, pool, wish):
    """Difference of the cheapest option with the wish confirmed vs without it — only with enough comparable options."""
    temp = spec.model_copy(update={'priorities': {**spec.priorities, wish: 'want'}})
    statuses = [assess(temp, a['hotel'], dest)['rows'][wish]['status'] for a in pool]
    yes = [a for a, st in zip(pool, statuses, strict=True) if st in MUST_OK or (wish in LOCATION_WISHES and st == 'district')]
    if len(pool) < 4 or len(yes) < 2:
        return {'text': 'мало вариантов для сравнения' if yes else 'нет подтверждённых вариантов', 'delta': None}
    delta = min(a['price']['total'] for a in yes) - min(a['price']['total'] for a in pool)
    return {'text': f'+{money(delta)}' if delta > 0 else 'без доплаты', 'delta': delta}


def _places_note(spec, picked, district_rows, base, cands, cards):
    if not cards:
        return _blockers_note(base)
    if spec.district and picked and picked != spec.district:
        names = {r['id']: r['name'] for r in district_rows}
        return f'В районе «{names.get(spec.district, spec.district)}» ничего не подошло — показываю «{names[picked]}»'
    if len(cards) >= 3:
        return None
    if not picked:
        return f'Под все условия подошли только {len(cards)}'
    if len(cands['pool']) >= 3:
        return None
    others = len(base['ok']) - len(cands['pool'])
    return f'В районе подошло {len(cands["pool"])}' + (f'; ещё {others} — в других районах' if others > 0 else '')


def _blockers_note(base):
    counts = {}
    for v in (v for a in base['all'] for v in a['violations']):
        counts[v['wish']] = counts.get(v['wish'], 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:2]
    if not top:
        return 'В этом направлении нет отелей под условия.'
    return 'Ни один отель не прошёл. Мешает: ' + ', '.join(f'«{WISHES.get(k, k)}» не подтверждено у {n} из {base["scanned"]}' for k, n in top)


def _more(dest, base, cards):
    shown = {c['id'] for c in cards}
    ranked = sorted(base['ok'], key=lambda a: (-a['score'], a['price']['total']))
    return [{'id': a['hotel']['id'], 'name': a['hotel']['name'], 'stars': a['hotel'].get('stars'),
             'district': (district_of(dest, a['hotel']) or {}).get('name'), 'total': a['price']['total']} for a in ranked if a['hotel']['id'] not in shown][:6]


def _hotel_cards(spec, dest, slots):
    best = next((a for code, _, a in slots if code == 'best'), None)
    cards = []
    for code, label, a in slots:
        c = card(spec, dest, a, code, label)
        c['tradeoff'] = None if a is best else tradeoff(spec, dest, best, a)
        cards.append(c)
    return cards


PROMISE_ORDER = {'contradicts': 0, 'unconfirmed': 1, 'tariff': 2, 'confirmed': 3}


def _promised(spec, h, a):
    rows = [{'wish': w, 'title': WISHES[w], 'level': spec.priorities[w], 'status': PROMISE[r['status']], 'text': r['text'],
             'source': r.get('source'), 'source_name': r.get('source_name')} for w, r in a['rows'].items()]
    rows += [{'wish': c['wish'], 'title': 'Сезонность', 'level': spec.priorities.get(c['wish'], 'skip'), 'status': 'contradicts', 'text': c['text'],
              'source': c['source'], 'source_name': 'сайт отеля'} for c in h.get('contradictions', []) if spec.check_in.month in c['months']]
    return sorted(rows, key=lambda r: (r['level'] != 'must', PROMISE_ORDER[r['status']]))


def _sacrifice(spec, dest, h, a):
    """Compare with the best option of the same district to name what was given up."""
    base = candidates(spec, dest, h.get('district'))
    best = next((x for code, _, x in pick_three(spec, dest, base['pool'], base['median']) if code == 'best'), None)
    if best and best['hotel']['id'] != h['id']:
        return tradeoff(spec, dest, best, a) + f' — по сравнению с «{best["hotel"]["name"]}»'
    return 'По важному для тебя ничем — это лучший вариант в бюджете по нашим данным'


def _cancel_text(p):
    return f'бесплатная отмена до {fmt_day(date.fromisoformat(p["free_until"]))}' if p['free_until'] else 'невозвратный'


def _rooms(spec, h, dest):
    out = []
    for r in room_options(spec):
        rates = [(rate, price(spec, h, dest, r['id'], rate['id'])) for rate in rate_options(dest)]
        out.append({'id': r['id'], 'name': r['name'], 'rooms': r['rooms'], 'capacity': r['capacity'],
                    'rates': [{'id': rate['id'], 'name': rate['name'], 'refundable': rate['refundable'], 'cancel': _cancel_text(p), 'total': p['total']} for rate, p in rates]})
    return out


def _rate_reason(spec, h, dest, chosen):
    if chosen['rate']['id'] == 'nr':
        return 'Самый дешёвый тариф, но без питания и без возврата денег при отмене'
    extra = chosen['total'] - price(spec, h, dest, chosen['room']['id'], 'nr')['total']
    return f'{chosen["rate"]["name"]} и бесплатная отмена — +{money(extra)}, зато можно передумать до {fmt_day(date.fromisoformat(chosen["free_until"]))}'


def _risks(spec, h, dest, chosen):
    budget = hotel_budget(spec, dest) or 0
    checks = [
        (chosen['rate']['id'] == 'nr', 'Невозвратный тариф: при отмене деньги не вернутся'),
        (len(h['facts']) <= 1, 'Мало данных об отеле: в открытых источниках только название и адрес'),
        (budget and 0 <= budget - chosen['total'] < budget * 0.05, 'Впритык по бюджету'),
        (budget and chosen['total'] > budget, f'Выше бюджета на {money(chosen["total"] - budget)}'),
        (_variation(h['id'] + spec.check_in.isoformat(), 0, 1) < 0.2, 'По демо-наличию остался последний номер этого типа'),
    ]
    return [text for hit, text in checks if hit]


def _cart_hotel(spec, dest):
    if not spec.hotel_id:
        raise Conflict('Сначала выбери отель')
    h = data.hotel(spec.hotel_id)
    if not h:
        raise Conflict('Отель больше не доступен')
    return h


def _cart_changes(expected_total, total, hard):
    changes = []
    if expected_total is not None and expected_total != total:
        changes.append(f'Итог изменился: было {money(expected_total)}, стало {money(total)}')
    if hard:
        changes.append('Отель больше не подходит под условия: ' + ', '.join(WISHES.get(v['wish'], v['wish']) for v in hard))
    return changes


def _dest_fit(spec, dest):
    return _fit(spec, dest['traits'], DEST_FIT)


def calm(dest):
    """How quiet a place is by its editorial traits: quiet and nature count, nightlife and city subtract."""
    t = set(dest['traits'])
    return ('quiet' in t) + ('nature' in t) - ('nightlife' in t) - ('city' in t)


def destinations(spec: FlowSpec):
    tr = Trace()
    considered = _considered(spec)
    rows = [r for r in (_dest_row(spec, d) for d in considered) if r]
    strict = [r for r in rows if not r['bad']]
    near = [r for r in rows if r['bad'] and r['bad']['near']]
    loose = [r for r in rows if r['bad'] and not r['bad']['near']]
    tr.step('Направления', len(considered))
    tr.step('Подходят под условия', len(strict))
    chosen = _choose_places(spec, strict, near, loose)
    cards = [_dest_card(spec, r, _dest_label(r, chosen)) for r in chosen]
    tr.step('Показываем', len(cards))
    return {'cards': cards, 'note': _dest_note(spec, cards), 'demo_note': DEMO_NOTE, 'trace': tr.dump(funnel=[len(considered), len(strict) + len(near), len(cards)])}


# ---------- screen 4: districts and three hotels ----------

def _district_fit(spec, d):
    return _fit(spec, d['traits'], DISTRICT_FIT)


def choose_district(spec, dest, ok):
    rows = [_district_row(spec, d, ok) for d in dest.get('districts') or []]
    valid = [r for r in rows if r['count']]
    agent = max(valid, key=lambda r: (r['fit'], r['count']), default=None)
    # A district where nothing fits is not a choice: fall back to the agent's district (places() says so).
    picked = spec.district if any(r['id'] == spec.district for r in valid) else (agent or {}).get('id')
    for r in rows:
        r['agent'] = r is agent
        r['selected'] = r['id'] == picked
    return picked, rows


def _relaxations(spec, dest, cands):
    out = []
    for w in [w for w, level in spec.priorities.items() if level == 'must']:
        freed = [a for a in cands['all'] if a['violations'] and all(v['wish'] == w for v in a['violations'])]
        if freed:
            out.append({'wish': w, 'label': f'Без «{WISHES[w]}» — {len(freed)} отел. от {money(min(a["price"]["total"] for a in freed))}',
                        'patch': {'priorities': {**spec.priorities, w: 'want'}}})
    return out + _nightly_relaxation(spec, cands)


def wish_prices(spec, dest, cands):
    pool = [a for a in cands['all'] if not [v for v in a['violations'] if not v.get('soft')]]
    out = {w: (_tariff_price if w in ('breakfast', 'all_inclusive') else _wish_price)(spec, dest, pool, w) for w in WISHES}
    return {w: v for w, v in out.items() if v}


TRANSFERS_IN_BUDGET = 2 * 2500  # engine.hotel_budget sets the same aside for two transfers


def _over_budget(spec, dest, base):
    """A total budget below the cheapest whole trip: an honest empty screen and at most two ways up, each with its count."""
    limit = hotel_budget(spec, dest) if spec.budget else None
    totals = sorted(a['price']['total'] for a in base['ok'])
    if limit is None or not totals or totals[0] <= limit:
        return None
    extra = road(spec, dest)['total'] + TRANSFERS_IN_BUDGET  # what hotel_budget keeps aside for the road
    ways = [(n, int(round(totals[n - 1] + extra + 499, -3))) for n in (1, 3) if len(totals) >= n]
    return {'cards': [], 'more': [],
            'note': f'В бюджет {money(spec.budget)} на всю поездку не укладывается ни один вариант: дорога и трансферы — {money(extra)}, '
                    f'самый дешёвый отель — {money(totals[0])}.',
            'relax': [{'wish': 'budget', 'label': f'Поднять бюджет до {money(need)} — ' + ('в него войдёт 1 отель' if n == 1 else f'в него войдут {n} отеля'), 'patch': {'budget': need}}
                      for n, need in ways]}


def places(spec: FlowSpec):
    tr = Trace()
    dest = dest_or_fail(spec)
    base = candidates(spec, dest)
    tr.step('Отели в направлении', base['scanned'])
    tr.step('Прошли жёсткие фильтры', len(base['ok']))
    picked, district_rows = choose_district(spec, dest, base['ok'])
    cands = candidates(spec.model_copy(update={'district': picked}), dest, picked) if picked else base
    cards = _hotel_cards(spec, dest, pick_three(spec, dest, cands['pool'], cands['median'], base['ok'] if picked else None))
    tr.step('Показываем', len(cards))
    totals = sorted(a['price']['total'] for a in base['ok']) or [0]
    screen = {
        'destination': {'id': dest['id'], 'name': dest['name'], 'country': dest['country'], 'character': dest['character']},
        'dates': fmt_range(spec.check_in, spec.check_out), 'party': fmt_party(spec), 'nights': spec.nights,
        'districts': district_rows, 'district': picked, 'cards': cards, 'more': _more(dest, base, cards),
        'note': _places_note(spec, picked, district_rows, base, cands, cards), 'relax': _relaxations(spec, dest, base) if len(cards) < 3 else [],
        'wish_prices': wish_prices(spec, dest, base),
        'budget': {'hotel_budget': hotel_budget(spec, dest), 'min': totals[0], 'max': totals[-1], 'road': road(spec, dest)['total']},
        'demo_note': DEMO_NOTE,
        'trace': tr.dump(funnel=[sum(data.catalogue_counts().values()), base['scanned'], len(base['ok']), len(cards)]),
    }
    return {**screen, **(_over_budget(spec, dest, base) or {})}


# ---------- screen 5: hotel ----------

PROMISE = {'yes': 'confirmed', 'distance': 'confirmed', 'tariff': 'tariff', 'district': 'unconfirmed', 'unknown': 'unconfirmed', 'far': 'contradicts', 'no': 'contradicts'}


def _not_for(spec, dest, a):
    h = a['hotel']
    district = district_of(dest, h)
    if district and 'nightlife' in district['traits']:
        return f'Не для тех, кто хочет тишины вечером — район «{district["name"]}»: {district["summary"]}'
    if h.get('not_for'):
        return 'Не для тех, кому это критично: ' + h['not_for'][0].lower() + h['not_for'][1:]
    if dest['kind'] == 'sea' and district and 'beach' not in district['traits']:
        return 'Не для тех, кто хочет выходить к морю прямо из номера — до воды дальше'
    if not h.get('stars'):
        return 'Не для тех, кому важна подтверждённая звёздность — в открытых данных её нет'
    return 'Не для тех, кому нужен подтверждённый детский клуб или спа — в открытых данных их нет'


def hotel_detail(spec: FlowSpec, hotel_id: str):
    dest = dest_or_fail(spec)
    h = data.hotel(hotel_id)
    if not h or h['destination'] != dest['id']:
        raise Conflict('Отель не найден в этом направлении')
    spec = spec.model_copy(update={'hotel_id': hotel_id})
    a = assess(spec, h, dest)
    chosen = price(spec, h, dest, spec.room_id, spec.rate_id)
    bd = breakdown(spec, h, dest)
    district = district_of(dest, h)
    return {
        'id': h['id'], 'name': h['name'], 'stars': h.get('stars'), 'district': district['name'] if district else None,
        'destination': dest['name'], 'dates': fmt_range(spec.check_in, spec.check_out), 'party': fmt_party(spec),
        'image': hotel_image(h['id']), 'website': h.get('website'), 'source_url': h['source_url'], 'retrieved_at': h.get('retrieved_at'),
        'promised': _promised(spec, h, a), 'facts': h['facts'], 'why': why_lines(spec, dest, a), 'not_for': _not_for(spec, dest, a),
        'sacrifice': _sacrifice(spec, dest, h, a), 'risks': _risks(spec, h, dest, chosen),
        'rooms': _rooms(spec, h, dest), 'selected': {'room': chosen['room']['id'], 'rate': chosen['rate']['id']}, 'rate_reason': _rate_reason(spec, h, dest, chosen),
        'distances': distances(spec, h, dest), 'timeline': bd['timeline'], 'breakdown': bd['rows'], 'total': bd['total'],
        'tickets': {'status': 'soon', 'text': 'Выбор билетов — скоро. Сейчас в расчёте модельный прямой рейс.'},
        'demo_note': DEMO_NOTE,
    }


# ---------- screen 7: cart ----------

def cart(spec: FlowSpec, expected_total: int | None = None):
    dest = dest_or_fail(spec)
    h = _cart_hotel(spec, dest)
    hard = [v for v in assess(spec, h, dest)['violations'] if not v.get('soft')]
    bd = breakdown(spec, h, dest)
    p = bd['price']
    checks = bd['timeline']['checks']
    open_issues = [c for c in checks if c['status'] != 'ok']
    guests = [{'kind': 'adult', 'age': None, 'label': 'взрослый'}] * spec.adults + [{'kind': 'child', 'age': age, 'label': f'ребёнок {age} лет'} for age in spec.children_ages]
    return {
        'hotel': {'id': h['id'], 'name': h['name'], 'destination': dest['name'], 'district': (district_of(dest, h) or {}).get('name')},
        'room': p['room']['name'] + (f' × {p["room"]["rooms"]}' if p['room']['rooms'] > 1 else ''), 'rate': p['rate']['name'],
        'dates': fmt_range(spec.check_in, spec.check_out), 'nights': spec.nights, 'party': fmt_party(spec),
        'rows': bd['rows'], 'total': bd['total'], 'quote_id': quote_id(spec, bd['total']),
        'cancel': (_cancel_text(p).capitalize() + ', потом — стоимость первой ночи') if p['free_until'] else 'Невозвратный тариф: при отмене деньги не возвращаются',
        'checks_ok': not open_issues, 'checks': checks,
        'recheck': 'Заселение сходится ✓ — проверили ещё раз' if not open_issues else f'Проверили ещё раз: осталось {len(open_issues)} ⚠',
        'available': not hard, 'changes': _cart_changes(expected_total, bd['total'], hard), 'guests': [dict(g) for g in guests],
        'tickets': 'Билеты — скоро: сейчас перелёт в расчёте как оценка',
        'checked_at': 'цены и наличие проверены только что', 'demo_note': DEMO_NOTE,
    }

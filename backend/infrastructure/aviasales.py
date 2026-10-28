"""Cached Aviasales Data API prices: indicative only, never a booking quote."""
import math
import os
import re
from datetime import date, datetime, timezone

import httpx

URL = 'https://api.travelpayouts.com/aviasales/v3/prices_for_dates'


async def search_flight_prices(args):
    for field in ('origin', 'destination', 'currency'):
        if not isinstance(args.get(field), str) or not re.fullmatch(r'[A-Z]{3}', args[field]):
            raise ValueError('Origin, destination and currency must be three uppercase letters')
    if args['origin'] == args['destination']:
        raise ValueError('Origin and destination must differ')
    try:
        departure = date.fromisoformat(args['departure_date'])
        returned = date.fromisoformat(args['return_date']) if 'return_date' in args else None
    except (KeyError, TypeError, ValueError):
        raise ValueError('Dates must be ISO dates') from None
    if departure < date.today() or (returned is not None and returned <= departure):
        raise ValueError('Invalid flight dates')
    key = os.getenv('TRAVELPAYOUTS_API_TOKEN', '').strip()
    base = {'source': 'Aviasales Data API', 'offers': [], 'indicative': True}
    if not key:
        return {**base, 'status': 'not_configured', 'message': 'Provider token is not configured; no price was invented.'}
    params = {'origin': args['origin'], 'destination': args['destination'], 'departure_at': departure.isoformat(),
              'currency': args['currency'].lower(), 'one_way': 'false' if returned else 'true', 'limit': 30}
    if returned:
        params['return_at'] = returned.isoformat()
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(URL, params=params, headers={'X-Access-Token': key, 'Accept': 'application/json'})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or payload.get('success') is not True or not isinstance(payload.get('data'), list):
            raise ValueError('Invalid provider response')
    except (httpx.HTTPError, ValueError):
        return {**base, 'status': 'provider_unavailable', 'message': 'Cached flight prices are unavailable; no price was invented.'}
    offers = []
    for item in payload['data'][:30]:
        if not isinstance(item, dict):
            continue
        price = item.get('price')
        if type(price) not in (int, float) or not math.isfinite(price) or not 0 < price < 100000000:
            continue
        if item.get('origin') != args['origin'] or item.get('destination') != args['destination']:
            continue
        if not isinstance(item.get('departure_at'), str) or not item['departure_at'].startswith(departure.isoformat()):
            continue
        if returned and (not isinstance(item.get('return_at'), str) or not item['return_at'].startswith(returned.isoformat())):
            continue
        offers.append({k: item[k] for k in ('origin', 'destination', 'origin_airport', 'destination_airport', 'price', 'airline', 'flight_number', 'departure_at', 'return_at', 'transfers', 'return_transfers', 'duration', 'duration_to', 'duration_back', 'found_at', 'expires_at') if k in item})
    return {**base, 'status': 'ok' if offers else 'no_results', 'offers': offers,
            'currency': args['currency'], 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'message': 'Prices are cached results from previous searches, not confirmed fares or availability; recheck before purchase.'}

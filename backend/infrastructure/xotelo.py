"""Xotelo public hotel rates for an explicitly identified hotel."""
import math
import re
from datetime import date, datetime, timezone
import httpx

URL = 'https://data.xotelo.com/api/rates'
CURRENCIES = {'USD','GBP','EUR','CAD','CHF','AUD','JPY','CNY','INR','THB','BRL','HKD','RUB','BZD'}


async def search_xotelo_rates(args):
    key = args.get('hotel_key')
    currency = args.get('currency')
    adults = args.get('adults')
    if not isinstance(key, str) or not re.fullmatch(r'g\d{1,12}-d\d{1,12}', key):
        raise ValueError('Invalid hotel key')
    if currency not in CURRENCIES or type(adults) is not int or not 1 <= adults <= 32:
        raise ValueError('Invalid currency or guest count')
    try:
        start, end = date.fromisoformat(args['check_in']), date.fromisoformat(args['check_out'])
    except (ValueError, KeyError, TypeError):
        raise ValueError('Invalid dates') from None
    if start < date.today() or not 1 <= (end-start).days <= 30:
        raise ValueError('Invalid dates')
    base = {'source': 'Xotelo', 'hotel_key': key, 'offers': []}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(URL, params={'hotel_key': key, 'chk_in': str(start), 'chk_out': str(end), 'currency': currency, 'adults': adults, 'rooms': 1})
            response.raise_for_status()
            payload = response.json()
        result = payload['result']
        if payload.get('error') is not None or not isinstance(result, dict) or result.get('currency') != currency or result.get('chk_in') != str(start) or result.get('chk_out') != str(end) or not isinstance(result.get('rates'), list):
            raise ValueError('Invalid provider response')
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {**base, 'status':'provider_unavailable', 'message':'Rates unavailable; no prices were invented.'}
    offers = []
    for rate in result['rates'][:30]:
        if not isinstance(rate, dict): continue
        amount = rate.get('rate')
        if type(amount) not in (int,float) or not math.isfinite(amount) or not 0 < amount < 100000000: continue
        offers.append({'provider': str(rate.get('name') or '')[:100], 'amount_per_room_night':amount, 'currency':currency, 'tax':rate.get('tax')})
    return {**base, 'status':'ok' if offers else 'no_results', 'offers':offers,
            'provider_timestamp':payload.get('timestamp'), 'fetched_at':datetime.now(timezone.utc).isoformat(),
            'message':'Price per room per night; taxes and availability must be checked with the seller. No booking was made.'}

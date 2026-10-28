"""Read-only LiteAPI rates adapter. It never creates bookings or substitutes prices."""
import os
import re
from datetime import date, datetime, timezone

import httpx

RATES_URL = 'https://api.liteapi.travel/v3.0/hotels/rates'


async def search_hotel_rates(args):
    city, country, nationality, currency = (args.get(k) for k in ('city', 'country_code', 'guest_nationality', 'currency'))
    if not isinstance(city, str) or not 2 <= len(city.strip()) <= 100:
        raise ValueError('Invalid city')
    if any(not isinstance(v, str) or not re.fullmatch(r'[A-Z]{2}', v) for v in (country, nationality)):
        raise ValueError('Country and guest nationality must be ISO alpha-2 codes')
    if not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('Currency must be an ISO alpha-3 code')
    adults = args.get('adults')
    if type(adults) is not int or not 1 <= adults <= 10:
        raise ValueError('Adults must be between 1 and 10')
    try:
        start, end = date.fromisoformat(args['check_in']), date.fromisoformat(args['check_out'])
    except (KeyError, ValueError, TypeError):
        raise ValueError('Dates must be ISO dates') from None
    if start < date.today() or not 1 <= (end-start).days <= 30:
        raise ValueError('Dates must be in the future and cover 1 to 30 nights')
    key = os.getenv('LITEAPI_KEY', '').strip()
    if not key:
        return {'status':'not_configured','offers':[],'source':'LiteAPI','message':'LiteAPI key is not configured; no prices were invented.'}
    payload = {'cityName':city.strip(),'countryCode':country,'guestNationality':nationality,'currency':currency,
               'checkin':start.isoformat(),'checkout':end.isoformat(),'occupancies':[{'adults':adults}],
               'maxRatesPerHotel':1,'includeHotelData':True,'timeout':8}
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response=await client.post(RATES_URL,headers={'X-API-Key':key,'Accept':'application/json'},json=payload)
            response.raise_for_status()
            data=response.json()
        if isinstance(data,dict) and isinstance(data.get('error'),dict) and data['error'].get('code')==2001:
            return {'status':'no_results','offers':[],'source':'LiteAPI','message':'The provider returned no available rates for these conditions.'}
        if not isinstance(data,dict) or data.get('error') or not isinstance(data.get('data'),list):
            raise ValueError('Invalid provider response')
    except (httpx.HTTPError, ValueError):
        return {'status':'provider_unavailable','offers':[],'source':'LiteAPI','message':'Hotel rates are unavailable; no prices were substituted.'}
    hotels={str(h.get('id')):h for h in data.get('hotels',[]) if isinstance(h,dict) and h.get('id')}
    fetched=datetime.now(timezone.utc).isoformat()
    offers=[]
    sandbox=data.get('sandbox') if isinstance(data.get('sandbox'),bool) else None
    for hotel in data['data'][:50]:
        if not isinstance(hotel,dict) or not hotel.get('hotelId'): continue
        info=hotels.get(str(hotel['hotelId']),{})
        for room in hotel.get('roomTypes',[]):
            if not isinstance(room,dict) or not room.get('offerId'): continue
            for rate in room.get('rates',[]):
                if not isinstance(rate,dict): continue
                totals=(rate.get('retailRate') or {}).get('total') or []
                for total in totals:
                    if not isinstance(total,dict) or total.get('currency')!=currency: continue
                    amount=total.get('amount')
                    if type(amount) not in (int,float) or not 0 <= amount < 100000000: continue
                    offers.append({'hotel_id':str(hotel['hotelId']),'hotel_name':info.get('name'),
                                   'offer_id':str(room['offerId']),'amount':amount,'currency':currency,
                                   'room_name':rate.get('name'),'board':rate.get('boardName'),
                                   'cancellation':rate.get('cancellationPolicies'),
                                   'source':'LiteAPI','fetched_at':fetched,'sandbox':sandbox})
    return {'status':'ok' if offers else 'no_results','offers':offers[:50],'source':'LiteAPI',
            'fetched_at':fetched,'sandbox':sandbox,
            'message':'Provider rates are indicative and must be revalidated; no booking was made.'}

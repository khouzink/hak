"""Attach indicative flight search results without changing the modelled package."""
from datetime import date
from backend.infrastructure.aviasales import search_flight_prices

# City IATA codes; unknown cities are never guessed.
CITIES = {'москва': 'MOW', 'moscow': 'MOW', 'сочи': 'AER', 'sochi': 'AER',
          'казань': 'KZN', 'kazan': 'KZN', 'санкт-петербург': 'LED', 'питер': 'LED',
          'saint petersburg': 'LED', 'екатеринбург': 'SVX', 'калининград': 'KGD',
          'минеральные воды': 'MRV', 'новосибирск': 'OVB'}


async def journey_flights(spec):
    if spec.get('transport', 'air') != 'air':
        return None
    origin = CITIES.get(spec.get('origin', '').strip().casefold())
    destination = CITIES.get(spec.get('destination', '').strip().casefold())
    if not origin or not destination or origin == destination:
        return {'status': 'unsupported_route', 'offers': []}
    try:
        if date.fromisoformat(spec['check_in']) < date.today():
            return {'status': 'invalid_dates', 'offers': []}
        return await search_flight_prices({'origin': origin, 'destination': destination,
            'departure_date': spec['check_in'], 'return_date': spec['check_out'], 'currency': 'RUB'})
    except (ValueError, KeyError, TypeError):
        return {'status': 'invalid_dates', 'offers': []}

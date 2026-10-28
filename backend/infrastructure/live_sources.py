"""User-triggered, cached public-source discovery. Never fabricates rates or reviews."""
import asyncio
import math
import os
from datetime import date, datetime, timezone
from urllib.parse import urlparse

import httpx

_catalog_lock=asyncio.Semaphore(1)
ALIASES={"хургада":"Hurghada","шарм-эль-шейх":"Sharm el Sheikh","шарм":"Sharm el Sheikh","анталья":"Antalya","казань":"Kazan","москва":"Moscow","питер":"Saint Petersburg","санкт-петербург":"Saint Petersburg","стамбул":"Istanbul","сочи":"Sochi","дубай":"Dubai"}


def safe_url(value):
    if not value:return None
    if not value.startswith(('http://','https://')):value='https://'+value
    p=urlparse(value)
    return value if p.scheme in {'http','https'} and p.hostname and not p.username else None


def distance_km(a,b,c,d):
    r=6371
    x=math.sin(math.radians(c-a)/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(math.radians(d-b)/2)**2
    return round(r*2*math.asin(min(1,math.sqrt(x))),1)


async def geocode(name, store):
    key='geo:'+name.casefold().strip()
    cached=store.cache_get(key)
    if cached is not None:return cached
    async with httpx.AsyncClient(timeout=15,follow_redirects=True) as c:
        r=await c.get(os.getenv('GEOCODING_URL','https://geocoding-api.open-meteo.com/v1/search'),params={'name':ALIASES.get(name.casefold().strip(),name),'count':5,'language':'ru'})
        r.raise_for_status()
        values=r.json().get('results',[])
    if not values:raise ValueError(f'Не удалось найти «{name}». Укажи название города, при необходимости — на английском.')
    values.sort(key=lambda v:-v.get('population',0))
    place=values[0]
    result={k:place.get(k) for k in ['id','name','country','country_code','latitude','longitude','timezone']}
    store.cache_put(key,result,7*86400)
    return result


async def hotels(place, store):
    key='osm-hotels:'+str(place['id'])
    cached=store.cache_get(key)
    if cached is not None:return cached
    lat,lon=float(place['latitude']),float(place['longitude'])
    query=f'[out:json][timeout:22];nwr["tourism"~"^(hotel|guest_house|apartment)$"]["name"](around:12000,{lat},{lon});out center tags 70;'
    endpoints=[os.getenv('OVERPASS_URL','https://overpass.private.coffee/api/interpreter'),'https://overpass-api.de/api/interpreter']
    last_error=None
    async with _catalog_lock:
        cached=store.cache_get(key)
        if cached is not None:return cached
        async with httpx.AsyncClient(timeout=30,follow_redirects=True,headers={'User-Agent':'OdinZapros/1.0 (user-requested hotel discovery)'}) as c:
            for endpoint in dict.fromkeys(endpoints):
                try:
                    r=await c.get(endpoint,params={'data':query});r.raise_for_status();payload=r.json();break
                except (httpx.HTTPError,ValueError) as e:last_error=e
            else:raise ValueError('Источник отелей временно не отвечает. Поездка сохранится; повтори поиск отелей чуть позже.') from last_error
    rows=[]
    seen=set()
    for e in payload.get('elements',[]):
        t=e.get('tags',{});name=t.get('name:ru') or t.get('name')
        if not name or name.casefold() in seen:continue
        seen.add(name.casefold())
        coords=e.get('center',e)
        if 'lat' not in coords:continue
        source=f"https://www.openstreetmap.org/{e['type']}/{e['id']}"
        facts=[]
        for tag,label in [('internet_access','Интернет'),('wheelchair','Доступность'),('swimming_pool','Бассейн'),('pets','Питомцы'),('stars','Звёзды')]:
            if tag in t:facts.append({'label':label,'value':t[tag],'source':source})
        rows.append({'id':f"osm:{e['type']}:{e['id']}",'name':name,'latitude':coords['lat'],'longitude':coords['lon'],
            'distance_km':distance_km(lat,lon,coords['lat'],coords['lon']),'stars':t.get('stars'),
            'address':', '.join(filter(None,[t.get('addr:street'),t.get('addr:housenumber'),t.get('addr:city')])) or None,
            'website':safe_url(t.get('website') or t.get('contact:website')),'phone':t.get('phone') or t.get('contact:phone'),
            'source_url':source,'source_name':'OpenStreetMap','retrieved_at':datetime.now(timezone.utc).isoformat(),
            'facts':facts,'rate':None,'availability':'unknown','photo':None})
    rows.sort(key=lambda h:h['distance_km'])
    store.cache_put(key,rows,24*3600)
    return rows


async def weather(place, spec, store):
    if not 0 <= (spec.check_in-date.today()).days <= 15:
        return {'available':False,'reason':'Прогноз на эти даты пока недоступен. Точную погоду заранее не обещаем.'}
    key=f"weather:{place['id']}:{spec.check_in}"
    cached=store.cache_get(key)
    if cached is not None:return cached
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get('https://api.open-meteo.com/v1/forecast',params={'latitude':place['latitude'],'longitude':place['longitude'],'daily':'temperature_2m_max,temperature_2m_min,precipitation_probability_max','timezone':place['timezone'],'forecast_days':16});r.raise_for_status();days=r.json()['daily']
        rows=[{k:v[i] for k,v in days.items()} for i,d in enumerate(days['time']) if spec.check_in.isoformat()<=d<=spec.check_out.isoformat()]
        result={'available':bool(rows),'days':rows,'source':'Open-Meteo','source_url':'https://open-meteo.com/','retrieved_at':datetime.now(timezone.utc).isoformat()}
        store.cache_put(key,result,3600);return result
    except (httpx.HTTPError,ValueError,KeyError):return {'available':False,'reason':'Прогноз временно недоступен. Остальные данные поездки сохранены.'}

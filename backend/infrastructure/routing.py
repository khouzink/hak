"""Cached pedestrian routing. Public FOSSGIS <=1 req/s; replace endpoint to scale."""
import asyncio
import hashlib
import json
import math
import os
import time
from datetime import datetime,timezone
import httpx

_lock=asyncio.Lock()
_last_call=0.0

async def walking_route(args,store):
    global _last_call
    keys=('start_lon','start_lat','end_lon','end_lat')
    values=[args[k] for k in keys]
    if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in values):raise ValueError('Invalid coordinates')
    a,b,c,d=values
    if not(-180<=a<=180 and -180<=c<=180 and -90<=b<=90 and -90<=d<=90):raise ValueError('Invalid coordinates')
    provider=os.getenv('ROUTING_PROVIDER','osrm')
    base=os.getenv('OSRM_FOOT_URL','https://routing.openstreetmap.de/routed-foot').rstrip('/')
    cachekey='route:'+hashlib.sha256(json.dumps([provider,base,values]).encode()).hexdigest()
    cached=store.cache_get(cachekey)
    if cached is not None:return {**cached,'cache_hit':True}
    async with _lock:
        cached=store.cache_get(cachekey)
        if cached is not None:return {**cached,'cache_hit':True}
        await asyncio.sleep(max(0,1.1-(time.monotonic()-_last_call)))
        _last_call=time.monotonic()
        async with httpx.AsyncClient(timeout=15,headers={'User-Agent':'OdinZapros/1.0 (user-requested pedestrian itinerary; cached)'}) as client:
            if provider=='ors':
                key=os.getenv('ORS_API_KEY','')
                if not key:return {'available':False,'reason':'ORS_API_KEY required for selected ORS provider'}
                r=await client.post(os.getenv('ORS_BASE_URL','https://api.openrouteservice.org').rstrip('/')+'/v2/directions/foot-walking/geojson',headers={'Authorization':key},json={'coordinates':[[a,b],[c,d]]})
                r.raise_for_status();features=r.json().get('features',[])
                if not features:return {'available':False,'reason':'No walking route found'}
                summary=features[0]['properties']['summary'];source='openrouteservice foot-walking'
            elif provider=='osrm':
                r=await client.get(f'{base}/route/v1/foot/{a},{b};{c},{d}',params={'overview':'false','steps':'false','alternatives':'false'})
                r.raise_for_status();data=r.json()
                if data.get('code')!='Ok' or not data.get('routes'):return {'available':False,'reason':'No walking route found'}
                summary=data['routes'][0];source='OSRM foot / OpenStreetMap'
            else:raise ValueError('Unsupported routing provider')
    result={'available':True,'distance_m':summary['distance'],'duration_s':summary['duration'],'source':source,'source_url':base if provider=='osrm' else os.getenv('ORS_BASE_URL','https://api.openrouteservice.org'),'retrieved_at':datetime.now(timezone.utc).isoformat(),'attribution':'© OpenStreetMap contributors, ODbL; routing '+source,'is_estimate':True,'cache_hit':False,'limitations':'Walking estimate; stairs, accessibility, closures and safety are not guaranteed.'}
    store.cache_put(cachekey,result,int(os.getenv('ROUTE_CACHE_SECONDS','604800')))
    return result

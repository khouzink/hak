"""Read-only travel tools. Optional supplier rates require server-side credentials."""
from backend.infrastructure.live_sources import geocode, hotels, weather

TOOLS = [
 {'name':'weather_forecast','description':'Cached Open-Meteo forecast for a city and ISO date range. Reports unavailable outside forecast horizon; never substitutes climate averages.', 'inputSchema':{'type':'object','properties':{'city':{'type':'string','minLength':2},'check_in':{'type':'string','format':'date'},'check_out':{'type':'string','format':'date'}},'required':['city','check_in','check_out'],'additionalProperties':False}},
 {'name':'nearby_verified_pois','description':'Read cached, verified walking times from hotels to museums and theatres. No fabricated routes.', 'inputSchema':{'type':'object','properties':{'hotel_id':{'type':'string','minLength':2},'category':{'type':'string','enum':['museum','theatre','culture']}},'required':['hotel_id'],'additionalProperties':False}},
 {'name':'geocode_city','description':'Resolve a city using free Open-Meteo geocoding. No prices or availability.', 'inputSchema':{'type':'object','properties':{'city':{'type':'string','minLength':2}},'required':['city'],'additionalProperties':False}},
 {'name':'discover_hotels','description':'Discover public OSM hotel locations and facts; availability and rates are unknown.', 'inputSchema':{'type':'object','properties':{'city':{'type':'string','minLength':2}},'required':['city'],'additionalProperties':False}},
 {'name':'walking_route','description':'Get pedestrian distance and duration via cached open-source OSRM foot API (no key), or optional openrouteservice.', 'inputSchema':{'type':'object','properties':{'start_lon':{'type':'number'},'start_lat':{'type':'number'},'end_lon':{'type':'number'},'end_lat':{'type':'number'}},'required':['start_lon','start_lat','end_lon','end_lat'],'additionalProperties':False}},
 {'name':'search_hotel_rates','description':'Search LiteAPI hotel rates when configured; no reservations. Sandbox results are not live prices.', 'inputSchema':{'type':'object','properties':{'city':{'type':'string','minLength':2,'maxLength':100},'country_code':{'type':'string','pattern':'^[A-Z]{2}$'},'guest_nationality':{'type':'string','pattern':'^[A-Z]{2}$'},'currency':{'type':'string','pattern':'^[A-Z]{3}$'},'check_in':{'type':'string','format':'date'},'check_out':{'type':'string','format':'date'},'adults':{'type':'integer','minimum':1,'maximum':10}},'required':['city','country_code','guest_nationality','currency','check_in','check_out','adults'],'additionalProperties':False}},
 {'name':'search_flight_prices','description':'Search cached Aviasales flight prices; these are indicative, not live availability or confirmed fares.', 'inputSchema':{'type':'object','properties':{'origin':{'type':'string','pattern':'^[A-Z]{3}$'},'destination':{'type':'string','pattern':'^[A-Z]{3}$'},'departure_date':{'type':'string','format':'date'},'return_date':{'type':'string','format':'date'},'currency':{'type':'string','pattern':'^[A-Z]{3}$'}},'required':['origin','destination','departure_date','currency'],'additionalProperties':False}},
 {'name':'search_xotelo_rates','description':'Read Xotelo rates for a known Tripadvisor hotel key. No key required; rates require rechecking.', 'inputSchema':{'type':'object','properties':{'hotel_key':{'type':'string','pattern':'^g[0-9]+-d[0-9]+$'},'check_in':{'type':'string','format':'date'},'check_out':{'type':'string','format':'date'},'currency':{'type':'string','pattern':'^[A-Z]{3}$'},'adults':{'type':'integer','minimum':1,'maximum':32}},'required':['hotel_key','check_in','check_out','currency','adults'],'additionalProperties':False}},
]


async def execute_tool(name, args, store):
    if name not in {x['name'] for x in TOOLS}: raise ValueError('Unknown tool')
    schema = next(x['inputSchema'] for x in TOOLS if x['name']==name)
    if not isinstance(args,dict) or any(k not in args for k in schema['required']) or any(k not in schema['properties'] for k in args): raise ValueError('Invalid tool arguments')
    if name=='search_hotel_rates':
        from backend.infrastructure.liteapi import search_hotel_rates
        return await search_hotel_rates(args)
    if name=='search_flight_prices':
        from backend.infrastructure.aviasales import search_flight_prices
        return await search_flight_prices(args)
    if name=='search_xotelo_rates':
        from backend.infrastructure.xotelo import search_xotelo_rates
        return await search_xotelo_rates(args)
    if name=='nearby_verified_pois':
        from backend.infrastructure.poi_matrix import hotel_routes, snapshot
        hotel_id=args['hotel_id']
        if not isinstance(hotel_id,str) or len(hotel_id)>100:raise ValueError('Invalid hotel id')
        category=args.get('category')
        if category not in (None,'museum','theatre','culture'):raise ValueError('Invalid category')
        return {'hotel_id':hotel_id,'routes':hotel_routes(hotel_id,category)[:20],'verified':snapshot().get('status')=='verified','source':snapshot().get('source')}
    if name in ('geocode_city','discover_hotels','weather_forecast'):
        city=args['city']
        if not isinstance(city,str) or not 2<=len(city)<=100: raise ValueError('Invalid city')
        if name=='weather_forecast':
            from backend.domain.journey import JourneySpec
            spec=JourneySpec(destination=city,check_in=args['check_in'],check_out=args['check_out'])
            from datetime import date
            if not 0<=(spec.check_in-date.today()).days<=15:return {'available':False,'reason':'Dates are outside the forecast horizon; no substitute forecast is invented.'}
            return await weather(await geocode(city,store),spec,store)
        place=await geocode(city,store)
        if name=='geocode_city':return {'place':place,'source':'Open-Meteo geocoding'}
        found=await hotels(place,store)
        return {'place':place,'hotels':found[:30],'total_found':len(found),'rates_live':False,'availability_live':False,'source':'OpenStreetMap'}
    from backend.infrastructure.routing import walking_route
    return await walking_route(args,store)

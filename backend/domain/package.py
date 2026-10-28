"""Scenario transport and lodging assembly. All prices/schedules explicitly synthetic.

Real geography is separate. Time arithmetic is on UTC instants with IANA zones.
This module is pure and does not perform network or model calls.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from hashlib import sha256
import json
from backend.domain.journey import JourneySpec

TZ={'Москва':'Europe/Moscow','Казань':'Europe/Moscow','Санкт-Петербург':'Europe/Moscow','Екатеринбург':'Asia/Yekaterinburg','Калининград':'Europe/Kaliningrad','Сочи':'Europe/Moscow','Адлер':'Europe/Moscow','Сириус':'Europe/Moscow','Хургада':'Africa/Cairo','Шарм-эль-Шейх':'Africa/Cairo','Дубай':'Asia/Dubai','Стамбул':'Europe/Istanbul'}
MODEL_DESTINATIONS={'Сочи','Адлер','Сириус','Казань','Санкт-Петербург','Калининград','Стамбул','Хургада','Шарм-эль-Шейх','Дубай'}
PRIORITY_MODEL_MINUTES={'Эль-Гуна':290,'Марса-Алам':300,'Рас-эль-Хайма':310}
ORIGIN_CODES={'Москва':'SVO','Казань':'KZN','Санкт-Петербург':'LED','Екатеринбург':'SVX','Калининград':'KGD','Сочи':'AER','Адлер':'AER','Сириус':'AER'}
SLOTS={'morning':(9,40,0),'day':(13,20,1200),'evening':(20,30,-1800),'night':(0,30,-2400)}
RETURN_SLOTS={'morning':(8,0,-1000),'day':(17,20,0),'evening':(22,30,-1600),'night':(1,30,-2200)}

def add_minutes(value, minutes):
    return (value.astimezone(timezone.utc)+timedelta(minutes=minutes)).astimezone(value.tzinfo)

def segment(day, hour, minute, duration, origin_tz, destination_tz):
    departure=datetime.combine(day,time(hour,minute),ZoneInfo(origin_tz))
    arrival=(departure.astimezone(timezone.utc)+timedelta(minutes=duration)).astimezone(ZoneInfo(destination_tz))
    return departure,arrival

def shuttle_available(local_time, pets=False):
    """Hotel shuttles operate from 06:00 through 22:59 and do not carry pets."""
    return not pets and 6 <= local_time.hour < 23

def taxi_cost(base, night):
    """Model taxi price, including the specified 30% nighttime surcharge."""
    return round(base * 1.3) if night else base

def assemble(spec:JourneySpec,hotel:dict,rooms:int,nightly:list[int],version:str):
    target_tz=hotel.get('timezone') or TZ.get(spec.destination);origin_tz=TZ.get(spec.origin)
    target_known=bool(target_tz)
    target_tz=target_tz or 'Europe/Moscow'
    local=spec.origin.casefold()==spec.destination.casefold() or (spec.origin in {'Сочи','Адлер','Сириус'} and spec.destination in {'Сочи','Адлер','Сириус'})
    priority_route=spec.origin=='Москва' and spec.destination in PRIORITY_MODEL_MINUTES and not spec.transport=='train'
    model_route_known=bool(origin_tz and target_known and (local or spec.destination in MODEL_DESTINATIONS or priority_route))
    train=spec.transport=='train'
    duration=(1440 if spec.origin=='Москва' else 2100) if train else {'Москва':220,'Казань':210,'Санкт-Петербург':270,'Екатеринбург':250,'Калининград':300}.get(spec.origin,220)
    if spec.destination not in {'Сочи','Адлер','Сириус'}:
        duration={**PRIORITY_MODEL_MINUTES,'Казань':100,'Санкт-Петербург':100,'Калининград':170,'Стамбул':280,'Хургада':290,'Шарм-эль-Шейх':350,'Дубай':340}.get(spec.destination,220)
        if spec.origin!='Москва':duration+=60
        if train:duration=780
    if local:duration=0
    oh,om,delta=SLOTS[spec.outbound_slot];rh,rm,return_delta=RETURN_SLOTS[spec.inbound_slot]
    # Dates refer to arrival and departure at destination; night arrivals reserve prior night.
    travel_day=spec.check_in-(timedelta(days=1) if train or spec.outbound_slot=='evening' else timedelta())
    departure,arrival=segment(travel_day,oh,om,duration,origin_tz or 'Europe/Moscow',target_tz)
    if train:
        while arrival.date()<spec.check_in:departure=add_minutes(departure,1440);arrival=add_minutes(arrival,1440)
    if arrival.date()<spec.check_in and not train:
        departure=add_minutes(departure,1440);arrival=add_minutes(arrival,1440)
    ret_departure,home_arrival=segment(spec.check_out,rh,rm,duration,target_tz,origin_tz or 'Europe/Moscow')
    transfer_minutes={'sochi-park':25,'mercure-sochi':55,'azimut-vinogradnaya':65,'mantera-congress':25}.get(hotel['id'],25 if spec.destination=='Эль-Гуна' else 45)
    terminal_buffer=30 if train else 60
    airport_buffer=60 if train else 180
    hotel_arrival=add_minutes(arrival,terminal_buffer+transfer_minutes)
    pickup=add_minutes(ret_departure,-airport_buffer-transfer_minutes)
    standard_in=datetime.combine(hotel_arrival.date(),time(14),ZoneInfo(target_tz))
    early=hotel_arrival.hour<6
    previous_night=early or spec.outbound_slot=='night'
    checkin=hotel_arrival if previous_night or spec.early_checkin or hotel_arrival>=standard_in else standard_in
    hotel_start=hotel_arrival.date()-timedelta(days=1) if previous_night else hotel_arrival.date()
    hotel_end=spec.check_out
    checkout=datetime.combine(hotel_end,time(spec.late_checkout or 12),ZoneInfo(target_tz))
    if not spec.late_checkout and pickup<checkout:checkout=pickup
    wait_before=max(0,round((checkin-hotel_arrival).total_seconds()/60))
    wait_after=max(0,round((pickup-checkout).total_seconds()/60))
    people=spec.adults+len(spec.children_ages)
    transport=0 if local else (spec.adults*(7000 if train else 10000)+len(spec.children_ages)*(4500 if train else 7000))+people*(delta+return_delta)
    transport=max(0,transport)
    outbound_transfer=add_minutes(arrival,terminal_buffer)
    outbound_night=outbound_transfer.hour<6 or outbound_transfer.hour>=23
    return_night=pickup.hour<6 or pickup.hour>=23
    night_transfer=outbound_night or return_night
    transfers=taxi_cost(1250,outbound_night)+taxi_cost(1250,return_night)
    base_night=round(sum(nightly)/len(nightly)) if nightly else hotel['base_night']
    extra_nights=max(0,(spec.check_in-hotel_start).days)
    hotel_total=sum(nightly)*rooms+extra_nights*base_night*rooms
    child_charge=sum(a>=6 for a in spec.children_ages)*700*len(nightly)
    pet='pets' in spec.required or any(w in spec.wishes.casefold() for w in ['с собак','с кошк','с питом'])
    if 'pets' in spec.excluded_requirements:pet=False
    pet_fee=1000*len(nightly) if pet else 0
    extras=(round(base_night*.5)*rooms if spec.early_checkin and not previous_night else 0)+(round(base_night*.5)*rooms if spec.late_checkout else 0)+(600 if spec.children_ages else 0)+(2000 if pet and not local else 0)
    food=round((spec.adults+len(spec.children_ages)*.7)*800*(len(nightly)+1))
    items=[{'kind':'hotel','label':f'Отель: {len(nightly)+extra_nights} ночей, {rooms} ном.','amount':hotel_total+child_charge+pet_fee},
           {'kind':'transport','label':('Поезд' if train else 'Перелёт')+' туда и обратно · модель','amount':transport},
           {'kind':'transfer','label':'Трансферы в обе стороны · модель','amount':transfers},
           {'kind':'extras','label':'Кресло, питомец, ранний/поздний заезд · модель','amount':extras},
           {'kind':'food','label':'Резерв на питание · модель','amount':food},
           {'kind':'local','label':'Резерв на местные расходы','amount':2500+(3000 if hotel['id']=='azimut-vinogradnaya' else 0)}]
    total=sum(x['amount'] for x in items)
    checks=[]
    def check(code,status,label,fix=None):
        checks.append({'code':code,'status':status,'label':label,'source':'scenario_rules_v1','fix':fix})
    check('origin','ok' if origin_tz else 'error','Часовой пояс отправления известен' if origin_tz else 'Нет модели дороги из этого города')
    check('destination','ok' if target_known else 'error','Часовой пояс назначения проверен' if target_known else 'Неизвестный часовой пояс назначения')
    check('train_coverage','error' if train and spec.destination not in {'Москва','Казань','Санкт-Петербург','Сочи','Адлер','Сириус'} else 'ok','География демонстрационной модели транспорта проверена')
    check('duration','error' if not model_route_known or (spec.max_travel_hours and duration>spec.max_travel_hours*60) else 'ok',f'Время в пути по модели: {duration//60} ч {duration%60} мин' if model_route_known else 'Для этого направления время дороги не подтверждено; вариант исключён')
    check('budget','ok' if spec.budget_unlimited or total<=spec.budget else 'error',f'Итог на всех: {total} ₽')
    check('night_budget','ok' if spec.nightly_budget is None or max(nightly)<=spec.nightly_budget else 'error','Ограничение цены за ночь проверено')
    check('nights','ok' if hotel_start<=spec.check_in and hotel_end>hotel_start else 'error','Ночи покрыты; ночной приезд учитывает предыдущую ночь' if previous_night else 'Ночи проживания покрыты')
    check('arrival','attention' if wait_before else 'ok',f'До заселения {wait_before} мин' if wait_before else 'Приезд и заселение согласованы',{'label':'Ранний заезд (демо)','patch':{'early_checkin':True},'price':round(base_night*.5)*rooms} if wait_before else None)
    check('departure','error' if checkout>pickup else 'attention' if wait_after>60 and not spec.luggage_storage else 'ok','Поздний выезд конфликтует с отправлением' if checkout>pickup else f'Между выездом и трансфером {wait_after} мин' if wait_after>60 else 'Выезд и обратный транспорт согласованы',{'label':'Камера хранения (демо), бесплатно','patch':{'late_checkout':None,'luggage_storage':True},'price':0} if wait_after>60 or checkout>pickup else None)
    home_leave=add_minutes(departure,-airport_buffer-60)
    is_night=any(dt.hour<6 or dt.hour>=23 for dt in (home_leave,departure,arrival,hotel_arrival,pickup,ret_departure,home_arrival))
    check('night','error' if is_night and spec.no_night else 'attention' if is_night and spec.children_ages else 'ok','Ночной отрезок: учти при поездке с ребёнком' if is_night else 'Ночных отправлений и прибытий нет')
    check('transfers','ok','Модельный круглосуточный трансфер; ночная доплата включена' if night_transfer else 'Оба модельных трансфера согласованы')
    check('pets','ok' if not pet or hotel.get('pets') is True else 'error','Питомец: отель проверен по источнику, транспорт — модель' if pet else 'Без питомца')
    club='family' in spec.required or 'детский клуб' in spec.wishes.casefold()
    check('club_age','attention' if club else 'ok','Возраст допуска в клуб нужно уточнить у отеля; не обещаем присмотр' if club else 'Детский клуб не обязателен')
    out={'id':f'demo-{spec.transport}-{spec.outbound_slot}','kind':'train' if train else 'air','departure':departure.isoformat(),'arrival':arrival.isoformat(),'duration_minutes':duration,'route_model_known':model_route_known,'origin_timezone':origin_tz,'destination_timezone':target_tz,'origin_code':ORIGIN_CODES.get(spec.origin),'destination_code':ORIGIN_CODES.get(spec.destination),'mode':'synthetic'}
    back={'id':f'demo-return-{spec.inbound_slot}','kind':out['kind'],'departure':ret_departure.isoformat(),'arrival':home_arrival.isoformat(),'duration_minutes':duration,'route_model_known':model_route_known,'origin_timezone':target_tz,'destination_timezone':origin_tz,'mode':'synthetic'}
    steps=[]
    def step(id,title,at,code='transfers'):
        c=next((x for x in checks if x['code']==code),{'status':'ok'})
        steps.append({'id':id,'title':title,'at':at.isoformat(),'timezone':getattr(at.tzinfo,'key',str(at.tzinfo)),'status':c['status'],'check_code':code})
    step('home','Выезд из дома · рекомендация',add_minutes(departure,-airport_buffer-60))
    step('out','Отправление · демонстрационное расписание',departure,'night')
    step('arrive','Прибытие по местному времени',arrival)
    step('transfer','Трансфер в отель',add_minutes(arrival,terminal_buffer))
    step('checkin','Заселение · условия модели',checkin,'arrival')
    step('checkout','Выезд из номера',checkout,'departure')
    step('return-transfer','Трансфер к обратному отправлению',pickup,'departure')
    step('back','Обратное отправление · модель',ret_departure)
    step('home-arrive','Возвращение домой · рекомендация',add_minutes(home_arrival,60))
    payload={'hotel':hotel['id'],'spec':spec.model_dump(mode='json'),'version':version,'items':items}
    quote={'id':sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24],'hotel_total':items[0]['amount'],'total':total,'items':items,'rooms':rooms,'nights':len(nightly)+extra_nights,'nightly':nightly,'hotel_check_in':hotel_start.isoformat(),'hotel_check_out':hotel_end.isoformat(),'extra_nights':extra_nights,'budget_remaining':None if spec.budget_unlimited else spec.budget-total,'pricing_mode':'synthetic','inventory_mode':'synthetic','catalog_version':version,'assumptions':['Расписания, тарифы, трансферы и правила заезда — модель для хакатона, не реальные предложения.','География и публичные факты отеля отделены от модели.','Налоги и обязательные модельные сборы включены; питание и местные расходы — резерв.']}
    return {'quote':quote,'checks':checks,'timeline':steps,'outbound':out,'inbound':back,'transfer_options':{'outbound_shuttle_available':shuttle_available(outbound_transfer,pet),'return_shuttle_available':shuttle_available(pickup,pet),'selected':'taxi','mode':'synthetic'},'cancellation':{'free_until':datetime.combine(spec.check_in-timedelta(days=7),time(18),ZoneInfo(target_tz)).isoformat(),'penalty':items[0]['amount'],'mode':'synthetic'},'mode':'synthetic_schedule_and_rates'}

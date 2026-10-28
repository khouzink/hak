"""Pure, deterministic constraint checking and pricing. No LLM or network here."""
from datetime import timedelta
import math
import re
from backend.domain.journey import JourneySpec
from backend.domain.hotel_features import priority_evidence


def constraints(spec:JourneySpec):
    text=spec.wishes.casefold().replace('ё','е')
    def wanted(pattern,negative):return bool(re.search(pattern,text)) and not re.search(negative,text)
    flags={
      'pool':wanted(r'бассейн',r'без бассейн|бассейн не (?:нужен|важен)'),
      'family':wanted(r'детск\w* клуб|детск\w* комнат|анимац\w* для дет',r'без детск|клуб не нужен'),
      'pets':wanted(r'с собак|с кошк|с питом|питомец|собак\w* с нами|с нами\s+(?:едет|поедет|путешествует)\s+(?:собак|кошк|питом)',r'без питом|без собак|без кош'),
      'accessible':wanted(r'инвалид|коляс\w* доступ|безбарьер|на коляске',r'без ограничений'),
      'dietary':wanted(r'аллерг|безглютен|безлактоз|веган|халяль',r'нет аллерг|без аллерг'),
      'beachfront':wanted(r'обязательн\w*[^.]*перв\w* лини|только[^.]*перв\w* лини',r'не обязательн'),
      'breakfast':False, 'sea':False, 'office':False, 'culture':False,
    }
    for key in spec.required:
        if key in flags:flags[key]=True
    for key in spec.excluded_requirements:
        if key in flags:flags[key]=False
    return flags


def make_package(spec:JourneySpec,hotel:dict,version:str):
    nights=(spec.check_out-spec.check_in).days
    # These are scenario assumptions, not claims about the hotel's actual occupancy rules.
    rooms=max(math.ceil(spec.adults/2),math.ceil((spec.adults+len(spec.children_ages))/4))
    days=[spec.check_in+timedelta(days=i) for i in range(nights)]
    nightly=[round(hotel['base_night']*(1.3 if d.month in {6,7,8} else 1)*(1.1 if d.weekday() in {4,5} else 1)) for d in days]
    from backend.domain.package import assemble
    return assemble(spec,hotel,rooms,nightly,version)


def make_quote(spec:JourneySpec,hotel:dict,version:str):
    return make_package(spec,hotel,version)['quote']


def rank_hotels(spec:JourneySpec,hotels:list[dict],version:str):
    if spec.children_age_unknown:
        raise ValueError('Укажи возраст ребёнка перед расчётом поездки.')
    requested=constraints(spec)
    offers=[];rejected=[]
    transport_seen={'air':set(),'train':set()}
    for hotel in hotels:
        package=make_package(spec,hotel,version)
        for leg in (package['outbound'],package['inbound']):
            if leg.get('route_model_known') and leg.get('duration_minutes',0)>0 and leg.get('kind') in transport_seen:
                transport_seen[leg['kind']].add((leg.get('id'),leg.get('departure'),leg.get('arrival')))
        from backend.domain.consistency import verify_package
        package['checks'].extend(verify_package(package))
        package['proof']={
            'hotel_id':hotel['id'],
            'catalog_version':version,
            'hotel_source_url':hotel.get('source_url') or hotel.get('website'),
            'facts':[{'label':f.get('label'),'value':f.get('value'),'source':f.get('source')} for f in hotel.get('facts',[]) if isinstance(f,dict) and f.get('source')],
            'checks':[{'code':c['code'],'status':c['status'],'source':c['source']} for c in package['checks']],
            'price_mode':'synthetic',
            'notice':'Расписание, тарифы и доступность рассчитаны по модели; источники фактов указаны отдельно.',
        }
        quote=package['quote']
        violations=[{'field':c['code'],'reason':c['label']} for c in package['checks'] if c['status']=='error' and c['code']!='budget']
        if spec.min_stars and (not str(hotel.get('stars','')).isdigit() or int(hotel['stars'])<spec.min_stars):violations.append({'field':'stars','reason':'Требуемая звёздность не подтверждена'})
        for key,required in requested.items():
            evidence=priority_evidence(hotel,key) if required else None
            if required and evidence is not True:
                violations.append({'field':key,'reason':'не подтверждено источником' if evidence is None else 'не соответствует условию'})
        if requested['pets'] and re.search(r'кошк',spec.wishes,re.I):violations.append({'field':'pets','reason':'В базе подтверждены только условия для собак, не кошек'})
        weight=re.search(r'(\d+)\s*кг',spec.wishes,re.I)
        if requested['pets'] and weight and int(weight[1])>20:violations.append({'field':'pets','reason':'Вес собаки превышает подтверждённое ограничение 20 кг'})
        if requested['pets'] and weight and hotel['id']!='mercure-sochi':violations.append({'field':'pets','reason':'Допустимый вес питомца не подтверждён источником'})
        if not spec.budget_unlimited and quote['total']>spec.budget:violations.append({'field':'budget','reason':f"Не хватает {quote['total']-spec.budget} ₽ на полный модельный бюджет"})
        if violations:
            rejected.append({'hotel_id':hotel['id'],'name':hotel['name'],'violations':violations,'minimum_budget':quote['total']});continue
        reasons=[(f"Полный модельный бюджет {quote['total']:,} ₽" + (f"; остаток {quote['budget_remaining']:,} ₽" if not spec.budget_unlimited else '; лимит не задан')).replace(',',' ')]
        if requested['pool']:reasons.append('Собственный бассейн подтверждён публичным источником; условия доступа указаны в карточке')
        if requested['family']:reasons.append('Детская инфраструктура подтверждена источником')
        if requested['pets']:reasons.append('Подтверждено размещение с собакой до 20 кг' if hotel['id']=='mercure-sochi' else 'OSM отмечает разрешение на питомцев; вид, вес и условия нужно уточнить')
        score=(30 if spec.mood in hotel['moods'] else 0)+(15 if spec.children_ages and hotel['family'] else 0)+max(0,20*(1-quote['total']/max(spec.budget,1)))
        offers.append({**hotel,'quote':quote,'package':package,'reasons':reasons,'score':round(score,2)})
    offers.sort(key=lambda o:(-o['score'],o['quote']['total'],o['id']))
    for i,o in enumerate(offers):o['badge']='Лучший выбор' if i==0 else ('Дешевле' if o['quote']['total']==min(x['quote']['total'] for x in offers) else 'Другой вариант')
    relaxations=[]
    budget_only=[r for r in rejected if all(v['field']=='budget' for v in r['violations'])]
    if not offers and budget_only:
        minimum=min(r['minimum_budget'] for r in budget_only)
        relaxations.append({'field':'budget','value':minimum,'label':f'Увеличить бюджет до {minimum:,} ₽'.replace(',',' '),'requires_confirmation':True})
    if not offers:
        for key,label in {'pool':'бассейн','family':'детскую инфраструктуру','pets':'размещение с питомцем','accessible':'безбарьерную среду','dietary':'специальное питание','beachfront':'первую линию'}.items():
            if requested.get(key) and any(r['violations'] and all(v['field']==key for v in r['violations']) for r in rejected):
                relaxations.append({'field':key,'label':f'Искать без обязательного требования: {label}','patch':{'excluded_requirements':list(set(spec.excluded_requirements+[key])),'required':[k for k in spec.required if k!=key]},'requires_confirmation':True})
    return {'offers':offers[:3],'alternatives':offers[3:10],'matched_count':len(offers),'rejected':rejected,'relaxations':relaxations,'constraints':requested,'scanned':len(hotels),'flights_scanned':len(transport_seen['air']),'trains_scanned':len(transport_seen['train']),'catalog_version':version,'mode':'synthetic_rates_public_facts','coverage':spec.destination}

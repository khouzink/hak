"""Deterministic budget trade-offs on demo hotel quotations. Never asserts real rates."""
from backend.domain.hotel_planner import make_quote,rank_hotels
from backend.domain.hotel_features import priority_evidence

PRIORITIES = {'pool':'Бассейн', 'family':'Детская инфраструктура', 'pets':'С питомцем', 'breakfast':'Завтрак', 'sea':'Вид на море', 'office':'Близко к офису', 'culture':'Музеи и театры пешком'}

def optimize(spec, hotels, version, priorities=None, must_have=None):
    priorities = priorities or {}
    must_have = set(must_have or [])
    unknown = (set(priorities)|must_have)-set(PRIORITIES)
    if unknown: raise ValueError('Неизвестные приоритеты: '+', '.join(sorted(unknown)))
    candidates=[]
    strict=rank_hotels(spec.model_copy(update={'budget_unlimited':True}),hotels,version)
    rejected={h['hotel_id'] for h in strict['rejected']}
    permitted={h['id'] for h in hotels if h['id'] not in rejected}
    for h in hotels:
        if h['id'] not in permitted:continue
        q=make_quote(spec,h,version)
        evidence={k:priority_evidence(h,k) for k in PRIORITIES}
        if any(evidence[k] is not True for k in must_have):continue
        score=sum(int(weight)*(1 if evidence[k] is True else 0) for k,weight in priorities.items())
        candidates.append({'hotel_id':h['id'],'hotel_name':h['name'],'total':q['total'],'quote':q,'score':score,'evidence':evidence,'tradeoff':h.get('tradeoff',''),'pricing_mode':'synthetic'})
    if not candidates:return {'best':None,'cheaper':None,'upgrade':None,'options':[],'reason':'Нет отелей, удовлетворяющих обязательным условиям; неизвестные свойства не считаются подтверждёнными.'}
    affordable=[c for c in candidates if spec.budget_unlimited or c['total']<=spec.budget]
    ranked=sorted(affordable,key=lambda c:(-c['score'],c['total'],c['hotel_id']))
    best=ranked[0] if ranked else None
    pivot=best['total'] if best else spec.budget
    cheaper=min((c for c in candidates if c['total']<pivot),key=lambda c:(-c['score'],c['total']),default=None)
    upgrade=min((c for c in candidates if c['total']>pivot),key=lambda c:(c['total'],-c['score']),default=None)
    def explain(c,base):
        if not c:return None
        c={**c,'delta':c['total']-(base['total'] if base else spec.budget)}
        c['differences']=[{'feature':PRIORITIES[k],'value':c['evidence'][k],'baseline':base['evidence'][k] if base else None} for k in priorities if not base or c['evidence'][k]!=base['evidence'][k]]
        return c
    return {'best':explain(best,best),'cheaper':explain(cheaper,best),'upgrade':explain(upgrade,best),'options':sorted(candidates,key=lambda c:(-c['score'],c['total'])),'reason':None if best else 'В бюджете нет подтверждённых вариантов; показаны доступные альтернативы.','notice':'Все суммы — модельные; разница цен не доказывает стоимость конкретного удобства.','solver':'deterministic_exhaustive_exact'}

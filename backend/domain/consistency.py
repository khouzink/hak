"""Independent checks over an assembled package, without invoking its generator."""
from datetime import datetime, timezone
from math import isfinite


def verify_package(package):
    findings=[]
    timeline=package.get('timeline') or []
    expected=['home','out','arrive','transfer','checkin','checkout','return-transfer','back','home-arrive']
    if [step.get('id') for step in timeline] != expected:
        findings.append(('timeline_structure','Неполный или неверный порядок шагов поездки.'))
    else:
        try:
            times=[datetime.fromisoformat(step['at']) for step in timeline]
            if any(t.utcoffset() is None for t in times): raise ValueError('Missing timezone')
            utc=[t.astimezone(timezone.utc) for t in times]
            if any(a>b for a,b in zip(utc,utc[1:])):
                findings.append(('timeline_order','Шаги поездки не согласованы по времени.'))
        except (KeyError, TypeError, ValueError):
            findings.append(('timeline_time','Время поездки или часовой пояс не подтверждены.'))
    quote=package.get('quote') or {}
    items=quote.get('items')
    if not isinstance(items,list) or not items or any(not isinstance(item,dict) or type(item.get('amount')) not in (int,float) or not isfinite(item['amount']) or item['amount']<0 for item in items):
        findings.append(('cost_items','Не подтверждены все составляющие стоимости.'))
    elif type(quote.get('total')) not in (int,float) or sum(item['amount'] for item in items)!=quote['total']:
        findings.append(('cost_total','Итоговая сумма не совпадает с составляющими.'))
    return [{'code':code,'status':'error','label':message,'source':'independent_consistency_v1','fix':None} for code,message in findings]

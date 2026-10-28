"""MCP tools over the linear flow: plan_trip and trip_details. Read-only, demo prices, no booking.

They live in the flow package so the infrastructure layer does not depend on the product path;
backend/presentation/mcp.py lists them next to the free travel tools and routes calls here.
"""
from backend.domain.errors import Conflict
from backend.flow import data, screens
from backend.flow.intake import understand
from backend.flow.model import FlowSpec

FLOW_TOOLS = [
    {'name':'plan_trip','description':'О!дин запрос: one free-text trip request (Russian) → what the agent understood, up to 3 destinations or a district and 3 hotels with trade-offs. Hotel facts from OpenStreetMap with sources; prices, rooms and flights are a demo model. No booking.', 'inputSchema':{'type':'object','properties':{'text':{'type':'string','minLength':2,'maxLength':500},'destination_id':{'type':'string','maxLength':40}},'required':['text'],'additionalProperties':False}},
    {'name':'trip_details','description':'О!дин запрос: for a request and a hotel id from plan_trip — what is promised vs confirmed (with sources), who it does not suit, arrival → check-in → check-out timeline in local time zones, and the full demo price.', 'inputSchema':{'type':'object','properties':{'text':{'type':'string','minLength':2,'maxLength':500},'destination_id':{'type':'string','maxLength':40},'hotel_id':{'type':'string','minLength':2,'maxLength':80}},'required':['text','hotel_id'],'additionalProperties':False}},
]


def _flow_spec(args):
    u = understand(args['text'])
    if u['status'] == 'offtopic':
        raise ValueError('Not a travel request')
    spec = FlowSpec.model_validate(u['spec'])
    did = args.get('destination_id')
    if did:
        if did not in data.DEST:
            raise ValueError('Unknown destination_id')
        spec = spec.model_copy(update={'destination': did})
    return u, spec


def flow_tool(name, args):
    u, spec = _flow_spec(args)
    understood = [{'title': c['title'], 'value': c['value'], 'source': c['source']} for c in u['chips']]
    if name == 'plan_trip':
        if not spec.destination:
            d = screens.destinations(spec)
            return {'understood': understood, 'destinations': [{k: c[k] for k in ('id', 'name', 'country', 'label', 'character', 'road_text', 'price_text', 'why', 'tradeoff')} | {'weather': (c['weather'] or {}).get('text')} for c in d['cards']], 'note': d['note'], 'next': 'call plan_trip again with destination_id', 'prices': 'demo'}
        p = screens.places(spec)
        return {'understood': understood, 'destination': p['destination']['name'], 'district': next((x['name'] for x in p['districts'] if x['selected']), None),
                'hotels': [{k: c[k] for k in ('id', 'label', 'name', 'stars', 'district', 'total', 'tradeoff', 'checkin_note')} | {'facts': [f['text'] for f in c['facts']]} for c in p['cards']],
                'note': p['note'], 'relax': [r['label'] for r in p['relax']], 'prices': 'demo'}
    h = screens.hotel_detail(spec, args['hotel_id'])
    return {'name': h['name'], 'promised': [{k: r[k] for k in ('title', 'status', 'text', 'source')} for r in h['promised']], 'not_for': h['not_for'], 'risks': h['risks'],
            'timeline': [f"{s['date']} {s['time']} {s['tz']}: {s['title']}" for s in h['timeline']['steps']], 'checks': [c['label'] for c in h['timeline']['checks']],
            'price': [{'label': r['label'], 'amount': r['amount']} for r in h['breakdown']], 'total': h['total'], 'prices': 'demo'}


def call(name, args):
    schema = next(x['inputSchema'] for x in FLOW_TOOLS if x['name'] == name)
    if not isinstance(args, dict) or any(k not in args for k in schema['required']) or any(k not in schema['properties'] for k in args):
        raise ValueError('Invalid tool arguments')
    try:
        return flow_tool(name, args)
    except Conflict as exc:
        raise ValueError(str(exc)) from exc

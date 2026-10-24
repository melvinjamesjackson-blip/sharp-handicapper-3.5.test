#!/usr/bin/env python3
"""Build research-only CFB first-half history from ESPN scoreboard quarter scores.

Unofficial endpoint: check coverage and terms before relying on the dataset.
No live score predictions are modified. Python stdlib only.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API='https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard'

def fetch(year, week, season_type, tries=3):
    params={'dates':str(year),'week':str(week),'seasontype':str(season_type),'groups':'80','limit':'500'}
    url=API+'?'+urlencode(params)
    for attempt in range(tries):
        try:
            with urlopen(Request(url,headers={'User-Agent':'SharpHandicapperResearch/1.0','Accept':'application/json'}),timeout=35) as response:
                data=json.load(response)
            if not isinstance(data.get('events'),list): raise ValueError('Missing events list')
            return data['events']
        except Exception:
            if attempt==tries-1: raise
            time.sleep(2*(attempt+1))

def quarter_scores(comp):
    arr=comp.get('linescores') or []
    if not isinstance(arr,list) or len(arr)<2: return None
    scores=[]
    for item in arr[:2]:
        v=item.get('value') if isinstance(item,dict) else item
        try:
            n=float(v)
            if not n.is_integer() or n<0: return None
            scores.append(int(n))
        except (ValueError,TypeError,OverflowError): return None
    return scores

def parse_event(ev):
    if not ev.get('status',{}).get('type',{}).get('completed'): return None
    comps=ev.get('competitions') or []
    if not comps: return None
    competition=comps[0]
    if not competition.get('status',ev.get('status',{})).get('type',{}).get('completed'): return None
    byrole={c.get('homeAway'):c for c in competition.get('competitors',[])}
    if set(byrole)!={'home','away'}: return None
    h,a=byrole['home'],byrole['away']
    hq,aq=quarter_scores(h),quarter_scores(a)
    if hq is None or aq is None: return None
    date=(competition.get('date') or ev.get('date') or '')[:10]
    if len(date)!=10: return None
    try: datetime.strptime(date,'%Y-%m-%d')
    except ValueError: return None
    try:
        hs,aws=int(float(h['score'])),int(float(a['score']))
    except (ValueError,TypeError,KeyError): return None
    if sum(hq)>hs or sum(aq)>aws: return None
    return {'event_id':str(ev['id']),'date':date,'season':int(ev.get('season',{}).get('year') or date[:4]),
            'week':int(ev.get('week',{}).get('number') or 0),
            'home':h.get('team',{}).get('displayName',''),'away':a.get('team',{}).get('displayName',''),
            'home_team_id':str(h.get('team',{}).get('id','')),'away_team_id':str(a.get('team',{}).get('id','')),
            'home_q1':hq[0],'home_q2':hq[1],'away_q1':aq[0],'away_q2':aq[1],
            'home_1h':sum(hq),'away_1h':sum(aq),'home_final':hs,'away_final':aws,
            'source':'ESPN scoreboard'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--start-year',type=int,default=2024)
    p.add_argument('--end-year',type=int,default=datetime.now(timezone.utc).year)
    p.add_argument('--output',default='data/cfb_1h_history.json')
    p.add_argument('--max-weeks',type=int,default=17)
    args=p.parse_args()
    if args.start_year>args.end_year: p.error('start-year must be <= end-year')
    rows={}; failures=[]; queries=0; completed_without_quarters=0
    for year in range(args.start_year,args.end_year+1):
        for season_type,max_week in ((2,args.max_weeks),(3,5)):
            for week in range(1,max_week+1):
                try: events=fetch(year,week,season_type)
                except Exception as e:
                    failures.append(f'{year} type={season_type} week={week}: {str(e)[:120]}')
                    continue
                queries+=1
                for ev in events:
                    rec=parse_event(ev)
                    if rec: rows[rec['event_id']]=rec
                    elif ev.get('status',{}).get('type',{}).get('completed'): completed_without_quarters+=1
                time.sleep(0.1)
    if not rows: raise SystemExit('ERROR: zero verified quarter-score games; refusing to publish an empty dataset. Failures: '+str(failures[:3]))
    if failures: raise SystemExit(f'ERROR: {len(failures)} source queries failed; refusing incomplete overwrite. Example: {failures[0]}')
    games=sorted(rows.values(),key=lambda r:(r['date'],r['event_id']))
    counts={}
    for g in games: counts[str(g['season'])]=counts.get(str(g['season']),0)+1
    payload={'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),
        'source':'ESPN college-football scoreboard (unofficial)',
        'coverage_note':'FBS groups=80; only completed games with verified Q1 and Q2 for both teams; not guaranteed exhaustive.',
        'seasons':counts,'games_count':len(games),'queries_succeeded':queries,
        'completed_events_missing_valid_quarters':completed_without_quarters,'games':games}
    dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(payload,separators=(',',':'))+'\n',encoding='utf-8');tmp.replace(dest)
    print(f'Wrote {len(games)} verified quarter-score games to {dest}; seasons={counts}; source queries={queries}')
if __name__=='__main__': main()

#!/usr/bin/env python3
"""Read unofficial ESPN NFL injury feed and produce a fail-closed, auditable snapshot."""
import datetime as dt
import json
import os
import pathlib
import urllib.request

URL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries'
OUT = pathlib.Path('data/nfl_injuries.json')
TEAMS = set('ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS'.split())

def normalize_status(raw):
    s = str(raw or '').strip().lower()
    if s in ('out','doubtful','questionable','active','confirmed active','unknown'): return s
    if s in ('injured reserve','ir','out for season','physically unable to perform','pup','non-football injury','nfi','suspended'): return 'out'
    if s in ('day-to-day','game-time decision','gtd','probable'): return 'questionable'
    return 'unknown'

def main():
    req = urllib.request.Request(URL, headers={'User-Agent':'SharpHandicapperInjuryAudit/0.1', 'Accept':'application/json'})
    with urllib.request.urlopen(req, timeout=35) as response:
        raw = response.read(16_000_001)
        if len(raw) > 16_000_000: raise RuntimeError('Feed exceeds size limit')
    data = json.loads(raw)
    groups = data.get('injuries') if isinstance(data,dict) else None
    if not isinstance(groups,list) or not groups: raise RuntimeError('Unexpected or empty league-wide ESPN injury schema; old file retained')
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    records=[]; seen=set(); bad=0
    for group in groups:
        if not isinstance(group,dict): bad+=1;continue
        team_obj=group.get('team') or {}
        team=str(team_obj.get('abbreviation') or '').upper().strip() if isinstance(team_obj,dict) else ''
        team={'LA':'LAR','WSH':'WAS','JAC':'JAX','OAK':'LV'}.get(team,team)
        entries=group.get('injuries')
        if not isinstance(entries,list): bad+=1;continue
        for item in entries:
            if not isinstance(item,dict):bad+=1;continue
            athlete=item.get('athlete') or {}
            if not isinstance(athlete,dict):bad+=1;continue
            name=str(athlete.get('fullName') or athlete.get('displayName') or '').strip()
            pos=athlete.get('position') or {}
            position=str(pos.get('abbreviation') or '').strip().upper() if isinstance(pos,dict) else ''
            raw_status=item.get('status')
            if isinstance(raw_status,dict): raw_status=raw_status.get('displayName') or raw_status.get('name')
            if team not in TEAMS or not name or not position: bad+=1;continue
            ident=(team,str(athlete.get('id') or name).lower())
            if ident in seen:continue
            seen.add(ident)
            records.append({'team':team,'player':name,'position':position,'status':normalize_status(raw_status),
                            'raw_status':str(raw_status or ''),'source_url':URL,'updated_at':now,
                            'timestamp_meaning':'retrieved_at; original per-player report time not verified',
                            'player_id':str(athlete.get('id') or ''),
                            'source':'ESPN unofficial site endpoint'})
    print(f"ESPN groups received: {len(groups)}", flush=True)
    print(f"Valid players: {len(records)}", flush=True)
    print(f"Malformed entries: {bad}", flush=True)
    print(f"Teams found: {sorted({r['team'] for r in records})}", flush=True)
    for group in groups[:2]:
        if isinstance(group, dict):
            print(f"Group keys: {list(group.keys())}", flush=True)
            print(f"Team: {str(group.get('team'))[:300]}", flush=True)
            entries = group.get('injuries')
            print(f"Entries type: {type(entries).__name__}", flush=True)
            if isinstance(entries, list) and entries:
                print(f"First entry: {str(entries[0])[:800]}", flush=True)     
    # Reject suspiciously incomplete data, rather than publish an empty/partial snapshot.
    if len(records)<20 or len({r['team'] for r in records})<8:
        raise RuntimeError(f'Only {len(records)} player records across {len({r["team"] for r in records})} teams; old file retained')
    if bad>len(records):raise RuntimeError(f'Too many malformed entries ({bad}); old file retained')
    snapshot={'published_at':now,'players':sorted(records,key=lambda r:(r['team'],r['player'])),
              'feed_source_url':URL,'feed_type':'unofficial ESPN current injury listing',
              'source_report_time_verified':False,
              'disclaimer':'updated_at is retrieval time, not verified medical report timestamp; no impact estimates'}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    temp=OUT.with_suffix('.json.tmp');temp.write_text(json.dumps(snapshot,indent=2)+'\n',encoding='utf-8');temp.replace(OUT)
    print(f'Published {len(records)} records across {len({r["team"] for r in records})} teams; {bad} malformed rows skipped')
if __name__=='__main__': main()

#!/usr/bin/env python3
"""Fetch ESPN's unofficial NFL injury listing; validate before atomic publication."""
import datetime as dt
import json
import pathlib
import urllib.request

URL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries'
OUT = pathlib.Path('data/nfl_injuries.json')
TEAMS = set('ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS'.split())
ALIASES = {'LA': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX', 'OAK': 'LV'}
# ESPN's league-wide endpoint currently groups by team ID/displayName rather than team object.
# Stable ESPN NFL team identifiers.
ESPN_IDS = dict(zip(
    ['1','2','3','4','5','6','7','8','9','10','11','12','13','14','15','16','17','18','19','20','21','22','23','24','25','26','27','28','29','30','33','34'],
    ['ATL','BUF','CHI','CIN','CLE','DAL','DEN','DET','GB','TEN','IND','KC','LV','LAR','MIA','MIN','NE','NO','NYG','NYJ','PHI','ARI','PIT','LAC','SF','SEA','TB','WAS','CAR','JAX','BAL','HOU']
))
NAMES = {
    'cardinals':'ARI','falcons':'ATL','ravens':'BAL','bills':'BUF','panthers':'CAR','bears':'CHI',
    'bengals':'CIN','browns':'CLE','cowboys':'DAL','broncos':'DEN','lions':'DET','packers':'GB',
    'texans':'HOU','colts':'IND','jaguars':'JAX','chiefs':'KC','chargers':'LAC','rams':'LAR',
    'raiders':'LV','dolphins':'MIA','vikings':'MIN','patriots':'NE','saints':'NO','giants':'NYG',
    'jets':'NYJ','eagles':'PHI','steelers':'PIT','seahawks':'SEA','49ers':'SF',
    'buccaneers':'TB','titans':'TEN','commanders':'WAS'
}

def team_code(group):
    obj = group.get('team')
    if isinstance(obj, dict):
        code = str(obj.get('abbreviation') or '').upper().strip()
        code = ALIASES.get(code, code)
        if code in TEAMS:
            return code
    code = ESPN_IDS.get(str(group.get('id') or ''))
    if code:
        return code
    name = str(group.get('displayName') or '').strip().lower()
    for nickname, abbr in NAMES.items():
        if name == nickname or name.endswith(' ' + nickname):
            return abbr
    return ''

def normalize_status(raw):
    s = str(raw or '').strip().lower()
    if s in ('out','doubtful','questionable','active','confirmed active','unknown'):
        return 'active' if s == 'confirmed active' else s
    if s in ('injured reserve','ir','out for season','physically unable to perform','pup',
             'non-football injury','nfi','suspended'):
        return 'out'
    if s in ('day-to-day','game-time decision','gtd','probable'):
        return 'questionable'
    return 'unknown'

def main():
    request = urllib.request.Request(URL, headers={
        'User-Agent': 'SharpHandicapperInjuryAudit/0.2', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=35) as response:
        raw = response.read(16_000_001)
    if len(raw) > 16_000_000:
        raise RuntimeError('Feed exceeds size limit; old file retained')
    data = json.loads(raw)
    groups = data.get('injuries') if isinstance(data, dict) else None
    if not isinstance(groups, list) or not groups:
        raise RuntimeError('Unexpected or empty ESPN injury schema; old file retained')
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    records, seen, bad = [], set(), 0
    unknown_groups = []
    for group in groups:
        if not isinstance(group, dict):
            bad += 1
            continue
        team = team_code(group)
        if team not in TEAMS:
            unknown_groups.append((str(group.get('id')), str(group.get('displayName'))))
            continue
        entries = group.get('injuries')
        if not isinstance(entries, list):
            bad += 1
            continue
        for item in entries:
            if not isinstance(item, dict):
                bad += 1
                continue
            athlete = item.get('athlete')
            if not isinstance(athlete, dict):
                bad += 1
                continue
            name = str(athlete.get('fullName') or athlete.get('displayName') or '').strip()
            if not name:
                bad += 1
                continue
            pos = athlete.get('position') or item.get('position') or {}
            position = str(pos.get('abbreviation') or '').strip().upper() if isinstance(pos, dict) else str(pos or '').strip().upper()
            raw_status = item.get('status')
            if isinstance(raw_status, dict):
                raw_status = raw_status.get('displayName') or raw_status.get('name')
            ident = (team, str(athlete.get('id') or name).lower())
            if ident in seen:
                continue
            seen.add(ident)
            records.append({
                'team': team, 'player': name, 'position': position or 'UNKNOWN',
                'status': normalize_status(raw_status), 'raw_status': str(raw_status or ''),
                'source_url': URL, 'updated_at': now,
                'timestamp_meaning': 'retrieved_at; original per-player report time not verified',
                'player_id': str(athlete.get('id') or ''),
                'source': 'ESPN unofficial site endpoint'})
    covered = {r['team'] for r in records}
    print(f'ESPN groups: {len(groups)}; players: {len(records)}; teams: {len(covered)}; malformed: {bad}', flush=True)
    if unknown_groups:
        print(f'Unrecognized team groups: {unknown_groups[:10]}', flush=True)
    if len(records) < 20 or len(covered) < 8:
        raise RuntimeError(f'Only {len(records)} player records across {len(covered)} teams; old file retained')
    if unknown_groups or bad > len(records):
        raise RuntimeError('Unrecognized groups or excessive malformed entries; old file retained')
    snapshot = {
        'published_at': now,
        'players': sorted(records, key=lambda r: (r['team'], r['player'])),
        'feed_source_url': URL, 'feed_type': 'unofficial ESPN current injury listing',
        'source_report_time_verified': False,
        'disclaimer': 'updated_at is retrieval time, not verified medical report timestamp; no impact estimates'
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(snapshot, indent=2) + '\n', encoding='utf-8')
    temp.replace(OUT)
    print(f'Published {len(records)} records across {len(covered)} teams', flush=True)

if __name__ == '__main__':
    main()


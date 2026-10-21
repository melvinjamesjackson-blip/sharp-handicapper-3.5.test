"""Build leakage-safe pre-week NFL efficiency snapshots from nflverse 2026 PBP.
Raw (not opponent-adjusted) efficiencies; SOS proxy uses prior opponent EPA only.
"""
import io, json, os, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

URL='https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.parquet'
COLUMNS=['season','week','season_type','game_id','posteam','defteam','play_type','epa','success','yards_gained','game_date']
OUTPUT=Path(__file__).resolve().parents[1]/'data'/'nfl_epa_2026.json'

def norm(t):
    t=str(t).strip().upper()
    return 'LAR' if t=='LA' else t

def mean(df,col):
    v=pd.to_numeric(df[col],errors='coerce').dropna()
    return round(float(v.mean()),6) if len(v) else 0.0

def run():
    req=urllib.request.Request(URL,headers={'User-Agent':'SharpHandicapperResearch/1.0'})
    with urllib.request.urlopen(req,timeout=150) as r: raw=r.read()
    pbp=pd.read_parquet(io.BytesIO(raw),columns=COLUMNS)
    pbp=pbp[(pbp.season==2026)&(pbp.season_type=='REG')&pbp.play_type.isin(['pass','run'])].copy()
    pbp=pbp[pbp.posteam.notna()&pbp.defteam.notna()&pbp.epa.notna()]
    pbp['posteam']=pbp.posteam.map(norm);pbp['defteam']=pbp.defteam.map(norm)
    pbp['week']=pd.to_numeric(pbp.week,errors='coerce')
    pbp=pbp[pbp.week.between(1,25)]
    pbp['explosive']=((pbp.play_type.eq('pass') & (pbp.yards_gained>=20)) | (pbp.play_type.eq('run') & (pbp.yards_gained>=10))).astype(float)
    # A completed game requires a final result in the separate schedules feed.
    # This builder conservatively includes only weeks strictly BEFORE the current calendar week
    # using game dates plus a 48-hour completion buffer. This is a freshness heuristic, not a final-score verification.
    cutoff=pd.Timestamp.now(tz='UTC')-pd.Timedelta(hours=48)
    dates=pd.to_datetime(pbp.game_date,errors='coerce',utc=True)
    pbp=pbp[dates<cutoff]
    if pbp.empty: raise ValueError('No eligible completed-age 2026 play data; existing published feed left unchanged')
    max_week=int(pbp.week.max())
    teams=sorted(set(pbp.posteam)|set(pbp.defteam))
    records=[]
    for week in range(1,max_week+2):
        prior=pbp[pbp.week<week]
        if prior.empty:continue
        for team in teams:
            off=prior[prior.posteam==team]; de=prior[prior.defteam==team]
            if off.empty or de.empty:continue
            pa=off[off.play_type=='pass'];ru=off[off.play_type=='run']
            opponents=prior.loc[prior.posteam==team,['game_id','defteam']].drop_duplicates().defteam.tolist()
            # SOS proxy: opponents' offensive EPA from strictly earlier weeks; excludes team-v-opponent plays.
            opp=prior[prior.posteam.isin(opponents)&(prior.defteam!=team)]
            sos=mean(opp,'epa') if len(opp) else 0.0
            records.append({'season':2026,'week':week,'team':team,'games_prior':int(off.game_id.nunique()),
              'sos_net_epa':sos,'adjusted_off_pass_epa':mean(pa,'epa'),'adjusted_off_rush_epa':mean(ru,'epa'),
              'adjusted_off_epa_per_play':mean(off,'epa'),'adjusted_def_allowed_epa_per_play':mean(de,'epa'),
              'adjusted_off_pass_success':mean(pa,'success'),'adjusted_off_rush_success':mean(ru,'success'),
              'adjusted_off_success_rate':mean(off,'success'),'adjusted_def_allowed_success_rate':mean(de,'success'),
              'adjusted_off_explosive_rate':mean(off,'explosive'),'adjusted_def_allowed_explosive_rate':mean(de,'explosive')})
    if not records:raise ValueError('No pregame snapshots created; existing feed left unchanged')
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    payload={'source':URL,'generated_utc':datetime.now(timezone.utc).isoformat(),'season':2026,
      'method':'RAW_UNADJUSTED_EPA_AND_SUCCESS; SOS proxy from prior opponent offense; 48h game-date buffer; research only',
      'max_completed_age_week':max_week,'rows':records}
    tmp=OUTPUT.with_suffix('.tmp');tmp.write_text(json.dumps(payload,separators=(',',':')));tmp.replace(OUTPUT)
    print(f'Wrote {len(records)} rows, max age-eligible week {max_week}')
if __name__=='__main__':run()


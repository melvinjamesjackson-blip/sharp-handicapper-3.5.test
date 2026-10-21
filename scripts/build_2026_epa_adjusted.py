"""Research-only, pre-week opponent-adjusted NFL efficiency snapshots.

Uses nflverse 2026 PBP. Each snapshot for week W uses only games in weeks < W
that are at least 48 hours old. Age is NOT confirmation of a final score.
Fits regularized additive offense/defense opponent effects using weighted
team-opponent play aggregates. Does not modify raw EPA feed or score model.
"""
import io, json, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

URL='https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.parquet'
COLUMNS=['season','week','season_type','game_id','posteam','defteam','play_type','epa','success','yards_gained','game_date']
OUTPUT=Path(__file__).resolve().parents[1]/'data'/'nfl_epa_2026_adjusted.json'

def norm(x):
    t=str(x).strip().upper()
    return 'LAR' if t=='LA' else t

def fit(prior, teams, metric, kind=None, shrink_plays=250):
    """Ridge solve: metric = global mean + offense effect + defense effect.
    Uses play counts as weights; ridge shrinks each team effect to zero.
    A positive defense effect means more EPA/success allowed (worse defense).
    """
    frame=prior if kind is None else prior[prior.play_type.eq(kind)]
    frame=frame[pd.to_numeric(frame[metric],errors='coerce').notna()]
    n=len(teams)
    if frame.empty:return None
    mu=float(frame[metric].mean())
    groups=frame.groupby(['posteam','defteam'])[metric].agg(['count','mean'])
    idx={t:i for i,t in enumerate(teams)}
    matrix=np.eye(2*n)*shrink_plays
    vector=np.zeros(2*n)
    for (off,defn),g in groups.iterrows():
        if off not in idx or defn not in idx:continue
        i,j=idx[off],n+idx[defn]
        w=float(g['count']);v=float(g['mean'])-mu
        matrix[i,i]+=w;matrix[j,j]+=w
        matrix[i,j]+=w;matrix[j,i]+=w
        vector[i]+=w*v;vector[j]+=w*v
    coefs=np.linalg.solve(matrix,vector)
    return mu,coefs[:n],coefs[n:]

def run():
    req=urllib.request.Request(URL,headers={'User-Agent':'SharpHandicapperResearch/1.0'})
    with urllib.request.urlopen(req,timeout=150) as response:
        pbp=pd.read_parquet(io.BytesIO(response.read()),columns=COLUMNS)
    pbp=pbp[(pbp.season==2026)&(pbp.season_type=='REG')&pbp.play_type.isin(['pass','run'])].copy()
    pbp=pbp[pbp.posteam.notna()&pbp.defteam.notna()&pbp.epa.notna()]
    pbp['posteam']=pbp.posteam.map(norm);pbp['defteam']=pbp.defteam.map(norm)
    pbp['week']=pd.to_numeric(pbp.week,errors='coerce')
    pbp=pbp[pbp.week.between(1,25)]
    pbp['explosive']=((pbp.play_type.eq('pass')&(pbp.yards_gained>=20))|(pbp.play_type.eq('run')&(pbp.yards_gained>=10))).astype(float)
    pbp['success']=pd.to_numeric(pbp.success,errors='coerce')
    dates=pd.to_datetime(pbp.game_date,errors='coerce',utc=True)
    pbp=pbp[dates<(pd.Timestamp.now(tz='UTC')-pd.Timedelta(hours=48))]
    if pbp.empty:raise ValueError('No age-eligible play data; existing adjusted feed untouched')
    teams=sorted(set(pbp.posteam)|set(pbp.defteam))
    max_week=int(pbp.week.max())
    rows=[]
    for week in range(2,max_week+2):
        prior=pbp[pbp.week<week]
        if prior.empty:continue
        models={name:fit(prior,teams,metric,kind) for name,metric,kind in [
            ('epa','epa',None),('pass_epa','epa','pass'),('rush_epa','epa','run'),
            ('success','success',None),('pass_success','success','pass'),
            ('rush_success','success','run'),('explosive','explosive',None)]}
        for i,team in enumerate(teams):
            off=prior[prior.posteam==team];de=prior[prior.defteam==team]
            if off.empty or de.empty:continue
            def get(name,role):
                model=models[name]
                if model is None:return None
                mu,o,d=model
                value=mu+(o[i] if role=='off' else d[i])
                if name in ('success','pass_success','rush_success','explosive'):
                    value=max(0.,min(1.,value))
                return round(float(value),6)
            # Offense and defense ratings evaluated versus an average opponent.
            # Defense rating is EPA/success allowed: LOWER is better.
            rows.append({'season':2026,'week':week,'team':team,
                'games_prior':int(off.game_id.nunique()),
                'opponent_adjusted_off_pass_epa':get('pass_epa','off'),
                'opponent_adjusted_off_rush_epa':get('rush_epa','off'),
                'opponent_adjusted_off_epa_per_play':get('epa','off'),
                'opponent_adjusted_def_allowed_epa_per_play':get('epa','def'),
                'opponent_adjusted_off_pass_success':get('pass_success','off'),
                'opponent_adjusted_off_rush_success':get('rush_success','off'),
                'opponent_adjusted_off_success_rate':get('success','off'),
                'opponent_adjusted_def_allowed_success_rate':get('success','def'),
                'opponent_adjusted_off_explosive_rate':get('explosive','off'),
                'opponent_adjusted_def_allowed_explosive_rate':get('explosive','def')})
    if not rows:raise ValueError('No adjusted snapshots; existing file untouched')
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    payload={'season':2026,'generated_utc':datetime.now(timezone.utc).isoformat(),
        'source':URL,'method':'RIDGE_OPPONENT_ADJUSTED_ADDITIVE_OFFENSE_DEFENSE',
        'shrinkage_pseudo_plays':250,'max_age_eligible_week':max_week,
        'warning':'Research only; 48-hour game-date buffer does not verify final scores. No prediction model changes.',
        'rows':rows}
    tmp=OUTPUT.with_suffix('.tmp');tmp.write_text(json.dumps(payload,separators=(',',':')));tmp.replace(OUTPUT)
    print(f'Wrote {len(rows)} opponent-adjusted research snapshots, latest week {max_week+1}')
if __name__=='__main__':run()

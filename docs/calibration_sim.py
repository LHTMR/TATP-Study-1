"""Simulation supporting calibration_methods_comparison.md (rev. 4).

Compares candidate procedures for estimating F40 -- the monofilament force at which
median pain VAS = 40 -- on the Aesthesio ladder.  Observer model and all assumptions
are documented in section 5.1 of the companion note.  Run with: python3 calibration_sim.py
"""
import numpy as np
rng = np.random.default_rng(20260822)

LAD = np.array([19.6,39.2,58.8,78.4,98.0,147,255,588,980,1760,2940])
L   = np.log10(LAD)
STEP = 0.246   # mean log10 step

# Observer: rating = 40 + s*(log10F - log10F40) + N(0,sig), clipped [0,100]
# s grounded in Ng et al. 2024 Weber fraction 0.88 on hand dorsum:
#   1 JND = log10(1.88) = 0.274 log10; in 2AFC that is d'~1 => mean shift = sqrt(2)*sigma_disc
#   with sigma_disc = 10 VAS pts  ->  s = sqrt(2)/0.274*10 = 51.6 VAS pts per log10 unit
S_FIXED = np.sqrt(2)/np.log10(1.88)*10.0

def rate(F,F40,sig,s=S_FIXED):
    return np.clip(40 + s*(np.log10(F)-np.log10(F40)) + rng.normal(0,sig), 0, 100)

def fit40(fs,rs,fixed_slope=None):
    x=np.log10(np.asarray(fs)); y=np.asarray(rs)
    if fixed_slope is not None:
        return 10**(np.mean(x) + (40-np.mean(y))/fixed_slope)
    if len(np.unique(x))<2: return np.nan
    b,a=np.polyfit(x,y,1)
    if b<=1e-9: return np.nan
    return 10**((40-a)/b)

def ascend(F40,sig,s,start):
    """approach from below, stop on first rating >=40. returns (index, fs, rs)"""
    fs,rs=[],[]; i=int(np.clip(start,0,len(LAD)-1))
    while True:
        r=rate(LAD[i],F40,sig,s); fs.append(LAD[i]); rs.append(r)
        if r>=40 or i==len(LAD)-1: break
        i+=1
    return i,fs,rs

def strat_ascend_local(F40,sig,s,reps=3,nlev=2,spread=1,fixed_slope=None,start=0):
    i,fs,rs=ascend(F40,sig,s,start)
    lo=int(np.clip(i-spread*(nlev-1),0,len(LAD)-1))
    levels=[int(np.clip(lo+k*spread,0,len(LAD)-1)) for k in range(nlev)]
    plan=np.repeat(levels,reps); rng.shuffle(plan)
    for j in plan: fs.append(LAD[j]); rs.append(rate(LAD[j],F40,sig,s))
    keep=slice(len(rs)-len(plan),len(rs))   # estimate from phase-2 trials only
    return fit40(fs[keep],rs[keep],fixed_slope),fs,rs

def strat_full(F40,sig,s,reps=2,lo=4,hi=11):
    fs,rs=[],[]; plan=np.repeat(np.arange(lo,hi),reps); rng.shuffle(plan)
    for j in plan: fs.append(LAD[j]); rs.append(rate(LAD[j],F40,sig,s))
    return fit40(fs,rs),fs,rs

def strat_kesten(F40,sig,s,n=12,c=0.5,start=0):
    fs,rs,revs=[],[],[]; x=L[start]; sh=0; prev=None
    for _ in range(n):
        j=int(np.argmin(np.abs(L-x))); F=LAD[j]; r=rate(F,F40,sig,s)
        fs.append(F); rs.append(r); d=np.sign(40-r)
        if prev is not None and d!=0 and d!=prev: sh+=1; revs.append(np.log10(F))
        if d!=0: prev=d
        x=np.clip(x+(c/(2+sh))*((40-r)/s),L[0],L[-1])
    return (10**np.mean(revs) if len(revs)>=2 else fs[-1]),fs,rs

def strat_binstair(F40,sig,s,n=12,start=0):
    fs,rs,revs=[],[],[]; j=start; prev=None
    for _ in range(n):
        F=LAD[j]; r=rate(F,F40,sig,s); fs.append(F); rs.append(r)
        d=-1 if r>=40 else 1
        if prev is not None and d!=prev: revs.append(np.log10(F))
        prev=d; j=int(np.clip(j+d,0,len(LAD)-1))
    return (10**np.mean(revs) if len(revs)>=2 else float(fs[-1])),fs,rs

def evaluate(fn,kw,F40s,sig,s,label):
    e,ok,n,p40,p70=[],[],[],[],[]
    for F40 in F40s:
        est,fs,rs=fn(F40,sig,s,**kw)
        if not np.isfinite(est): est=fs[-1]
        est=float(np.clip(est,LAD[0],LAD[-1]))
        e.append(np.log10(est)-np.log10(F40))
        ok.append(np.argmin(np.abs(L-np.log10(est)))==np.argmin(np.abs(L-np.log10(F40))))
        n.append(len(fs)); p40.append(sum(r>=40 for r in rs)); p70.append(sum(r>=70 for r in rs))
    e=np.array(e); rmse=np.sqrt((e**2).mean())
    return dict(label=label,rmse=rmse,steps=rmse/STEP,ok=100*np.mean(ok),
                n=np.mean(n),p40=np.mean(p40),p70=np.mean(p70))

def run(title,med,sig,N=4000,prior_start=None):
    s=S_FIXED
    F40s=np.clip(med*10**rng.normal(0,0.20,N),LAD[0]*1.05,LAD[-1]*0.95)
    st = 0 if prior_start is None else prior_start
    rows=[
      evaluate(strat_ascend_local,dict(reps=3,nlev=2,spread=1,start=st),F40s,sig,s,"Ascend -> 2 adjacent x3, free slope"),
      evaluate(strat_ascend_local,dict(reps=3,nlev=2,spread=2,start=st),F40s,sig,s,"Ascend -> 2 levels 2 apart x3, free"),
      evaluate(strat_ascend_local,dict(reps=3,nlev=3,spread=1,start=st),F40s,sig,s,"Ascend -> 3 adjacent x3, free slope"),
      evaluate(strat_ascend_local,dict(reps=3,nlev=3,spread=2,start=st),F40s,sig,s,"Ascend -> 3 levels 2 apart x3, free"),
      evaluate(strat_ascend_local,dict(reps=3,nlev=2,spread=1,fixed_slope=s,start=st),F40s,sig,s,"Ascend -> 2 adjacent x3, FIXED slope"),
      evaluate(strat_ascend_local,dict(reps=3,nlev=3,spread=1,fixed_slope=s,start=st),F40s,sig,s,"Ascend -> 3 adjacent x3, FIXED slope"),
      evaluate(strat_ascend_local,dict(reps=2,nlev=3,spread=1,fixed_slope=s,start=st),F40s,sig,s,"Ascend -> 3 adjacent x2, FIXED slope"),
      evaluate(strat_full,dict(reps=2),F40s,sig,s,"Full 7 levels x2, free slope"),
      evaluate(strat_kesten,dict(n=12,start=st),F40s,sig,s,"Rating-guided (Kesten) 12"),
      evaluate(strat_kesten,dict(n=18,start=st),F40s,sig,s,"Rating-guided (Kesten) 18"),
      evaluate(strat_binstair,dict(n=12,start=st),F40s,sig,s,"Binarised staircase 12"),
      evaluate(strat_binstair,dict(n=18,start=st),F40s,sig,s,"Binarised staircase 18"),
    ]
    print(f"\n=== {title} | median F40={med} mN | rating noise SD={sig} | start={'bottom' if prior_start is None else 'informed prior'} ===")
    print(f"{'strategy':<40}{'apps':>6}{'RMSE':>8}{'steps':>7}{'right filament':>16}{'>=40':>7}{'>=70':>7}")
    for r in rows:
        print(f"{r['label']:<40}{r['n']:>6.1f}{r['rmse']:>8.3f}{r['steps']:>7.2f}{r['ok']:>15.0f}%{r['p40']:>7.1f}{r['p70']:>7.1f}")

print(f"slope s = {S_FIXED:.1f} VAS pts per log10 unit (fixed across scenarios)")
print(f"one filament step (0.246 log10) = {0.246*S_FIXED:.1f} VAS pts")
run("PRE-S",600,10)
run("POST-S",130,10)
run("POST-S, noisy reporter (s unchanged)",130,18)
run("POST-S, informed prior start",130,10,prior_start=4)

# ---- Sensitivity: what if the assumed fixed slope is wrong? ----------------
def run_slope_misspec(title,med,sig,N=4000,start=0):
    s=S_FIXED
    F40s=np.clip(med*10**rng.normal(0,0.20,N),LAD[0]*1.05,LAD[-1]*0.95)
    print(f"\n=== SLOPE MISSPECIFICATION | {title} | true s={s:.1f} ===")
    print(f"{'assumed slope':<22}{'ratio':>7}{'apps':>6}{'RMSE':>8}{'steps':>7}{'right filament':>16}")
    for mult in [0.5,0.7,0.85,1.0,1.2,1.5,2.0]:
        r=evaluate(strat_ascend_local,dict(reps=3,nlev=3,spread=1,fixed_slope=s*mult,start=start),
                   F40s,sig,s,f"{s*mult:.1f}")
        print(f"{r['label']:<22}{mult:>7.2f}{r['n']:>6.1f}{r['rmse']:>8.3f}{r['steps']:>7.2f}{r['ok']:>15.0f}%")
    # regularised: shrink the fitted slope toward the prior
    print("\n  shrinkage estimator (w*fitted + (1-w)*prior), prior correct:")
    for w in [0.0,0.25,0.5,0.75,1.0]:
        e,ok=[],[]
        for F40 in F40s:
            i,fs,rs=ascend(F40,sig,s,start)
            lo=int(np.clip(i-2,0,len(LAD)-1)); lev=[int(np.clip(lo+k,0,len(LAD)-1)) for k in range(3)]
            plan=np.repeat(lev,3); rng.shuffle(plan)
            f2=[LAD[j] for j in plan]; r2=[rate(LAD[j],F40,sig,s) for j in plan]
            x=np.log10(np.asarray(f2)); y=np.asarray(r2)
            b,a=np.polyfit(x,y,1); b=max(b,1e-9)
            bb=w*b+(1-w)*s
            est=10**(np.mean(x)+(40-np.mean(y))/bb)
            est=float(np.clip(est,LAD[0],LAD[-1]))
            e.append(np.log10(est)-np.log10(F40))
            ok.append(np.argmin(np.abs(L-np.log10(est)))==np.argmin(np.abs(L-np.log10(F40))))
        rm=np.sqrt((np.array(e)**2).mean())
        print(f"    w={w:.2f}  RMSE {rm:.3f}  ({rm/STEP:.2f} steps)  right filament {100*np.mean(ok):.0f}%")

run_slope_misspec("POST-S",130,10)
run_slope_misspec("POST-S noisy reporter",130,18)

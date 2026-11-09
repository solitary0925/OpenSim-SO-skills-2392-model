"""Review saved SO output numerically, preserving failed samples as missing data."""
import argparse
import csv
import json
from pathlib import Path
import re

import numpy as np


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def save(p,d):
    Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def storage(p):
    lines=Path(p).read_text(encoding='utf-8-sig').splitlines()
    h=next(i for i,x in enumerate(lines) if x.strip().lower()=='endheader')
    names=lines[h+1].split();a=np.loadtxt(lines[h+2:],ndmin=2)
    if len(names)!=len(set(names)) or a.shape[1]!=len(names) or names[0]!='time':
        raise ValueError('Invalid or duplicate storage columns: '+str(p))
    if not np.isfinite(a[:,0]).all() or not np.all(np.diff(a[:,0])>0):
        raise ValueError('Invalid storage timestamps: '+str(p))
    return names,a


def csvwrite(p,rows,fields):
    with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def native_validity(t,activations,forces,log,tolerance):
    reasons=[[] for _ in t]
    fail=re.findall(r'could not find a solution at time\s*[=:]?\s*([\d.eE+-]+)',log,re.I)
    for text in fail:
        ft=float(text.rstrip('.'));idx=int(np.argmin(abs(t-ft)))
        if abs(t[idx]-ft)>1e-7:raise ValueError('Native failure time does not match any output sample')
        reasons[idx].append('native_optimizer_failure')
    if len(re.findall('OPTIMIZATION FAILED',log,re.I))>len(fail):
        raise ValueError('Native failure message without a mapped failure time')
    violations={round(float(x),8):float(y) for x,y in re.findall(
        r'time =\s*([\d.eE+-]+).*?Constraint violation =\s*([\d.eE+-]+)',log)}
    for i,x in enumerate(t):
        violation=violations.get(round(float(x),8))
        if violation is None:reasons[i].append('native_constraint_record_missing')
        elif not np.isfinite(violation) or violation>tolerance:reasons[i].append('constraint_violation')
        if not np.isfinite(activations[i]).all() or not np.isfinite(forces[i]).all():reasons[i].append('nonfinite_output')
    return reasons,violations


def integrate_valid(t,v,ok):
    pairs=ok[:-1]&ok[1:]
    if not pairs.any():return None
    return float((.5*(v[:-1]+v[1:])*np.diff(t))[pairs].sum())


def review(folder):
    folder=Path(folder).resolve();c=read(folder/'comparison_config.json');status=read(folder/'run_status.json')
    muscles=c['muscle_names'];mass=c['measured_mass_kg'];rate=c['marker_rate_hz']
    if not np.isfinite(mass) or mass<=0:raise ValueError('Measured mass required')
    target_start,target_end=c['target_20N_window_s'];target_duration=target_end-target_start
    if target_duration<=0:raise ValueError('Invalid target stance event')
    frames=c.get('total_original_frames');time_origin=c.get('original_time_origin_s',0.)
    if frames is None:
        p=Path(c['source_RRA_job'])/'stance_window.json'
        if p.is_file():frames=read(p).get('total_original_frames')
    data={};bad=[];quality=[];metrics=[];curves=[];reserves=[]
    for label,r in status.get('routes',{}).items():
        route=folder/label
        route_origin=r.get('original_time_origin_s',time_origin)
        an,a=storage(r['output_files']['activation']);fn,f=storage(r['output_files']['force'])
        t=a[:,0]
        expected=np.array(r.get('expected_times_s',c.get('expected_times_s',[])),float)
        if not len(expected):expected=t.copy()
        if a.shape[0]!=f.shape[0] or len(t)!=len(expected) or not np.allclose(t,expected,rtol=0,atol=1e-8) or not np.allclose(f[:,0],t,rtol=0,atol=1e-8):
            raise ValueError('SO output sampling mismatch: '+label)
        if not all(n in an and n in fn for n in muscles):raise ValueError('Missing muscle output columns')
        log=(route/'SO_console.log').read_text(encoding='utf-8',errors='replace')
        reasons,violations=native_validity(t,a,f,log,c['optimizer_tolerance'])
        bounds=r.get('muscle_bounds',{})
        for name in muscles:
            lo,hi=bounds.get(name,[0.,1.]);values=a[:,an.index(name)]
            for i in np.where((values<lo-1e-4)|(values>hi+1e-4))[0]:reasons[i].append('activation_outside_model_bounds')
        for i in range(len(t)):
            reasons[i]=sorted(set(reasons[i]))
            if reasons[i]:
                frame_float=c['original_first_frame']+(t[i]-route_origin)*rate
                bad.append(dict(route=label,time_s=float(t[i]),original_frame_float=float(frame_float),
                    original_ordinal_float=float((t[i]-route_origin)*rate+1),total_original_frames=frames,
                    original_stance_percent=float(100*(t[i]-target_start)/target_duration),
                    reason=';'.join(reasons[i]),constraint_violation=violations.get(round(float(t[i]),8))))
        ok=np.array([not x for x in reasons])
        data[label]=dict(t=t,an=an,a=a,fn=fn,f=f,ok=ok,route=r)
    if not data:raise ValueError('No completed route output available; inspect native errors')
    for label,d in data.items():
        a,f,an,fn,ok,t=[d[k] for k in ['a','f','an','fn','ok','t']]
        route_origin=d['route'].get('original_time_origin_s',time_origin)
        translations=['residual_pelvis_'+s for s in ['tx','ty','tz']]
        reserve_names=[n for n in fn if n.startswith('reserve_')]
        if not all(n in fn for n in translations):raise ValueError('Missing pelvis residual components')
        residual=f[ok][:,[fn.index(n) for n in translations]]
        reserve=f[ok][:,[fn.index(n) for n in reserve_names]]
        row=dict(route=label,total_samples=len(t),valid_samples=int(ok.sum()),failed_samples=int((~ok).sum()),
                 numeric_status='complete_numeric_solve' if ok.all() else 'partial_numeric_failure' if ok.any() else 'no_valid_samples',
                 native_exit_code=d['route']['SO']['returncode'],
                 maximum_component_residual_RMS_N=float(np.sqrt(np.mean(residual**2,axis=0)).max()) if ok.any() else None,
                 maximum_component_residual_abs_peak_N=float(abs(residual).max()) if ok.any() else None,
                 maximum_joint_reserve_abs_peak_Nm=float(abs(reserve).max()) if ok.any() and reserve.size else None,
                 adjacent_valid_duration_s=float(np.diff(t)[ok[:-1]&ok[1:]].sum()),
                 original_stance_percent_range=[float(100*(x-target_start)/target_duration) for x in t[[0,-1]]],
                 near_upper_activation_muscles=sum(bool(np.any(a[ok,an.index(n)]>=.99)) for n in muscles),
                 research_validity='not_established')
        quality.append(row)
        for n in muscles:
            av=a[:,an.index(n)];fv=f[:,fn.index(n)];v=fv[ok];u=av[ok]
            metric=dict(route=label,muscle=n,valid_samples=int(ok.sum()),
                force_peak_N=float(v.max()) if len(v) else None,
                force_mean_sample_N=float(v.mean()) if len(v) else None,
                force_peak_N_per_kg=float(v.max()/mass) if len(v) else None,
                force_peak_BW=float(v.max()/(mass*9.80665)) if len(v) else None,
                activation_peak=float(u.max()) if len(u) else None,
                activation_mean_sample=float(u.mean()) if len(u) else None,
                force_peak_time_s=float(t[ok][v.argmax()]) if len(v) else None,
                activation_peak_time_s=float(t[ok][u.argmax()]) if len(u) else None,
                force_integral_valid_intervals_Ns=integrate_valid(t,fv,ok),
                activation_integral_valid_intervals_s=integrate_valid(t,av,ok))
            metrics.append(metric)
            for i,x in enumerate(t):curves.append(dict(route=label,muscle=n,time_s=float(x),
                original_frame_float=float(c['original_first_frame']+(x-route_origin)*rate),
                original_stance_percent=float(100*(x-target_start)/target_duration),
                solver_valid=bool(ok[i]),
                force_N=float(fv[i]) if ok[i] else None,activation=float(av[i]) if ok[i] else None))
        idfile=folder/label/'id_reference/ID_reference.sto'
        if idfile.is_file():
            idn,ida=storage(idfile)
            if len(ida)!=len(t) or not np.allclose(ida[:,0],t,rtol=0,atol=1e-8):raise ValueError('ID reference timing mismatch')
            for n in reserve_names:
                coord=n.removeprefix('reserve_');key=coord+'_moment'
                if key not in idn:raise ValueError('Missing ID coordinate moment: '+key)
                peak=float(abs(f[ok,fn.index(n)]).max()) if ok.any() else None
                reference=float(abs(ida[ok,idn.index(key)]).max()) if ok.any() else None
                reserves.append(dict(route=label,coordinate=coord,peak_reserve_Nm=peak,peak_ID_moment_Nm=reference,
                    ratio_of_peaks_percent=100*peak/reference if reference is not None and reference>1e-8 else None,
                    denominator_below_1_Nm=reference is not None and reference<1.))
    badfields=['route','time_s','original_frame_float','original_ordinal_float','total_original_frames','original_stance_percent','reason','constraint_violation']
    csvwrite(folder/'invalid_frames.csv',bad,badfields)
    csvwrite(folder/'route_quality_summary.csv',quality,list(quality[0]))
    csvwrite(folder/'muscle_metrics.csv',metrics,list(metrics[0]))
    csvwrite(folder/'validated_muscle_curves.csv',curves,list(curves[0]))
    if reserves:csvwrite(folder/'reserve_vs_ID_reference.csv',reserves,list(reserves[0]))
    result=dict(routes=quality,invalid_frames=bad,
                upstream_mass=c.get('upstream_mass'),upstream_warnings=c.get('upstream_fidelity_warnings'),
                statistics='descriptive only; no inference',plots_generated=False)
    save(folder/'SO_review.json',result)
    lines=['# SO review','',
      'This is a numerical/descriptive review, not physiological validation. RMS and peak are maxima across translational generalized residual components, may be different components, and are not resultants.',
      '', '| Route | Valid / total | Original stance | RMS (N) | Absolute peak (N) | Max joint reserve (Nm) |', '|---|---:|---:|---:|---:|---:|']
    for r in quality:
        fmt=lambda v:'no valid output' if v is None else f'{v:.5g}'
        lo,hi=r['original_stance_percent_range']
        lines.append(f"| {r['route']} | {r['valid_samples']}/{r['total_samples']} | {lo:.2f}%–{hi:.2f}% | {fmt(r['maximum_component_residual_RMS_N'])} | {fmt(r['maximum_component_residual_abs_peak_N'])} | {fmt(r['maximum_joint_reserve_abs_peak_Nm'])} |")
    lines+=['','Each route uses its own valid samples for summaries.',
      '', 'Failed samples are missing in validated CSV, not zero. Integrals never bridge invalid samples. Keep native storage and logs.',
      '', '## Failed sample locations', '']
    for r in bad:lines.append(f"- {r['route']}: {r['time_s']:.6g}s; original frame {r['original_frame_float']:.6g}; ordinal {r['original_ordinal_float']:.6g}/{r['total_original_frames']}; stance {r['original_stance_percent']:.3f}%; {r['reason']}.")
    lines+=['','## Limits','',
      '- Preserve upstream mass/COM and motion/marker warnings in SO_review.json. Complete numeric convergence does not clear these warnings.',
      '- Near-upper activations and residual/reserve magnitudes require review; the script does not automatically strengthen muscles or grant acceptance.',
      '- Standard SO activation is model-estimated, not EMG; rigid-tendon and no-activation-dynamics assumptions matter for running.',
      '- No plots, CMC, JRA, filtering changes or inferential statistics are performed by this reviewer.']
    (folder/'SO_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',type=Path,required=True)
    args=p.parse_args();result=review(args.folder)
    print(json.dumps(dict(routes=result['routes']),ensure_ascii=True,indent=2))

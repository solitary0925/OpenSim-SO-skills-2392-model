"""Configurable, provenance-checked prepared CGM24 native OpenSim SO comparison.

This is a one-case pilot, not an installed skill or a batch acceptance pipeline.
"""
from pathlib import Path
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np
import opensim as osim
from scipy.interpolate import CubicSpline

from muscle_strength import prepare_strength_model

JOB = EXPORT = OUT = CLI = None
SETTINGS = {}


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def save(p, d):
    Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def storage(p):
    lines = Path(p).read_text(encoding='utf-8-sig').splitlines()
    idx = next(i for i, s in enumerate(lines) if s.strip().lower() == 'endheader')
    names = lines[idx + 1].split()
    a = np.loadtxt(lines[idx + 2:], ndmin=2)
    assert a.shape[1] == len(names) and np.isfinite(a).all(), str(p)
    assert np.all(np.diff(a[:, 0]) > 0), str(p)
    return names, a, lines[:idx]


def write_motion(p, names, a, degrees):
    with Path(p).open('w', encoding='utf-8', newline='\n') as f:
        f.write(f'SO_common_grid\nnRows={len(a)}\nnColumns={len(names)}\ninDegrees={degrees}\nendheader\n')
        f.write('\t'.join(names) + '\n')
        np.savetxt(f, a, delimiter='\t', fmt='%.12g')


def run_native(setup, log):
    started = time.time()
    env = os.environ.copy()
    env['PATH'] = str(CLI.parent) + os.pathsep + env.get('PATH', '')
    with Path(log).open('w', encoding='utf-8') as f:
        proc = subprocess.run([str(CLI), 'run-tool', str(setup)], cwd=setup.parent,
                              env=env, stdout=f, stderr=subprocess.STDOUT, timeout=600)
    text = Path(log).read_text(encoding='utf-8', errors='replace')
    failures = re.findall(r'could not find a solution at time\s*[=:]?\s*([\d.eE+-]+)', text, re.I)
    # A process may return success while individual SO frames failed.
    return dict(returncode=proc.returncode, seconds=time.time()-started,
                optimizer_failed_times=[float(s.rstrip('.')) for s in failures],
                optimization_failure_messages=len(re.findall(r'OPTIMIZATION FAILED', text, re.I)),
                warning_lines=[s for s in text.splitlines() if '[warning]' in s.lower() or '[error]' in s.lower()])


def fix_meshes(model_file):
    tree = ET.parse(model_file)
    for e in tree.getroot().iter('mesh_file'):
        name = Path(e.text.strip()).name
        f = EXPORT / 'Geometry' / name
        if not f.exists():
            f = CLI.parent.parent / 'Geometry' / name
        if f.exists():
            e.text = f.as_posix()
    tree.write(model_file, encoding='utf-8', xml_declaration=True)


def main():
    assert not OUT.exists(), 'Use a new output folder; no overwrite of past runs.'
    OUT.mkdir(parents=True)
    osim.Logger.removeFileSink()
    osim.Logger.addFileSink(str(OUT / 'preparation_opensim.log'))
    osim.ModelVisualizer.addDirToGeometrySearchPaths(str(EXPORT / 'Geometry'))
    manifest = read(JOB / 'input_manifest.json')
    protected = {**manifest['source_hashes'], **manifest['prepared_inputs']}
    for p in [JOB/'final_review.json', JOB/'stance_window.json', *[EXPORT/n for n in
              ['RRA_model.osim', 'RRA_motion.mot', 'original_IK.mot', 'ExternalLoads.xml', 'external_loads.mot']]]:
        protected[str(p)] = sha(p)
    strength = SETTINGS.get('muscle_strength')
    donor = strength.get('donor_model') if strength is not None else None
    if donor is not None:
        protected[donor] = sha(donor)
    checks = {p: Path(p).is_file() and sha(p) == h for p, h in protected.items()}
    save(OUT/'input_audit_before.json', dict(files=checks, all_unchanged=all(checks.values())))
    assert all(checks.values()), 'Source/provenance mismatch: inspect input audit.'
    assert CLI.is_file()
    review = read(JOB/'final_review.json')
    assert review['selected_iteration'] and review['status'].startswith('selected')
    window = read(JOB/'stance_window.json')
    assert window['status'] == 'ready'
    ik_names, ik, ik_head = storage(EXPORT/'original_IK.mot')
    rr_names, rr, rr_head = storage(EXPORT/'RRA_motion.mot')
    assert set(ik_names) == set(rr_names)
    rr = rr[:, [rr_names.index(n) for n in ik_names]]
    ik_deg = next(s.split('=')[1].strip().lower() for s in ik_head if s.lower().startswith('indegrees='))
    rr_deg = next(s.split('=')[1].strip().lower() for s in rr_head if s.lower().startswith('indegrees='))
    assert ik_deg == rr_deg
    start, end = review['actual_window_s']
    # Same original marker-rate sample grid for all three routes; no low-pass filter.
    grid = ik[(ik[:, 0] >= start-1e-9) & (ik[:, 0] <= end+1e-9), 0]
    assert len(grid) >= 10 and grid[0] >= rr[0, 0]-1e-9 and grid[-1] <= rr[-1, 0]+1e-9
    a_ik = np.column_stack([grid, CubicSpline(ik[:, 0], ik[:, 1:], axis=0)(grid)])
    a_rr = np.column_stack([grid, CubicSpline(rr[:, 0], rr[:, 1:], axis=0)(grid)])
    assert np.max(np.abs(a_ik[:, 1:]-ik[np.searchsorted(ik[:, 0], grid), 1:])) < 1e-7
    names_f, force, _ = storage(EXPORT/'external_loads.mot')
    assert force[0, 0] <= grid[0] and force[-1, 0] >= grid[-1]
    base = osim.Model(str(JOB/'inputs/base.osim')); state=base.initSystem()
    muscles = [base.getMuscles().get(i).getName() for i in range(base.getMuscles().getSize())]
    assert len(muscles) == 92 and base.getForceSet().getSize() == 92
    active = [base.getCoordinateSet().get(i).getName() for i in range(base.getCoordinateSet().getSize())
              if not base.getCoordinateSet().get(i).isConstrained(state)]
    assert len(active) == 18
    job_config=read(JOB/'job_config.json')
    config = dict(subject=job_config['subject'], trial=job_config['trial'], side=job_config['target_side'], stage=SETTINGS['review_purpose'],
                  source_RRA_job=str(JOB), source_RRA_candidate=review['selected_iteration'],
                  actual_window_s=[float(grid[0]), float(grid[-1])], samples=len(grid),
                  marker_rate_hz=window['point_rate_hz'], original_first_frame=window['source_first_original_frame'],
                  original_time_origin_s=float(ik[0,0]),
                  total_original_frames=window.get('total_original_frames'), expected_times_s=grid.tolist(), source_run_config=SETTINGS,
                  target_20N_window_s=window['target_window_s'],
                  target_percent_range=[100*(float(t)-window['target_window_s'][0])/window['target_duration_s'] for t in [grid[0],grid[-1]]],
                  sampling='IK original sample times; RRA cubic interpolation onto same grid, no extrapolation; no low-pass added',
                  derivative_context='Both SO inputs restricted to the same grid/window; endpoint derivative sensitivity retained as warning',
                  filtering=dict(mode='no_added_filtering', cutoff_Hz=-1,
                                 source=SETTINGS['filtering']['decision']),
                  activation_exponent=SETTINGS['optimizer']['activation_exponent'], use_muscle_physiology=SETTINGS['optimizer']['use_muscle_physiology'], optimizer_tolerance=SETTINGS['optimizer']['tolerance'], optimizer_max_iterations=SETTINGS['optimizer']['max_iterations'],
                  reserve_optimal_force=SETTINGS['actuators']['optimal_force'], reserve_control_bounds=[SETTINGS['actuators']['control_min'],SETTINGS['actuators']['control_max']],
                  reserve_policy='Same one actuator per active coordinate in all routes; N for translation and Nm for rotation; permissive bounds expose infeasibility and are not acceptance criteria',
                  measured_mass_kg=SETTINGS['measured_mass_kg'], normalization_mass='Measured subject mass, NOT each RRA-adjusted mass',
                  original_active_coordinates=active, muscle_names=muscles,
                  upstream_mass=review['mass'], upstream_fidelity_warnings=review['selected_acceptance']['failures'],
                  external_forces='Both designated concurrent plates retained; no contact window extension',
                  engine=dict(cli=str(CLI), api_version=osim.GetVersionAndDate()),
                  interpretation='Paired technical comparison; no statistical inference, research acceptance, CMC, or JRA')
    save(OUT/'comparison_config.json',config)
    frame_rows=[]
    for t in grid:
        frame_rows.append(dict(time_s=float(t), original_frame_float=float(window['source_first_original_frame']+(t-ik[0,0])*window['point_rate_hz']),
                               target_stance_percent=100*(float(t)-window['target_window_s'][0])/window['target_duration_s']))
    with (OUT/'time_frame_map.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(frame_rows[0]));w.writeheader();w.writerows(frame_rows)
    available=[('IK_original_model',JOB/'inputs/base.osim',a_ik),
            ('IK_RRA_model_control',EXPORT/'RRA_model.osim',a_ik),
            ('RRA_adjusted_model',EXPORT/'RRA_model.osim',a_rr)]
    routes=[r for r in available if r[0] in SETTINGS['routes']]
    all_results={}
    for label, source, motion in routes:
        folder=OUT/label; inp=folder/'inputs'; inp.mkdir(parents=True)
        muscle_model = inp/'muscle_model.osim'
        if strength is None:
            shutil.copy2(source, muscle_model)
        else:
            strength_tree, audit = prepare_strength_model(source, strength['profile'], donor)
            if donor is not None and audit['donor_model']['sha256'] != protected[donor]:
                raise ValueError('Muscle strength donor changed during preparation')
            strength_tree.write(muscle_model, encoding='utf-8', xml_declaration=True)
            save(inp/'muscle_strength_audit.json', audit)
        fix_meshes(muscle_model)
        write_motion(inp/'motion.mot',ik_names,motion,ik_deg)
        shutil.copy2(EXPORT/'external_loads.mot',inp/'external_loads.mot')
        tree=ET.parse(EXPORT/'ExternalLoads.xml'); tree.find('.//datafile').text=(inp/'external_loads.mot').as_posix()
        tree.write(inp/'ExternalLoads.xml',encoding='utf-8',xml_declaration=True)
        model=osim.Model(str(inp/'muscle_model.osim')); st=model.initSystem();cs=model.getCoordinateSet()
        assert model.getMuscles().getSize()==92 and model.getForceSet().getSize()==92
        coordinates=[cs.get(i) for i in range(cs.getSize()) if not cs.get(i).isConstrained(st)]
        assert [c.getName() for c in coordinates]==active
        assert [model.getMuscles().get(i).getName() for i in range(92)]==muscles
        route=dict(source_model=str(source),source_model_sha256=sha(source),mass_kg=model.getTotalMass(st),
                   muscle_count=92, active_coordinates=active, reserve_units={},
                   muscle_bounds={model.getMuscles().get(i).getName():[model.getMuscles().get(i).getMinControl(),model.getMuscles().get(i).getMaxControl()] for i in range(92)})
        for coord in coordinates:
            actuator=osim.CoordinateActuator(coord.getName())
            actuator.setName(('residual_' if coord.getName().startswith('pelvis_') else 'reserve_')+coord.getName())
            actuator.setOptimalForce(SETTINGS['actuators']['optimal_force']);actuator.setMinControl(SETTINGS['actuators']['control_min']);actuator.setMaxControl(SETTINGS['actuators']['control_max'])
            route['reserve_units'][actuator.getName()]='N' if int(coord.getMotionType())==2 else 'Nm'
            model.addForce(actuator)
        model.finalizeConnections();model.initSystem();model.printToXML(str(inp/'SO_model.osim'))
        so=osim.StaticOptimization();so.setName('StaticOptimization');so.setStartTime(float(grid[0]));so.setEndTime(float(grid[-1]))
        so.setStepInterval(1);so.setUseModelForceSet(True);so.setUseMusclePhysiology(SETTINGS['optimizer']['use_muscle_physiology'])
        so.setActivationExponent(SETTINGS['optimizer']['activation_exponent']);so.setConvergenceCriterion(SETTINGS['optimizer']['tolerance']);so.setMaxIterations(SETTINGS['optimizer']['max_iterations'])
        tool=osim.AnalyzeTool();tool.setName(label);tool.setModelFilename(str(inp/'SO_model.osim'))
        tool.setReplaceForceSet(False);tool.setCoordinatesFileName(str(inp/'motion.mot'))
        tool.setExternalLoadsFileName(str(inp/'ExternalLoads.xml'));tool.setLowpassCutoffFrequency(-1)
        tool.setInitialTime(float(grid[0]));tool.setFinalTime(float(grid[-1]));tool.setResultsDir(str(folder/'results'))
        tool.updAnalysisSet().cloneAndAppend(so);tool.printToXML(str(folder/'SO_setup.xml'))
        # Separate ID from the same muscle-only model provides joint-moment references for reserve review.
        idt=osim.InverseDynamicsTool();idt.setName(label+'_ID_reference');idt.setModelFileName(str(inp/'muscle_model.osim'))
        idt.setCoordinatesFileName(str(inp/'motion.mot'));idt.setExternalLoadsFileName(str(inp/'ExternalLoads.xml'))
        excluded=osim.ArrayStr();excluded.append('Muscles');idt.setExcludedForces(excluded)
        idt.setLowpassCutoffFrequency(-1);idt.setStartTime(float(grid[0]));idt.setEndTime(float(grid[-1]))
        idt.setResultsDir(str(folder/'id_reference'));idt.setOutputGenForceFileName('ID_reference.sto')
        idt.printToXML(str(folder/'ID_reference_setup.xml'))
        save(folder/'route_config.json',route)
        save(OUT/'run_status.json',dict(status='running',route=label,completed=list(all_results)))
        print('RUN',label,flush=True)
        route['SO']=run_native(folder/'SO_setup.xml',folder/'SO_console.log')
        route['ID_reference']=run_native(folder/'ID_reference_setup.xml',folder/'ID_console.log')
        files={key:folder/'results'/f'{label}_StaticOptimization_{key}.sto' for key in ['activation','force']}
        assert route['SO']['returncode']==0 and all(f.is_file() for f in files.values()), route
        an,aa,_=storage(files['activation']); fn,ff,_=storage(files['force'])
        assert np.allclose(aa[:,0],grid,atol=1e-8) and np.allclose(ff[:,0],grid,atol=1e-8)
        assert all(n in an and n in fn for n in muscles)
        route['output_files']={k:str(v) for k,v in files.items()};route['output_samples']=len(aa)
        route['finite_and_complete']=True
        route['technical_pass']=route['SO']['optimization_failure_messages']==0 and not route['SO']['optimizer_failed_times']
        save(folder/'run_status.json',route);all_results[label]=route
        print('DONE',label,'pass',route['technical_pass'],'seconds',round(route['SO']['seconds'],2),flush=True)
    unchanged={p:Path(p).is_file() and sha(p)==h for p,h in protected.items()}
    save(OUT/'input_audit_after.json',dict(files=unchanged,all_unchanged=all(unchanged.values())))
    assert all(unchanged.values())
    save(OUT/'run_status.json',dict(status='completed',routes=all_results,source_inputs_unchanged=True))
    print('OUTPUT',OUT,flush=True)





def configure(path):
    global JOB, EXPORT, OUT, CLI, SETTINGS
    SETTINGS=read(path)
    for key in ['rra_job','output_folder','opensim_cmd']:
        p=Path(SETTINGS[key]).expanduser()
        if not p.is_absolute():
            p=Path(path).resolve().parent/p
        SETTINGS[key]=str(p.resolve())
    if 'muscle_strength' in SETTINGS:
        strength = SETTINGS['muscle_strength']
        if not isinstance(strength, dict) or not strength.get('profile'):
            raise ValueError('Record the selected muscle strength profile')
        if strength.get('donor_model') is not None:
            donor = Path(strength['donor_model']).expanduser()
            SETTINGS['muscle_strength']['donor_model'] = str((Path(path).resolve().parent/donor).resolve())
    JOB=Path(SETTINGS['rra_job']);EXPORT=JOB/'final_original_frame'
    OUT=Path(SETTINGS['output_folder']);CLI=Path(SETTINGS['opensim_cmd'])
    for p in [JOB,EXPORT]:
        if OUT==p or p in OUT.parents or OUT in p.parents:
            raise ValueError('Keep a new output folder separate from the source job tree')
    if SETTINGS['filtering']['mode']!='no_added_filtering':
        raise ValueError('Version0.1.0 implements no-added-filtering only; prepare and validate any new filter explicitly')
    if not SETTINGS['filtering'].get('decision','').strip() or not SETTINGS.get('input_disposition','').strip():
        raise ValueError('Record actual applicable filtering and input-review decisions')
    allowed={'IK_original_model','IK_RRA_model_control','RRA_adjusted_model'}
    routes=SETTINGS['routes']
    if not routes or len(set(routes))!=len(routes) or not set(routes)<=allowed:
        raise ValueError('Select nonempty unique supported routes')
    if SETTINGS['review_purpose'] not in ['technical_pilot','research_analysis']:
        raise ValueError('Specify technical_pilot or research_analysis')
    o=SETTINGS['optimizer'];a=SETTINGS['actuators']
    vals=[SETTINGS['measured_mass_kg'],o['activation_exponent'],o['tolerance'],o['max_iterations'],a['optimal_force'],a['control_min'],a['control_max']]
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and np.isfinite(v) for v in vals):
        raise ValueError('Finite numeric settings required')
    if min(SETTINGS['measured_mass_kg'],o['activation_exponent'],o['tolerance'],o['max_iterations'],a['optimal_force'])<=0:
        raise ValueError('Mass and optimizer/optimal-force settings must be positive')
    if int(o['max_iterations'])!=o['max_iterations'] or not a['control_min']<0<a['control_max']:
        raise ValueError('Integer iteration cap and signed actuator bounds required')
    o['max_iterations']=int(o['max_iterations'])
    if not isinstance(o['use_muscle_physiology'],bool):raise ValueError('Physiology must be boolean')


def preflight():
    if not CLI.is_file():raise FileNotFoundError(CLI)
    version=subprocess.run([str(CLI),'-V'],capture_output=True,text=True,errors='replace',timeout=60)
    if version.returncode:raise RuntimeError('Native CLI version probe failed: '+version.stdout+version.stderr)
    if '4.5' not in version.stdout+version.stderr or '4.5' not in osim.GetVersionAndDate():
        raise ValueError('This adapter requires verified OpenSim4.5 native/API compatibility')
    m=read(JOB/'input_manifest.json')
    protected={**m['source_hashes'],**m['prepared_inputs']}
    missing_or_changed=[p for p,h in protected.items() if not Path(p).is_file() or sha(p)!=h]
    if missing_or_changed:raise ValueError('Missing/changed provenance inputs: '+str(missing_or_changed))
    w=read(JOB/'stance_window.json');r=read(JOB/'final_review.json');c=read(JOB/'job_config.json')
    if w['status']!='ready' or w.get('side') not in ['L','R'] or not w.get('plate') or not w.get('contact_witnesses'):
        raise ValueError('Prepared target-side/plate/contact audit missing or not ready')
    if c['target_side']!=w['side']:raise ValueError('Target-side mismatch')
    if not r.get('selected_iteration') or not r['status'].startswith('selected'):
        raise ValueError('A matched selected RRA export is required by this prepared-job adapter')
    warnings=r.get('selected_acceptance',{}).get('failures',[])+r.get('calibration_warnings',[])
    if SETTINGS['review_purpose']=='research_analysis' and warnings and not SETTINGS.get('upstream_review_cleared',False):
        raise ValueError('Upstream RRA warnings need an explicit research-review disposition')
    lo,hi=r['actual_window_s'];el,eh=w['target_window_s']
    if not el-1e-9<=lo<hi<=eh+1e-9:raise ValueError('Export outside original stance event')
    models=[]
    for file in [JOB/'inputs/base.osim',EXPORT/'RRA_model.osim']:
        strength_info = None
        if 'muscle_strength' in SETTINGS:
            strength = SETTINGS['muscle_strength']
            _, audit = prepare_strength_model(file, strength['profile'], strength.get('donor_model'))
            strength_info = {key: audit[key] for key in ('profile', 'donor_model', 'transferred_count', 'retained_count')}
        model=osim.Model(str(file));s=model.initSystem();cs=model.getCoordinateSet()
        active=[cs.get(i).getName() for i in range(cs.getSize()) if not cs.get(i).isConstrained(s)]
        if model.getMuscles().getSize()!=92 or model.getForceSet().getSize()!=92 or len(active)!=18:
            raise ValueError('Unsupported model topology/force set; explicit adaptation required')
        expected=['pelvis_tilt','pelvis_list','pelvis_rotation','pelvis_tx','pelvis_ty','pelvis_tz',
                  'hip_flexion_r','hip_adduction_r','hip_rotation_r','knee_angle_r','ankle_angle_r','subtalar_angle_r',
                  'hip_flexion_l','hip_adduction_l','hip_rotation_l','knee_angle_l','ankle_angle_l','subtalar_angle_l']
        if active!=expected:raise ValueError('Original-knee CGM24 active coordinates required')
        if not np.isfinite(model.getTotalMass(s)) or model.getTotalMass(s)<=0:raise ValueError('Invalid total mass')
        for i in range(model.getBodySet().getSize()):
            body=model.getBodySet().get(i);inertia=body.getInertia();moments=inertia.getMoments()
            vals=np.array([body.getMass(),*[moments.get(j) for j in range(3)]],float)
            if not np.isfinite(vals).all() or (vals<0).any():raise ValueError('Invalid body mass/inertia')
        models.append(dict(file=str(file),mass_kg=model.getTotalMass(s),active=active,
                           muscle_strength=strength_info))
    motions=[]
    for file in [EXPORT/'original_IK.mot',EXPORT/'RRA_motion.mot',EXPORT/'external_loads.mot']:
        names,arr,header=storage(file)
        if arr[0,0]>lo+1e-7 or arr[-1,0]<hi-1e-7:raise ValueError('Motion/load does not cover export: '+str(file))
        motions.append(dict(file=str(file),samples=len(arr),start=float(arr[0,0]),end=float(arr[-1,0])))
    loads=ET.parse(EXPORT/'ExternalLoads.xml').getroot()
    fs=loads.findall('.//ExternalForce')
    if not fs:raise ValueError('External force definitions missing')
    force_names,_,_=storage(EXPORT/'external_loads.mot')
    for f in fs:
        if f.findtext('applied_to_body') not in ['calcn_l','calcn_r']:raise ValueError('Unsupported force application body')
        for field in ['force_expressed_in_body','point_expressed_in_body']:
            if f.findtext(field)!='ground':raise ValueError('Ground-expressed prepared loads required')
        for field in ['force_identifier','point_identifier','torque_identifier']:
            prefix=f.findtext(field)
            if not prefix or any(prefix+axis not in force_names for axis in ['x','y','z']):
                raise ValueError('Missing force/COP/torque columns for '+str(prefix))
    return dict(ready=True,native_version=(version.stdout+version.stderr).strip(),api_version=osim.GetVersionAndDate(),
                protected_files=len(protected),models=models,motions=motions,upstream_warnings=warnings,
                limitation='Prepared contact/zero/transform decisions must also be reviewed; this is not C3D revalidation')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    try:
        configure(args.config)
        info=preflight()
        if args.check_only:
            print(json.dumps(info,ensure_ascii=True,indent=2))
        else:
            existed=OUT.exists()
            if existed:raise FileExistsError('Use a new output directory')
            main()
            save(OUT/'environment_preflight.json',info)
    except Exception as exc:
        # Never add error files to an existing historical result directory.
        if OUT is not None and OUT.exists() and 'existed' in locals() and not existed:
            save(OUT/'pilot_error.json',dict(error=type(exc).__name__,message=str(exc)))
        raise

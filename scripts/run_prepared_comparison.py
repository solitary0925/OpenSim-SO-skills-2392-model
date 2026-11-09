"""Run each prepared CGM24 OpenSim SO route over its own verified window."""
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
from input_filter6 import PROFILE, NO_ADDED, choice, verify_receipt

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
        f.write(f'SO_motion\nnRows={len(a)}\nnColumns={len(names)}\ninDegrees={degrees}\nendheader\n')
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


def needs_rra():
    return set(SETTINGS['routes'])!={'IK_original_model'} or not SETTINGS.get('ik_inputs')


def route_inputs(label, window, review):
    rra_motion = label=='RRA_adjusted_model'
    independent = SETTINGS.get('ik_inputs') if not rra_motion else None
    model = JOB/'inputs/base.osim' if label=='IK_original_model' else EXPORT/'RRA_model.osim'
    motion = Path(independent['motion']) if independent else EXPORT/('RRA_motion.mot' if rra_motion else 'original_IK.mot')
    loads = Path(independent['loads']) if independent else EXPORT/'ExternalLoads.xml'
    receipt = SETTINGS.get('filter_receipts',{}).get(label)
    selected = choice(SETTINGS['filtering_decision']) if 'filtering_decision' in SETTINGS else set()
    if selected:
        record = read(receipt)
        processed = {key:Path(item['path']).resolve() for signal in record['signals'].values()
                     for key,item in signal['outputs'].items()}
        protected = {str(file):sha(file) for file in processed.values()}
        verify_receipt(receipt,SETTINGS['filtering_decision'],protected)
        if 'kinematics' in selected:
            source = record['signals']['kinematics']['input']
            if source['sha256']!=sha(motion):
                if not rra_motion:
                    raise ValueError('Filtered motion does not come from this route’s verified IK')
                original_names,original,_ = storage(motion)
                regular_names,regular,_ = storage(source['path'])
                if regular_names!=original_names or not np.allclose(
                        CubicSpline(original[:,0],original[:,1:],axis=0,extrapolate=False)(regular[:,0]),
                        regular[:,1:],rtol=1e-8,atol=1e-8):
                    raise ValueError('Regularized filter source does not match this route’s RRA motion')
        if 'wrench' in selected:
            source_tree = ET.parse(loads)
            source_wrench = loads.parent/source_tree.findtext('.//datafile') if independent else EXPORT/'external_loads.mot'
            source_hashes = [item['sha256'] for item in record['signals']['wrench']['inputs']]
            if sha(source_wrench) not in source_hashes:
                raise ValueError('Filtered wrench does not come from this route’s verified loads')
        motion = processed.get('motion',motion)
        loads = processed.get('loads',loads)
    tree = ET.parse(loads)
    wrench = ((loads.parent/tree.findtext('.//datafile')) if independent or 'wrench' in selected else EXPORT/'external_loads.mot').resolve(strict=True)
    if 'wrench' in selected and wrench!=processed['wrench']:
        raise ValueError('Filtered ExternalLoads XML does not reference the recorded filtered wrench')
    names,values,header = storage(motion)
    force_names,force,_ = storage(wrench)
    external = tree.findall('.//ExternalForce')
    if not external:
        raise ValueError('External force definitions missing')
    for entry in external:
        if entry.findtext('applied_to_body') not in ('calcn_l','calcn_r'):
            raise ValueError('Unsupported force application body')
        if any(entry.findtext(k)!='ground' for k in ('force_expressed_in_body','point_expressed_in_body')):
            raise ValueError('Ground-expressed prepared loads required')
        for k in ('force_identifier','point_identifier','torque_identifier'):
            prefix = entry.findtext(k)
            if not prefix or any(prefix+axis not in force_names for axis in 'xyz'):
                raise ValueError('Missing force/COP/torque columns for '+str(prefix))
    verified = independent['verified_window_s'] if independent else review['actual_window_s']
    event = window['target_window_s']
    if not event[0]-1e-9<=verified[0]<verified[1]<=event[1]+1e-9:
        raise ValueError(f'{label} verified window lies outside the target stance')
    lo,hi = max(verified[0],values[0,0],force[0,0]),min(verified[1],values[-1,0],force[-1,0])
    origin = (float(independent['original_time_origin_s']) if independent else
              float(storage(EXPORT/'original_IK.mot')[1][0,0]))
    if rra_motion:
        rate = window['point_rate_hz']
        grid = origin + np.arange(int(np.ceil((lo-origin-1e-9)*rate)),int(np.floor((hi-origin+1e-9)*rate))+1)/rate
        grid = np.round(grid,9)
        grid = grid[(grid>=values[0,0])&(grid<=values[-1,0])]
        values = np.column_stack([grid,CubicSpline(values[:,0],values[:,1:],axis=0,extrapolate=False)(grid)])
    else:
        # Keep the full kinematics file for derivative context and select only this route's verified solve samples.
        grid = values[(values[:,0]>=lo-1e-9)&(values[:,0]<=hi+1e-9),0]
    if len(grid)<3:
        raise ValueError(f'{label} has fewer than three verified samples')
    if independent:
        hashes = independent['source_hashes']
        unchanged = ([motion] if 'kinematics' not in selected else [])+([loads,wrench] if 'wrench' not in selected else [])
        for file in unchanged:
            if sha(file)!=hashes.get(str(file)):
                raise ValueError(f'{label} independently prepared file is missing or has a mismatched hash: {file}')
    degrees = next(s.split('=')[1].strip().lower() for s in header if s.lower().startswith('indegrees='))
    files = (model,motion,loads,wrench,*([Path(receipt)] if selected else []))
    return dict(model=model,names=names,values=values,grid=grid,degrees=degrees,origin=origin,
                tree=tree,wrench=wrench,files=files,verified=verified)


def main():
    assert not OUT.exists(), 'Use a new output folder; no overwrite of past runs.'
    OUT.mkdir(parents=True)
    osim.Logger.removeFileSink()
    osim.Logger.addFileSink(str(OUT / 'preparation_opensim.log'))
    osim.ModelVisualizer.addDirToGeometrySearchPaths(str(EXPORT / 'Geometry'))
    manifest = read(JOB / 'input_manifest.json')
    protected = {**manifest['source_hashes'], **manifest['prepared_inputs']}
    review = read(JOB/'final_review.json') if needs_rra() else {}
    window = read(JOB/'stance_window.json')
    available = {label:route_inputs(label,window,review) for label in SETTINGS['routes']}
    files = [JOB/'stance_window.json',JOB/'job_config.json',*[p for r in available.values() for p in r['files']]]
    if needs_rra():
        files.extend((JOB/'final_review.json',EXPORT/'original_IK.mot'))
    for p in files:
        protected[str(p)] = sha(p)
    strength = SETTINGS.get('muscle_strength')
    donor = strength.get('donor_model') if strength is not None else None
    if donor is not None:
        protected[donor] = sha(donor)
    checks = {p: Path(p).is_file() and sha(p) == h for p, h in protected.items()}
    save(OUT/'input_audit_before.json', dict(files=checks, all_unchanged=all(checks.values())))
    assert all(checks.values()), 'Source/provenance mismatch: inspect input audit.'
    assert CLI.is_file()
    first_route = next(iter(available.values()))
    grid = first_route['grid']
    origin = first_route['origin']
    base = osim.Model(str(JOB/'inputs/base.osim')); state=base.initSystem()
    muscles = [base.getMuscles().get(i).getName() for i in range(base.getMuscles().getSize())]
    assert len(muscles) == 92 and base.getForceSet().getSize() == 92
    active = [base.getCoordinateSet().get(i).getName() for i in range(base.getCoordinateSet().getSize())
              if not base.getCoordinateSet().get(i).isConstrained(state)]
    assert len(active) == 18
    job_config=read(JOB/'job_config.json')
    config = dict(subject=job_config['subject'], trial=job_config['trial'], side=job_config['target_side'], stage=SETTINGS['review_purpose'],
                  source_RRA_job=str(JOB), source_RRA_candidate=review.get('selected_iteration'),
                  marker_rate_hz=window['point_rate_hz'], original_first_frame=window['source_first_original_frame'],
                  original_time_origin_s=origin,
                  total_original_frames=window.get('total_original_frames'), source_run_config=SETTINGS,
                  target_20N_window_s=window['target_window_s'],
                  sampling='Independent verified grid per route; native low-pass disabled',
                  filtering=dict(mode=SETTINGS['filtering']['mode'],native_cutoff_Hz=-1,
                                 decision=SETTINGS.get('filtering_decision'),receipts=SETTINGS.get('filter_receipts',{})),
                  activation_exponent=SETTINGS['optimizer']['activation_exponent'], use_muscle_physiology=SETTINGS['optimizer']['use_muscle_physiology'], optimizer_tolerance=SETTINGS['optimizer']['tolerance'], optimizer_max_iterations=SETTINGS['optimizer']['max_iterations'],
                  reserve_optimal_force=SETTINGS['actuators']['optimal_force'], reserve_control_bounds=[SETTINGS['actuators']['control_min'],SETTINGS['actuators']['control_max']],
                  reserve_policy='Same one actuator per active coordinate in all routes; N for translation and Nm for rotation; permissive bounds expose infeasibility and are not acceptance criteria',
                  measured_mass_kg=SETTINGS['measured_mass_kg'], normalization_mass='Measured subject mass, NOT each RRA-adjusted mass',
                  original_active_coordinates=active, muscle_names=muscles,
                  upstream_mass=review.get('mass'), upstream_fidelity_warnings=review.get('selected_acceptance',{}).get('failures',[]),
                  external_forces='Both designated concurrent plates retained; no contact window extension',
                  engine=dict(cli=str(CLI), api_version=osim.GetVersionAndDate()),
                  interpretation='Route-specific numerical output; compare saved valid outputs in postprocessing')
    if all(np.array_equal(grid,r['grid']) and origin==r['origin'] for r in available.values()):
        config.update(expected_times_s=grid.tolist(),actual_window_s=[float(grid[0]),float(grid[-1])],samples=len(grid))
    save(OUT/'comparison_config.json',config)
    frame_rows=[]
    for label,inputs in available.items():
        for t in inputs['grid']:
            frame_rows.append(dict(route=label,time_s=float(t),original_frame_float=float(window['source_first_original_frame']+(t-inputs['origin'])*window['point_rate_hz']),
                                   target_stance_percent=100*(float(t)-window['target_window_s'][0])/window['target_duration_s']))
    with (OUT/'time_frame_map.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(frame_rows[0]));w.writeheader();w.writerows(frame_rows)
    all_results={}
    for label,inputs in available.items():
        source,motion,grid = inputs['model'],inputs['values'],inputs['grid']
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
        write_motion(inp/'motion.mot',inputs['names'],motion,inputs['degrees'])
        shutil.copy2(inputs['wrench'],inp/'external_loads.mot')
        tree=inputs['tree']; tree.find('.//datafile').text=(inp/'external_loads.mot').as_posix()
        tree.write(inp/'ExternalLoads.xml',encoding='utf-8',xml_declaration=True)
        model=osim.Model(str(inp/'muscle_model.osim')); st=model.initSystem();cs=model.getCoordinateSet()
        assert model.getMuscles().getSize()==92 and model.getForceSet().getSize()==92
        coordinates=[cs.get(i) for i in range(cs.getSize()) if not cs.get(i).isConstrained(st)]
        assert [c.getName() for c in coordinates]==active
        assert [model.getMuscles().get(i).getName() for i in range(92)]==muscles
        route=dict(source_model=str(source),source_model_sha256=sha(source),mass_kg=model.getTotalMass(st),
                   expected_times_s=grid.tolist(),actual_window_s=[float(grid[0]),float(grid[-1])],
                   original_time_origin_s=inputs['origin'],verified_window_s=inputs['verified'],
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
    independent = SETTINGS.get('ik_inputs')
    if independent:
        base = Path(path).resolve().parent
        for key in ('motion','loads'):
            independent[key] = str((base/independent[key]).resolve(strict=True))
        independent['source_hashes'] = {str((base/p).resolve()):h for p,h in independent['source_hashes'].items()}
    for p in [JOB,EXPORT]:
        if OUT==p or p in OUT.parents or OUT in p.parents:
            raise ValueError('Keep a new output folder separate from the source job tree')
    mode = SETTINGS['filtering']['mode']
    if mode not in (NO_ADDED,PROFILE):
        raise ValueError('Choose no added filtering or the supported 4th-order Butterworth 6 Hz profile')
    decision = SETTINGS.get('filtering_decision')
    if decision is not None:
        choice(decision)
        if decision['choice']!=mode:
            raise ValueError('Filter mode and confirmed decision disagree')
    if mode==PROFILE:
        choice(decision)
        receipts = SETTINGS.get('filter_receipts',{})
        if set(receipts)!=set(SETTINGS['routes']):
            raise ValueError('Supply a filter receipt for each requested route')
        SETTINGS['filter_receipts'] = {route:str((Path(path).resolve().parent/file).resolve(strict=True)) for route,file in receipts.items()}
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
    w=read(JOB/'stance_window.json');c=read(JOB/'job_config.json')
    r=read(JOB/'final_review.json') if needs_rra() else {}
    if w['status']!='ready' or w.get('side') not in ['L','R'] or not w.get('plate') or not w.get('contact_witnesses'):
        raise ValueError('Prepared target-side/plate/contact audit missing or not ready')
    if c['target_side']!=w['side']:raise ValueError('Target-side mismatch')
    if needs_rra() and (not r.get('selected_iteration') or not r['status'].startswith('selected')):
        raise ValueError('A matched selected RRA export is required by this prepared-job adapter')
    warnings=r.get('selected_acceptance',{}).get('failures',[])+r.get('calibration_warnings',[])
    if SETTINGS['review_purpose']=='research_analysis' and warnings and not SETTINGS.get('upstream_review_cleared',False):
        raise ValueError('Upstream RRA warnings need an explicit research-review disposition')
    inputs = {label:route_inputs(label,w,r) for label in SETTINGS['routes']}
    models=[]
    for file in dict.fromkeys(route['model'] for route in inputs.values()):
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
    motions=[dict(route=label,samples=len(v['grid']),start=float(v['grid'][0]),end=float(v['grid'][-1]))
             for label,v in inputs.items()]
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

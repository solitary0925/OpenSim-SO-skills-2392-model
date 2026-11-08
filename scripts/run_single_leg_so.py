"""Run prepared unilateral CGM24 SO with one verified target-foot plate."""

import argparse
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import opensim as osim

from muscle_strength import ORIGINAL, TRANSFER, prepare_strength_model
from review_so_results import storage

PELVIS = ['pelvis_tilt', 'pelvis_list', 'pelvis_rotation', 'pelvis_tx', 'pelvis_ty', 'pelvis_tz']


def leg_coordinates(side):
    return [f'{name}_{side.lower()}' for name in ('hip_flexion', 'hip_adduction', 'hip_rotation', 'knee_angle', 'ankle_angle', 'subtalar_angle')]


def write_storage(path, names, data, degrees):
    with path.open('w', encoding='utf-8', newline='\n') as file:
        file.write(f'SingleLegSO\nnRows={len(data)}\nnColumns={len(names)}\ninDegrees={degrees}\nendheader\n')
        file.write('\t'.join(names) + '\n')
        np.savetxt(file, data, delimiter='\t', fmt='%.12g')


def reduce_model(source, destination, side):
    suffix = '_' + side.lower()
    tree = source if isinstance(source, ET.ElementTree) else ET.parse(source)
    model = tree.find('Model')
    model.set('name', 'CGM24_single_leg_' + side)
    keep = {'BodySet': {'pelvis', 'torso'}, 'JointSet': {'ground_pelvis', 'back'}, 'ForceSet': set(), 'MarkerSet': set()}
    for set_name, extra in keep.items():
        objects = model.find(f'{set_name}/objects')
        for obj in list(objects):
            name = obj.get('name', '')
            if set_name == 'MarkerSet' or (name not in extra and not name.endswith(suffix)):
                objects.remove(obj)
        groups = model.find(f'{set_name}/groups')
        if groups is not None:
            groups.clear()
    tree.write(destination, encoding='utf-8', xml_declaration=True)


def select_plate(source, destination, side, plate):
    tree = ET.parse(source)
    loads = tree.find('ExternalLoads')
    objects = loads.find('objects')
    identifier = f'ground_force_{plate}_v'
    matches = [force for force in objects if force.findtext('force_identifier') == identifier]
    assert len(matches) == 1 and matches[0].findtext('applied_to_body') == 'calcn_' + side.lower(), 'Target force assignment mismatch'
    for force in list(objects):
        if force is not matches[0]:
            objects.remove(force)
    data = (source.parent / loads.findtext('datafile')).resolve(strict=True)
    names, values = storage(data)
    prefixes = (f'ground_force_{plate}_', f'ground_torque_{plate}_')
    columns = [0] + [i for i, name in enumerate(names) if name.startswith(prefixes)]
    assert len(columns) == 10 and np.isfinite(values[:, columns]).all()
    mot = destination / 'target_plate.mot'
    write_storage(mot, [names[i] for i in columns], values[:, columns], 'no')
    loads.find('datafile').text = mot.as_posix()
    xml = destination / 'target_loads.xml'
    tree.write(xml, encoding='utf-8', xml_declaration=True)
    return xml, data, values[[0, -1], 0]


def prepare(source_model, source_motion, source_loads, destination, side, plate, event, initial_activation=None,
            *, strength_profile=None, strength_donor=None):
    strength_audit = None
    if strength_profile is None and strength_donor is None:
        tree = ET.parse(source_model)
    else:
        tree, strength_audit = prepare_strength_model(source_model, strength_profile, strength_donor)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    free = destination / 'single_leg_free_base.osim'
    reduce_model(tree, free, side)
    if strength_audit is not None:
        strength_audit['target_side'] = side
        (destination / 'muscle_strength_audit.json').write_text(json.dumps(strength_audit, indent=2), encoding='utf-8')
    model = osim.Model(str(free))
    model.initSystem()
    coordinates = model.getCoordinateSet()
    names, values = storage(source_motion)
    header = source_motion.read_text(encoding='utf-8-sig').lower().split('endheader', 1)[0]
    assert 'indegrees=yes' in header.replace(' ', ''), 'Expected motion rotations in degrees'
    retained = {coordinates.get(i).getName() for i in range(coordinates.getSize())}
    columns = [i for i, name in enumerate(names) if name == 'time' or name in retained]
    active_leg = leg_coordinates(side)
    assert set(PELVIS + active_leg).issubset({names[i] for i in columns})
    assert values[0, 0] <= event[0] < event[1] <= values[-1, 0], 'Motion does not span the target event'
    times = values[(values[:, 0] >= event[0] - 1e-9) & (values[:, 0] <= event[1] + 1e-9), 0]
    assert len(times) >= 7
    motion = destination / 'single_leg_motion.mot'
    write_storage(motion, [names[i] for i in columns], values[:, columns], 'yes')
    loads, source_load_data, load_range = select_plate(source_loads, destination, side, plate)
    assert load_range[0] <= event[0] < event[1] <= load_range[1], 'External loads do not span the target event'
    angles = osim.Storage(str(motion))
    model.getSimbodyEngine().convertDegreesToRadians(angles)
    splines = osim.GCVSplineSet(5, angles)
    for name in PELVIS:
        index = splines.getIndex(name)
        assert index >= 0
        coordinate = model.updCoordinateSet().get(name)
        coordinate.setPrescribedFunction(splines.getGCVSpline(index))
        coordinate.setDefaultIsPrescribed(True)
    if initial_activation is not None:
        assert initial_activation in (.01, .1)
        for i in range(model.getMuscles().getSize()):
            osim.Thelen2003Muscle.safeDownCast(model.getMuscles().get(i)).setDefaultActivation(initial_activation)
    model.finalizeConnections()
    state = model.initSystem()
    coordinates = model.getCoordinateSet()
    assert all(coordinates.get(name).isPrescribed(state) for name in PELVIS)
    assert [coordinates.get(i).getName() for i in range(coordinates.getSize()) if not coordinates.get(i).isConstrained(state)] == active_leg
    assert model.getMuscles().getSize() == 46 and model.getForceSet().getSize() == 52
    prescribed = destination / 'single_leg_prescribed.osim'
    model.printToXML(str(prescribed))
    analysis = osim.StaticOptimization()
    analysis.setName('StaticOptimization')
    analysis.setStartTime(float(times[0]))
    analysis.setEndTime(float(times[-1]))
    analysis.setStepInterval(1)
    analysis.setUseModelForceSet(True)
    analysis.setUseMusclePhysiology(True)
    analysis.setActivationExponent(2)
    analysis.setConvergenceCriterion(1e-4)
    analysis.setMaxIterations(500)
    tool = osim.AnalyzeTool()
    tool.setName('SingleLeg')
    tool.setModelFilename(str(prescribed))
    tool.setReplaceForceSet(False)
    tool.setCoordinatesFileName(str(motion))
    tool.setExternalLoadsFileName(str(loads))
    tool.setLowpassCutoffFrequency(-1)
    tool.setInitialTime(float(times[0]))
    tool.setFinalTime(float(times[-1]))
    tool.setResultsDir(str(destination))
    tool.updAnalysisSet().cloneAndAppend(analysis)
    setup = destination / 'SO_setup.xml'
    tool.printToXML(str(setup))
    record = dict(side=side, plate=plate, target_20N_window_s=list(event), expected_times_s=times.tolist(),
                  initialization_activation=initial_activation, source_load_data=str(source_load_data),
                  motion=str(motion), model=str(prescribed), loads=str(loads), setup=str(setup),
                  muscle_strength_profile=strength_profile)
    (destination / 'single_leg_prepared.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    return record


def run(setup, opensim_cmd):
    setup = Path(setup).resolve(strict=True)
    log = setup.parent / 'SO_console.log'
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.run([str(opensim_cmd), 'run-tool', str(setup)], cwd=setup.parent,
                                 stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False)
    return process.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('model', 'motion', 'loads', 'output', 'opensim-cmd'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--side', choices=['L', 'R'], required=True)
    parser.add_argument('--plate', type=int, choices=[1, 2], required=True)
    parser.add_argument('--event', type=float, nargs=2, required=True, metavar=('ONSET', 'OFFSET'))
    parser.add_argument('--verified-target-contact', action='store_true', required=True)
    parser.add_argument('--initialize-activation', type=float, choices=[.01, .1])
    parser.add_argument('--muscle-strength', choices=[ORIGINAL, TRANSFER], required=True)
    parser.add_argument('--rajagopal-model', type=Path)
    parser.add_argument('--check-only', action='store_true', help='Validate muscle strength inputs without running SO')
    args = parser.parse_args()
    if args.check_only:
        _, audit = prepare_strength_model(args.model, args.muscle_strength, args.rajagopal_model)
        print(json.dumps({key: value for key, value in audit.items() if key != 'muscles'}, indent=2))
        return
    job = prepare(args.model, args.motion, args.loads, args.output, args.side, args.plate, args.event,
                  args.initialize_activation, strength_profile=args.muscle_strength, strength_donor=args.rajagopal_model)
    raise SystemExit(run(job['setup'], args.opensim_cmd))


if __name__ == '__main__':
    main()

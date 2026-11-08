"""Select and audit the maximum isometric forces of a Gait2392 SO model."""

from hashlib import sha256
from math import isfinite
from pathlib import Path
import xml.etree.ElementTree as ET


ORIGINAL = 'gait2392_original'
TRANSFER = 'rajagopal2016_fmax'

# Gait2392_Simbody/gait2392_simbody.osim, same forces on the left and right.
GAIT2392_FMAX = {
    'glut_med1': 819, 'glut_med2': 573, 'glut_med3': 653,
    'glut_min1': 270, 'glut_min2': 285, 'glut_min3': 323,
    'semimem': 1288, 'semiten': 410, 'bifemlh': 896, 'bifemsh': 804,
    'sar': 156, 'add_long': 627, 'add_brev': 429,
    'add_mag1': 381, 'add_mag2': 343, 'add_mag3': 488,
    'tfl': 233, 'pect': 266, 'grac': 162,
    'glut_max1': 573, 'glut_max2': 819, 'glut_max3': 552,
    'iliacus': 1073, 'psoas': 1113, 'quad_fem': 381, 'gem': 164, 'peri': 444,
    'rect_fem': 1169, 'vas_med': 1294, 'vas_int': 1365, 'vas_lat': 1871,
    'med_gas': 1558, 'lat_gas': 683, 'soleus': 3549, 'tib_post': 1588,
    'flex_dig': 310, 'flex_hal': 322, 'tib_ant': 905,
    'per_brev': 435, 'per_long': 943, 'per_tert': 180,
    'ext_dig': 512, 'ext_hal': 162, 'ercspn': 2500, 'intobl': 900, 'extobl': 900,
}

# Same-side muscle compartments. Adductor magnus has 3 vs 4 paths and is excluded.
GAIT2392_TO_RAJAGOPAL = {
    'glut_med1': 'glmed1', 'glut_med2': 'glmed2', 'glut_med3': 'glmed3',
    'glut_min1': 'glmin1', 'glut_min2': 'glmin2', 'glut_min3': 'glmin3',
    'glut_max1': 'glmax1', 'glut_max2': 'glmax2', 'glut_max3': 'glmax3',
    'semimem': 'semimem', 'semiten': 'semiten', 'bifemlh': 'bflh', 'bifemsh': 'bfsh',
    'sar': 'sart', 'add_long': 'addlong', 'add_brev': 'addbrev', 'tfl': 'tfl',
    'grac': 'grac', 'iliacus': 'iliacus', 'psoas': 'psoas', 'peri': 'piri',
    'rect_fem': 'recfem', 'vas_med': 'vasmed', 'vas_int': 'vasint', 'vas_lat': 'vaslat',
    'med_gas': 'gasmed', 'lat_gas': 'gaslat', 'soleus': 'soleus', 'tib_post': 'tibpost',
    'flex_dig': 'fdl', 'flex_hal': 'fhl', 'tib_ant': 'tibant', 'per_brev': 'perbrev',
    'per_long': 'perlong', 'ext_dig': 'edl', 'ext_hal': 'ehl',
}
RAJAGOPAL_EXTRA = {'addmagDist', 'addmagIsch', 'addmagMid', 'addmagProx'}


def read_forces(path, muscle_type, names):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    tree = ET.ElementTree(ET.fromstring(data))
    forces = {}
    for muscle in tree.findall('./Model/ForceSet/objects/*'):
        element = muscle.find('max_isometric_force')
        if element is None:
            continue
        name = muscle.get('name')
        if not name or muscle.tag != muscle_type or name in forces:
            raise ValueError(f'Unexpected muscle type or duplicate name in {path}: {name}')
        value = float(element.text)
        if not isfinite(value) or value <= 0:
            raise ValueError(f'Invalid maximum isometric force in {path}: {name}')
        forces[name] = (element, value)
    if forces.keys() != names:
        raise ValueError(f'Muscle inventory mismatch in {path}; missing {sorted(names - forces.keys())}, '
                         f'unexpected {sorted(forces.keys() - names)}')
    return tree, forces, {'path': str(path), 'sha256': sha256(data).hexdigest()}


def prepare_strength_model(source, profile, donor=None):
    """Return an independent model tree and the force audit without writing either file."""
    if profile not in (ORIGINAL, TRANSFER) or (profile == TRANSFER) != (donor is not None):
        raise ValueError(f'Select {ORIGINAL} or {TRANSFER}; the latter requires Rajagopal2016.osim')
    expected = {f'{name}_{side}': value for name, value in GAIT2392_FMAX.items() for side in 'lr'}
    tree, targets, source_info = read_forces(source, 'Thelen2003Muscle', expected.keys())
    modified = [name for name, (_, value) in targets.items() if value != expected[name]]
    if modified:
        raise ValueError(f'Source differs from original Gait2392 maximum isometric forces: {modified}')

    mapping = {}
    donor_info = None
    unused = []
    if profile == TRANSFER:
        if Path(donor).name.lower() != 'rajagopal2016.osim':
            raise ValueError('Use Rajagopal2016.osim from the official OpenSim model distribution')
        mapping = {f'{target}_{side}': f'{origin}_{side}'
                   for target, origin in GAIT2392_TO_RAJAGOPAL.items() for side in 'lr'}
        unused = sorted(f'{name}_{side}' for name in RAJAGOPAL_EXTRA for side in 'lr')
        donor_tree, donors, donor_info = read_forces(donor, 'Millard2012EquilibriumMuscle',
                                                     set(mapping.values()).union(unused))
        if donor_tree.find('Model').get('name') != 'Rajagopal2016':
            raise ValueError('Expected the official Rajagopal2016 model')

    rows = []
    for name, (element, original) in sorted(targets.items()):
        donor_name = mapping.get(name)
        selected = original
        if donor_name is not None:
            donor_element, selected = donors[donor_name]
            element.text = donor_element.text
        rows.append({'muscle': name, 'donor_muscle': donor_name, 'original_N': original,
                     'selected_N': selected})
    audit = {'profile': profile, 'source_model': source_info, 'donor_model': donor_info,
             'transferred_count': len(mapping), 'retained_count': len(targets) - len(mapping),
             'unused_donor_muscles': unused, 'muscles': rows}
    return tree, audit

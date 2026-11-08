# Version0.1.0 validation and limits

## Validation evidence

The initial whole-body adapter was exercised on a partially measured walking stance with three prepared model and motion routes. Independent checks compared native outputs, original timestamps, the common valid window, residual and reserve measures, and protected input checksums. Per-frame failures remained visible even when the solver returned a successful process exit code.

The v0.3.0 muscle strength profiles passed whole-body input preflight and single-leg model preparation using OpenSim 4.5. Four bundled unit tests cover native failure messages, constraint violations, incomplete numerical records, and integration across valid intervals. These checks establish the scope of the implementation tests.

## Transfer limitations

- One subject, one partial walking stance does not validate running, all subjects, full-stance peaks, arbitrary muscle models or clinical interpretation.
- The bundled runner needs the named prepared-job contract. It does not ingest raw C3D/VSK or prepare force-plate assignments and baseline corrections.
- No added filtering is implemented. A chosen filter needs a validated upstream preparation step with explicit provenance; unfiltered IK can produce poor acceleration/residual behavior.
- Standard SO neglects activation dynamics and assumes rigid tendons. Running interpretation, especially plantarflexor/Achilles behavior, must acknowledge this.
- Same-grid interpolation and short-window differentiation can affect accelerations and peak forces; matched windows do not remove endpoint sensitivity or guarantee alias-free resampling.
- A mass/COM-adjusted model differs from the original. Use the optional control route to disentangle parameter and motion effects; trial-specific masses should not silently become the normalization denominator.
- Generalized pelvis moments are not Cartesian torque vectors. Do not rotate them as though they were measured free torques.
- Broad reserve bounds and numerical feasibility are not physiological validation. Review muscles, residuals, reserves, kinetics, motion fidelity and EMG when available.
- The bundled reviewer supplies tables/reports. Plotting and research acceptance are explicit subsequent steps, not advertised as automatically validated functionality.

## Primary documentation

- [SO input/output files](https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53089624/Getting%2BStarted%2Bwith%2BStatic%2BOptimization)
- [SO mathematical method](https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53089619/How%2BStatic%2BOptimization%2BWorks)
- [OpenSim best practices](https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53087686)
- [SO assumptions and implementation](https://opensimconfluence.atlassian.net/wiki/spaces/OpenSim/pages/53084318/Custom%2BStatic%2BOptimization%2Bin%2BMATLAB)

These documentation links support definitions and workflow; local numerical choices are not presented as universal official thresholds.

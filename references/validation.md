# Validation and limits

## Verification checks

- The bundled review tests cover native failure flags despite finite storage, large constraint violations, nonfinite or missing output, and integration that never bridges rejected samples.
- The 6 Hz option was verified for filter response, original timestamps, fixed-origin wrench consistency, file hashes and prepared SO input selection. Full native SO execution with the new option is a separate validation step.
- A solver can finish and save finite output even when individual frames fail. Review convergence by frame and inspect residual and reserve curves. Label maximum-component summaries explicitly because RMS and peak can come from different axes.

## Transfer limitations

- Validate the workflow for each movement class and model. A partial walking stance cannot establish full-stance peaks or performance for running.
- The bundled runner needs the named prepared-job contract. It does not ingest raw C3D/VSK or prepare force-plate assignments and baseline corrections.
- An optional 6 Hz input profile uses the bundled preprocessor and explicit provenance. Recheck derivative and residual behavior for the selected motion and loads.
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

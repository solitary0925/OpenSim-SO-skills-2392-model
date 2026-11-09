# Prepared-job adapter

## Scope and environment

The runner accepts a **prepared RRA stance-job directory** using the documented CGM24 input contract. An existing prepared job can be read independently of the RRA skill installation.

Required job files:

- `input_manifest.json` with `source_hashes` and `prepared_inputs` SHA256 maps.
- `job_config.json` with subject/trial/target side and original preprocessing decisions.
- `stance_window.json` containing `status=ready`, point rate, original first frame, target window and duration, explicit plate designation and recorded contact witnesses.
- `final_review.json` with selected candidate, actual time window, mass diagnostics and acceptance warnings.
- `inputs/base.osim` (original muscle model, same frame as exported motion).
- `final_original_frame/RRA_model.osim`, `RRA_motion.mot`, `original_IK.mot`, `ExternalLoads.xml`, `external_loads.mot`, and available `Geometry`.

Python needs OpenSim API, NumPy and SciPy; the native CLI is OpenSim4.5. Use the executable/environment actually verified on the destination machine. No package installation or backend switch is implicit. API and native tool versions are recorded. Models must initialize with exactly92 muscles, no other pre-existing forces, and the original18 active coordinates. Other topology/force sets need explicit adaptation rather than deleting forces to fit this profile.

## Configure

Copy `assets/prepared-comparison.example.json` to a run-specific file and replace the named paths and measured mass. Set `routes` to the routes the user requested:

- `IK_original_model`
- `IK_RRA_model_control`
- `RRA_adjusted_model`

Every route has its own verified solve window and frame grid. RRA is cubic-interpolated to original frame timestamps within its native coverage, without extrapolation or a new filter. An IK route uses all original IK samples supported by its own verified loads and contact. The fallback for legacy configurations uses the matched export inputs and their verified scope. If fuller independent IK coverage is available, provide `ik_inputs` for `IK_original_model` rather than inheriting the RRA export window. Supply `motion`, `loads`, `verified_window_s`, `original_time_origin_s`, and a `source_hashes` map for the motion, load XML and its wrench file. Hashes must match the upstream contact-checked files. With only that route selected and those inputs supplied, the job folder needs the original prepared model, stance audit and input manifest. It can be used before an RRA result exists.

Record the actual user purpose, filtering and contact decisions. Set `review_purpose=technical_pilot` for an explicitly authorized test with upstream warnings. `research_analysis` requires documented upstream review clearance. Use [input filtering](input-filtering.md) for the supported optional profile and per-route receipts.

## Muscle strength

Record the user's chat selection in `muscle_strength.profile` before execution. `gait2392_original` verifies and retains all 92 standard Gait2392 maximum isometric forces. `rajagopal2016_fmax` starts from the same verified baseline and requires `muscle_strength.donor_model` pointing to the official `Rajagopal2016.osim`. Leave the donor path null for the original profile. Old configurations without `muscle_strength` retain their supplied input model for backward compatibility. New skill runs require the explicit choice.

The transfer copies only `max_isometric_force` in N into 72 corresponding Thelen2003 muscle units (36 per side). The remaining 20 keep their Gait2392 values. Per side these are three adductor magnus paths, pectineus, quadratus femoris, gemelli, peroneus tertius, erector spinae and the internal and external obliques. The two models use different adductor magnus subdivisions, so those values are left as supplied by Gait2392. Geometry, muscle paths and force–length parameters are inherited from the selected Gait2392/CGM24 input model. Identify the output as Gait2392/CGM24 with Rajagopal 2016 Fmax. Transferring the parameter is a strength sensitivity setup and does not inherit the validation of the full Rajagopal model. [OpenSim model distribution](https://github.com/opensim-org/opensim-models/tree/master/Models/Rajagopal) · [Rajagopal et al. (2016)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5507211/)

The runner verifies the muscle inventories and finite positive forces, checks the Gait2392 baseline, and records source and donor SHA256 plus each muscle's original and selected Fmax in `<route>/inputs/muscle_strength_audit.json`. Resolve incompatible inputs before running the selected profile.

## Commands

```text
<verified-python> scripts/run_prepared_comparison.py --config <run-config.json> --check-only
<verified-python> scripts/run_prepared_comparison.py --config <run-config.json>
<verified-python> scripts/review_so_results.py --folder <run-output-folder>
```

`--check-only` imports the API, initializes original/RRA models, verifies topology, source hashes, load metadata, times, settings and native CLI version; it performs zero SO/ID solves and creates no output folder. It is not a new independent validation of C3D calibration or whole-body contact evidence: inspect the prepared audit and actual source decisions.

The runner refuses to reuse an output directory. It generates one SO and one matching ID reference per requested route, with an independent model/motion/setup/log/status. A native call has a600s timeout. Failed native execution or absent storage stops that run with saved error evidence; per-frame SO failures are saved as partial results and do not prevent other requested comparison routes. No automatic numeric retries, higher strength or relaxed bounds. Future authorized retries need a new output folder.

## Initial numerical settings

- Original muscle bounds retained; use_model_force_set=true.
- Activation exponent2, physiology=true, tolerance1e-4, maximum100 optimizer iterations per frame.
- One CoordinateActuator per active coordinate: `optimal_force=1`, controls−1000 to1000; translation in N and rotation in Nm. These broad pilot bounds expose failures and large residual demand. They are not acceptance limits; do not transfer them to other profiles as a scientific recommendation.
- Native low-pass is disabled. Optional external input preprocessing and force-zero offsets are recorded separately.
- ID reference excludes muscles in the muscle-only model. It is diagnostic and separate from the SO solve.

## Reviewer outputs

`review_so_results.py` uses Python standard library plus NumPy; it does not import OpenSim or a plotting library. It verifies expected row times, muscle names, finite values and configured activation bounds, reads native failure messages and constraint violations, and reports discrepancies rather than silently dropping them.

- `SO_review.json`, `SO_review.md`, `route_quality_summary.csv`.
- `invalid_frames.csv` with native time, original frame and ordinal/total when available, and original stance percentage.
- `muscle_metrics.csv`: per-route muscle peaks, means, peak times and adjacent-valid-interval integrals over each route's own valid samples, with raw SI units and measured-mass normalization.
- `validated_muscle_curves.csv`: missing values at failed times, never zero-filled.
- `reserve_vs_ID_reference.csv` when matching native ID results exist.

The reviewer is repeatable postprocessing; it never reruns solves or modifies raw output. Bounds and high activation counts are reported separately from native convergence. No inferential statistics, automatic research acceptance or automatic plots.

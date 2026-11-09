# Single-leg gait static optimization

Use this route when the target foot has verified measured support but the other foot's load is missing or the user explicitly requests a target-only comparison. The original-knee CGM24 adapter retains the target leg, pelvis and rigid torso needed for muscle paths. It uses the selected muscle strength profile and retains coordinate locks and joint reserves. It removes the other leg and prescribes all six pelvis coordinates from the prepared IK using OpenSim GCV splines. The only applied external wrench is the designated target plate's force, center of pressure and free moment on the target calcaneus.

## Inputs and eligibility

- Use the original scaled model prepared for whole-body SO, with its 92 muscles, joint reserves and pelvis actuators, plus the full-context IK motion and matching prepared ExternalLoads XML and wrench data. Reuse the documented filtering, rotation and force-zero choices. Record file hashes, units, time coverage and the C3D frame-to-time map.
- Match the target side to the explicit Vicon plate assignment and the applied body. Independently verify the target foot's force and contact evidence over the requested support. A recorded force crossing alone does not show that the target foot's full load was captured. Flag boundary censoring, suspected off-plate or partial contact, shared plate signals and unverified intervals. Keep those segments out of full-stance comparisons until resolved.
- Use onset and offset from the target foot's audited 20 N event. Run all verified samples of the chosen route across the event. If input or contact coverage is incomplete, supply the longest verified continuous range to `--event` and preserve the original 20 N bounds separately. Preserve enough motion before and after for spline and derivative preparation. Other routes' output times and failure frames are used only in a requested later comparison.

## Run

With compatible OpenSim Python and the OpenSim CLI, run the bundled adapter into a new output directory. The verified-contact switch records that the caller completed the contact review.

```powershell
python scripts/run_single_leg_so.py --model SO_model.osim --motion IK_full.mot --loads ExternalLoads.xml --output single_leg_L --opensim-cmd opensim-cmd --side L --plate 2 --event 0.40 1.10 --verified-target-contact --muscle-strength gait2392_original
```

If the user selects the transfer, pass `--muscle-strength rajagopal2016_fmax --rajagopal-model <path-to-Rajagopal2016.osim>`. Use `--check-only` to validate the strength inputs before preparing a model or running SO. Complete the motion, load and contact checks separately. The adapter applies the [strength profile](execution.md#muscle-strength) to the bilateral input in memory before reduction, retaining 36 transferred and 10 original muscle units on the target side. The audit lists both sides and identifies the target side.

The adapter saves the reduced and prescribed-pelvis models, selected target load, motion, setup and expected time grid. Use `--prepare-only` to build these inputs without solving SO. A normal run saves the native log and uses muscle physiology, activation exponent 2, 500 iterations per frame and tolerance 1e-4. For selected input preprocessing, use [input filtering](input-filtering.md). If native initialization fails in Thelen muscle fiber equilibrium, a separate attempt may use `--initialize-activation 0.01` or `0.1`. Record the change and keep the earlier attempt.

## Validate and compare

- Review native convergence per frame. The bundled `review_so_results.py` exposes `storage` and `native_validity` for this purpose. Match the activation and force timestamps to `expected_times_s` from `single_leg_prepared.json`, check muscle columns and bounds, and retain failure reasons and original frame positions. Leave failed samples missing.
- On a new model/data setup, compare the six target-leg ID moments from the original model with assigned loads and the reduced model with the target wrench. Use identical motion and analysis times. For this check use the reduced free-base model before adding prescribed pelvis functions. Report differences and the numerical tolerance. Then check target joint reserve loads and muscle activation saturation in SO.
- When requested, compare saved outputs on the intersection of valid timestamps, preserving original stance percentages. Report force RMSE and peak differences, activation differences in percentage points and common sample counts. Preserve the independent SO results and disclose missing or failed samples.
- Describe the output as target-leg estimates conditional on the recorded pelvis motion. This route provides no estimate of the unmeasured contralateral wrench or whole-body dynamic consistency. Use the whole-body route to compare pelvis residuals.

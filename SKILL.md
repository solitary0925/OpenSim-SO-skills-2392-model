---
name: opensim-vicon-so
description: Run and review gait-stance OpenSim static optimization for muscle forces and activations, with provenance, contact and timing checks, and IK versus RRA comparisons. Supports prepared whole-body and prescribed-pelvis single-leg routes for original-knee CGM24 gait models.
---

# OpenSim Vicon SO

Version **0.3.0**. Use for muscle-force/activation estimation from prepared gait kinematics and verified external loads. Read [workflow](references/workflow.md), [whole-body execution](references/execution.md) and [validation and limitations](references/validation.md). For a target-leg calculation using only that foot's designated plate, use the [single-leg route](references/single-leg.md). Both bundled runners use the original-knee CGM24 model family. Other models and raw C3D require separate preparation.

## Decide and preflight

Identify subject, trial, target L/R event, IK or RRA route, comparison purpose and output folder. Ask whether to add filtering unless an applicable decision exists; a fourth-order 6Hz Butterworth zero-phase low-pass is an example, not a default. Confirm kinematics and force processing separately. Never assume IK has already been filtered. The initial runner implements **no added filtering only**, including reuse of documented upstream processing; a new filtering choice needs implementation and validation first.

Before starting a new SO run or batch, ask in chat which muscle strength profile to use. Offer **original Gait2392 maximum isometric forces** (`gait2392_original`) and **Rajagopal 2016 maximum isometric forces transferred onto Gait2392** (`rajagopal2016_fmax`). Wait for an explicit selection that applies to this run or batch. Keep the same selection across IK/RRA routes unless the user explicitly requests a strength comparison. If the selected inputs fail the [strength preflight](references/execution.md#muscle-strength), report the issue in chat and wait for corrected inputs or a new choice.

Check runtime availability, model/motion/load sources and SHA256, units, coordinate names/locks, rotations and time coverage, original frame mapping, force-zero decisions and explicit foot/plate designations. For whole-body SO, retain concurrent contralateral loads and use the verified continuous window within the target 20 N stance. For single-leg SO, verify the target foot's measured contact over the requested interval and prescribe the pelvis from the corresponding IK. Preserve omitted head/tail and original stance percentage for either route. Report missing/changed files and new contact faults in chat. Obtain a repair or explicit skip/diagnostic disposition before dependent analysis, continuing independent approved jobs when possible.

Use the matched original model with IK, or the selected RRA candidate's adjusted model with its motion. Warned/diagnostic inputs need an applicable technical-test/review decision; do not silently treat them as accepted. A comparison uses the same loads, window, sampling and SO settings. The optional third route—RRA model with original IK—separates model-parameter changes from motion changes. Do not automatically require three runs for ordinary SO.

## Prepare and run

Preserve muscles, their bounds, original knee configuration and coordinate locks. Apply the chosen maximum isometric force profile to an independent SO model copy. Save the profile and per-muscle source and selected values in `muscle_strength_audit.json`. Configure documented residual and reserve actuators rather than reusing strong RRA joint motors. Their optimal forces and control bounds are numerical settings, not biological validity thresholds. Keep N and Nm separate. See the workflow for the pilot's actual choices and transfer limits.

Generate and retain the muscle model, SO actuator model and AnalyzeTool/StaticOptimization setup. Record activation exponent, muscle-physiology option, optimizer tolerance, per-frame iteration cap and filtering. The pilot used exponent2, physiology=true, tolerance1e-4 and100 iterations/frame. This is not the TWSA200-proposal budget. Existing ID files are not mandatory SO inputs; an ID reference with the same model/motion/loads is useful for reserve review.

Run the native OpenSim tool with logs and status records. Preserve `*_StaticOptimization_force.sto`, `*_StaticOptimization_activation.sto` and controls XML. A zero exit code or complete finite storage file does **not** prove every frame converged.

## Validate every sample and explain quality

Read native failure times and acceleration-constraint violations; check storage time grids, columns, finite values and actuator/muscle bounds. Exclude failed samples from validated data while retaining original files. Plot gaps; never fill failures with zero or interpolate them into success. Report original frame, ordinal/total frames, original time and stance location. Classify blocked inputs, process failures, partial numerical failures and complete numerical solves separately.

Report joint reserves (Nm), muscle forces (N), activation saturation and visible spikes. Compare reserve peaks to corresponding ID-moment peaks with low-denominator warnings. For whole-body SO, also report pelvis translational residuals (N) and rotational generalized residuals (Nm). If reporting maximum component RMS and maximum absolute peak, identify them as component statistics. Prescribed-pelvis single-leg SO omits pelvis residual actuators. Native numeric convergence and small reserves do not establish muscle-force validity. Retain upstream marker/motion and mass/COM warnings. Do not automatically change muscle strength, tendon parameters or actuator bounds to force success.

## Compare and deliver

Use only muscle columns for muscle-force/activation metrics; storage may also contain reserves and other loads. Save peaks, means, times and valid-interval integrals. Normalize by **measured** subject mass/weight, not trial-specific RRA-adjusted mass. Compare routes on common valid times, integrate adjacent valid intervals only and disclose missing coverage. A partial stance cannot provide complete-stance peaks/integrals or be relabeled0–100%. A single-trial pilot is descriptive, not an inferential statistical analysis.

Save reproducible configs, provenance, setups, logs, raw/validated storage or CSV, failed-frame locations, quality measures, fixed-script figures where requested and a Markdown report. In chat state actual successes/failures, abnormal positions, residuals/reserves, saturation and cropping limitations. Verify protected source hashes again after execution. SO activation is an estimated model quantity, not measured EMG; standard SO ignores activation dynamics and uses rigid-tendon assumptions, material for running interpretation.

The supplied reviewer produces JSON/CSV/Markdown; figures are a coordinating-agent step using the chosen plotting backend. Do not claim it automatically provides a C3D pipeline, validated running analysis or plots it did not generate. No automatic CMC/JRA or GitHub publication. JRA needs a separately reviewed, route-consistent model, motion, external loads and muscle/actuator forces.

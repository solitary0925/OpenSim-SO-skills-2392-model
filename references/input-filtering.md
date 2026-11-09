# Confirm the input filter before each new batch

Ask whether to use no additional filtering or fourth-order Butterworth low-pass at 6 Hz, applied forward and backward for zero phase. If selected, confirm kinematics, force/torque, or both. A user request to add the option does not select it for a run. Reuse an existing decision only if it applies to the same batch. Record the actual decision and verify the upstream processing of every selected signal. Reuse a verified already-filtered input with no additional filtering.

Record `status: confirmed`, `choice: no_added_filtering` or `butterworth_4_6hz_zero_phase`, `confirmation_source`, `signals` (`kinematics`, `wrench` or both), and `upstream_filtering` with `verified_unfiltered` for each signal receiving the filter. Use an empty signal list for no additional filtering.

The design is fourth-order per pass, with 6 Hz as the single-pass design cutoff. The forward–backward composite has a different magnitude response. Use full available uniformly sampled verified context with more than 15 finite samples and a rate above 12 Hz. Preserve timestamps and source files. A short, gappy or irregular source needs a separately validated preparation decision. Do not silently resample, interpolate gaps, change the frequency or apply the filter again.

For external loads, use ground-expressed force and torque in SI units. Filter force and moment about a fixed origin together, retain the recorded application point, and reconstruct the equivalent torque at that point. Keep zeroed unloaded samples at zero in contact-masked load tables. Use the original calibrated vertical force after any separately authorized baseline correction for 20 N events. Filtered samples do not redefine contact or add a plate assignment. Report timing/endpoint sensitivity where relevant.

Use the bundled preprocessor with NumPy and SciPy installed in the OpenSim Python environment when building derived inputs. It writes a new folder and an `input_filtering.json` receipt with settings, paths and SHA-256 values. Leave the solver's native low-pass disabled when feeding these files.

```text
python scripts/input_filter6.py --decision decision.json --output filtered_inputs --motion original.mot --translations pelvis_tx pelvis_ty pelvis_tz --loads ExternalLoads.xml
```

Supply only the arguments for the chosen signals. Declare all translational coordinate names for the model. Keep original time, frame and contact records alongside filtered inputs.

## SO runs
Single-leg: pass `--filter-decision` and, when selected, `--filter-receipt` with the matching `--motion` and/or `--loads` paths. Prescribe the pelvis from the same processed motion. Whole-body: set `filtering.mode` and `filtering_decision.choice` to the same value. For this profile provide `filter_receipts` keyed by selected route. Each receipt must represent that route's verified motion and loads. Build the RRA regular time grid with the documented provenance before applying the helper if the native replay is irregular. Matching ID reference uses the same processed motion and loads.

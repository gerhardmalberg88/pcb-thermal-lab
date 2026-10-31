# Implementation and verification checklist

**2026-10-31: the reduced CPU execution is complete; detailed-region validation
is UNCONVERGED.** All twelve steady cases pass source/artifact and heat-balance
checks. The 10/20 mm comparison changes a local resistor hotspot by 1.831 °C
(5.03% of rise), exceeding both limits. Published results are provisional.
The BMS simulation scope is now closed at these completed steady cases. The
original transient/GPU/full-domain extensions have been canceled for BMS, not
marked as completed validation.

## Reduced deliverable and checks

- [x] Preserve and verify four automatic cases at h = 5/10/20/50 W/m²K.
- [x] Complete eight odd/even cases at h = 10, 5, 50, 20 using the same converted
  production mesh, CPU/Hypre, two MPI ranks and one thread per rank.
- [x] Add bounded `study` schedule selection, per-case deadlines, a two-minute
  shutdown reserve, checkpointed progress and owned-container cleanup.
- [x] Pass all 29 unit tests, including case selection, changed inputs/artifacts,
  saved configuration/SIF checks, direct-run path resolution and Podman/Docker
  cleanup command handling.
- [x] Exercise real Podman deadline cleanup: the interrupted log remains, an
  independent control container survives and no owned container remains.
- [x] Execute the one permitted 20 mm comparison within its 20-minute cap.
  The run passes heat accounting, but the local hotspot convergence check fails.
- [x] Publish twelve completed provisional cases, three figures and compact
  CSV/provenance, with the failed domain criterion visible. Incomplete solves
  and large native results are excluded from commit candidates.
- [x] Review documentation links/images, whitespace, candidate sizes, local
  paths, credential patterns and ignored build/native outputs for Git handoff.
- [x] Confirm numerical services and containers have stopped. No staging,
  commits, pushes, branch or Git configuration changes were made.

The numerical window was **20:25:57–21:41:14 Helsinki time: 75 minutes 16 seconds**,
within the original 120-minute limit. The first odd h=10 attempt stopped after
11 minutes 45 seconds at the host-memory reserve during flux calculation.
Sampled solver RSS was 7.031 GB; host available memory fell to 1.507 GB, below
its 1.611 GB (1.5 GiB) reserve. After freeing RAM, one authorized CPU retry used
a 12-minute cap per case and retained the original deadline and memory limits.
It completed all eight missing cases and the limited comparison. The failed
attempt's native logs/resources remain local. Older experiments stayed stopped.
See [study operation](studies.md).

## BMS scope closure

No further BMS thermal simulations are planned. The transient input and its
warm-up/cooldown and timestep-refinement plan have been removed. Further domain
refinement, BMS CUDA comparisons and direct-solver experiments are excluded.
Existing source, native results and diagnostic evidence remain available.

The numerical limitation is unchanged: automatic h=10 global maximum changes
61.2413 → 61.4036 °C, while R361 changes 51.5804 → 53.4113 °C. Local domain
convergence has not been established. These are provisional steady predictions;
closing the work scope does not establish transient peaks or hardware accuracy.

## Implemented tooling

- [x] Standalone Apache-2.0 lab, attribution, package/launcher and Mermaid workflow.
- [x] Pinned CPU/tools/CUDA recipes; bootstrap/build/doctor/run/study/sweep/gui/export/import.
- [x] Content-hashed stages, shared geometry cache, input preservation and failed logs.
- [x] Saved KiCad outline, stackup, all-layer copper, zones, holes, placements and STEP.
- [x] CB connectivity verification and resistor-only I²R power schedules.
- [x] Finite copper, hollow barrels, solder/mask openings, resistor bodies and terminals.
- [x] Whole-board hybrid, explicit and cropped geometry; named conformal interfaces.
- [x] Separate straight-sided mechanical STEP/contact-layer support. General curved
  assemblies are rejected; no mechanical cooling assembly is in the BMS cases.
- [x] Native Elmer mesh/SIF/restart/fields/scalars/line samples/logs; heat balance and
  extrema reports; relocatable ParaView state and headless images.
- [x] Authenticated GUI launchers with persistent independent preferences.
- [x] Memory/disk safeguards, sequential workflows and safe image transfer.

## Verified numerical and operational evidence

Generated evidence stays in ignored `results/validation/` and in each case's
configured output directory. These are local paths to reproduce, not links that
must exist in a fresh clone. The hardware snapshot preserves compact results.

| Check | Measured evidence | Limit |
|---|---|---|
| Analytical conduction | Maximum error 0.000126 K | Verification fixture |
| Analytical transient cooling | 0.033343 K error at 10 s | Verification fixture |
| Heater normalization | Density-two slab verifies Elmer W/kg convention | Each source normalized to watts |
| Layered PCB with hollow via | 0.1 W balanced to about 7e-11 relative error; interface/tag checks pass | Synthetic fixture |
| STEP coordinates | Outline/Z discrepancy about 1e-7 mm; all 17 heater centres agree | Saved board |
| CPU serial/MPI | Cached transient scalar differences <1.6e-7 | Small fixture |
| Scheduled source wrapper | Cached/native histories differ <3.1e-12 through switching/cooldown | Small fixture |
| CPU/CUDA | Maximum small-mesh difference about 1.46e-6 °C | BMS-sized CUDA has not converged |
| Limited 10/20 mm detail check | Maximum local change 1.830867 °C; 5.029% of reference rise | **FAIL: domain unconverged** |
| Corrected BMS mesh refinement | Scales 1.5/1/0.75; baseline-to-fine hotspot change 0.081435 °C, 0.2245% of rise | Mesh check passes; domain remains separate |
| Overlay tolerance | 1 µm versus 0.1 µm: maximum hotspot difference 0.001690 °C | Production remains 0.1 µm |
| Merged identical dielectric plies | Maximum hotspot change 0.104078 °C; material-volume error <4e-16 | Diagnostic; production mesh retained |
| GUI reopening | KiCad, FreeCAD, Gmsh, ElmerGUI and ParaView inspected; source hashes unchanged | Authenticated private display |
| Portability | Clean-copy CPU example and CPU/tools/CUDA archive round trip pass; installed editable CLI resolves its own example from another directory | x86-64 Linux/Podman; Docker execution not exercised |
| Field compression | All field arrays preserved exactly | Native fields remain local |

The production BMS mesh has 2,052,022 nodes and 3,603,579 prisms. It uses the
whole board, a 10 mm detailed region, and the saved soldermask openings. Earlier
pre-correction diagnostic meshes are retained locally and excluded from the
published sweep. Automatic h=5/10/20/50 maxima are
84.9592/61.2413/48.6308/39.5647 °C, with passing heat accounting.

## Closed BMS extensions and separate lab backlog

The former BMS transient, full detail/crop, CUDA and direct-solver tasks are
removed from the active plan. Short transient pilots do not constitute full
warm-up/cooldown verification. Two BMS classical-AMG attempts failed/stagnated;
aggregation/DILU remains untested. The isolated MUMPS steady pilot agreed within
2.85e-7 °C, while corrected full-mesh CHOLMOD pilots exceeded the safe RAM budget.
These are retained diagnostic facts, not pending BMS runs or completed validation.
Hardware correlation, environmental inputs and supplier material properties
remain unverified; they are separate from the closed simulation scope.

The reusable lab still supports transient and backend workflows for other cases.
Its independent crop-boundary fixture remains a tooling verification item:

- [ ] Verify the crop-boundary snapping fix with the synthetic layered-via
  fixture (`tests/verify_crop_boundaries.py`); this is not a BMS simulation task.

## Physical and reporting limits

Only selected balancing resistors generate heat. Other component copper remains,
but component bodies and internal losses are omitted. Material constants,
25 µm barrel plating, 100 µm solder and ideal bonded interfaces are engineering
assumptions. Radiation, enclosure/mounting heat paths, cell depletion and thermal
balancing pauses are disabled. Nearby board temperatures are not junction
temperatures or external NTC accuracy predictions.

A completed steady case requires successful native Elmer termination, unchanged
design hashes and <1% heat imbalance. Mesh/detail acceptance requires changes
below both 1 °C and 2% of temperature rise. Simulation verification and measured
hardware correlation are distinct. No staging, commits, pushes, branch or Git
configuration changes are part of this work.

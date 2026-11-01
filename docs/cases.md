# Thermal case configuration

Case files use **JSON only**, parsed with Python's standard library. Use
`.json` filenames, double-quoted keys and strings, and no comments or trailing
commas. Legacy YAML syntax is rejected. Paths are relative to the case file.

`"schema": 1` identifies the case interface. Paths are relative to the case file;
`project_root` encloses the board and mechanical inputs. `output` must be a
dedicated directory. The pipeline owns its stage directories; manual work
belongs in another directory. CLI execution options override case execution.

| Section | Meaning |
|---|---|
| `board`, `project_root`, `output` | Source ownership and generated files |
| `sources.refs` | Unique populated resistor references; independent of modeled board extent |
| `sources.kind` | `balancing` derives CB0–CB16 powers; `watts` uses the explicit `watts` mapping |
| `sources.schedule` | `automatic`, `odd` or `even`; adjacent manual channels are outside this study |
| `geometry.mode` | `hybrid`, `explicit` or `crop` |
| `geometry.detail_margin_mm` | Default 10 mm around resistor package footprints |
| `geometry.tile_mm` | Default 5 mm spatial averaging outside the detailed region |
| `geometry.crop_mm` | `[xmin,ymin,xmax,ymax]` in saved KiCad XY coordinates |
| `geometry.plating_mm`, `solder_mm` | Initial assumptions: 0.025 mm barrel walls and 0.1 mm solder |
| `mesh.fine_mm`, `coarse_mm`, `scale`, `chord_mm` | Gmsh sizing and KiCad polygon chord error |
| `materials` | Conductivity diagonal `[kx,ky,kz]` W/mK, density kg/m³, heat capacity J/kgK |
| `cooling` | Ambient °C and exposed-surface convection W/m²K |
| `analysis` | `steady` or `transient` |
| `transient` | On/off durations, timestep and field-output interval in seconds |
| `execution` | Backend, MPI ranks, threads per rank and GPU count |

The initial material constants are explicitly assumed: copper k=400, FR4
k=[0.8,0.8,0.3], soldermask k=0.2, resistor ceramic k=25, effective terminals
k=67 and solder k=50 W/mK. Their densities and heat capacities are stored in
the physical case, included in provenance and used for transient energy checks.
They are not manufacturer-certified thermal models. Resistor power is uniformly
distributed through the modeled ceramic body, so its maximum is a body-model
temperature rather than a validated resistive-film temperature.

The hybrid approximation mixes local copper fractions in parallel in-plane,
combines layer resistance in series through thickness and includes plated-via
area and volume-weighted heat capacity. It does not resolve all remote copper
connectivity. Expand the detailed region and compare results before relying on
the approximation. All copper nets are retained in the explicit region.

The planar material arrangement is snapped at 0.1 µm to remove numerical
zero-width overlay slivers. Gmsh triangulates the arrangement; shared nodes are
swept through the exact saved layer heights into linear prisms. Holes remain
void and plated barrels remain hollow. Material interfaces share node indices.
The final mesh is in metres; Elmer performs no additional scale conversion.
Saved soldermask openings come from KiCad's mask-layer polygon conversion,
including saved margins, tented vias and mask graphics. They are distinct from
the copper pad polygons used for solder contacts. The package template currently
supports front-side resistor bodies and through plated barrels; backside sources
and blind/buried vias are rejected explicitly.
`thermal-surface.stl` represents the actual meshed surface. The original
`board.step` preserves KiCad geometry for CAD inspection.

The optional `mesh.merge_identical_dielectric_plies: true` removes internal
mesh planes only between adjacent dielectric subplies with the same saved
layer name. They already use the same assumed FR4 material. Copper, mask and
distinct dielectric-layer boundaries stay explicit; the extracted stackup is
preserved verbatim. The default is false. This is numerical coarsening and must
be compared with the full-ply mesh before acceptance. `physical-groups.json`
records every removed plane and the resulting through-thickness levels.

Only real exposed surfaces receive convection. Artificial crop cuts are
insulated. A crop must enclose each selected source and must not cut a drilled
hole. Rejecting an invalid crop prevents silently discarding a heat path.

Elmer's `Heat Source` is power per unit mass. Each heater receives
`watts / (density × meshed volume)`; source normalization and heat conservation
are checked independently. Solver temperatures use kelvin; reports and images
use Celsius. The native scalar columns remain alongside derived CSV.
`ThermalScalars` compiles Elmer's native SaveScalars with a narrow correction:
an empty MPI partition contributes a neutral value to minimum/maximum reduction.
Otherwise a resistor entirely on one rank can incorrectly report a 0 K minimum.
The full patched upstream source, its license header and source hashes are
retained under `solve/native/`; all other native scalar behavior is preserved.

Transient timesteps must divide the phase duration, on/off durations and field
interval. The load uses the phase immediately before each step endpoint, so
the first 1,800 seconds include exactly 1,800 seconds of balancing. No cell
depletion, diagnostic pauses, thermal shutdown feedback or other heat sources
are included in this operating assumption.

For local debugging only, `PCB_THERMAL_ENGINE=native` uses installed host tools
and the Elmer build under `.cache/native/elmer`. Native versions are identified
separately from container versions. Reproducible deployment uses the pinned
container images and exported inventories.

## Mechanical STEP contacts

Separate mechanical inputs are optional and are absent from the BMS study.
The current conformal mesher supports a single straight-sided vertical prism
per STEP, with translation and rotation around Z. Its flat contact footprint
must fit entirely on uninterrupted top soldermask, outside resistor bodies and
pad openings. Curved parts, sloped walls, overlapping parts and unsupported
contact locations fail explicitly. A general curved heatsink/enclosure requires
an extension to the geometry/contact mesher; it is not approximated silently.

```json
{
  "mechanicals": [
    {
      "name": "cooling_block",
      "step": "mechanics/block.step",
      "material": "aluminium",
      "translate_mm": [
        0,
        0,
        0.135
      ],
      "rotate_z_deg": 0,
      "contact": {
        "kind": "layer",
        "thickness_mm": 0.1,
        "material": "thermal_pad"
      }
    }
  ]
}
```

The STEP path is relative to `project_root`. Define `aluminium` and
`thermal_pad` in `materials` with editable conductivity, density and heat
capacity values before using this example.

A `perfect` contact has no additional layer. A `layer` contact models finite
thermal resistance and heat capacity through its actual thickness and material,
with shared interface nodes. For the BMS stack, top soldermask is z=0.035 mm;
the example placement assumes the mechanical STEP starts at its own z=0.
Original KiCad STEP and mechanical inputs remain separate. Canonical exports
`pcb-thermal-coordinates.step`, `copper-thermal-coordinates.step` and
`resistors-thermal-coordinates.step` use saved KiCad XY and front-copper z=0.
`step-audit.json` records the transform, outline/thickness checks and any
packages whose named CAD centre could not be verified.

## Long transient runs

For fixed materials, mesh, timestep and convection, `ScheduledHeat` reuses
Elmer HeatSolver's bulk stiffness/mass matrices and updates the integrated
odd/even source vectors at every phase boundary and cooldown. `FastAudit`
caches exact linear-element quadrature weights for scalar histories. Native
SaveScalars independently checks the final row. These are lab-supplied Elmer
modules compiled against the selected solver; source and hashes are retained.
Set `numerics.cache_bulk: false` and `numerics.fast_audit: false` to execute the
standard Elmer reference path. Edited nonlinear/moving-mesh SIFs must disable
these optimizations. The layered-via verification compares both paths.

Fields remain native VTU/PVTU with a PVD time collection. A watcher losslessly
compresses completed VTU files and verifies all field, geometry and connectivity
arrays before atomic replacement; hashes and byte counts are recorded in
`field-compression.json`. Scalars remain available every timestep. Solver
runtime and sampled peak process-tree memory appear in `resources.json`.

`outputs.line_mm` optionally supplies two `[x,y,z]` endpoints for native
SaveLine output; coordinates use the thermal frame in millimetres and are
converted once. `outputs.line_divisions` defaults to 200. `outputs.render`
defaults to true. The rendered report also includes sampled PCB temperatures
beneath footprint centres and pads in `nearby-board-temperatures.csv`; open
drills or locations outside the modeled domain remain invalid/blank. These
samples refer to PCB material at the selected field time, not component or
junction temperatures.

An explicit `--sif` is captured before replacing the solve stage, including
when it comes from that run's previous GUI folder. The GUI's local mesh path
is normalized to the scripted `mesh/` directory; the supplied text is retained
as `case.override.sif`. Keep native scalar/output definitions if derived
reports are required. Changed physical assumptions must also be reflected in
the case file so heat accounting remains meaningful. Failed stage directories
are retained under `failed-attempts/` for diagnosis.

## CPU solver and memory budget

`execution.cpu_solver: hypre` is the default MPI-capable iterative solver.
`execution.cpu_solver: cholmod` selects a single-rank sparse Cholesky solver;
set `execution.mpi_ranks: 1`. It can reuse its factorization for the fixed-step
linear transient, but its memory requirement depends strongly on mesh fill-in.
Use `execution.max_memory_gib` to stop the solver if sampled process-tree RSS
exceeds your budget. The measurement interval is 0.5 s, so a short allocation
can exceed the threshold before termination. Limits and termination status are
recorded in `solve/resources.json`; failed solves are never switched to another
backend. The GUI settings and native SIF reflect the selected solver.

### Resource limits

`execution.max_memory_gib` defaults to 8 GiB. Podman/Docker apply this to solver
and numerical-worker containers with no extra container swap; the process
monitor also retains 1.5 GiB of host available RAM and 2 GiB of disk space.
A pressure stop is a failed stage with retained logs, not a valid thermal result.
Only one pipeline runs per lab checkout. Schedule large native diagnostics and
GUI reopening separately on small-memory machines. The documented BMS baseline
used 7.19 GB peak solver RSS; refined domains may need more RAM.

## JSON migration verification, 2026-11-01

The layered-via example and board-specific case definitions were renamed to
`.json` without changing their bytes or physical values. Generated sweep and
study inputs also use JSON. Case parsing rejects YAML syntax and works without
site packages; all 33 unit tests pass. The standalone CPU example completes
extraction, meshing, conversion, solving, reporting and headless rendering.
The CUDA comparison on the same mesh has a maximum nodal temperature difference
of 1.46e-6 °C, below the 0.1 °C backend-agreement criterion. This does not extend
BMS physical-model validation or reopen its closed simulation scope.

The editable installation was refreshed offline using the existing environment.
Installed container images were reused; a full source rebuild was not repeated.
NVIDIA tooling accepts a temporary JSON device specification, and bootstrap
scripts now request JSON. Existing host GPU configuration, historical result
records and downloaded third-party source caches were left unchanged.

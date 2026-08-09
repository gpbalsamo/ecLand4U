# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

ecLand4U is a practical support layer around ECMWF's official ecLand land-surface model
(https://github.com/ecmwf-ifs/ecland). It is not the ecLand source itself — it holds
installation notes, workflows, diagnostics, and examples that help students, researchers,
and collaborators install, run, test, and analyse ecLand. The repo is currently
lightweight: mostly documentation plus one diagnostics script. `docs/`, `notebooks/`, and
`examples/` are placeholders (each contains only `.gitkeep`) reserved for future material.

Repository layout:
```
docs/        Documentation and user guides
notebooks/   Interactive examples and diagnostics
scripts/     Command-line utilities (currently: landgram.py)
examples/    Ready-to-run ecLand use cases
assets/      Images and visual material for the README and documentation
```

There is no build system, package manifest, or test suite in this repo — do not assume
a `pyproject.toml`/`requirements.txt`/CI config exists; check before referencing one.

## Building and testing ecLand itself (macOS)

ecLand4U documents the build; the actual ecLand build happens in a separate clone
(`~/Work/ecland` in the README's examples), not inside this repo. Key points from
`README.md`, in case you're asked to script or debug this workflow:

- Use a clean Python venv (avoid `conda base` / Homebrew's externally-managed Python),
  and `pip install fypp` (required by the `field_api` dependency).
- MPI must be configured explicitly before building:
  ```bash
  export MPI_HOME=$(brew --prefix open-mpi)
  export PATH="$MPI_HOME/bin:$PATH"
  export CC=mpicc CXX=mpicxx FC=mpifort
  export DR_HOOK_ASSERT_MPI_INITIALIZED=0
  ```
- Build via the bundle tooling: `./ecland-bundle create` then
  `./ecland-bundle build --cmake="Python3_EXECUTABLE=$(which python);FYPP=$(which fypp)"`.
- Install with `./build/install.sh --fast`.
- Test with `ctest -L ecland --output-on-failure` (run from `build/` after sourcing
  `env.sh`). Avoid plain `ctest` — it also runs tests for bundled deps (ecCodes, fiat,
  field_api).
- A debug build variant disables OpenMP/tests and adds `-g -O0 -fcheck=all -fbacktrace`
  Fortran flags — see the README's "Debug build" section for the full recipe.
- ecLand's namelist must have output writing enabled or `o_*.nc` files won't be produced
  for diagnostics.

## scripts/landgram.py

A standalone diagnostics tool that plots ecLand offline single-site/small-domain output
(`o_*.nc` files) into a 5-panel PNG/PDF/SVG figure: surface fractions, energy fluxes,
water fluxes, temperatures, and soil water/snow states.

Run it directly (needs `numpy`, `pandas`, `xarray`, `matplotlib` — no requirements file
is checked in, so install these manually):
```bash
python scripts/landgram.py --input "./o_*.nc" \
  --lat 42.5378 --lon -72.1715 --loc "Harvard Forest" --out landgram_HarvardForest.png
```
Useful flags: `--debug-vars` (print detected variables/dims and inferred alias mapping,
then exit — the fastest way to diagnose "no plottable variables found"), `--var
KEY=NAME` (override/add a variable alias), `--water {mmday,mmstep}`, `--box-deg` (average
over a lat/lon box instead of nearest-point).

Architecture, if modifying it:
- `ALIASES`: maps ecLand4U's internal variable keys (e.g. `"lh"`, `"swvl1"`) to the list
  of candidate NetCDF variable names to look for, across ecLand's own o_*.nc naming and
  common IFS/CF conventions. `find_var()` resolves a key to whatever name is actually
  present in the dataset (case-insensitive fallback). Add new variables here first.
- `open_dataset()` merges the five ecLand output file groups (o_efl, o_wat, o_gg, o_cld,
  o_sus, o_fix) with an outer join rather than `open_mfdataset`, because `o_fix` has no
  time dimension and file groups can start at different times — a plain multi-file open
  is fragile for this data.
- `extract_point_or_box()` selects a site or averages a lat/lon box while deliberately
  *not* squeezing the `time` dimension, since a single-timestep diagnostic file would
  otherwise look like a static scalar and get dropped from the plots.
- `collect_series()` is the per-variable pipeline: look up the alias, convert to a pandas
  Series via `as_series()`, then apply a unit conversion depending on the variable class
  — `energy_wm2` (J m-2 accumulated → W m-2 via time-step differencing), `water_to_display`
  (rate/accumulation → mm/day or mm/step, with sign normalization for evap/runoff since
  ecLand uses a mathematical sign convention), `state_water` (soil moisture kg m-2 →
  volumetric % using layer thickness from `o_fix`), or `temp_c` (K → °C).
- `plot_landgram()` lays out the fixed 5-panel figure; `set_water_ylim_from_precip()`
  scales the water panel's y-axis from precipitation alone so runoff/evaporation spikes
  don't compress the rain/snow signal — this is a deliberate, non-obvious design choice
  (see `--water-ymax`/`--water-ymax-factor`/`--water-negative-frac` to adjust it).

There is no test suite for this script — validate changes by running it against real
`o_*.nc` output (or with `--debug-vars` against a sample file) and inspecting the figure.

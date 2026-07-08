#!/usr/bin/env python3
"""
landgram_ecLand_offline.py

Python Landgram for ecLand offline single-site or small-domain NetCDF outputs
named o_*.nc.

This version is adapted to the current ecLand offline files shown by ncdump:
  o_efl : SWnet, LWnet, Qle, Qh, Qg, Qf, SWdown, LWdown, LWup
  o_wat : Rainf, Snowf, Evap, Qs, Qsb, Qsm, Intercept, fldfrc
  o_gg  : AvgSurfT, SWE, SnowT, SoilMoist(time,nlevs,...), SoilTemp(time,nlevs,...)
  o_cld : SnowFrac, IceFrac, SnowDepth, Fdepth, Tdepth
  o_sus : VegT, BaresoilT, RadT, Albedo, lai, z0m
  o_fix : SoilThick, SoilFC, SoilWilt, SoilSat, RootDist

Example:
  python landgram_ecLand_offline.py --input '/path/to/run/o_*.nc' \
      --lat 42.5378 --lon -72.1715 --loc HarvardForest --out landgram.png

For single-site files (lat=1, lon=1), --lat/--lon are used only for the title
and nearest selection is harmless.
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

SCRIPT_VERSION = "2026-06-11-v4-water-yaxis-precip"

# -----------------------------------------------------------------------------
# Variable aliases for ecLand offline o_*.nc files, plus common IFS/ecLand names.
# -----------------------------------------------------------------------------
ALIASES: Dict[str, List[str]] = {
    # Surface fractions / indices
    "snowfrac": ["SnowFrac", "snowfrac", "snow_cover_fraction"],
    "icefrac": ["IceFrac", "icefrac"],
    "fldfrc": ["fldfrc", "flooded_area_fraction"],
    "albedo": ["Albedo", "albedo", "SAlbedo"],
    "lai": ["lai", "LAI"],

    # Energy fluxes
    "sw_net": ["SWnet", "ssr", "SSR", "surface_net_solar_radiation", "sw_net"],
    "lw_net": ["LWnet", "str", "STR", "surface_net_thermal_radiation", "lw_net"],
    "lh": ["Qle", "slhf", "SLHF", "latent_heat_flux", "LE"],
    "sh": ["Qh", "sshf", "SSHF", "sensible_heat_flux", "H"],
    "gflux": ["Qg", "soil_heat_flux"],
    "fflux": ["Qf", "soil_fusion_heat_flux"],
    "sw_down": ["SWdown", "SWdown_orig"],
    "lw_down": ["LWdown", "LWdown_orig"],
    "lw_up": ["LWup"],

    # Water fluxes
    "rain": ["Rainf", "rainf", "rain", "liquid_precip"],
    "snow": ["Snowf", "snowf", "snow", "snowfall"],
    "evap": ["Evap", "evap", "e", "E"],
    "qs": ["Qs", "surface_runoff", "sro"],
    "qsb": ["Qsb", "subsurface_runoff", "ssro"],
    "runoff": ["Runoff", "runoff", "ro", "RO"],
    "snowmelt": ["Qsm", "snowmelt"],
    "intercept": ["Intercept"],

    # Temperatures
    "skt": ["AvgSurfT", "skt", "SKT", "skin_temperature"],
    "radt": ["RadT", "radiative_temperature"],
    "vegt": ["VegT", "vegetation_temperature"],
    "bare": ["BaresoilT", "bare_soil_temperature"],
    "snowt": ["SnowT", "snow_temperature"],
    "t2m": ["t2m", "2t", "Tair", "screen_temperature"],
    "stl1": ["SoilTemp", "stl1", "STL1"],
    "stl2": ["SoilTemp", "stl2", "STL2"],
    "stl3": ["SoilTemp", "stl3", "STL3"],
    "stl4": ["SoilTemp", "stl4", "STL4"],

    # Water/snow states
    "swe": ["SWE", "swe", "sd", "snow_water_equivalent"],
    "snowdepth": ["SnowDepth", "snow_depth", "snd"],
    "canopint": ["CanopInt", "canopy_interception_depth"],
    "fdepth": ["Fdepth"],
    "tdepth": ["Tdepth"],
    "swvl1": ["SoilMoist", "swvl1", "SWVL1"],
    "swvl2": ["SoilMoist", "swvl2", "SWVL2"],
    "swvl3": ["SoilMoist", "swvl3", "SWVL3"],
    "swvl4": ["SoilMoist", "swvl4", "SWVL4"],

    # Static fields
    "soilthick": ["SoilThick"],
    "soilfc": ["SoilFC"],
    "soilwilt": ["SoilWilt"],
    "soilsat": ["SoilSat"],
    "rootdist": ["RootDist"],
}

LEVEL_INDEX = {
    "stl1": 0, "stl2": 1, "stl3": 2, "stl4": 3,
    "swvl1": 0, "swvl2": 1, "swvl3": 2, "swvl4": 3,
}
SOIL_LABEL = {
    "stl1": "Soil T L1", "stl2": "Soil T L2", "stl3": "Soil T L3", "stl4": "Soil T L4",
    "swvl1": "Soil water L1", "swvl2": "Soil water L2", "swvl3": "Soil water L3", "swvl4": "Soil water L4",
}
SOIL_DEPTHS = [0.07, 0.28, 1.00, 2.89]  # cumulative bottom depths in m; used only in labels if SoilThick absent

@dataclass
class Series:
    key: str
    label: str
    data: pd.Series
    units: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--input", required=True, nargs="+", help="Glob(s) or files, e.g. '/run/o_*.nc'. Quote globs.")
    p.add_argument("--lat", type=float, default=None, help="Target latitude. Optional for single-site files.")
    p.add_argument("--lon", type=float, default=None, help="Target longitude. Optional for single-site files.")
    p.add_argument("--loc", default="ecLand site", help="Location label in the title.")
    p.add_argument("--out", default="landgram.png", help="Output figure path: png/pdf/svg.")
    p.add_argument("--box-deg", type=float, default=0.0, help="Average +/- this many degrees around lat/lon. 0 = nearest point.")
    p.add_argument("--var", action="append", default=[], metavar="KEY=NAME", help="Override/add variable name, e.g. --var rain=Rainf")
    p.add_argument("--water", choices=["mmday", "mmstep"], default="mmday", help="Display water rates as mm/day or interval mm/step.")
    p.add_argument("--water-ymax", choices=["auto", "precip"], default="precip",
                   help="Water-panel y-axis scaling. 'precip' uses max(Rain,Snow) rather than runoff/evap extremes.")
    p.add_argument("--water-ymax-factor", type=float, default=1.15,
                   help="Multiplier applied to max precipitation when --water-ymax=precip.")
    p.add_argument("--water-negative-frac", type=float, default=0.25,
                   help="Negative lower-limit fraction of precipitation max, useful for negative evaporation.")
    p.add_argument("--energy-sign", choices=["native", "flip"], default="native", help="Flip signs of energy fluxes if desired.")
    p.add_argument("--include-extra-energy", action="store_true", help="Also plot Qg/Qf in the energy panel if available.")
    p.add_argument("--max-points", type=int, default=0, help="Decimate plotted time series to at most this many points.")
    p.add_argument("--dpi", type=int, default=160, help="PNG resolution.")
    p.add_argument("--debug-vars", action="store_true", help="Print variables and inferred mappings, then exit.")
    return p.parse_args()


def expand_inputs(patterns: Sequence[str]) -> List[str]:
    files: List[str] = []
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if hits:
            files.extend(hits)
        elif os.path.exists(pat):
            files.append(pat)
    files = sorted(dict.fromkeys(files))
    if not files:
        raise FileNotFoundError(f"No files matched {patterns}")
    return files


def open_dataset(files: List[str]) -> xr.Dataset:
    """Open heterogeneous o_*.nc files and merge variables by shared coordinates.

    open_mfdataset can be fragile for ecLand offline outputs because o_fix has no
    time dimension and o_gg may include the initial state whereas flux files start
    later. Opening each file and merging with an outer join is more robust.
    """
    datasets = []
    for f in files:
        ds = xr.open_dataset(f, decode_times=True, mask_and_scale=True)
        # Drop duplicated coordinate variables that can otherwise trigger strict
        # compatibility errors. Values are identical for single-site runs.
        datasets.append(ds)
    try:
        return xr.merge(datasets, join="outer", compat="override", combine_attrs="drop_conflicts")
    except Exception as exc:
        print(f"xr.merge failed ({exc}); trying open_mfdataset fallback", file=sys.stderr)
        return xr.open_mfdataset(files, combine="by_coords", parallel=False, decode_times=True)


def apply_var_overrides(aliases: Dict[str, List[str]], overrides: Sequence[str]) -> Dict[str, List[str]]:
    out = {k: list(v) for k, v in aliases.items()}
    for item in overrides:
        if "=" not in item:
            raise ValueError(f"Bad --var override {item!r}; expected KEY=NAME")
        key, name = [x.strip() for x in item.split("=", 1)]
        out.setdefault(key, [])
        out[key] = [name] + [x for x in out[key] if x != name]
    return out


def find_var(ds: xr.Dataset, aliases: Dict[str, List[str]], key: str) -> Optional[str]:
    names = set(ds.data_vars) | set(ds.coords)
    for name in aliases.get(key, []):
        if name in names:
            return name
    lower = {n.lower(): n for n in names}
    for name in aliases.get(key, []):
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def lat_lon_names(ds: xr.Dataset) -> Tuple[Optional[str], Optional[str]]:
    names = list(ds.coords) + list(ds.dims)
    lower = {n.lower(): n for n in names}
    lat = lower.get("lat") or lower.get("latitude")
    lon = lower.get("lon") or lower.get("longitude")
    return lat, lon


def normalize_lon(lon: float, lon_values: xr.DataArray) -> float:
    vals = np.asarray(lon_values.values, dtype=float)
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return lon
    if np.nanmin(finite) >= 0 and lon < 0:
        return lon % 360.0
    if np.nanmax(finite) <= 180 and lon > 180:
        return ((lon + 180.0) % 360.0) - 180.0
    return lon


def _squeeze_only(ds: xr.Dataset, dims: Sequence[str]) -> xr.Dataset:
    """Squeeze selected singleton dimensions, but never squeeze time or levels."""
    squeeze_dims = [d for d in dims if d in ds.dims and ds.sizes.get(d, 0) == 1]
    if squeeze_dims:
        return ds.squeeze(dim=squeeze_dims, drop=True)
    return ds


def extract_point_or_box(ds: xr.Dataset, lat: Optional[float], lon: Optional[float], box_deg: float) -> xr.Dataset:
    """Select a site/box while preserving singleton time dimensions.

    Earlier versions used ``ds.squeeze(drop=True)``, which also removed
    ``time`` when a diagnostic file contained a single time step.  That made
    valid variables such as SnowFrac, SWnet, Rainf, and SoilTemp look like
    static scalars and they were not plotted.
    """
    lat_name, lon_name = lat_lon_names(ds)
    spatial_dims = [d for d in [lat_name, lon_name] if d]
    if lat_name is None or lon_name is None or lat is None or lon is None:
        return _squeeze_only(ds, spatial_dims)
    lon2 = normalize_lon(lon, ds[lon_name])
    if box_deg > 0 and lat_name in ds.dims and lon_name in ds.dims:
        latvals = ds[lat_name]
        lat_slice = slice(lat + box_deg, lat - box_deg) if latvals[0] > latvals[-1] else slice(lat - box_deg, lat + box_deg)
        sub = ds.sel({lat_name: lat_slice, lon_name: slice(lon2 - box_deg, lon2 + box_deg)})
        dims = [d for d in [lat_name, lon_name] if d in sub.dims]
        return sub.mean(dim=dims, skipna=True)
    if ds[lat_name].ndim == 1 and ds[lon_name].ndim == 1 and lat_name in ds.dims and lon_name in ds.dims:
        sub = ds.sel({lat_name: lat, lon_name: lon2}, method="nearest")
        return _squeeze_only(sub, spatial_dims)
    return _squeeze_only(ds, spatial_dims)


def time_name(da: xr.DataArray) -> Optional[str]:
    for d in da.dims:
        if d in da.coords and np.issubdtype(da[d].dtype, np.datetime64):
            return d
    for cand in ["time", "valid_time", "date"]:
        if cand in da.dims:
            return cand
    return None


def select_level(da: xr.DataArray, key: str) -> xr.DataArray:
    if key not in LEVEL_INDEX:
        return da
    idx = LEVEL_INDEX[key]
    for d in ["nlevs", "soil_layer", "level", "lev"]:
        if d in da.dims:
            if da.sizes[d] > idx:
                return da.isel({d: idx})
    return da


def as_series(ds: xr.Dataset, varname: str, key: str) -> pd.Series:
    da = select_level(ds[varname], key).squeeze(drop=True)
    tn = time_name(da)
    other = [d for d in da.dims if d != tn]
    if other:
        da = da.mean(dim=other, skipna=True)
    if tn is None:
        arr = np.asarray(da.values).astype(float).ravel()
        arr = arr[np.isfinite(arr)]
        val = float(arr[0]) if arr.size else np.nan
        return pd.Series([val], index=pd.Index([0], name="index"), dtype=float)
    s = da.to_series().astype(float)
    if isinstance(s.index, pd.MultiIndex):
        # Should not happen after averaging, but keep robust.
        s = s.groupby(level=tn).mean()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    # Convert CFTimeIndex/object datetimes to a DatetimeIndex when possible so
    # matplotlib and the interval conversions behave cleanly.
    if not isinstance(s.index, pd.DatetimeIndex):
        try:
            s.index = pd.to_datetime(np.asarray(s.index))
        except Exception:
            pass
    return s.replace([np.inf, -np.inf], np.nan)


def seconds_between_steps(index: pd.Index) -> pd.Series:
    """Return representative seconds per time step without mutating pandas views."""
    if isinstance(index, pd.DatetimeIndex):
        vals = index.to_series().diff().dt.total_seconds().to_numpy(dtype=float)
        if len(vals) > 1 and np.isfinite(vals[1]):
            vals[0] = vals[1]
        med = np.nanmedian(vals) if np.isfinite(vals).any() else 3600.0
        vals = np.where(np.isfinite(vals), vals, med)
        return pd.Series(vals, index=index)
    # CFTimeIndex and object datetime indexes are handled here.
    try:
        t = pd.to_datetime(np.asarray(index))
        vals = pd.Series(t, index=index).diff().dt.total_seconds().to_numpy(dtype=float)
        if len(vals) > 1 and np.isfinite(vals[1]):
            vals[0] = vals[1]
        med = np.nanmedian(vals) if np.isfinite(vals).any() else 3600.0
        vals = np.where(np.isfinite(vals), vals, med)
        return pd.Series(vals, index=index)
    except Exception:
        vals0 = pd.Series(np.arange(len(index), dtype=float), index=index)
        vals = vals0.diff().to_numpy(dtype=float)
        if len(vals) > 1 and np.isfinite(vals[1]):
            vals[0] = vals[1]
        med = np.nanmedian(vals) if np.isfinite(vals).any() else 1.0
        vals = np.where(np.isfinite(vals), vals, med)
        return pd.Series(vals * 3600.0, index=index)


def temp_c(s: pd.Series, units: str) -> Tuple[pd.Series, str]:
    med = np.nanmedian(s.values) if len(s) else np.nan
    if "k" in (units or "").lower() or med > 150:
        return s - 273.15, "°C"
    return s, units or "°C"


def energy_wm2(s: pd.Series, units: str, flip: bool) -> Tuple[pd.Series, str]:
    x = s.copy()
    u = (units or "").lower()
    if "j" in u and "m" in u and len(x) > 1:
        dt = seconds_between_steps(x.index)
        x = (x.diff() / dt.values).iloc[1:]
    if flip:
        x = -x
    return x, "W m$^{-2}$"


def water_to_display(s: pd.Series, units: str, mode: str, key: str) -> Tuple[pd.Series, str]:
    x = s.copy()
    u = (units or "").lower().replace(" ", "")
    is_rate = "s-1" in u or "/s" in u or "s*1" in u
    if is_rate:
        if mode == "mmstep":
            x = x * seconds_between_steps(x.index).values
            unit = "mm step$^{-1}$"
        else:
            x = x * 86400.0
            unit = "mm day$^{-1}$"
    elif "kgm-2" in u or "kg/m2" in u:
        unit = "mm"
    elif "m" in u and "m3" not in u and "mm" not in u:
        x = x * 1000.0
        unit = "mm"
    else:
        unit = units or ""
    # ecLand file uses mathematical convention; evaporation and Qsb can be negative.
    if key in {"evap", "qsb", "runoff"}:
        finite = x.dropna()
        if len(finite) and np.nanmedian(finite.values) < 0:
            x = -x
    return x, unit


def state_water(s: pd.Series, units: str, key: str, soil_thick: Optional[float]) -> Tuple[pd.Series, str]:
    x = s.copy()
    u = (units or "").lower().replace(" ", "")
    if key.startswith("swvl"):
        # SoilMoist in your files is kg m-2 per layer. Convert to volumetric
        # soil water (%) if layer thickness is known; otherwise keep mm.
        if "kgm-2" in u or "kg/m2" in u:
            if soil_thick and soil_thick > 0:
                return (x / (1000.0 * soil_thick)) * 100.0, "% vol"
            return x, "mm"
        if "m3m-3" in u or np.nanmedian(np.abs(x.values)) < 2:
            return x * 100.0, "% vol"
    if key == "swe":
        if "kgm-2" in u or "kg/m2" in u:
            return x, "mm SWE"
        if "m" in u and "mm" not in u:
            return x * 1000.0, "mm SWE"
    if key == "snowdepth":
        if "m" in u and "mm" not in u:
            return x * 100.0, "cm"
    if key in {"canopint"} and ("kgm-2" in u or "kg/m2" in u):
        return x, "mm"
    return x, units or ""


def decimate(s: pd.Series, max_points: int) -> pd.Series:
    if max_points and len(s) > max_points:
        return s.iloc[:: int(math.ceil(len(s) / max_points))]
    return s


def static_level_values(ds: xr.Dataset, aliases: Dict[str, List[str]], key: str) -> Optional[np.ndarray]:
    name = find_var(ds, aliases, key)
    if not name:
        return None
    da = ds[name].squeeze(drop=True)
    tn = time_name(da)
    dims = [d for d in da.dims if d != tn]
    # Preserve nlevs, average any accidental spatial dims.
    avg_dims = [d for d in dims if d != "nlevs"]
    if avg_dims:
        da = da.mean(dim=avg_dims, skipna=True)
    arr = np.asarray(da.values, dtype=float).ravel()
    return arr[np.isfinite(arr)]


def collect_series(ds: xr.Dataset, aliases: Dict[str, List[str]], args: argparse.Namespace) -> Tuple[Dict[str, Series], Dict[str, str]]:
    found = {k: v for k in aliases if (v := find_var(ds, aliases, k))}
    out: Dict[str, Series] = {}
    soil_thick = static_level_values(ds, aliases, "soilthick")

    def add(key: str, label: str, conv: str) -> None:
        if key not in found:
            return
        name = found[key]
        da = ds[name]
        units = da.attrs.get("units", "")
        s = as_series(ds, name, key)
        # Keep single-time-step diagnostics if they have a real time coordinate.
        # Drop only genuinely static scalar fields from the plotted time panels.
        if len(s) <= 1 and not isinstance(s.index, pd.DatetimeIndex):
            return
        if conv == "frac":
            vals = np.asarray(s.values, dtype=float)
            if np.all(~np.isfinite(vals)):
                x = s
            else:
                x = s * 100.0 if np.nanmax(np.abs(vals)) <= 1.5 else s
            unit = "%"
        elif conv == "raw":
            x, unit = s, units or ""
        elif conv == "temp":
            x, unit = temp_c(s, units)
        elif conv == "energy":
            x, unit = energy_wm2(s, units, args.energy_sign == "flip")
        elif conv == "water":
            x, unit = water_to_display(s, units, args.water, key)
        elif conv == "statewater":
            thick = None
            if key in LEVEL_INDEX and soil_thick is not None and len(soil_thick) > LEVEL_INDEX[key]:
                thick = float(soil_thick[LEVEL_INDEX[key]])
            x, unit = state_water(s, units, key, thick)
        else:
            x, unit = s, units or ""
        out[key] = Series(key, label, decimate(x, args.max_points), unit)

    # Surface fractions/indices
    add("snowfrac", "Snow fraction", "frac")
    add("icefrac", "Ice fraction", "frac")
    add("fldfrc", "Flood fraction", "frac")
    add("albedo", "Albedo", "frac")
    # LAI has different units and scale; plot it in same panel only if few fraction vars are absent.
    add("lai", "LAI", "raw")

    # Energy
    for key, label in [("sw_net", "SWnet"), ("lw_net", "LWnet"), ("lh", "Latent heat"), ("sh", "Sensible heat")]:
        add(key, label, "energy")
    if args.include_extra_energy:
        add("gflux", "Ground heat", "energy")
        add("fflux", "Fusion heat", "energy")

    # Water fluxes. Derive total runoff if possible.
    for key, label in [("rain", "Rain"), ("snow", "Snow"), ("evap", "Evaporation"), ("qs", "Surface runoff"), ("qsb", "Subsurface runoff"), ("snowmelt", "Snowmelt")]:
        add(key, label, "water")
    if "runoff" in found:
        add("runoff", "Runoff", "water")
    elif "qs" in out and "qsb" in out:
        # Qs and Qsb were already sign-normalised independently; this gives a readable total magnitude.
        joined = pd.concat([out["qs"].data, out["qsb"].data], axis=1).sum(axis=1, min_count=1)
        out["runoff"] = Series("runoff", "Total runoff", joined, out["qs"].units)

    # Temperatures
    for key, label in [("t2m", "T2m"), ("skt", "Skin T"), ("radt", "Radiative T"), ("vegt", "Vegetation T"), ("bare", "Bare soil T"), ("snowt", "Snow T")]:
        add(key, label, "temp")
    for key in ["stl1", "stl2", "stl3", "stl4"]:
        lab = SOIL_LABEL[key]
        if soil_thick is not None and len(soil_thick) > LEVEL_INDEX[key]:
            lab += f" ({soil_thick[LEVEL_INDEX[key]]:.2g} m)"
        add(key, lab, "temp")

    # Water/snow states
    for key, label in [("swe", "SWE"), ("snowdepth", "Snow depth"), ("canopint", "Canopy int."), ("fdepth", "Frozen depth"), ("tdepth", "Thaw depth")]:
        add(key, label, "statewater")
    for key in ["swvl1", "swvl2", "swvl3", "swvl4"]:
        lab = SOIL_LABEL[key]
        if soil_thick is not None and len(soil_thick) > LEVEL_INDEX[key]:
            lab += f" ({soil_thick[LEVEL_INDEX[key]]:.2g} m)"
        add(key, lab, "statewater")

    return out, found


def build_title(ds: xr.Dataset, aliases: Dict[str, List[str]], args: argparse.Namespace) -> str:
    lat_name, lon_name = lat_lon_names(ds)
    lat = args.lat
    lon = args.lon
    if lat is None and lat_name in ds:
        vals = np.asarray(ds[lat_name].values).ravel()
        if vals.size:
            lat = float(vals[0])
    if lon is None and lon_name in ds:
        vals = np.asarray(ds[lon_name].values).ravel()
        if vals.size:
            lon = float(vals[0])
    bits = [args.loc]
    if lat is not None and lon is not None:
        bits.append(f"lat={lat:.4f}, lon={lon:.4f}")
    soil_thick = static_level_values(ds, aliases, "soilthick")
    soilfc = static_level_values(ds, aliases, "soilfc")
    soilwilt = static_level_values(ds, aliases, "soilwilt")
    soilsat = static_level_values(ds, aliases, "soilsat")
    if soil_thick is not None and len(soil_thick):
        bits.append("soil layers " + "/".join(f"{v:g}" for v in soil_thick[:4]) + " m")
    if soilfc is not None and soilwilt is not None and soilsat is not None and len(soilfc):
        bits.append(f"FC/WP/Sat L1={soilfc[0]:.2f}/{soilwilt[0]:.2f}/{soilsat[0]:.2f}")
    return " | ".join(bits)


def setup_time_axis(ax, plotted: List[Series]) -> None:
    for ser in plotted:
        if isinstance(ser.data.index, pd.DatetimeIndex):
            loc = mdates.AutoDateLocator(minticks=4, maxticks=10)
            ax.xaxis.set_major_locator(loc)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
            ax.set_xlabel("Time")
            return
    ax.set_xlabel("Time index")


def plot_panel(ax, series: Dict[str, Series], keys: List[str], title: str, ylabel: Optional[str] = None) -> List[Series]:
    present = [series[k] for k in keys if k in series]
    if not present:
        ax.text(0.5, 0.5, f"No variables found for {title}", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, loc="left", fontsize=10)
        ax.grid(True, alpha=0.3)
        return []
    for ser in present:
        marker = "o" if len(ser.data) == 1 else None
        ax.plot(ser.data.index, ser.data.values, label=ser.label, linewidth=1.5, marker=marker, markersize=3)
    unit = ylabel or next((s.units for s in present if s.units), "")
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_ylabel(unit)
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=min(4, len(present)), fontsize=8, loc="best")
    return present


def set_water_ylim_from_precip(ax, series: Dict[str, Series], args: argparse.Namespace) -> None:
    """Scale the water-flux y-axis from precipitation only.

    This prevents large runoff/evaporation excursions from compressing the
    precipitation signal. Rainf and Snowf have already been converted to the
    plotted units (mm/day or mm/step) in collect_series().
    """
    if args.water_ymax != "precip":
        return

    precip_max = 0.0
    for key in ("rain", "snow"):
        if key not in series:
            continue
        vals = np.asarray(series[key].data.values, dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size:
            precip_max = max(precip_max, float(np.nanmax(vals)))

    if precip_max <= 0.0 or not np.isfinite(precip_max):
        return

    lower = -max(0.0, args.water_negative_frac) * precip_max
    upper = max(args.water_ymax_factor, 1.0) * precip_max
    ax.set_ylim(lower, upper)

    # Add a small note inside the panel so the scaling choice is explicit.
    ax.text(
        0.995, 0.02,
        f"y max from precip: {precip_max:.3g}",
        ha="right", va="bottom", transform=ax.transAxes, fontsize=7, alpha=0.7,
    )


def plot_landgram(series: Dict[str, Series], title: str, args: argparse.Namespace) -> None:
    fig, axes = plt.subplots(5, 1, figsize=(12, 14), sharex=True, constrained_layout=True)
    fig.suptitle(title, fontsize=11)
    plotted: List[Series] = []
    plotted += plot_panel(axes[0], series, ["snowfrac", "icefrac", "fldfrc", "albedo"], "Surface fractions", "%")
    plotted += plot_panel(axes[1], series, ["sw_net", "lw_net", "lh", "sh", "gflux", "fflux"], "Energy fluxes", "W m$^{-2}$")
    plotted += plot_panel(axes[2], series, ["rain", "snow", "evap", "runoff", "qs", "qsb", "snowmelt"], "Water fluxes")
    set_water_ylim_from_precip(axes[2], series, args)
    plotted += plot_panel(axes[3], series, ["skt", "radt", "vegt", "bare", "snowt", "t2m", "stl1", "stl2", "stl3", "stl4"], "Temperatures", "°C")
    plotted += plot_panel(axes[4], series, ["swe", "snowdepth", "canopint", "swvl1", "swvl2", "swvl3", "swvl4", "fdepth", "tdepth"], "Soil water and snow")
    setup_time_axis(axes[-1], plotted)
    fig.text(0.01, 0.004, "Python Landgram for ecLand offline o_*.nc: surface fractions, energy, water, temperature, soil/snow states.", fontsize=8)
    fig.savefig(args.out, dpi=args.dpi)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    files = expand_inputs(args.input)
    aliases = apply_var_overrides(ALIASES, args.var)
    print(f"landgram_ecLand_offline.py version: {SCRIPT_VERSION}")
    print(f"Reading {len(files)} file(s). First: {files[0]}")
    ds0 = open_dataset(files)

    if args.debug_vars:
        print("Dimensions:")
        print(ds0.dims)
        print("\nVariables:")
        for name, da in ds0.data_vars.items():
            print(f"  {name:22s} dims={da.dims} units={da.attrs.get('units','')}")
        print("\nInferred mapping:")
        for k in sorted(aliases):
            v = find_var(ds0, aliases, k)
            if v:
                print(f"  {k:12s} <- {v}")
        return 0

    ds = extract_point_or_box(ds0, args.lat, args.lon, args.box_deg)
    series, found = collect_series(ds, aliases, args)
    if not series:
        print("No plottable variables found. Try --debug-vars and --var KEY=NAME overrides.", file=sys.stderr)
        return 2

    print("Variable mapping used:")
    for k in sorted(found):
        if k in series or k in {"soilthick", "soilfc", "soilwilt", "soilsat", "rootdist"}:
            print(f"  {k:12s} <- {found[k]}")

    title = build_title(ds, aliases, args)
    if args.box_deg > 0:
        title += f" | box mean +/- {args.box_deg:g}°"
    plot_landgram(series, title, args)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

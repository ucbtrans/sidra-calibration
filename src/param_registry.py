"""
param_registry.py  -  Registry of all seven calibration input parameters.

Each entry defines:
  label         - human-readable name
  type          - "continuous" or "categorical"
  applies_to    - model keys this parameter is valid for
  default_range - (p_min, p_max) for continuous parameters
  default_steps - n_steps for continuous parameters
  values        - ordered list for categorical parameters
  value_labels  - display labels for categorical values
  setter        - function(sid, site, model_code, value) -> None
  ready         - True if the SIDRA API property name is confirmed

Parameters marked ready=False raise NotImplementedError until the API
property name is confirmed by running the relevant probe script.
"""

# ---------------------------------------------------------------------------
# Setters  -  one function per parameter
# ---------------------------------------------------------------------------

def _set_fe(sid, site, model_code, value):
    """Environment Factor - applies to SIDRA Standard US (model_code=0)."""
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        try:
            leg.Leg_roundabout.Environment_factor = float(value)
        except Exception:
            pass


def _set_cf(sid, site, model_code, value):
    """Model Calibration Factor - applies to HCM 2010 (code=1) and HCM 6 (code=2)."""
    for leg_idx in range(8):
        leg = sid._get_leg(site, leg_idx)
        if leg is None:
            continue
        rleg = leg.Leg_roundabout
        try:
            if model_code == 1:
                rleg.LegRouHCM2010.Model_calib_factor = float(value)
            elif model_code == 2:
                rleg.LegRouHCM6.Model_calib_factor    = float(value)
        except Exception:
            pass


def _set_ec_flow_adjustment(sid, site, model_code, value):
    """
    Entry-Circulating Flow Adjustment  (0=None, 1=Low, 2=Medium, 3=High).

    API property name not yet confirmed. Run probe_modelsetting.py to find it,
    then replace the raise below with the correct setter call.
    Expected location: site.ModelSetting or rleg (roundabout leg setting).
    """
    raise NotImplementedError(
        "EC Flow Adjustment: SIDRA API property name not yet confirmed.\n"
        "Run probe_modelsetting.py, look for a property like "
        "'Rou_EC_adjust', 'EntCirc_adjust', or similar.\n"
        "Then update _set_ec_flow_adjustment() in param_registry.py."
    )


def _set_gap_acceptance_factor(sid, site, model_code, value):
    """
    Gap Acceptance Factor  -  adjusts tc by vehicle movement class.
    API property name not yet confirmed. Requires gap-acceptance field data.
    """
    raise NotImplementedError(
        "Gap Acceptance Factor: API property not yet confirmed. "
        "Requires video-based gap-acceptance field study and API probing."
    )


def _set_opposing_vehicle_factor(sid, site, model_code, value):
    """
    Opposing Vehicle Factor  -  adjusts capacity effect of circulating vehicle classes.
    API property name not yet confirmed. Requires classified TMC field data.
    """
    raise NotImplementedError(
        "Opposing Vehicle Factor: API property not yet confirmed. "
        "Requires classified turning movement count data and API probing."
    )


def _set_lane_utilization_ratio(sid, site, model_code, value):
    """
    Lane Utilization Ratio  -  accounts for unequal lane use at multi-lane entries.
    API property name not yet confirmed. Multi-lane sites only.
    """
    raise NotImplementedError(
        "Lane Utilization Ratio: API property not yet confirmed. "
        "Requires per-lane stop-line count data and API probing."
    )


def _set_extra_bunching_parameter(sid, site, model_code, value):
    """
    Extra Bunching Parameter  -  captures platooning from upstream signals.
    API property name not yet confirmed. Signal-adjacent sites only.
    """
    raise NotImplementedError(
        "Extra Bunching Parameter: API property not yet confirmed. "
        "Requires upstream signal timing data and API probing."
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
PARAM_REGISTRY = {
    "fe": {
        "label":         "Environment Factor (fe)",
        "type":          "continuous",
        "applies_to":    ["sidra_standard_us"],
        "default_range": (0.5, 2.0),
        "default_steps": 15,
        "setter":        _set_fe,
        "ready":         True,
    },
    "cf": {
        "label":         "Model Calibration Factor (cf)",
        "type":          "continuous",
        "applies_to":    ["hcm2010", "hcm6"],
        "default_range": (0.7, 1.3),
        "default_steps": 15,
        "setter":        _set_cf,
        "ready":         True,
    },
    "ec_flow_adjustment": {
        "label":         "Entry-Circulating Flow Adjustment",
        "type":          "categorical",
        "applies_to":    ["sidra_standard_us", "hcm2010", "hcm6"],
        "values":        [0, 1, 2, 3],
        "value_labels":  ["None", "Low", "Medium", "High"],
        "setter":        _set_ec_flow_adjustment,
        "ready":         False,
    },
    "gap_acceptance_factor": {
        "label":         "Gap Acceptance Factor",
        "type":          "continuous",
        "applies_to":    ["sidra_standard_us", "hcm2010", "hcm6"],
        "default_range": (0.8, 1.2),
        "default_steps": 10,
        "setter":        _set_gap_acceptance_factor,
        "ready":         False,
    },
    "opposing_vehicle_factor": {
        "label":         "Opposing Vehicle Factor",
        "type":          "continuous",
        "applies_to":    ["sidra_standard_us", "hcm2010", "hcm6"],
        "default_range": (0.8, 1.2),
        "default_steps": 10,
        "setter":        _set_opposing_vehicle_factor,
        "ready":         False,
    },
    "lane_utilization_ratio": {
        "label":         "Lane Utilization Ratio",
        "type":          "continuous",
        "applies_to":    ["sidra_standard_us", "hcm2010", "hcm6"],
        "default_range": (0.5, 1.0),
        "default_steps": 10,
        "setter":        _set_lane_utilization_ratio,
        "ready":         False,
    },
    "extra_bunching_parameter": {
        "label":         "Extra Bunching Parameter",
        "type":          "continuous",
        "applies_to":    ["sidra_standard_us", "hcm2010", "hcm6"],
        "default_range": (0.0, 1.0),
        "default_steps": 10,
        "setter":        _set_extra_bunching_parameter,
        "ready":         False,
    },
}


def get_param_values(param_name: str, user_cfg: dict) -> list:
    """
    Return the ordered list of values to sweep for a parameter.

    user_cfg is the per-parameter block from the YAML grid_search section.
    Falls back to registry defaults when user_cfg omits fields.
    """
    info = PARAM_REGISTRY[param_name]

    if info["type"] == "categorical":
        return list(user_cfg.get("values", info["values"]))

    lo   = float(user_cfg.get("p_min",   info["default_range"][0]))
    hi   = float(user_cfg.get("p_max",   info["default_range"][1]))
    n    = int(user_cfg.get("n_steps", info["default_steps"]))
    step = (hi - lo) / max(n - 1, 1)
    return [round(lo + i * step, 6) for i in range(n)]


def get_param_spec(param_name: str, user_cfg: dict) -> dict:
    """
    Build a genetic_search parameter spec for a parameter.

    Continuous  -> {"name", "type": "continuous", "lo", "hi"}
    Categorical -> {"name", "type": "categorical", "values": [...]}

    user_cfg is the per-parameter block from the YAML parameters list.
    Falls back to registry defaults when user_cfg omits fields.
    """
    info = PARAM_REGISTRY[param_name]

    if info["type"] == "categorical":
        return {
            "name":   param_name,
            "type":   "categorical",
            "values": list(user_cfg.get("values", info["values"])),
        }

    lo = float(user_cfg.get("p_min", info["default_range"][0]))
    hi = float(user_cfg.get("p_max", info["default_range"][1]))
    return {"name": param_name, "type": "continuous", "lo": lo, "hi": hi}


def validate_param(param_name: str, model_key: str) -> str:
    """
    Check that param_name exists, is ready, and applies to model_key.
    Returns an error string, or empty string if valid.
    """
    if param_name not in PARAM_REGISTRY:
        known = ", ".join(PARAM_REGISTRY)
        return f"Unknown parameter '{param_name}'. Known: {known}"

    info = PARAM_REGISTRY[param_name]
    if not info["ready"]:
        return (f"Parameter '{param_name}' is not yet implemented "
                f"(API property unconfirmed). See param_registry.py.")

    if model_key not in info["applies_to"]:
        return (f"Parameter '{param_name}' does not apply to model '{model_key}'. "
                f"Valid models: {info['applies_to']}")

    return ""

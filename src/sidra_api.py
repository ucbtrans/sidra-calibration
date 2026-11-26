"""
sidra_api.py
Wrapper around the SIDRA Intersection v10 Python API.

The SIDRA API uses Python.NET (pythonnet) to call the .NET DLL.
Install dependency:  pip install pythonnet

Key objects exposed by the API:
  SIAPI            – top-level API object (open/close projects)
  ISIAPIProject    – project (contains SiteFolders)
  ISIAPISite       – one intersection site
  ISIAPILeg        – one approach leg
  ISIAPILeg_roundabout – roundabout-specific leg geometry
  ISIAPIMovement_vehicle_od – origin-destination volume entry

Outputs read after site.Process():
  outputLane.Capacity       – entry lane capacity (veh/h)
  outputLane.Deg_satn       – degree of saturation (v/c)
  outputLane.Flow_total     – arrival flow (veh/h)
  outputLeg.Avg_delay       – average control delay (s/veh)
  outputLeg.Deg_satn        – leg-level degree of saturation
"""

import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap Python.NET runtime once at import time
# ---------------------------------------------------------------------------
_SIDRA_INSTALL = os.environ.get(
    "SIDRA_PATH", r"C:\Program Files\SIDRA SOLUTIONS\SIDRA INTERSECTION 10")

# US template .sipx shipped with the tool (templates/ in the repository).
# It holds one roundabout site configured as US HCM (Customary), right-hand
# traffic.  New sites are CLONED from that site so they inherit the US model,
# units and driving side.  Sites created with AddSite() get SIDRA's generic
# "Standard Right" model in metric units, and the API cannot change a site's
# units or driving side afterwards (both properties are read-only).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SIDRA_TEMPLATE_US = str(_REPO_ROOT / "templates" / "us_roundabout_template.sipx")

# Site.Units codes reported by the API
UNITS_METRIC    = 0
UNITS_CUSTOMARY = 1
FT_PER_M        = 3.28084

# Roundabout capacity model codes (site.ModelSetting.Rou_Capacity_Model)
MODEL_SIDRA_STANDARD = 0
MODEL_HCM2010        = 1
MODEL_HCM6           = 2
_RUNTIME_CONFIG = os.path.join(_SIDRA_INSTALL, "SIDRASolutions.SI.API.runtimeconfig.json")
_API_DLL        = os.path.join(_SIDRA_INSTALL, "SIDRASolutions.SI.API.dll")

try:
    from pythonnet import set_runtime
    from clr_loader import get_coreclr
    rt = get_coreclr(runtime_config=_RUNTIME_CONFIG)
    set_runtime(rt)
    import clr
    clr.AddReference(_API_DLL)
    from SIDRASolutions.SI.API import SIAPI
    _SIDRA_AVAILABLE = True
except Exception as _e:
    _SIDRA_AVAILABLE = False
    _SIDRA_LOAD_ERROR = str(_e)


# ---------------------------------------------------------------------------
# Leg orientation constants (same as SIDRA API)
# ---------------------------------------------------------------------------
LEG_SOUTH     = 0
LEG_SOUTHEAST = 1
LEG_EAST      = 2
LEG_NORTHEAST = 3
LEG_NORTH     = 4
LEG_NORTHWEST = 5
LEG_WEST      = 6
LEG_SOUTHWEST = 7

# Leg orientations for 3-, 4-, and 5-leg roundabouts
LEG_ORIENTATIONS = {
    3: [LEG_SOUTH, LEG_EAST,  LEG_NORTH],
    4: [LEG_SOUTH, LEG_EAST,  LEG_NORTH, LEG_WEST],
    5: [LEG_SOUTH, LEG_EAST,  LEG_NORTH, LEG_WEST, LEG_SOUTHEAST],
    6: [LEG_SOUTH, LEG_EAST,  LEG_NORTH, LEG_WEST, LEG_SOUTHEAST, LEG_NORTHEAST],
}

# Movement class indices in SIDRA API (1-based)
MC_LIGHT_VEHICLES = 1
MC_HEAVY_VEHICLES = 2

DIAGNOSTIC_STATUS = {1: "Processed", 2: "Not Processed",
                     3: "Input Warning", 4: "Processing Warning", 5: "Error"}


# ---------------------------------------------------------------------------
# SIDRASession – manages one SIAPI instance
# ---------------------------------------------------------------------------
class SIDRASession:
    """
    Context manager wrapping a SIDRA API session.

    Usage:
        with SIDRASession() as sid:
            sid.create_project(path, name)
            site = sid.add_roundabout_site(...)
            ...
            sid.process_site(site)
            results = sid.read_lane_outputs(site)
    """

    def __init__(self):
        if not _SIDRA_AVAILABLE:
            raise RuntimeError(
                f"SIDRA API could not be loaded: {_SIDRA_LOAD_ERROR}\n"
                f"Ensure SIDRA Intersection 10 is installed at:\n  {_SIDRA_INSTALL}"
            )
        self._api = SIAPI()
        self._project = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        try:
            self._api.Close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Project management
    # ------------------------------------------------------------------
    def create_project(self, filepath: str, name: str = "Calibration",
                       template: str = None):
        """
        Create a new .sipx project from the US template and open it.

        The template is required.  Without it every site would be built with
        SIDRA's generic metric model instead of US HCM (Customary), so the
        tool stops instead of silently continuing.

        Parameters
        ----------
        filepath : destination .sipx path (created if necessary)
        name     : project name label
        template : override template path
                   (default: templates/us_roundabout_template.sipx)
        """
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        tpl = template or _SIDRA_TEMPLATE_US
        if not os.path.isfile(tpl):
            raise FileNotFoundError(
                f"SIDRA US template not found at:\n  {tpl}\n"
                "The template ships with the tool in the templates/ folder. "
                "Restore it from the repository before running."
            )
        shutil.copy2(tpl, filepath)
        # Cloud-sync clients (Dropbox, OneDrive) can lock a new file briefly
        import time
        for attempt in range(6):
            try:
                self._api.OpenProject(filepath)
                break
            except Exception as e:
                if "being used by another process" not in str(e) or attempt == 5:
                    raise
                time.sleep(2)

        self._project = self._api.Project
        try:
            self._project.Name = name
        except Exception:
            pass  # Name is read-only on some template files
        return self._project

    def open_project(self, filepath: str):
        """Open an existing .sipx project file."""
        self._api.OpenProject(filepath)
        self._project = self._api.Project
        return self._project

    def save_project(self):
        self._api.SaveProject()

    def close_project(self):
        self._api.CloseProject()
        self._project = None

    # ------------------------------------------------------------------
    # Site creation
    # ------------------------------------------------------------------
    def find_template_roundabout(self):
        """Return (folder, site) for the US right-hand roundabout in the open project."""
        if self._project is None:
            raise RuntimeError("No project is open.")
        proj = self._project
        for fi in range(proj.SiteFolders.Count):
            folder = proj.SiteFolders[fi]
            for si in range(folder.Sites.Count):
                s = folder.Sites[si]
                if s.Sitetype == 1 and not s.Driveonleft and \
                        int(s.Units) == UNITS_CUSTOMARY:
                    return folder, s
        raise RuntimeError("US roundabout site (customary units, right-hand "
                           "traffic) not found in the template.")

    def add_roundabout_site_from_template(self, name: str) -> object:
        """
        Clone the template's US roundabout site, strip its legs and return it.

        The clone keeps the template's model (US HCM Customary), units,
        right-hand traffic and analysis settings.  All other sites are removed
        from the project so the saved .sipx holds only the new site.
        Legs are added afterwards with configure_leg().
        """
        folder, src = self.find_template_roundabout()
        site = folder.CloneSite(src)
        site.Name = name
        for ori in range(8):
            if site.Legs[ori] is not None:
                site.RemoveLeg(ori)
        proj = self._project
        for fi in range(proj.SiteFolders.Count):
            f = proj.SiteFolders[fi]
            for si in reversed(range(f.Sites.Count)):
                s = f.Sites[si]
                if s.Site_id != site.Site_id:
                    f.RemoveSite(s)
        return site

    def add_roundabout_site(self, name: str, n_legs: int,
                            folder_name: str = "Sites") -> object:
        """
        Add a blank roundabout site with AddSite().

        Note: SIDRA gives such sites the generic "Standard Right" model in
        metric units, not US HCM (Customary).  Use
        add_roundabout_site_from_template() for US analysis.
        """
        if self._project is None:
            raise RuntimeError("No project is open.")
        folder = self._project.AddSiteFolder(folder_name)
        # AddSite(site_type, n_legs): site_type=1 → Roundabout
        site = folder.AddSite(1, n_legs)
        site.Name = name
        return site

    # ------------------------------------------------------------------
    # Units
    # ------------------------------------------------------------------
    @staticmethod
    def is_customary(site) -> bool:
        """True when the site stores lengths in feet (US Customary)."""
        try:
            return int(site.Units) == UNITS_CUSTOMARY
        except Exception:
            return False

    def length_in_site_units(self, site, metres: float) -> float:
        """Convert a length in metres to the site's own length unit."""
        return metres * FT_PER_M if self.is_customary(site) else metres

    def set_inscribed_diameter(self, site, icd_m: float,
                               circ_lanes: int = None):
        """
        Set the island diameter on every leg from an INSCRIBED diameter (m).

        SIDRA's Island_diameter is the central island, so the value written
        is ICD - 2 x circulating width, in the site's own length unit.
        """
        for leg_idx in range(8):
            leg = self._get_leg(site, leg_idx)
            if leg is None:
                continue
            rleg = leg.Leg_roundabout
            if circ_lanes is not None:
                rleg.Num_circulating_lanes = int(circ_lanes)
            icd = self.length_in_site_units(site, icd_m)
            island = icd - 2.0 * float(rleg.Circulating_width)
            rleg.Island_diameter = max(island, 1.0)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def configure_leg(self, site, leg_orientation: int,
                      n_entry_lanes: int, n_exit_lanes: int,
                      n_circ_lanes: int, circ_width_m: float,
                      island_diameter_m: float,
                      entry_width_m: float = 4.0,
                      entry_radius_m: float = 20.0,
                      entry_angle_deg: float = 30.0,
                      leg_name: str = "") -> object:
        """
        Add and configure one leg on a roundabout site.

        Returns the ISIAPILeg object.
        """
        leg = site.AddLeg(leg_orientation)
        if leg_name:
            leg.Name = leg_name

        pos = 1
        # Exit lanes first (SIDRA convention for right-hand traffic)
        for _ in range(n_exit_lanes):
            leg.InsertExitLane(pos); pos += 1

        # Splitter island (required for roundabout legs)
        leg.InsertIsland_RoundaboutSplitter(pos); pos += 1

        # Entry (approach) lanes
        for _ in range(n_entry_lanes):
            leg.InsertApproachLane(pos); pos += 1

        # Roundabout geometry.  Inputs are metres; SIDRA expects the site's
        # own length unit (feet for US Customary sites).
        L = lambda m: self.length_in_site_units(site, m)
        rleg = leg.Leg_roundabout
        rleg.Num_circulating_lanes = n_circ_lanes
        rleg.Circulating_width     = L(circ_width_m)
        rleg.Island_diameter       = L(island_diameter_m)

        # Lane geometry (entry width, radius, angle)
        # These are set on the leg level in SIDRA v10
        try:
            rleg.Entry_width = L(entry_width_m)
            rleg.Entry_radius = L(entry_radius_m)
            rleg.Entry_angle  = entry_angle_deg
        except AttributeError:
            # Property names may vary – skip silently; defaults will be used
            pass

        return leg

    def finalize_geometry(self, site):
        """Must be called after all legs/lanes are added."""
        self._set_default_lane_disciplines(site)  # must happen before UpdateGeometryData
        site.UpdateGeometryData()

    def _set_default_lane_disciplines(self, site):
        """
        Assign lane disciplines after UpdateGeometryData().
        Each approach lane is assigned to all valid destinations (all other legs).
        SetDefaultLaneDisciplines() was removed in SIDRA v10; this replicates it.

        Note: site.Legs is indexed by orientation (0–7), not sequentially.
              site.Legs[2] = East leg (orientation 2), legs[1] = None if not added.
        """
        legs = site.Legs
        # Collect all actual legs by scanning all 8 orientation slots
        leg_list = [legs[ori] for ori in range(8) if legs[ori] is not None]
        all_orientations = [leg.Orientation for leg in leg_list]

        for leg in leg_list:
            try:
                lane_apprhs = leg.LaneApproachs
            except Exception:
                continue
            for lane_no in range(1, lane_apprhs.Count + 1):
                try:
                    lane = lane_apprhs[lane_no]
                    if lane is None:
                        continue
                    for dest_ori in all_orientations:
                        if dest_ori == leg.Orientation:
                            continue  # skip U-turn
                        try:
                            mov = lane.LaneApproachMovements[dest_ori]
                            if mov is None:
                                continue
                            mov.LaneApproachMovementMCs[MC_LIGHT_VEHICLES].Exists = True
                            mov.LaneApproachMovementMCs[MC_HEAVY_VEHICLES].Exists = True
                        except Exception:
                            pass
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Volumes
    # ------------------------------------------------------------------
    def set_volume(self, site, origin_leg: int, dest_leg: int,
                   lv_volume: int, hv_volume: int = 0):
        """
        Set vehicle OD movement volume.

        origin_leg / dest_leg : leg orientation indices (0–7)
        lv_volume             : light vehicle volume (veh/h or veh/period)
        hv_volume             : heavy vehicle volume
        """
        mov = site.MovementVehicleODs[origin_leg, dest_leg]
        if mov is None:
            return
        mov.MovementVehicleODMCs[MC_LIGHT_VEHICLES].Volume = int(lv_volume)
        if hv_volume:
            mov.MovementVehicleODMCs[MC_HEAVY_VEHICLES].Volume = int(hv_volume)

    # ------------------------------------------------------------------
    # Calibration parameters
    # ------------------------------------------------------------------
    def set_environment_factor(self, site, fe: float):
        """
        Set the Environment Factor on all legs of a roundabout site.
        fe range: 0.5 – 2.0  (default 1.05 for SIDRA Standard US HCM single-lane)
        Property name confirmed via introspection: Environment_factor
        """
        for leg_idx in range(8):
            leg = self._get_leg(site, leg_idx)
            if leg is None:
                continue
            leg.Leg_roundabout.Environment_factor = fe

    def set_hcm_calibration_factor(self, site, cf: float,
                                   model: int = MODEL_HCM6):
        """
        Set the HCM Model Calibration Factor (cf) on all legs.

        model : MODEL_HCM6 (LegRouHCM6) or MODEL_HCM2010 (LegRouHCM2010).
        cf only changes results when the site runs that capacity model;
        select it first with set_capacity_model().
        """
        for leg_idx in range(8):
            leg = self._get_leg(site, leg_idx)
            if leg is None:
                continue
            rleg = leg.Leg_roundabout
            if model == MODEL_HCM2010:
                rleg.LegRouHCM2010.Model_calib_factor = cf
            else:
                rleg.LegRouHCM6.Model_calib_factor = cf

    def set_capacity_model(self, site, model: int):
        """
        Select the roundabout capacity model:
        MODEL_SIDRA_STANDARD (0), MODEL_HCM2010 (1) or MODEL_HCM6 (2).
        """
        site.ModelSetting.Rou_Capacity_Model = int(model)

    def get_capacity_model(self, site) -> int:
        return int(site.ModelSetting.Rou_Capacity_Model)

    def set_calibration_parameter(self, site, value: float):
        """
        Set the parameter that belongs to the site's current capacity model:
        fe for SIDRA Standard, cf for HCM 2010 / HCM 6.
        """
        model = self.get_capacity_model(site)
        if model == MODEL_SIDRA_STANDARD:
            self.set_environment_factor(site, value)
        else:
            self.set_hcm_calibration_factor(site, value, model)

    def is_hcm6_mode(self, site) -> bool:
        """Return True if the site is using the HCM 6 capacity model."""
        return self.get_capacity_model(site) == MODEL_HCM6

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------
    def process_site(self, site) -> bool:
        """Run SIDRA analysis. Returns True on success."""
        ok = site.Process()
        if not ok or site.Outputset is None:
            msgs = [site.DiagnosticMsgs[i].Message
                    for i in range(site.DiagnosticMsgs.Count)]
            status = DIAGNOSTIC_STATUS.get(site.DiagnosticStatus, "Unknown")
            detail = "; ".join(msgs) if msgs else (site.ProcessingError or "no detail")
            raise RuntimeError(f"SIDRA processing failed [{status}]: {detail}")
        return ok

    # ------------------------------------------------------------------
    # Output reading
    # ------------------------------------------------------------------
    def read_lane_outputs(self, site) -> list[dict]:
        """
        Read per-lane outputs after processing.

        Returns a list of dicts, one per active entry lane, with keys:
          leg_idx, leg_name, lane_no,
          flow_veh_h, capacity_veh_h, deg_satn,
          avg_delay_s, level_of_service, queue_95pct_veh

        Property names confirmed via introspection:
          OutputLeg:  Delay_control_average, Level_of_service, Queue_maxback_percentile
          OutputLane: Flow_total, Capacity, Deg_satn
        """
        outputset = site.Outputset
        if outputset is None:
            raise RuntimeError("Site has not been processed.")

        results = []
        output_legs = outputset.OutputLegs

        for leg_idx in range(8):
            output_leg = output_legs[leg_idx]
            if output_leg is None:
                continue

            leg = self._get_leg(site, leg_idx)
            leg_name = leg.Name if leg else f"Leg{leg_idx}"
            leg_delay  = self._safe_get(output_leg, "Delay_control_average",  None)
            leg_los    = self._safe_get(output_leg, "Level_of_service",        None)
            leg_queue  = self._safe_get(output_leg, "Queue_maxback_percentile", None)

            output_lanes = output_leg.OutputLanes
            for lane_no in range(1, output_lanes.Count + 1):
                ol = output_lanes[lane_no]
                results.append({
                    "leg_idx":          leg_idx,
                    "leg_name":         leg_name,
                    "lane_no":          lane_no,
                    "flow_veh_h":       self._safe_get(ol, "Flow_total", 0.0),
                    "capacity_veh_h":   self._safe_get(ol, "Capacity",   0.0),
                    "deg_satn":         self._safe_get(ol, "Deg_satn",   0.0),
                    "avg_delay_s":      leg_delay,
                    "level_of_service": leg_los,
                    "queue_95pct_veh":  leg_queue,
                })
        return results

    def read_intersection_summary(self, site) -> dict:
        """Read intersection-level summary outputs."""
        outputset = site.Outputset
        if outputset is None:
            raise RuntimeError("Site has not been processed.")

        sv = outputset.OutputSiteVehicle
        return {
            "flow_total_veh_h": self._safe_get(sv, "Flow_total",   0.0),
            "travel_speed":     self._safe_get(sv, "Travel_speed", 0.0),
        }

    # ------------------------------------------------------------------
    # Diagnostics / discovery
    # ------------------------------------------------------------------
    def introspect_roundabout_leg(self, site) -> list[str]:
        """
        Return all settable properties on ISIAPILeg_roundabout.
        Useful for discovering the exact Environment Factor property name.
        """
        for leg_idx in range(8):
            leg = self._get_leg(site, leg_idx)
            if leg is None:
                continue
            rleg = leg.Leg_roundabout
            return [p for p in dir(rleg) if not p.startswith("_")]
        return []

    def get_diagnostics(self, site) -> str:
        status = DIAGNOSTIC_STATUS.get(site.DiagnosticStatus, "Unknown")
        msgs = [site.DiagnosticMsgs[i].Message
                for i in range(site.DiagnosticMsgs.Count)]
        return f"Status: {status}\n" + "\n".join(msgs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_leg(self, site, leg_idx: int):
        # Legs is indexed by orientation directly (0–7)
        try:
            leg = site.Legs[leg_idx]
            return leg if leg is not None else None
        except Exception:
            return None

    @staticmethod
    def _safe_get(obj, attr: str, default):
        try:
            return getattr(obj, attr)
        except Exception:
            return default

# SIDRA template

`us_roundabout_template.sipx` contains one roundabout site, set up in SIDRA
Intersection 10 as follows:

- Model setup: US HCM (Customary); lengths in feet
- Right-hand traffic
- Volumes in veh/h (unit time 60 min), peak flow period 15 min
- Capacity model SIDRA Standard, fe = 1.05, HCM 2010 and HCM 6 cf = 1.0

The tools clone this site for every analysis and then set the capacity model
and its parameter in code, so it does not matter which model is stored in the
template. Units and driving side are a different story: the SIDRA API cannot
change them on an existing site, so they have to come from the template.

Please leave the template alone unless the project-level settings need to
change. If you do rebuild it, keep a single roundabout site with the settings
listed above.

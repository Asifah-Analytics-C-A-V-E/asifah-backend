"""
notam_monitor.py -- ME shim (v3.0.0, Nov 1 2026)

Airspace Watch now lives in airspace_watch.py, a shared module that is
byte-identical on all five backends. This file stays only so ME app.py
(`from notam_monitor import register_notam_endpoints`) needs no edit.
"""
from airspace_watch import register_airspace_endpoints


def register_notam_endpoints(app):
    register_airspace_endpoints(app, 'me', legacy_route='/api/notams', job_name='notam_scan')

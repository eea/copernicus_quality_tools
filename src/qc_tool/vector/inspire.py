#! /usr/bin/env python3
# -*- coding: utf-8 -*-


"""
The last implementation used external inspire validation service at `<http://inspire-geoportal.ec.europa.eu/GeoportalProxyWebServices/resources/INSPIREResourceTester>`_.
Such service has been discontinued.

Until new implementation come, the check always results in cancelled.
Cancelled result does not prevent later submittion of the delivery.
This way it may be avoided adapting and hampering already stable product definitions.
"""


DESCRIPTION = "Metadata are in accord with INSPIRE specification."
IS_SYSTEM = False


def run_check(params, status):
    """The check always results in cancelled."""
    status.cancelled("The check is not implemented yet.")

"""One temporary root for everything the tests create, removed when the run ends.

Tests call ``mkdtemp`` from here instead of ``tempfile.mkdtemp``; nothing is left
behind in %TEMP%, even for tests that never clean up after themselves.
"""
import atexit
import logging
import os
import shutil
import tempfile

_root = None


def mkdtemp(prefix="halo_battery_test_"):
    global _root
    if _root is None:
        _root = tempfile.mkdtemp(prefix="halo_tests_")
        atexit.register(_cleanup)
    return tempfile.mkdtemp(prefix=prefix, dir=_root)


def _cleanup():
    logging.shutdown()          # the app's log file lives in one of the folders
    if _root:
        shutil.rmtree(_root, ignore_errors=True)

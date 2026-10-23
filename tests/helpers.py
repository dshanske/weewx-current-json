"""Puts the extension and WeeWX on the path for the tests.

WeeWX itself must be importable: run the tests from a WeeWX 5 environment, or point WEEWX_LIB at a
directory holding the weewx, weeutil and weedb packages (such as an unpacked weewx wheel).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'bin'))
if os.environ.get('WEEWX_LIB'):
    sys.path.insert(1, os.environ['WEEWX_LIB'])

DATA = os.path.join(HERE, 'data')

#!/usr/bin/env python3

import argparse

import opcodemap

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db")
    ns = parser.parse_args()
    if not ns.db:
        ns.db = "opcode.db"
    with opcodemap.OpcodeMapping(ns.db, False) as opc_map:

        # Based on some manual debugging we found that earlier versions of
        # gendb didn't properly derive some opcodes such as BUILD_CONST_KEY_MAP
        # / 156. The gendb script has been changed and with this script we can
        # now quickly check whether we found this one and if the mapping is
        # still the same. Just for testing purposes of the other scripts.

        assert(opc_map.get(252) == 156)

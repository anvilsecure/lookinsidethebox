#!/usr/bin/env python3

import argparse
import dis

import opcodemap

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db")
    ns = parser.parse_args()
    if not ns.db:
        ns.db = "opcode.db"
    with opcodemap.OpcodeMapping(ns.db, False) as opc_map:

        table = opc_map.reverse_mapping()

        # Based on some manual debugging we found that earlier versions of
        # gendb didn't properly derive some opcodes such as BUILD_CONST_KEY_MAP
        # / 156. The gendb script has been changed and with this script we can
        # now quickly check whether we found this one and if the mapping is
        # still the same. Just for testing purposes of the other scripts.
        assert(opc_map.get(252) == 156)
        assert(table.get(156) == 252)

        print("mapping as defined in %s is as follows:" % ns.db)
        fmt = "| {0:<30} | {1:>7} | {2:>7} |"
        print(fmt.format("="*30, "="*7, "="*7))
        print(fmt.format("OPCODE", "PYTHON", "DROPBOX"))
        print(fmt.format("="*30, "="*7, "="*7))
        for i, opname in enumerate(dis.opname):
            db_i = table.get(i)
            if db_i is None:
                continue
            print(fmt.format(opname, i, db_i))
        print(fmt.format("="*30, "="*7, "="*7))
        print("")

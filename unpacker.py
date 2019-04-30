#!/usr/bin/env python3

import argparse
import logging
import sys
import struct
import zipfile
import io
import types
import os

import opcodemap
import tea
import unmarshaller

if sys.version_info[0] < 3:
    raise Exception("This module is Python 3 only")

logger = logging.getLogger(__name__)


def rng(a, b):
    b = ((b << 13) ^ b) & 0xffffffff
    c = (b ^ (b >> 17))
    c = (c ^ (c << 5))
    return (a * 69069 + c + 0x6611CB3B) & 0xffffffff


def _int32(x):
    # Get the 32 least significant bits.
    return int(0xFFFFFFFF & x)


class MT19937:

    def __init__(self, seed):
        # Initialize the index to 0
        self.index = 624
        self.mt = [0] * 624
        self.mt[0] = seed  # Initialize the initial state to the seed
        for i in range(1, 624):
            self.mt[i] = _int32(
                1812433253 * (self.mt[i - 1] ^ self.mt[i - 1] >> 30) + i)

    def extract_number(self):
        if self.index >= 624:
            self.twist()

        y = self.mt[self.index]

        # Right shift by 11 bits
        y = y ^ y >> 11
        # Shift y left by 7 and take the bitwise and of 2636928640
        y = y ^ y << 7 & 2636928640
        # Shift y left by 15 and take the bitwise and of y and 4022730752
        y = y ^ y << 15 & 4022730752
        # Right shift by 18 bits
        y = y ^ y >> 18

        self.index = self.index + 1

        return _int32(y)

    def twist(self):
        for i in range(624):
            # Get the most significant bit and add it to the less significant
            # bits of the next number
            y = _int32((self.mt[i] & 0x80000000) +
                       (self.mt[(i + 1) % 624] & 0x7fffffff))
            self.mt[i] = self.mt[(i + 397) % 624] ^ y >> 1

            if y % 2 != 0:
                self.mt[i] = self.mt[i] ^ 0x9908b0df
        self.index = 0


def load_code(self):
    rand = self.r_long()
    length = self.r_long()

    seed = rng(rand, length)
    mt = MT19937(seed)
    key = []
    for i in range(0, 4):
        key.append(mt.extract_number())

    # take care of padding for size calculation
    sz = (length + 15) & ~0xf
    words = sz / 4

    # convert data to list of dwords
    buf = self._read(sz)
    data = list(struct.unpack("<%dL" % words, buf))

    # decrypt and convert back to stream of bytes
    data = tea.tea_decipher(data, key)
    data = struct.pack("<%dL" % words, *data)

    iodata = io.BytesIO(data)
    um = unmarshaller.Unmarshaller(iodata.read)
    # make sure that the rest is being marshalled with the same TYPE_CODE
    # dispatch method as is being used for the current code object such that we
    # end up with a consistent ummarshalled object structure (instead of for
    # example having parent code level objects being opcode-remapped and child
    # objects still having the obfuscated opcode-mapping.
    um.opcode_mapping = self.opcode_mapping
    um.dispatch[unmarshaller.TYPE_CODE] = self.dispatch[unmarshaller.TYPE_CODE]
    um.flags.append(0)
    um.depth = self.depth
    retval = um.load_code()
    return retval


def load_code_without_patching(self):
    code = load_code(self)
    return types.CodeType(code.co_argcount, code.co_kwonlyargcount,
                          code.co_nlocals, code.co_stacksize, code.co_flags,
                          code.co_code, code.co_consts, code.co_names,
                          code.co_varnames, code.co_filename, code.co_name,
                          code.co_firstlineno, code.co_lnotab,
                          code.co_freevars, code.co_cellvars)


def load_code_with_patching(self):
    code = load_code(self)
    bcode = bytearray(code.co_code)
    opcode_map = self.opcode_mapping
    i = 0
    n = len(bcode)
    while i < n:
        old = bcode[i]
        new = opcode_map.get(bcode[i])
        if old != 90:
            bcode[i] = new
        i = i + (2)  # HAVE_ARGUMENT
        # 144 extended_arg
    bcode = bytes(bcode)
    return types.CodeType(code.co_argcount, code.co_kwonlyargcount,
                          code.co_nlocals, code.co_stacksize, code.co_flags,
                          bcode, code.co_consts, code.co_names,
                          code.co_varnames, code.co_filename, code.co_name,
                          code.co_firstlineno, code.co_lnotab,
                          code.co_freevars, code.co_cellvars)


def decompile_co_object(co):
    from uncompyle6 import code_deparse
    out = io.StringIO()
    try:
        debug_opts = {"asm": False, "tree": False, "grammar": False}
        code_deparse(co, out=out, version=3.6, debug_opts=debug_opts)
    except Exception as e:
        return (False, "Error while trying to decompile\n%s" % (str(e)))
    return (True, out.getvalue())


def decompile_pycfiles_from_zipfile(opc_map, zf, outdir):
    failed = 0
    processed = 0
    for fn in zf.namelist():
        if fn[-3:] != "pyc":
            continue
        with zf.open(fn, "r") as f:
            processed += 1

            logger.info("Decrypting, patching and decompiling %s" % fn)
            try:
                f.read(12)
                um = unmarshaller.Unmarshaller(f.read)
                um.opcode_mapping = opc_map
                um.dispatch[unmarshaller.TYPE_CODE] = (load_code_with_patching,
                                                       "TYPE_CODE")
                co = um.load()

                outfn = os.path.join(outdir, fn[:-1])
                ok, res = decompile_co_object(co)
                if not ok:
                    logger.warning("Failed to decompile %s to %s" %
                                   (fn, outfn))
                    failed += 1
                else:
                    logger.info("Successfully decompiled %s to %s" %
                                (fn, outfn))

                partial_dirname = os.path.dirname(fn)
                full_dirname = os.path.join(outdir, partial_dirname)
                os.makedirs(full_dirname, exist_ok=True)
                with open(outfn, "wb") as outfd:
                    outfd.write(res.encode("utf-8"))

            except Exception as e:
                failed += 1
                logger.error("Exception %s occured" % str(e))
                break
    logger.info("Processed %d files (%d succesfully decompiled, %d failed)" %
                (processed, processed-failed, failed))


if __name__ == "__main__":

    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    parser = argparse.ArgumentParser()
    parser.add_argument("--dropbox-zip", required=True,
                        help="zipfile containing the dropbox obfuscated code")
    parser.add_argument("--output-dir", default="./out",
                        help="output dir for the decompiled source code "
                             "(will be created if it doesn't exist)")
    parser.add_argument("--db", default="opcode.db",
                        help="opcode database file to use")
    ns = parser.parse_args()

    with opcodemap.OpcodeMapping(ns.db, False) as opc_map:
        with zipfile.PyZipFile(ns.dropbox_zip, "r",
                               zipfile.ZIP_DEFLATED) as zf:
            decompile_pycfiles_from_zipfile(opc_map, zf, ns.output_dir)

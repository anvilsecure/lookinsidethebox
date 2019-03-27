#!/usr/bin/env python3

import argparse
import logging
import sys
import struct
import zipfile
import io
import types
import os
import marshal

import unmarshaller

logger = logging.getLogger(__name__)


def rng(a, b):
    b = ((b << 13) ^ b) & 0xffffffff
    c = (b ^ (b >> 17))
    c = (c ^ (c << 5))
    return (a * 69069 + c + 0x6611CB3B) & 0xffffffff


def MX(z, y, sum, key, p, e):
    return (((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^
            ((sum ^ y) + (key[(p & 3) ^ e] ^ z)))


def tea_decipher(v, key):
    DELTA = 0x9e3779b9
    n = len(v)
    rounds = 6 + 52//n
    sum = (rounds*DELTA)
    y = v[0]
    while sum != 0:
        e = (sum >> 2) & 3
        for p in range(n - 1, -1, -1):
            z = v[(n + p - 1) % n]
            v[p] = (v[p] - MX(z, y, sum, key, p, e)) & 0xffffffff
            y = v[p]
        sum -= DELTA
    return v


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
    data = tea_decipher(data, key)
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
        import dis
        if old != 90:
            bcode[i] = new
        # i = i + (2 if bcode[i] >= 90 else 1)  # HAVE_ARGUMENT
        i = i + (2)# if bcode[i] >= 90 else 1)  # HAVE_ARGUMENT
        # 144 extended_arg
    bcode = bytes(bcode)
    return types.CodeType(code.co_argcount, code.co_kwonlyargcount,
                          code.co_nlocals, code.co_stacksize, code.co_flags,
                          bcode, code.co_consts, code.co_names,
                          code.co_varnames, code.co_filename, code.co_name,
                          code.co_firstlineno, code.co_lnotab,
                          code.co_freevars, code.co_cellvars)


class OpcodeMapping:
    # before using always need to call sanitize()
    def __init__(self):
        self.table = {}
        self.map = {}
        self.co_len_mismatch = 0
        self.co_matched = 0

    def _map_co_objects(self, a, b):
        if len(a.co_code) != len(b.co_code):
            self.co_len_mismatch += 1
            return
        for i, j in zip(a.co_code, b.co_code):
            v = self.map.setdefault(i, {})
            v[j] = v.get(j, 0) + 1

    def map_co_objects(self, a, b):
        self.co_matched += 1
        self._map_co_objects(a, b)
        a_c = filter(lambda x: isinstance(x, types.CodeType), a.co_consts)
        b_c = filter(lambda x: isinstance(x, types.CodeType), b.co_consts)
        for i, j in zip(a_c, b_c):
            self.map_co_objects(i, j)

    def sanitize(self):
        table = {}
        keys = sorted(self.map.keys())
        for key in keys:
            maxcnt = 0
            for i, count in self.map[key].items():
                if i == key:
                    continue
                if maxcnt < count:
                    maxcnt = count
                    table[key] = i
        self.table = table
        self.missing = {}
        return self.table

    def get(self, op):
        if op not in self.table:
            self.missing[op] = self.missing.get(op, 0) + 1
        op_new = self.table.get(op, op)
        return op_new


def decompile_co_object(co):
    from uncompyle6 import code_deparse
    out = io.StringIO()
    try:
        debug_opts = {"asm": False, "tree": False, "grammar": False}
        code_deparse(co, out=out, version=3.6, debug_opts=debug_opts)
    except Exception as e:
        return "Error while trying to decompile\n%s" % (str(e))
    return out.getvalue()


def decompile_pycfiles_from_zipfile(zf, files, mapping, limit=-1):
    ii = 0
    for fn in files:
        if fn[-3:] != "pyc":
            continue
        logger.info("opening %s" % fn)
        with zf.open(fn, "r") as f:
            ii += 1
            if limit > 0 and ii > limit:
                break

            f.read(12) # XXX should be seek
            um = unmarshaller.Unmarshaller(f.read)
            um.opcode_mapping = mapping
            um.dispatch[unmarshaller.TYPE_CODE] = (load_code_with_patching,
                                                   "TYPE_CODE")
            co = um.load()

            res = decompile_co_object(co)

            output_dir = os.path.dirname(fn)
            if len(output_dir) > 0:
                os.makedirs("out/%s" % output_dir, exist_ok=True)
            with open("out/%s" % fn[:-1], "wb") as outfd:
                #d = marshal.dumps(co)
                #outfd.write(b"\x42\x0d\x0d\x0a\x00\x00\x00\x00\x0a\x00\x20\x5c\xb8\x89\x00\x00")
                outfd.write(res.encode("utf-8"))



def generate_opcode_mapping_from_zipfile(zf, files, pydir, limit=-1):
    mapping = OpcodeMapping()
    ii = 0
    for fn in files:
        if fn[-3:] != "pyc":
            continue
        logger.info("opening %s" % fn)
        with zf.open(fn, "r") as f:
            ii += 1
            if limit > 0 and ii > limit:
                break

            data = f.read(12)
            um = unmarshaller.Unmarshaller(f.read)
            um.dispatch[unmarshaller.TYPE_CODE] = (load_code_without_patching,
                                                   "TYPE_CODE")
            remapped_co = um.load()

            # XXX need to determine the cpython-37 part automatically
            libfile = "%s/%s.cpython-36.opt-2.pyc" % (pydir, fn[:-4])
            libfile = "%s/__pycache__/%s" % (os.path.dirname(libfile),
                                             os.path.basename(libfile))

            try:
                with open(libfile, "rb") as f:
                    f.read(12)
                    data = f.read()
                    orig_co = marshal.loads(data)
                    logger.info("mapping %s to %s" % (remapped_co.co_filename,
                                orig_co.co_filename))
                    mapping.map_co_objects(remapped_co, orig_co)

            except FileNotFoundError:
                continue
    mapping.sanitize()
    return mapping


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
    parser.add_argument("--python-dir", required=True)
    parser.add_argument("--dropbox-zip", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--opcode-file")
    ns = parser.parse_args()

    if not ns.opcode_file:
        ns.opcode_file = "opcode.db"

    max_fn = 1000

    with zipfile.PyZipFile(ns.dropbox_zip, "r", zipfile.ZIP_DEFLATED) as zf:
        mapping = generate_opcode_mapping_from_zipfile(zf, zf.namelist(),
                                                       ns.python_dir, max_fn)
        decompile_pycfiles_from_zipfile(zf, zf.namelist(), mapping, max_fn)


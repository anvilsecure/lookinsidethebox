#!/usr/bin/env python3

import argparse
import hashlib
import logging
import sys
import struct
import zipfile
import types
import io

import opcodemap
import tea
import unmarshaller
import unpacker

logger = logging.getLogger(__name__)


def read_wrapper(self, readfn):
    def fn(sz):
        data = readfn(sz)
        fn.bytez.write(data)
        return data
    fn.bytez = io.BytesIO()
    return fn



def load_code(self, search, replace):
    rand = self.r_long()
    length = self.r_long()

    seed = unpacker.rng(rand, length)
    mt = unpacker.MT19937(seed)
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

    if search in data:
        print(data)
        print(len(data))
        ndata = data.replace(search, replace)
        ndata = list(struct.unpack("<%dL" % words, ndata))
        ndata = tea.tea_encipher(ndata, key)
        ndata = struct.pack("<%dL" % words, *ndata)
        print(ndata)
        print(len(ndata))

        print(self._read)
        bytez = self._read.bytez
        print(bytez.tell())
        print(bytez.seekable())
        print(bytez.seek(bytez.tell()-len(ndata)))
        bytez.write(ndata)
        print(bytez.tell())
        print(dir(bytez))


    iodata = io.BytesIO(data)
    um = unmarshaller.Unmarshaller(read_wrapper(self, iodata.read))
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

def replace_hash(search, replace):
    def fn(self):
        code = load_code(self, search, replace)
        consts = [x if x != search else replace for x in list(code.co_consts)]
        ret_co = types.CodeType(code.co_argcount, code.co_kwonlyargcount,
                              code.co_nlocals, code.co_stacksize, code.co_flags,
                              code.co_code, tuple(consts), code.co_names,
                              code.co_varnames, code.co_filename, code.co_name,
                              code.co_firstlineno, code.co_lnotab,
                              code.co_freevars, code.co_cellvars)
        return (search in code.co_consts, ret_co)
    return fn

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
    parser.add_argument("--dropbox-zip", required=True)
    parser.add_argument("--db")
    ns = parser.parse_args()

    if not ns.db:
        ns.db = "opcode.db"

    hashes = {
            "dropbox/foundation/environment.pyc": b"e27eae61e774b19f4053361e523c771a92e838026da42c60e6b097d9cb2bc825",
            "dropbox/webdebugger/server.pyc": b"5df50a9c69f00ac71f873d02ff14f3b86e39600312c0b603cbb76b8b8a433d3f"
    }

    replace_str = bytes(hashlib.sha256(b"ANVILVENTURES").hexdigest(), encoding="ascii")

    with opcodemap.OpcodeMapping(ns.db) as opc_map:
        with zipfile.PyZipFile(ns.dropbox_zip,
                               "r",
                               zipfile.ZIP_DEFLATED) as zf:
            for fn in [x for x in zf.namelist() if x in hashes]:
                with zf.open(fn, "r") as f:

                    data = f.read(12)
                    ulc = unpacker.load_code_without_patching
                    um = unmarshaller.Unmarshaller(f.read)
                    um._read = read_wrapper(um, f.read)  # XXX dirty
                    um.dispatch[unmarshaller.TYPE_CODE] = (replace_hash(hashes[fn], replace_str), "TYPE_CODE")
                    replaced, co = um.load()



                    print(um._read.bytez)
                    print(dir(um._read.bytez))
                    print(um._read.bytez.tell())

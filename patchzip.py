#!/usr/bin/env python3

import argparse
import hashlib
import logging
import sys
import struct
import zipfile
import types
import io

import tea
import unmarshaller
import unpacker

if sys.version_info[0] < 3:
    raise Exception("This module is Python 3 only")

logger = logging.getLogger(__name__)


def read_wrapper(self, readfn):
    def fn(sz):
        data = readfn(sz)
        fn.bytez.write(data)
        return data
    fn.bytez = io.BytesIO()
    return fn


def dump_code_wrapper(self, co):
    start_off = self._buf.tell()
    self.dump_code(co)
    self._buf.flush()
    end_off = self._buf.tell()
    ln = end_off - start_off
    self._buf.seek(start_off)

    # make sure to skip past the TYPE_CODE identifier
    data = self._buf.read(ln)
    data = data[1:]

    rand = 0x00000000
    length = len(data)
    sz = (length + 15) & ~0xf
    words = sz / 4

    seed = unpacker.rng(rand, length)
    mt = unpacker.MT19937(seed)
    key = []
    for i in range(0, 4):
        key.append(mt.extract_number())

    # convert data to list of dwords
    data = data + bytes(sz - length)
    data = list(struct.unpack("<%dL" % words, data))

    # encrypt and convert back to stream of bytes
    data = tea.tea_encipher(data, key)
    data = struct.pack("<%dL" % words, *data)

    assert(len(data) == sz)

    self._buf.seek(start_off+1)
    self.w_long(rand)
    self.w_long(length)
    self._write(data)


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
        if search in code.co_consts:
            logging.info("replacing %s with %s in %s at line %i" %
                         (search, replace, code.co_filename,
                          code.co_firstlineno))
        consts = [x if x != search else replace for x in list(code.co_consts)]
        ret_co = types.CodeType(code.co_argcount, code.co_kwonlyargcount,
                                code.co_nlocals, code.co_stacksize,
                                code.co_flags, code.co_code, tuple(consts),
                                code.co_names, code.co_varnames,
                                code.co_filename, code.co_name,
                                code.co_firstlineno, code.co_lnotab,
                                code.co_freevars, code.co_cellvars)
        return ret_co
    return fn


if __name__ == "__main__":

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    parser = argparse.ArgumentParser()
    parser.add_argument("--dropbox-zip", required=True,
                        help="zipfile containing the dropbox obfuscated code")
    parser.add_argument("--output-zip", default="./out.zip",
                        help="output zip filename with patched hashes")
    ns = parser.parse_args()

    logger.info("rewriting %s and outputting to %s" %
                (ns.dropbox_zip, ns.output_zip))

    hashes = {
            "build_number/environment.pyc":
            "e27eae61e774b19f4053361e523c771a92e838026da42c60e6b097d9cb2bc825",
            "dropbox/webdebugger/server.pyc":
            "5df50a9c69f00ac71f873d02ff14f3b86e39600312c0b603cbb76b8b8a433d3f"
    }

    results = {}

    replace_str = hashlib.sha256(b"ANVILVENTURES").hexdigest()

    with zipfile.PyZipFile(ns.dropbox_zip,
                           "r",
                           zipfile.ZIP_DEFLATED) as zf:
        for fn in [x for x in zf.namelist() if x in hashes]:
            with zf.open(fn, "r") as f:

                data = f.read(12)
                ulc = unpacker.load_code_without_patching
                um = unmarshaller.Unmarshaller(f.read)
                um._read = read_wrapper(um, f.read)  # XXX dirty
                um.dispatch[unmarshaller.TYPE_CODE] = (replace_hash(hashes[fn],
                                                       replace_str),
                                                       "TYPE_CODE")
                co = um.load()

                with io.BytesIO() as out:
                    out.write(data)
                    m = unmarshaller.Marshaller(out.write, out)
                    m.dispatch[unmarshaller.TYPE_CODE] = (dump_code_wrapper,
                                                          "TYPE_CODE")
                    m.dump(co)

                    out.flush()
                    results[fn] = bytes(out.getbuffer())

        with zipfile.PyZipFile(ns.output_zip,
                               "w",
                               zipfile.ZIP_DEFLATED) as zout:
            zout.comment = zf.comment
            for item in zf.infolist():
                if item.filename not in results:
                    zout.writestr(item, zf.read(item.filename))
                    continue
                zout.writestr(item, results[item.filename])

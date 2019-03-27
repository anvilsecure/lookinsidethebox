#!/usr/bin/env python3

import logging
import struct
import sys
import types

if sys.version_info[0] < 3:
    raise Exception("This module is Python 3 only")

logger = logging.getLogger(__name__)

MAX_MARSHAL_STACK_DEPTH = 2000
FLAG_REF = 0x80
SIZE32_MAX = 0x7FFFFFFF

TYPE_NULL = '0'
TYPE_NONE = 'N'
TYPE_FALSE = 'F'
TYPE_TRUE = 'T'
TYPE_STOPITER = 'S'
TYPE_ELLIPSIS = '.'
TYPE_INT = 'i'
TYPE_INT64 = 'I'
TYPE_FLOAT = 'f'
TYPE_BINARY_FLOAT = 'g'
TYPE_COMPLEX = 'x'
TYPE_BINARY_COMPLEX = 'y'
TYPE_LONG = 'l'
TYPE_STRING = 's'
TYPE_INTERNED = 't'
TYPE_REF = 'r'
TYPE_TUPLE = '('
TYPE_LIST = '['
TYPE_DICT = '{'
TYPE_CODE = 'c'
TYPE_UNICODE = 'u'
TYPE_UNKNOWN = '?'
TYPE_SET = '<'
TYPE_FROZENSET = '>'
TYPE_ASCII = 'a'
TYPE_ASCII_INTERNED = 'A'
TYPE_SMALL_TUPLE = ')'
TYPE_SHORT_ASCII = 'z'
TYPE_SHORT_ASCII_INTERNED = 'Z'


class _NULL:
    pass


def R_REF(func):
    def wrapper(*args, **kwargs):
        retval = func(*args, **kwargs)
        retval = args[0].r_ref(retval)
        return retval
    return wrapper


class Unmarshaller:

    def __init__(self, readfunc):
        self._read = readfunc

        # dynamically create the dispatcher by finding all
        # globals that start with TYPE_ and then mapping
        # them to associated methods in this class
        types = [x for x in globals() if x.startswith("TYPE_")]
        dispatch = {}
        for _type in types:
            dispatch[globals()[_type]] = (getattr(Unmarshaller, "load_%s" % (_type[5:].lower())), _type)

        self.dispatch = dispatch
        self._opcode_mapping = None
        self.depth = 0  # XXX should this be here or at the top of the unmarshaller?
        self.refs = []
        self.flags = []

    @property
    def opcode_mapping(self):
        return self._opcode_mapping

    @opcode_mapping.setter
    def opcode_mapping(self, value):
        self._opcode_mapping = value

    def load(self):
        return self.r_object()

    def r_long64(self):
        a = ord(self._read(1))
        b = ord(self._read(1))
        c = ord(self._read(1))
        d = ord(self._read(1))
        e = ord(self._read(1))
        f = ord(self._read(1))
        g = ord(self._read(1))
        h = ord(self._read(1))
        x = a | (b << 8) | (c << 16) | (d << 24)
        x = x | (e << 32) | (f << 40) | (g << 48) | (h << 56)
        if h & 0x80 and x > 0:
            x = -((1 << 64) - x)
        return x

    def r_ref_reserve(self):
        if self.flags[-1]:
            lr = len(self.refs)
            if lr > SIZE32_MAX-1:
                raise Exception("bad marshal data (index list too large)")
            self.refs.append(None)
            logger.debug("reserved reference with idx %d" % lr)
            return lr
        return 0

    def r_ref_insert(self, idx, obj):
        if self.flags[-1]:
            bef = self.refs[idx]
            logger.debug("inserted reference at idx %d" % idx)
            logger.debug("reference at idx %d before: %s and after: %s" % (idx, bef, obj))
            self.refs[idx] = obj
            return self.refs[idx]

    def r_byte(self):
        return self._read(1)

    def r_short(self):
        a, b = tuple(self._read(2))
        x = a | (b << 8)
        # sign extension in case short greater than 16 bits
        # XXX double check
        x |= -(x & 0x80000)
        return x

    def r_long(self):
        a, b, c, d = tuple(self._read(4))
        x = a | (b<<8) | (c<<16) | (d<<24)
        if d & 0x80 and x > 0:
            x = -((1<<32) - x)
            return int(x)
        else:
            return x

    def r_ref(self, obj):
        if self.flags[-1] == 0:
            logger.debug("not adding reference to object %s" % (obj,))
            return obj
        logger.debug("adding reference %d to object %s" % (len(self.refs), obj))
        self.refs.append(obj)
        return obj
    
    def r_object(self):
        code = ord(self.r_byte())
        co_flag = (code & FLAG_REF) & 0xff
        co_type = chr((code & ~FLAG_REF) & 0xff)
        retval = None

        self.depth += 1
        self.flags.append(co_flag)
        if self.depth > MAX_MARSHAL_STACK_DEPTH:
            raise Exception("max marshal stack depth exceeded")

        try:
            fn, _type = self.dispatch[co_type]
            logger.debug("dispatching %c (%d) to %s" % (co_type, ord(co_type), _type))
            retval = fn(self)
        except KeyError:
            raise ValueError("invalid marshal code: %c (%d)" % (co_type, ord(co_type)))
        self.flags = self.flags[:-1]

        self.depth -= 1
        return retval

    def load_null(self):
        return _NULL

    def load_none(self):
        return None

    def load_true(self):
        return True

    def load_false(self):
        return False

    def load_stopiter(self):
        return StopIteration

    def load_ellipsis(self):
        return Ellipsis

    @R_REF
    def load_int(self):
        return self.r_long()

    @R_REF
    def load_int64(self):
        retval = self.r_long64()
        return retval

    @R_REF
    def load_float(self):
        n = ord(self.r_byte())
        s = self.r_string(n)
        return float(s)

    @R_REF
    def load_binary_float(self):
        buf = self.r_string(8)
        d, = struct.unpack("@d", buf)
        return float(d)

    @R_REF
    def load_complex(self):
        n = ord(self._read(1))
        real = float(self.r_string(n))
        n = ord(self._read(1))
        imag = float(self.r_string(n))
        return complex(real, imag)

    @R_REF
    def load_binary_complex(self):
        buf = self.r_string(8)
        real, = struct.unpack("@d", buf)
        buf = self.r_string(8)
        imag, = struct.unpack("@d", buf)
        return complex(real, imag)

    @R_REF
    def load_long(self):
        # XXX in reality r_PyLong() has somewhat dynamic sizes based on
        # marshal_base and marshal_shift; this implementation is kinda
        # wonky and partially based on the PyPy marshal.py module
        n = self.r_long()
        if n == 0:
            return long(0)
        sign = 1
        if n < 0:
            sign = -1
            n = -n
        if n > SIZE32_MAX: # int_32_max
            raise Exception("bad marshal data: long size out of range")
        x = 0
        for i in range(n):
            d = self.r_short()
            x = x | (d<<(i*15))
        return x * sign

    def r_string(self, n):
        return self._read(n)

    @R_REF
    def load_string(self):
        n = self.r_long()
        return self.r_string(n)

    def load_interned(self):
        return self.load_unicode(True)

    def load_ref(self):
        n = self.r_long()
        if n < 0 or n >= len(self.refs):
            raise Exception("bad marshal data (invalid reference: %d)", n)
        logger.debug("loading reference %d" % n)
        obj = self.refs[n]
        if obj is not None:
            return obj
        raise Exception("bad marshal data (invalid reference: %d)", n)

    @R_REF
    def load_tuple(self):
        n = self.r_long()
        l = []
        for _ in range(n):
            l.append(self.r_object())
        return tuple(l.copy())

    @R_REF
    def load_list(self):
        raise NotImplementedError

    @R_REF
    def load_dict(self):
        raise NotImplementedError

    def load_code(self):
        idx = self.r_ref_reserve()

        argcount = self.r_long()
        kwonlyargcount = self.r_long()
        nlocals = self.r_long()
        stacksize = self.r_long()
        flags = self.r_long()
        code = self.load()
        consts = self.load()
        names = self.load()
        varnames = self.load()
        freevars = self.load()
        cellvars = self.load()
        filename = self.load()
        name = self.load()
        firstlineno = self.r_long()
        lnotab = self.r_object()
        retval = types.CodeType(argcount, kwonlyargcount, nlocals, stacksize,
                flags, code, consts, names, varnames,
                filename, name, firstlineno, lnotab, freevars, cellvars)

        self.r_ref_insert(idx, retval)
        return retval

    @R_REF
    def load_unicode(self, interned=False):
        n = self.r_long()
        if n < 0 or n > SIZE32_MAX:
            raise Exception("bad marshal data (string size out of range)")
        s = self.r_string(n)
        retval = s.decode('utf8', "surrogatepass")
        if interned:
            retval = sys.intern(retval)
        return retval

    def load_unknown(self):
        raise NotImplementedError

    @R_REF
    def load_set(self):
        n = self.r_long()
        if n < 0 or n > SIZE32_MAX:
            raise Exception("bad marshal data (set size out of range")
        s = set()
        for _ in range(n):
            s.append(self.r_object())
        return s.copy()

    def load_frozenset(self):
        n = self.r_long()
        if n < 0 or n > SIZE32_MAX:
            raise Exception("bad marshal data (set size out of range")
        if n == 0:
            return self.r_ref(frozenset())
        idx = self.r_ref_reserve()
        if idx < 0:
            raise Exception("bad marshal data (cannot reserve reference)")
        l = []
        for _ in range(n):
            l.append(self.r_object())
        retval = frozenset(l.copy())
        retval = self.r_ref_insert(idx, retval)
        return retval

    @R_REF
    def load_ascii(self, interned=False):
        n = self.r_long()
        if n < 0 or n > SIZE32_MAX:
            raise Exception("bad marshal data (string size out of range)")
        v = self.r_string(n)
        retval = v.decode("utf-8")
        if interned:
            retval = sys.intern(retval)
        return retval

    # doesn't need @R_REF as it's handled by load_ascii
    def load_ascii_interned(self):
        return self.load_ascii(True)

    def load_small_tuple(self):
        n = ord(self.r_byte())
        l = []
        idx = self.r_ref_reserve()
        for _ in range(n):
            l.append(self.r_object())
        retval = tuple(l)
        self.r_ref_insert(idx, retval)
        return retval

    @R_REF
    def load_short_ascii(self, interned=False):
        n = ord(self.r_byte())
        if n < 0 or n > 255:
            raise Exception("bad marshal data (string size out of range)")
        v = self.r_string(n)
        # XXX is UTF-8 the right choice here?
        retval = v.decode("utf-8")
        if interned:
            retval = sys.intern(retval)
        return retval

    # doesn't need @R_REF as it's handled by load_short_ascii
    def load_short_ascii_interned(self):
        return self.load_short_ascii(interned=True)



if __name__ == "__main__":
    # setup logging to stdout and turn DEBUG level logging on
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    if len(sys.argv) != 2:
        raise Exception("expected argument of PYC file to unmarshal")

    with open(sys.argv[1], "rb") as fd:
        fd.read(16)
        u = Unmarshaller(fd.read)
        obj = u.load()

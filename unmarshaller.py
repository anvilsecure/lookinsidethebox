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


# taken from Python-3.6.8/Lib/test/test_code.py
def isinterned(s):
    return s is sys.intern(('_' + s + '_')[1:-1])


def _chr(c):
    return struct.pack("B", c)


class Marshaller:
    def __init__(self, writefunc, buf=None):
        self._write = writefunc
        self._buf = buf

        # dynamically create the dispatcher by finding all
        # globals that start with TYPE_ and then mapping
        # them to associated methods in this class
        types = [x for x in globals() if x.startswith("TYPE_")]
        dispatch = {}
        for _type in types:
            attrname = "dump_%s" % (_type[5:].lower())
            dispatch[globals()[_type]] = (getattr(Marshaller, attrname), _type)

        self.depth = 0
        self.dispatch = dispatch
        self.entries = []
        self.flags = []

    def w_long(self, l):
        # this is dirty but too lazy to deal with the different corner cases or
        # write it myself
        try:
            self._write(struct.pack("<l", l))
        except Exception:
            self._write(struct.pack("<L", l))

    def w_short(self, s):
        self._write(struct.pack("<H", s))

    def w_ref(self, obj):
        if obj in self.entries[-1]:
            idx = self.entries[-1].index(obj)
            self.w_byte(TYPE_REF)
            self.w_long(idx)
            return True
        else:
            self.entries[-1].append(obj)
            self.flags[-1] = self.flags[-1] | FLAG_REF
            return False

    def w_object(self, obj):

        self.entries.append([])
        self.flags.append(0)
        self.depth += 1
        if self.depth > MAX_MARSHAL_STACK_DEPTH:
            raise Exception("max marshal stack depth exceeded")

        otype = type(obj)
        if obj is None:
            self.dump_none(obj)
        elif otype == bool:
            if obj is True:
                self.dump_true()
            else:
                self.dump_false()
        elif obj == StopIteration:
            self.dump_stopiter(obj)
        elif obj == Ellipsis:
            self.dump_ellipsis(obj)

        # We are now in 'complex' object territory as per
        # marshal.c in CPython which means we need to check
        # and insert a reference if we have seen this object
        # before and already outputted it to the stream.

        elif self.w_ref(obj):
            self.depth -= 1
            self.flags = self.flags[:-1]
            self.entries = self.entries[:-1]
            return

        elif isinstance(otype, types.CodeType):
            # XXX this is the only one we use the dispatch for so the other
            # ones cannot be overridden as easily
            fn, _type = self.dispatch[TYPE_CODE]
            fn(self, obj)
        elif otype == bytes:
            self.dump_bytes(obj)
        elif otype == int:
            self.dump_int(obj)
        elif otype == tuple:
            if len(obj) < 256:
                self.dump_small_tuple(obj)
            else:
                self.dump_tuple(obj)
        elif otype == bytes:
            self.dump_string(obj)
        elif otype == str:
            try:
                enc = obj.encode("ascii")
                is_ascii = True
            except UnicodeEncodeError:
                is_ascii = False
            if is_ascii:
                if len(enc) < 256:
                    if isinterned(obj):
                        self.dump_short_ascii_interned(enc)
                    else:
                        self.dump_short_ascii(enc)
                else:
                    if isinterned(obj):
                        self.dump_ascii_interned(enc)
                    else:
                        self.dump_ascii(enc)
            else:
                if isinterned(obj):
                    self.dump_interned(obj)
                else:
                    self.dump_unicode(obj)
        elif otype == float:
            self.dump_binary_float(obj)
        elif otype == complex:
            self.dump_binary_complex(obj)
        else:
            raise NotImplementedError

        self.depth -= 1
        self.flags = self.flags[:-1]
        self.entries = self.entries[:-1]

    def w_byte(self, b):
        if type(b) == str:
            tmp = b.encode("utf-8")
            assert(len(tmp) == 1)
            self._write(tmp)
        else:
            self._write(b)

    def w_type(self, t):
        self.w_byte(_chr(ord(t) | self.flags[-1]))

    def w_size(self, i):
        if i > SIZE32_MAX:
            raise Exception("size too big")
        self.w_long(i)

    def dump_bytes(self, obj):
        # `W_TYPE(TYPE_STRING, p);
        # w_pstring(PyBytes_AS_STRING(v), PyBytes_GET_SIZE(v), p);
        self.w_type(TYPE_STRING)
        self.w_size(len(obj))
        self._write(obj)

    def dump_null(self, obj):
        self.w_byte(TYPE_NULL)

    def dump_none(self, obj):
        self.w_byte(TYPE_NONE)

    def dump_false(self):
        self.w_byte(TYPE_FALSE)

    def dump_true(self):
        self.w_byte(TYPE_TRUE)

    def dump_stopiter(self, obj):
        self.w_byte(TYPE_STOPITER)

    def dump_ellipsis(self, obj):
        self.w_byte(TYPE_ELLIPSIS)

    def w_pylong(self, x):
        self.w_type(TYPE_LONG)
        sign = 1
        if x < 0:
            sign = -1
            x = -x
        digits = []
        while x:
            digits.append(x & 0x7FFF)
            x = x >> 15
        self.w_long(len(digits)*sign)
        for d in digits:
            self.w_short(d)

    def dump_int(self, obj):

        y = obj >> 31
        if y and y != -1:
            self.w_pylong(obj)
        else:
            self.w_type(TYPE_INT)
            self.w_long(obj)

    def dump_int64(self, obj):
        raise NotImplementedError

    def dump_binary_float(self, obj):
        self.w_type(TYPE_BINARY_FLOAT)
        buf = struct.pack("<d", obj)
        self._write(buf)

    def dump_float(self, obj):
        raise NotImplementedError

    def dump_complex(self, obj):
        raise NotImplementedError

    def dump_binary_complex(self, obj):
        self.w_type(TYPE_BINARY_COMPLEX)
        self._write(struct.pack("<d", obj.real))
        self._write(struct.pack("<d", obj.imag))

    def dump_long(self, obj):
        raise NotImplementedError

    def dump_string(self, obj):
        self.dump_bytes(obj.encode("utf-8"))

    def dump_interned(self, obj):
        self.w_type(TYPE_INTERNED)
        enc = obj.encode("utf8", errors="surrogatepass")
        self.w_size(len(enc))
        self._write(enc)

    def dump_ref(self, obj):
        raise NotImplementedError

    def dump_tuple(self, obj):
        self.w_type(TYPE_TUPLE)
        self.w_size(len(obj))
        for tuple_obj in obj:
            self.w_object(tuple_obj)

    def dump_list(self, obj):
        raise NotImplementedError

    def dump_dict(self, obj):
        raise NotImplementedError

    def dump_code(self, co):
        self.w_type(TYPE_CODE)
        self.w_long(co.co_argcount)
        self.w_long(co.co_kwonlyargcount)
        self.w_long(co.co_nlocals)
        self.w_long(co.co_stacksize)
        self.w_long(co.co_flags)
        self.w_object(co.co_code)
        self.w_object(co.co_consts)
        self.w_object(co.co_names)
        self.w_object(co.co_varnames)
        self.w_object(co.co_freevars)
        self.w_object(co.co_cellvars)
        self.w_object(co.co_filename)
        self.w_object(co.co_name)
        self.w_long(co.co_firstlineno)
        self.w_object(co.co_lnotab)

    def dump_unicode(self, obj):
        self.w_type(TYPE_UNICODE)
        enc = obj.encode("utf8", errors="surrogatepass")
        self.w_size(len(enc))
        self._write(enc)

    def dump_unknown(self, obj):
        raise NotImplementedError

    def dump_set(self, obj):
        raise NotImplementedError

    def dump_frozenset(self, obj):
        raise NotImplementedError

    def dump_ascii(self, enc):
        self.w_type(TYPE_ASCII)
        self.w_size(len(enc))
        self._write(enc)

    def dump_ascii_interned(self, enc):
        self.w_type(TYPE_ASCII_INTERNED)
        self.w_size(len(enc))
        self._write(enc)

    def dump_small_tuple(self, obj):
        self.w_type(TYPE_SMALL_TUPLE)
        self.w_byte(_chr(len(obj)))
        for tuple_obj in obj:
            self.w_object(tuple_obj)

    def dump_short_ascii(self, enc):
        self.w_type(TYPE_SHORT_ASCII)
        self.w_byte(_chr(len(enc)))
        self._write(enc)

    def dump_short_ascii_interned(self, enc):
        self.w_type(TYPE_SHORT_ASCII_INTERNED)
        self.w_byte(_chr(len(enc)))
        self._write(enc)

    def dump(self, obj):
        self.w_object(obj)


class Unmarshaller:

    def __init__(self, readfunc):
        self._read = readfunc

        # dynamically create the dispatcher by finding all
        # globals that start with TYPE_ and then mapping
        # them to associated methods in this class
        types = [x for x in globals() if x.startswith("TYPE_")]
        dispatch = {}
        for _type in types:
            attrname = "load_%s" % (_type[5:].lower())
            dispatch[globals()[_type]] = (getattr(Unmarshaller, attrname),
                                          _type)

        self.dispatch = dispatch
        self._opcode_mapping = None
        self.depth = 0
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
            logger.debug("reference at idx %d before: %s and after: %s" %
                         (idx, bef, obj))
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
        x = a | (b << 8) | (c << 16) | (d << 24)
        if d & 0x80 and x > 0:
            x = -((1 << 32) - x)
            return int(x)
        else:
            return x

    def r_ref(self, obj):
        if self.flags[-1] == 0:
            logger.debug("not adding reference to object %s" % (obj,))
            return obj
        logger.debug("adding reference %d to object %s" %
                     (len(self.refs), obj))
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
            logger.debug("dispatching %c (%d) to %s" %
                         (co_type, ord(co_type), _type))
            retval = fn(self)
        except KeyError:
            raise ValueError("invalid marshal code: %c (%d)" %
                             (co_type, ord(co_type)))
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
            return 0
        sign = 1
        if n < 0:
            sign = -1
            n = -n
        if n > SIZE32_MAX:
            raise Exception("bad marshal data: long size out of range")
        x = 0
        for i in range(n):
            d = self.r_short()
            x = x | (d << (i*15))
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
            raise Exception("bad marshal data (invalid reference: %d)" % n)
        logger.debug("loading reference %d" % n)
        obj = self.refs[n]
        if obj is not None:
            return obj
        raise Exception("bad marshal data (invalid reference: %d)" % n)

    @R_REF
    def load_tuple(self):
        n = self.r_long()
        l2 = []
        for _ in range(n):
            l2.append(self.r_object())
        return tuple(l2.copy())

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
                                filename, name, firstlineno, lnotab, freevars,
                                cellvars)

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
        l2 = []
        for _ in range(n):
            l2.append(self.r_object())
        retval = frozenset(l2.copy())
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
        l2 = []
        idx = self.r_ref_reserve()
        for _ in range(n):
            l2.append(self.r_object())
        retval = tuple(l2)
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
    root.setLevel(logging.ERROR)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    if len(sys.argv) != 2:
        raise Exception("expected argument of PYC file to unmarshal")

    with open(sys.argv[1], "rb") as fd:
        hdr = fd.read(12)
        u = Unmarshaller(fd.read)
        obj = u.load()
        import marshal
        import io
        with io.BytesIO() as out:
            out.write(hdr)
            m = Marshaller(out.write)
            m.dump(obj)

            out.flush()
            out.seek(0)

            out.read(len(hdr))
            u3 = Unmarshaller(out.read)
            obj3 = u3.load()

            marshal.loads(out.getbuffer()[len(hdr):])
            sys.stdout.write(".")

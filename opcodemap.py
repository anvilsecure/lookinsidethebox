import logging
import pickle
import types


logger = logging.getLogger(__name__)


class OpcodeMapping:
    # before using always need to call sanitize()
    def __init__(self, fn, overwrite=False):
        self.fn = fn
        self.table = {}
        self.map = {}
        self.co_len_mismatch = 0
        self.co_matched = 0
        self.loaded_from_fs = False
        self.overwrite = overwrite
        self.missing = {}

    def __enter__(self):
        logger.debug("__enter__ opcodemapping")
        try:
            with open(self.fn, "rb") as fd:
                data = pickle.load(fd)
        except Exception:
            return self
        self.loaded_from_fs = True
        self.table = data
        return self

    def __exit__(self, extype, exvalue, traceback):
        if not self.overwrite and self.loaded_from_fs:
            # if caller didn't specify a force overwrite and this opcode
            # mapping was loaded from the filesystem don't do anything
            logger.warning("NOT writing opcode map as force overwrite not set")
            return

        logger.warning("stats: co_len_mismatch=%i, co_matched=%i" %
                       (self.co_len_mismatch, self.co_matched))

        logger.warning("opcode map database is being sanitized and written")
        self.sanitize()
        with open(self.fn, "wb") as fd:
            pickle.dump(self.table, fd)

    def _map_co_objects(self, a, b):
        if len(a.co_code) != len(b.co_code):
            self.co_len_mismatch += 1
            return
        n = 0
        for i, j in zip(a.co_code, b.co_code):
            n += 1
            if n % 2 == 0:
                continue
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

    def get(self, op):
        if op not in self.table:
            self.missing[op] = self.missing.get(op, 0) + 1
        op_new = self.table.get(op, op)
        return op_new

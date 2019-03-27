#!/usr/bin/env python2

"""

gvb@santarago.org
"""

import struct
import types
import zipfile
import os.path
import marshal
import StringIO
import sys
import _marshal
import pickle

from uncompyle2 import uncompyle, magics

missing = {}


def rng(a, b):
	b = ((b << 13) ^ b) & 0xffffffff
	c = (b ^ (b >> 17))
	c = (c ^ (c << 5))
	return (a * 69069 + c + 0x6611CB3B) & 0xffffffff

def MX(z,y,sum,key,p,e):
    return (((z>>5^y<<2) + (y>>3^z<<4)) ^ ((sum^y) + (key[(p&3)^e] ^ z)))

def tea_decipher(v,key):
    DELTA = 0x9e3779b9
    n = len(v)
    rounds = 6 + 52//n
    sum = (rounds*DELTA)
    y = v[0]
    while sum != 0:
        e = (sum >> 2) & 3
        for p in xrange(n-1, -1, -1):
            z = v[(n+p-1)%n]
            v[p] = (v[p] - MX(z,y,sum,key,p,e)) & 0xffffffff
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

def load_code_without_patching(self):
	code = load_code(self)
	return types.CodeType(code.co_argcount, code.co_nlocals, code.co_stacksize,
		code.co_flags, code.co_code, code.co_consts,
		code.co_names, code.co_varnames, code.co_filename,
		code.co_name, code.co_firstlineno, code.co_lnotab,
		code.co_freevars, code.co_cellvars)

def load_code_with_patching(self):
	code = load_code(self)
	bcode = bytearray(code.co_code)
	i = 0
	n = len(bcode)
	while i < n:
		op = bcode[i]
		if not op in opcode_mapping:
			missing[op] = missing.get(op, 0) + 1
		bcode[i] = opcode_mapping.get(op, op)
		i = i + 1
		if opcode_mapping.get(op, op) >= 90: # HAVE_ARGUMENT
			i = i + 2
	patched_code = str(bcode)
	return types.CodeType(code.co_argcount, code.co_nlocals, code.co_stacksize,
		code.co_flags, patched_code, code.co_consts,
		code.co_names, code.co_varnames, code.co_filename,
		code.co_name, code.co_firstlineno, code.co_lnotab,
		code.co_freevars, code.co_cellvars)

def load_code(self):
	rand = _marshal._r_long(self)
	length = _marshal._r_long(self)

	seed = rng(rand, length)
	mt = MT19937(seed)
	key = []
	for i in range(0, 4):
		key.append(mt.extract_number())

	off = self.bufpos
	padding = (length + 15) & ~0xf
	words = padding / 4
	
	# convert data to list of dwords
	data = list(struct.unpack("<%dL" % words, self.bufstr[off:off+padding]))

	# decrypt and convert back to stream of bytes
	data = tea_decipher(data, key)
	data = struct.pack("<%dL" % words, *data)
	self.bufpos = self.bufpos + padding

	obj = _marshal._FastUnmarshaller(data)
	return obj.load_code()

opcode_mapping = {}

def fill_opcode_mapping(c, d):
	if len(c.co_code) != len(d.co_code):
		return
	for i, j in zip(c.co_code, d.co_code):
		v = opcode_mapping.setdefault(i, {})
		v[j] = v.get(j, 0) + 1

def decrypt_and_patch_pycfile(zf, pycfile):
	_marshal._FastUnmarshaller.dispatch[_marshal.TYPE_CODE] = load_code_with_patching
	f = zf.open(pycfile, "r")
	data = f.read()
	f.close()
	try:
		c = _marshal.loads(data[8:])
	except Exception, e:
		return str(e)
	return c

def decompile(co):
	version = magics.versions["\x03\xf3\r\n"]
	s = StringIO.StringIO()
	try:
		uncompyle(version, co, s, showasm=0, showast=0)
		ret = s.getvalue()
	except Exception, e:
		return str(e)
	return ret

def decrypt_pycfile(zf, pycfile, dirname):
	_marshal._FastUnmarshaller.dispatch[_marshal.TYPE_CODE] = load_code_without_patching
	f = zf.open(pycfile, "r")
	data = f.read()
	f.close()

	# try to find matching python .pyo file for automatic
	# opcode mapping if possible
	domapping = False
	libfile = "%s/%s" % (dirname, pycfile)
	libfile = libfile[:-1] + "o"
	try:
		st = os.stat(libfile)
		lf = open(libfile, "rb")
		lfdata = lf.read()
		lf.close()
		d = marshal.loads(lfdata[8:])			
		domapping = True
	except Exception, e:
		return

	if not domapping:
		return

	try:
		c = _marshal.loads(data[8:])
	except Exception, e:
		return

	fill_opcode_mapping(c, d)
	codes_c = filter(lambda x: type(x) == type(c), c.co_consts)
	codes_d = filter(lambda x: type(x) == type(d), d.co_consts)
	for i, j in zip(codes_c, codes_d):
		fill_opcode_mapping(i, j)

if __name__ != "__main__":
	raise Exception("don't import this file")

if len(sys.argv) != 4:
	print "Usage: %s <dropbox binary> <python dir> <output.zip>" % sys.argv[0]
	sys.exit(1)

fn = sys.argv[1]
dirname = sys.argv[2]
outputfn = sys.argv[3]
opcodedb = "opcode.db"

zf = zipfile.PyZipFile(fn, "r", zipfile.ZIP_DEFLATED)
pycfiles = zf.namelist()
#dirname = "./python/Python-2.7.10/Lib/"

opcode_mapping = {}
try:
	opcode_mapping = pickle.loads(open(opcodedb, "r").read())
	print "pass one: load saved opcode mapping from disk"
except:
	print "no saved opcode mapping found; try to generate it"
	print "pass one: automatically generate opcode mapping"
	done = 1
	for pycfile in pycfiles:
		print "%i/%i\r" % (done,len(pycfiles)),
		sys.stdout.flush()
		if pycfile[-3:] != "pyc":
			continue
		try:
			decrypt_pycfile(zf, pycfile, dirname)
		except Exception, e:
			print e
			pass
		done = done + 1

	print ""
	print "sanitizing reconstructed opcode map: ",
	k = sorted(opcode_mapping.keys())
	table = {}
	for i in k:
		maxcount = 0
		for j,count in opcode_mapping[i].iteritems():
			if j == i: continue
			if maxcount < count:
				maxcount = count
				table[ord(i)] = ord(j)
	opcode_mapping = table
	open(opcodedb, "w").write(pickle.dumps(opcode_mapping))

print "%i opcodes" % len(opcode_mapping)

print "pass two: decrypt files, patch bytecode and decompile"

success = 0
error_decrypt = 0
error_decompile = 0

outzip = zipfile.PyZipFile(outputfn, "w", zipfile.ZIP_DEFLATED)
done = 1
for pycfile in pycfiles:
	print "%i/%i\r" % (done,len(pycfiles)),
	sys.stdout.flush()
	if pycfile[-3:] != "pyc":
		done = done + 1
		continue

	co = None
	pyfile = None
	try:
		co = decrypt_and_patch_pycfile(zf, pycfile)
	except Exception, e:
		error_decrypt = error_decrypt + 1
	if not co:
		pyfile = "error while decrypting and patching %s\n" % (pycfile)
	else:
		try:
			pyfile = decompile(co)
			if not pyfile:
				raise Exception("decompile failed")
			success = success + 1
		except Exception, e:
			pyfile = "error while decompiling %s\n%s" % (pycfile, e)
			error_decompile = error_decompile + 1
	outzip.writestr(pycfile[:-1], pyfile)
	done = done + 1

outzip.close()
zf.close()

print ""
print "successfully decrypted and decompiled: %i files" % success
print "error while decrypting: %i files" % error_decrypt
print "error while decompiling: %i files" % error_decompile
print "opcode misses: %i total" % len(missing),
for i in missing:
	print "0x%2x (%i) [#%i], " % (i, i, missing[i]),
print ""

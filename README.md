Lookinsidethebox
================

This tool is just the latest implementation that breaks the encryption and obfuscation layers that Dropbox applies to their modified Python interpreter. It's based on work the author did many, many moons ago as well as public work done by others. For more information please see the blogpost at: XXX


# Requirements

- Have a recent Python 3.x installation for the unpacking.
- Make sure that `uncompyle6` is installed. You can do this with:
```
pip3 install uncompyle6
```
- For regenerating the opcode database make sure that the Python version installed is **3.6**. Please note that there's already a version of this opcode database mapping included so it shouldn't be necessary to rerun it.



# Usage

- Run the included `fetchdeps.sh` bash script. This will fetch the Python source code as well as download the latest version of the Dropbox for Linux tarball. The Python source code is only needed if one wants to regenerate the opcode database.

- Execute the following to unpack, decrypt and decompile most of the Dropbox Python source code. It will extract to a default directory named `out`:
```
python3 unpacker.py --dropbox-zip `find ./tmp -type f -iname python-packages-36.zip`
```

- To regenerate the opcode mapping database use something like this. Please note that Python 3.6 is a requirement for this to work.

```
/usr/bin/env python3.6 gendb.py --dropbox-zip `find ./tmp -type f -iname python-packages-36.zip` --python-dir tmp/Python-3.6.8/Lib/ --db opcode.db
```

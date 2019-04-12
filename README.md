empty readme

# Requirements

- Have a recent Python 3.x installation for the unpacking.
- Make sure that `uncompyle6` is installed. You can do this with:

```
pip3 install uncompyle6
```.

- For regenerating the opcode database make sure that the Python version installed is 3.6. Please note that there's already a version of this opcode database included so it shouldn't be necessary.



# Usage

- Run the included `fetchdeps.sh` bash script. This will fetch the Python source code as well as download the latest version of the Dropbox for Linux tarball.

- 

python3 unpacker.py --dropbox-zip `find ./tmp -type f -iname python-packages-36.zip` --output-file bl

To generate the opcode database use something like the following:

```
/usr/bin/env python3.6 gendb.py --dropbox-zip tmp/dropbox-dist/dropbox-lnx.x86_64-70.4.93/python-packages-36.zip --python-dir tmp/Python-3.6.8/Lib/ --db opcode.db
```

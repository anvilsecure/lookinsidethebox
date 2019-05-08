Look inside the box
================

This tool is just the latest implementation that breaks the encryption and obfuscation layers that Dropbox applies to their modified Python interpreter. It's based on work the author did many, many moons ago as well as public work done by others. For more information please see the [blogpost](http://anvilventures.com/blog/looking-inside-the-box.html).

All this assumes that current versions of the Dropbox Linux client keep being based on Python 3.6. Otherwise work might have to be done to change this to Python 3.7 by adjusting the commands. Of course if Dropbox changes their encryption and obfuscation schemes one will be out of luck too and more work will have to be done to get all this working again.


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
python3 unpacker.py --dropbox-zip `find . -name python-packages-36.zip`
```

- To regenerate the opcode mapping database use something like this. Please note that _Python 3.6 is a requirement_ for this to work.

```
python3.6 gendb.py --dropbox-zip `find . -name python-packages-36.zip` --python-dir tmp/Python-3.6.8 --db opcode.db
```

- To patch the ZIP file in the Dropbox distribution and rewrite the pyc files such that the SHA-256 hashes in there are known SHA-256 hashes use the following to rewrite and inject code into the zip.

```
python3 patchzip.py --dropbox-zip `find . -name python-packages-36.zip` --output-zip out.zip
mv out.zip ~/.dropbox-dist/dropbox-lnx_64-71.4.108/python-packages-36.zip
~/.dropbox-dist/dropbox-lnx_64-71.4.108/dropbox
```

- To set the environment variables to enable hidden Dropbox functionality see the `setenv.py` script. For more information on this please see the [blogpost](http://anvilventures.com/blog/looking-inside-the-box.html) again. Modify at will and then use it like this to setup the environment and run dropbox.

```
eval `python3 setenv.py`
~/.dropbox-dist/dropbox-lnx_64-71.4.108/dropbox
```

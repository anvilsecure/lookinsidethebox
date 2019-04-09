#!/bin/sh

PYTHON="/usr/bin/env python3.6"
PYVER="3.6.8"
TMPDIR="./tmp"

# try to find wget or curl
FETCH=$(which wget)
if [ -z "$FETCH" ]; then
	FETCH=$(which curl)
	if [ -z "$FETCH" ]; then
		echo "cannot find wget or curl to fetch data";
		exit 1;
	fi
	FETCH="curl -L"
else
	FETCH="wget -O -"
fi

if [ ! -d $TMPDIR ]; then
	mkdir -p $TMPDIR
fi

cd $TMPDIR

if [ ! -d "dropbox-dist" ]; then
	$FETCH "https://www.dropbox.com/download?plat=lnx.x86_64" | tar xzf -
	mv .dropbox-dist dropbox-dist
fi

if [ ! -d "Python-$PYVER" ]; then
	$FETCH "https://www.python.org/ftp/python/$PYVER/Python-$PYVER.tar.xz" | tar -xJf -
	$PYTHON -O -m compileall Python-$PYVER/Lib
	$PYTHON -OO -m compileall Python-$PYVER/Lib
	$PYTHON -m compileall Python-$PYVER/Lib
fi

if [ ! -d "uncompyle2" ]; then
	git clone https://github.com/wibiti/uncompyle2.git
	mv uncompyle2 _uncompyle2
	mv _uncompyle2/uncompyle2 uncompyle2
fi

echo "\n\n\nfetched all dependencies..lets try decompiling\n\n\n"

cd -

CMD="$PYTHON ./unpacker.py --python-dir $TMPDIR/Python-$PYVER/Lib"
CMD="$CMD --dropbox-zip `find $TMPDIR/dropbox-dist/ -type f -iname \"python-packages*.zip\"`"
CMD="$CMD --output-file output.zip"

echo $CMD
$CMD

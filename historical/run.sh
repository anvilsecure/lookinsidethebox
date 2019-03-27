#!/bin/sh

WGET="wget -O -"
WGET="curl -L"
PYTHON="/usr/bin/env python2"

if [ ! -d "dropbox-dist" ]; then
	$WGET "https://www.dropbox.com/download?plat=lnx.x86_64" | tar xzf -
	mv .dropbox-dist dropbox-dist
fi

if [ ! -d "Python-2.7.10" ]; then
	$WGET "https://www.python.org/ftp/python/2.7.10/Python-2.7.10.tar.xz" | tar -xJf -
	$PYTHON -O -m compileall ./Python-2.7.10/Lib
fi

if [ ! -d "uncompyle2" ]; then
	git clone https://github.com/wibiti/uncompyle2.git
	mv uncompyle2 _uncompyle2
	mv _uncompyle2/uncompyle2 uncompyle2
fi

echo "\n\n\nfetched all dependencies..lets try decompiling\n\n\n"

$PYTHON ./unpacker.py `find dropbox-dist/ -type f -iname "python-packages-36*.zip"` ./Python-2.7.10/Lib output.zip

#!/bin/sh

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
fi

cd ..

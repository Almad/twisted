#!c:\python23\python.exe

# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.



### Twisted Preamble
# This makes sure that users don't have to set up their environment
# specially in order to run these programs from bin/.
from twisted.application import app
app.reactorTypes['iocp'] = 'proactor'
import sys, os, string
if string.find(os.path.abspath(sys.argv[0]), os.sep+'Twisted') != -1:
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]), os.pardir, os.pardir)))
if hasattr(os, "getuid") and os.getuid() != 0:
    sys.path.insert(0, os.curdir)
### end of preamble

from twisted.python.runtime import platformType
if platformType == "win32":
    from twisted.scripts._twistw import run
else:
    from twisted.scripts.twistd import run

run()

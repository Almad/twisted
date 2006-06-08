##
# Copyright (c) 2005 Apple Computer, Inc. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# DRI: Wilfredo Sanchez, wsanchez@apple.com
##

from twisted.trial.unittest import SkipTest
from twisted.web2.iweb import IResponse
from twisted.web2.stream import MemoryStream
from twisted.web2 import responsecode

import twisted.web2.dav.test.util
from twisted.web2.test.test_server import SimpleRequest
from twisted.web2.dav import davxml

class REPORT_expand(twisted.web2.dav.test.util.TestCase):
    """
    DAV:expand-property REPORT request
    """
    def test_REPORT_expand_property(self):
        """
        DAV:expand-property REPORT request.
        """
        raise SkipTest("test unimplemeted")

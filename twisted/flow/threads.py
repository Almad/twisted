# Twisted, the Framework of Your Internet
# Copyright (C) 2003 Matthew W. Lefkowitz
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of version 2.1 of the GNU Lesser General
# Public License as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307
# USA
#
# Author: Clark Evans  (cce@clarkevans.com)
#

""" flow.thread 

    Support for threads within a flow
"""

from base import *
from twisted.python.failure import Failure
from twisted.internet import reactor
from time import sleep

class Threaded(Stage):
    """ A stage which runs a blocking iterable in a separate thread

        This stage tunnels output from an iterable executed in a separate
        thread to the main thread.   This process is carried out by 
        a result buffer, and returning Cooperate if the buffer is
        empty.   The wrapped iterable's __iter__ and next() methods
        will only be invoked in the spawned thread.

        This can be used in one of two ways, first, it can be 
        extended via inheritance; with the functionality of the
        inherited code implementing next(), and using init() for
        initialization code to be run in the thread.

        If the iterable happens to have a chunked attribute, and
        that attribute is true, then this wrapper will assume that
        data arrives in chunks via a sequence instead of by values.

            def runInThread(cnt):
                while cnt > 0:
                   from time import sleep
                   sleep(.1)
                   yield cnt
                   cnt -= 1
            
            def howdy():
                print "howdy"
            
            source = flow.Threaded(runInThread(8))
            reactor.callLater(.3,howdy)
            printFlow(source)
            
    """
    class Instruction(CallLater):
        def __init__(self):
            self.flow = None
            self.final = False
        def callLater(self, callable):
            if self.final:
                reactor.callLater(0,callable)
            else:
                self.flow = callable
        def __call__(self, final = False):
            if self.flow:
                reactor.callFromThread(self.flow)
                self.flow = None
            self.final = final

    def __init__(self, iterable, *trap):
        Stage.__init__(self, trap)
        self._iterable  = iterable
        self._cooperate = Threaded.Instruction()
        self.srcchunked = getattr(iterable, 'chunked', False)
        reactor.callInThread(self._process)

    def _process(self):
        """ pull values from the iterable and add them to the buffer """
        try:
            self._iterable = iter(self._iterable)
        except: 
            self.failure = Failure()
        else:
            try:
                while True:
                    val = self._iterable.next()
                    if self.srcchunked:
                        self.results.extend(val)
                    else:
                        self.results.append(val)
                    self._cooperate()
            except StopIteration:
                self.stop = True
            except: 
                self.failure = Failure()
        self._cooperate(final=True)

    def _yield(self):
        if self.results or self.stop or self.failure:
            return
        return self._cooperate

class QueryIterator:
    """ Converts a database query into a result iterator
        
        This is particularly useful for executing a query in
        a thread.   TODO: show example here
    """

    def __init__(self, pool, sql, fetchmany=False, fetchall=False):
        self.curs = None
        self.sql = sql
        self.pool = pool
        if fetchmany: 
            self.next = self.next_fetchmany
            self.chunked = True
        if fetchall:
            self.next = self.next_fetchall
            self.chunked = True

    def __iter__(self):
        conn = self.pool.connect()
        self.curs = conn.cursor()
        self.curs.execute(self.sql)
        return self

    def next_fetchall(self):
        if self.curs:
            ret = self.curs.fetchall()
            self.curs = None
            return ret
        raise StopIteration
    
    def next_fetchmany(self):
        ret = self.curs.fetchmany()
        if not ret:
            raise StopIteration
        return ret

    def next(self):
        ret = self.curs.fetchone()
        if not ret: 
            raise StopIteration
        return ret


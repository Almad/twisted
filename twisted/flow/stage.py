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

""" flow.stage 

    Base flow stages for manipulating the stream

"""
from base import *
from wrap import wrap
from twisted.python.failure import Failure

class Filter(Stage):
    """ flow equivalent to filter:  Filter(function, stage, ... )

        Yield those elements from a stage for which a function
        returns true.   If the function is None, the identity 
        function is assumed, that is, all items yielded that are
        false (zero or empty) are discarded.

            def odd(val):
                if val % 2:
                    return True
            
            def range():
                yield 1
                yield 2
                yield 3
                yield 4
            
            source = flow.Filter(odd,range)
            printFlow(source)

    """
    def __init__(self, func, stage, *trap):
        Stage.__init__(self, *trap)
        self.func = func
        self.stage = wrap(stage)

    def _yield(self):
        if self.stop or self.failure:
            return
        stage = self.stage
        while not self.results:
            instruction = stage._yield()
            if instruction:
                return instruction
            self.results.extend(filter(self.func,stage.results))
            stage.results = []
            if stage.stop:
                self.stop = 1
                return
            if stage.failure:
                self.failure = stage.failure
                return

class Map(Stage):
    """ flow equivalent to map:  Map(function, stage, ... )
 
        Apply a function to every item yielded and yield the results.
        If additional stages are passed, the function must take that
        many arguments and is applied to the items of all lists in 
        parallel.  If a list is shorter than another, it is assumed
        to be extended with None items.    If the function is None,
        the identity function is assumed; if there are multiple list
        arguments, Map stage returns a sequence consisting of tuples
        containing the corresponding items from all lists.

            def fn(val):
                return val + 10
            
            source = flow.Map(fn,range(4))
            printFlow(source)
            
    """
    def __init__(self, func, stage, *stages):
        Stage.__init__(self)
        self.func = func
        self._stage  = [wrap(stage)]
        for stage in stages:
            self._stage.append(wrap(stage))
        self._index  = 0

    def _yield(self):
        if self.results or self.stop or self.failure:
            return
        if not self._index:
            self._curr = []
            self._done = True
        while self._index < len(self._stage):
            idx = self._index
            curr = self._stage[idx]
            instruction = curr._yield()
            if instruction:
                return instruction
            if curr.results:
                self._curr.append(curr.results.pop(0))
                self._index += 1
                self._done = False
                continue
            if curr.stop:
                self._curr.append(None)
                self._index += 1
                continue
            if curr.failure:
                self.failure = curr.failure
                return
            raise AssertionError("flow.Map ; no results, stop or failure?")
        if self._done:
            self.stop = 1
            return
        curr = tuple(self._curr)
        if self.func:
            try:
                curr = self.func(*curr)
            except Failure, fail:
                self.failure = fail
                return
            except:
                self.failure = Failure()
                return
        self.results.append(curr)
        self._index  = 0

class Zip(Map):
    """ Zips two or more stages into a stream of N tuples

            source = flow.Zip([1,flow.Cooperate(),2,3],["one","two"])
            printFlow(source)

    """
    def __init__(self, *stages):
        Map.__init__(self, None, stages[0], *stages[1:])

class Concurrent(Stage):
    """ Executes stages concurrently

        This stage allows two or more stages (branches) to be executed 
        at the same time.  It returns each stage as it becomes available.
        This can be used if you have N callbacks, and you want to yield 
        and wait for the first available one that produces results.   Once
        a stage is retuned, its next() method should be used to extract 
        the value for the stage.
    """

    class Instruction(CallLater):
        def __init__(self, inst):
            self.inst = inst
        def callLater(self, callable):
            for inst in self.inst:
                inst.callLater(callable)

    def __init__(self, *stages):
        Stage.__init__(self)
        self._stages = []
        for stage in stages:
            self._stages.append(wrap(stage))

    def _yield(self):
        if self.results or self.stop or self.failure:
            return
        stages = self._stages
        later = []
        exit = None
        while stages:
            if stages[0] is exit:
                if self.results:
                    return
                break
            curr = stages.pop(0)
            instruction = curr._yield()
            if curr.results:
                self.results.append(curr)
            if curr.failure:
                self.failure = curr.failure
                return
            if curr.stop:
                exit = None
                if self.results:
                    return
                continue
            stages.append(curr)
            if not exit:
                exit = curr
            if instruction:
                if isinstance(instruction, CallLater):
                    if instruction not in later:
                        later.append(instruction)
                    continue
                raise Unsupported(instruction)
        if later:
            return Concurrent.Instruction(later)
        self.stop = True

class Merge(Stage):
    """ Merges two or more Stages results into a single stream

            source = flow.Zip([1,flow.Cooperate(),2,3],["one","two"])
            printFlow(source)

    """
    def __init__(self, *stages):
        Stage.__init__(self)
        self.concurrent = Concurrent(*stages)

    def _yield(self):
        if self.results or self.stop or self.failure:
            return
        instruction = self.concurrent._yield()
        if instruction: 
            return instruction
        for stage in self.concurrent.results:
            self.results.extend(stage.results)
            stage.results = []
        self.concurrent.results = []
        if self.concurrent.stop:
            self.stop = True
        self.failure =  self.concurrent.failure

class Callback(Stage):
    """ Converts a single-thread push interface into a pull interface.
   
        Once this stage is constructed, its result, errback, and 
        finish member variables may be called by a producer.   The
        results of which can be obtained by yielding the Callback and
        then calling next().   For example:

            source = flow.Callback()
            reactor.callLater(0, lambda: source.result("one"))
            reactor.callLater(.5, lambda: source.result("two"))
            reactor.callLater(1, lambda: source.finish())
            printFlow(source)

    """
    # TODO: Potentially rename this 'Consumer' and make it
    #       comply with protocols.IConsumer
    # TODO: Make the inverse stage, which is an IProducer
    class Instruction(CallLater):
        def __init__(self):
            self.flow = lambda: True
        def callLater(self, callable):
            self.flow = callable
    def __init__(self, *trap):
        Stage.__init__(self, *trap)
        self._finished   = False
        self._cooperate  = Callback.Instruction()
    def result(self,result):
        """ called by the producer to indicate a successful result """
        self.results.append(result)
        self._cooperate.flow()
    def finish(self):
        """ called by producer to indicate successful stream completion """
        assert not self.failure, "failed streams should not be finished"
        self._finished = True
        self._cooperate.flow()
    def errback(self, fail):
        """ called by the producer in case of Failure """
        self.failure = fail
        self._cooperate.flow()
    def _yield(self):
        if self.results or self.stop or self.failure:
            return
        if not self.results: 
            if self._finished:
                self.stop = True
                return
            return self._cooperate
    __call__ = result


# -*- test-case-name: twisted.test.test_trial -*-

# -#*- test-case-name: twisted.test.trialtest3.TestTests -*-
# -@*- test-case-name: twisted.test.trialtest3 -*-
# -$*- test-case-name: buildbot.test.test_trial.TestRemoteReporter.testConnectToSlave -*-
#
# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.

# Author: Jonathan D. Simms <slyphon@twistedmatrix.com>
# Original Author: Jonathan Lange <jml@twistedmatrix.com>

#  B{What's going on here?}
#
#  I've been staring at this file for about 3 weeks straight, and it seems
#  like a good place to write down how all this stuff works.
#
#  The program flow goes like this:
#
#  The twisted.scripts.trial module parses command line options, creates a
#  TestSuite and passes it the Janitor and Reporter objects. It then adds
#  the modules, classes, and methods that the user requested that the suite
#  search for test cases. Then the script calls .runTests() on the suite.
#
#  The suite goes through each argument and calls ITestRunner(obj) on each
#  object. There are adapters that are registered for ModuleType, ClassType
#  and MethodType, so each one of these adapters knows how to run their
#  tests, and provides a common interface to the suite.
#
#  The module runner goes through the module and searches for classes that
#  implement itrial.TestCaseFactory, does setUpModule, adapts that module's
#  classes with ITestRunner(), and calls .run() on them in sequence.
#
#  The method runner wraps the method, locates the method's class and
#  modules so that the setUp{Module, Class, } can be run for that test.
#
#  ------
#
#  A word about reporters...
#
#  All output is to be handled by the reporter class. Warnings, Errors, etc.
#  are all given to the reporter and it decides what the correct thing to do
#  is depending on the options given on the command line. This allows the
#  runner code to concentrate on testing logic. The reporter is also given
#  Test-related objects wherever possible, not strings. It is not the job of
#  the runner to know what string should be output, it is the reporter's job
#  to know how to make sense of the data
#
#  -------
#
#  The test framework considers any user-written code *dangerous*, and it
#  wraps it in a UserMethodWrapper before execution. This allows us to
#  handle the errors in a sane, consistent way. The wrapper will run the
#  user-code, catching errors, and then checking for logged errors, saving
#  it to IUserMethod.errors.
#
#  (more to follow)
#
from __future__ import generators


import os, glob, types, warnings, time, sys, gc, cPickle as pickle, signal
import os.path as osp, fnmatch, random
from os.path import join as opj

import doctest

from twisted.internet import defer
from twisted.python import components, reflect, log, context, failure, \
     util as tputil
from twisted.trial import itrial, util, unittest, registerAdapter, \
     adaptWithDefault
from twisted.trial.itrial import ITestCaseFactory, IReporter, \
     IPyUnitTCFactory, ITrialDebug
from twisted.trial.reporter import SKIP, EXPECTED_FAILURE, FAILURE, \
     ERROR, UNEXPECTED_SUCCESS, SUCCESS
import zope.interface as zi


MAGIC_ATTRS = ('skip', 'todo', 'timeout')

# --- Exceptions and Warnings ------------------------ 

class BrokenTestCaseWarning(Warning):
    """emitted as a warning when an exception occurs in one of
    setUp, tearDown, setUpClass, or tearDownClass"""

class CouldNotImportWarning(Warning):
    pass

class TwistedPythonComponentsBugWarning(Warning):
    pass


class Timed(object):
    zi.implements(itrial.ITimed)
    startTime = None
    endTime = None

def _dbgPA(msg):
   log.msg(iface=itrial.ITrialDebug, parseargs=msg)

class TestSuite(Timed):
    """This is the main organizing object. The front-end script creates a
    TestSuite, and tells it what modules were requested on the command line.
    It also hands it a reporter. The TestSuite then takes all of the
    packages, modules, classes and methods, and adapts them to ITestRunner
    objects, which it then calls the runTests method on.
    """
    zi.implements(itrial.ITestSuite)
    moduleGlob = 'test_*.py'
    sortTests = 1

    def __init__(self, reporter, janitor, benchmark=0):
        self.reporter = IReporter(reporter)
        self.janitor = itrial.IJanitor(janitor)
        util._wait(self.reporter.setUpReporter())
        self.benchmark = benchmark
        self.startTime, self.endTime = None, None
        self.numTests = 0
        self.couldNotImport = {}
        self.tests = []
        self.children = []
        if benchmark:
            registerAdapter(None, itrial.ITestCaseFactory,
                            itrial.ITestRunner)
            registerAdapter(BenchmarkCaseRunner, itrial.ITestCaseFactory,
                            itrial.ITestRunner)

    def addMethod(self, method):
        self.tests.append(method)

    def _getMethods(self):
        for runner in self.children:
            for meth in runner.children:
                yield meth
    methods = property(_getMethods)
        
    def addTestClass(self, testClass):
        if ITestCaseFactory.providedBy(testClass):
            self.tests.append(testClass)
        else:
            warnings.warn("didn't add %s because it does not implement ITestCaseFactory" % testClass)

    def addModule(self, module):
        if isinstance(module, types.StringType):
            _dbgPA("addModule: %r" % (module,))
            try:
                module = reflect.namedModule(module)
            except:
                self.couldNotImport[module] = failure.Failure()
                return

        if isinstance(module, types.ModuleType):
            _dbgPA("adding module: %r" % module)
            self.tests.append(module)


    def addPackage(self, package):
        modGlob = os.path.join(os.path.dirname(package.__file__),
                               self.moduleGlob)
        modules = map(reflect.filenameToModuleName, glob.glob(modGlob))
        for module in modules:
            self.addModule(module)

    def _packageRecurse(self, arg, dirname, names):
        testModuleNames = fnmatch.filter(names, self.moduleGlob)
        testModules = [ reflect.filenameToModuleName(opj(dirname, name))
                        for name in testModuleNames ]
        for module in testModules:
            self.addModule(module)

    def addPackageRecursive(self, package):
        packageDir = os.path.dirname(package.__file__)
        os.path.walk(packageDir, self._packageRecurse, None)


    def _getBenchmarkStats(self):
        stat = {}
        for r in self.children:
            for m in r.children:
                stat.update(getattr(m, 'benchmarkStats', {}))
        return stat
    benchmarkStats = property(_getBenchmarkStats)

    def getJanitor(self):
        return self.janitor

    def getReporter(self):
        return self.reporter

    def run(self, seed=None):
        self.startTime = time.time()
        tests = self.tests
        if self.sortTests:
            # XXX twisted.python.util.dsu(tests, str)
            tests.sort(lambda x,y: cmp(str(x), str(y)))

        log.startKeepingErrors()

        # randomize tests if requested
        # this should probably also call some kind of random method on the
        # test runners, to get *them* to run tests in a random order
        r = None
        if seed is not None:
            r = random.Random(seed)
            r.shuffle(tests)
            self.reporter.write('Running tests shuffled with seed %d' % seed)


        # set up SIGCHLD signal handler so that parents of spawned processes
        # will be notified when their child processes end
        from twisted.internet import reactor
        if hasattr(reactor, "_handleSigchld") and hasattr(signal, "SIGCHLD"):
            self.sigchldHandler = signal.signal(signal.SIGCHLD,
                                                reactor._handleSigchld)

        def _bail():
            from twisted.internet import reactor
            reactor.fireSystemEvent('shutdown') # radix's suggestion
            reactor.suggestThreadPoolSize(0)

        try:
            # this is where the test run starts
            # eventually, the suite should call reporter.startSuite() with
            # the predicted number of tests to be run
            for test in tests:
                tr = itrial.ITestRunner(test)
                self.children.append(tr)
                tr.parent = self

                try:
                    tr.runTests(randomize=(seed is not None))
                except KeyboardInterrupt:
                    log.msg(iface=ITrialDebug, kbd="KEYBOARD INTERRUPT")
                    _bail()
                    raise
                except:
                    f = failure.Failure()
                    annoyingBorder = "-!*@&" * 20
                    trialIsBroken = """
\tWHOOP! WHOOP! DANGER WILL ROBINSON! DANGER! WHOOP! WHOOP!
\tcaught exception in TestSuite! \n\n\t\tTRIAL IS BROKEN!\n\n
\t%s""" % ('\n\t'.join(f.getTraceback().split('\n')),)
                    raise RuntimeError, "\n%s\n%s\n\n%s\n" % \
                          (annoyingBorder, trialIsBroken, annoyingBorder)

            for name, exc in self.couldNotImport.iteritems():
                # XXX: AFAICT this is only used by RemoteJellyReporter
                self.reporter.reportImportError(name, exc)

            if self.benchmark:
                pickle.dump(self.benchmarkStats, file("test.stats", 'wb'))
        finally:
            self.endTime = time.time()

        # hand the reporter the TestSuite to give it access to all information
        # from the test run
        self.reporter.endSuite(self)
        try:
            util._wait(self.reporter.tearDownReporter())
        except:
            t, v, tb = sys.exc_info()
            raise RuntimeError, "your reporter is broken %r" % \
                  (''.join(v),), tb
        _bail()


class MethodInfoBase(Timed):
    def __init__(self, original):
        self.original = o = original
        self.name = o.__name__
        self.klass = itrial.IClass(original)
        self.module = itrial.IModule(original)
        self.fullName = "%s.%s.%s" % (self.module, self.klass.__name__,
                                      self.name)
        self.docstr = (o.__doc__ or None)
        self.startTime = 0.0
        self.endTime = 0.0
        self.errors = []

    def runningTime(self):
        return self.endTime - self.startTime


class UserMethodError(Exception):
    """indicates that the user method had an error, but raised after
    call is complete
    """

class UserMethodWrapper(MethodInfoBase):
   zi.implements(itrial.IUserMethod, itrial.IMethodInfo)
   def __init__(self, original, janitor):
       super(UserMethodWrapper, self).__init__(original)
       self.janitor = janitor
       self.original = original
       self.errors = []

   def __call__(self, *a, **kw):
       self.startTime = time.time()
       try:
           try:
               r = self.original(*a, **kw)
               if isinstance(r, defer.Deferred):
                   util._wait(r, getattr(self.original, 'timeout', None))
           finally:
               self.endTime = time.time()
       except:
           self.errors.append(failure.Failure())
           try:
               self.janitor.do_logErrCheck()
           except util.LoggedErrors:
               self.errors.append(failure.Failure())
           raise UserMethodError


class JanitorAndReporterMixin:
    def getJanitor(self):
        return self.parent.getJanitor()

    def getReporter(self):
        return self.parent.getReporter()


class TestRunnerBase(Timed, JanitorAndReporterMixin):
    zi.implements(itrial.ITestRunner)
    _tcInstance = None
    methodNames = setUpClass = tearDownClass = methodsWithStatus = None
    children = parent = None
    testCaseInstance = lambda x: None
    skip = None
    
    def __init__(self, original):
        self.original = original
        self.methodsWithStatus = {}
        self.children = []
        self.startTime, self.endTime = None, None
        self._signalStateMgr = util.SignalStateManager()

    def doCleanup(self):
        """do cleanup after the test run. check log for errors, do reactor
        cleanup, and restore signals to the state they were in before the
        test ran
        """
        return self.getJanitor().postCaseCleanup()


def _bogusCallable(ignore=None):
    pass

class TestModuleRunner(TestRunnerBase):
    _tClasses = _mnames = None
    def __init__(self, original):
        super(TestModuleRunner, self).__init__(original)
        self.module = self.original
        self.setUpModule = getattr(self.original, 'setUpModule',
                                   _bogusCallable)
        self.tearDownModule = getattr(self.original, 'tearDownModule',
                                      _bogusCallable)
        self.moudleName = itrial.IModuleName(self.original)
        self.skip = getattr(self.original, 'skip', None)
        self.todo = getattr(self.original, 'todo', None)
        self.timeout = getattr(self.original, 'timeout', None)

        self.setUpClass = _bogusCallable
        self.tearDownClass = _bogusCallable
        self.children = []

    def methodNames(self):
        if self._mnames is None:
            self._mnames = [mn for tc in self._testCases
                            for mn in tc.methodNames]
        return self._mnames
    methodNames = property(methodNames)

    def _testClasses(self):
        if self._tClasses is None:
            self._tClasses = []
            mod = self.original
            if hasattr(mod, '__tests__'):
                objects = mod.__tests__
            else:
                names = dir(mod)
                objects = [getattr(mod, name) for name in names]

            for obj in objects:
                if isinstance(obj, (components.MetaInterface, zi.Interface)):
                    continue

                try:
                    if ITestCaseFactory.providedBy(obj):
                        self._tClasses.append(obj)
                except AttributeError:
                    # if someone (looking in exarkun's direction)
                    # messes around with __getattr__ in a particularly funky
                    # way, it's possible to mess up zi's providedBy()
                    pass

        return self._tClasses

    def runTests(self, randomize=False):
        reporter = self.getReporter()
        reporter.startModule(self.original)

        # add setUpModule handling
        tests = self._testClasses()
        if randomize:
            random.shuffle(tests)
        for testClass in tests:
            runner = itrial.ITestRunner(testClass)
            self.children.append(runner)
            runner.parent = self.parent
            runner.runTests(randomize)
            for k, v in runner.methodsWithStatus.iteritems():
                self.methodsWithStatus.setdefault(k, []).extend(v)

        # add tearDownModule handling
        reporter.endModule(self.original)



class TestClassAndMethodBase(TestRunnerBase):
    _module = _tcInstance = None
    
    def testCaseInstance(self):
        # a property getter, called by subclasses
        if not self._tcInstance:
            self._tcInstance = self._testCase()
        return self._tcInstance
    testCaseInstance = property(testCaseInstance)

    def module(self):
        if self._module is None:
            self._module = reflect.namedAny(self.testCases[0].__module__)
        return self._module
    module = property(module)

    def setUpModule(self):
        return getattr(self.module, 'setUpModule', _bogusCallable)
    setUpModule = property(setUpModule)

    def tearDownModule(self):
        return getattr(self.module, 'tearDownModule', _bogusCallable)
    tearDownModule = property(tearDownModule)

    def runTests(self, randomize=False):
        reporter = self.getReporter()
        janitor = self.getJanitor()

        def _apply(f):                  # XXX: need to rename this
            for mname in self.methodNames:
                m = getattr(self._testCase, mname)
                tm = adaptWithDefault(itrial.ITestMethod, m, default=None)
                if tm == None:
                    continue

                tm.parent = self
                self.children.append(tm)
                f(tm)
        
        tci = self.testCaseInstance
        self.startTime = time.time()

        try:
            self._signalStateMgr.save()

            reporter.startClass(self._testCase.__name__) # fix! this sucks!

            # --- setUpClass -----------------------------------------------

            um = UserMethodWrapper(self.setUpClass, janitor)
            try:
                um()
            except UserMethodError:
                for error in um.errors:
                    if error.check(unittest.SkipTest):
                        self.skip = error.value[0]
                        def _setUpSkipTests(tm):
                            tm.skip = self.skip
                        break                   # <--- skip the else: clause
                    elif error.check(KeyboardInterrupt):
                        log.msg(iface=ITrialDebug, kbd="KEYBOARD INTERRUPT")
                        um.error.raiseException()
                else:
                    reporter.upDownError(um)
                    def _setUpClassError(tm):
                        tm.errors.extend(um.errors)
                        reporter.startTest(tm)
                        self.methodsWithStatus.setdefault(tm.status,
                                                          []).append(tm)
                        reporter.endTest(tm)
                    return _apply(_setUpClassError) # and we're done

            # --- run methods ----------------------------------------------

            methodNames = self.methodNames
            if randomize:
                random.shuffle(self.methodNames)

            def _runTestMethod(testMethod):
                log.msg("--> %s.%s.%s <--" % (testMethod.module.__name__,
                                              testMethod.klass.__name__,
                                              testMethod.name))

                testMethod.run(tci)
                self.methodsWithStatus.setdefault(testMethod.status,
                                                  []).append(testMethod)

            _apply(_runTestMethod)

            # --- tearDownClass ---------------------------------------------

            um = UserMethodWrapper(self.tearDownClass, janitor)
            try:
                um()
            except UserMethodError:
                for error in um.errors:
                    if error.check(KeyboardInterrupt):
                        log.msg(iface=ITrialDebug, kbd="KEYBOARD INTERRUPT")
                        error.raiseException()
                else:
                    reporter.upDownError(um)

        finally:
            errs = self.doCleanup()
            if errs:
                reporter.cleanupErrors(errs)
            self._signalStateMgr.restore()
            reporter.endClass(self._testCase.__name__) # fix! this sucks!
            self.endTime = time.time()
        

class TestCaseRunner(TestClassAndMethodBase):
    """I run L{twisted.trial.unittest.TestCase} instances"""
    methodPrefix = 'test'
    def __init__(self, original):
        super(TestCaseRunner, self).__init__(original)
        self.original = original
        self._testCase = self.original

        self.setUpClass = getattr(self.testCaseInstance, 'setUpClass',
                                  _bogusCallable)
        self.tearDownClass = getattr(self.testCaseInstance, 'tearDownClass',
                                     _bogusCallable)

        self.methodNames = [name for name in dir(self.testCaseInstance)
                            if name.startswith(self.methodPrefix)]
        for attr in MAGIC_ATTRS:
            setattr(self, attr, getattr(self.original, attr, None))


class TestCaseMethodRunner(TestClassAndMethodBase):
    """I run single test methods"""
    # formerly known as SingletonRunner
    def __init__(self, original):
        super(TestCaseMethodRunner, self).__init__(original)
        self.original = o = original
        self._testCase = o.im_class
        self.methodNames = [o.__name__]
        self.setUpClass = self.testCaseInstance.setUpClass
        self.tearDownClass = self.testCaseInstance.tearDownClass

        for attr in MAGIC_ATTRS:
            v = getattr(self.original, attr, None)
            if v is None:
                v = getattr(self._testCase, attr, None)
            setattr(self, attr, v)

    # TODO: for 2.1
    # this needs a custom runTests to handle setUpModule/tearDownModule


class PyUnitTestCaseRunner(TestClassAndMethodBase):
    """I run python stdlib TestCases"""
    def __init__(self, original):
        original.__init__ = lambda _: None
        super(PyUnitTestCaseRunner, self).__init__(original)

    testCaseInstance = property(TestClassAndMethodBase.testCaseInstance)


class BenchmarkCaseRunner(TestCaseRunner):
    """I run benchmarking tests"""
    methodPrefix = 'benchmark'
    def runTests(self, randomize=False):
        # need to hook up randomize for Benchmark test cases
        registerAdapter(None, types.MethodType, itrial.ITestMethod)
        registerAdapter(BenchmarkMethod, types.MethodType, itrial.ITestMethod)
        try:
            super(BenchmarkCaseRunner, self).runTests()
        finally:
            registerAdapter(None, types.MethodType, itrial.ITestMethod)
            registerAdapter(TestMethod, types.MethodType, itrial.ITestMethod)
        

class TestMethod(MethodInfoBase, JanitorAndReporterMixin):
    zi.implements(itrial.ITestMethod, itrial.IMethodInfo, itrial.ITimeout)
    _status = parent = todo = timeout = None

    def __init__(self, original):
        super(TestMethod, self).__init__(original)

        self.setUp = self.klass.setUp
        self.tearDown = self.klass.tearDown

        self.runs = 0
        self.failures = []
        self.stdout = ''
        self.stderr = ''
        self.logevents = []

        self._skipReason = None  
        self._signalStateMgr = util.SignalStateManager()


    def _checkTodo(self):
        # returns EXPECTED_FAILURE for now if ITodo.types is None for
        # backwards compatiblity but as of twisted 2.1, will return FAILURE
        # or ERROR as appropriate
        #
        # TODO: This is a bit simplistic for right now, it makes sure all
        # errors and/or failures are of the type(s) specified in
        # ITodo.types, else it returns EXPECTED_FAILURE. This should
        # probably allow for more complex specifications. Perhaps I will
        # define a Todo object that will allow for greater
        # flexibility/complexity.

        for f in util.iterchain(self.failures, self.errors):
            if not itrial.ITodo(self.todo).isExpected(f):
                return ERROR
        return EXPECTED_FAILURE

    def _getStatus(self):
        if self._status is None:
            if self.todo is not None and (self.failures or self.errors):
                self._status = self._checkTodo()
            elif self.skip is not None:
                self._status = SKIP
            elif self.errors:
                self._status = ERROR
            elif self.failures:
                self._status = FAILURE
            elif self.todo:
                self._status = UNEXPECTED_SUCCESS
            else:
                self._status = SUCCESS
        return self._status
    status = property(_getStatus)
        
    def _getSkip(self):
        return (getattr(self.original, 'skip', None) \
                or self._skipReason or self.parent.skip)
    def _setSkip(self, value):
        self._skipReason = value
    skip = property(_getSkip, _setSkip)

    def todo(self):
        return getattr(self.original, 'todo',
                       getattr(self.parent, 'todo', None))
    todo = property(todo)
   
    def timeout(self):
        if hasattr(self.original, 'timeout'):
            return getattr(self.original, 'timeout')
        else:
            return getattr(self.parent, 'timeout', util.DEFAULT_TIMEOUT)
    timeout = property(timeout)

    def hasTbs(self):
        return self.errors or self.failures
    hasTbs = property(hasTbs)

    def _eb(self, f):
        log.msg(f.printTraceback())
        if f.check(unittest.FAILING_EXCEPTION,
                   unittest.FailTest):
            self.failures.append(f)
        elif f.check(KeyboardInterrupt):
            log.msg(iface=ITrialDebug, kbd="KEYBOARD INTERRUPT")
        elif f.check(unittest.SkipTest):
            if len(f.value.args) > 1:
                reason = f.value.args[0]
            else:
                warnings.warn(("Do not raise unittest.SkipTest with no "
                               "arguments! "
                               "Give a reason for skipping tests!"),
                              stacklevel=2)
                reason = str(f)
            self._skipReason = reason
        else:
            self.errors.append(f)


    def run(self, testCaseInstance):
        self.testCaseInstance = tci = testCaseInstance
        self.runs += 1
        self.startTime = time.time()
        self._signalStateMgr.save()
        janitor = self.parent.getJanitor()
        reporter = self.parent.getReporter()

        try:
            # don't run test methods that are marked as .skip
            #
            if self.skip:
                # wheeee!
                reporter.startTest(self)
                reporter.endTest(self)
                return

            f = None
            try:
                # capture all a TestMethod run's log events (warner's request)
                observer = util.TrialLogObserver().install()

                setUp = UserMethodWrapper(self.setUp, janitor)
                try:
                    setUp(tci)
                except UserMethodError:
                    for error in setUp.errors:
                        if error.check(KeyboardInterrupt):
                            error.raiseException()
                        self._eb(error)
                    else:
                        # give the reporter the illusion that the test has run normally
                        # but don't actually run the test if setUp is broken
                        reporter.startTest(self)
                        reporter.upDownError(setUp, warn=False, printStatus=False)
                        return
                 
                reporter.startTest(self)

                try:
                    sys.stdout = util.StdioProxy(sys.stdout)
                    sys.stderr = util.StdioProxy(sys.stderr)
                   
                    # --- this is basically the guts of UserMethodWrapper,
                    #     because I *SUCK* -----
                    try:
                        try:
                            r = self.original(tci)
                            if isinstance(r, defer.Deferred):
                                util._wait(r, self.timeout)
                        finally:
                            self.endTime = time.time()
                    except:
                        f = failure.Failure()
                        self._eb(f)

                        try:
                            janitor.do_logErrCheck()
                        except util.LoggedErrors:
                            self.errors.append(failure.Failure())
                    # ------------------------------------------------------

                finally:
                    self.endTime = time.time()

                    self.stdout = sys.stdout.getvalue()
                    self.stderr = sys.stderr.getvalue()
                    sys.stdout = sys.stdout.original
                    sys.stderr = sys.stderr.original

                    um = UserMethodWrapper(self.tearDown, janitor)
                    try:
                        um(tci)
                    except UserMethodError:
                        for error in um.errors:
                            self._eb(error)
                        else:
                            reporter.upDownError(um, warn=False)
            finally:
                observer.remove()
                self.logevents = observer.events
                self.doCleanup()
                reporter.endTest(self)

        finally:
            self._signalStateMgr.restore()


    def doCleanup(self):
        """do cleanup after the test run. check log for errors, do reactor
        cleanup
        """
        errs = self.getJanitor().postMethodCleanup()
        for f in errs:
            self._eb(f)
        return errs


class BenchmarkMethod(TestMethod):
    def __init__(self, original):
        super(BenchmarkMethod, self).__init__(original)
        self.benchmarkStats = {}

    def run(self, testCaseInstance):
        # WHY IS THIS MONKEY PATCH HERE?
        testCaseInstance.recordStat = lambda datum: self.benchmarkStats.__setitem__(itrial.IFQMethodName(self.original), datum)
        self.original(testCaseInstance)
        

def runTest(method):
    # utility function, used by test_trial to more closely emulate the usual
    # testing process. This matches the same check in util.extract_tb that
    # matches SingletonRunner.runTest and TestClassRunner.runTest .
    method()




## class PerformanceTestClassRunner(TestClassRunner):
##     methodPrefixes = ('benchmark',)
##     def runTest(self, method):
##         assert method.__name__ in self.methodNames
##         fullName = "%s.%s" % (method.im_class, method.im_func.__name__)
##         method.im_self.recordStat = lambda datum: self.stats.__setitem__(fullName,datum)
##         method()



## class PerformanceSingletonRunner(SingletonRunner):
##     def __init__(self, methodName, stats):
##         SingletonRunner.__init__(self, methodName)
##         self.stats = stats

##     def runTest(self, method):
##         assert method.__name__ == self.methodName
##         fullName = "%s.%s" % (method.im_class, method.im_func.__name__)
##         method.im_self.recordStat = lambda datum: self.stats.__setitem__(fullName, datum)
##         method()



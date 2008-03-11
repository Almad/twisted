# -*- test-case-name: twisted.python.test.test_release -*-
# Copyright (c) 2007-2008 Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Twisted's automated release system.

This module is only for use within Twisted's release system. If you are anyone
else, do not use it. The interface and behaviour will change without notice.
"""

from datetime import date
import os
from tempfile import mkdtemp

# Popen4 isn't available on Windows.  BookBuilder won't work on Windows, but
# we don't care. -exarkun
try:
    from popen2 import Popen4
except ImportError:
    Popen4 = None

from twisted.python.versions import Version
from twisted.python.filepath import FilePath

# This import is an example of why you shouldn't use this module unless you're
# radix
from twisted.lore.scripts import lore

# The offset between a year and the corresponding major version number.
VERSION_OFFSET = 2000


class CommandFailed(Exception):
    """
    Raised when a child process exits unsuccessfully.

    @type exitCode: C{int}
    @ivar exitCode: The exit code for the child process.

    @type output: C{str}
    @ivar output: The bytes read from stdout and stderr of the child process.
    """
    def __init__(self, exitCode, output):
        Exception.__init__(self, exitCode, output)
        self.exitCode = exitCode
        self.output = output


def _changeVersionInFile(old, new, filename):
    """
    Replace the C{old} version number with the C{new} one in the given
    C{filename}.
    """
    replaceInFile(filename, {old.base(): new.base()})



def getNextVersion(version, now=None):
    """
    Calculate the version number for a new release of Twisted based on
    the previous version number.

    @param version: The previous version number.
    @param now: (optional) The current date.
    """
    # XXX: This has no way of incrementing the patch number. Currently, we
    # don't need it. See bug 2915. Jonathan Lange, 2007-11-20.
    if now is None:
        now = date.today()
    major = now.year - VERSION_OFFSET
    if major != version.major:
        minor = 0
    else:
        minor = version.minor + 1
    return Version(version.package, major, minor, 0)



class Project(object):
    """
    A representation of a project that has a version.

    @ivar directory: A L{twisted.python.filepath.FilePath} pointing to the base
        directory of a Twisted-style Python package. The package should contain
        a C{_version.py} file and a C{topfiles} directory that contains a
        C{README} file.
    """

    def __init__(self, directory):
        self.directory = directory


    def __repr__(self):
        return '%s(%r)' % (
            self.__class__.__name__, self.directory)


    def getVersion(self):
        """
        @return: A L{Version} specifying the version number of the project
        based on live python modules.
        """
        namespace = {}
        execfile(self.directory.child("_version.py").path, namespace)
        return namespace["version"]


    def updateVersion(self, version):
        """
        Replace the existing version numbers in _version.py and README files
        with the specified version.
        """
        oldVersion = self.getVersion()
        replaceProjectVersion(oldVersion.package,
                              self.directory.child("_version.py").path,
                              (version.major, version.minor, version.micro))
        _changeVersionInFile(
            oldVersion, version,
            self.directory.child("topfiles").child("README").path)



def findTwistedProjects(baseDirectory):
    """
    Find all Twisted-style projects beneath a base directory.

    @param baseDirectory: A L{twisted.python.filepath.FilePath} to look inside.
    @return: A list of L{Project}.
    """
    projects = []
    for filePath in baseDirectory.walk():
        if filePath.basename() == 'topfiles':
            projectDirectory = filePath.parent()
            projects.append(Project(projectDirectory))
    return projects



def updateTwistedVersionInformation(baseDirectory, now):
    """
    Update the version information for Twisted and all subprojects to the
    date-based version number.

    @param baseDirectory: Where to look for Twisted. If None, the function
        infers the information from C{twisted.__file__}.
    @param now: The current date (as L{datetime.date}). If None, it defaults
        to today.
    """
    for project in findTwistedProjects(baseDirectory):
        project.updateVersion(getNextVersion(project.getVersion(), now=now))



def replaceProjectVersion(name, filename, newversion):
    """
    Write version specification code into the given filename, which
    sets the version to the given version number.

    @param filename: A filename which is most likely a "_version.py"
    under some Twisted project.
    @param newversion: A sequence of three numbers.
    """
    # XXX - this should be moved to Project and renamed to writeVersionFile.
    # jml, 2007-11-15.
    f = open(filename, 'w')
    f.write('''\
# This is an auto-generated file. Do not edit it.
from twisted.python import versions
version = versions.Version(%r, %s, %s, %s)
''' % ((name,) + tuple(newversion)))
    f.close()



def replaceInFile(filename, oldToNew):
    """
    I replace the text `oldstr' with `newstr' in `filename' using science.
    """
    os.rename(filename, filename+'.bak')
    f = open(filename+'.bak')
    d = f.read()
    f.close()
    for k,v in oldToNew.items():
        d = d.replace(k, v)
    f = open(filename + '.new', 'w')
    f.write(d)
    f.close()
    os.rename(filename+'.new', filename)
    os.unlink(filename+'.bak')



class NoDocumentsFound(Exception):
    """
    Raised when no input documents are found.
    """



class LoreBuilderMixin(object):
    """
    Base class for builders which invoke lore.
    """
    def lore(self, arguments):
        """
        Run lore with the given arguments.

        @param arguments: A C{list} of C{str} giving command line arguments to
            lore which should be used.
        """
        options = lore.Options()
        options.parseOptions(["--null"] + arguments)
        lore.runGivenOptions(options)



class DocBuilder(LoreBuilderMixin):
    """
    Generate HTML documentation for projects.
    """

    def build(self, version, resourceDir, docDir, template, deleteInput=False):
        """
        Build the documentation in C{docDir} with Lore.

        Input files ending in .xhtml will be considered. Output will written as
        .html files.

        @param version: the version of the documentation to pass to lore.
        @type version: C{str}

        @param resourceDir: The directory which contains the toplevel index and
            stylesheet file for this section of documentation.
        @type resourceDir: L{twisted.python.filepath.FilePath}

        @param docDir: The directory of the documentation.
        @type docDir: L{twisted.python.filepath.FilePath}

        @param template: The template used to generate the documentation.
        @type template: L{twisted.python.filepath.FilePath}

        @param deleteInput: If True, the input documents will be deleted after
            their output is generated.
        @type deleteInput: C{bool}

        @raise NoDocumentsFound: When there are no .xhtml files in the given
            C{docDir}.
        """
        linkrel = self.getLinkrel(resourceDir, docDir)
        inputFiles = docDir.globChildren("*.xhtml")
        filenames = [x.path for x in inputFiles]
        if not filenames:
            raise NoDocumentsFound("No input documents found in %s" % (docDir,))
        arguments = ["--config", "template=%s" % (template.path,),
                     "--config", "ext=.html",
                     "--config", "version=%s" % (version,),
                     "--linkrel", linkrel] + filenames
        self.lore(arguments)
        if deleteInput:
            for inputFile in inputFiles:
                inputFile.remove()


    def getLinkrel(self, resourceDir, docDir):
        """
        Calculate a value appropriate for Lore's --linkrel option.

        Lore's --linkrel option defines how to 'find' documents that are
        linked to from TEMPLATE files (NOT document bodies). That is, it's a
        prefix for links ('a' and 'link') in the template.

        @param resourceDir: The directory which contains the toplevel index and
            stylesheet file for this section of documentation.
        @type resourceDir: L{twisted.python.filepath.FilePath}

        @param docDir: The directory containing documents that must link to
            C{resourceDir}.
        @type docDir: L{twisted.python.filepath.FilePath}
        """
        if resourceDir != docDir:
            return '/'.join(filePathDelta(docDir, resourceDir)) + "/"
        else:
            return ""



class ManBuilder(LoreBuilderMixin):
    """
    Generate man pages of the different existing scripts.
    """

    def build(self, manDir):
        """
        Generate Lore input files from the man pages in C{manDir}.

        Input files ending in .1 will be considered. Output will written as
        -man.xhtml files.

        @param manDir: The directory of the man pages.
        @type manDir: L{twisted.python.filepath.FilePath}

        @raise NoDocumentsFound: When there are no .1 files in the given
            C{manDir}.
        """
        inputFiles = manDir.globChildren("*.1")
        filenames = [x.path for x in inputFiles]
        if not filenames:
            raise NoDocumentsFound("No manual pages found in %s" % (manDir,))
        arguments = ["--input", "man",
                     "--output", "lore",
                     "--config", "ext=-man.xhtml"] + filenames
        self.lore(arguments)



class BookBuilder(LoreBuilderMixin):
    """
    Generate the LaTeX and PDF documentation.
    """
    def run(self, command):
        """
        Execute a command in a child process and return the output.

        @type command C{str}
        @param command: The shell command to run.

        @raise L{RuntimeError}: If the child process exits with an error.
        """
        process = Popen4(command)
        stdout = process.fromchild.read()
        exitCode = process.wait()
        if os.WIFSIGNALED(exitCode) or os.WEXITSTATUS(exitCode):
            raise CommandFailed(exitCode, stdout)
        return stdout


    def buildTeX(self, howtoDir):
        """
        Build LaTex files for lore input files in the given directory.

        Input files ending in .xhtml will be considered. Output will written as
        .tex files.

        @type howtoDir: L{FilePath}
        @param howtoDir: A directory containing lore input files.

        @raise ValueError: If C{howtoDir} does not exist.
        """
        if not howtoDir.exists():
            raise ValueError("%r does not exist." % (howtoDir.path,))
        self.lore(
            ["--output", "latex",
             "--config", "section"] +
            [child.path for child in howtoDir.globChildren("*.xhtml")])


    def buildPDF(self, bookPath, inputDirectory, outputPath):
        """
        Build a PDF from the given a LaTeX book document.

        @type bookPath: L{FilePath}
        @param bookPath: The location of a LaTeX document defining a book.

        @type inputDirectory: L{FilePath}
        @param inputDirectory: The directory which the inputs of the book are
            relative to.

        @type outputPath: L{FilePath}
        @param outputPath: The location to which to write the resulting book.
        """
        if not bookPath.basename().endswith(".tex"):
            raise ValueError("Book filename must end with .tex")

        workPath = FilePath(mkdtemp())
        try:
            startDir = os.getcwd()
            try:
                os.chdir(inputDirectory.path)

                texToDVI = (
                    "latex -interaction=nonstopmode "
                    "-output-directory=%s %s") % (
                    workPath.path, bookPath.path)

                # What I tell you three times is true!
                # The first two invocations of latex on the book file allows it
                # correctly create page numbers for in-text references.  Why this is
                # the case, I could not tell you. -exarkun
                for i in range(3):
                    self.run(texToDVI)

                bookBaseWithoutExtension = bookPath.basename()[:-4]
                dviPath = workPath.child(bookBaseWithoutExtension + ".dvi")
                psPath = workPath.child(bookBaseWithoutExtension + ".ps")
                pdfPath = workPath.child(bookBaseWithoutExtension + ".pdf")
                self.run(
                    "dvips -o %(postscript)s -t letter -Ppdf %(dvi)s" % {
                        'postscript': psPath.path,
                        'dvi': dviPath.path})
                self.run("ps2pdf13 %(postscript)s %(pdf)s" % {
                        'postscript': psPath.path,
                        'pdf': pdfPath.path})
                pdfPath.moveTo(outputPath)
                workPath.remove()
            finally:
                os.chdir(startDir)
        except:
            workPath.moveTo(bookPath.parent().child(workPath.basename()))
            raise


    def build(self, baseDirectory, inputDirectories, bookPath, outputPath):
        """
        Build a PDF book from the given TeX book definition and directories
        containing lore inputs.

        @type baseDirectory: L{FilePath}
        @param baseDirectory: The directory which the inputs of the book are
            relative to.

        @type inputDirectories: C{list} of L{FilePath}
        @param inputDirectories: The paths which contain lore inputs to be
            converted to LaTeX.

        @type bookPath: L{FilePath}
        @param bookPath: The location of a LaTeX document defining a book.

        @type outputPath: L{FilePath}
        @param outputPath: The location to which to write the resulting book.
        """
        for inputDir in inputDirectories:
            self.buildTeX(inputDir)
        self.buildPDF(bookPath, baseDirectory, outputPath)
        for inputDirectory in inputDirectories:
            for child in inputDirectory.children():
                if child.splitext()[1] == ".tex" and child != bookPath:
                    child.remove()



def filePathDelta(origin, destination):
    """
    Return a list of strings that represent C{destination} as a path relative
    to C{origin}.

    It is assumed that both paths represent directories, not files. That is to
    say, the delta of L{twisted.python.filepath.FilePath} /foo/bar to
    L{twisted.python.filepath.FilePath} /foo/baz will be C{../baz},
    not C{baz}.

    @type origin: L{twisted.python.filepath.FilePath}
    @param origin: The origin of the relative path.

    @type destination: L{twisted.python.filepath.FilePath}
    @param destination: The destination of the relative path.
    """
    commonItems = 0
    path1 = origin.path.split(os.sep)
    path2 = destination.path.split(os.sep)
    for elem1, elem2 in zip(path1, path2):
        if elem1 == elem2:
            commonItems += 1
    path = [".."] * (len(path1) - commonItems)
    return path + path2[commonItems:]

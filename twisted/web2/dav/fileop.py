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

"""
WebDAV file operations

This API is considered private to static.py and is therefore subject to
change.
"""

__all__ = [
    "delete",
    "copy",
    "move",
    "put",
    "mkcollection",
]

import os
import urllib
from urlparse import urlsplit

from twisted.python import log
from twisted.python.filepath import FilePath
from twisted.python.failure import Failure
from twisted.internet.defer import DeferredList
from twisted.web2 import responsecode
from twisted.web2.http import StatusResponse
from twisted.web2.stream import FileStream, readIntoFile
from twisted.web2.dav.http import ResponseQueue, statusForFailure

def delete(uri, filepath, depth="infinity"):
    """
    Perform a X{DELETE} operation on the given URI, which is backed by the given
    filepath.
    @param filepath: the L{FilePath} to delete.
    @param depth: the recursion X{Depth} for the X{DELETE} operation, which must
        be "infinity".
    @return: a response or response code.
        If C{depth} is not "infinity", L{responsecode.BAD_REQUEST} is returned.
        If the operation succeeds, the return value will be
        L{responsecode.NO_CONTENT}.
    """
    #
    # Remove the file(s)
    #
    # FIXME: defer
    if filepath.isdir():
        #
        # RFC 2518, section 8.6 says that we must act as if the Depth header is
        # set to infinity, and that the client must omit the Depth header or set
        # it to infinity, meaning that for collections, we will delete all
        # members.
        #
        # This seems somewhat at odds with the notion that a bad request should
        # be rejected outright; if the client sends a bad depth header, the
        # client is broken, and RFC 2518, section 8 suggests that a bad request
        # should be rejected...
        #
        # Let's play it safe for now and ignore broken clients.
        #

        if depth != "infinity":
            msg = ("Client sent illegal depth header value for DELETE: %s" % (depth,))
            log.err(msg)
            return StatusResponse(responsecode.BAD_REQUEST, msg)

        #
        # Recursive delete
        #
        # RFC 2518, section 8.6 says that if we get an error deleting a resource
        # other than the collection in the request-URI, that we must respond
        # with a multi-status response containing error statuses for each
        # resource that we fail to delete.  It also says we should not return
        # no-content (success) status, which means that we should continue after
        # errors, rather than aborting right away.  This is interesting in that
        # it's different from how most operating system tools act (eg. rm) when
        # recursive filsystem deletes fail.
        #

        uri_path = urllib.unquote(urlsplit(uri)[2])
        if uri_path[-1] == "/": uri_path = uri_path[:-1]

        log.msg("Deleting directory %s" % (filepath.path,))

        # NOTE: len(uri_path) is wrong if os.sep is not one byte long... meh.
        request_basename = filepath.path[:-len(uri_path)]
        request_basename_len = len(request_basename)

        errors = ResponseQueue(request_basename, "DELETE", responsecode.NO_CONTENT)

        # FIXME: defer this
        for dir, subdirs, files in os.walk(filepath.path, topdown=False):
            for filename in files:
                path = os.path.join(dir, filename)
                try: os.remove(path)
                except: errors.add(path, Failure())

            for subdir in subdirs:
                path = os.path.join(dir, subdir)
                if os.path.islink(path):
                    try: os.remove(path)
                    except: errors.add(path, Failure())
                else:
                    try: os.rmdir(path)
                    except: errors.add(path, Failure())

        try: os.rmdir(filepath.path)
        except:
            return statusForFailure(Failure(), "deleting directory: %s" % (filepath.path,))

        response = errors.response()

    else:
        #
        # Delete a file; much simpler, eh?
        #
        log.msg("Deleting file %s" % (filepath.path,))
        try:
            os.remove(filepath.path)
        except:
            return statusForFailure(Failure(), "deleting file: %s" % (filepath.path,))

        response = responsecode.NO_CONTENT

    # Restat filepath since we deleted the backing file
    filepath.restat(False)

    return response

def copy(source_filepath, destination_filepath, destination_uri, depth):
    """
    Perform a X{COPY} from the given source and destination filepaths.
    This will perform a X{DELETE} on the destination if necessary; the caller
    should check and handle the X{overwrite} header before calling L{copy} (as
    in L{COPYMOVE.prepareForCopy}).
    @param source_filepath: a L{FilePath} for the file to copy from.
    @param destination_filepath: a L{FilePath} for the file to copy to.
    @param destination_uri: the URI of the destination resource.
    @param depth: the recursion X{Depth} for the X{COPY} operation, which must
        be one of "0", "1", or "infinity".
    @return: a response or response code.
        If C{depth} is not "0", "1" or "infinity", L{responsecode.BAD_REQUEST}
        is returned.
        If the operation succeeds, the return value will be
        L{responsecode.CREATED} if the destination already exists or
        L{responsecode.NO_CONTENT} if the destination was created by the
        X{COPY}.
    """
    if source_filepath.isfile():
        #
        # Copy the file
        #
        log.msg("Copying file %s to %s" % (source_filepath.path, destination_filepath.path))

        try:
            source_file = source_filepath.open()
        except:
            return statusForFailure(Failure(), "opening file for reading: %s" % (source_filepath.path,))
    
        return put(FileStream(source_file), destination_filepath, destination_uri)

    elif source_filepath.isdir():
        if destination_filepath.exists():
            #
            # Delete the destination
            #
            response = delete(destination_uri, destination_filepath)
            if response != responsecode.NO_CONTENT: return response
    
            success_code = responsecode.NO_CONTENT
        else:
            success_code = responsecode.CREATED

        #
        # Copy the directory
        #
        log.msg("Copying directory %s to %s" % (source_filepath.path, destination_filepath.path))

        source_basename = source_filepath.path
        destination_basename = destination_filepath.path

        if destination_filepath.parent().isdir():
            if os.path.islink(source_basename):
                link_destination = os.readlink(source_basename)
                if link_destination[0] != os.path.sep:
                    link_destination = os.path.join(source_basename, link_destination)
                try:
                    os.symlink(destination_basename, link_destination)
                except:
                    errors.add(source_basename, Failure())
            else:
                try:
                    os.mkdir(destination_basename)
                except:
                    return statusForFailure(Failure(), "creating directory %s" % (destination_basename,))

                if depth == "0": return responsecode.CREATED
        else:
            return StatusResponse(
                responsecode.CONFLICT,
                "Parent collection for destination %s does not exist" % (destination_uri,)
            )

        #
        # Recursive copy
        #
        # FIXME: When we report errors, do we report them on the source URI
        # or on the destination URI?  We're using the source URI here.
        #
        # FIXME: defer the walk

        source_basename_len = len(source_basename)

        errors = ResponseQueue(source_basename, "COPY", success_code)

        def paths(basepath, subpath):
            source_path = os.path.join(basepath, subpath)
            assert source_path.startswith(source_basename)
            destination_path = os.path.join(destination_basename, source_path[source_basename_len+1:])
            return source_path, destination_path

        ds = []

        for dir, subdirs, files in os.walk(source_filepath.path, topdown=True):
            for filename in files:
                source_path, destination_path = paths(dir, filename)
                if not os.path.isdir(os.path.dirname(destination_path)):
                    errors.add(source_path, responsecode.NOT_FOUND)
                else:
                    d = copy(FilePath(source_path), FilePath(destination_path), destination_uri, depth)
                    ds.append(d)

            for subdir in subdirs:
                source_path, destination_path = paths(dir, subdir)
                log.msg("Copying directory %s to %s" % (source_path, destination_path))

                if not os.path.isdir(os.path.dirname(destination_path)):
                    errors.add(source_path, responsecode.CONFLICT)
                else:
                    if os.path.islink(source_path):
                        link_destination = os.readlink(source_path)
                        if link_destination[0] != os.path.sep:
                            link_destination = os.path.join(source_path, link_destination)
                        try:
                            os.symlink(destination_path, link_destination)
                        except:
                            errors.add(source_path, Failure())
                    else:
                        try: os.mkdir(destination_path)
                        except: errors.add(source_path, Failure())

        def respond(_): return errors.response()
        dl = DeferredList(ds)
        dl.addCallback(respond)

        return dl

    else:
        log.err("Unable to COPY to non-file: %s" % (source_filepath.path,))
        return StatusResponse(
            responsecode.FORBIDDEN,
            "The requested resource exists but is not backed by a regular file."
        )

def move(source_filepath, source_uri, destination_filepath, destination_uri, depth):
    """
    Perform a X{MOVE} from the given source and destination filepaths.
    This will perform a X{DELETE} on the destination if necessary; the caller
    should check and handle the X{overwrite} header before calling L{copy} (as
    in L{COPYMOVE.prepareForCopy}).
    Following the X{DELETE}, this will attempt an atomic filesystem move.  If
    that fails, a X{COPY} operation followed by a X{DELETE} on the source will
    be attempted instead.
    @param source_filepath: a L{FilePath} for the file to copy from.
    @param destination_filepath: a L{FilePath} for the file to copy to.
    @param destination_uri: the URI of the destination resource.
    @param depth: the recursion X{Depth} for the X{MOVE} operation, which must
        be "infinity".
    @return: a response or response code.
        If C{depth} is not "infinity", L{responsecode.BAD_REQUEST} is returned.
        If the operation succeeds, the return value will be
        L{responsecode.CREATED} if the destination already exists or
        L{responsecode.NO_CONTENT} if the destination was created by the
        X{MOVE}.
    """
    log.msg("Moving %s to %s" % (source_filepath.path, destination_filepath.path))

    #
    # Choose a success status
    #
    if destination_filepath.exists():
        #
        # Delete the destination
        #
        response = delete(destination_uri, destination_filepath)
        if response != responsecode.NO_CONTENT: return response

        success_code = responsecode.NO_CONTENT
    else:
        success_code = responsecode.CREATED

    #
    # See if rename (which is atomic, and fast) works
    #
    try:
        os.rename(source_filepath.path, destination_filepath.path)
    except OSError: pass
    else:
        # Restat source filepath since we moved it
        source_filepath.restat(False)
        return success_code

    #
    # Do a copy, then delete the source
    #

    def do_delete(copy_response):
        # If copy failed, return the error response
        if copy_response not in (responsecode.CREATED, responsecode.NO_CONTENT):
            return copy_response

        delete_response = delete(source_uri, source_filepath)
        if delete_response != responsecode.NO_CONTENT:
            return delete_response
        else:
            return success_code

    d = maybeDeferred(copy, source_filepath, destination_filepath, destination_uri, depth)
    d.addCallback(do_delete)
    return d

def put(stream, filepath, uri=None):
    """
    Perform a PUT of the given data stream into the given filepath.
    @param stream: the stream to write to the destination.
    @param filepath: the L{FilePath} of the destination file.
    @param uri: the URI of the destination resource.
        If the destination exists, if C{uri} is not C{None}, perform a
        X{DELETE} operation on the destination, but if C{uri} is C{None},
        delete the destination directly.
        Note that whether a L{put} deletes the destination directly vs.
        performing a X{DELETE} on the destination affects the response returned
        in the event of an error during deletion.  Specifically, X{DELETE}
        on collections must return a L{MultiStatusResponse} under certain
        circumstances, whereas X{PUT} isn't required to do so.  Therefore,
        if the caller expects X{DELETE} semantics, it must provide a valid
        C{uri}.
    @return: a response or response code.
        If the operation succeeds, the return value will be
        L{responsecode.CREATED} if the destination already exists or
        L{responsecode.NO_CONTENT} if the destination was created by the
        X{PUT}.
    """
    if filepath.exists():
        if uri is None:
            try:
                if filepath.isdir(): rmdir(filepath.path)
                else: os.remove(filepath.path)
            except:
                return statusForFailure(Failure(), "writing to file: %s" % (filepath.path,))
        else:
            response = delete(uri, filepath)
            if response != responsecode.NO_CONTENT: return response

        success_code = responsecode.NO_CONTENT
    else:
        success_code = responsecode.CREATED

    #
    # Write the contents of the request stream to resource's file
    #

    def done(_):
        # Restat filepath since we modified the backing file
        filepath.restat(False)
        return success_code

    def oops(f):
        return statusForFailure(f, "writing to file: %s" % (filepath.path,))

    try:
        resource_file = filepath.open("w")
    except:
        return statusForFailure(Failure(), "opening file for writing: %s" % (filepath.path,))

    d = readIntoFile(stream, resource_file)

    d.addCallback(done)
    d.addErrback (oops)

    return d

def mkcollection(filepath):
    """
    Perform a X{MKCOL} on the given filepath.
    @param filepath: the L{FilePath} of the collection resource to create.
    @return: a response or response code.
        If the operation succeeds, the return value will be
        L{responsecode.CREATED} if the destination already exists or
        L{responsecode.NO_CONTENT} if the destination was created by the
        X{MKCOL}.
    """
    try:
        os.mkdir(filepath.path)
        # Restat filepath because we modified it
        filepath.restat(False)
    except:
        return statusForFailure(Failure(), "creating directory in MKCOL: %s" % (filepath.path,))

    return responsecode.CREATED

def rmdir(dirname):
    """
    Removes the directory with the given name, as well as its contents.
    @param dirname: the path to the directory to remove.
    """
    for dir, subdirs, files in os.walk(dirname, topdown=False):
        for filename in files:
            os.remove(os.path.join(dir, filename))
        for subdir in subdirs:
            path = os.path.join(dir, subdir)
            if os.path.islink(path):
                os.remove(path)
            else:
                os.rmdir(path)

    os.rmdir(dirname)

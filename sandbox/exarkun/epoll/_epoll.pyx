
cdef extern from "stdio.h":
	cdef extern void *malloc(int)
	cdef extern void free(void *)
	cdef extern int close(int)

cdef extern from "errno.h":
	cdef extern int errno
	cdef extern char *strerror(int)

cdef extern from "string.h":
	cdef extern void *memset(void* s, int c, int n)

cdef extern from "stdint.h":
	ctypedef unsigned long uint32_t
	ctypedef unsigned long long uint64_t

cdef extern from "sys/epoll.h":

	cdef enum:
		EPOLL_CTL_ADD = 1
		EPOLL_CTL_DEL = 2
		EPOLL_CTL_MOD = 3

	cdef enum EPOLL_EVENTS:
		EPOLLIN = 0x001
		EPOLLPRI = 0x002
		EPOLLOUT = 0x004
		EPOLLRDNORM = 0x040
		EPOLLRDBAND = 0x080
		EPOLLWRNORM = 0x100
		EPOLLWRBAND = 0x200
		EPOLLMSG = 0x400
		EPOLLERR = 0x008
		EPOLLHUP = 0x010
		EPOLLET = (1 << 31)

	ctypedef union epoll_data_t:
		void *ptr
		int fd
		uint32_t u32
		uint64_t u64

	cdef struct epoll_event:
		uint32_t events
		epoll_data_t data

	int epoll_create(int size)
	int epoll_ctl(int epfd, int op, int fd, epoll_event *event)
	int epoll_wait(int epfd, epoll_event *events, int maxevents, int timeout)

cdef extern from "Python.h":
	ctypedef struct PyThreadState
	cdef extern PyThreadState *PyEval_SaveThread()
	cdef extern void PyEval_RestoreThread(PyThreadState*)

cdef class epoll:
	"""
	Represent a set of file descriptors being monitored for events
	"""

	cdef int fd
	cdef int initialized

	def __init__(self, int size):
		self.fd = epoll_create(size)
		if self.fd == -1:
			raise IOError(errno, strerror(errno))
		self.initialized = 1

	def __dealloc__(self):
		if self.initialized:
			close(self.fd)
			self.initialized = 0

	def close(self):
		if self.initialized:
			if close(self.fd) == -1:
				raise IOError(errno, strerror(errno))
			self.initialized = 0

	def fileno(self):
		return self.fd

	def _control(self, int op, int fd, int events):
		"""Modify the monitored state of a particular file descriptor.

		@type op: C{int}
		@param op: One of CTL_ADD, CTL_DEL, or CTL_MOD

		@type fd: C{int}
		@param fd: File descriptor to modify

		@type events: C{int}
		@param events: A bit set of IN, OUT, PRI, ERR, HUP, and ET.

		@raise IOError: Raised if the underlying epoll_ctl() call fails.
		"""
		cdef int result
		cdef epoll_event evt
		evt.events = events
		evt.data.fd = fd
		result = epoll_ctl(self.fd, op, fd, &evt)
		if result == -1:
			raise IOError(errno, strerror(errno))

	def add(self, int fd, int events):
		"""Begin monitoring the given file descriptor for events.

		@type fd: C{int}
		@param fd: File descriptor to monitor

		@type events: C{int}
		@param events: A bit set of IN, OUT, PRI, ERR, HUP, and ET.

		@raise IOError: Raised if the underlying epoll_ctl() call fails.
		"""
		self._control(CTL_ADD, fd, events)

	def remove(self, int fd):
		"""Stop monitoring the given file descriptor for events.

		@type fd: C{int}
		@param fd: File descriptor not to monitor any more

		@raise IOError: Raised if the underlying epoll_ctl() call fails.
		"""
		self._control(CTL_DEL, fd, 0, None)

	def modify(self, int fd, int events):
		"""Change the monitored state of the given file descriptor.

		@type fd: C{int}
		@param fd: File descriptor to monitor

		@type events: C{int}
		@param events: A bit set of IN, OUT, PRI, ERR, HUP, and ET.

		@raise IOError: Raised if the underlying epoll_ctl()
		call fails.
		"""
		self._control(CTL_MOD, fd, events, None)

	def wait(self, unsigned int maxevents, int timeout):
		cdef epoll_event *events
		cdef int result
		cdef int nbytes
		cdef int fd
		cdef PyThreadState *_save

		nbytes = sizeof(epoll_event) * maxevents
		events = <epoll_event*>malloc(nbytes)
		memset(events, 0, nbytes)
		try:
			fd = self.fd

			_save = PyEval_SaveThread()
			result = epoll_wait(fd, events, maxevents, timeout)
			PyEval_RestoreThread(_save)

			if result == -1:
				raise IOError(result, strerror(result))
			results = []
			for i from 0 <= i < result:
				results.append((events[i].data.fd, <int>events[i].events))
			return results
		finally:
			free(events)

CTL_ADD = EPOLL_CTL_ADD
CTL_DEL = EPOLL_CTL_DEL
CTL_MOD = EPOLL_CTL_MOD

IN = EPOLLIN
OUT = EPOLLOUT
PRI = EPOLLPRI
ERR = EPOLLERR
HUP = EPOLLHUP
ET = EPOLLET

RDNORM = EPOLLRDNORM
RDBAND = EPOLLRDBAND
WRNORM = EPOLLWRNORM
WRBAND = EPOLLWRBAND
MSG = EPOLLMSG

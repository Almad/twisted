import sys, os
from os.path import join
from distutils.core import setup
from distutils.extension import Extension
from distutils import sysconfig

# break abstraction to set g++ as linker - is there better way?
sysconfig._init_posix()
sysconfig._config_vars["CC"] = "g++"
sysconfig._config_vars["LDSHARED"] = "g++ -shared"

setup(
  name = "echo",
  ext_modules=[ 
    Extension("echo", ["echo.cpp"],
              libraries=["boost_python"],
              include_dirs=["../include"]),
    ],
)

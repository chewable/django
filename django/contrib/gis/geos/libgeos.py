"""
 This module houses the ctypes initialization procedures, as well
 as the notice and error handler function callbacks (get called
 when an error occurs in GEOS).

 This module also houses GEOS Pointer utilities, including
 get_pointer_arr(), and GEOM_PTR.
"""
import atexit, os, re, sys
from ctypes import c_char_p, string_at, Structure, CDLL, CFUNCTYPE, POINTER
from django.contrib.gis.geos.error import GEOSException

# NumPy supported?
try:
    from numpy import array, ndarray
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Custom library path set?
try:
    from django.conf import settings
    lib_name = settings.GEOS_LIBRARY_PATH
except (AttributeError, EnvironmentError, ImportError):
    lib_name = None

# Setting the appropriate name for the GEOS-C library, depending on which
# OS and POSIX platform we're running.
if lib_name:
    pass
elif os.name == 'nt':
    # Windows NT library
    lib_name = 'libgeos_c-1.dll'
elif os.name == 'posix':
    platform = os.uname()[0] # Using os.uname()
    if platform == 'Darwin':
        # Mac OSX Shared Library (Thanks Matt!)
        lib_name = 'libgeos_c.dylib'
    else:
        # Attempting to use the .so extension for all other platforms
        lib_name = 'libgeos_c.so'
else:
    raise GEOSException('Unsupported OS "%s"' % os.name)

# Getting the GEOS C library.  The C interface (CDLL) is used for
#  both *NIX and Windows.
# See the GEOS C API source code for more details on the library function calls:
#  http://geos.refractions.net/ro/doxygen_docs/html/geos__c_8h-source.html
lgeos = CDLL(lib_name)

# The notice and error handler C function callback definitions.
#  Supposed to mimic the GEOS message handler (C below):
#  "typedef void (*GEOSMessageHandler)(const char *fmt, ...);"
NOTICEFUNC = CFUNCTYPE(None, c_char_p, c_char_p)
def notice_h(fmt, lst, output_h=sys.stdout):
    try:
        warn_msg = fmt % lst
    except:
        warn_msg = fmt 
    output_h.write('GEOS_NOTICE: %s\n' % warn_msg)
notice_h = NOTICEFUNC(notice_h)

ERRORFUNC = CFUNCTYPE(None, c_char_p, c_char_p)
def error_h(fmt, lst, output_h=sys.stderr):
    try:
        err_msg = fmt % lst
    except:
        err_msg = fmt
    output_h.write('GEOS_ERROR: %s\n' % err_msg)
error_h = ERRORFUNC(error_h)

# The initGEOS routine should be called first, however, that routine takes
#  the notice and error functions as parameters.  Here is the C code that
#  is wrapped:
#  "extern void GEOS_DLL initGEOS(GEOSMessageHandler notice_function, GEOSMessageHandler error_function);"
lgeos.initGEOS(notice_h, error_h)

#### GEOS Geometry C data structures, and utility functions. ####

# Opaque GEOS geometry structures, used for GEOM_PTR and CS_PTR
class GEOSGeom_t(Structure): pass
class GEOSCoordSeq_t(Structure): pass

# Pointers to opaque GEOS geometry structures.
GEOM_PTR = POINTER(GEOSGeom_t)
CS_PTR = POINTER(GEOSCoordSeq_t)

# Used specifically by the GEOSGeom_createPolygon and GEOSGeom_createCollection 
#  GEOS routines
def get_pointer_arr(n):
    "Gets a ctypes pointer array (of length `n`) for GEOSGeom_t opaque pointer."
    GeomArr = GEOM_PTR * n
    return GeomArr()

def geos_version():
    "Returns the string version of GEOS."
    return string_at(lgeos.GEOSversion())

# Regular expression should be able to parse version strings such as
# '3.0.0rc4-CAPI-1.3.3', or '3.0.0-CAPI-1.4.1'
version_regex = re.compile(r'^(?P<version>\d+\.\d+\.\d+)(rc(?P<release_candidate>\d+))?-CAPI-(?P<capi_version>\d+\.\d+\.\d+)$')
def geos_version_info():
    """
    Returns a dictionary containing the various version metadata parsed from
    the GEOS version string, including the version number, whether the version
    is a release candidate (and what number release candidate), and the C API
    version.
    """
    ver = geos_version()
    m = version_regex.match(ver)
    if not m: raise GEOSException('Could not parse version info string "%s"' % ver)
    return dict((key, m.group(key)) for key in ('version', 'release_candidate', 'capi_version'))

# Calling the finishGEOS() upon exit of the interpreter.
atexit.register(lgeos.finishGEOS)

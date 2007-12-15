"""
 This module contains the spatial lookup types, and the get_geo_where_clause()
 routine for Oracle Spatial.
"""
import re
from decimal import Decimal
from django.db import connection
from django.contrib.gis.db.backend.util import SpatialFunction
from django.contrib.gis.measure import Distance
qn = connection.ops.quote_name

# The GML, distance, transform, and union procedures.
ASGML = 'SDO_UTIL.TO_GMLGEOMETRY'
DISTANCE = 'SDO_GEOM.SDO_DISTANCE'
TRANSFORM = 'SDO_CS.TRANSFORM'
UNION = 'SDO_AGGR_UNION'

# We want to get SDO Geometries as WKT because it is much easier to 
# instantiate GEOS proxies from WKT than SDO_GEOMETRY(...) strings.  
# However, this adversely affects performance (i.e., Java is called 
# to convert to WKT on every query).  If someone wishes to write a 
# SDO_GEOMETRY(...) parser in Python, let me know =)
GEOM_SELECT = 'SDO_UTIL.TO_WKTGEOMETRY(%s)'

#### Classes used in constructing Oracle spatial SQL ####
class SDOOperation(SpatialFunction):
    "Base class for SDO* Oracle operations."
    def __init__(self, func, end_subst=") %s '%s'"):
        super(SDOOperation, self).__init__(func, end_subst=end_subst, operator='=', result='TRUE')

class SDODistance(SpatialFunction):
    "Class for Distance queries."
    def __init__(self, op, tolerance=0.05):
        super(SDODistance, self).__init__(DISTANCE, end_subst=', %s) %%s %%s' % tolerance, 
                                          operator=op, result='%%s')

class SDOGeomRelate(SpatialFunction):
    "Class for using SDO_GEOM.RELATE."
    def __init__(self, mask, tolerance=0.05):
        # SDO_GEOM.RELATE(...) has a peculiar argument order: column, mask, geom, tolerance.
        # Moreover, the runction result is the mask (e.g., 'DISJOINT' instead of 'TRUE').
        end_subst = "%s%s) %s '%s'" % (', %%s, ', tolerance, '=', mask)
        beg_subst = "%%s(%%s, '%s'" % mask 
        super(SDOGeomRelate, self).__init__('SDO_GEOM.RELATE', beg_subst=beg_subst, end_subst=end_subst)

class SDORelate(SpatialFunction):
    "Class for using SDO_RELATE."
    masks = 'TOUCH|OVERLAPBDYDISJOINT|OVERLAPBDYINTERSECT|EQUAL|INSIDE|COVEREDBY|CONTAINS|COVERS|ANYINTERACT|ON'
    mask_regex = re.compile(r'^(%s)(\+(%s))*$' % (masks, masks), re.I)
    def __init__(self, mask):
        if not self.mask_regex.match(mask):
            raise ValueError('Invalid %s mask: "%s"' % (self.lookup, mask))
        super(SDORelate, self).__init__('SDO_RELATE', end_subst=", 'mask=%s') = 'TRUE'" % mask)

#### Lookup type mapping dictionaries of Oracle spatial operations ####

# Valid distance types and substitutions
dtypes = (Decimal, Distance, float, int)
DISTANCE_FUNCTIONS = {
    'distance_gt' : (SDODistance('>'), dtypes),
    'distance_gte' : (SDODistance('>='), dtypes),
    'distance_lt' : (SDODistance('<'), dtypes),
    'distance_lte' : (SDODistance('<='), dtypes),
    }

ORACLE_GEOMETRY_FUNCTIONS = {
    'contains' : SDOOperation('SDO_CONTAINS'),
    'coveredby' : SDOOperation('SDO_COVEREDBY'),
    'covers' : SDOOperation('SDO_COVERS'),
    'disjoint' : SDOGeomRelate('DISJOINT'),
    'dwithin' : (SDOOperation('SDO_WITHIN_DISTANCE', end_subst=", %%s, 'distance=%%s') %s '%s'"), dtypes),
    'intersects' : SDOOperation('SDO_OVERLAPBDYINTERSECT'), # TODO: Is this really the same as ST_Intersects()?
    'equals' : SDOOperation('SDO_EQUAL'),
    'exact' : SDOOperation('SDO_EQUAL'),
    'overlaps' : SDOOperation('SDO_OVERLAPS'),
    'same_as' : SDOOperation('SDO_EQUAL'),
    'relate' : (SDORelate, basestring), # Oracle uses a different syntax, e.g., 'mask=inside+touch'
    'touches' : SDOOperation('SDO_TOUCH'),
    'within' : SDOOperation('SDO_INSIDE'),
    }
ORACLE_GEOMETRY_FUNCTIONS.update(DISTANCE_FUNCTIONS)

# This lookup type does not require a mapping.
MISC_TERMS = ['isnull']

# Assacceptable lookup types for Oracle spatial.
ORACLE_SPATIAL_TERMS  = ORACLE_GEOMETRY_FUNCTIONS.keys()
ORACLE_SPATIAL_TERMS += MISC_TERMS
ORACLE_SPATIAL_TERMS = tuple(ORACLE_SPATIAL_TERMS) # Making immutable

#### The `get_geo_where_clause` function for Oracle ####
def get_geo_where_clause(lookup_type, table_prefix, field_name, value):
    "Returns the SQL WHERE clause for use in Oracle spatial SQL construction."
    # Getting the quoted table name as `geo_col`.
    geo_col = '%s.%s' % (qn(table_prefix), qn(field_name))

    # See if a Oracle Geometry function matches the lookup type next
    lookup_info = ORACLE_GEOMETRY_FUNCTIONS.get(lookup_type, False)
    if lookup_info:
        # Lookup types that are tuples take tuple arguments, e.g., 'relate' and 
        # 'dwithin' lookup types.
        if isinstance(lookup_info, tuple):
            # First element of tuple is lookup type, second element is the type
            # of the expected argument (e.g., str, float)
            sdo_op, arg_type = lookup_info

            # Ensuring that a tuple _value_ was passed in from the user
            if not isinstance(value, tuple):
                raise TypeError('Tuple required for `%s` lookup type.' % lookup_type)
            if len(value) != 2: 
                raise ValueError('2-element tuple required for %s lookup type.' % lookup_type)
            
            # Ensuring the argument type matches what we expect.
            if not isinstance(value[1], arg_type):
                raise TypeError('Argument type should be %s, got %s instead.' % (arg_type, type(value[1])))

            if lookup_type == 'relate':
                # The SDORelate class handles construction for these queries, 
                # and verifies the mask argument.
                return sdo_op(value[1]).as_sql(geo_col)
            else:
                # Otherwise, just call the `as_sql` method on the SDOOperation instance.
                return sdo_op.as_sql(geo_col)
        else:
            # Lookup info is a SDOOperation instance, whos `as_sql` method returns
            # the SQL necessary for the geometry function call. For example:  
            #  SDO_CONTAINS("geoapp_country"."poly", SDO_GEOMTRY('POINT(5 23)', 4326)) = 'TRUE'
            return lookup_info.as_sql(geo_col)
    elif lookup_type == 'isnull':
        # Handling 'isnull' lookup type
        return "%s IS %sNULL" % (geo_col, (not value and 'NOT ' or ''))

    raise TypeError("Got invalid lookup_type: %s" % repr(lookup_type))

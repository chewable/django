"""
 This module contains the spatial lookup types, and the get_geo_where_clause()
 routine for PostGIS.
"""
import re
from decimal import Decimal
from django.db import connection
from django.contrib.gis.measure import Distance
from django.contrib.gis.db.backend.postgis.management import postgis_version_tuple
from django.contrib.gis.db.backend.util import SpatialOperation, SpatialFunction
qn = connection.ops.quote_name

# Getting the PostGIS version information
POSTGIS_VERSION, MAJOR_VERSION, MINOR_VERSION1, MINOR_VERSION2 = postgis_version_tuple()

# The supported PostGIS versions.
#  TODO: Confirm tests with PostGIS versions 1.1.x -- should work.  
#        Versions <= 1.0.x do not use GEOS C API, and will not be supported.
if MAJOR_VERSION != 1 or (MAJOR_VERSION == 1 and MINOR_VERSION1 < 1):
    raise Exception('PostGIS version %s not supported.' % POSTGIS_VERSION)

# Versions of PostGIS >= 1.2.2 changed their naming convention to be
#  'SQL-MM-centric' to conform with the ISO standard. Practically, this
#  means that 'ST_' is prefixes geometry function names.
GEOM_FUNC_PREFIX = ''
if MAJOR_VERSION >= 1:
    if (MINOR_VERSION1 > 2 or
        (MINOR_VERSION1 == 2 and MINOR_VERSION2 >= 2)):
        GEOM_FUNC_PREFIX = 'ST_'

    def get_func(func): return '%s%s' % (GEOM_FUNC_PREFIX, func)

    # Custom selection not needed for PostGIS since GEOS geometries may be
    # instantiated directly from the HEXEWKB returned by default.  If
    # WKT is needed for some reason in the future, this value may be changed,
    # 'AsText(%s)'
    GEOM_SELECT = None

    # Functions used by the GeoManager & GeoQuerySet
    ASKML = get_func('AsKML')
    ASGML = get_func('AsGML')
    DISTANCE = get_func('Distance')
    DISTANCE_SPHEROID = get_func('distance_spheroid')
    EXTENT = get_func('extent')
    GEOM_FROM_TEXT = get_func('GeomFromText')
    GEOM_FROM_WKB = get_func('GeomFromWKB')
    TRANSFORM = get_func('Transform')

    # Special cases for union and KML methods.
    if MINOR_VERSION1 < 3:
        UNION = 'GeomUnion'
    else:
        UNION = 'ST_Union'

    if MINOR_VERSION1 == 1:
        ASKML = False
else:
    raise NotImplementedError('PostGIS versions < 1.0 are not supported.')

#### Classes used in constructing PostGIS spatial SQL ####
class PostGISOperator(SpatialOperation):
    "For PostGIS operators (e.g. `&&`, `~`)."
    def __init__(self, operator):
        super(PostGISOperator, self).__init__(operator=operator, beg_subst='%s %s %%s')

class PostGISFunction(SpatialFunction):
    "For PostGIS function calls (e.g., `ST_Contains(table, geom)`)."
    def __init__(self, function, **kwargs):
        super(PostGISFunction, self).__init__(get_func(function), **kwargs)

class PostGISFunctionParam(PostGISFunction):
    "For PostGIS functions that take another parameter (e.g. DWithin, Relate)."
    def __init__(self, func):
        super(PostGISFunctionParam, self).__init__(func, end_subst=', %%s)')

class PostGISDistance(PostGISFunction):
    "For PostGIS distance operations."
    dist_func = 'Distance'
    def __init__(self, operator):
        super(PostGISDistance, self).__init__(self.dist_func, end_subst=') %s %s', 
                                              operator=operator, result='%%s')

class PostGISSphereDistance(PostGISFunction):
    "For PostGIS spherical distance operations."
    dist_func = 'distance_spheroid'
    def __init__(self, operator):
        # An extra parameter in `end_subst` is needed for the spheroid string.
        super(PostGISSphereDistance, self).__init__(self.dist_func, 
                                                    beg_subst='%s(%s, %%s, %%s', 
                                                    end_subst=') %s %s',
                                                    operator=operator, result='%%s')

class PostGISRelate(PostGISFunctionParam):
    "For PostGIS Relate(<geom>, <pattern>) calls."
    pattern_regex = re.compile(r'^[012TF\*]{9}$')
    def __init__(self, pattern):
        if not self.pattern_regex.match(pattern):
            raise ValueError('Invalid intersection matrix pattern "%s".' % pattern)
        super(PostGISRelate, self).__init__('Relate')

#### Lookup type mapping dictionaries of PostGIS operations. ####

# PostGIS-specific operators. The commented descriptions of these
# operators come from Section 6.2.2 of the official PostGIS documentation.
POSTGIS_OPERATORS = {
    # The "&<" operator returns true if A's bounding box overlaps or
    #  is to the left of B's bounding box.
    'overlaps_left' : PostGISOperator('&<'),
    # The "&>" operator returns true if A's bounding box overlaps or
    #  is to the right of B's bounding box.
    'overlaps_right' : PostGISOperator('&>'),
    # The "<<" operator returns true if A's bounding box is strictly
    #  to the left of B's bounding box.
    'left' : PostGISOperator('<<'),
    # The ">>" operator returns true if A's bounding box is strictly
    #  to the right of B's bounding box.
    'right' : PostGISOperator('>>'),
    # The "&<|" operator returns true if A's bounding box overlaps or
    #  is below B's bounding box.
    'overlaps_below' : PostGISOperator('&<|'),
    # The "|&>" operator returns true if A's bounding box overlaps or
    #  is above B's bounding box.
    'overlaps_above' : PostGISOperator('|&>'),
    # The "<<|" operator returns true if A's bounding box is strictly
    #  below B's bounding box.
    'strictly_below' : PostGISOperator('<<|'),
    # The "|>>" operator returns true if A's bounding box is strictly
    # above B's bounding box.
    'strictly_above' : PostGISOperator('|>>'),
    # The "~=" operator is the "same as" operator. It tests actual
    #  geometric equality of two features. So if A and B are the same feature,
    #  vertex-by-vertex, the operator returns true.
    'same_as' : PostGISOperator('~='),
    'exact' : PostGISOperator('~='),
    # The "@" operator returns true if A's bounding box is completely contained
    #  by B's bounding box.
    'contained' : PostGISOperator('@'),
    # The "~" operator returns true if A's bounding box completely contains
    #  by B's bounding box.
    'bbcontains' : PostGISOperator('~'),
    # The "&&" operator returns true if A's bounding box overlaps
    #  B's bounding box.
    'bboverlaps' : PostGISOperator('&&'),
    }

# For PostGIS >= 1.2.2 the following lookup types will do a bounding box query
# first before calling the more computationally expensive GEOS routines (called
# "inline index magic"):
# 'touches', 'crosses', 'contains', 'intersects', 'within', 'overlaps', and
# 'covers'.
POSTGIS_GEOMETRY_FUNCTIONS = {
    'equals' : PostGISFunction('Equals'),
    'disjoint' : PostGISFunction('Disjoint'),
    'touches' : PostGISFunction('Touches'),
    'crosses' : PostGISFunction('Crosses'),
    'within' : PostGISFunction('Within'),
    'overlaps' : PostGISFunction('Overlaps'),
    'contains' : PostGISFunction('Contains'),
    'intersects' : PostGISFunction('Intersects'),
    'relate' : (PostGISRelate, basestring),
    }

# Valid distance types and substitutions
dtypes = (Decimal, Distance, float, int, long)
def get_dist_ops(operator):
    "Returns operations for both regular and spherical distances."
    return (PostGISDistance(operator), PostGISSphereDistance(operator))
DISTANCE_FUNCTIONS = {
    'distance_gt' : (get_dist_ops('>'), dtypes),
    'distance_gte' : (get_dist_ops('>='), dtypes),
    'distance_lt' : (get_dist_ops('<'), dtypes),
    'distance_lte' : (get_dist_ops('<='), dtypes),
    }

if GEOM_FUNC_PREFIX == 'ST_':
    # The ST_DWithin, ST_CoveredBy, and ST_Covers routines become available in 1.2.2+
    POSTGIS_GEOMETRY_FUNCTIONS.update(
        {'coveredby' : PostGISFunction('CoveredBy'),
         'covers' : PostGISFunction('Covers'),
         })
    DISTANCE_FUNCTIONS['dwithin'] = (PostGISFunctionParam('DWithin'), dtypes)

# Distance functions are a part of PostGIS geometry functions.
POSTGIS_GEOMETRY_FUNCTIONS.update(DISTANCE_FUNCTIONS)

# Any other lookup types that do not require a mapping.
MISC_TERMS = ['isnull']

# These are the PostGIS-customized QUERY_TERMS -- a list of the lookup types
#  allowed for geographic queries.
POSTGIS_TERMS = POSTGIS_OPERATORS.keys() # Getting the operators first
POSTGIS_TERMS += POSTGIS_GEOMETRY_FUNCTIONS.keys() # Adding on the Geometry Functions
POSTGIS_TERMS += MISC_TERMS # Adding any other miscellaneous terms (e.g., 'isnull')
POSTGIS_TERMS = tuple(POSTGIS_TERMS) # Making immutable

#### The `get_geo_where_clause` function for PostGIS. ####
def get_geo_where_clause(lookup_type, table_prefix, field, value):
    "Returns the SQL WHERE clause for use in PostGIS SQL construction."
    # Getting the quoted field as `geo_col`.
    geo_col = '%s.%s' % (qn(table_prefix), qn(field.column))
    if lookup_type in POSTGIS_OPERATORS:
        # See if a PostGIS operator matches the lookup type.
        return POSTGIS_OPERATORS[lookup_type].as_sql(geo_col)
    elif lookup_type in POSTGIS_GEOMETRY_FUNCTIONS:
        # See if a PostGIS geometry function matches the lookup type.
        tmp = POSTGIS_GEOMETRY_FUNCTIONS[lookup_type]

        # Lookup types that are tuples take tuple arguments, e.g., 'relate' and 
        # distance lookups.
        if isinstance(tmp, tuple):
            # First element of tuple is the PostGISOperation instance, and the
            # second element is either the type or a tuple of acceptable types
            # that may passed in as further parameters for the lookup type.
            op, arg_type = tmp

            # Ensuring that a tuple _value_ was passed in from the user
            if not isinstance(value, (tuple, list)): 
                raise TypeError('Tuple required for `%s` lookup type.' % lookup_type)
            if len(value) != 2:
                raise ValueError('2-element tuple required or `%s` lookup type.' % lookup_type)
            
            # Ensuring the argument type matches what we expect.
            if not isinstance(value[1], arg_type):
                raise TypeError('Argument type should be %s, got %s instead.' % (arg_type, type(value[1])))

            # For lookup type `relate`, the op instance is not yet created (has
            # to be instantiated here to check the pattern parameter).
            if lookup_type == 'relate': 
                op = op(value[1])
            elif lookup_type in DISTANCE_FUNCTIONS and lookup_type != 'dwithin':
                if field._unit_name == 'degree':
                    # Geodetic distances are only availble from Points to PointFields.
                    if field._geom != 'POINT':
                        raise TypeError('PostGIS spherical operations are only valid on PointFields.')
                    if value[0].geom_typeid != 0:
                        raise TypeError('PostGIS geometry distance parameter is required to be of type Point.')
                    op = op[1]
                else:
                    op = op[0]
        else:
            op = tmp
        # Calling the `as_sql` function on the operation instance.
        return op.as_sql(geo_col)
    elif lookup_type == 'isnull':
        # Handling 'isnull' lookup type
        return "%s IS %sNULL" % (geo_col, (not value and 'NOT ' or ''))

    raise TypeError("Got invalid lookup_type: %s" % repr(lookup_type))

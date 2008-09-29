from types import UnicodeType

def gqn(val):
    """
    The geographic quote name function; used for quoting tables and 
    geometries (they use single rather than the double quotes of the
    backend quotename function).
    """
    if isinstance(val, basestring):
        if isinstance(val, UnicodeType): val = val.encode('ascii')
        return "'%s'" % val
    else:
        return str(val)

class SpatialOperation(object):
    """
    Base class for generating spatial SQL.
    """
    def __init__(self, function='', operator='', result='', beg_subst='', end_subst=''):
        self.function = function
        self.operator = operator
        self.result = result
        self.beg_subst = beg_subst
        try:
            # Try and put the operator and result into to the
            # end substitution.
            self.end_subst = end_subst % (operator, result)
        except TypeError:
            self.end_subst = end_subst

    @property
    def sql_subst(self):
        return ''.join([self.beg_subst, self.end_subst])

    def as_sql(self, geo_col):
        return self.sql_subst % self.params(geo_col)

    def params(self, geo_col):
        return (geo_col, self.operator)

class SpatialFunction(SpatialOperation):
    """
    Base class for generating spatial SQL related to a function.
    """
    def __init__(self, func, beg_subst='%s(%s, %%s', end_subst=')', result='', operator=''):
        # Getting the function prefix.
        kwargs = {'function' : func, 'operator' : operator, 'result' : result,
                  'beg_subst' : beg_subst, 'end_subst' : end_subst,}
        super(SpatialFunction, self).__init__(**kwargs)

    def params(self, geo_col):
        return (self.function, geo_col)

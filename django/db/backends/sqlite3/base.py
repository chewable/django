"""
SQLite3 backend for django.  Requires pysqlite2 (http://pysqlite.org/).
"""

from django.db.backends import util
from pysqlite2 import dbapi2 as Database

DatabaseError = Database.DatabaseError

Database.register_converter("bool", lambda s: str(s) == '1')
Database.register_converter("time", util.typecast_time)
Database.register_converter("date", util.typecast_date)
Database.register_converter("datetime", util.typecast_timestamp)

def utf8rowFactory(cursor, row):
    def utf8(s):
        if type(s) == unicode:
            return s.encode("utf-8")
        else:
            return s
    return [utf8(r) for r in row]

class DatabaseWrapper:
    def __init__(self):
        self.connection = None
        self.queries = []

    def cursor(self):
        from django.conf.settings import DATABASE_NAME, DEBUG
        if self.connection is None:
            self.connection = Database.connect(DATABASE_NAME, detect_types=Database.PARSE_DECLTYPES)
            # register extract and date_trun functions
            self.connection.create_function("django_extract", 2, _sqlite_extract)
            self.connection.create_function("django_date_trunc", 2, _sqlite_date_trunc)
        cursor = self.connection.cursor(factory=SQLiteCursorWrapper)
        cursor.row_factory = utf8rowFactory
        if DEBUG:
            return util.CursorDebugWrapper(cursor, self)
        else:
            return cursor

    def commit(self):
        self.connection.commit()

    def rollback(self):
        if self.connection:
            self.connection.rollback()

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

class SQLiteCursorWrapper(Database.Cursor):
    """
    Django uses "format" style placeholders, but pysqlite2 uses "qmark" style.
    This fixes it -- but note that if you want to use a literal "%s" in a query,
    you'll need to use "%%s" (which I belive is true of other wrappers as well).
    """

    def execute(self, query, params=[]):
        query = self.convert_query(query, len(params))
        return Database.Cursor.execute(self, query, params)

    def executemany(self, query, params=[]):
        query = self.convert_query(query, len(params[0]))
        return Database.Cursor.executemany(self, query, params)

    def convert_query(self, query, num_params):
        # XXX this seems too simple to be correct... is this right?
        return query % tuple("?" * num_params)

supports_constraints = False

def quote_name(name):
    if name.startswith('"') and name.endswith('"'):
        return name # Quoting once is enough.
    return '"%s"' % name

dictfetchone = util.dictfetchone
dictfetchmany = util.dictfetchmany
dictfetchall  = util.dictfetchall

def get_last_insert_id(cursor, table_name, pk_name):
    return cursor.lastrowid

def get_date_extract_sql(lookup_type, table_name):
    # lookup_type is 'year', 'month', 'day'
    # sqlite doesn't support extract, so we fake it with the user-defined
    # function _sqlite_extract that's registered in connect(), above.
    return 'django_extract("%s", %s)' % (lookup_type.lower(), table_name)

def _sqlite_extract(lookup_type, dt):
    try:
        dt = util.typecast_timestamp(dt)
    except (ValueError, TypeError):
        return None
    return str(getattr(dt, lookup_type))

def get_date_trunc_sql(lookup_type, field_name):
    # lookup_type is 'year', 'month', 'day'
    # sqlite doesn't support DATE_TRUNC, so we fake it as above.
    return 'django_date_trunc("%s", %s)' % (lookup_type.lower(), field_name)

def get_limit_offset_sql(limit, offset=None):
    sql = "LIMIT %s" % limit
    if offset and offset != 0:
        sql += " OFFSET %s" % offset
    return sql

def get_random_function_sql():
    return "RANDOM()"

def _sqlite_date_trunc(lookup_type, dt):
    try:
        dt = util.typecast_timestamp(dt)
    except (ValueError, TypeError):
        return None
    if lookup_type == 'year':
        return "%i-01-01 00:00:00" % dt.year
    elif lookup_type == 'month':
        return "%i-%02i-01 00:00:00" % (dt.year, dt.month)
    elif lookup_type == 'day':
        return "%i-%02i-%02i 00:00:00" % (dt.year, dt.month, dt.day)

# SQLite requires LIKE statements to include an ESCAPE clause if the value
# being escaped has a percent or underscore in it.
# See http://www.sqlite.org/lang_expr.html for an explanation.
OPERATOR_MAPPING = {
    'exact': '= %s',
    'iexact': "LIKE %s ESCAPE '\\'",
    'contains': "LIKE %s ESCAPE '\\'",
    'icontains': "LIKE %s ESCAPE '\\'",
    'ne': '!= %s',
    'gt': '> %s',
    'gte': '>= %s',
    'lt': '< %s',
    'lte': '<= %s',
    'startswith': "LIKE %s ESCAPE '\\'",
    'endswith': "LIKE %s ESCAPE '\\'",
    'istartswith': "LIKE %s ESCAPE '\\'",
    'iendswith': "LIKE %s ESCAPE '\\'",
}

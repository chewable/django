from django.db.backends.ansi import sql
builder = sql.SchemaBuilder()

DATA_TYPES = {
    'AutoField':         'number(38)',
    'BooleanField':      'number(1)',
    'CharField':         'varchar2(%(maxlength)s)',
    'CommaSeparatedIntegerField': 'varchar2(%(maxlength)s)',
    'DateField':         'date',
    'DateTimeField':     'date',
    'FileField':         'varchar2(100)',
    'FilePathField':     'varchar2(100)',
    'FloatField':        'number(%(max_digits)s, %(decimal_places)s)',
    'ImageField':        'varchar2(100)',
    'IntegerField':      'integer',
    'IPAddressField':    'char(15)',
    'ManyToManyField':   None,
    'NullBooleanField':  'integer',
    'OneToOneField':     'integer',
    'PhoneNumberField':  'varchar(20)',
    'PositiveIntegerField': 'integer',
    'PositiveSmallIntegerField': 'smallint',
    'SlugField':         'varchar(50)',
    'SmallIntegerField': 'smallint',
    'TextField':         'long',
    'TimeField':         'timestamp',
    'URLField':          'varchar(200)',
    'USStateField':      'varchar(2)',
}

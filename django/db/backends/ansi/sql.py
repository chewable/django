"""ANSISQL schema manipulation functions and classes
"""
import os
import re
from django.db import models

# For Python 2.3
if not hasattr(__builtins__, 'set'):
    from sets import Set as set

# default dummy style
class dummy:
    def __getattr__(self, attr):
        return lambda x: x
default_style = dummy()
del dummy

class BoundStatement(object):
    """Represents an SQL statement that is to be executed, at some point in
    the future, using a specific database connection.
    """
    def __init__(self, sql, connection):
        self.sql = sql
        self.connection = connection

    def execute(self):
        cursor = self.connection.cursor()
        cursor.execute(self.sql)

    def __repr__(self):
        return "BoundStatement(%r)" % self.sql

    def __str__(self):
        return self.sql

    def __eq__(self, other):
        return self.sql == other.sql and self.connection == other.connection

class SchemaBuilder(object):
    """Basic ANSI SQL schema element builder. Instances of this class may be
    used to construct SQL expressions that create or drop schema elements such
    as tables, indexes and (for those backends that support them) foreign key
    or other constraints.
    """
    def __init__(self):
        # models that I have created
        self.models_already_seen = set()
        # model references, keyed by the referrent model
        self.references = {}
        # table cache; set to short-circuit table lookups
        self.tables = None
        
    def get_create_table(self, model, style=None):
        """Construct and return the SQL expression(s) needed to create the
        table for the given model, and any constraints on that
        table. The return value is a 2-tuple. The first element of the tuple
        is a list of BoundStatements that may be executed immediately. The
        second is a dict of BoundStatements representing constraints that
        can't be executed immediately because (for instance) the referent
        table does not exist, keyed by the model class they reference.
        """
        if style is None:
            style = default_style
        self.models_already_seen.add(model)
        
        opts = model._meta
        info = opts.connection_info
        backend = info.backend
        quote_name = backend.quote_name
        data_types = info.get_creation_module().DATA_TYPES
        table_output = []

        # pending field references, keyed by the model class
        # they reference
        pending_references = {}

        # pending statements to execute, keyed by
        # the model class they reference
        pending = {}
        for f in opts.fields:
            if isinstance(f, models.ForeignKey):
                rel_field = f.rel.get_related_field()
                data_type = self.get_rel_data_type(rel_field)
            else:
                rel_field = f
                data_type = f.get_internal_type()
            col_type = data_types[data_type]
            if col_type is not None:
                # Make the definition (e.g. 'foo VARCHAR(30)') for this field.
                field_output = [style.SQL_FIELD(quote_name(f.column)),
                    style.SQL_COLTYPE(col_type % rel_field.__dict__)]
                field_output.append(style.SQL_KEYWORD(
                        '%sNULL' % (not f.null and 'NOT ' or '')))
                if f.unique:
                    field_output.append(style.SQL_KEYWORD('UNIQUE'))
                if f.primary_key:
                    field_output.append(style.SQL_KEYWORD('PRIMARY KEY'))
                if f.rel:
                    if f.rel.to in self.models_already_seen:
                        field_output.append(
                            style.SQL_KEYWORD('REFERENCES') + ' ' + 
                            style.SQL_TABLE(
                                quote_name(f.rel.to._meta.db_table)) + ' (' + 
                            style.SQL_FIELD(
                                quote_name(f.rel.to._meta.get_field(
                                        f.rel.field_name).column)) + ')'
                        )
                    else:
                        # We haven't yet created the table to which this field
                        # is related, so save it for later.
                        pending_references.setdefault(f.rel.to, []).append(f)
                table_output.append(' '.join(field_output))
        if opts.order_with_respect_to:
            table_output.append(style.SQL_FIELD(quote_name('_order')) + ' ' + \
                style.SQL_COLTYPE(data_types['IntegerField']) + ' ' + \
                style.SQL_KEYWORD('NULL'))
        for field_constraints in opts.unique_together:
            table_output.append(style.SQL_KEYWORD('UNIQUE') + ' (%s)' % \
                ", ".join([quote_name(style.SQL_FIELD(
                                opts.get_field(f).column))
                           for f in field_constraints]))

        full_statement = [style.SQL_KEYWORD('CREATE TABLE') + ' ' + 
                          style.SQL_TABLE(quote_name(opts.db_table)) + ' (']
        for i, line in enumerate(table_output): # Combine and add commas.
            full_statement.append('    %s%s' %
                                  (line, i < len(table_output)-1 and ',' or ''))
        full_statement.append(');')
        create = [BoundStatement('\n'.join(full_statement), opts.connection)]

        if (pending_references and
            backend.supports_constraints):
            for rel_class, cols in pending_references.items():
                for f in cols:
                    rel_opts = rel_class._meta
                    r_table = rel_opts.db_table
                    r_col = f.column
                    table = opts.db_table
                    col = opts.get_field(f.rel.field_name).column
                    sql = style.SQL_KEYWORD('ALTER TABLE') + ' %s ADD CONSTRAINT %s FOREIGN KEY (%s) REFERENCES %s (%s);' % \
                        (quote_name(table),
                        quote_name('%s_referencing_%s_%s' % (r_col, r_table, col)),
                        quote_name(r_col), quote_name(r_table), quote_name(col))
                    pending.setdefault(rel_class, []).append(
                        BoundStatement(sql, opts.connection))
        return (create, pending)    

    def get_create_indexes(self, model, style=None):
        """Construct and return SQL statements needed to create the indexes for
        a model. Returns a list of BoundStatements.
        """
        if style is None:
            style = default_style
        info = model._meta.connection_info
        backend = info.backend
        connection = info.connection
        output = []
        for f in model._meta.fields:
            if f.db_index:
                unique = f.unique and 'UNIQUE ' or ''
                output.append(
                    BoundStatement(
                        ' '.join(
                            [style.SQL_KEYWORD('CREATE %sINDEX' % unique), 
                             style.SQL_TABLE('%s_%s' %
                                             (model._meta.db_table, f.column)),
                             style.SQL_KEYWORD('ON'), 
                             style.SQL_TABLE(
                                    backend.quote_name(model._meta.db_table)),
                             "(%s);" % style.SQL_FIELD(
                                    backend.quote_name(f.column))]),
                        connection)
                    )
        return output

    def get_create_many_to_many(self, model, style=None):
        """Construct and return SQL statements needed to create the
        tables and relationships for all many-to-many relations
        defined in the model. Returns a list of bound statments. Note
        that these statements should only be executed after all models
        for an app have been created.
        """
        if style is None:
            style = default_style
        info = model._meta.connection_info
        quote_name = info.backend.quote_name
        connection = info.connection
        data_types = info.get_creation_module().DATA_TYPES
        opts = model._meta

        # statements to execute, keyed by the other model
        output = {}       
        for f in opts.many_to_many:
            if not isinstance(f.rel, models.GenericRel):
                table_output = [
                    style.SQL_KEYWORD('CREATE TABLE') + ' ' + \
                    style.SQL_TABLE(quote_name(f.m2m_db_table())) + ' (']
                table_output.append('    %s %s %s,' % \
                    (style.SQL_FIELD(quote_name('id')),
                    style.SQL_COLTYPE(data_types['AutoField']),
                    style.SQL_KEYWORD('NOT NULL PRIMARY KEY')))
                table_output.append('    %s %s %s %s (%s),' % \
                    (style.SQL_FIELD(quote_name(f.m2m_column_name())),
                    style.SQL_COLTYPE(data_types[self.get_rel_data_type(opts.pk)] % opts.pk.__dict__),
                    style.SQL_KEYWORD('NOT NULL REFERENCES'),
                    style.SQL_TABLE(quote_name(opts.db_table)),
                    style.SQL_FIELD(quote_name(opts.pk.column))))
                table_output.append('    %s %s %s %s (%s),' % \
                    (style.SQL_FIELD(quote_name(f.m2m_reverse_name())),
                    style.SQL_COLTYPE(data_types[self.get_rel_data_type(f.rel.to._meta.pk)] % f.rel.to._meta.pk.__dict__),
                    style.SQL_KEYWORD('NOT NULL REFERENCES'),
                    style.SQL_TABLE(quote_name(f.rel.to._meta.db_table)),
                    style.SQL_FIELD(quote_name(f.rel.to._meta.pk.column))))
                table_output.append('    %s (%s, %s)' % \
                    (style.SQL_KEYWORD('UNIQUE'),
                    style.SQL_FIELD(quote_name(f.m2m_column_name())),
                    style.SQL_FIELD(quote_name(f.m2m_reverse_name()))))
                table_output.append(');')
                output.setdefault(f.rel.to, []).append(
                    BoundStatement('\n'.join(table_output), connection))
        return output

    def get_drop_table(self, model, cascade=False, style=None):
        """Construct and return the SQL statment(s) needed to drop a model's
        table. If cascade is true, then output additional statments to drop any
        many-to-many tables that this table created and any foreign keys that
        reference this table.
        """
        if style is None:
            style = default_style
        opts = model._meta
        info = opts.connection_info
        db_table = opts.db_table
        backend = info.backend
        qn = backend.quote_name
        output = []
        output.append(BoundStatement(
                '%s %s;' % (style.SQL_KEYWORD('DROP TABLE'),
                            style.SQL_TABLE(qn(db_table))),
                info.connection))

        if cascade:
            # deal with others that might have a foreign key TO me: alter
            # their tables to drop the constraint
            if backend.supports_constraints:
                references_to_delete = self.get_references()
                if model in references_to_delete:
                    for rel_class, f in references_to_delete[model]:
                        table = rel_class._meta.db_table
                        if not self.table_exists(info, table):
                            continue
                        col = f.column
                        r_table = opts.db_table
                        r_col = opts.get_field(f.rel.field_name).column
                        output.append(BoundStatement(
                            '%s %s %s %s;' % 
                            (style.SQL_KEYWORD('ALTER TABLE'),
                             style.SQL_TABLE(qn(table)),
                             style.SQL_KEYWORD(
                                        backend.get_drop_foreignkey_sql()),
                             style.SQL_FIELD(qn("%s_referencing_%s_%s" %
                                                (col, r_table, r_col)))),
                            info.connection))
                    del references_to_delete[model]
            # many to many: drop any many-many tables that are my
            # responsiblity
            for f in opts.many_to_many:
                if not isinstance(f.rel, models.GenericRel):
                    output.append(BoundStatement(
                            '%s %s;' %
                            (style.SQL_KEYWORD('DROP TABLE'),
                             style.SQL_TABLE(qn(f.m2m_db_table()))),
                            info.connection))
        # Reverse it, to deal with table dependencies.        
        output.reverse()
        return output
        
    def get_initialdata(self, model):
        opts = model._meta
        info = opts.connection_info
        settings = info.connection.settings
        backend = info.backend
        app_dir = self.get_initialdata_path(model)
        output = []

        # Some backends can't execute more than one SQL statement at a time.
        # We'll split the initial data into individual statements unless
        # backend.supports_compound_statements.
        statements = re.compile(r";[ \t]*$", re.M)

        # Find custom SQL, if it's available.
        sql_files = [os.path.join(app_dir, "%s.%s.sql" % (opts.object_name.lower(), settings.DATABASE_ENGINE)),
                     os.path.join(app_dir, "%s.sql" % opts.object_name.lower())]
        for sql_file in sql_files:
            if os.path.exists(sql_file):
                fp = open(sql_file)
                if backend.supports_compound_statements:
                    output.append(BoundStatement(fp.read(), info.connection))
                else:                                 
                    for statement in statements.split(fp.read()):
                        if statement.strip():
                            output.append(BoundStatement(statement + ";",
                                                         info.connection))
                fp.close()
        return output

    def get_initialdata_path(self, model):
        """Get the path from which to load sql initial data files for a model.
        """
        return os.path.normpath(os.path.join(os.path.dirname(
                    models.get_app(model._meta.app_label).__file__), 'sql'))
            
    def get_rel_data_type(self, f):
        return (f.get_internal_type() in ('AutoField', 'PositiveIntegerField',
                                          'PositiveSmallIntegerField')) \
                                          and 'IntegerField' \
                                          or f.get_internal_type()
    
    def get_references(self):
        """Fill (if needed) and return the reference cache.
        """
        if self.references:
            return self.references
        for klass in models.get_models():
            for f in klass._meta.fields:
                if f.rel:
                    self.references.setdefault(f.rel.to, []).append((klass, f))
        return self.references

    def get_table_list(self, connection_info):
        """Get list of tables accessible via the connection described by
        connection_info.
        """
        if self.tables is not None:
            return self.tables
        cursor = info.connection.cursor()
        introspection = connection_info.get_introspection_module()
        return introspection.get_table_list(cursor)        
    
    def table_exists(self, connection_info, table):
        tables = self.get_table_list(connection_info)
        return table in tables

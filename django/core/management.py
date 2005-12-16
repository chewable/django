# Django management-related functions, including "CREATE TABLE" generation and
# development-server initialization.

import django
from django.core.exceptions import ImproperlyConfigured
import os, re, sys, textwrap
from optparse import OptionParser

MODULE_TEMPLATE = '''    {%% if perms.%(app)s.%(addperm)s or perms.%(app)s.%(changeperm)s %%}
    <tr>
        <th>{%% if perms.%(app)s.%(changeperm)s %%}<a href="%(app)s/%(mod)s/">{%% endif %%}%(name)s{%% if perms.%(app)s.%(changeperm)s %%}</a>{%% endif %%}</th>
        <td class="x50">{%% if perms.%(app)s.%(addperm)s %%}<a href="%(app)s/%(mod)s/add/" class="addlink">{%% endif %%}Add{%% if perms.%(app)s.%(addperm)s %%}</a>{%% endif %%}</td>
        <td class="x75">{%% if perms.%(app)s.%(changeperm)s %%}<a href="%(app)s/%(mod)s/" class="changelink">{%% endif %%}Change{%% if perms.%(app)s.%(changeperm)s %%}</a>{%% endif %%}</td>
    </tr>
    {%% endif %%}'''

APP_ARGS = '[modelmodule ...]'

# Use django.__path__[0] because we don't know which directory django into
# which has been installed.
PROJECT_TEMPLATE_DIR = os.path.join(django.__path__[0], 'conf', '%s_template')

INVALID_PROJECT_NAMES = ('django', 'test')

def _get_packages_insert(app_label):
    from django.db import backend
    return "INSERT INTO %s (%s, %s) VALUES ('%s', '%s');" % \
        (backend.quote_name('packages'), backend.quote_name('label'), backend.quote_name('name'),
        app_label, app_label)

def _get_permission_codename(action, opts):
    return '%s_%s' % (action, opts.object_name.lower())

def _get_all_permissions(opts):
    "Returns (codename, name) for all permissions in the given opts."
    perms = []
    if opts.admin:
        for action in ('add', 'change', 'delete'):
            perms.append((_get_permission_codename(action, opts), 'Can %s %s' % (action, opts.verbose_name)))
    return perms + list(opts.permissions)

def _get_permission_insert(name, codename, opts):
    from django.db import backend
    return "INSERT INTO %s (%s, %s, %s) VALUES ('%s', '%s', '%s');" % \
        (backend.quote_name('auth_permissions'), backend.quote_name('name'), backend.quote_name('package'),
        backend.quote_name('codename'), name.replace("'", "''"), opts.app_label, codename)

def _get_contenttype_insert(opts):
    from django.db import backend
    return "INSERT INTO %s (%s, %s, %s) VALUES ('%s', '%s', '%s');" % \
        (backend.quote_name('content_types'), backend.quote_name('name'), backend.quote_name('package'),
        backend.quote_name('python_module_name'), opts.verbose_name, opts.app_label, opts.module_name)

def _is_valid_dir_name(s):
    return bool(re.search(r'^\w+$', s))

# If the foreign key points to an AutoField, the foreign key should be an
# IntegerField, not an AutoField. Otherwise, the foreign key should be the same
# type of field as the field to which it points.
get_rel_data_type = lambda f: (f.get_internal_type() == 'AutoField') and 'IntegerField' or f.get_internal_type()

def get_sql_create(mod):
    "Returns a list of the CREATE TABLE SQL statements for the given module."
    from django.db import backend, get_creation_module, models
    data_types = get_creation_module().DATA_TYPES
    final_output = []
    opts_output = set()
    pending_references = {} 
    for klass in mod._MODELS:
        opts = klass._meta
        table_output = []
        for f in opts.fields:
            if isinstance(f, models.ForeignKey):
                rel_field = f.rel.get_related_field()
                data_type = get_rel_data_type(rel_field)
            else:
                rel_field = f
                data_type = f.get_internal_type()
            col_type = data_types[data_type]
            if col_type is not None:
                field_output = [backend.quote_name(f.column), col_type % rel_field.__dict__]
                field_output.append('%sNULL' % (not f.null and 'NOT ' or ''))
                if f.unique:
                    field_output.append('UNIQUE')
                if f.primary_key:
                    field_output.append('PRIMARY KEY')
                if f.rel:
                     if f.rel.to in opts_output:
                         field_output.append('REFERENCES %s (%s)' % \
                             (db.db.quote_name(f.rel.to._meta.db_table),
                             db.db.quote_name(f.rel.to._meta.get_field(f.rel.field_name).column)))
                     else:
                         pr = pending_references.setdefault(f.rel.to._meta, []).append( (opts, f) )
                table_output.append(' '.join(field_output))
        if opts.order_with_respect_to:
            table_output.append('%s %s NULL' % (backend.quote_name('_order'), data_types['IntegerField']))
        for field_constraints in opts.unique_together:
            table_output.append('UNIQUE (%s)' % \
                ", ".join([backend.quote_name(opts.get_field(f).column) for f in field_constraints]))

        full_statement = ['CREATE TABLE %s (' % backend.quote_name(opts.db_table)]
        for i, line in enumerate(table_output): # Combine and add commas.
            full_statement.append('    %s%s' % (line, i < len(table_output)-1 and ',' or ''))
        full_statement.append(');')
        final_output.append('\n'.join(full_statement))
        if opts in pending_references:
            for (rel_opts, f) in pending_references[opts]:
                r_table = rel_opts.db_table
                r_col = f.column
                table =  opts.db_table
                col = opts.get_field(f.rel.field_name).column
                final_output.append( 'ALTER TABLE %s ADD CONSTRAINT %s FOREIGN KEY (%s) REFERENCES %s (%s);'  % \
                                     (backend.quote_name(r_table), 
                                      backend.quote_name("%s_referencing_%s_%s" % (r_col,table,col)),
                                      backend.quote_name(r_col), backend.quote_name(table),backend.quote_name(col))
                                     )
            del pending_references[opts]
        opts_output.add(opts)

    for klass in mod._MODELS:
        opts = klass._meta
        for f in opts.many_to_many:
            table_output = ['CREATE TABLE %s (' % backend.quote_name(f.get_m2m_db_table(opts))]
            table_output.append('    %s %s NOT NULL PRIMARY KEY,' % (backend.quote_name('id'), data_types['AutoField']))
            table_output.append('    %s %s NOT NULL REFERENCES %s (%s),' % \
                (backend.quote_name(opts.object_name.lower() + '_id'),
                data_types[get_rel_data_type(opts.pk)] % opts.pk.__dict__,
                backend.quote_name(opts.db_table),
                backend.quote_name(opts.pk.column)))
            table_output.append('    %s %s NOT NULL REFERENCES %s (%s),' % \
                (backend.quote_name(f.rel.to._meta.object_name.lower() + '_id'),
                data_types[get_rel_data_type(f.rel.to._meta.pk)] % f.rel.to._meta.pk.__dict__,
                backend.quote_name(f.rel.to._meta.db_table),
                backend.quote_name(f.rel.to._meta.pk.column)))
            table_output.append('    UNIQUE (%s, %s)' % \
                (backend.quote_name(opts.object_name.lower() + '_id'),
                backend.quote_name(f.rel.to._meta.object_name.lower() + '_id')))
            table_output.append(');')
            final_output.append('\n'.join(table_output))
    return final_output
get_sql_create.help_doc = "Prints the CREATE TABLE SQL statements for the given model module name(s)."
get_sql_create.args = APP_ARGS

def get_sql_delete(mod):
    "Returns a list of the DROP TABLE SQL statements for the given module."
    from django.db import backend, connection

    try:
        cursor = connection.cursor()
    except:
        cursor = None

    # Determine whether the admin log table exists. It only exists if the
    # person has installed the admin app.
    try:
        if cursor is not None:
            # Check whether the table exists.
            cursor.execute("SELECT 1 FROM %s LIMIT 1" % backend.quote_name('django_admin_log'))
    except:
        # The table doesn't exist, so it doesn't need to be dropped.
        connection.rollback()
        admin_log_exists = False
    else:
        admin_log_exists = True

    output = []

    # Output DROP TABLE statements for standard application tables.
    to_delete = set()
    
    references_to_delete = {}
    for klass in mod._MODELS:
        try:
            if cursor is not None:
                # Check whether the table exists.
                cursor.execute("SELECT 1 FROM %s LIMIT 1" % backend.quote_name(klass._meta.db_table))
        except:
            # The table doesn't exist, so it doesn't need to be dropped.
            connection.rollback()
        else:
            opts = klass._meta
            for f in opts.fields:
                if f.rel and f.rel.to not in to_delete:
                    refs = references_to_delete.get(f.rel.to, [])
                    refs.append( (opts, f) )
                    references_to_delete[f.rel.to] = refs

            to_delete.add(opts)
             
    for klass in mod._MODELS:
         try:
             if cursor is not None:
                 # Check whether the table exists.
                 cursor.execute("SELECT 1 FROM %s LIMIT 1" % db.db.quote_name(klass._meta.db_table))
         except:
             # The table doesn't exist, so it doesn't need to be dropped.
             db.db.rollback()
         else:
             output.append("DROP TABLE %s;" % db.db.quote_name(klass._meta.db_table))
             if references_to_delete.has_key(klass._meta):
                 for opts, f in references_to_delete[klass._meta]:
                     col = f.column
                     table = opts.db_table
                     r_table = f.rel.to._meta.db_table
                     r_col = f.rel.to.get_field(f.rel.field_name).column

                     output.append( 'ALTER TABLE %s DROP CONSTRAINT %s;'  % \
                                          (db.db.quote_name(table),
                                           db.db.quote_name("%s_referencing_%s_%s" % (col,r_table,r_col))
                                          ))

    # Output DROP TABLE statements for many-to-many tables.
    for klass in mod._MODELS:
        opts = klass._meta
        for f in opts.many_to_many:
            try:
                if cursor is not None:
                    cursor.execute("SELECT 1 FROM %s LIMIT 1" % backend.quote_name(f.get_m2m_db_table(opts)))
            except:
                connection.rollback()
            else:
                output.append("DROP TABLE %s;" % backend.quote_name(f.get_m2m_db_table(opts)))

    app_label = mod._MODELS[0]._meta.app_label

    # Delete from packages, auth_permissions, content_types.
    output.append("DELETE FROM %s WHERE %s = '%s';" % \
        (backend.quote_name('packages'), backend.quote_name('label'), app_label))
    output.append("DELETE FROM %s WHERE %s = '%s';" % \
        (backend.quote_name('auth_permissions'), backend.quote_name('package'), app_label))
    output.append("DELETE FROM %s WHERE %s = '%s';" % \
        (backend.quote_name('content_types'), backend.quote_name('package'), app_label))

    # Delete from the admin log.
    if cursor is not None:
        cursor.execute("SELECT %s FROM %s WHERE %s = %%s" % \
            (backend.quote_name('id'), backend.quote_name('content_types'),
            backend.quote_name('package')), [app_label])
        if admin_log_exists:
            for row in cursor.fetchall():
                output.append("DELETE FROM %s WHERE %s = %s;" % \
                    (backend.quote_name('django_admin_log'), backend.quote_name('content_type_id'), row[0]))

    # Close database connection explicitly, in case this output is being piped
    # directly into a database client, to avoid locking issues.
    cursor.close()
    connection.close()

    return output[::-1] # Reverse it, to deal with table dependencies.
get_sql_delete.help_doc = "Prints the DROP TABLE SQL statements for the given model module name(s)."
get_sql_delete.args = APP_ARGS

def get_sql_reset(mod):
    "Returns a list of the DROP TABLE SQL, then the CREATE TABLE SQL, for the given module."
    return get_sql_delete(mod) + get_sql_all(mod)
get_sql_reset.help_doc = "Prints the DROP TABLE SQL, then the CREATE TABLE SQL, for the given model module name(s)."
get_sql_reset.args = APP_ARGS

def get_sql_initial_data(mod):
    "Returns a list of the initial INSERT SQL statements for the given module."
    from django.conf.settings import DATABASE_ENGINE
    output = []
    app_label = mod._MODELS[0]._meta.app_label
    output.append(_get_packages_insert(app_label))
    app_dir = os.path.normpath(os.path.join(os.path.dirname(mod.__file__), '..', 'sql'))
    for klass in mod._MODELS:
        opts = klass._meta

        # Add custom SQL, if it's available.
        sql_files = [os.path.join(app_dir, opts.module_name + '.' + DATABASE_ENGINE +  '.sql'),
                     os.path.join(app_dir, opts.module_name + '.sql')]
        for sql_file in sql_files:
            if os.path.exists(sql_file):
                fp = open(sql_file)
                output.append(fp.read())
                fp.close()

        # Content types.
        output.append(_get_contenttype_insert(opts))
        # Permissions.
        for codename, name in _get_all_permissions(opts):
            output.append(_get_permission_insert(name, codename, opts))
    return output
get_sql_initial_data.help_doc = "Prints the initial INSERT SQL statements for the given model module name(s)."
get_sql_initial_data.args = APP_ARGS

def get_sql_sequence_reset(mod):
    "Returns a list of the SQL statements to reset PostgreSQL sequences for the given module."
    from django.db import backend, models
    output = []
    for klass in mod._MODELS:
        for f in klass._meta.fields:
            if isinstance(f, models.AutoField):
                output.append("SELECT setval('%s_%s_seq', (SELECT max(%s) FROM %s));" % \
                    (klass._meta.db_table, f.column, backend.quote_name(f.column),
                    backend.quote_name(klass._meta.db_table)))
        for f in klass._meta.many_to_many:
            output.append("SELECT setval('%s_id_seq', (SELECT max(%s) FROM %s));" % \
                (f.get_m2m_db_table(klass._meta), backend.quote_name('id'), f.get_m2m_db_table(klass._meta)))
    return output
get_sql_sequence_reset.help_doc = "Prints the SQL statements for resetting PostgreSQL sequences for the given model module name(s)."
get_sql_sequence_reset.args = APP_ARGS

def get_sql_indexes(mod):
    "Returns a list of the CREATE INDEX SQL statements for the given module."
    from django.db import backend
    output = []
    for klass in mod._MODELS:
        for f in klass._meta.fields:
            if f.db_index:
                unique = f.unique and "UNIQUE " or ""
                output.append("CREATE %sINDEX %s_%s ON %s (%s);" % \
                    (unique, klass._meta.db_table, f.column,
                    backend.quote_name(klass._meta.db_table), backend.quote_name(f.column)))
    return output
get_sql_indexes.help_doc = "Prints the CREATE INDEX SQL statements for the given model module name(s)."
get_sql_indexes.args = APP_ARGS

def get_sql_all(mod):
    "Returns a list of CREATE TABLE SQL and initial-data insert for the given module."
    return get_sql_create(mod) + get_sql_initial_data(mod)
get_sql_all.help_doc = "Prints the CREATE TABLE and initial-data SQL statements for the given model module name(s)."
get_sql_all.args = APP_ARGS

def has_no_records(cursor):
    "Returns True if the cursor, having executed a query, returned no records."
    # This is necessary due to an inconsistency in the DB-API spec.
    # cursor.rowcount can be -1 (undetermined), according to
    # http://www.python.org/peps/pep-0249.html
    if cursor.rowcount < 0:
        return cursor.fetchone() is None
    return cursor.rowcount < 1

def database_check(mod):
    "Checks that everything is properly installed in the database for the given module."
    from django.db import backend, connection
    cursor = connection.cursor()
    app_label = mod._MODELS[0]._meta.app_label

    # Check that the package exists in the database.
    cursor.execute("SELECT 1 FROM %s WHERE %s = %%s" % \
        (backend.quote_name('packages'), backend.quote_name('label')), [app_label])
    if has_no_records(cursor):
#         sys.stderr.write("The '%s' package isn't installed.\n" % app_label)
        print _get_packages_insert(app_label)

    # Check that the permissions and content types are in the database.
    perms_seen = {}
    contenttypes_seen = {}
    for klass in mod._MODELS:
        opts = klass._meta
        perms = _get_all_permissions(opts)
        perms_seen.update(dict(perms))
        contenttypes_seen[opts.module_name] = 1
        for codename, name in perms:
            cursor.execute("SELECT 1 FROM %s WHERE %s = %%s AND %s = %%s" % \
                (backend.quote_name('auth_permissions'), backend.quote_name('package'),
                backend.quote_name('codename')), (app_label, codename))
            if has_no_records(cursor):
#                 sys.stderr.write("The '%s.%s' permission doesn't exist.\n" % (app_label, codename))
                print _get_permission_insert(name, codename, opts)
        cursor.execute("SELECT 1 FROM %s WHERE %s = %%s AND %s = %%s" % \
            (backend.quote_name('content_types'), backend.quote_name('package'),
            backend.quote_name('python_module_name')), (app_label, opts.module_name))
        if has_no_records(cursor):
#             sys.stderr.write("The '%s.%s' content type doesn't exist.\n" % (app_label, opts.module_name))
            print _get_contenttype_insert(opts)

    # Check that there aren't any *extra* permissions in the DB that the model
    # doesn't know about.
    cursor.execute("SELECT %s FROM %s WHERE %s = %%s" % \
        (backend.quote_name('codename'), backend.quote_name('auth_permissions'),
        backend.quote_name('package')), (app_label,))
    for row in cursor.fetchall():
        try:
            perms_seen[row[0]]
        except KeyError:
#             sys.stderr.write("A permission called '%s.%s' was found in the database but not in the model.\n" % (app_label, row[0]))
            print "DELETE FROM %s WHERE %s='%s' AND %s = '%s';" % \
                (backend.quote_name('auth_permissions'), backend.quote_name('package'),
                app_label, backend.quote_name('codename'), row[0])

    # Check that there aren't any *extra* content types in the DB that the
    # model doesn't know about.
    cursor.execute("SELECT %s FROM %s WHERE %s = %%s" % \
        (backend.quote_name('python_module_name'), backend.quote_name('content_types'),
        backend.quote_name('package')), (app_label,))
    for row in cursor.fetchall():
        try:
            contenttypes_seen[row[0]]
        except KeyError:
#             sys.stderr.write("A content type called '%s.%s' was found in the database but not in the model.\n" % (app_label, row[0]))
            print "DELETE FROM %s WHERE %s='%s' AND %s = '%s';" % \
                (backend.quote_name('content_types'), backend.quote_name('package'),
                app_label, backend.quote_name('python_module_name'), row[0])
database_check.help_doc = "Checks that everything is installed in the database for the given model module name(s) and prints SQL statements if needed."
database_check.args = APP_ARGS

def get_admin_index(mod):
    "Returns admin-index template snippet (in list form) for the given module."
    from django.utils.text import capfirst
    output = []
    app_label = mod._MODELS[0]._meta.app_label
    output.append('{%% if perms.%s %%}' % app_label)
    output.append('<div class="module"><h2>%s</h2><table>' % app_label.title())
    for klass in mod._MODELS:
        if klass._meta.admin:
            output.append(MODULE_TEMPLATE % {
                'app': app_label,
                'mod': klass._meta.module_name,
                'name': capfirst(klass._meta.verbose_name_plural),
                'addperm': klass._meta.get_add_permission(),
                'changeperm': klass._meta.get_change_permission(),
            })
    output.append('</table></div>')
    output.append('{% endif %}')
    return output
get_admin_index.help_doc = "Prints the admin-index template snippet for the given model module name(s)."
get_admin_index.args = APP_ARGS

def init():
    "Initializes the database with auth and core."
    try:
        from django.db import backend, connection, models
        from django.models import auth, core
        cursor = connection.cursor()
        for sql in get_sql_create(core) + get_sql_create(auth) + get_sql_initial_data(core) + get_sql_initial_data(auth):
            cursor.execute(sql)
        cursor.execute("INSERT INTO %s (%s, %s) VALUES ('example.com', 'Example site')" % \
            (backend.quote_name(core.Site._meta.db_table), backend.quote_name('domain'),
            backend.quote_name('name')))
    except Exception, e:
        import traceback
        sys.stderr.write("Error: The database couldn't be initialized.\n")
        sys.stderr.write('\n'.join(traceback.format_exception(*sys.exc_info())) + "\n")
        try:
            connection.rollback()
        except UnboundLocalError:
            pass
        sys.exit(1)
    else:
        connection.commit()
init.args = ''

def install(mod):
    "Executes the equivalent of 'get_sql_all' in the current database."
    from django.db import connection
    from cStringIO import StringIO
    mod_name = mod.__name__[mod.__name__.rindex('.')+1:]

    # First, try validating the models.
    s = StringIO()
    num_errors = get_validation_errors(s)
    if num_errors:
        sys.stderr.write("Error: %s couldn't be installed, because there were errors in your model:\n" % mod_name)
        s.seek(0)
        sys.stderr.write(s.read())
        sys.exit(1)
    sql_list = get_sql_all(mod)

    try:
        cursor = connection.cursor()
        for sql in sql_list:
            cursor.execute(sql)
    except Exception, e:
        sys.stderr.write("""Error: %s couldn't be installed. Possible reasons:
  * The database isn't running or isn't configured correctly.
  * At least one of the database tables already exists.
  * The SQL was invalid.
Hint: Look at the output of 'django-admin.py sqlall %s'. That's the SQL this command wasn't able to run.
The full error: %s\n""" % \
            (mod_name, mod_name, e))
        connection.rollback()
        sys.exit(1)
    connection.commit()
install.help_doc = "Executes ``sqlall`` for the given model module name(s) in the current database."
install.args = APP_ARGS

def installperms(mod):
    "Installs any permissions for the given model, if needed."
    from django.models.auth import Permission
    from django.models.core import Package
    num_added = 0
    package = Package.objects.get_object(pk=mod._MODELS[0]._meta.app_label)
    for klass in mod._MODELS:
        opts = klass._meta
        for codename, name in _get_all_permissions(opts):
            try:
                Permission.objects.get_object(name__exact=name, codename__exact=codename, package__label__exact=package.label)
            except Permission.DoesNotExist:
                p = Permission(name=name, package=package, codename=codename)
                p.save()
                print "Added permission '%r'." % p
                num_added += 1
    if not num_added:
        print "No permissions were added, because all necessary permissions were already installed."
installperms.help_doc = "Installs any permissions for the given model module name(s), if needed."
installperms.args = APP_ARGS

def _start_helper(app_or_project, name, directory, other_name=''):
    other = {'project': 'app', 'app': 'project'}[app_or_project]
    if not _is_valid_dir_name(name):
        sys.stderr.write("Error: %r is not a valid %s name. Please use only numbers, letters and underscores.\n" % (name, app_or_project))
        sys.exit(1)
    top_dir = os.path.join(directory, name)
    try:
        os.mkdir(top_dir)
    except OSError, e:
        sys.stderr.write("Error: %s\n" % e)
        sys.exit(1)
    template_dir = PROJECT_TEMPLATE_DIR % app_or_project
    for d, subdirs, files in os.walk(template_dir):
        relative_dir = d[len(template_dir)+1:].replace('%s_name' % app_or_project, name)
        if relative_dir:
            os.mkdir(os.path.join(top_dir, relative_dir))
        for i, subdir in enumerate(subdirs):
            if subdir.startswith('.'):
                del subdirs[i]
        for f in files:
            if f.endswith('.pyc'):
                continue
            fp_old = open(os.path.join(d, f), 'r')
            fp_new = open(os.path.join(top_dir, relative_dir, f.replace('%s_name' % app_or_project, name)), 'w')
            fp_new.write(fp_old.read().replace('{{ %s_name }}' % app_or_project, name).replace('{{ %s_name }}' % other, other_name))
            fp_old.close()
            fp_new.close()

def startproject(project_name, directory):
    "Creates a Django project for the given project_name in the given directory."
    from random import choice
    if project_name in INVALID_PROJECT_NAMES:
        sys.stderr.write("Error: %r isn't a valid project name. Please try another.\n" % project_name)
        sys.exit(1)
    _start_helper('project', project_name, directory)
    # Create a random SECRET_KEY hash, and put it in the main settings.
    main_settings_file = os.path.join(directory, project_name, 'settings.py')
    settings_contents = open(main_settings_file, 'r').read()
    fp = open(main_settings_file, 'w')
    secret_key = ''.join([choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)])
    settings_contents = re.sub(r"(?<=SECRET_KEY = ')'", secret_key + "'", settings_contents)
    fp.write(settings_contents)
    fp.close()
startproject.help_doc = "Creates a Django project directory structure for the given project name in the current directory."
startproject.args = "[projectname]"

def startapp(app_name, directory):
    "Creates a Django app for the given app_name in the given directory."
    # Determine the project_name a bit naively -- by looking at the name of
    # the parent directory.
    project_dir = os.path.normpath(os.path.join(directory, '..'))
    project_name = os.path.basename(project_dir)
    _start_helper('app', app_name, directory, project_name)
startapp.help_doc = "Creates a Django app directory structure for the given app name in the current directory."
startapp.args = "[appname]"

def createsuperuser(username=None, email=None, password=None):
    "Creates a superuser account."
    from django.core import validators
    from django.models.auth import User
    import getpass
    try:
        while 1:
            if not username:
                username = raw_input('Username (only letters, digits and underscores): ')
            if not username.isalnum():
                sys.stderr.write("Error: That username is invalid.\n")
                username = None
            try:
                User.objects.get_object(username__exact=username)
            except User.DoesNotExist:
                break
            else:
                sys.stderr.write("Error: That username is already taken.\n")
                username = None
        while 1:
            if not email:
                email = raw_input('E-mail address: ')
            try:
                validators.isValidEmail(email, None)
            except validators.ValidationError:
                sys.stderr.write("Error: That e-mail address is invalid.\n")
                email = None
            else:
                break
        while 1:
            if not password:
                password = getpass.getpass()
                password2 = getpass.getpass('Password (again): ')
                if password != password2:
                    sys.stderr.write("Error: Your passwords didn't match.\n")
                    password = None
                    continue
            if password.strip() == '':
                sys.stderr.write("Error: Blank passwords aren't allowed.\n")
                password = None
                continue
            break
    except KeyboardInterrupt:
        sys.stderr.write("\nOperation cancelled.\n")
        sys.exit(1)
    u = User.objects.create_user(username, email, password)
    u.is_staff = True
    u.is_active = True
    u.is_superuser = True
    u.save()
    print "User created successfully."
createsuperuser.args = '[username] [email] [password] (Either all or none)'

def inspectdb(db_name):
    "Generator that introspects the tables in the given database name and returns a Django model, one line at a time."
    from django.db import connection, get_introspection_module
    from django.conf import settings

    introspection_module = get_introspection_module()

    def table2model(table_name):
        object_name = table_name.title().replace('_', '')
        return object_name.endswith('s') and object_name[:-1] or object_name

    settings.DATABASE_NAME = db_name
    cursor = connection.cursor()
    yield "# This is an auto-generated Django model module."
    yield "# You'll have to do the following manually to clean this up:"
    yield "#     * Rearrange models' order"
    yield "#     * Add primary_key=True to one field in each model."
    yield "# Feel free to rename the models, but don't rename db_table values or field names."
    yield "#"
    yield "# Also note: You'll have to insert the output of 'django-admin.py sqlinitialdata [appname]'"
    yield "# into your database."
    yield ''
    yield 'from django.db import models'
    yield ''
    for table_name in introspection_module.get_table_list(cursor):
        yield 'class %s(models.Model):' % table2model(table_name)
        try:
            relations = introspection_module.get_relations(cursor, table_name)
        except NotImplementedError:
            relations = {}
        for i, row in enumerate(introspection_module.get_table_description(cursor, table_name)):
            column_name = row[0]
            if relations.has_key(i):
                rel = relations[i]
                rel_to = rel[1] == table_name and "'self'" or table2model(rel[1])
                if column_name.endswith('_id'):
                    field_desc = '%s = models.ForeignKey(%s' % (column_name[:-3], rel_to)
                else:
                    field_desc = '%s = models.ForeignKey(%s, db_column=%r' % (column_name, rel_to, column_name)
            else:
                try:
                    field_type = introspection_module.DATA_TYPES_REVERSE[row[1]]
                except KeyError:
                    field_type = 'TextField'
                    field_type_was_guessed = True
                else:
                    field_type_was_guessed = False

                # This is a hook for DATA_TYPES_REVERSE to return a tuple of
                # (field_type, extra_params_dict).
                if type(field_type) is tuple:
                    field_type, extra_params = field_type
                else:
                    extra_params = {}

                if field_type == 'CharField' and row[3]:
                    extra_params['maxlength'] = row[3]

                field_desc = '%s = models.%s(' % (column_name, field_type)
                field_desc += ', '.join(['%s=%s' % (k, v) for k, v in extra_params.items()])
                field_desc += ')'
                if field_type_was_guessed:
                    field_desc += ' # This is a guess!'
            yield '    %s' % field_desc
        yield '    class META:'
        yield '        db_table = %r' % table_name
        yield ''
inspectdb.help_doc = "Introspects the database tables in the given database and outputs a Django model module."
inspectdb.args = "[dbname]"

class ModelErrorCollection:
    def __init__(self, outfile=sys.stdout):
        self.errors = []
        self.outfile = outfile

    def add(self, opts, error):
        self.errors.append((opts, error))
        self.outfile.write("%s.%s: %s\n" % (opts.app_label, opts.module_name, error))

def get_validation_errors(outfile):
    "Validates all installed models. Writes errors, if any, to outfile. Returns number of errors."
    import django.models
    from django.db import models
    e = ModelErrorCollection(outfile)
    module_list = models.get_installed_model_modules()
    for module in module_list:
        for cls in module._MODELS:
            opts = cls._meta

            # Do field-specific validation.
            for f in opts.fields:
                if isinstance(f, models.CharField) and f.maxlength in (None, 0):
                    e.add(opts, '"%s" field: CharFields require a "maxlength" attribute.' % f.name)
                if isinstance(f, models.FloatField):
                    if f.decimal_places is None:
                        e.add(opts, '"%s" field: FloatFields require a "decimal_places" attribute.' % f.name)
                    if f.max_digits is None:
                        e.add(opts, '"%s" field: FloatFields require a "max_digits" attribute.' % f.name)
                if isinstance(f, models.FileField) and not f.upload_to:
                    e.add(opts, '"%s" field: FileFields require an "upload_to" attribute.' % f.name)
                if isinstance(f, models.ImageField):
                    try:
                        from PIL import Image
                    except ImportError:
                        e.add(opts, '"%s" field: To use ImageFields, you need to install the Python Imaging Library. Get it at http://www.pythonware.com/products/pil/ .')
                if f.prepopulate_from is not None and type(f.prepopulate_from) not in (list, tuple):
                    e.add(opts, '"%s" field: prepopulate_from should be a list or tuple.' % f.name)
                if f.choices:
                    if not type(f.choices) in (tuple, list):
                        e.add(opts, '"%s" field: "choices" should be either a tuple or list.' % f.name)
                    else:
                        for c in f.choices:
                            if not type(c) in (tuple, list) or len(c) != 2:
                                e.add(opts, '"%s" field: "choices" should be a sequence of two-tuples.' % f.name)

            # Check for multiple ManyToManyFields to the same object, and
            # verify "singular" is set in that case.
            for i, f in enumerate(opts.many_to_many):
                for previous_f in opts.many_to_many[:i]:
                    if f.rel.to._meta == previous_f.rel.to._meta and f.rel.singular == previous_f.rel.singular:
                        e.add(opts, 'The "%s" field requires a "singular" parameter, because the %s model has more than one ManyToManyField to the same model (%s).' % (f.name, opts.object_name, previous_f.rel.to._meta.object_name))

            # Check admin attribute.
            if opts.admin is not None:
                if not isinstance(opts.admin, models.Admin):
                    e.add(opts, '"admin" attribute, if given, must be set to a models.Admin() instance.')
                else:
                    # list_display
                    if not isinstance(opts.admin.list_display, (list, tuple)):
                        e.add(opts, '"admin.list_display", if given, must be set to a list or tuple.')
                    else:
                        for fn in opts.admin.list_display:
                            try:
                                f = opts.get_field(fn)
                            except models.FieldDoesNotExist:
                                if not hasattr(cls, fn) or not callable(getattr(cls, fn)):
                                    e.add(opts, '"admin.list_display" refers to %r, which isn\'t a field or method.' % fn)
                            else:
                                if isinstance(f, models.ManyToManyField):
                                    e.add(opts, '"admin.list_display" doesn\'t support ManyToManyFields (%r).' % fn)
                    # list_filter
                    if not isinstance(opts.admin.list_filter, (list, tuple)):
                        e.add(opts, '"admin.list_filter", if given, must be set to a list or tuple.')
                    else:
                        for fn in opts.admin.list_filter:
                            try:
                                f = opts.get_field(fn)
                            except models.FieldDoesNotExist:
                                e.add(opts, '"admin.list_filter" refers to %r, which isn\'t a field.' % fn)

            # Check ordering attribute.
            if opts.ordering:
                for field_name in opts.ordering:
                    if field_name == '?': continue
                    if field_name.startswith('-'):
                        field_name = field_name[1:]
                    if opts.order_with_respect_to and field_name == '_order':
                        continue
                    try:
                        opts.get_field(field_name, many_to_many=False)
                    except models.FieldDoesNotExist:
                        e.add(opts, '"ordering" refers to "%s", a field that doesn\'t exist.' % field_name)

            # Check core=True, if needed.
            for related in opts.get_followed_related_objects():
                try:
                    for f in related.opts.fields:
                        if f.core:
                            raise StopIteration
                    e.add(related.opts, "At least one field in %s should have core=True, because it's being edited inline by %s.%s." % (related.opts.object_name, opts.module_name, opts.object_name))
                except StopIteration:
                    pass

            # Check unique_together.
            for ut in opts.unique_together:
                for field_name in ut:
                    try:
                        f = opts.get_field(field_name, many_to_many=True)
                    except models.FieldDoesNotExist:
                        e.add(opts, '"unique_together" refers to %s, a field that doesn\'t exist. Check your syntax.' % field_name)
                    else:
                        if isinstance(f.rel, models.ManyToMany):
                            e.add(opts, '"unique_together" refers to %s. ManyToManyFields are not supported in unique_together.' % f.name)
    return len(e.errors)

def validate(outfile=sys.stdout):
    "Validates all installed models."
    try:
        num_errors = get_validation_errors(outfile)
        outfile.write('%s error%s found.\n' % (num_errors, num_errors != 1 and 's' or ''))
    except ImproperlyConfigured:
        outfile.write("Skipping validation because things aren't configured properly.")
validate.args = ''

def runserver(addr, port):
    "Starts a lightweight Web server for development."
    from django.core.servers.basehttp import run, AdminMediaHandler, WSGIServerException
    from django.core.handlers.wsgi import WSGIHandler
    if not addr:
        addr = '127.0.0.1'
    if not port.isdigit():
        sys.stderr.write("Error: %r is not a valid port number.\n" % port)
        sys.exit(1)
    def inner_run():
        from django.conf.settings import SETTINGS_MODULE
        print "Validating models..."
        validate()
        print "\nStarting server on port %s with settings module %r." % (port, SETTINGS_MODULE)
        print "Go to http://%s:%s/ for Django." % (addr, port)
        print "Quit the server with CONTROL-C (Unix) or CTRL-BREAK (Windows)."
        try:
            run(addr, int(port), AdminMediaHandler(WSGIHandler()))
        except WSGIServerException, e:
            # Use helpful error messages instead of ugly tracebacks.
            ERRORS = {
                13: "You don't have permission to access that port.",
                98: "That port is already in use.",
                99: "That IP address can't be assigned-to.",
            }
            try:
                error_text = ERRORS[e.args[0].args[0]]
            except (AttributeError, KeyError):
                error_text = str(e)
            sys.stderr.write("Error: %s\n" % error_text)
            sys.exit(1)
        except KeyboardInterrupt:
            sys.exit(0)
    from django.utils import autoreload
    autoreload.main(inner_run)
runserver.args = '[optional port number, or ipaddr:port]'

def createcachetable(tablename):
    "Creates the table needed to use the SQL cache backend"
    from django.db import backend, get_creation_module, models
    data_types = get_creation_module().DATA_TYPES
    fields = (
        # "key" is a reserved word in MySQL, so use "cache_key" instead.
        models.CharField(name='cache_key', maxlength=255, unique=True, primary_key=True),
        models.TextField(name='value'),
        models.DateTimeField(name='expires', db_index=True),
    )
    table_output = []
    index_output = []
    for f in fields:
        field_output = [backend.quote_name(f.column), data_types[f.get_internal_type()] % f.__dict__]
        field_output.append("%sNULL" % (not f.null and "NOT " or ""))
        if f.unique:
            field_output.append("UNIQUE")
        if f.primary_key:
            field_output.append("PRIMARY KEY")
        if f.db_index:
            unique = f.unique and "UNIQUE " or ""
            index_output.append("CREATE %sINDEX %s_%s ON %s (%s);" % \
                (unique, tablename, f.column, backend.quote_name(tablename),
                backend.quote_name(f.column)))
        table_output.append(" ".join(field_output))
    full_statement = ["CREATE TABLE %s (" % backend.quote_name(tablename)]
    for i, line in enumerate(table_output):
        full_statement.append('    %s%s' % (line, i < len(table_output)-1 and ',' or ''))
    full_statement.append(');')
    curs = connection.cursor()
    curs.execute("\n".join(full_statement))
    for statement in index_output:
        curs.execute(statement)
    connection.commit()
createcachetable.args = "[tablename]"

# Utilities for command-line script

DEFAULT_ACTION_MAPPING = {
    'adminindex': get_admin_index,
    'createsuperuser': createsuperuser,
    'createcachetable' : createcachetable,
#     'dbcheck': database_check,
    'init': init,
    'inspectdb': inspectdb,
    'install': install,
    'installperms': installperms,
    'runserver': runserver,
    'sql': get_sql_create,
    'sqlall': get_sql_all,
    'sqlclear': get_sql_delete,
    'sqlindexes': get_sql_indexes,
    'sqlinitialdata': get_sql_initial_data,
    'sqlreset': get_sql_reset,
    'sqlsequencereset': get_sql_sequence_reset,
    'startapp': startapp,
    'startproject': startproject,
    'validate': validate,
}

NO_SQL_TRANSACTION = ('adminindex', 'createcachetable', 'dbcheck', 'install', 'installperms', 'sqlindexes')

class DjangoOptionParser(OptionParser):
    def print_usage_and_exit(self):
        self.print_help(sys.stderr)
        sys.exit(1)

def get_usage(action_mapping):
    """
    Returns a usage string. Doesn't do the options stuff, because optparse
    takes care of that.
    """
    usage = ["usage: %prog action [options]\nactions:"]
    available_actions = action_mapping.keys()
    available_actions.sort()
    for a in available_actions:
        func = action_mapping[a]
        usage.append("  %s %s" % (a, func.args))
        usage.extend(textwrap.wrap(getattr(func, 'help_doc', func.__doc__), initial_indent='    ', subsequent_indent='    '))
        usage.append("")
    return '\n'.join(usage[:-1]) # Cut off last list element, an empty space.

def print_error(msg, cmd):
    sys.stderr.write('Error: %s\nRun "%s --help" for help.\n' % (msg, cmd))
    sys.exit(1)

def execute_from_command_line(action_mapping=DEFAULT_ACTION_MAPPING):
    # Parse the command-line arguments. optparse handles the dirty work.
    parser = DjangoOptionParser(get_usage(action_mapping))
    parser.add_option('--settings',
        help='Python path to settings module, e.g. "myproject.settings.main". If this isn\'t provided, the DJANGO_SETTINGS_MODULE environment variable will be used.')
    parser.add_option('--pythonpath',
        help='Lets you manually add a directory the Python path, e.g. "/home/djangoprojects/myproject".')
    options, args = parser.parse_args()

    # Take care of options.
    if options.settings:
        os.environ['DJANGO_SETTINGS_MODULE'] = options.settings
    if options.pythonpath:
        sys.path.insert(0, options.pythonpath)

    # Run the appropriate action. Unfortunately, optparse can't handle
    # positional arguments, so this has to parse/validate them.
    try:
        action = args[0]
    except IndexError:
        parser.print_usage_and_exit()
    if not action_mapping.has_key(action):
        print_error("Your action, %r, was invalid." % action, sys.argv[0])

    # Switch to English, because django-admin.py creates database content
    # like permissions, and those shouldn't contain any translations.
    # But only do this if we should have a working settings file.
    if action not in ('startproject', 'startapp'):
        from django.utils import translation
        translation.activate('en-us')

    if action == 'createsuperuser':
        try:
            username, email, password = args[1], args[2], args[3]
        except IndexError:
            if len(args) == 1: # We got no arguments, just the action.
                action_mapping[action]()
            else:
                sys.stderr.write("Error: %r requires arguments of 'username email password' or no argument at all.\n")
                sys.exit(1)
        else:
            action_mapping[action](username, email, password)
    elif action in ('init', 'validate'):
        action_mapping[action]()
    elif action == 'inspectdb':
        try:
            param = args[1]
        except IndexError:
            parser.print_usage_and_exit()
        try:
            for line in action_mapping[action](param):
                print line
        except NotImplementedError:
            sys.stderr.write("Error: %r isn't supported for the currently selected database backend.\n" % action)
            sys.exit(1)
    elif action == 'createcachetable':
        try:
            action_mapping[action](args[1])
        except IndexError:
            parser.print_usage_and_exit()
    elif action in ('startapp', 'startproject'):
        try:
            name = args[1]
        except IndexError:
            parser.print_usage_and_exit()
        action_mapping[action](name, os.getcwd())
    elif action == 'runserver':
        if len(args) < 2:
            addr = ''
            port = '8000'
        else:
            try:
                addr, port = args[1].split(':')
            except ValueError:
                addr, port = '', args[1]
        action_mapping[action](addr, port)
    else:
        from django.db import models
        if action == 'dbcheck':
            mod_list = models.get_all_installed_modules()
        else:
            try:
                mod_list = [models.get_app(app_label) for app_label in args[1:]]
            except ImportError, e:
                sys.stderr.write("Error: %s. Are you sure your INSTALLED_APPS setting is correct?\n" % e)
                sys.exit(1)
            if not mod_list:
                parser.print_usage_and_exit()
        if action not in NO_SQL_TRANSACTION:
            print "BEGIN;"
        for mod in mod_list:
            output = action_mapping[action](mod)
            if output:
                print '\n'.join(output)
        if action not in NO_SQL_TRANSACTION:
            print "COMMIT;"

def execute_manager(settings_mod):
    # Add this project to sys.path so that it's importable in the conventional
    # way. For example, if this file (manage.py) lives in a directory
    # "myproject", this code would add "/path/to/myproject" to sys.path.
    project_directory = os.path.dirname(settings_mod.__file__)
    project_name = os.path.basename(project_directory)
    sys.path.append(os.path.join(project_directory, '..'))
    project_module = __import__(project_name, '', '', [''])
    sys.path.pop()

    # Set DJANGO_SETTINGS_MODULE appropriately.
    os.environ['DJANGO_SETTINGS_MODULE'] = '%s.settings' % project_name

    action_mapping = DEFAULT_ACTION_MAPPING.copy()

    # Remove the "startproject" command from the action_mapping, because that's
    # a django-admin.py command, not a manage.py command.
    del action_mapping['startproject']

    # Override the startapp handler so that it always uses the
    # project_directory, not the current working directory (which is default).
    action_mapping['startapp'] = lambda app_name, directory: startapp(app_name, project_directory)
    action_mapping['startapp'].help_doc = startapp.help_doc
    action_mapping['startapp'].args = startapp.args

    # Run the django-admin.py command.
    execute_from_command_line(action_mapping)


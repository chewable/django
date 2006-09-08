import sys, time
from django.conf import settings

from django.db import backend, connect, connection, connection_info, connections
from django.dispatch import dispatcher
from django.test import signals
from django.template import Template

# The prefix to put on the default database name when creating
# the test database.
TEST_DATABASE_PREFIX = 'test_'

def instrumented_test_render(self, context):
    """An instrumented Template render method, providing a signal 
    that can be intercepted by the test system Client
    
    """
    dispatcher.send(signal=signals.template_rendered, sender=self, template=self, context=context)
    return self.nodelist.render(context)
    
def setup_test_environment():
    """Perform any global pre-test setup. This involves:
        
        - Installing the instrumented test renderer
        
    """
    Template.original_render = Template.render
    Template.render = instrumented_test_render
    
def teardown_test_environment():
    """Perform any global post-test teardown. This involves:

        - Restoring the original test renderer
        
    """
    Template.render = Template.original_render
    del Template.original_render
    
def _set_autocommit(connection):
    "Make sure a connection is in autocommit mode."
    if hasattr(connection.connection, "autocommit"):
        connection.connection.autocommit(True)
    elif hasattr(connection.connection, "set_isolation_level"):
        connection.connection.set_isolation_level(0)
        
def create_test_db(verbosity=1, autoclobber=False):
    if verbosity >= 1:
        print "Creating test database..."
        
    # If we're using SQLite, it's more convenient to test against an
    # in-memory database.
    if settings.DATABASE_ENGINE == "sqlite3":
        TEST_DATABASE_NAME = ":memory:"
        if verbosity >= 2:
            print "Using in-memory sqlite database for testing"
    else:
        if settings.TEST_DATABASE_NAME:
            TEST_DATABASE_NAME = settings.TEST_DATABASE_NAME
        else:
            TEST_DATABASE_NAME = TEST_DATABASE_PREFIX + settings.DATABASE_NAME

        qn = backend.quote_name
        # Create the test database and connect to it. We need to autocommit
        # if the database supports it because PostgreSQL doesn't allow 
        # CREATE/DROP DATABASE statements within transactions.
        cursor = connection.cursor()
        _set_autocommit(connection)
        try:
            cursor.execute("CREATE DATABASE %s" % qn(db_name))
        except Exception, e:            
            sys.stderr.write("Got an error creating the test database: %s\n" % e)
            if not autoclobber:
                confirm = raw_input("It appears the test database, %s, already exists. Type 'yes' to delete it, or 'no' to cancel: " % db_name)
            if autoclobber or confirm == 'yes':
                try:
                    if verbosity >= 1:
                        print "Destroying old test database..."                
                    cursor.execute("DROP DATABASE %s" % qn(db_name))
                    if verbosity >= 1:
                        print "Creating test database..."
                    cursor.execute("CREATE DATABASE %s" % qn(db_name))
                except Exception, e:
                    sys.stderr.write("Got an error recreating the test database: %s\n" % e)
                    sys.exit(2)
            else:
                print "Tests cancelled."
                sys.exit(1)
               
    connection.close()
    settings.DATABASE_NAME = TEST_DATABASE_NAME

    # Get a cursor (even though we don't need one yet). This has
    # the side effect of initializing the test database.
    cursor = connection.cursor()

    # Fill OTHER_DATABASES with the TEST_DATABASES settings,
    # and connect each named connection to the test database, using
    # a separate connection instance for each (so, eg, transactions don't
    # collide)
    test_databases = {}
    for db_name in settings.TEST_DATABASES:
        if settings.DATABASE_ENGINE == 'sqlite3':
            full_name = TEST_DATABASE_NAME
        else:
            full_name = TEST_DATABASE_NAME + db_name
        db_st = {'DATABASE_NAME': full_name}
        if db_name in settings.TEST_DATABASE_MODELS:
            db_st['MODELS'] = settings.TEST_DATABASE_MODELS.get(db_name, [])
        test_databases[db_name] = db_st
        connections[db_name] = connect(connection_info.settings)
        connections[db_name].connection.cursor() # Initialize it
    settings.OTHER_DATABASES = test_databases

def destroy_test_db(old_database_name, old_databases, verbosity=1):
    # Unless we're using SQLite, remove the test database to clean up after
    # ourselves. Connect to the previous database (not the test database)
    # to do so, because it's not allowed to delete a database while being
    # connected to it.
    if verbosity >= 1:
        print "Destroying test database..."
    connection.close()
    TEST_DATABASE_NAME = settings.DATABASE_NAME
    settings.DATABASE_NAME = old_database_name

    if settings.DATABASE_ENGINE != "sqlite3":
        settings.OTHER_DATABASES = old_databases
        cursor = connection.cursor()
        _set_autocommit(connection)
        time.sleep(1) # To avoid "database is being accessed by other users" errors.
        cursor.execute("DROP DATABASE %s" % backend.quote_name(TEST_DATABASE_NAME))
        connection.close()

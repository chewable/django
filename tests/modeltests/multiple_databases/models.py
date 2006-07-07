"""
XXX. Using multiple database connections

Django normally uses only a single database connection. However,
support is available for using any number of different, named
connections. Multiple database support is entirely optional and has
no impact on your application if you don't use it.

Named connections are defined in your settings module. Create a
`DATABASES` variable that is a dict, mapping connection names to their
particulars. The particulars are defined in a dict with the same keys
as the variable names as are used to define the default connection.

Access to named connections is through `django.db.connections`, which
behaves like a dict: you access connections by name. Connections are
established lazily, when accessed.  `django.db.connections[database]`
holds a `ConnectionInfo` instance, with the attributes:
`DatabaseError`, `backend`, `get_introspection_module`,
`get_creation_module`, and `runshell`.

Models can define which connection to use, by name. To use a named
connection, set the `db_connection` property in the model's Meta class
to the name of the connection. The name used must be a key in
settings.DATABASES, of course.

To access a model's connection, use `model._meta.connection`. To find
the backend or other connection metadata, use
`model._meta.connection_info`.
"""

from django.db import models

class Artist(models.Model):
    name = models.CharField(maxlength=100)
    alive = models.BooleanField(default=True)
    
    def __str__(self):
        return self.name
   
    class Meta:
        db_connection = 'django_test_db_a'

class Opus(models.Model):
    artist = models.ForeignKey(Artist)
    name = models.CharField(maxlength=100)
    year = models.IntegerField()
    
    def __str__(self):
        return "%s (%s)" % (self.name, self.year)
    
    class Meta:
        db_connection = 'django_test_db_a'


class Widget(models.Model):
    code = models.CharField(maxlength=10, unique=True)
    weight = models.IntegerField()

    def __str__(self):
        return self.code

    class Meta:
        db_connection = 'django_test_db_b'


class DooHickey(models.Model):
    name = models.CharField(maxlength=50)
    widgets = models.ManyToManyField(Widget, related_name='doohickeys')
    
    def __str__(self):
        return self.name
    
    class Meta:
        db_connection = 'django_test_db_b'


class Vehicle(models.Model):
    make = models.CharField(maxlength=20)
    model = models.CharField(maxlength=20)
    year = models.IntegerField()

    def __str__(self):
        return "%d %s %s" % (self.year, self.make, self.model)


API_TESTS = """

# See what connections are defined. django.db.connections acts like a dict.
>>> from django.db import connection, connections
>>> from django.conf import settings
>>> connections.keys()
['django_test_db_a', 'django_test_db_b']

# Each connection references its settings
>>> connections['django_test_db_a'].settings.DATABASE_NAME == settings.DATABASES['django_test_db_a']['DATABASE_NAME']
True
>>> connections['django_test_db_b'].settings.DATABASE_NAME == settings.DATABASES['django_test_db_b']['DATABASE_NAME']
True
>>> connections['django_test_db_b'].settings.DATABASE_NAME == settings.DATABASES['django_test_db_a']['DATABASE_NAME']
False
    
# Invalid connection names raise ImproperlyConfigured
>>> connections['bad']
Traceback (most recent call last):
 ...
ImproperlyConfigured: No database connection 'bad' has been configured

# Models can access their connections through their _meta properties
>>> Artist._meta.connection.settings == connections['django_test_db_a'].settings
True
>>> Widget._meta.connection.settings == connections['django_test_db_b'].settings
True
>>> Vehicle._meta.connection.settings == connection.settings
True
>>> Artist._meta.connection.settings == Widget._meta.connection.settings
False
>>> Artist._meta.connection.settings == Vehicle._meta.connection.settings
False

# Managers use their models' connections

>>> a = Artist(name="Paul Klee", alive=False)
>>> a.save()
>>> w = Widget(code='100x2r', weight=1000)
>>> w.save()
>>> v = Vehicle(make='Chevy', model='Camaro', year='1966')
>>> v.save()
>>> artists = Artist.objects.all()
>>> list(artists)
[<Artist: Paul Klee>]
>>> artists[0]._meta.connection.settings == connections['django_test_db_a'].settings
True

# When transactions are not managed, model save will commit only
# for the model's connection.

>>> from django.db import transaction
>>> transaction.enter_transaction_management()
>>> transaction.managed(False)
>>> a = Artist(name="Joan Miro", alive=False)
>>> w = Widget(code="99rbln", weight=1)
>>> a.save()

# Only connection 'django_test_db_a' is committed, so if we rollback
# all connections we'll forget the new Widget.

>>> transaction.rollback()
>>> list(Artist.objects.all())
[<Artist: Paul Klee>, <Artist: Joan Miro>]
>>> list(Widget.objects.all())
[<Widget: 100x2r>]

# Managed transaction state applies across all connections.

>>> transaction.managed(True)

# When managed, just as when using a single connection, updates are
# not committed until a commit is issued.

>>> a = Artist(name="Pablo Picasso", alive=False)
>>> a.save()
>>> w = Widget(code="99rbln", weight=1)
>>> w.save()
>>> v = Vehicle(make='Pontiac', model='Fiero', year='1987')
>>> v.save()

# The connections argument may be passed to commit, rollback, and the
# commit_on_success decorator as a keyword argument, as the first (for
# commit and rollback) or second (for the decorator) positional
# argument. It may be passed as a ConnectionInfo object, a connection
# (DatabaseWrapper) object, a connection name, or a list or dict of
# ConnectionInfo objects, connection objects, or connection names. If a
# dict is passed, the keys are ignored and the values used as the list
# of connections to commit, rollback, etc.

>>> transaction.commit(connections['django_test_db_b'])
>>> transaction.commit('django_test_db_b')
>>> transaction.commit(connections='django_test_db_b')
>>> transaction.commit(connections=['django_test_db_b'])
>>> transaction.commit(['django_test_db_a', 'django_test_db_b'])
>>> transaction.commit(connections)

# When the connections argument is omitted entirely, the transaction
# command applies to all connections. Here we have committed
# connections 'django_test_db_a' and 'django_test_db_b', but not the
# default connection, so the new vehicle is lost on rollback.

>>> transaction.rollback()
>>> list(Artist.objects.all())
[<Artist: Paul Klee>, <Artist: Joan Miro>, <Artist: Pablo Picasso>]
>>> list(Widget.objects.all())
[<Widget: 100x2r>, <Widget: 99rbln>]
>>> list(Vehicle.objects.all())
[<Vehicle: 1966 Chevy Camaro>]
>>> transaction.rollback()
>>> transaction.managed(False)
>>> transaction.leave_transaction_management()

# Of course, relations and all other normal database operations work
# with models that use named connections just the same as with models
# that use the default connection. The only caveat is that you can't
# use a relation between two models that are stored in different
# databases. Note that that doesn't mean that two models using
# different connection *names* can't be related; only that in the the
# context in which they are used, if you use the relation, the
# connections named by the two models must resolve to the same
# database.

>>> a = Artist.objects.get(name="Paul Klee")
>>> list(a.opus_set.all())
[]
>>> a.opus_set.create(name="Magic Garden", year="1926")
<Opus: Magic Garden (1926)>
>>> list(a.opus_set.all())
[<Opus: Magic Garden (1926)>]
>>> d = DooHickey(name='Thing')
>>> d.save()
>>> d.widgets.create(code='d101', weight=92)
<Widget: d101>
>>> list(d.widgets.all())
[<Widget: d101>]
>>> w = Widget.objects.get(code='d101')
>>> list(w.doohickeys.all())
[<DooHickey: Thing>]
"""

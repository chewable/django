from django.conf import settings
from django.db.models.related import RelatedObject
from django.db.models.fields.related import ManyToManyRel
from django.db.models.fields import AutoField, FieldDoesNotExist
from django.db.models.loading import get_models
from django.db.models.query import orderlist2sql
from bisect import bisect
import re

# Calculate the verbose_name by converting from InitialCaps to "lowercase with spaces".
get_verbose_name = lambda class_name: re.sub('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))', ' \\1', class_name).lower().strip()

DEFAULT_NAMES = ('verbose_name', 'db_table', 'ordering',
                 'unique_together', 'permissions', 'get_latest_by',
                 'order_with_respect_to', 'app_label')

class Options(object):
    def __init__(self, meta):
        self.fields, self.many_to_many = [], []
        self.module_name, self.verbose_name = None, None
        self.verbose_name_plural = None
        self.db_table = ''
        self.ordering = []
        self.unique_together =  []
        self.permissions =  []
        self.object_name, self.app_label = None, None
        self.get_latest_by = None
        self.order_with_respect_to = None
        self.admin = None
        self.meta = meta
        self.pk = None
        self.has_auto_field = False
        self.one_to_one_field = None
        self.parents = []

    def contribute_to_class(self, cls, name):
        cls._meta = self
        self.installed = re.sub('\.models$', '', cls.__module__) in settings.INSTALLED_APPS
        # First, construct the default values for these options.
        self.object_name = cls.__name__
        self.module_name = self.object_name.lower()
        self.verbose_name = get_verbose_name(self.object_name)
        # Next, apply any overridden values from 'class Meta'.
        if self.meta:
            meta_attrs = self.meta.__dict__
            del meta_attrs['__module__']
            del meta_attrs['__doc__']
            for attr_name in DEFAULT_NAMES:
                setattr(self, attr_name, meta_attrs.pop(attr_name, getattr(self, attr_name)))
            # verbose_name_plural is a special case because it uses a 's'
            # by default.
            setattr(self, 'verbose_name_plural', meta_attrs.pop('verbose_name_plural', self.verbose_name + 's'))
            # Any leftover attributes must be invalid.
            if meta_attrs != {}:
                raise TypeError, "'class Meta' got invalid attribute(s): %s" % ','.join(meta_attrs.keys())
        else:
            self.verbose_name_plural = self.verbose_name + 's'
        del self.meta

    def _prepare(self, model):
        if self.order_with_respect_to:
            self.order_with_respect_to = self.get_field(self.order_with_respect_to)
            self.ordering = ('_order',)
        else:
            self.order_with_respect_to = None

        if self.pk is None:
            auto = AutoField(verbose_name='ID', primary_key=True)
            auto.creation_counter = -1
            model.add_to_class('id', auto)

        # If the db_table wasn't provided, use the app_label + module_name.
        if not self.db_table:
            self.db_table = "%s_%s" % (self.app_label, self.module_name)

    def add_field(self, field):
        # Insert the given field in the order in which it was created, using
        # the "creation_counter" attribute of the field.
        # Move many-to-many related fields from self.fields into self.many_to_many.
        if field.rel and isinstance(field.rel, ManyToManyRel):
            self.many_to_many.insert(bisect(self.many_to_many, field), field)
        else:
            self.fields.insert(bisect(self.fields, field), field)
            if not self.pk and field.primary_key:
                self.pk = field
                field.serialize = False

    def __repr__(self):
        return '<Options for %s>' % self.object_name

    def __str__(self):
        return "%s.%s" % (self.app_label, self.module_name)

    def get_field(self, name, many_to_many=True):
        "Returns the requested field by name. Raises FieldDoesNotExist on error."
        to_search = many_to_many and (self.fields + self.many_to_many) or self.fields
        for f in to_search:
            if f.name == name:
                return f
        raise FieldDoesNotExist, '%s has no field named %r' % (self.object_name, name)

    def get_order_sql(self, table_prefix=''):
        "Returns the full 'ORDER BY' clause for this object, according to self.ordering."
        if not self.ordering: return ''
        pre = table_prefix and (table_prefix + '.') or ''
        return 'ORDER BY ' + orderlist2sql(self.ordering, self, pre)

    def get_add_permission(self):
        return 'add_%s' % self.object_name.lower()

    def get_change_permission(self):
        return 'change_%s' % self.object_name.lower()

    def get_delete_permission(self):
        return 'delete_%s' % self.object_name.lower()

    def get_all_related_objects(self):
        try: # Try the cache first.
            return self._all_related_objects
        except AttributeError:
            rel_objs = []
            for klass in get_models():
                for f in klass._meta.fields:
                    if f.rel and self == f.rel.to._meta:
                        rel_objs.append(RelatedObject(f.rel.to, klass, f))
            self._all_related_objects = rel_objs
            return rel_objs

    def get_followed_related_objects(self, follow=None):
        if follow == None:
            follow = self.get_follow()
        return [f for f in self.get_all_related_objects() if follow.get(f.name, None)]

    def get_data_holders(self, follow=None):
        if follow == None:
            follow = self.get_follow()
        return [f for f in self.fields + self.many_to_many + self.get_all_related_objects() if follow.get(f.name, None)]

    def get_follow(self, override=None):
        follow = {}
        for f in self.fields + self.many_to_many + self.get_all_related_objects():
            if override and f.name in override:
                child_override = override[f.name]
            else:
                child_override = None
            fol = f.get_follow(child_override)
            if fol != None:
                follow[f.name] = fol
        return follow

    def get_all_related_many_to_many_objects(self):
        try: # Try the cache first.
            return self._all_related_many_to_many_objects
        except AttributeError:
            rel_objs = []
            for klass in get_models():
                for f in klass._meta.many_to_many:
                    if f.rel and self == f.rel.to._meta:
                        rel_objs.append(RelatedObject(f.rel.to, klass, f))
            self._all_related_many_to_many_objects = rel_objs
            return rel_objs

    def get_ordered_objects(self):
        "Returns a list of Options objects that are ordered with respect to this object."
        if not hasattr(self, '_ordered_objects'):
            objects = []
            # TODO
            #for klass in get_models(get_app(self.app_label)):
            #    opts = klass._meta
            #    if opts.order_with_respect_to and opts.order_with_respect_to.rel \
            #        and self == opts.order_with_respect_to.rel.to._meta:
            #        objects.append(opts)
            self._ordered_objects = objects
        return self._ordered_objects

    def has_field_type(self, field_type, follow=None):
        """
        Returns True if this object's admin form has at least one of the given
        field_type (e.g. FileField).
        """
        # TODO: follow
        if not hasattr(self, '_field_types'):
            self._field_types = {}
        if field_type not in self._field_types:
            try:
                # First check self.fields.
                for f in self.fields:
                    if isinstance(f, field_type):
                        raise StopIteration
                # Failing that, check related fields.
                for related in self.get_followed_related_objects(follow):
                    for f in related.opts.fields:
                        if isinstance(f, field_type):
                            raise StopIteration
            except StopIteration:
                self._field_types[field_type] = True
            else:
                self._field_types[field_type] = False
        return self._field_types[field_type]

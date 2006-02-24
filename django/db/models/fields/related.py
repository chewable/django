from django.db import backend, connection
from django.db.models import signals
from django.db.models.fields import AutoField, Field, IntegerField
from django.db.models.related import RelatedObject
from django.utils.translation import gettext_lazy, string_concat
from django.utils.functional import curry
from django.core import validators
from django import forms
from django.dispatch import dispatcher

# For Python 2.3
if not hasattr(__builtins__, 'set'):
    from sets import Set as set

# Values for Relation.edit_inline.
TABULAR, STACKED = 1, 2

RECURSIVE_RELATIONSHIP_CONSTANT = 'self'

pending_lookups = {}

def add_lookup(rel_cls, field):
    name = field.rel.to
    module = rel_cls.__module__
    key = (module, name)
    pending_lookups.setdefault(key, []).append((rel_cls, field))

def do_pending_lookups(sender):
    other_cls = sender
    key = (other_cls.__module__, other_cls.__name__)
    for rel_cls, field in pending_lookups.setdefault(key, []):
        field.rel.to = other_cls
        field.do_related_class(other_cls, rel_cls)

dispatcher.connect(do_pending_lookups, signal=signals.class_prepared)

def manipulator_valid_rel_key(f, self, field_data, all_data):
    "Validates that the value is a valid foreign key"
    klass = f.rel.to
    try:
        klass._default_manager.get_object(pk=field_data)
    except klass.DoesNotExist:
        raise validators.ValidationError, _("Please enter a valid %s.") % f.verbose_name

#HACK
class RelatedField(object):
    def contribute_to_class(self, cls, name):
        sup = super(RelatedField, self)

        # Add an accessor to allow easy determination of the related query path for this field
        self.related_query_name = curry(self._get_related_query_name, cls._meta)

        if hasattr(sup, 'contribute_to_class'):
            sup.contribute_to_class(cls, name)
        other = self.rel.to
        if isinstance(other, basestring):
            if other == RECURSIVE_RELATIONSHIP_CONSTANT:
                self.rel.to = cls.__name__
            add_lookup(cls, self)
        else:
            self.do_related_class(other, cls)

    def set_attributes_from_rel(self):
        self.name = self.name or (self.rel.to._meta.object_name.lower() + '_' + self.rel.to._meta.pk.name)
        self.verbose_name = self.verbose_name or self.rel.to._meta.verbose_name
        self.rel.field_name = self.rel.field_name or self.rel.to._meta.pk.name

    def do_related_class(self, other, cls):
        self.set_attributes_from_rel()
        related = RelatedObject(other, cls, self)
        self.contribute_to_related_class(other, related)

    def _get_related_query_name(self, opts):
        # This method defines the name that can be used to identify this related object
        # in a table-spanning query. It uses the lower-cased object_name by default,
        # but this can be overridden with the "related_name" option.
        return self.rel.related_name or opts.object_name.lower()

class SingleRelatedObjectDescriptor(object):
    # This class provides the functionality that makes the related-object
    # managers available as attributes on a model class, for fields that have
    # a single "remote" value.
    # In the example "choice.poll", the poll attribute is a
    # SingleRelatedObjectDescriptor instance.
    def __init__(self, field_with_rel):
        self._field = field_with_rel

    def __get__(self, instance, instance_type=None):
        if instance is None:
            raise AttributeError, "%s must be accessed via instance" % self._field.name
        cache_name = self._field.get_cache_name()
        try:
            return getattr(instance, cache_name)
        except AttributeError:
            val = getattr(instance, self._field.attname)
            if val is None:
                raise self._field.rel.to.DoesNotExist
            other_field = self._field.rel.get_related_field()
            if other_field.rel:
                params = {'%s__%s__exact' % (self._field.rel.field_name, other_field.rel.field_name): val}
            else:
                params = {'%s__exact' % self._field.rel.field_name: val}
            rel_obj = self._field.rel.to._default_manager.get(**params)
            setattr(instance, cache_name, rel_obj)
            return rel_obj

def _add_m2m_items(rel_manager_inst, managerclass, rel_model, join_table, source_col_name,
        target_col_name, source_pk_val, *objs, **kwargs):
    # Utility function used by the ManyRelatedObjectsDescriptors
    # to do addition to a many-to-many field.
    # rel_manager_inst: the RelatedManager instance
    # managerclass: class that can create and save new objects
    # rel_model: the model class of the 'related' object
    # join_table: name of the m2m link table
    # source_col_name: the PK colname in join_table for the source object
    # target_col_name: the PK colname in join_table for the target object
    # source_pk_val: the primary key for the source object
    # *objs - objects to add, or **kwargs to create new objects

    from django.db import connection
    rel_opts = rel_model._meta
    # Create the related object.
    if kwargs:
        assert len(objs) == 0, "add() can't be passed both positional and keyword arguments"
        objs = [managerclass.add(rel_manager_inst, **kwargs)]
    else:
        assert len(objs) > 0, "add() must be passed either positional or keyword arguments"
        for obj in objs:
            if not isinstance(obj, rel_model):
                raise ValueError, "positional arguments to add() must be %s instances" % rel_opts.object_name

    # Add the newly created or already existing objects to the join table.
    # First find out which items are already added, to avoid adding them twice
    new_ids = set([obj._get_pk_val() for obj in objs])
    cursor = connection.cursor()
    cursor.execute("SELECT %s FROM %s WHERE %s = %%s AND %s IN (%s)" % \
        (target_col_name, join_table, source_col_name,
        target_col_name, ",".join(['%s'] * len(new_ids))),
        [source_pk_val] + list(new_ids))
    if cursor.rowcount is not None and cursor.rowcount > 0:
        existing_ids = set([row[0] for row in cursor.fetchmany(cursor.rowcount)])
    else:
        existing_ids = set()

    # Add the ones that aren't there already
    for obj_id in (new_ids - existing_ids):
        cursor.execute("INSERT INTO %s (%s, %s) VALUES (%%s, %%s)" % \
            (join_table, source_col_name, target_col_name),
            [source_pk_val, obj_id])
    connection.commit()

def _remove_m2m_items(rel_model, join_table, source_col_name,
        target_col_name, source_pk_val, *objs):
    # Utility function used by the ManyRelatedObjectsDescriptors
    # to do removal from a many-to-many field.
    # rel_model: the model class of the 'related' object
    # join_table: name of the m2m link table
    # source_col_name: the PK colname in join_table for the source object
    # target_col_name: the PK colname in join_table for the target object
    # source_pk_val: the primary key for the source object
    # *objs - objects to remove

    from django.db import connection
    rel_opts = rel_model._meta
    for obj in objs:
        if not isinstance(obj, rel_model):
            raise ValueError, "objects to remove() must be %s instances" % rel_opts.object_name
    # Remove the specified objects from the join table
    cursor = connection.cursor()
    for obj in objs:
        cursor.execute("DELETE FROM %s WHERE %s = %%s AND %s = %%s" % \
            (join_table, source_col_name, target_col_name),
            [source_pk_val, obj._get_pk_val()])
    connection.commit()

def _clear_m2m_items(join_table, source_col_name, source_pk_val):
    # Utility function used by the ManyRelatedObjectsDescriptors
    # to clear all from a many-to-many field.
    # join_table: name of the m2m link table
    # source_col_name: the PK colname in join_table for the source object
    # source_pk_val: the primary key for the source object
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute("DELETE FROM %s WHERE %s = %%s" % \
        (join_table, source_col_name),
        [source_pk_val])
    connection.commit()

class ManyRelatedObjectsDescriptor(object):
    # This class provides the functionality that makes the related-object
    # managers available as attributes on a model class, for fields that have
    # multiple "remote" values and have a ManyToManyField pointed at them by
    # some other model (rather than having a ManyToManyField themselves).
    # In the example "poll.choice_set", the choice_set attribute is a
    # ManyRelatedObjectsDescriptor instance.
    def __init__(self, related, rel_type):
        self.related = related   # RelatedObject instance
        self.rel_type = rel_type # Either 'o2m' or 'm2m'

    def __get__(self, instance, instance_type=None):
        if instance is None:
            raise AttributeError, "Manager must be accessed via instance"

        rel_field = self.related.field
        rel_type = self.rel_type
        rel_model = self.related.model

        if rel_type == "m2m":
            qn = backend.quote_name
            this_opts = instance.__class__._meta
            rel_opts = rel_model._meta
            join_table = qn(self.related.field.m2m_db_table())
            source_col_name = qn(self.related.field.m2m_reverse_name())
            target_col_name = qn(self.related.field.m2m_column_name())

        # Dynamically create a class that subclasses the related
        # model's default manager.
        superclass = self.related.model._default_manager.__class__

        class RelatedManager(superclass):
            def get_query_set(self):
                return superclass.get_query_set(self).filter(**(self.core_filters))

            if rel_type == "o2m":
                def add(self, **kwargs):
                    kwargs.update({rel_field.name: instance})
                    return superclass.add(self, **kwargs)
            else:
                def add(self, *objs, **kwargs):
                    _add_m2m_items(self, superclass, rel_model, join_table, source_col_name,
                        target_col_name, instance._get_pk_val(), *objs, **kwargs)
            add.alters_data = True

            if rel_type == "o2m":
                def remove(self, *objs):
                    pass # TODO
            else:
                def remove(self, *objs):
                    _remove_m2m_items(rel_model, join_table, source_col_name,
                        target_col_name, instance._get_pk_val(), *objs)
            remove.alters_data = True

            if rel_type == "o2m":
                def clear(self):
                    pass # TODO
            else:
                def clear(self):
                    _clear_m2m_items(join_table, source_col_name, instance._get_pk_val())
            clear.alters_data = True

        manager = RelatedManager()

        if self.rel_type == 'o2m':
            manager.core_filters = {'%s__pk' % rel_field.name: getattr(instance, rel_field.rel.get_related_field().attname)}
        else:
            manager.core_filters = {'%s__pk' % rel_field.name: instance._get_pk_val()}

        manager.model = self.related.model

        return manager

class ReverseManyRelatedObjectsDescriptor(object):
    # This class provides the functionality that makes the related-object
    # managers available as attributes on a model class, for fields that have
    # multiple "remote" values and have a ManyToManyField defined in their
    # model (rather than having another model pointed *at* them).
    # In the example "poll.sites", the sites attribute is a
    # ReverseManyRelatedObjectsDescriptor instance.
    def __init__(self, m2m_field):
        self.field = m2m_field

    def __get__(self, instance, instance_type=None):
        if instance is None:
            raise AttributeError, "Manager must be accessed via instance"

        qn = backend.quote_name
        this_opts = instance.__class__._meta
        rel_model = self.field.rel.to
        rel_opts = rel_model._meta
        join_table = qn(self.field.m2m_db_table())
        source_col_name = qn(self.field.m2m_column_name())
        target_col_name = qn(self.field.m2m_reverse_name())

        # Dynamically create a class that subclasses the related
        # model's default manager.
        superclass = rel_model._default_manager.__class__

        class RelatedManager(superclass):
            def get_query_set(self):
                return superclass.get_query_set(self).extra(
                    tables=(join_table,),
                    where=[
                        '%s.%s = %s.%s' % (qn(rel_opts.db_table), qn(rel_opts.pk.column), join_table, target_col_name),
                        '%s.%s = %%s' % (join_table, source_col_name)
                    ],
                    params = [instance._get_pk_val()]
                )
                return superclass.get_query_set(self).filter(**(self.core_filters))

            def add(self, *objs, **kwargs):
                _add_m2m_items(self, superclass, rel_model, join_table, source_col_name,
                    target_col_name, instance._get_pk_val(), *objs, **kwargs)

                # If this is an m2m relation to self, add the mirror entry in the m2m table
                if instance.__class__ == rel_model:
                    _add_m2m_items(self, superclass, rel_model, join_table, target_col_name,
                        source_col_name, instance._get_pk_val(), *objs, **kwargs)                    

            add.alters_data = True

            def remove(self, *objs):
                _remove_m2m_items(rel_model, join_table, source_col_name,
                    target_col_name, instance._get_pk_val(), *objs)
                    
                # If this is an m2m relation to self, remove the mirror entry in the m2m table
                if instance.__class__ == rel_model:
                    _remove_m2m_items(rel_model, join_table, target_col_name,
                        source_col_name, instance._get_pk_val(), *objs)
                    
            remove.alters_data = True

            def clear(self):
                _clear_m2m_items(join_table, source_col_name, instance._get_pk_val())
    
                # If this is an m2m relation to self, clear the mirror entry in the m2m table                
                if instance.__class__ == rel_model:
                    _clear_m2m_items(join_table, target_col_name, instance._get_pk_val())
                
            clear.alters_data = True

        manager = RelatedManager()
        
        manager.core_filters = {'%s__pk' % self.field.related_query_name() : instance._get_pk_val()}
        
        manager.model = rel_model

        return manager

class ForeignKey(RelatedField, Field):
    empty_strings_allowed = False
    def __init__(self, to, to_field=None, **kwargs):
        try:
            to_name = to._meta.object_name.lower()
        except AttributeError: # to._meta doesn't exist, so it must be RECURSIVE_RELATIONSHIP_CONSTANT
            assert isinstance(to, basestring), "ForeignKey(%r) is invalid. First parameter to ForeignKey must be either a model, a model name, or the string %r" % (to, RECURSIVE_RELATIONSHIP_CONSTANT)
        else:
            to_field = to_field or to._meta.pk.name
        kwargs['verbose_name'] = kwargs.get('verbose_name', '')

        if kwargs.has_key('edit_inline_type'):
            import warnings
            warnings.warn("edit_inline_type is deprecated. Use edit_inline instead.")
            kwargs['edit_inline'] = kwargs.pop('edit_inline_type')

        kwargs['rel'] = ManyToOne(to, to_field,
            edit_inline=kwargs.pop('edit_inline', False),
            related_name=kwargs.pop('related_name', None),
            limit_choices_to=kwargs.pop('limit_choices_to', None),
            lookup_overrides=kwargs.pop('lookup_overrides', None),
            raw_id_admin=kwargs.pop('raw_id_admin', False))
        Field.__init__(self, **kwargs)

        self.db_index = True

        for name in ('num_in_admin', 'min_num_in_admin', 'max_num_in_admin', 'num_extra_on_change'):
            if name in kwargs:
                self.deprecated_args.append(name)

    def get_attname(self):
        return '%s_id' % self.name

    def get_validator_unique_lookup_type(self):
        return '%s__%s__exact' % (self.name, self.rel.get_related_field().name)

    def prepare_field_objs_and_params(self, manipulator, name_prefix):
        params = {'validator_list': self.validator_list[:], 'member_name': name_prefix + self.attname}
        if self.rel.raw_id_admin:
            field_objs = self.get_manipulator_field_objs()
            params['validator_list'].append(curry(manipulator_valid_rel_key, self, manipulator))
        else:
            if self.radio_admin:
                field_objs = [forms.RadioSelectField]
                params['ul_class'] = get_ul_class(self.radio_admin)
            else:
                if self.null:
                    field_objs = [forms.NullSelectField]
                else:
                    field_objs = [forms.SelectField]
            params['choices'] = self.get_choices_default()
        return field_objs, params

    def get_manipulator_field_objs(self):
        rel_field = self.rel.get_related_field()
        if self.rel.raw_id_admin and not isinstance(rel_field, AutoField):
            return rel_field.get_manipulator_field_objs()
        else:
            return [forms.IntegerField]

    def get_db_prep_save(self, value):
        if value == '' or value == None:
            return None
        else:
            return self.rel.get_related_field().get_db_prep_save(value)

    def flatten_data(self, follow, obj=None):
        if not obj:
            # In required many-to-one fields with only one available choice,
            # select that one available choice. Note: For SelectFields
            # (radio_admin=False), we have to check that the length of choices
            # is *2*, not 1, because SelectFields always have an initial
            # "blank" value. Otherwise (radio_admin=True), we check that the
            # length is 1.
            if not self.blank and (not self.rel.raw_id_admin or self.choices):
                choice_list = self.get_choices_default()
                if self.radio_admin and len(choice_list) == 1:
                    return {self.attname: choice_list[0][0]}
                if not self.radio_admin and len(choice_list) == 2:
                    return {self.attname: choice_list[1][0]}
        return Field.flatten_data(self, follow, obj)

    def contribute_to_class(self, cls, name):
        super(ForeignKey, self).contribute_to_class(cls, name)
        setattr(cls, self.name, SingleRelatedObjectDescriptor(self))

    def contribute_to_related_class(self, cls, related):
        setattr(cls, related.get_accessor_name(), ManyRelatedObjectsDescriptor(related, 'o2m'))

class OneToOneField(RelatedField, IntegerField):
    def __init__(self, to, to_field=None, **kwargs):
        kwargs['verbose_name'] = kwargs.get('verbose_name', 'ID')
        to_field = to_field or to._meta.pk.name

        if kwargs.has_key('edit_inline_type'):
            import warnings
            warnings.warn("edit_inline_type is deprecated. Use edit_inline instead.")
            kwargs['edit_inline'] = kwargs.pop('edit_inline_type')

        kwargs['rel'] = OneToOne(to, to_field,
            edit_inline=kwargs.pop('edit_inline', False),
            related_name=kwargs.pop('related_name', None),
            limit_choices_to=kwargs.pop('limit_choices_to', None),
            lookup_overrides=kwargs.pop('lookup_overrides', None),
            raw_id_admin=kwargs.pop('raw_id_admin', False))
        kwargs['primary_key'] = True
        IntegerField.__init__(self, **kwargs)

        self.db_index = True

        for name in ('num_in_admin',):
            if name in kwargs:
                self.deprecated_args.append(name)

    def get_attname(self):
        return '%s_id' % self.name

    def get_validator_unique_lookup_type(self):
        return '%s__%s__exact' % (self.name, self.rel.get_related_field().name)

    def contribute_to_class(self, cls, name):
        super(OneToOneField, self).contribute_to_class(cls, name)
        setattr(cls, self.name, SingleRelatedObjectDescriptor(self))

    def contribute_to_related_class(self, cls, related):
        setattr(cls, related.get_accessor_name(), SingleRelatedObjectDescriptor(self))
        if not cls._meta.one_to_one_field:
           cls._meta.one_to_one_field = self

class ManyToManyField(RelatedField, Field):
    def __init__(self, to, **kwargs):
        kwargs['verbose_name'] = kwargs.get('verbose_name', None)
        kwargs['rel'] = ManyToMany(to, kwargs.pop('singular', None),
            related_name=kwargs.pop('related_name', None),
            filter_interface=kwargs.pop('filter_interface', None),
            limit_choices_to=kwargs.pop('limit_choices_to', None),
            raw_id_admin=kwargs.pop('raw_id_admin', False))
        if kwargs["rel"].raw_id_admin:
            kwargs.setdefault("validator_list", []).append(self.isValidIDList)
        Field.__init__(self, **kwargs)
        for name in ('num_in_admin'):
            if name in kwargs:
                self.deprecated_args.append(name)

        if self.rel.raw_id_admin:
            msg = gettext_lazy('Separate multiple IDs with commas.')
        else:
            msg = gettext_lazy('Hold down "Control", or "Command" on a Mac, to select more than one.')
        self.help_text = string_concat(self.help_text, msg)

    def get_manipulator_field_objs(self):
        if self.rel.raw_id_admin:
            return [forms.RawIdAdminField]
        else:
            choices = self.get_choices_default()
            return [curry(forms.SelectMultipleField, size=min(max(len(choices), 5), 15), choices=choices)]

    def get_choices_default(self):
        return Field.get_choices(self, include_blank=False)

    def _get_m2m_db_table(self, opts):
        "Function that can be curried to provide the m2m table name for this relation"
        return '%s_%s' % (opts.db_table, self.name)

    def _get_m2m_column_name(self, related):
        "Function that can be curried to provide the source column name for the m2m table"
        # If this is an m2m relation to self, avoid the inevitable name clash 
        if related.model == related.parent_model:
            return 'from_' + related.model._meta.object_name.lower() + '_id'
        else:
            return related.model._meta.object_name.lower() + '_id'
        
    def _get_m2m_reverse_name(self, related):
        "Function that can be curried to provide the related column name for the m2m table"
        # If this is an m2m relation to self, avoid the inevitable name clash 
        if related.model == related.parent_model:
            return 'to_' + related.parent_model._meta.object_name.lower() + '_id'        
        else:
            return related.parent_model._meta.object_name.lower() + '_id'

    def isValidIDList(self, field_data, all_data):
        "Validates that the value is a valid list of foreign keys"
        mod = self.rel.to
        try:
            pks = map(int, field_data.split(','))
        except ValueError:
            # the CommaSeparatedIntegerField validator will catch this error
            return
        objects = mod._default_manager.in_bulk(pks)
        if len(objects) != len(pks):
            badkeys = [k for k in pks if k not in objects]
            raise validators.ValidationError, ngettext("Please enter valid %(self)s IDs. The value %(value)r is invalid.",
                    "Please enter valid %(self)s IDs. The values %(value)r are invalid.", len(badkeys)) % {
                'self': self.verbose_name,
                'value': len(badkeys) == 1 and badkeys[0] or tuple(badkeys),
            }

    def flatten_data(self, follow, obj = None):
        new_data = {}
        if obj:
            instance_ids = [instance._get_pk_val() for instance in getattr(obj, self.name).all()]
            if self.rel.raw_id_admin:
                 new_data[self.name] = ",".join([str(id) for id in instance_ids])
            else:
                 new_data[self.name] = instance_ids
        else:
            # In required many-to-many fields with only one available choice,
            # select that one available choice.
            if not self.blank and not self.rel.edit_inline and not self.rel.raw_id_admin:
               choices_list = self.get_choices_default()
               if len(choices_list) == 1:
                   new_data[self.name] = [choices_list[0][0]]
        return new_data

    def contribute_to_class(self, cls, name):
        super(ManyToManyField, self).contribute_to_class(cls, name)
        # Add the descriptor for the m2m relation
        setattr(cls, self.name, ReverseManyRelatedObjectsDescriptor(self))

        # Set up the accessor for the m2m table name for the relation
        self.m2m_db_table = curry(self._get_m2m_db_table, cls._meta)

    def contribute_to_related_class(self, cls, related):
        setattr(cls, related.get_accessor_name(), ManyRelatedObjectsDescriptor(related, 'm2m'))
        # Add the descriptor for the m2m relation
        self.rel.singular = self.rel.singular or self.rel.to._meta.object_name.lower()

        # Set up the accessors for the column names on the m2m table
        self.m2m_column_name = curry(self._get_m2m_column_name, related)
        self.m2m_reverse_name = curry(self._get_m2m_reverse_name, related)

    def set_attributes_from_rel(self):
        pass

class ManyToOne:
    def __init__(self, to, field_name, edit_inline=False,
        related_name=None, limit_choices_to=None, lookup_overrides=None, raw_id_admin=False):
        try:
            to._meta
        except AttributeError:
            assert isinstance(to, basestring), "'to' must be either a model, a model name or the string %r" % RECURSIVE_RELATIONSHIP_CONSTANT
        self.to, self.field_name = to, field_name
        self.edit_inline = edit_inline
        self.related_name = related_name
        self.limit_choices_to = limit_choices_to or {}
        self.lookup_overrides = lookup_overrides or {}
        self.raw_id_admin = raw_id_admin

    def get_related_field(self):
        "Returns the Field in the 'to' object to which this relationship is tied."
        return self.to._meta.get_field(self.field_name)

class OneToOne(ManyToOne):
    def __init__(self, to, field_name, edit_inline=False,
        related_name=None, limit_choices_to=None, lookup_overrides=None,
        raw_id_admin=False):
        self.to, self.field_name = to, field_name
        self.edit_inline = edit_inline
        self.related_name = related_name
        self.limit_choices_to = limit_choices_to or {}
        self.lookup_overrides = lookup_overrides or {}
        self.raw_id_admin = raw_id_admin

class ManyToMany:
    def __init__(self, to, singular=None, related_name=None,
        filter_interface=None, limit_choices_to=None, raw_id_admin=False):
        self.to = to
        self.singular = singular or None
        self.related_name = related_name
        self.filter_interface = filter_interface
        self.limit_choices_to = limit_choices_to or {}
        self.edit_inline = False
        self.raw_id_admin = raw_id_admin
        assert not (self.raw_id_admin and self.filter_interface), "ManyToMany relationships may not use both raw_id_admin and filter_interface"

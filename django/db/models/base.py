from django.db.models.manipulators import ManipulatorDescriptor, ModelAddManipulator, ModelChangeManipulator
from django.db.models.fields import Field, DateField, FileField, ImageField, AutoField
from django.db.models.fields import OneToOne, ManyToOne, ManyToMany, RECURSIVE_RELATIONSHIP_CONSTANT
from django.db.models.related import RelatedObject
from django.db.models.manager import Manager
from django.db.models.query import orderlist2sql 
from django.db.models.options import Options
from django.db import connection, backend

from django.core.exceptions import ObjectDoesNotExist
from django.utils.functional import curry

import re
import types
import sys


# Calculate the module_name using a poor-man's pluralization.
get_module_name = lambda class_name: class_name.lower() + 's'

# Calculate the verbose_name by converting from InitialCaps to "lowercase with spaces".
get_verbose_name = lambda class_name: re.sub('([A-Z])', ' \\1', class_name).lower().strip()


class ModelBase(type):
    "Metaclass for all models"
    def __new__(cls, name, bases, attrs):
        # If this isn't a subclass of Model, don't do anything special.
        if not bases or bases == (object,):
            return type.__new__(cls, name, bases, attrs)

        try:
            meta_attrs = attrs.pop('META').__dict__
            del meta_attrs['__module__']
            del meta_attrs['__doc__']
        except KeyError:
            meta_attrs = {}

        # Gather all attributes that are Field or Manager instances.
        fields, managers = [], []
        for obj_name, obj in attrs.items():
            if isinstance(obj, Field):
                obj.set_name(obj_name)
                fields.append(obj)
                del attrs[obj_name]
            elif isinstance(obj, Manager):
                managers.append((obj_name, obj))
                del attrs[obj_name]

        # Sort the fields and managers in the order that they were created. The
        # "creation_counter" is needed because metaclasses don't preserve the
        # attribute order.
        fields.sort(lambda x, y: x.creation_counter - y.creation_counter)
        managers.sort(lambda x, y: x[1].creation_counter - y[1].creation_counter)

        opts = Options(
            module_name = meta_attrs.pop('module_name', get_module_name(name)),
            # If the verbose_name wasn't given, use the class name,
            # converted from InitialCaps to "lowercase with spaces".
            verbose_name = meta_attrs.pop('verbose_name', get_verbose_name(name)),
            verbose_name_plural = meta_attrs.pop('verbose_name_plural', ''),
            db_table = meta_attrs.pop('db_table', ''),
            fields = fields,
            ordering = meta_attrs.pop('ordering', None),
            unique_together = meta_attrs.pop('unique_together', None),
            admin = meta_attrs.pop('admin', None),
            where_constraints = meta_attrs.pop('where_constraints', None),
            object_name = name,
            app_label = meta_attrs.pop('app_label', None),
            exceptions = meta_attrs.pop('exceptions', None),
            permissions = meta_attrs.pop('permissions', None),
            get_latest_by = meta_attrs.pop('get_latest_by', None),
            order_with_respect_to = meta_attrs.pop('order_with_respect_to', None),
            module_constants = meta_attrs.pop('module_constants', None),
        )

        if meta_attrs != {}:
            raise TypeError, "'class META' got invalid attribute(s): %s" % ','.join(meta_attrs.keys())

        # Create the DoesNotExist exception.
        attrs['DoesNotExist'] = types.ClassType('DoesNotExist', (ObjectDoesNotExist,), {})

        # Create the class, because we need it to use in currying.
        new_class = type.__new__(cls, name, bases, attrs)

        # Give the class a docstring -- its definition.
        if new_class.__doc__ is None:
            new_class.__doc__ = "%s.%s(%s)" % (opts.module_name, name, ", ".join([f.name for f in opts.fields]))

        if hasattr(new_class, 'get_absolute_url'):
            new_class.get_absolute_url = curry(get_absolute_url, opts, new_class.get_absolute_url)

        # Figure out the app_label by looking one level up.
        app_package = sys.modules.get(new_class.__module__)
        app_label = app_package.__name__.replace('.models', '')
        app_label = app_label[app_label.rfind('.')+1:]

        # Populate the _MODELS member on the module the class is in.
        app_package.__dict__.setdefault('_MODELS', []).append(new_class)

        # Cache the app label.
        opts.app_label = app_label

        # If the db_table wasn't provided, use the app_label + module_name.
        if not opts.db_table:
            opts.db_table = "%s_%s" % (app_label, opts.module_name)
        new_class._meta = opts

        # Create the default manager, if needed.
        # TODO: Use weakref because of possible memory leak / circular reference.
        if managers:
            for m_name, m in managers:
                m._prepare(new_class)
                setattr(new_class, m_name, m)
            new_class._default_manager = managers[0][1]
        else:
            if hasattr(new_class, 'objects'):
                raise ValueError, "Model %s must specify a custom Manager, because it has a field named 'objects'" % name
            m = Manager()
            m._prepare(new_class)
            new_class.objects = m
            new_class._default_manager = m

        new_class._prepare()

        for field in fields:
            if field.rel:
                other = field.rel.to
                if isinstance(other, basestring):
                    print "string lookup"
                else:
                    related = RelatedObject(other._meta, new_class, field)
                    field.contribute_to_related_class(other, related)

        
        return new_class


class Model(object):
    __metaclass__ = ModelBase
    
    AddManipulator = ManipulatorDescriptor('AddManipulator', ModelAddManipulator)
    ChangeManipulator = ManipulatorDescriptor('ChangeManipulator', ModelChangeManipulator)    
    
    def __repr__(self):
        return '<%s object>' % self.__class__.__name__

    def __eq__(self, other):
        return isinstance(other, self.__class__) and getattr(self, self._meta.pk.attname) == getattr(other, self._meta.pk.attname)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __init__(self, *args, **kwargs):
        if kwargs:
            for f in self._meta.fields:
                if isinstance(f.rel, ManyToOne):
                    try:
                        # Assume object instance was passed in.
                        rel_obj = kwargs.pop(f.name)
                    except KeyError:
                        try:
                            # Object instance wasn't passed in -- must be an ID.
                            val = kwargs.pop(f.attname)
                        except KeyError:
                            val = f.get_default()
                    else:
                        # Object instance was passed in.
                        # Special case: You can pass in "None" for related objects if it's allowed.
                        if rel_obj is None and f.null:
                            val = None
                        else:
                            try:
                                val = getattr(rel_obj, f.rel.get_related_field().attname)
                            except AttributeError:
                                raise TypeError, "Invalid value: %r should be a %s instance, not a %s" % (f.name, f.rel.to, type(rel_obj))
                    setattr(self, f.attname, val)
                else:
                    val = kwargs.pop(f.attname, f.get_default())
                    setattr(self, f.attname, val)
            if kwargs:
                raise TypeError, "'%s' is an invalid keyword argument for this function" % kwargs.keys()[0]
        for i, arg in enumerate(args):
            setattr(self, self._meta.fields[i].attname, arg)

    def _prepare(cls):
        # Creates some methods once self._meta has been populated.
        for f in cls._meta.fields:
            if f.choices:
                setattr(cls, 'get_%s_display' % f.name, curry(cls.__get_FIELD_display, field=f))
            if isinstance(f, DateField):
                if not f.null:
                    setattr(cls, 'get_next_by_%s' % f.name, curry(cls.__get_next_or_previous_by_FIELD, field=f, is_next=True))
                    setattr(cls, 'get_previous_by_%s' % f.name, curry(cls.__get_next_or_previous_by_FIELD, field=f, is_next=False))
            elif isinstance(f, FileField):
                setattr(cls, 'get_%s_filename' % f.name, curry(cls.__get_FIELD_filename, field=f))
                setattr(cls, 'get_%s_url' % f.name, curry(cls.__get_FIELD_url, field=f))
                setattr(cls, 'get_%s_size' % f.name, curry(cls.__get_FIELD_size, field=f))
                setattr(cls, 'save_%s_file' % f.name, curry(cls.__save_FIELD_file, field=f))
                if isinstance(f, ImageField):
                    # Add get_BLAH_width and get_BLAH_height methods, but only
                    # if the image field doesn't have width and height cache
                    # fields.
                    if not f.width_field:
                        setattr(cls, 'get_%s_width' % f.name, curry(cls.__get_FIELD_width, field=f))
                    if not f.height_field:
                        setattr(cls, 'get_%s_height' % f.name, curry(cls.__get_FIELD_height, field=f))

            # If the object has a relationship to itself, as designated by
            # RECURSIVE_RELATIONSHIP_CONSTANT, create that relationship formally.
            if f.rel and f.rel.to == RECURSIVE_RELATIONSHIP_CONSTANT:
                f.rel.to = cls
                f.name = f.name or (f.rel.to._meta.object_name.lower() + '_' + f.rel.to._meta.pk.name)
                f.verbose_name = f.verbose_name or f.rel.to._meta.verbose_name
                f.rel.field_name = f.rel.field_name or f.rel.to._meta.pk.name

            # Add methods for many-to-one related objects.
            # EXAMPLES: Choice.get_poll(), Story.get_dateline()
            if isinstance(f.rel, ManyToOne):
                setattr(cls, 'get_%s' % f.name, curry(cls.__get_foreign_key_object, field_with_rel=f))

        # Create the default class methods.
        for f in cls._meta.many_to_many:
            # Add "get_thingie" methods for many-to-many related objects.
            # EXAMPLES: Poll.get_site_list(), Story.get_byline_list()
            setattr(cls, 'get_%s_list' % f.rel.singular, curry(cls.__get_many_to_many_objects, field_with_rel=f))

            # Add "set_thingie" methods for many-to-many related objects.
            # EXAMPLES: Poll.set_sites(), Story.set_bylines()
            setattr(cls, 'set_%s' % f.name, curry(cls.__set_many_to_many_objects, field_with_rel=f))

        if cls._meta.order_with_respect_to:
            cls.get_next_in_order = curry(cls.__get_next_or_previous_in_order, is_next=True)
            cls.get_previous_in_order = curry(cls.__get_next_or_previous_in_order, is_next=False)

    _prepare = classmethod(_prepare)

    def save(self):
        # Run any pre-save hooks.
        if hasattr(self, '_pre_save'):
            self._pre_save()

        non_pks = [f for f in self._meta.fields if not f.primary_key]
        cursor = connection.cursor()

        # First, try an UPDATE. If that doesn't update anything, do an INSERT.
        pk_val = getattr(self, self._meta.pk.attname)
        pk_set = bool(pk_val)
        record_exists = True
        if pk_set:
            # Determine whether a record with the primary key already exists.
            cursor.execute("SELECT 1 FROM %s WHERE %s=%%s LIMIT 1" % \
                (backend.quote_name(self._meta.db_table), backend.quote_name(self._meta.pk.column)), [pk_val])
            # If it does already exist, do an UPDATE.
            if cursor.fetchone():
                db_values = [f.get_db_prep_save(f.pre_save(getattr(self, f.attname), False)) for f in non_pks]
                cursor.execute("UPDATE %s SET %s WHERE %s=%%s" % \
                    (backend.quote_name(self._meta.db_table),
                    ','.join(['%s=%%s' % backend.quote_name(f.column) for f in non_pks]),
                    backend.quote_name(self._meta.pk.attname)),
                    db_values + [pk_val])
            else:
                record_exists = False
        if not pk_set or not record_exists:
            field_names = [backend.quote_name(f.column) for f in self._meta.fields if not isinstance(f, AutoField)]
            db_values = [f.get_db_prep_save(f.pre_save(getattr(self, f.attname), True)) for f in self._meta.fields if not isinstance(f, AutoField)]
            # If the PK has been manually set, respect that.
            if pk_set:
                field_names += [f.column for f in self._meta.fields if isinstance(f, AutoField)]
                db_values += [f.get_db_prep_save(f.pre_save(getattr(self, f.column), True)) for f in self._meta.fields if isinstance(f, AutoField)]
            placeholders = ['%s'] * len(field_names)
            if self._meta.order_with_respect_to:
                field_names.append(backend.quote_name('_order'))
                # TODO: This assumes the database supports subqueries.
                placeholders.append('(SELECT COUNT(*) FROM %s WHERE %s = %%s)' % \
                    (backend.quote_name(self._meta.db_table), backend.quote_name(self._meta.order_with_respect_to.column)))
                db_values.append(getattr(self, self._meta.order_with_respect_to.attname))
            cursor.execute("INSERT INTO %s (%s) VALUES (%s)" % \
                (backend.quote_name(self._meta.db_table), ','.join(field_names),
                ','.join(placeholders)), db_values)
            if self._meta.has_auto_field and not pk_set:
                setattr(self, self._meta.pk.attname, backend.get_last_insert_id(cursor, self._meta.db_table, self._meta.pk.column))
        connection.commit()

        # Run any post-save hooks.
        if hasattr(self, '_post_save'):
            self._post_save()

    save.alters_data = True

    def delete(self):
        assert getattr(self, self._meta.pk.attname) is not None, "%r can't be deleted because it doesn't have an ID."

        # Run any pre-delete hooks.
        if hasattr(self, '_pre_delete'):
            self._pre_delete()

        cursor = connection.cursor()
        for related in self._meta.get_all_related_objects():
            rel_opts_name = related.get_method_name_part()
            if isinstance(related.field.rel, OneToOne):
                try:
                    sub_obj = getattr(self, 'get_%s' % rel_opts_name)()
                except ObjectDoesNotExist:
                    pass
                else:
                    sub_obj.delete()
            else:
                for sub_obj in getattr(self, 'get_%s_list' % rel_opts_name)():
                    sub_obj.delete()
        for related in self._meta.get_all_related_many_to_many_objects():
            cursor.execute("DELETE FROM %s WHERE %s=%%s" % \
                (backend.quote_name(related.field.get_m2m_db_table(related.opts)),
                backend.quote_name(self._meta.object_name.lower() + '_id')), [getattr(self, self._meta.pk.attname)])
        for f in self._meta.many_to_many:
            cursor.execute("DELETE FROM %s WHERE %s=%%s" % \
                (backend.quote_name(f.get_m2m_db_table(self._meta)),
                backend.quote_name(self._meta.object_name.lower() + '_id')),
                [getattr(self, self._meta.pk.attname)])

        cursor.execute("DELETE FROM %s WHERE %s=%%s" % \
            (backend.quote_name(self._meta.db_table), backend.quote_name(self._meta.pk.column)),
            [getattr(self, self._meta.pk.attname)])

        connection.commit()
        setattr(self, self._meta.pk.attname, None)
        for f in self._meta.fields:
            if isinstance(f, FileField) and getattr(self, f.attname):
                file_name = getattr(self, 'get_%s_filename' % f.name)()
                # If the file exists and no other object of this type references it,
                # delete it from the filesystem.
                if os.path.exists(file_name) and not self._default_manager.get_list(**{'%s__exact' % f.name: getattr(self, f.name)}):
                    os.remove(file_name)

        # Run any post-delete hooks.
        if hasattr(self, '_post_delete'):
            self._post_delete()

    delete.alters_data = True

    
    def __get_FIELD_display(self, field):
        value = getattr(self, field.attname)
        return dict(field.choices).get(value, value)

    def __get_next_or_previous_by_FIELD(self, field, is_next, **kwargs):
        op = is_next and '>' or '<'
        kwargs.setdefault('where', []).append('(%s %s %%s OR (%s = %%s AND %s.%s %s %%s))' % \
            (backend.quote_name(field.column), op, backend.quote_name(field.column),
            backend.quote_name(self._meta.db_table), backend.quote_name(self._meta.pk.column), op))
        param = str(getattr(self, field.attname))
        kwargs.setdefault('params', []).extend([param, param, getattr(self, self._meta.pk.attname)])
        kwargs['order_by'] = [(not is_next and '-' or '') + field.name, (not is_next and '-' or '') + self._meta.pk.name]
        kwargs['limit'] = 1
        return self.__class__._default_manager.get_object(**kwargs)

    def __get_next_or_previous_in_order(self, is_next):
        cachename = "__%s_order_cache" % is_next
        if not hasattr(self, cachename):
            op = is_next and '>' or '<'
            order_field = self.order_with_respect_to
            obj = self._default_manager.get_object(order_by=('_order',),
                where=['%s %s (SELECT %s FROM %s WHERE %s=%%s)' % \
                    (backend.quote_name('_order'), op, backend.quote_name('_order'),
                    backend.quote_name(opts.db_table), backend.quote_name(opts.pk.column)),
                    '%s=%%s' % backend.quote_name(order_field.column)],
                limit=1,
                params=[getattr(self, opts.pk.attname), getattr(self, order_field.attname)])
            setattr(self, cachename, obj)
        return getattr(self, cachename)

    def __get_FIELD_filename(self, field):
        return os.path.join(settings.MEDIA_ROOT, getattr(self, field.attname))

    def __get_FIELD_url(self, field):
        if getattr(self, field.attname): # value is not blank
            import urlparse
            return urlparse.urljoin(settings.MEDIA_URL, getattr(self, field.attname)).replace('\\', '/')
        return ''

    def __get_FIELD_size(self, field):
        return os.path.getsize(self.__get_FIELD_filename(field))

    def __save_FIELD_file(self, field, filename, raw_contents):
        directory = field.get_directory_name()
        try: # Create the date-based directory if it doesn't exist.
            os.makedirs(os.path.join(settings.MEDIA_ROOT, directory))
        except OSError: # Directory probably already exists.
            pass
        filename = field.get_filename(filename)

        # If the filename already exists, keep adding an underscore to the name of
        # the file until the filename doesn't exist.
        while os.path.exists(os.path.join(settings.MEDIA_ROOT, filename)):
            try:
                dot_index = filename.rindex('.')
            except ValueError: # filename has no dot
                filename += '_'
            else:
                filename = filename[:dot_index] + '_' + filename[dot_index:]

        # Write the file to disk.
        setattr(self, field.attname, filename)

        full_filename = self.__get_FIELD_filename(field)
        fp = open(full_filename, 'wb')
        fp.write(raw_contents)
        fp.close()

        # Save the width and/or height, if applicable.
        if isinstance(field, ImageField) and (field.width_field or field.height_field):
            from django.utils.images import get_image_dimensions
            width, height = get_image_dimensions(full_filename)
            if field.width_field:
                setattr(self, field.width_field, width)
            if field.height_field:
                setattr(self, field.height_field, height)

        # Save the object, because it has changed.
        self.save()

    __save_FIELD_file.alters_data = True

    def __get_FIELD_width(self, field):
        return self.__get_image_dimensions(field)[0]

    def __get_FIELD_height(self, field):
        return self.__get_image_dimensions(field)[1]

    def __get_image_dimensions(self, field):
        cachename = "__%s_dimensions_cache" % field.name
        if not hasattr(self, cachename):
            from django.utils.images import get_image_dimensions
            filename = self.__get_FIELD_filename(field)()
            setattr(self, cachename, get_image_dimensions(filename))
        return getattr(self, cachename)

    def __get_foreign_key_object(self, field_with_rel):
        cache_var = field_with_rel.get_cache_name()
        if not hasattr(self, cache_var):
            val = getattr(self, field_with_rel.attname)
            if val is None:
                raise field_with_rel.rel.to.DoesNotExist
            other_field = field_with_rel.rel.get_related_field()
            if other_field.rel:
                params = {'%s__%s__exact' % (field_with_rel.rel.field_name, other_field.rel.field_name): val}
            else:
                params = {'%s__exact' % field_with_rel.rel.field_name: val}
            retrieved_obj = field_with_rel.rel.to._default_manager.get_object(**params)
            setattr(self, cache_var, retrieved_obj)
        return getattr(self, cache_var)

    def __get_many_to_many_objects(self, field_with_rel):
        cache_var = '_%s_cache' % field_with_rel.name
        if not hasattr(self, cache_var):
            rel_opts = field_with_rel.rel.to._meta
            sql = "SELECT %s FROM %s a, %s b WHERE a.%s = b.%s AND b.%s = %%s %s" % \
                (','.join(['a.%s' % backend.quote_name(f.column) for f in rel_opts.fields]),
                backend.quote_name(rel_opts.db_table),
                backend.quote_name(field_with_rel.get_m2m_db_table(self._meta)),
                backend.quote_name(rel_opts.pk.column),
                backend.quote_name(rel_opts.object_name.lower() + '_id'),
                backend.quote_name(self._meta.object_name.lower() + '_id'), rel_opts.get_order_sql('a'))
            cursor = connection.cursor()
            cursor.execute(sql, [getattr(self, self._meta.pk.attname)])
            setattr(self, cache_var, [field_with_rel.rel.to(*row) for row in cursor.fetchall()])
        return getattr(self, cache_var)

    def __set_many_to_many_objects(self, id_list, field_with_rel):
        current_ids = [obj.id for obj in self.__get_many_to_many_objects(field_with_rel)]
        ids_to_add, ids_to_delete = dict([(i, 1) for i in id_list]), []
        for current_id in current_ids:
            if current_id in id_list:
                del ids_to_add[current_id]
            else:
                ids_to_delete.append(current_id)
        ids_to_add = ids_to_add.keys()
        # Now ids_to_add is a list of IDs to add, and ids_to_delete is a list of IDs to delete.
        if not ids_to_delete and not ids_to_add:
            return False # No change
        rel = field_with_rel.rel.to._meta
        m2m_table = field_with_rel.get_m2m_db_table(self._meta)
        cursor = connection.cursor()
        this_id = getattr(self, self._meta.pk.attname)
        if ids_to_delete:
            sql = "DELETE FROM %s WHERE %s = %%s AND %s IN (%s)" % \
                (backend.quote_name(m2m_table),
                backend.quote_name(self._meta.object_name.lower() + '_id'),
                backend.quote_name(rel.object_name.lower() + '_id'), ','.join(map(str, ids_to_delete)))
            cursor.execute(sql, [this_id])
        if ids_to_add:
            sql = "INSERT INTO %s (%s, %s) VALUES (%%s, %%s)" % \
                (backend.quote_name(m2m_table),
                backend.quote_name(self._meta.object_name.lower() + '_id'),
                backend.quote_name(rel.object_name.lower() + '_id'))
            cursor.executemany(sql, [(this_id, i) for i in ids_to_add])
        connection.commit()
        try:
            delattr(self, '_%s_cache' % field_with_rel.name) # clear cache, if it exists
        except AttributeError:
            pass
        return True

    __set_many_to_many_objects.alters_data = True

    def _get_related(self, method_name, rel_class, rel_field, **kwargs):
        kwargs['%s__%s__exact' % (rel_field.name, rel_field.rel.to._meta.pk.name)] = getattr(self, rel_field.rel.get_related_field().attname)
        kwargs.update(rel_field.rel.lookup_overrides)
        return getattr(rel_class._default_manager, method_name)(**kwargs)

    def _add_related(self, rel_class, rel_field, *args, **kwargs):
        init_kwargs = dict(zip([f.attname for f in rel_class._meta.fields if f != rel_field and not isinstance(f, AutoField)], args))
        init_kwargs.update(kwargs)
        for f in rel_class._meta.fields:
            if isinstance(f, AutoField):
                init_kwargs[f.attname] = None
        init_kwargs[rel_field.name] = self
        obj = rel_class(**init_kwargs)
        obj.save()
        return obj

    _add_related.alters_data = True


    # Handles related many-to-many object retrieval.
    # Examples: Album.get_song(), Album.get_song_list(), Album.get_song_count()
    def _get_related_many_to_many(self, method_name, rel_class, rel_field, **kwargs):
        kwargs['%s__%s__exact' % (rel_field.name, self._meta.pk.name)] = getattr(self, self._meta.pk.attname)
        return getattr(rel_class._default_manager, method_name)(**kwargs)

    # Handles setting many-to-many related objects.
    # Example: Album.set_songs()
    def _set_related_many_to_many(self, rel_class, rel_field, id_list):
        id_list = map(int, id_list) # normalize to integers
        rel = rel_field.rel.to
        m2m_table = rel_field.get_m2m_db_table(rel_opts)
        this_id = getattr(self, self._meta.pk.attname)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM %s WHERE %s = %%s" % \
            (backend.quote_name(m2m_table),
            backend.quote_name(rel.object_name.lower() + '_id')), [this_id])
        sql = "INSERT INTO %s (%s, %s) VALUES (%%s, %%s)" % \
            (backend.quote_name(m2m_table),
            backend.quote_name(rel.object_name.lower() + '_id'),
            backend.quote_name(rel_opts.object_name.lower() + '_id'))
        cursor.executemany(sql, [(this_id, i) for i in id_list])
        connection.commit()


    


############################################
# HELPER FUNCTIONS (CURRIED MODEL METHODS) #
############################################

# ORDERING METHODS #########################

def method_set_order(ordered_obj, self, id_list):
    cursor = connection.cursor()
    # Example: "UPDATE poll_choices SET _order = %s WHERE poll_id = %s AND id = %s"
    sql = "UPDATE %s SET %s = %%s WHERE %s = %%s AND %s = %%s" % \
        (backend.quote_name(ordered_obj.db_table), backend.quote_name('_order'),
        backend.quote_name(ordered_obj.order_with_respect_to.column),
        backend.quote_name(ordered_obj.pk.column))
    rel_val = getattr(self, ordered_obj.order_with_respect_to.rel.field_name)
    cursor.executemany(sql, [(i, rel_val, j) for i, j in enumerate(id_list)])
    connection.commit()

def method_get_order(ordered_obj, self):
    cursor = connection.cursor()
    # Example: "SELECT id FROM poll_choices WHERE poll_id = %s ORDER BY _order"
    sql = "SELECT %s FROM %s WHERE %s = %%s ORDER BY %s" % \
        (backend.quote_name(ordered_obj.pk.column),
        backend.quote_name(ordered_obj.db_table),
        backend.quote_name(ordered_obj.order_with_respect_to.column),
        backend.quote_name('_order'))
    rel_val = getattr(self, ordered_obj.order_with_respect_to.rel.field_name)
    cursor.execute(sql, [rel_val])
    return [r[0] for r in cursor.fetchall()]

##############################################
# HELPER FUNCTIONS (CURRIED MODEL FUNCTIONS) #
##############################################

def get_absolute_url(opts, func, self):
    return settings.ABSOLUTE_URL_OVERRIDES.get('%s.%s' % (opts.app_label, opts.module_name), func)(self)



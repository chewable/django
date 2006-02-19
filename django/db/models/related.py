class BoundRelatedObject(object):
    def __init__(self, related_object, field_mapping, original):
        self.relation = related_object
        self.field_mappings = field_mapping[related_object.opts.module_name]

    def template_name(self):
        raise NotImplementedError

    def __repr__(self):
        return repr(self.__dict__)

class RelatedObject(object):
    def __init__(self, parent_model, model, field):
        self.parent_model = parent_model
        self.model = model
        self.opts = model._meta
        self.field = field
        self.edit_inline = field.rel.edit_inline
        self.name = self.opts.module_name
        self.var_name = self.opts.object_name.lower()

    def flatten_data(self, follow, obj=None):
        new_data = {}
        rel_instances = self.get_list(obj)
        for i, rel_instance in enumerate(rel_instances):
            instance_data = {}
            for f in self.opts.fields + self.opts.many_to_many:
                # TODO: Fix for recursive manipulators.
                fol = follow.get(f.name, None)
                if fol:
                    field_data = f.flatten_data(fol, rel_instance)
                    for name, value in field_data.items():
                        instance_data['%s.%d.%s' % (self.var_name, i, name)] = value
            new_data.update(instance_data)
        return new_data

    def extract_data(self, data):
        """
        Pull out the data meant for inline objects of this class,
        i.e. anything starting with our module name.
        """
        return data # TODO

    def editable_fields(self):
        "Get the fields in this class that should be edited inline."
        return [f for f in self.opts.fields + self.opts.many_to_many if f.editable and f != self.field]

    def get_follow(self, override=None):
        if isinstance(override, bool):
            if override:
                over = {}
            else:
                return None
        else:
            if override:
                over = override.copy()
            elif self.edit_inline:
                over = {}
            else:
                return None

        over[self.field.name] = False
        return self.opts.get_follow(over)

    def __repr__(self):
        return "<RelatedObject: %s related to %s>" % (self.name, self.field.name)

    def bind(self, field_mapping, original, bound_related_object_class=BoundRelatedObject):
        return bound_related_object_class(self, field_mapping, original)

    def get_accessor_name(self):
        # This method encapsulates the logic that decides what name to give an
        # accessor descriptor that retrieves related many-to-one or
        # many-to-many objects. It uses the lower-cased object_name + "_set",
        # but this can be overridden with the "related_name" option.
        return self.field.rel.related_name or (self.opts.object_name.lower() + '_set')

    def get_query_name(self):
        # This method defines the name that can be used to identify this related object
        # in a table-spanning query. It uses the lower-cased object_name by default,
        # but this can be overridden with the "related_name" option.
        return self.field.rel.related_name or self.opts.object_name.lower()

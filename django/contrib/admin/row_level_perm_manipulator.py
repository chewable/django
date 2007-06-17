from django import oldforms as forms
from django.contrib.contenttypes.models import ContentType
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.contrib.auth.models import User, Group, Permission, RowLevelPermission
from django.db.models import manipulators

class ChangeRLPManipulator(forms.Manipulator):
    def __init__(self, ct=None):
        perm_list = []
        if ct:
            self.ct = ct
            perm_list = [(o.id, o.name) for o in self.ct.permission_set.order_by("name")]

        obj_list = [(User, User.objects.order_by("username"))]
        obj_list.extend([(Group, Group.objects.order_by("name"))])

        self.fields = (
            MultipleObjSelectField(field_name="owner", obj_list=obj_list),
            forms.SelectField(field_name="perm", choices=perm_list),
            forms.CheckboxField(field_name="negative"),
        )

    def save(self, new_data):
        rlp = RowLevelPermission.objects.get(pk=new_data['id'])

        self.original_object = rlp
        self.manager = rlp._default_manager
        self.opts = rlp._meta

        owner = MultipleObjSelectField.returnObject(new_data['owner'])
        owner_ct = ContentType.objects.get_for_model(owner)

        model_ct = rlp.model_ct
        model = model_ct.get_object_for_this_type (pk=rlp.model_id)
        model_id = rlp.model_id

        perm = Permission.objects.get(pk=new_data['perm'])

        field_name_list = ('owner_ct', 'owner_id', 'model_ct', 'model_id', 'permission')
        field_data = owner_ct.id
        all_data = {'owner_id': owner.id, 'model_ct_id': model_ct.id, 'model_id': model_id, 'permission_id': perm.id}
        manipulators.manipulator_validator_unique_together(field_name_list, self.opts, self, field_data, all_data)

        rlp.owner = owner
        rlp.permission = perm
        rlp.negative = new_data['negative']
        rlp.save()
        return rlp

class AddRLPManipulator(ChangeRLPManipulator):
    def __init__(self, obj_instance, ct):
        self.ct = ct
        self.obj_instance = obj_instance
        obj_list = [(User, User.objects.order_by("username"))]
        obj_list.extend([(Group, Group.objects.order_by("name"))])
        perm_list = [(o.id, o.name) for o in self.ct.permission_set.order_by("name")]
        self.fields = (
            MultipleObjSelectField(field_name="owner", obj_list=obj_list, default_text=_("Select an option")),
            forms.SelectMultipleField(field_name="perm", choices=perm_list, size=3),
            forms.CheckboxField(field_name="negative"),
        )

    def save(self, new_data):
        owner = MultipleObjSelectField.returnObject(new_data['owner'])

        self.manager = RowLevelPermission._default_manager
        self.opts = RowLevelPermission._meta

        ct = ContentType.objects.get_for_model(owner)
        rlp_list = []
        for i in new_data.getlist('perm'):
            perm = Permission.objects.get(pk=i)

            # Check that the new row level perms are unique.
            field_name_list = ('owner_ct', 'owner_id', 'model_ct', 'model_id', 'permission')
            field_data = ct.id
            model_id = self.obj_instance._get_pk_val()
            all_data = {'owner_id': owner.id, 'model_ct_id': self.ct.id, 'model_id': model_id, 'permission_id': perm.id}
            manipulators.manipulator_validator_unique_together(field_name_list, self.opts, self, field_data, all_data)

            rlp = RowLevelPermission.objects.create_row_level_permission(self.obj_instance, owner, perm, negative=new_data['negative'])
            rlp_list.append(rlp)

        return rlp_list

class MultipleObjSelectField(forms.SelectField):
    """
    Extends a select field to use more then one type of model in a select field.
    Uses optgroup in the select field to differentiate between object types.

    obj_list should be a list of lists containing the model and a list of objects.
    E.g. ((User, User.objects.all()), (Group, Group.objects.all))

    If you wish to define a default text to be shown as the default option, use the
    default_text parameter. An example of default text would be "Select an option"

    The remaining parameters are very similiar to the normal SelectField.

    To return the object selected pass the string result to MultipleObjSelectField.returnObject(string),
    it returns the object instance.

    To create a key for a specific object, use: MultipleObjSelectField.returnKey(object). It has an optional
    parameter for the content type (ct), if you have already determined the content type and want to save on
    db queries.
    """
    def __init__(self, field_name, obj_list=None, default_text=None, size=1,
            is_required=False, validator_list=None, member_name=None):
        choice_list = []
        self.default_text = default_text
        # Loop through the object list and create the list to be displayed
        for obj, obj_choices in obj_list:
            ct = ContentType.objects.get_for_model(obj)
            object_choice = [(MultipleObjSelectField.returnKey(o, ct=ct), str(o)) for o in obj_choices]
            choice_list.extend([(ct.name.title(), object_choice)])
        super(MultipleObjSelectField, self).__init__(field_name, choices=choice_list,
            size=size, is_required=is_required, validator_list=validator_list, member_name=member_name)

    def render(self, data):
        from django.utils.html import escape
        output = ['<select id="%s" class="v%s%s" name="%s" size="%s">' % \
            (self.get_id(), self.__class__.__name__,
             self.is_required and ' required' or '', self.field_name, self.size)]
        str_data = str(data) # normalize to string

        if self.default_text:
            selected_html = ''
            if not str_data:
                selected_html = ' selected="selected"'
            output.append('    <option %s>%s</option>' % (selected_html, escape(self.default_text)))

        for obj, obj_choices in self.choices:
            output.append('    <optgroup label="%s">' % (obj,))
            for value, display_name in obj_choices:
                selected_html = ''
                if str(value) == str_data:
                    selected_html = ' selected="selected"'
                output.append('    <option value="%s"%s>%s</option>' % (escape(value), selected_html, escape(display_name)))
            output.append('    </optgroup>')
        output.append('  </select>')
        return '\n'.join(output)

    def returnObject(data):
        data = data.split('/')
        ct = ContentType.objects.get(app_label__exact=data[0], model__exact=data[1])
        obj = ct.get_object_for_this_type(pk=data[2])
        return obj

    def returnKey(obj, ct=None):
        if not ct:
            ct = ContentType.objects.get_for_model(obj.__class__)
        return ct.app_label + "/" + ct.model + "/" + str(obj.id)

    returnObject = staticmethod(returnObject)
    returnKey = staticmethod(returnKey)

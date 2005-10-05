from django.core import template, template_loader, meta
from django.core.template_loader import render_to_string
from django.conf.settings import ADMIN_MEDIA_PREFIX
from django.utils.text import capfirst
from django.utils.html import escape
from django.utils.functional import curry

from django.core.template_decorators import simple_tag, inclusion_tag

from django.views.admin.main import AdminBoundField
import re

word_re = re.compile('[A-Z][a-z]+')

def class_name_to_underscored(name):
    return '_'.join([ s.lower() for s in word_re.findall(name)[:-1] ])

#@simple_tag        
def include_admin_script(script_path):
        return '<script type="text/javascript" src="%s%s"></script>' % \
            (ADMIN_MEDIA_PREFIX, script_path)
include_admin_script = simple_tag(include_admin_script)          


#@inclusion_tag('admin_submit_line', takes_context=True)
def submit_row(context):        
        change = context['change']
	add = context['add']
	show_delete = context['show_delete']
	ordered_objects = context['ordered_objects']
 	save_as = context['save_as']
	has_delete_permission = context['has_delete_permission']
        is_popup = context['is_popup']
	  
        return {
	    'onclick_attrib' : (ordered_objects and change 
                                and 'onclick="submitOrderForm();"' or ''), 
            'show_delete_link' : (not is_popup and has_delete_permission 
                                  and (change or show_delete)), 
            'show_save_as_new' : not is_popup and change and save_as,
            'show_save_and_add_another': not is_popup and (not save_as or add),
            'show_save_and_continue': not is_popup,
            'show_save': True
        }

srdec = inclusion_tag('admin_submit_line', takes_context=True)
submit_row = srdec(submit_row)

#@simple_tag   
def field_label(bound_field):
    class_names = []
    if isinstance(bound_field.field, meta.BooleanField):
        class_names.append("vCheckboxLabel")
    else:
        if not bound_field.field.blank:
            class_names.append('required')
        if not bound_field.first:
            class_names.append('inline')
    
    class_str = class_names and ' class="%s"' % ' '.join(class_names) or ''
    return '<label for="%s"%s>%s:</label> ' % \
            (bound_field.element_id, class_str, 
             capfirst(bound_field.field.verbose_name) )
field_label = simple_tag(field_label)


class FieldWidgetNode(template.Node):
    def __init__(self, bound_field_var):
        self.bound_field_var = bound_field_var
        self.nodelists = {}
        t = template_loader.get_template("widget/default")
        self.default = t.nodelist 

    def render(self, context):
    
        bound_field = template.resolve_variable(self.bound_field_var, context)
        add = context['add']
        change = context['change']
        
        context.push()
        context['bound_field'] = bound_field
        klass = bound_field.field.__class__
        if not self.nodelists.has_key(klass):
            t = None
            while klass:
                try: 
                    field_class_name = klass.__name__
                    template_name = "widget/%s" % \
                        class_name_to_underscored(field_class_name)
                    t = template_loader.get_template(template_name)
                    break
                except template.TemplateDoesNotExist: 
                    klass = bool(klass.__bases__) and klass.__bases__[0] or None
             
            if t == None:
                nodelist = self.default
            else:           
                nodelist = t.nodelist

            self.nodelists[klass] = nodelist            

        output = self.nodelists[klass].render(context)
        context.pop()
        return output

class FieldWrapper(object):
    def __init__(self, field ):
        self.field = field

    def needs_header(self):
        return not isinstance(self.field, meta.AutoField)

    def header_class_attribute(self):
        return self.field.blank and ' class="optional"' or ''

    def use_raw_id_admin(self):
         return isinstance(self.field.rel, (meta.ManyToOne, meta.ManyToMany)) \
                and self.field.rel.raw_id_admin

class FormFieldCollectionWrapper(object):
    def __init__(self, obj, fields):
        self.obj = obj
        self.fields = fields
        self.bound_fields = [ AdminBoundField(field, obj['original'],  True, self.obj) for field in self.fields ]

    def showurl(self):
        return False

class EditInlineNode(template.Node):
    def __init__(self, rel_var):
        self.rel_var = rel_var
    
    def render(self, context):
        relation = template.resolve_variable(self.rel_var, context)
        add, change = context['add'], context['change']
        
        context.push()

        self.fill_context(relation, add, change, context)
        
        t = template_loader.get_template(relation.field.rel.edit_inline)
        
        output = t.render(context)
         
        context.pop()
        return output

       
    def fill_context(self, relation, add, change, context):
        field_wrapper_list = relation.editable_fields(FieldWrapper)

        var_name = relation.opts.object_name.lower()
        
        form = template.resolve_variable('form', context)
        form_field_collections = form[relation.opts.module_name]
        fields = relation.editable_fields()
        form_field_collection_wrapper_list = [FormFieldCollectionWrapper(o,fields) for o in form_field_collections] 
   
        context['field_wrapper_list'] = field_wrapper_list
        context['form_field_collection_wrapper_list'] = form_field_collection_wrapper_list 
        context['num_headers'] = len(field_wrapper_list)
        context['original_row_needed'] = max([fw.use_raw_id_admin() for fw in field_wrapper_list]) 
#        context['name_prefix'] = "%s." % (var_name,)


#@simple_tag
def output_all(form_fields):
    return ''.join([str(f) for f in form_fields])
output_all = simple_tag(output_all)


#@simple_tag
def auto_populated_field_script(auto_pop_fields, change = False):
    for field in auto_pop_fields:
        t = []
        if change:
            t.append('document.getElementById("id_%s")._changed = true;' % field.name )
        else: 
            t.append('document.getElementById("id_%s").onchange = function() { this._changed = true; };' % field.name)

        add_values = ' + " " + '.join(['document.getElementById("id_%s").value' % g for g in field.prepopulate_from])
        for f in field.prepopulate_from:
            t.append('document.getElementById("id_%s").onkeyup = function() { var e = document.getElementById("id_%s"); if(e._changed) { e.value = URLify(%s, %s);} } ' % (f, field.name, add_values, field.maxlength) )

    return ''.join(t)
auto_populated_field_script = simple_tag(auto_populated_field_script)

#@simple_tag
def filter_interface_script_maybe(bound_field):
    f = bound_field.field 
    if f.rel and isinstance(f.rel, meta.ManyToMany) and f.rel.filter_interface:
       return '<script type="text/javascript">addEvent(window, "load", function(e) { SelectFilter.init("id_%s", "%s", %s, %r); });</script>\n' % (f.name, f.verbose_name, f.rel.filter_interface-1, ADMIN_MEDIA_PREFIX) 
    else: 
        return ''
filter_interface_script_maybe = simple_tag(filter_interface_script_maybe)

def do_one_arg_tag(node_factory, parser,token):
    tokens = token.contents.split()
    if len(tokens) != 2:
        raise template.TemplateSyntaxError("%s takes 1 argument" % tokens[0])
    return node_factory(tokens[1]) 


one_arg_tag_nodes = [
    FieldWidgetNode, 
    EditInlineNode, 
]


def register_one_arg_tag(node):
    tag_name = class_name_to_underscored(node.__name__)
    parse_func = curry(do_one_arg_tag, node)
    template.register_tag(tag_name, parse_func)

for node in one_arg_tag_nodes:
    register_one_arg_tag(node)    

     
#@inclusion_tag('admin_field', takes_context=True)
def admin_field_bound(context, argument_val):
    if (isinstance(argument_val, list)):
        bound_fields = argument_val 
    else:
        bound_fields = [argument_val]
    add = context['add']
    change = context['change']
   
    class_names = ['form-row']
    for bound_field in bound_fields: 
        for f in bound_field.form_fields:
            if f.errors():
                class_names.append('errors')
                break
      
    # Assumes BooleanFields won't be stacked next to each other!
    if isinstance(bound_fields[0].field, meta.BooleanField):
        class_names.append('checkbox-row')

    return { 
        'add' : context['add'],
        'change' : context['change'],
        'bound_fields' :  bound_fields, 
        'class_names' : " ".join(class_names)
    } 

    
afbdec = inclusion_tag('admin_field', takes_context=True)    
admin_field_bound = afbdec(admin_field_bound)



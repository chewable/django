"""
Form Widget classes specific to the Django admin site.
"""

from django import newforms as forms
from django.utils.text import capfirst
from django.utils.translation import ugettext as _
from django.conf import settings

class FilteredSelectMultiple(forms.SelectMultiple):
    """
    A SelectMultiple with a JavaScript filter interface.

    Note that the resulting JavaScript assumes that the SelectFilter2.js
    library and its dependencies have been loaded in the HTML page.
    """
    def __init__(self, verbose_name, is_stacked, attrs=None, choices=()):
        self.verbose_name = verbose_name
        self.is_stacked = is_stacked
        super(FilteredSelectMultiple, self).__init__(attrs, choices)

    def render(self, name, value, attrs=None, choices=()):
        from django.conf import settings
        output = [super(FilteredSelectMultiple, self).render(name, value, attrs, choices)]
        output.append(u'<script type="text/javascript">addEvent(window, "load", function(e) {')
        # TODO: "id_" is hard-coded here. This should instead use the correct
        # API to determine the ID dynamically.
        output.append(u'SelectFilter.init("id_%s", "%s", %s, "%s"); });</script>\n' % \
            (name, self.verbose_name.replace('"', '\\"'), int(self.is_stacked), settings.ADMIN_MEDIA_PREFIX))
        return u''.join(output)

class AdminDateWidget(forms.TextInput):
    class Media:
        js = (settings.ADMIN_MEDIA_PREFIX + "js/calendar.js", 
              settings.ADMIN_MEDIA_PREFIX + "js/admin/DateTimeShortcuts.js")
        
    def __init__(self, attrs={}):
        super(AdminDateWidget, self).__init__(attrs={'class': 'vDateField', 'size': '10'})

class AdminTimeWidget(forms.TextInput):
    class Media:
        js = (settings.ADMIN_MEDIA_PREFIX + "js/calendar.js", 
              settings.ADMIN_MEDIA_PREFIX + "js/admin/DateTimeShortcuts.js")

    def __init__(self, attrs={}):
        super(AdminTimeWidget, self).__init__(attrs={'class': 'vTimeField', 'size': '8'})
    
class AdminSplitDateTime(forms.SplitDateTimeWidget):
    """
    A SplitDateTime Widget that has some admin-specific styling.
    """
    def __init__(self, attrs=None):
        widgets = [AdminDateWidget, AdminTimeWidget]
        # Note that we're calling MultiWidget, not SplitDateTimeWidget, because
        # we want to define widgets.
        forms.MultiWidget.__init__(self, widgets, attrs)

    def format_output(self, rendered_widgets):
        return u'<p class="datetime">%s %s<br />%s %s</p>' % \
            (_('Date:'), rendered_widgets[0], _('Time:'), rendered_widgets[1])

class ForeignKeyRawIdWidget(forms.TextInput):
    """
    A Widget for displaying ForeignKeys in the "raw_id" interface rather than
    in a <select> box.
    """
    def __init__(self, rel, attrs=None):
        self.rel = rel
        super(ForeignKeyRawIdWidget, self).__init__(attrs)

    def render(self, name, value, attrs=None):
        from django.conf import settings
        related_url = '../../../%s/%s/' % (self.rel.to._meta.app_label, self.rel.to._meta.object_name.lower())
        if self.rel.limit_choices_to:
            url = '?' + '&amp;'.join(['%s=%s' % (k, v) for k, v in self.rel.limit_choices_to.items()])
        else:
            url = ''
        attrs['class'] = 'vRawIdAdminField' # The JavaScript looks for this hook.
        output = [super(ForeignKeyRawIdWidget, self).render(name, value, attrs)]
        # TODO: "id_" is hard-coded here. This should instead use the correct
        # API to determine the ID dynamically.
        output.append('<a href="%s%s" class="related-lookup" id="lookup_id_%s" onclick="return showRelatedObjectLookupPopup(this);"> ' % \
            (related_url, url, name))
        output.append('<img src="%simg/admin/selector-search.gif" width="16" height="16" alt="Lookup"></a>' % settings.ADMIN_MEDIA_PREFIX)
        return u''.join(output)
        #if self.change: # TODO
            #output.append('&nbsp;<strong>TODO</strong>')

class RelatedFieldWidgetWrapper(object):
    """
    This class is a wrapper whose __call__() method mimics the interface of a
    Widget's render() method.
    """
    def __init__(self, render_func, rel, admin_site):
        self.render_func, self.rel = render_func, rel
        # so we can check if the related object is registered with this AdminSite
        self.admin_site = admin_site

    def __call__(self, name, value, *args, **kwargs):
        from django.conf import settings
        rel_to = self.rel.to
        related_url = '../../../%s/%s/' % (rel_to._meta.app_label, rel_to._meta.object_name.lower())
        output = [self.render_func(name, value, *args, **kwargs)]
        if rel_to in self.admin_site._registry: # If the related object has an admin interface:
            # TODO: "id_" is hard-coded here. This should instead use the correct
            # API to determine the ID dynamically.
            output.append(u'<a href="%sadd/" class="add-another" id="add_id_%s" onclick="return showAddAnotherPopup(this);"> ' % \
                (related_url, name))
            output.append(u'<img src="%simg/admin/icon_addlink.gif" width="10" height="10" alt="Add Another"/></a>' % settings.ADMIN_MEDIA_PREFIX)
        return u''.join(output)

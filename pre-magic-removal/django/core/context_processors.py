"""
A set of request processors that return dictionaries to be merged into a
template context. Each function takes the request object as its only parameter
and returns a dictionary to add to the context.

These are referenced from the setting TEMPLATE_CONTEXT_PROCESSORS and used by
DjangoContext.
"""

from django.conf.settings import DEBUG, INTERNAL_IPS, LANGUAGES, LANGUAGE_CODE

def auth(request):
    """
    Returns context variables required by apps that use Django's authentication
    system.
    """
    return {
        'user': request.user,
        'messages': request.user.get_and_delete_messages(),
        'perms': PermWrapper(request.user),
    }

def debug(request):
    "Returns context variables helpful for debugging."
    context_extras = {}
    if DEBUG and request.META.get('REMOTE_ADDR') in INTERNAL_IPS:
        context_extras['debug'] = True
        from django.core import db
        context_extras['sql_queries'] = db.db.queries
    return context_extras

def i18n(request):
    context_extras = {}
    context_extras['LANGUAGES'] = LANGUAGES
    if hasattr(request, 'LANGUAGE_CODE'):
        context_extras['LANGUAGE_CODE'] = request.LANGUAGE_CODE
    else:
        context_extras['LANGUAGE_CODE'] = LANGUAGE_CODE
    return context_extras

def request(request):
    return {'request': request}

# PermWrapper and PermLookupDict proxy the permissions system into objects that
# the template system can understand.

class PermLookupDict:
    def __init__(self, user, module_name):
        self.user, self.module_name = user, module_name
    def __repr__(self):
        return str(self.user.get_permission_list())
    def __getitem__(self, perm_name):
        return self.user.has_perm("%s.%s" % (self.module_name, perm_name))
    def __nonzero__(self):
        return self.user.has_module_perms(self.module_name)

class PermWrapper:
    def __init__(self, user):
        self.user = user
    def __getitem__(self, module_name):
        return PermLookupDict(self.user, module_name)

"""
Set of "markup" template filters for Django.  These filters transform plain text
markup syntaxes to HTML; currently there is support for:

    * Textile, which requires the PyTextile library available at
      http://dealmeida.net/projects/textile/

    * Markdown, which requires the Python-markdown library from
      http://www.freewisdom.org/projects/python-markdown

    * ReStructuredText, which requires docutils from http://docutils.sf.net/

In each case, if the required library is not installed, the filter will
silently fail and return the un-marked-up text.
"""

from django import template
from django.conf import settings
from django.utils.encoding import smart_str, force_unicode
from django.utils.safestring import mark_safe

register = template.Library()

def textile(value):
    try:
        import textile
    except ImportError:
        if settings.DEBUG:
            raise template.TemplateSyntaxError, "Error in {% textile %} filter: The Python textile library isn't installed."
        return force_unicode(value)
    else:
        return mark_safe(force_unicode(textile.textile(smart_str(value), encoding='utf-8', output='utf-8')))
textile.is_safe = True

def markdown(value, arg=''):
    """
    Runs Markdown over a given value, optionally using various
    extensions python-markdown supports.

    Syntax::

        {{ value|markdown:"extension1_name,extension2_name..." }}

    To enable safe mode, which strips raw HTML and only returns HTML
    generated by actual Markdown syntax, pass "safe" as the first
    extension in the list.

    If the version of Markdown in use does not support extensions,
    they will be silently ignored.

    """
    try:
        import markdown
    except ImportError:
        if settings.DEBUG:
            raise template.TemplateSyntaxError, "Error in {% markdown %} filter: The Python markdown library isn't installed."
        return force_unicode(value)
    else:
        # markdown.version was first added in 1.6b. The only version of markdown
        # to fully support extensions before 1.6b was the shortlived 1.6a.
        if hasattr(markdown, 'version'):
            extensions = [e for e in arg.split(",") if e]
            if len(extensions) > 0 and extensions[0] == "safe":
                extensions = extensions[1:]
                safe_mode = True
            else:
                safe_mode = False
            return mark_safe(force_unicode(markdown.markdown(smart_str(value), extensions, safe_mode=safe_mode)))
        else:
            return mark_safe(force_unicode(markdown.markdown(smart_str(value))))
markdown.is_safe = True

def restructuredtext(value):
    try:
        from docutils.core import publish_parts
    except ImportError:
        if settings.DEBUG:
            raise template.TemplateSyntaxError, "Error in {% restructuredtext %} filter: The Python docutils library isn't installed."
        return force_unicode(value)
    else:
        docutils_settings = getattr(settings, "RESTRUCTUREDTEXT_FILTER_SETTINGS", {})
        parts = publish_parts(source=smart_str(value), writer_name="html4css1", settings_overrides=docutils_settings)
        return mark_safe(force_unicode(parts["fragment"]))
restructuredtext.is_safe = True

register.filter(textile)
register.filter(markdown)
register.filter(restructuredtext)

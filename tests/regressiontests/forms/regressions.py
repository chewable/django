# -*- coding: utf-8 -*-
# Tests to prevent against recurrences of earlier bugs.

regression_tests = r"""
It should be possible to re-use attribute dictionaries (#3810)
>>> from django.newforms import *
>>> extra_attrs = {'class': 'special'}
>>> class TestForm(Form):
...     f1 = CharField(max_length=10, widget=TextInput(attrs=extra_attrs))
...     f2 = CharField(widget=TextInput(attrs=extra_attrs))
>>> TestForm(auto_id=False).as_p()
u'<p>F1: <input type="text" class="special" name="f1" maxlength="10" /></p>\n<p>F2: <input type="text" class="special" name="f2" /></p>'

#######################
# Tests for form i18n #
#######################
There were some problems with form translations in #3600

>>> from django.utils.translation import ugettext_lazy, activate, deactivate
>>> class SomeForm(Form):
...     username = CharField(max_length=10, label=ugettext_lazy('Username'))
>>> f = SomeForm()
>>> print f.as_p()
<p><label for="id_username">Username:</label> <input id="id_username" type="text" name="username" maxlength="10" /></p>

# XFAIL
# >>> activate('de')
# >>> print f.as_p()
# <p><label for="id_username">Benutzername:</label> <input id="id_username" type="text" name="username" maxlength="10" /></p>
# >>> deactivate()

Unicode decoding problems...
>>> GENDERS = ((u'\xc5', u'En tied\xe4'), (u'\xf8', u'Mies'), (u'\xdf', u'Nainen'))
>>> class SomeForm(Form):
...     somechoice = ChoiceField(choices=GENDERS, widget=RadioSelect(), label=u'\xc5\xf8\xdf')
>>> f = SomeForm()
>>> f.as_p()
u'<p><label for="id_somechoice_0">\xc5\xf8\xdf:</label> <ul>\n<li><label><input type="radio" id="id_somechoice_0" value="\xc5" name="somechoice" /> En tied\xe4</label></li>\n<li><label><input type="radio" id="id_somechoice_1" value="\xf8" name="somechoice" /> Mies</label></li>\n<li><label><input type="radio" id="id_somechoice_2" value="\xdf" name="somechoice" /> Nainen</label></li>\n</ul></p>'
"""

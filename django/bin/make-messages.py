#!/usr/bin/python

import re
import os
import sys
import getopt

basedir = None

if os.path.isdir(os.path.join('conf', 'locale')):
    basedir = os.path.abspath(os.path.join('conf', 'locale'))
elif os.path.isdir('locale'):
    basedir = os.path.abspath('locale')
else:
    print "this script should be run from the django svn tree or your project or app tree"
    sys.exit(1)

(opts, args) = getopt.getopt(sys.argv[1:], 'l:d:v')

lang = None
domain = 'django'
verbose = False

for o, v in opts:
    if o == '-l':
        lang = v
    elif o == '-d':
        domain = v
    elif o == '-v':
        verbose = True

if lang is None or domain is None:
    print "usage: make-messages.py -l <language>"
    sys.exit(1)

basedir = os.path.join(basedir, lang, 'LC_MESSAGES')
if not os.path.isdir(basedir):
    os.makedirs(basedir)

tpl_i18n_re = re.compile(r'{%\s+i18n\s+.*?%}')
tpl_value_re = re.compile(r'{{\s*_\(.*?\)\s*}}')
tpl_tag_re = re.compile(r"""{%.*_\((?:".*?")|(?:'.*?')\).*%}""")

pofile = os.path.join(basedir, '%s.po' % domain)
potfile = os.path.join(basedir, '%s.pot' % domain)

if os.path.exists(potfile):
    os.unlink(potfile)

for (dirpath, dirnames, filenames) in os.walk("."):
    for file in filenames:
        if file.endswith('.py') or file.endswith('.html'):
            thefile = file
            if file.endswith('.html'):
                src = open(os.path.join(dirpath, file), "rb").read()
                lst = []
                for match in tpl_i18n_re.findall(src):
                   lst.append(match)
                for match in tpl_value_re.findall(src):
                   lst.append(match)
                for match in tpl_tag_re.findall(src):
                   lst.append(match)
                open(os.path.join(dirpath, '%s.py' % file), "wb").write('\n'.join(lst))
                thefile = '%s.py' % file
            if verbose: sys.stdout.write('processing file %s in %s\n' % (file, dirpath))
            cmd = 'xgettext %s -d %s -L Python -o - "%s"' % (
                os.path.exists(potfile) and '--omit-header' or '', domain, os.path.join(dirpath, thefile))
            msgs = os.popen(cmd, 'r').read()
            if msgs:
                open(potfile, 'ab').write(msgs)
            if thefile != file:
                os.unlink(os.path.join(dirpath, thefile))

msgs = os.popen('msguniq %s' % potfile, 'r').read()
open(potfile, 'w').write(msgs)
if os.path.exists(pofile):
    msgs = os.popen('msgmerge %s %s' % (pofile, potfile), 'r').read()
open(pofile, 'wb').write(msgs)
os.unlink(potfile)


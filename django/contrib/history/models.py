from django.db import models
from django.db.models import signals, get_models
from django.dispatch import dispatcher
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
#from tut1.polls.models import Poll, Choice #Temp import of used models
# Misc stuff
import cPickle as Pickle
from datetime import datetime
from django.utils.text import capfirst


class ChangeLog(models.Model):
    change_time = models.DateTimeField (_('time of change'), auto_now=True)

    content_type = models.ForeignKey(ContentType)
    parent = models.GenericForeignKey()
    object_id = models.IntegerField(_('object ID'))

    user = models.ForeignKey(User, default="1")
    object = models.TextField()
    comment = models.CharField(maxlength=250, default="Bla")

    #object_type = models.CharField(maxlength=50)
    #pub_date = models.DateTimeField('date published')
    
    class Meta:
	verbose_name = _('changelog entry')
	verbose_name_plural = _('changelog entries')
	db_table = _('history_changelog')
	
    class Admin:
	fields = (
	    ('Meta info', {'fields': ('change_time', 'content_type', 'object_id', 'user', 'comment'),}),
	    ('Object', {'fields': ('object',),}),
	)

	list_display = ('object_id', 'user', 'change_time')

    def get_object(self):
	""" Returns unpickled object. """
	return Pickle.loads(self.object)

    def get_revision_number(self):
	""" Returns the ID/revision number of ChangeLog entry. """
	return self.id

#######################
# Other (API) methods #
#######################

def get_version(object, offset=0):
    """ Returns 'current-offset' revision of the 'object' """
    list = ChangeLog.objects.order_by('-id').filter(object_id=object.id)[offset]
    print list.get_object()
    return list

def list_history(parent_id, **kwargs):
    """ 
    list_history(parent_id): Returns a list of all revisions for that id.
    list_history(parent_id, offset=X): Returns a list of last X revisions.    
    """
    if kwargs:
	list = ChangeLog.objects.filter(object_id=parent_id)[:kwargs['offset']]
	return list
    else:
	return ChangeLog.objects.filter(object_id=parent_id)


def version_by_date(object, date):
    """ Returns a list of revisions made at 'date'. """
    return ChangeLog.objects.filter(object_id=object.id).filter(change_time__exact=date)


def _get_enabled_models():
    """ Returns a list of History-enabled models. """
    model_list = []
    for model in models.get_models():
	try:
	    if model.History:
		model_list.append({'module': model.__module__,
				   'name': model.__name__})
	except:
	    pass
    return model_list
	

#########################
# Pre-save signal catch #
#########################

def save_new_revision(sender, instance, signal, *args, **kwargs):
    """ Saves a old copy of the record into the History table."""
    print "Sender: ",sender

    instance_name = instance.__class__.__name__
    #print instance_name
    global m

    for model in _get_enabled_models():
	if model['name'] is instance_name:
	    try:
		m = __import__(model['module'], '', '', [model['name']])
		#print model['module'],": ",model['name'],"- ",m
	    except:
		print "Model import error."
    
    if not isinstance(sender, instance_name):
	print "Bad sender, exit."
	return 0

    old = getattr(m, model['name']).objects.filter(pk=instance.id)
    print "Old: ",old
    print "Instance: ",instance.id
    log = ChangeLog(parent=instance)
    print "Log: ",log
    log.object = Pickle.dumps(old[0], protocol=0)
    log.save()
    print "New change saved."

dispatcher.connect( save_new_revision, signal=signals.pre_save )

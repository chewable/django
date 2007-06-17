from django.core import validators
from django.core.exceptions import ImproperlyConfigured
from django.db import backend, connection, models
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
import datetime

def check_password(raw_password, enc_password):
    """
    Returns a boolean of whether the raw_password was correct. Handles
    encryption formats behind the scenes.
    """
    algo, salt, hsh = enc_password.split('$')
    if algo == 'md5':
        import md5
        return hsh == md5.new(salt+raw_password).hexdigest()
    elif algo == 'sha1':
        import sha
        return hsh == sha.new(salt+raw_password).hexdigest()
    elif algo == 'crypt':
        try:
            import crypt
        except ImportError:
            raise ValueError, "Crypt password algorithm not supported in this environment."
        return hsh == crypt.crypt(raw_password, salt)
    raise ValueError, "Got unknown password algorithm type in password."

class SiteProfileNotAvailable(Exception):
    pass

class Permission(models.Model):
    """The permissions system provides a way to assign permissions to specific users and groups of users.

    The permission system is used by the Django admin site, but may also be useful in your own code. The Django admin site uses permissions as follows:

        - The "add" permission limits the user's ability to view the "add" form and add an object.
        - The "change" permission limits a user's ability to view the change list, view the "change" form and change an object.
        - The "delete" permission limits the ability to delete an object.

    Permissions are set globally per type of object, not per specific object instance. It is possible to say "Mary may change news stories," but it's not currently possible to say "Mary may change news stories, but only the ones she created herself" or "Mary may only change news stories that have a certain status or publication date."

    Three basic permissions -- add, change and delete -- are automatically created for each Django model.
    """
    name = models.CharField(_('name'), maxlength=50)
    content_type = models.ForeignKey(ContentType)
    codename = models.CharField(_('codename'), maxlength=100)

    class Meta:
        verbose_name = _('permission')
        verbose_name_plural = _('permissions')
        unique_together = (('content_type', 'codename'),)
        ordering = ('content_type', 'codename')

    def __str__(self):
        return "%s | %s | %s" % (self.content_type.app_label, self.content_type, self.name)

class RowLevelPermissionManager(models.Manager):
    def create_row_level_permission(self, model_instance, owner, permission, negative=False):
        model_ct = ContentType.objects.get_for_model(model_instance)
        if isinstance(permission, str):
            permission = Permission.objects.get(codename=permission, content_type=model_ct.id)
        if model_ct != permission.content_type:
            raise TypeError, "Permission content type (%s) and object content type (%s) do not match" % (permission.content_type, type_ct)
        model_id = model_instance._get_pk_val()
        row_lvl_perm = self.model(model_id=model_id, model_ct=model_ct, owner_id=owner.id,
            owner_ct=ContentType.objects.get_for_model(owner),
            permission=permission, negative=negative)
        row_lvl_perm.save()
        return row_lvl_perm

    def create_default_row_permissions(self, model_instance, owner, change=True, delete=True, negChange=False, negDel=False):
        ret_dict = {}
        model_ct = ContentType.objects.get_for_model(model_instance)
        if change:
            change_str = "change_%s" % (model_ct.model)
            ret_dict[change_str] = self.create_row_level_permission(model_instance, owner, change_str, negative=negChange)
        if delete:
            delete_str = "delete_%s" % (model_ct.model)
            ret_dict[delete_str] = self.create_row_level_permission(model_instance, owner, delete_str, negative=negDel)
        return ret_dict

    def get_model_list(self, user, model, perm):
        model_ct = ContentType.objects.get_for_model(model)
        if isinstance(perm, str):
            perm = Permission.objects.get(codename__exact=perm, content_type=model_ct.id)
        user_model_ids = RowLevelPermission.objects.filter(owner_ct=ContentType.objects.get_for_model(User),
            owner_id=user.id, permission=perm.id, model_ct=model_ct).values('model_id')
        id_list = [o['model_id'] for o in user_model_ids]
        user_group_list = [g['id'] for g in user.groups.select_related().values('id')]
        if user_group_list:
            group_model_ids = RowLevelPermission.objects.filter(owner_ct=ContentType.objects.get_for_model(Group).id,
                owner_id__in=user_group_list, model_ct = model_ct).values('model_id')
            id_list = id_list + [o['model_id'] for o in group_model_ids]
        return id_list

class RowLevelPermission(models.Model):
    """
    Similiar to permissions but works on instances of objects instead of types.
    This uses generic relations to minimize the number of tables, and connects to the
    permissions table using a many to one relation.
    """
    model_id = models.PositiveIntegerField("'Model' ID")
    model_ct = models.ForeignKey(ContentType, verbose_name="'Model' content type", related_name="model_ct")
    owner_id = models.PositiveIntegerField("'Owner' ID")
    owner_ct = models.ForeignKey(ContentType, verbose_name="'Owner' content type", related_name="owner_ct")
    negative = models.BooleanField()
    permission = models.ForeignKey(Permission)
    model = generic.GenericForeignKey(fk_field='model_id', ct_field='model_ct')
    owner = generic.GenericForeignKey(fk_field='owner_id', ct_field='owner_ct')
    objects = RowLevelPermissionManager()

    class Meta:
        verbose_name = _('row level permission')
        verbose_name_plural = _('row level permissions')
        unique_together = (('model_ct', 'model_id', 'owner_id', 'owner_ct', 'permission'),)

    class Admin:
        hidden = True

    def __str__(self):
        return "%s | %s:%s | %s:%s" % (self.permission, self.owner_ct, self.owner, self.model_ct, self.model)

    def __repr__(self):
        return "%s | %s:%s | %s:%s" % (self.permission, self.owner_ct, self.owner, self.model_ct, self.model)

class Group(models.Model):
    """Groups are a generic way of categorizing users to apply permissions, or some other label, to those users. A user can belong to any number of groups.

    A user in a group automatically has all the permissions granted to that group. For example, if the group Site editors has the permission can_edit_home_page, any user in that group will have that permission.

    Beyond permissions, groups are a convenient way to categorize users to apply some label, or extended functionality, to them. For example, you could create a group 'Special users', and you could write code that would do special things to those users -- such as giving them access to a members-only portion of your site, or sending them members-only e-mail messages.
    """
    name = models.CharField(_('name'), maxlength=80, unique=True)
    permissions = models.ManyToManyField(Permission, verbose_name=_('permissions'), blank=True, filter_interface=models.HORIZONTAL)
    row_level_permissions_owned = generic.GenericRelation(RowLevelPermission, object_id_field="owner_id", content_type_field="owner_ct", related_name="group")
    class Meta:
        verbose_name = _('group')
        verbose_name_plural = _('groups')
        ordering = ('name',)

    class Admin:
        search_fields = ('name',)

    def __str__(self):
        return self.name

class UserManager(models.Manager):
    def create_user(self, username, email, password):
        "Creates and saves a User with the given username, e-mail and password."
        now = datetime.datetime.now()
        user = self.model(None, username, '', '', email.strip().lower(), 'placeholder', False, True, False, now, now)
        user.set_password(password)
        user.save()
        return user

    def make_random_password(self, length=10, allowed_chars='abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'):
        "Generates a random password with the given length and given allowed_chars"
        # Note that default value of allowed_chars does not have "I" or letters
        # that look like it -- just to avoid confusion.
        from random import choice
        return ''.join([choice(allowed_chars) for i in range(length)])

class User(models.Model):
    """Users within the Django authentication system are represented by this model.

    Username and password are required. Other fields are optional.
    """
    username = models.CharField(_('username'), maxlength=30, unique=True, validator_list=[validators.isAlphaNumeric], help_text=_("Required. 30 characters or fewer. Alphanumeric characters only (letters, digits and underscores)."))
    first_name = models.CharField(_('first name'), maxlength=30, blank=True)
    last_name = models.CharField(_('last name'), maxlength=30, blank=True)
    email = models.EmailField(_('e-mail address'), blank=True)
    password = models.CharField(_('password'), maxlength=128, help_text=_("Use '[algo]$[salt]$[hexdigest]' or use the <a href=\"password/\">change password form</a>."))
    is_staff = models.BooleanField(_('staff status'), default=False, help_text=_("Designates whether the user can log into this admin site."))
    is_active = models.BooleanField(_('active'), default=True, help_text=_("Designates whether this user can log into the Django admin. Unselect this instead of deleting accounts."))
    is_superuser = models.BooleanField(_('superuser status'), default=False, help_text=_("Designates that this user has all permissions without explicitly assigning them."))
    last_login = models.DateTimeField(_('last login'), default=datetime.datetime.now)
    date_joined = models.DateTimeField(_('date joined'), default=datetime.datetime.now)
    groups = models.ManyToManyField(Group, verbose_name=_('groups'), blank=True,
        help_text=_("In addition to the permissions manually assigned, this user will also get all permissions granted to each group he/she is in."))
    user_permissions = models.ManyToManyField(Permission, verbose_name=_('user permissions'), blank=True, filter_interface=models.HORIZONTAL)

    row_level_permissions_owned = generic.GenericRelation(RowLevelPermission, object_id_field="owner_id", content_type_field="owner_ct", related_name="owner")

    objects = UserManager()

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        ordering = ('username',)
        row_level_permissions = True

    class Admin:
        fields = (
            (None, {'fields': ('username', 'password')}),
            (_('Personal info'), {'fields': ('first_name', 'last_name', 'email')}),
            (_('Permissions'), {'fields': ('is_staff', 'is_active', 'is_superuser', 'user_permissions')}),
            (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
            (_('Groups'), {'fields': ('groups',)}),
        )
        list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff')
        list_filter = ('is_staff', 'is_superuser')
        search_fields = ('username', 'first_name', 'last_name', 'email')

    def __str__(self):
        return self.username

    def get_absolute_url(self):
        return "/users/%s/" % self.username

    def is_anonymous(self):
        "Always returns False. This is a way of comparing User objects to anonymous users."
        return False

    def is_authenticated(self):
        """Always return True. This is a way to tell if the user has been authenticated in templates.
        """
        return True

    def get_full_name(self):
        "Returns the first_name plus the last_name, with a space in between."
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def set_password(self, raw_password):
        import sha, random
        algo = 'sha1'
        salt = sha.new(str(random.random())).hexdigest()[:5]
        hsh = sha.new(salt+raw_password).hexdigest()
        self.password = '%s$%s$%s' % (algo, salt, hsh)

    def check_password(self, raw_password):
        """
        Returns a boolean of whether the raw_password was correct. Handles
        encryption formats behind the scenes.
        """
        # Backwards-compatibility check. Older passwords won't include the
        # algorithm or salt.
        if '$' not in self.password:
            import md5
            is_correct = (self.password == md5.new(raw_password).hexdigest())
            if is_correct:
                # Convert the password to the new, more secure format.
                self.set_password(raw_password)
                self.save()
            return is_correct
        return check_password(raw_password, self.password)

    def get_group_permissions(self):
        "Returns a list of permission strings that this user has through his/her groups."
        if not hasattr(self, '_group_perm_cache'):
            import sets
            cursor = connection.cursor()
            # The SQL below works out to the following, after DB quoting:
            # cursor.execute("""
            #     SELECT ct."app_label", p."codename"
            #     FROM "auth_permission" p, "auth_group_permissions" gp, "auth_user_groups" ug, "django_content_type" ct
            #     WHERE p."id" = gp."permission_id"
            #         AND gp."group_id" = ug."group_id"
            #         AND ct."id" = p."content_type_id"
            #         AND ug."user_id" = %s, [self.id])
            sql = """
                SELECT ct.%s, p.%s
                FROM %s p, %s gp, %s ug, %s ct
                WHERE p.%s = gp.%s
                    AND gp.%s = ug.%s
                    AND ct.%s = p.%s
                    AND ug.%s = %%s""" % (
                backend.quote_name('app_label'), backend.quote_name('codename'),
                backend.quote_name('auth_permission'), backend.quote_name('auth_group_permissions'),
                backend.quote_name('auth_user_groups'), backend.quote_name('django_content_type'),
                backend.quote_name('id'), backend.quote_name('permission_id'),
                backend.quote_name('group_id'), backend.quote_name('group_id'),
                backend.quote_name('id'), backend.quote_name('content_type_id'),
                backend.quote_name('user_id'),)
            cursor.execute(sql, [self.id])
            self._group_perm_cache = sets.Set(["%s.%s" % (row[0], row[1]) for row in cursor.fetchall()])
        return self._group_perm_cache

    def get_all_permissions(self):
        if not hasattr(self, '_perm_cache'):
            import sets
            self._perm_cache = sets.Set(["%s.%s" % (p.content_type.app_label, p.codename) for p in self.user_permissions.select_related()])
            self._perm_cache.update(self.get_group_permissions())
        return self._perm_cache

    def check_row_level_permission(self, permission, object):
        object_ct = ContentType.objects.get_for_model(object)
        if isinstance(permission, str):
            try:
                permission = Permission.objects.get(codename=permission, content_type=object_ct.id)
            except Permission.DoesNotExist:
                return False
        try:
            model_id = object._get_pk_val()
            row_level_perm = self.row_level_permissions_owned.get(model_id=model_id,
                model_ct=object_ct.id, permission=permission.id)
        except RowLevelPermission.DoesNotExist:
            return self.check_group_row_level_permissions(permission, object)
        return not row_level_perm.negative

    def check_group_row_level_permissions(self, permission, object):
        model_id = object._get_pk_val()
        cursor = connection.cursor()
        sql = """
            SELECT rlp.%s
            FROM %s ug, %s rlp
            WHERE rlp.%s = ug.%s
                AND ug.%s=%%s
                AND rlp.%s=%%s
                AND rlp.%s=%%s
                AND rlp.%s=%%s
                AND rlp.%s=%%s
                ORDER BY rlp.%s""" % (
            backend.quote_name('negative'), backend.quote_name('auth_user_groups'),
            backend.quote_name('auth_rowlevelpermission'), backend.quote_name('owner_id'),
            backend.quote_name('group_id'), backend.quote_name('user_id'),
            backend.quote_name('owner_ct_id'), backend.quote_name('model_id'),
            backend.quote_name('model_ct_id'), backend.quote_name('permission_id'),
            backend.quote_name('negative'))
        cursor.execute(sql, [self.id,
                             ContentType.objects.get_for_model(Group).id,
                             model_id,
                             ContentType.objects.get_for_model(object).id,
                             permission.id,])
        row = cursor.fetchone()
        if row is None:
            return None
        return not row[0]

    def has_perm(self, perm, object=None):
        "Returns True if the user has the specified permission."
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        if object and object._meta.row_level_permissions:
            # Since we use the content type for row level perms, we don't need the application name.
            permission_str = perm[perm.index('.')+1:]
            row_level_permission = self.check_row_level_permission(permission_str, object)
            if row_level_permission is not None:
                return row_level_permission
        return perm in self.get_all_permissions()

    def has_perms(self, perm_list):
        "Returns True if the user has each of the specified permissions."
        for perm in perm_list:
            if not self.has_perm(perm):
                return False
        return True

    def contains_permission(self, perm, model=None):
        """
        This checks if the user has the given permission for any instance
        of the given model.
        """
        if self.has_perm(perm):
            return True
        if model and model._meta.row_level_permissions:
            perm = perm[perm.index('.')+1:]
            return self.contains_row_level_perm(perm, model)
        return False

    def contains_row_level_perm(self, perm, model):
        model_ct = ContentType.objects.get_for_model(model)
        if isinstance(perm, str):
            permission = Permission.objects.get(codename__exact=perm, content_type=model_ct.id)
        else:
            permission = perm
        count = self.row_level_permissions_owned.filter(model_ct=model_ct.id, permission=permission.id).count()
        if count > 0:
            return True
        return self.contains_group_row_level_perms(permission, model_ct)

    def contains_group_row_level_perms(self, perm, ct):
        cursor = connection.cursor()
        sql = """
            SELECT COUNT(*)
            FROM %s ug, %s rlp, %s ct
            WHERE rlp.%s = ug.%s
                AND ug.%s=%%s
                AND rlp.%s = %%s
                AND rlp.%s = %%s
                AND rlp.%s = %%s
                AND rlp.%s = %%s""" % (
            backend.quote_name('auth_user_groups'), backend.quote_name('auth_rowlevelpermission'),
            backend.quote_name('django_content_type'), backend.quote_name('owner_id'),
            backend.quote_name('group_id'), backend.quote_name('user_id'),
            backend.quote_name('negative'),  backend.quote_name('owner_ct_id'),
            backend.quote_name('model_ct_id'), backend.quote_name('permission_id'))
        cursor.execute(sql, [self.id, False, ContentType.objects.get_for_model(Group).id, ct.id, perm.id])
        count = int(cursor.fetchone()[0])
        return count > 0

    def has_module_perms(self, app_label):
        "Returns True if the user has any permissions in the given app label."
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        if [p for p in self.get_all_permissions() if p[:p.index('.')] == app_label]:
            return True
        return self.has_module_row_level_perms(app_label)

    def has_module_row_level_perms(self, app_label):
        cursor = connection.cursor()
        sql = """
            SELECT COUNT(*)
            FROM %s ct, %s rlp
            WHERE rlp.%s = ct.%s
                AND ct.%s=%%s
                AND rlp.%s = %%s
                AND rlp.%s = %%s
                AND rlp.%s = %%s
                """ % (
            backend.quote_name('django_content_type'), backend.quote_name('auth_rowlevelpermission'),
            backend.quote_name('model_ct_id'), backend.quote_name('id'),
            backend.quote_name('app_label'),
            backend.quote_name('owner_ct_id'),
            backend.quote_name('owner_id'),backend.quote_name('negative'), )
        cursor.execute(sql, [app_label, ContentType.objects.get_for_model(User).id, self.id, False])
        count = int(cursor.fetchone()[0])
        if count > 0:
            return True
        return self.has_module_group_row_level_perms(app_label)

    def has_module_group_row_level_perms(self, app_label):
        cursor = connection.cursor()
        sql = """
            SELECT COUNT(*)
            FROM %s ug, %s rlp, %s ct
            WHERE rlp.%s = ug.%s
                AND ug.%s=%%s
                AND rlp.%s = ct.%s
                AND ct.%s=%%s
                AND rlp.%s = %%s
                AND rlp.%s = %%s""" % (
            backend.quote_name('auth_user_groups'), backend.quote_name('auth_rowlevelpermission'),
            backend.quote_name('django_content_type'), backend.quote_name('owner_id'),
            backend.quote_name('group_id'), backend.quote_name('user_id'),
            backend.quote_name('model_ct_id'), backend.quote_name('id'),
            backend.quote_name('app_label'), backend.quote_name('negative'),
            backend.quote_name('owner_ct_id'))
        cursor.execute(sql, [self.id, app_label, False, ContentType.objects.get_for_model(Group).id])
        count = int(cursor.fetchone()[0])
        return (count>0)

    def get_and_delete_messages(self):
        messages = []
        for m in self.message_set.all():
            messages.append(m.message)
            m.delete()
        return messages

    def email_user(self, subject, message, from_email=None):
        "Sends an e-mail to this User."
        from django.core.mail import send_mail
        send_mail(subject, message, from_email, [self.email])

    def get_profile(self):
        """
        Returns site-specific profile for this user. Raises
        SiteProfileNotAvailable if this site does not allow profiles.
        """
        if not hasattr(self, '_profile_cache'):
            from django.conf import settings
            if not settings.AUTH_PROFILE_MODULE:
                raise SiteProfileNotAvailable
            try:
                app_label, model_name = settings.AUTH_PROFILE_MODULE.split('.')
                model = models.get_model(app_label, model_name)
                self._profile_cache = model._default_manager.get(user__id__exact=self.id)
            except (ImportError, ImproperlyConfigured):
                raise SiteProfileNotAvailable
        return self._profile_cache

class Message(models.Model):
    """The message system is a lightweight way to queue messages for given users. A message is associated with a User instance (so it is only applicable for registered users). There's no concept of expiration or timestamps. Messages are created by the Django admin after successful actions. For example, "The poll Foo was created successfully." is a message.
    """
    user = models.ForeignKey(User)
    message = models.TextField(_('message'))

    def __str__(self):
        return self.message

class AnonymousUser(object):
    id = None
    username = ''

    def __init__(self):
        pass

    def __str__(self):
        return _('AnonymousUser')

    def __eq__(self, other):
        return isinstance(other, self.__class__)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return 1 # instances always return the same hash value

    def save(self):
        raise NotImplementedError

    def delete(self):
        raise NotImplementedError

    def set_password(self, raw_password):
        raise NotImplementedError

    def check_password(self, raw_password):
        raise NotImplementedError

    def _get_groups(self):
        raise NotImplementedError
    groups = property(_get_groups)

    def _get_user_permissions(self):
        raise NotImplementedError
    user_permissions = property(_get_user_permissions)

    def has_perm(self, perm, object=None):
        return False

    def has_module_perms(self, module):
        return False

    def contains_permission(self, perm, model=None):
        return False

    def get_and_delete_messages(self):
        return []

    def is_anonymous(self):
        return True

    def is_authenticated(self):
        return False

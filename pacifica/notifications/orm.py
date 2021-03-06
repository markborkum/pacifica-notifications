#!/usr/bin/python
# -*- coding: utf-8 -*-
"""The ORM module defining the SQL model for notifications."""
import uuid
from time import sleep
from datetime import datetime
from json import loads
from peewee import Model, CharField, TextField, DateTimeField, UUIDField, OperationalError, IntegerField
from playhouse.db_url import connect
from .config import get_config
from .jsonpath import parse

SCHEMA_MAJOR = 1
SCHEMA_MINOR = 0
DB = connect(get_config().get('database', 'peewee_url'))


class OrmSync(object):
    """
    Special module for syncing the orm.

    This module should incorporate a schema migration strategy.

    The supported versions migrating forward must be in a versions array
    containing tuples for major and minor versions.

    The version tuples are directly translated to method names in the
    orm_update class for the update between those versions.

    Example Version Control::

      class orm_update:
        versions = [
          (0, 1),
          (0, 2),
          (1, 0),
          (1, 1)
        ]

        def update_0_1_to_0_2():
            pass
        def update_0_2_to_1_0():
            pass

    The body of the update should follow peewee migration practices.
    http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#migrate
    """

    versions = [
        (0, 0),
        (1, 0)
    ]

    @staticmethod
    def dbconn_blocking():
        """Wait for the db connection."""
        dbcon_attempts = get_config().getint('database', 'connect_attempts')
        dbcon_wait = get_config().getint('database', 'connect_wait')
        while dbcon_attempts:
            try:
                EventMatch.database_connect()
                return
            except OperationalError:
                # couldnt connect, potentially wait and try again
                sleep(dbcon_wait)
                dbcon_attempts -= 1
        raise OperationalError('Failed database connect retry.')

    @classmethod
    def update_0_0_to_1_0(cls):
        """Update by adding the boolean column."""
        if not EventMatch.table_exists():
            EventMatch.create_table()

    @classmethod
    def update_tables(cls):
        """Update the database to the current version."""
        verlist = cls.versions
        db_ver = NotificationSystem.get_version()
        if verlist.index(verlist[-1]) == verlist.index(db_ver):
            # we have the current version don't update
            return
        with EventMatch.atomic():
            for db_ver in verlist[verlist.index(db_ver):-1]:
                next_db_ver = verlist[verlist.index(db_ver)+1]
                method_name = 'update_{}_to_{}'.format(
                    '{}_{}'.format(*db_ver),
                    '{}_{}'.format(*next_db_ver)
                )
                getattr(cls, method_name)()
            NotificationSystem.drop_table()
            NotificationSystem.create_table()
            NotificationSystem.get_or_create_version()


# pylint: disable=too-few-public-methods
class BaseModel(Model):
    """Auto-generated by pwiz."""

    class Meta(object):
        """Map to the database connected above."""

        database = DB

    @classmethod
    def database_connect(cls):
        """
        Make sure database is connected.

        Trying to connect a second
        time *does* cause problems.
        """
        # pylint: disable=no-member
        if not cls._meta.database.is_closed():
            cls._meta.database.close()
        cls._meta.database.connect()
        # pylint: enable=no-member

    @classmethod
    def database_close(cls):
        """
        Close the database connection.

        Closing already closed database
        is not a problem, so continue on.
        """
        # pylint: disable=no-member
        if not cls._meta.database.is_closed():
            cls._meta.database.close()
        # pylint: enable=no-member

    @classmethod
    def atomic(cls):
        """Do the database atomic action."""
        return cls._meta.database.atomic()


class NotificationSystem(BaseModel):
    """Notification Schema Version Model."""

    part = CharField(primary_key=True)
    value = IntegerField(default=-1)

    @classmethod
    def get_or_create_version(cls):
        """Set or create the current version of the schema."""
        if not cls.table_exists():
            return (0, 0)
        major = cls.get_or_create(part='major', value=SCHEMA_MAJOR)
        minor = cls.get_or_create(part='minor', value=SCHEMA_MINOR)
        return (major, minor)

    @classmethod
    def get_version(cls):
        """Get the current version as a tuple."""
        if not cls.table_exists():
            return (0, 0)
        return (cls.get(part='major').value, cls.get(part='minor').value)

    @classmethod
    def is_equal(cls):
        """Check to see if schema version matches code version."""
        major, minor = cls.get_version()
        return major == SCHEMA_MAJOR and minor == SCHEMA_MINOR

    @classmethod
    def is_safe(cls):
        """Check to see if the schema version is safe for the code."""
        major, _minor = cls.get_version()
        return major == SCHEMA_MAJOR


class EventMatch(BaseModel):
    """Events matching via jsonpath per user."""

    uuid = UUIDField(primary_key=True, default=uuid.uuid4, index=True)
    name = CharField(index=True)
    jsonpath = TextField()
    user = CharField(index=True)
    disabled = DateTimeField(index=True, null=True, default=None)
    error = TextField(null=True)
    target_url = TextField()
    version = CharField(default='v0.1')
    # JSONField is extension specific and we are using URLs to bind
    # to a database backend
    extensions = TextField(default='{}')
    created = DateTimeField(default=datetime.now, index=True)
    updated = DateTimeField(default=datetime.now, index=True)
    deleted = DateTimeField(null=True, index=True)

    # pylint: disable=too-few-public-methods
    class Meta(object):
        """The meta class that contains db connection."""

        database = DB
    # pylint: enable=too-few-public-methods

    def validate_jsonpath(self):
        """Validate the jsonpath string."""
        parse(self.jsonpath)
        return True

    def to_hash(self):
        """Convert the object to a json serializable hash."""
        ret_obj = {}
        for field_name in self._meta.sorted_field_names:
            ret_obj[field_name] = getattr(self, field_name)
        ret_obj['uuid'] = str(ret_obj['uuid'])
        ret_obj['extensions'] = loads(ret_obj['extensions'])
        for dt_element in ['disabled', 'deleted', 'updated', 'created']:
            if getattr(self, dt_element):
                # pylint: disable=no-member
                ret_obj[dt_element] = getattr(self, dt_element).isoformat()
                # pylint: enable=no-member
        return ret_obj

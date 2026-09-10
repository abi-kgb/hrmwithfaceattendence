import os

try:
    import pymysql
    pymysql.install_as_MySQLdb()

    # Bypass strict database version checks for XAMPP's MariaDB version
    from django.db.backends.base.base import BaseDatabaseWrapper
    BaseDatabaseWrapper.check_database_version_supported = lambda self: None

    # Disable RETURNING clause for MariaDB 10.4 compatibility
    from django.db.backends.mysql.features import DatabaseFeatures
    DatabaseFeatures.can_return_columns_from_insert = property(lambda self: False)
    DatabaseFeatures.can_return_rows_from_bulk_insert = property(lambda self: False)
except ImportError:
    pass





from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myhrm.settings')

application = get_wsgi_application()

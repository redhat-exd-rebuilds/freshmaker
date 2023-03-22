========================
Freshmaker database
========================

Freshmaker as an SQL toolkit uses SQLAlchemy extension for `Flask <https://flask-sqlalchemy.palletsprojects.com/en/2.x/>`_. So whenever you want to add some columns or tables you should at least check ``models.py`` file. Every class that has a **FreshmakerBase** as a parent is actually a table with its own columns, relationships etc.

As for database management system, we are using `PostgreSQL <https://www.postgresql.org/>`_ in deployments and `SQLite <https://www.sqlite.org/index.html>`_ in local environment.
And besides that for testing we are using *in-memory* database, so whenever you are running tests from ``tests/`` folder, new database is created and live while tests are running.


Setting up Database
============================
When you for the first time want to create freshmaker database, you are supposed to run:

.. sourcecode:: none

    ./manager createdb

This command will create new ``freshmaker.db`` file for local use for you.


Database update
========================

When some changes are applied to database scheme, like changing ``models.py``, you should generate  migration file for a new database scheme by running:

.. sourcecode:: none

    ./manager db migrate

After that you can apply that migration by running:

.. sourcecode:: none

    ./manager db upgrade

After that all changes should be already applied to your local database.


Querying database
==========================

You can query your locally created database by running something like this in the directory with database file:

.. sourcecode:: none

    sqlite3 freshmaker.db 'SELECT id FROM artifact_builds;'




Database Migrations
=============================

Migration is similar to `Cachito <https://github.com/release-engineering/cachito>`_.
Follow the steps below for database data and/or schema migrations:

* Checkout the main branch and ensure no schema changes are present in ``freshmaker/models.py``

* Set ``SQLALCHEMY_DATABASE_URI`` to ``sqlite:///*path-to-your-freshmaker.db*`` in used configuration file.

* Run ``./manager db upgrade`` which will create an empty database in the root of your Git repository

  called ``freshmaker.db`` with the current schema applied

* Checkout a new branch where the changes are to be made

* In case of schema changes,

  * Apply any schema changes to ``freshmaker/models.py``

  * Run ``./manager db migrate`` which will autogenerate a migration script in

    ``freshmaker/migrations/versions``

* In case of no schema changes,

  * Run ``./manager db revision`` to create an empty migration script file

* Rename the migration script so that the suffix has a description of the change

* Modify the docstring of the migration script

* For data migrations, define the schema of any tables you will be modifying. This is so that it

  captures the schema of the time of the migration and not necessarily what is in models.py since

  that reflects the latest schema.

* Modify the ``upgrade`` function to make the adjustments as necessary

* Modify the ``downgrade`` function to reverse the changes that were made in the ``upgrade`` function

* Make any adjustments to the migration script as necessary

* To test the migration script,

  * Populate the database with some dummy data as per the requirement

  * Run ``./manager db upgrade``

  * Also test the downgrade by running ``./manager db downgrade <previous revision>``

    (where previous revision is the revision ID of the previous migration script)

* Remove the configuration of ``SQLALCHEMY_DATABASE_URI`` that you set earlier

* Remove ``freshmaker.db``

* Commit your changes

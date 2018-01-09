.. image:: https://travis-ci.org/Kentzo/async_app.svg?branch=master
    :target: https://travis-ci.org/Kentzo/async_app
    :alt: Travis
.. image:: https://ci.appveyor.com/api/projects/status/abqxn2vbk5k2styb/branch/master?svg=true
    :target: https://ci.appveyor.com/project/Kentzo/async-app
    :alt: AppVeyor
.. image:: https://codecov.io/gh/Kentzo/async_app/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/Kentzo/async_app
    :alt: Coverage
.. image:: https://pyup.io/repos/github/Kentzo/async_app/shield.svg
    :target: https://pyup.io/repos/github/Kentzo/async_app/
    :alt: Updates
.. image:: https://pyup.io/repos/github/Kentzo/async_app/python-3-shield.svg
    :target: https://pyup.io/repos/github/Kentzo/async_app/
    :alt: Python 3
.. image:: https://img.shields.io/pypi/v/async_app.svg
    :target: https://pypi.python.org/pypi/async_app
    :alt: PyPI

Key Features
============

- Service-oriented application layout
- Integrate different asyncio libraries with ease
- `typing-friendly <https://docs.python.org/3/library/typing.html>`_ Config that can enforce types (via `typeguard <typeguard>`_ or `pytypes <pytypes>`_)


Development
===========

requirements.txt lists all dependencies needed to run tests and generate reports.

CI tests each change against latest release of CPython 3 (Windows and macOS) as well as dev (macOS and Ubuntu)
and nightly builds (Ubuntu).
Tests are run against both pytypes and typeguard. Combined coverage is uploaded to PyPI.
See `.travis.yml <.travis.yml>`_, `.appveyor.yml <.appveyor.yml>`_ and `setup.cfg <setup.cfg>`_
for the detailed configuration.

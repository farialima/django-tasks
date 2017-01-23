#/usr/bin/env python
# coding: utf-8

from setuptools import setup, find_packages

setup(
    name = "djangotasks",
    description = "Long-running task queue for Django",
    author = "Francois Granade",
    author_email = "djangotasks@farialima.net",
    url = "https://github.com/farialima/django-tasks",
    version = "0.95",
    packages = find_packages(),
    include_package_data = True,
    zip_safe = False,
    classifiers = [
        "Programming Language :: Python",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Framework :: Django",
        "Intended Audience :: Developers",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)

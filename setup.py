# -*- coding: utf-8 -*-

from setuptools import setup, find_packages


with open("README.md") as f:
    readme = f.read()

with open("LICENSE") as f:
    license = f.read()

setup(
    name="verified_agile_hardware",
    version="0.1.0",
    description="Translation validation for agile hardware development",
    long_description=readme,
    author="Jackson Melchert",
    author_email="melchert@stanford.edu",
    url="https://github.com/jack-melchert/verified_agile_hardware",
    license=license,
    packages=find_packages(exclude=("tests", "docs")),
)

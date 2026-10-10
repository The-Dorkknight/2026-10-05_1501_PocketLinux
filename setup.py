# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
from setuptools import setup

setup(
    name="pocketlinux",
    version="0.3.0",  # PEP 440; the app reports 0.3.0-wip
    description="Tiny isolated Linux console in a Windows folder (WSL based). Work in progress.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Matthew Armstrong",
    author_email="The-Dorkknight@users.noreply.github.com",
    url="https://github.com/The-Dorkknight/pocketlinux",
    license="PolyForm-Noncommercial-1.0.0",
    package_dir={"": "src"},
    py_modules=["backend", "main"],
    python_requires=">=3.8",
    entry_points={"gui_scripts": ["pocketlinux = main:main"]},
    classifiers=["Operating System :: Microsoft :: Windows", "Development Status :: 2 - Pre-Alpha"],
)
